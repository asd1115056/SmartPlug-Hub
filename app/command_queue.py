"""Per-device command queue with deduplication, rate limiting, and session timeout."""

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from .core import (
    DeviceBackend, DeviceConfig, DeviceOfflineError, DeviceRejectedError, DeviceState,
)

logger = logging.getLogger(__name__)

Action = Callable[[DeviceBackend, DeviceConfig], Awaitable[Any]]


@dataclass
class Command:
    action: Action
    future: asyncio.Future[Any]
    dedup_key: tuple[str | None, bool] | None


class DeviceQueue:
    """Serializes commands for one device; manages the backend TCP session lifecycle."""

    def __init__(self, device_id: str, backend: DeviceBackend, config: DeviceConfig) -> None:
        self._device_id = device_id
        self._backend = backend
        self._config = config
        self._queue: asyncio.Queue[Command] = asyncio.Queue()
        self._pending: list[Command] = []
        self._processor: asyncio.Task[None] | None = None
        self._executing: bool = False
        self._last_cmd_time: float = 0.0

    def submit(self, outlet_id: str | None, on: bool) -> asyncio.Future[DeviceState]:
        """Enqueue a power command and return a future. Deduplicates identical pending commands."""
        dedup_key = (outlet_id, on)
        for cmd in self._pending:
            if cmd.dedup_key == dedup_key:
                return cmd.future

        async def action(backend: DeviceBackend, config: DeviceConfig) -> DeviceState:
            await backend.set_power(config, outlet_id, on)
            return await backend.probe(config)

        logger.debug("[%s] command queued outlet=%s on=%s", self._device_id, outlet_id, on)
        return self._enqueue(action, dedup_key)

    def run(self, action: Action) -> asyncio.Future[Any]:
        """Enqueue an arbitrary backend operation, serialized against power commands and polling."""
        logger.debug("[%s] operation queued", self._device_id)
        return self._enqueue(action, dedup_key=None)

    def _enqueue(
        self, action: Action, dedup_key: tuple[str | None, bool] | None,
    ) -> asyncio.Future[Any]:
        future: asyncio.Future[Any] = asyncio.get_running_loop().create_future()
        cmd = Command(action=action, future=future, dedup_key=dedup_key)
        self._pending.append(cmd)
        self._queue.put_nowait(cmd)

        if self._processor is None or self._processor.done():
            self._processor = asyncio.create_task(self._run())
            logger.debug("[%s] processor started", self._device_id)

        return future

    def is_active(self) -> bool:
        """True while a command is actively executing (not just idle session hold)."""
        return self._executing

    async def close(self) -> None:
        """Cancel the processor and close the backend connection."""
        if self._processor and not self._processor.done():
            self._processor.cancel()
            try:
                await self._processor
            except asyncio.CancelledError:
                pass

    # ── Processor ─────────────────────────────────────────────────────────────

    async def _run(self) -> None:
        logger.debug(
            "[%s] processor running (session_timeout=%.0fs)",
            self._device_id, self._backend.session_timeout,
        )
        try:
            while True:
                cmd = await self._next_command()
                if cmd is None:
                    break   # session idle timeout or empty stateless queue

                try:
                    self._pending.remove(cmd)
                except ValueError:
                    pass

                await self._rate_limit()
                await self._execute(cmd)

        finally:
            await self._backend.close()
            logger.debug("[%s] processor exited", self._device_id)

            # Restart if commands arrived during teardown
            if not self._queue.empty():
                logger.debug("[%s] commands pending — restarting processor", self._device_id)
                self._processor = asyncio.create_task(self._run())

    async def _next_command(self) -> Command | None:
        timeout = self._backend.session_timeout
        if timeout > 0:
            # Stateful (Kasa): hold session open waiting for next command
            try:
                return await asyncio.wait_for(self._queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                logger.debug(
                    "[%s] session idle after %.0fs — closing",
                    self._device_id, self._backend.session_timeout,
                )
                return None
        else:
            # Stateless (MiIO): drain queue immediately then exit
            try:
                return self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return None

    async def _execute(self, cmd: Command) -> None:
        logger.debug("[%s] executing command", self._device_id)
        self._executing = True
        try:
            result = await cmd.action(self._backend, self._config)
            if not cmd.future.done():
                cmd.future.set_result(result)
            logger.debug("[%s] command completed", self._device_id)
        except asyncio.CancelledError:
            logger.info("[%s] command cancelled — connection closed underneath it", self._device_id)
            if not cmd.future.done():
                cmd.future.cancel()
            raise
        except DeviceOfflineError as e:
            logger.info("[%s] device offline: %s", self._device_id, e)
            if not cmd.future.done():
                cmd.future.set_exception(e)
        except DeviceRejectedError as e:
            logger.info("[%s] device rejected command: %s", self._device_id, e)
            if not cmd.future.done():
                cmd.future.set_exception(e)
        except ValueError as e:
            if not cmd.future.done():
                cmd.future.set_exception(e)
        except Exception as e:
            logger.exception("[%s] unexpected error executing command", self._device_id)
            if not cmd.future.done():
                cmd.future.set_exception(e)
        finally:
            self._executing = False

    async def _rate_limit(self) -> None:
        interval = self._backend.command_interval
        if not interval:
            return
        wait = interval - (time.monotonic() - self._last_cmd_time)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_cmd_time = time.monotonic()

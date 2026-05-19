"""Per-device command queue with deduplication, rate limiting, and session timeout."""

import asyncio
import logging
import time
from dataclasses import dataclass

from .core import DeviceBackend, DeviceConfig, DeviceOfflineError, DeviceState

logger = logging.getLogger(__name__)


@dataclass
class Command:
    outlet_id: str | None
    on: bool
    future: asyncio.Future[DeviceState]


class DeviceQueue:
    """Serializes commands for one device; manages the backend TCP session lifecycle."""

    def __init__(self, device_id: str, backend: DeviceBackend, config: DeviceConfig) -> None:
        self._device_id = device_id
        self._backend = backend
        self._config = config
        self._queue: asyncio.Queue[Command] = asyncio.Queue()
        self._pending: list[Command] = []
        self._processor: asyncio.Task[None] | None = None
        self._last_cmd_time: float = 0.0

    def submit(self, outlet_id: str | None, on: bool) -> asyncio.Future[DeviceState]:
        """Enqueue a command and return a future. Deduplicates identical pending commands."""
        for cmd in self._pending:
            if cmd.outlet_id == outlet_id and cmd.on == on:
                return cmd.future

        future: asyncio.Future[DeviceState] = asyncio.get_running_loop().create_future()
        cmd = Command(outlet_id=outlet_id, on=on, future=future)
        self._pending.append(cmd)
        self._queue.put_nowait(cmd)
        logger.debug("[%s] command queued outlet=%s on=%s", self._device_id, outlet_id, on)

        if self._processor is None or self._processor.done():
            self._processor = asyncio.create_task(self._run())
            logger.debug("[%s] processor started", self._device_id)

        return future

    def is_active(self) -> bool:
        """True while the processor task is running (TCP session is held open)."""
        return self._processor is not None and not self._processor.done()

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
        logger.debug("[%s] processor running (session_timeout=%.0fs)", self._device_id, self._backend.session_timeout)
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
                logger.debug("[%s] session idle after %.0fs — closing", self._device_id, self._backend.session_timeout)
                return None
        else:
            # Stateless (MiIO): drain queue immediately then exit
            try:
                return self._queue.get_nowait()
            except asyncio.QueueEmpty:
                return None

    async def _execute(self, cmd: Command) -> None:
        logger.debug("[%s] executing outlet=%s on=%s", self._device_id, cmd.outlet_id, cmd.on)
        try:
            await self._backend.set_power(self._config, cmd.outlet_id, cmd.on)
            state = await self._backend.probe(self._config)
            if not cmd.future.done():
                cmd.future.set_result(state)
            logger.debug("[%s] command completed", self._device_id)
        except DeviceOfflineError as e:
            logger.info("[%s] device offline: %s", self._device_id, e)
            if not cmd.future.done():
                cmd.future.set_exception(e)
        except Exception as e:
            logger.exception("[%s] unexpected error executing command", self._device_id)
            if not cmd.future.done():
                cmd.future.set_exception(e)

    async def _rate_limit(self) -> None:
        interval = self._backend.command_interval
        if not interval:
            return
        wait = interval - (time.monotonic() - self._last_cmd_time)
        if wait > 0:
            await asyncio.sleep(wait)
        self._last_cmd_time = time.monotonic()

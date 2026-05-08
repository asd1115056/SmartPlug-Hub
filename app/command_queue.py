"""Protocol-agnostic per-device command queue."""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from datetime import datetime

from .config import ConfigManager
from .models import (
    Command,
    CommandStatus,
    DeviceBackend,
    DeviceOfflineError,
    DeviceState,
)

logger = logging.getLogger(__name__)


class CommandQueue:
    """Per-device command queue. Delegates execution to DeviceBackend."""

    def __init__(
        self,
        config: ConfigManager,
        backends: dict[str, DeviceBackend],
        on_state_update: Callable[[str, DeviceState | None], None],
    ) -> None:
        self._config = config
        self._backends = backends
        self._on_state_update = on_state_update

        self._queues: dict[str, asyncio.Queue[Command]] = {}
        self._processors: dict[str, asyncio.Task] = {}
        self._last_command_time: dict[str, float] = {}

    def submit(self, command: Command) -> Command:
        """Submit a command, returning the canonical Command (may be deduplicated).

        If an identical command (same device, action, child_id) is already QUEUED,
        the existing one is returned so callers share the same completion event.
        """
        device_id = command.device_id

        if device_id not in self._queues:
            self._queues[device_id] = asyncio.Queue()

        queue = self._queues[device_id]

        for existing in queue._queue:
            if (
                existing.status == CommandStatus.QUEUED
                and existing.device_id == device_id
                and existing.child_id == command.child_id
                and existing.action == command.action
            ):
                logger.debug(
                    f"Dedup: reusing command {existing.id} for {device_id} "
                    f"action={command.action} child={command.child_id}"
                )
                return existing

        queue.put_nowait(command)

        if device_id not in self._processors or self._processors[device_id].done():
            self._processors[device_id] = asyncio.create_task(
                self._process_queue(device_id)
            )

        return command

    async def wait_for_command(
        self, command: Command, timeout: float = 30.0
    ) -> Command:
        """Wait for a command to complete."""
        try:
            await asyncio.wait_for(command._event.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            command.status = CommandStatus.FAILED
            command.error = "Command timed out"
            command._event.set()
        return command

    def has_active_processor(self, device_id: str) -> bool:
        """Return True if a processor task is currently running for this device."""
        task = self._processors.get(device_id)
        return task is not None and not task.done()

    async def shutdown(self) -> None:
        """Cancel all processor tasks."""
        for task in self._processors.values():
            task.cancel()

        for task in self._processors.values():
            try:
                await task
            except asyncio.CancelledError:
                pass

        self._processors.clear()
        self._queues.clear()

    async def _process_queue(self, device_id: str) -> None:
        """Command processing loop for a single device."""
        queue = self._queues[device_id]

        mac = self._config.resolve_id(device_id)
        if not mac:
            logger.error(f"Processor: unknown device_id {device_id}")
            self._processors.pop(device_id, None)
            return

        cfg = self._config.whitelist[mac]
        backend = self._backends.get(device_id)
        if not backend:
            logger.error(f"Processor: no backend registered for device_id {device_id}")
            self._processors.pop(device_id, None)
            return

        # session_timeout=0 means stateless (e.g. MiIO): exit after each command.
        # session_timeout>0 means keep-alive (e.g. Kasa TCP): wait for more commands.
        timeout = backend.session_timeout if backend.session_timeout > 0 else None

        try:
            while True:
                try:
                    cmd = await asyncio.wait_for(queue.get(), timeout=timeout)
                except asyncio.TimeoutError:
                    logger.info(f"Idle timeout for {cfg.name}, processor exiting")
                    break

                cmd.status = CommandStatus.PROCESSING
                await self._wait_for_rate_limit(device_id, backend.command_interval)

                try:
                    state = await backend.execute_command(cmd, cfg)
                    cmd.status = CommandStatus.COMPLETED
                    cmd.completed_at = datetime.now()
                    cmd.result = state
                    self._on_state_update(device_id, state)
                except DeviceOfflineError as e:
                    cmd.status = CommandStatus.FAILED
                    cmd.error = str(e)
                    self._on_state_update(device_id, None)
                except Exception as e:
                    cmd.status = CommandStatus.FAILED
                    cmd.error = str(e)
                    logger.error(f"Unexpected error processing command for {cfg.name}: {e}")
                finally:
                    cmd._event.set()

                if not backend.session_timeout:
                    break  # stateless: exit so the next command starts a fresh processor
        finally:
            await backend.cleanup(device_id)
            self._processors.pop(device_id, None)

    async def _wait_for_rate_limit(self, device_id: str, interval: float) -> None:
        if not interval:
            return
        now = time.monotonic()
        elapsed = now - self._last_command_time.get(device_id, 0)
        if elapsed < interval:
            await asyncio.sleep(interval - elapsed)
        self._last_command_time[device_id] = time.monotonic()


def make_command(
    device_id: str, action: str, child_id: str | None = None
) -> Command:
    """Create a new Command with a unique ID."""
    return Command(
        id=uuid.uuid4().hex[:8],
        device_id=device_id,
        action=action,
        child_id=child_id,
    )

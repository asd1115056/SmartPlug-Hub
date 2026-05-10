"""Thin facade combining ConfigManager + CommandQueue with a device state cache."""

import asyncio
import logging
from pathlib import Path

from .command_queue import CommandQueue, make_command
from .config import ConfigManager
from .models import (
    CommandStatus,
    DeviceBackend,
    DeviceOfflineError,
    DeviceOperationError,
    DeviceState,
    build_offline_state,
)
from .registry import PROTOCOLS

logger = logging.getLogger(__name__)

HEALTH_CHECK_INTERVAL = 60


class DeviceManager:
    """Combines ConfigManager + CommandQueue. Manages state cache."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config = ConfigManager(config_dir)
        self._ip_cache: dict[str, str] = {}
        self._states: dict[str, DeviceState] = {}
        self._backends: dict[str, DeviceBackend] = {}
        self._queue: CommandQueue | None = None
        self._health_task: asyncio.Task | None = None

    async def initialize(self) -> None:
        """Load config -> register backends -> discover -> build initial state cache."""
        self._config.load()

        for type_name, spec in PROTOCOLS.items():
            sub_devices = {
                mac: info
                for mac, info in self._config.devices.items()
                if isinstance(info, spec.model)
            }
            if not sub_devices:
                continue

            backend = spec.backend(self._ip_cache)
            for cfg in sub_devices.values():
                self._backends[cfg.id] = backend

            self._ip_cache.update(await spec.discover(sub_devices))

            for cfg in sub_devices.values():
                self._states[cfg.id] = await backend.refresh(cfg)

        self._queue = CommandQueue(
            config=self._config,
            backends=self._backends,
            on_state_update=self._on_state_update,
        )

        online = sum(1 for s in self._states.values() if s.status == "online")
        total = len(self._states)
        logger.info(f"Initialization complete: {online}/{total} devices online")

        self._health_task = asyncio.create_task(self._health_check_loop())

    async def shutdown(self) -> None:
        """Stop health check and command queue."""
        if self._health_task:
            self._health_task.cancel()
            try:
                await self._health_task
            except asyncio.CancelledError:
                pass

        if self._queue:
            await self._queue.shutdown()

        logger.info("Device manager shut down")

    async def control_device(
        self, device_id: str, action: str, child_id: str | None = None
    ) -> DeviceState:
        """Submit command to queue and wait for completion."""
        mac = self._config.resolve_id(device_id)
        if not mac:
            raise ValueError(f"Device {device_id} not found")

        if action not in ("on", "off"):
            raise ValueError(f"Invalid action: {action}. Use 'on' or 'off'")

        if child_id is not None:
            current = self._states.get(device_id)
            if current and not current.is_strip:
                raise ValueError(f"Device {device_id} does not support child outlets")
            if current and current.children:
                if child_id not in {c.id for c in current.children}:
                    raise ValueError(f"Child outlet {child_id} not found")

        if not self._queue:
            raise RuntimeError("Device manager not initialized")

        cmd = make_command(device_id, action, child_id)
        cmd = self._queue.submit(cmd)
        cmd = await self._queue.wait_for_command(cmd)

        if cmd.status == CommandStatus.COMPLETED:
            assert cmd.result is not None
            return cmd.result

        error_msg = cmd.error or "Unknown error"
        if "offline" in error_msg.lower():
            raise DeviceOfflineError(error_msg)
        if "timed out" in error_msg.lower():
            raise DeviceOperationError(error_msg)
        raise DeviceOperationError(error_msg)

    def get_all_states(self) -> list[DeviceState]:
        """Get all device states from cache, in config file order."""
        return [
            self._states[info.id]
            for info in self._config.devices.values()
            if info.id in self._states
        ]

    def get_device_state(self, device_id: str) -> DeviceState:
        """Get a single device state from cache."""
        state = self._states.get(device_id)
        if not state:
            raise ValueError(f"Device {device_id} not found")
        return state

    async def refresh_device(self, device_id: str) -> DeviceState:
        """Bypass queue: re-discover + connect + update cache."""
        mac = self._config.resolve_id(device_id)
        if not mac:
            raise ValueError(f"Device {device_id} not found")

        cfg = self._config.devices[mac]
        backend = self._backends.get(device_id)
        if not backend:
            raise ValueError(f"No backend registered for device {device_id}")

        state = await backend.refresh(cfg)
        self._states[device_id] = state
        return state

    def _on_state_update(self, device_id: str, state: DeviceState | None) -> None:
        """Callback from CommandQueue when a command completes or fails."""
        if state is None:
            mac = self._config.resolve_id(device_id)
            if not mac:
                logger.warning(f"State update for unknown device {device_id}")
                return
            previous = self._states.get(device_id)
            state = build_offline_state(self._config.devices[mac], previous)
        self._states[device_id] = state

    async def _health_check_loop(self) -> None:
        """Periodically check devices without active processors."""
        while True:
            await asyncio.sleep(HEALTH_CHECK_INTERVAL)
            try:
                await self._run_health_check()
            except Exception as e:
                logger.warning(f"Health check failed: {e}")

    async def _run_health_check(self) -> None:
        """Poll idle devices and update state cache."""
        checked = 0
        online = 0

        for mac, cfg in self._config.devices.items():
            backend = self._backends.get(cfg.id)
            if not backend:
                continue

            if self._queue and self._queue.has_active_processor(cfg.id):
                continue

            state = await backend.health_check(cfg, self._states.get(cfg.id))
            if state is None:
                continue

            if state.status == "online":
                online += 1

            self._states[cfg.id] = state
            checked += 1

        logger.debug(f"Health check: {online}/{checked} devices online")

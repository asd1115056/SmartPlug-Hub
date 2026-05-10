"""MiIO protocol backend — stateless UDP, no persistent connection."""

import logging

from ..models import Command, DeviceBackend, DeviceOfflineError, DeviceState, MiioDeviceConfig, build_offline_state
from . import connection

logger = logging.getLogger(__name__)


class MiioBackend(DeviceBackend[MiioDeviceConfig]):
    """MiIO backend: stateless UDP, processor exits immediately after each command."""

    session_timeout: float = 0.0  # UDP has no session; processor exits right away
    command_interval: float = 0.0

    def __init__(self, ip_cache: dict[str, str]) -> None:
        self._ip_cache = ip_cache

    async def execute_command(self, cmd: Command, cfg: MiioDeviceConfig) -> DeviceState:
        ip = self._ip_cache.get(cfg.mac)
        if not ip:
            raise DeviceOfflineError(f"{cfg.name}: IP unknown, device not yet discovered")
        await connection.set_power(ip, cfg, cmd.action == "on", cmd.child_id)
        return await connection.get_status(ip, cfg)

    async def refresh(
        self, cfg: MiioDeviceConfig, previous: DeviceState | None = None
    ) -> DeviceState:
        """Re-discover + get current state. Always attempts discovery first."""
        self._ip_cache.update(await connection.discover_all({cfg.mac: cfg}))
        ip = self._ip_cache.get(cfg.mac)
        if not ip:
            logger.warning(f"Could not reach {cfg.name} during refresh")
            return build_offline_state(cfg, previous)
        return await connection.get_status(ip, cfg)

    async def health_check(
        self, cfg: MiioDeviceConfig, previous: DeviceState | None = None
    ) -> DeviceState | None:
        """Poll current state. Returns None if IP is unknown (skip this cycle)."""
        ip = self._ip_cache.get(cfg.mac)
        if not ip:
            return None
        return await connection.get_status(ip, cfg)

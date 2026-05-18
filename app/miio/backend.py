"""MiIO protocol backend — stateless UDP, no persistent connection."""

import logging

from ..core.backend import BackendPolicy, Command, DeviceBackend
from ..core.exceptions import DeviceOfflineError
from ..core.models import DeviceState, DeviceStatus
from ..db import DeviceInfo
from . import connection

logger = logging.getLogger(__name__)


class MiioBackend(DeviceBackend[DeviceInfo]):
    """MiIO backend: stateless UDP, exits immediately after each command."""

    policy = BackendPolicy(session_timeout=0.0, command_interval=0.0, command_timeout=25.0)

    def __init__(self) -> None:
        super().__init__()

    async def execute_command(self, cmd: Command, cfg: DeviceInfo) -> DeviceState:
        if not self.ip:
            raise DeviceOfflineError(f"{cfg.name}: IP unknown, device not yet discovered")
        await connection.set_power(self.ip, cfg, cmd.action == "on", cmd.child_id)
        return await connection.get_status(self.ip, cfg)

    async def fetch_state(self, cfg: DeviceInfo, ip: str) -> DeviceState | None:
        state = await connection.get_status(ip, cfg)
        if state.status == DeviceStatus.ONLINE:
            self.ip = ip
            return state
        return None

    async def find_ip(self, cfg: DeviceInfo) -> str | None:
        results = await connection.discover_all({cfg.mac: cfg})
        ip = results.get(cfg.mac)
        if ip:
            self.ip = ip
            logger.info(f"Discovered {cfg.name} at {ip}")
        else:
            logger.warning(f"Broadcast discovery found no result for {cfg.name}")
        return ip

    async def rename_outlet(self, cfg: DeviceInfo, outlet_id: str, new_name: str) -> None:
        pass  # MiIO does not support hardware alias; label is stored in DB only

    async def rename_device(self, cfg: DeviceInfo, new_name: str) -> None:
        pass  # MiIO does not support hardware rename

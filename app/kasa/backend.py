"""Kasa protocol backend with persistent TCP connection pool."""

import logging

from kasa import Device

from ..models import (
    Command,
    DeviceBackend,
    DeviceOfflineError,
    DeviceState,
    KasaDeviceConfig,
    build_offline_state,
)
from ..utils import normalize_mac
from .connection import (
    build_device_state,
    connect_device,
    discover_device_ip,
)

logger = logging.getLogger(__name__)


class KasaBackend(DeviceBackend[KasaDeviceConfig]):
    """Kasa backend: persistent TCP connections, retry + rediscovery on failure."""

    session_timeout: float = 30.0  # processor exits after 30s idle
    command_interval: float = 0.5  # rate limiting between commands

    def __init__(self, ip_cache: dict[str, str]) -> None:
        self._ip_cache = ip_cache
        self._connections: dict[str, Device] = {}

    async def execute_command(self, cmd: Command, cfg: KasaDeviceConfig) -> DeviceState:
        device_id = cmd.device_id
        device = self._connections.get(device_id)

        if device:
            try:
                await self._execute_action(device, cmd)
                await device.update()
                state = build_device_state(cfg, device)
                self._ip_cache[cfg.mac] = device.host
                self._connections[device_id] = device
                return state
            except Exception as e:
                logger.warning(
                    f"Command failed on existing connection for {cfg.name}: {e}"
                )
                try:
                    await device.disconnect()
                except Exception:
                    pass
                device = None
                self._connections.pop(device_id, None)

        cached_ip = self._ip_cache.get(cfg.mac)
        if cached_ip:
            logger.info(f"Retrying {cfg.name} at cached IP {cached_ip}...")
            device, _ = await connect_device(cached_ip, cfg.credentials)
            if device:
                device_mac = getattr(device, "mac", None)
                try:
                    mac_mismatch = device_mac and normalize_mac(device_mac) != cfg.mac
                except ValueError:
                    mac_mismatch = True
                if mac_mismatch:
                    logger.warning(f"IP {cached_ip} no longer belongs to {cfg.mac}")
                    await device.disconnect()
                    device = None
                else:
                    try:
                        await self._execute_action(device, cmd)
                        await device.update()
                        state = build_device_state(cfg, device)
                        self._ip_cache[cfg.mac] = device.host
                        self._connections[device_id] = device
                        return state
                    except Exception as e:
                        logger.warning(
                            f"Retry at cached IP failed for {cfg.name}: {e}"
                        )
                        try:
                            await device.disconnect()
                        except Exception:
                            pass
                        device = None

        logger.info(f"Discovering new IP for {cfg.name}...")
        new_ip = await discover_device_ip(cfg)
        if new_ip:
            device, _ = await connect_device(new_ip, cfg.credentials)
            if device:
                try:
                    await self._execute_action(device, cmd)
                    await device.update()
                    state = build_device_state(cfg, device)
                    self._ip_cache[cfg.mac] = new_ip
                    self._connections[device_id] = device
                    return state
                except Exception as e:
                    logger.warning(
                        f"Command at discovered IP failed for {cfg.name}: {e}"
                    )
                    try:
                        await device.disconnect()
                    except Exception:
                        pass

        raise DeviceOfflineError(
            f"Device {cfg.name} is offline (all retry attempts failed)"
        )

    async def cleanup(self, device_id: str) -> None:
        device = self._connections.pop(device_id, None)
        if device:
            try:
                await device.disconnect()
                logger.info(f"Disconnected idle session for device {device_id}")
            except Exception:
                pass

    async def refresh(self, cfg: KasaDeviceConfig) -> DeviceState:
        """Re-discover + connect + return current state. Always disconnects after."""
        cached_ip = self._ip_cache.get(cfg.mac)
        if cached_ip:
            device, _ = await connect_device(cached_ip, cfg.credentials)
            if device:
                state = build_device_state(cfg, device)
                self._ip_cache[cfg.mac] = device.host
                await device.disconnect()
                logger.info(f"Initialized {cfg.name} ({device.model}) at {cached_ip}")
                return state

        new_ip = await discover_device_ip(cfg)
        if new_ip:
            device, _ = await connect_device(new_ip, cfg.credentials)
            if device:
                state = build_device_state(cfg, device)
                self._ip_cache[cfg.mac] = new_ip
                await device.disconnect()
                logger.info(f"Initialized {cfg.name} ({device.model}) at {new_ip}")
                return state

        logger.warning(f"Could not reach {cfg.name} during refresh")
        return build_offline_state(cfg)

    async def health_check(self, cfg: KasaDeviceConfig) -> DeviceState | None:
        """Connect + get state. Returns None if no IP is known (skip this cycle)."""
        cached_ip = self._ip_cache.get(cfg.mac)
        if not cached_ip:
            return None

        device, _ = await connect_device(cached_ip, cfg.credentials)
        if device:
            state = build_device_state(cfg, device)
            self._ip_cache[cfg.mac] = device.host
            await device.disconnect()
            return state

        return build_offline_state(cfg)

    async def _execute_action(self, device: Device, command: Command) -> None:
        """Execute a single on/off command on a device or child outlet."""
        target = device
        if command.child_id:
            child_found = False
            for child in device.children:
                if child.device_id == command.child_id:
                    target = child
                    child_found = True
                    break
            if not child_found:
                raise ValueError(f"Child outlet {command.child_id} not found")

        if command.action == "on":
            await target.turn_on()
        else:
            await target.turn_off()

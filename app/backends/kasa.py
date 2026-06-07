"""Kasa protocol backend — persistent TCP connection, reconnects on demand."""

import asyncio
import logging

from kasa import Credentials, Device, Module
from kasa import DeviceConfig as KasaConfig
from kasa import Discover
from kasa.exceptions import AuthenticationError

from ..core import (
    ChildState, DeviceBackend, DeviceConfig, DeviceOfflineError, DeviceState, normalize_mac,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_RETRIES = 2
_RETRY_DELAY = 0.5


class KasaBackend(DeviceBackend):
    can_rename_outlet = True
    can_rename_device = True
    session_timeout = 60.0
    command_interval = 0.5

    def __init__(self) -> None:
        self.ip: str | None = None
        self._device: Device | None = None

    async def probe(self, cfg: DeviceConfig) -> DeviceState:
        device = await self._get_device(cfg)
        try:
            await device.update()
            self.ip = device.host
            return _build_state(device)
        except Exception:
            await self._drop()
            raise DeviceOfflineError(f"Lost connection to {cfg.mac}")

    async def set_power(self, cfg: DeviceConfig, outlet_id: str | None, on: bool) -> None:
        device = await self._get_device(cfg)
        try:
            await device.update()
            if outlet_id:
                child = next((c for c in (device.children or []) if c.device_id == outlet_id), None)
                if child is None:
                    raise ValueError(f"Outlet {outlet_id} not found on {cfg.mac}")
                await (child.turn_on() if on else child.turn_off())
            else:
                await (device.turn_on() if on else device.turn_off())
        except ValueError:
            raise
        except Exception:
            await self._drop()
            raise DeviceOfflineError(f"Lost connection to {cfg.mac}")

    async def rename_outlet(self, cfg: DeviceConfig, outlet_id: str, name: str) -> None:
        device = await self._get_device(cfg)
        try:
            await device.update()
            target = next(
                (c for c in (device.children or []) if c.device_id == outlet_id), None
            )
            if target is None:
                raise ValueError(f"Outlet {outlet_id} not found on {cfg.mac}")
            await target.set_alias(name)
        except ValueError:
            raise
        except Exception:
            await self._drop()
            raise DeviceOfflineError(f"Lost connection to {cfg.mac}")

    async def rename_device(self, cfg: DeviceConfig, name: str) -> None:
        # TODO: verify set_alias on strip (HS300 untested) and cloud sync on single plug
        device = await self._get_device(cfg)
        try:
            await device.set_alias(name)
        except Exception:
            await self._drop()
            raise DeviceOfflineError(f"Lost connection to {cfg.mac}")

    async def close(self) -> None:
        await self._drop()

    # ── Connection management ─────────────────────────────────────────────────

    async def _get_device(self, cfg: DeviceConfig) -> Device:
        if self._device is not None:
            return self._device

        logger.info("Probing %s at %s", cfg.id, self.ip or cfg.last_known_ip or cfg.broadcast)
        for ip in _unique(self.ip, cfg.last_known_ip):
            device = await _connect(ip, _credentials(cfg))
            if device is not None and _mac_ok(device, cfg.mac):
                self._device = device
                self.ip = device.host
                return device
            if device is not None:
                await _safe_close(device)

        ip = await _discover(cfg)
        if ip:
            device = await _connect(ip, _credentials(cfg))
            if device is not None:
                self._device = device
                self.ip = device.host
                return device

        raise DeviceOfflineError(f"Cannot reach {cfg.mac}")

    async def _drop(self) -> None:
        if self._device is not None:
            await _safe_close(self._device)
            self._device = None


# ── Module-level helpers ──────────────────────────────────────────────────────

def _credentials(cfg: DeviceConfig) -> Credentials | None:
    if cfg.username and cfg.password:
        return Credentials(username=cfg.username, password=cfg.password)
    return None


async def _connect(ip: str, credentials: Credentials | None) -> Device | None:
    """Try connecting without auth first, then with credentials if auth is required."""
    for creds in ([None, credentials] if credentials else [None]):
        for attempt in range(_RETRIES):
            device = None
            try:
                device = await Device.connect(
                    config=KasaConfig(host=ip, credentials=creds, timeout=_TIMEOUT)
                )
                await device.update()
                return device
            except AuthenticationError:
                if device:
                    await _safe_close(device)
                break  # wrong creds — try next creds variant, not retry
            except Exception as e:
                if device:
                    await _safe_close(device)
                if attempt < _RETRIES - 1:
                    await asyncio.sleep(_RETRY_DELAY)
                else:
                    logger.warning("Cannot connect to %s: %s", ip, e)
    return None


async def _discover(cfg: DeviceConfig) -> str | None:
    found: str | None = None

    async def on_found(device: Device) -> None:
        nonlocal found
        mac = getattr(device, "mac", None)
        if mac and normalize_mac(mac) == cfg.mac:
            found = device.host
        await _safe_close(device)

    await Discover.discover(target=cfg.broadcast, on_discovered=on_found)
    return found


async def _safe_close(device: Device) -> None:
    try:
        await device.disconnect()
    except Exception as e:
        logger.debug("Disconnect error (ignored): %s", e)


def _mac_ok(device: Device, expected_mac: str) -> bool:
    mac = getattr(device, "mac", None)
    if not mac:
        return True
    try:
        return normalize_mac(mac) == expected_mac
    except ValueError:
        return True


def _unique(*values: str | None) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        if v is not None:
            seen[v] = None
    return list(seen)


def _watts(obj: Device) -> float | None:
    energy = obj.modules.get(Module.Energy)
    if energy is None:
        return None
    try:
        return energy.current_consumption
    except Exception:
        return None


def _build_state(device: Device) -> DeviceState:
    is_strip = bool(device.children)
    children = [
        ChildState(
            outlet_id=child.device_id,
            hw_alias=child.alias,
            is_on=child.is_on,
            watts=_watts(child),
        )
        for child in (device.children or [])
    ]
    return DeviceState(
        hw_alias=device.alias,
        hw_model=device.model,
        hw_is_strip=is_strip,
        is_on=device.is_on,
        children=children,
        watts=_watts(device) if not is_strip else None,
    )

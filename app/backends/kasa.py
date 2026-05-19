"""Kasa protocol backend — persistent TCP connection, reconnects on demand."""

import asyncio
import logging

from kasa import Credentials, Device, DeviceConnectionParameters, DeviceEncryptionType, Module
from kasa import DeviceConfig as KasaConfig
from kasa import Discover
from kasa.deviceconfig import DeviceFamily
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
        self.kasa_encrypt_type: str | None = None    # set after first successful connect
        self.kasa_device_family: str | None = None
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

        encrypt_type = self.kasa_encrypt_type or cfg.kasa_encrypt_type
        device_family = self.kasa_device_family or cfg.kasa_device_family
        logger.info("Probing %s at %s", cfg.id, self.ip or cfg.last_known_ip or cfg.broadcast)
        for ip in _unique(self.ip, cfg.last_known_ip):
            device = await _connect(ip, _credentials(cfg), encrypt_type, device_family)
            if device is not None and _mac_ok(device, cfg.mac):
                self._device = device
                self.ip = device.host
                self.kasa_encrypt_type, self.kasa_device_family = _extract_connection_info(device)
                return device
            if device is not None:
                await _safe_close(device)

        device = await _discover(cfg)
        if device is not None:
            self._device = device
            self.ip = device.host
            self.kasa_encrypt_type, self.kasa_device_family = _extract_connection_info(device)
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


async def _connect(
    ip: str,
    credentials: Credentials | None,
    encrypt_type: str | None,
    device_family: str | None,
) -> Device | None:
    """Connect to a device at a known IP.

    Uses stored encrypt_type + device_family to skip protocol negotiation.
    Falls back to unicast discovery when unknown or when stored info fails.
    """
    if encrypt_type and device_family:
        try:
            conn_params = DeviceConnectionParameters(
                device_family=DeviceFamily(device_family),
                encryption_type=DeviceEncryptionType(encrypt_type),
            )
            device = await Device.connect(
                config=KasaConfig(
                    host=ip,
                    credentials=credentials,
                    timeout=_TIMEOUT,
                    connection_type=conn_params,
                )
            )
            await device.update()
            return device
        except AuthenticationError:
            return None
        except Exception as e:
            logger.warning("Cannot connect to %s with stored protocol: %s", ip, e)
            # fall through to unicast discovery

    # Protocol unknown or stored info failed — unicast-discover to auto-detect
    return await _discover_at(ip, credentials)


async def _discover_at(ip: str, credentials: Credentials | None) -> Device | None:
    """Unicast-discover a specific IP to auto-detect its protocol."""
    found: Device | None = None

    async def on_found(device: Device) -> None:
        nonlocal found
        found = device

    for attempt in range(_RETRIES):
        found = None
        try:
            await Discover.discover(
                target=ip,
                credentials=credentials,
                on_discovered=on_found,
                timeout=_TIMEOUT,
            )
            if found is not None:
                await found.update()
                return found
        except AuthenticationError:
            if found:
                await _safe_close(found)
            return None
        except Exception as e:
            if found:
                await _safe_close(found)
                found = None
            if attempt < _RETRIES - 1:
                await asyncio.sleep(_RETRY_DELAY)
            else:
                logger.warning("Cannot connect to %s: %s", ip, e)
    return None


async def _discover(cfg: DeviceConfig) -> Device | None:
    """Broadcast-discover by MAC; returns the connected Device or None."""
    found: Device | None = None
    creds = _credentials(cfg)

    async def on_found(device: Device) -> None:
        nonlocal found
        mac = getattr(device, "mac", None)
        if mac and normalize_mac(mac) == cfg.mac:
            found = device
        else:
            await _safe_close(device)

    await Discover.discover(target=cfg.broadcast, credentials=creds, on_discovered=on_found)
    if found is not None:
        try:
            await found.update()
        except Exception:
            await _safe_close(found)
            return None
    return found


def _extract_connection_info(device: Device) -> tuple[str | None, str | None]:
    """Return (encrypt_type, device_family) strings from a connected device."""
    try:
        ct = device.config.connection_type
        return ct.encryption_type.value, ct.device_family.value
    except Exception:
        return None, None


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

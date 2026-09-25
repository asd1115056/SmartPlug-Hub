"""Kasa protocol backend — persistent connection over XOR or KLAP, reconnects on demand."""

import asyncio
import logging

from kasa import Credentials, Device, Module
from kasa import DeviceConfig as KasaConfig
from kasa import Discover
from kasa.device_factory import get_device_class_from_sys_info, get_protocol
from kasa.deviceconfig import DeviceConnectionParameters, DeviceEncryptionType
from kasa.exceptions import AuthenticationError, KasaException, UnsupportedDeviceError
from kasa.protocols import BaseProtocol, IotProtocol
from kasa.transports.klaptransport import KlapTransportV2

from ..core import (
    ChildState, DeviceBackend, DeviceConfig, DeviceOfflineError, DeviceRejectedError,
    DeviceState, mac_to_id, normalize_mac,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 10
_RETRIES = 2
_RETRY_DELAY = 0.5
_SYSINFO_QUERY = {"system": {"get_sysinfo": {}}}


class KasaBackend(DeviceBackend):
    can_rename_outlet = True
    can_rename_device = True
    # Every DeviceQueue operation (power, rename, refresh, and the periodic poll
    # in device_service.POLL_INTERVAL) resets this idle timer. Must stay well
    # below POLL_INTERVAL (60s) so the connection is deterministically closed
    # and re-established each poll cycle, not held open indefinitely by polling.
    session_timeout = 20.0
    command_interval = 0.5

    def __init__(self) -> None:
        self.ip: str | None = None
        self._device: Device | None = None
        # Detected once per backend instead of on every reconnect; _connect re-detects if
        # it stops working (e.g. Third-Party Compatibility toggled in the Kasa app)
        self._params: DeviceConnectionParameters | None = None

    def is_configured(self, cfg: DeviceConfig) -> bool:
        return True  # Kasa probes without credentials; auth is attempted opportunistically

    async def probe(self, cfg: DeviceConfig) -> DeviceState:
        device = await self._get_device(cfg)
        try:
            await device.update()
            self.ip = device.host
            return _build_state(device)
        except Exception as e:
            await self._drop()
            raise DeviceOfflineError(f"Lost connection to {cfg.mac}: {e}") from e

    async def set_power(self, cfg: DeviceConfig, outlet_id: str | None, on: bool) -> None:
        device = await self._get_device(cfg)
        try:
            await device.update()
            if outlet_id:
                child = next((c for c in (device.children or []) if c.device_id == outlet_id), None)
                if child is None:
                    raise ValueError(f"Outlet {outlet_id} not found on {cfg.mac}")
                await (child.turn_on() if on else child.turn_off())
            elif device.children:
                raise ValueError(f"{cfg.mac} is a power strip — outlet_id is required")
            else:
                await (device.turn_on() if on else device.turn_off())
        except ValueError:
            raise
        except Exception as e:
            await self._drop()
            raise DeviceOfflineError(f"Lost connection to {cfg.mac}: {e}") from e

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
        except Exception as e:
            if _is_rejection(e):
                # The device answered, so the connection is healthy — keep it open
                raise DeviceRejectedError(f"{cfg.mac} rejected outlet rename: {e}") from e
            await self._drop()
            raise DeviceOfflineError(f"Lost connection to {cfg.mac}: {e}") from e

    async def rename_device(self, cfg: DeviceConfig, name: str) -> None:
        # TODO: verify set_alias on strip (HS300 untested) and cloud sync on single plug
        device = await self._get_device(cfg)
        try:
            await device.set_alias(name)
        except Exception as e:
            await self._drop()
            raise DeviceOfflineError(f"Lost connection to {cfg.mac}: {e}") from e

    async def close(self) -> None:
        await self._drop()

    # ── Connection management ─────────────────────────────────────────────────

    async def _get_device(self, cfg: DeviceConfig) -> Device:
        if self._device is not None:
            return self._device

        # Broadcast discovery only when no IP is known (new device, or after refresh()).
        # A known-but-dead IP is reported offline; refresh() rediscovers, same as MiIO/Tuya.
        known_ips = _unique(self.ip, cfg.last_known_ip)
        if not known_ips:
            logger.info("Discovering %s on %s", cfg.id, cfg.broadcast)
            ip = await _discover(cfg)
            known_ips = [ip] if ip else []

        taken_ips: list[str] = []
        for ip in known_ips:
            logger.info("Probing %s at %s", cfg.id, ip)
            try:
                device = await _connect(ip, _credentials(cfg), self._params)
            except AuthenticationError as e:
                raise DeviceOfflineError(
                    f"Kasa login failed for {cfg.mac} at {ip} — check the account email and "
                    f"password: {e}"
                ) from e
            if device is not None and _mac_ok(device, cfg.mac):
                self._device = device
                self._params = device.config.connection_type
                self.ip = device.host
                return device
            if device is not None:
                await _safe_close(device)
                taken_ips.append(ip)

        if taken_ips:
            raise DeviceOfflineError(
                f"Cannot reach {cfg.mac}: {', '.join(taken_ips)} now answers as another device"
            )
        raise DeviceOfflineError(f"Cannot reach {cfg.mac}")

    async def _drop(self) -> None:
        if self._device is not None:
            await _safe_close(self._device)
            self._device = None


# ── Module-level helpers ──────────────────────────────────────────────────────

def _credentials(cfg: DeviceConfig) -> Credentials | None:
    if cfg.username and cfg.password:
        # KLAP hashes the username case-sensitively, and devices are bound to the lowercased
        # account email (discovery's owner field is md5(email.lower()))
        return Credentials(username=cfg.username.lower(), password=cfg.password)
    return None


async def _connect(
    ip: str, credentials: Credentials | None, params: DeviceConnectionParameters | None,
) -> Device | None:
    """Connect over the device's own protocol, detecting it first when params is None.

    Raises AuthenticationError (retrying can't fix wrong credentials); returns None when
    the device can't be reached.
    """
    for attempt in range(_RETRIES):
        try:
            if params is None:
                params = await _detect_protocol(ip, credentials)
            return await _open(ip, params, credentials)
        except AuthenticationError:
            raise
        except Exception as e:
            params = None  # the cached protocol may be stale — re-detect on the next attempt
            if attempt < _RETRIES - 1:
                await asyncio.sleep(_RETRY_DELAY)
            else:
                logger.warning("Cannot connect to %s: %s", ip, e)
    return None


async def _detect_protocol(
    ip: str, credentials: Credentials | None,
) -> DeviceConnectionParameters:
    """Unicast discovery: which protocol (XOR / KLAP, login version) the device speaks."""
    device = await Discover.discover_single(ip, credentials=credentials, timeout=_TIMEOUT)
    await _safe_close(device)
    return device.config.connection_type


async def _open(
    ip: str, params: DeviceConnectionParameters, credentials: Credentials | None,
) -> Device:
    config = KasaConfig(
        host=ip, credentials=credentials, timeout=_TIMEOUT, connection_type=params,
    )
    if not params.device_family.value.startswith("IOT."):
        return await Device.connect(config=config)  # newer (SMART) devices: library path works

    # python-kasa picks the class of an IOT KLAP device from its family alone, which makes
    # an HS300 an IotPlug with no outlets; sysinfo gives the real class (IotStrip)
    protocol = _iot_protocol(config)
    try:
        info = await protocol.query(_SYSINFO_QUERY)
        device = get_device_class_from_sys_info(info)(ip, config=config, protocol=protocol)
        await device.update()
    except BaseException:
        await protocol.close()
        raise
    return device


def _iot_protocol(config: KasaConfig) -> BaseProtocol:
    ctype = config.connection_type
    if ctype.encryption_type is DeviceEncryptionType.Klap and (ctype.login_version or 1) >= 2:
        # python-kasa 0.10.2 gives every IOT KLAP device the v1 handshake, but firmware that
        # advertises login_version 2 (HS300 fw 1.1.2, EP10, HS200, ...) rejects it. Drop
        # this once python-kasa PR #1731 is released.
        return IotProtocol(transport=KlapTransportV2(config=config))
    protocol = get_protocol(config)
    if protocol is None:
        raise UnsupportedDeviceError(f"Unsupported Kasa protocol for {config.host}: {ctype}")
    return protocol


async def _broadcast_discover(
    broadcast: str, timeout: float = 3.0
) -> list[tuple[str, str, str | None]]:
    """Send Kasa discovery to one broadcast; return [(normalized_mac, ip, model)]."""
    found: list[tuple[str, str, str | None]] = []

    async def on_found(device: Device) -> None:
        mac = getattr(device, "mac", None)
        if mac:
            model = getattr(device, "model", None)
            found.append((normalize_mac(mac), device.host, model))
        await _safe_close(device)

    await Discover.discover(target=broadcast, on_discovered=on_found, timeout=int(timeout))
    return found


async def _discover(cfg: DeviceConfig) -> str | None:
    """Search cfg.broadcast for a device matching cfg.mac; return IP or None."""
    for mac, ip, _model in await _broadcast_discover(cfg.broadcast):
        if mac == cfg.mac:
            return ip
    return None


async def scan(iface_pairs: list[tuple[str, str]], timeout: float = 3.0) -> list[DeviceConfig]:
    """Discover all Kasa devices across multiple broadcast addresses."""
    seen: dict[str, DeviceConfig] = {}

    async def _one(broadcast: str) -> None:
        for mac, ip, model in await _broadcast_discover(broadcast, timeout):
            seen.setdefault(mac, DeviceConfig(
                id=mac_to_id(mac), mac=mac, type="kasa",
                broadcast=broadcast, last_known_ip=ip, hw_model=model,
            ))

    await asyncio.gather(*(_one(brd) for _, brd in iface_pairs), return_exceptions=True)
    return list(seen.values())


async def _safe_close(device: Device) -> None:
    try:
        await device.disconnect()
    except Exception as e:
        logger.debug("Disconnect error (ignored): %s", e)


def _is_rejection(e: Exception) -> bool:
    # IotDevice._query_helper raises a bare KasaException when the device replies with a
    # non-zero err_code; transport failures use subclasses (TimeoutError, _ConnectionError).
    return type(e) is KasaException


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

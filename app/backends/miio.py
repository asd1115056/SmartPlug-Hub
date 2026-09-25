"""MiIO protocol backend — stateless UDP, device-profile driven."""

import asyncio
import logging
import re
import socket
import time
from dataclasses import dataclass
from functools import partial

from miio.exceptions import DeviceException
from miio.miot_device import MiotDevice
from miio.protocol import Message

from ..core import (
    ChildState,
    DeviceBackend,
    DeviceConfig,
    DeviceOfflineError,
    DeviceState,
    mac_to_id,
)
from ..network import mac_from_ip

logger = logging.getLogger(__name__)

_MIIO_PORT = 54321
_HELLO = bytes.fromhex("21310020" + "ff" * 28)
_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32}$")


# ── Device support table ──────────────────────────────────────────────────────

@dataclass
class MiotProfile:
    """MiOT property map for one device model."""
    model: str
    main_siid: int
    outlet_siids: list[int]     # physical outlets in order
    usb_siid: int | None        # None if model has no USB port
    power_siid: int | None      # service siid for power consumption
    power_piid: int | None      # property piid for electric-power (W)

    def siid_map(self) -> dict[int, tuple[str, str]]:
        """Return {siid: (outlet_id, display_name)} for all switchable outlets."""
        result: dict[int, tuple[str, str]] = {
            siid: (str(i + 1), f"Outlet {i + 1}")
            for i, siid in enumerate(self.outlet_siids)
        }
        if self.usb_siid is not None:
            result[self.usb_siid] = ("usb", "USB")
        return result


# Keyed by model string returned by miIO.info (e.g. "cuco.plug.wp12").
# Only devices listed here are supported — probe() raises for unknown models.
SUPPORTED_DEVICES: dict[str, MiotProfile] = {
    "cuco.plug.wp12": MiotProfile(
        model="cuco.plug.wp12",
        main_siid=2,
        outlet_siids=[3, 4, 5, 6, 7, 8],
        usb_siid=None,
        power_siid=11,
        power_piid=4,
    ),
}


# ── Backend ───────────────────────────────────────────────────────────────────

class MiioBackend(DeviceBackend):
    # MiIO does not support hardware rename — labels live in DB only
    can_rename_outlet = False
    can_rename_device = False
    session_timeout = 0.0
    command_interval = 0.0

    def __init__(self) -> None:
        self.ip: str | None = None
        self._model: str | None = None   # cached after first miIO.info call

    def is_configured(self, cfg: DeviceConfig) -> bool:
        return bool(cfg.miio_token and _TOKEN_RE.match(cfg.miio_token))

    async def probe(self, cfg: DeviceConfig) -> DeviceState:
        _require_token(cfg)
        if not self.ip:
            logger.info("Probing %s at %s", cfg.id, cfg.last_known_ip or cfg.broadcast)
            if cfg.last_known_ip:
                try:
                    profile = await self._resolve_profile(cfg.last_known_ip, cfg)
                    state = await _get_status(cfg.last_known_ip, cfg, profile)
                    self.ip = cfg.last_known_ip
                    return state
                except DeviceOfflineError:
                    logger.warning(
                        "Cannot connect to %s, falling back to discover", cfg.last_known_ip
                    )
            ip = await _discover(cfg)
            if not ip:
                raise DeviceOfflineError(f"Cannot reach {cfg.mac}")
            self.ip = ip
        profile = await self._resolve_profile(self.ip, cfg)
        return await _get_status(self.ip, cfg, profile)

    async def set_power(self, cfg: DeviceConfig, outlet_id: str | None, on: bool) -> None:
        _require_token(cfg)
        if not self.ip:
            raise DeviceOfflineError(f"{cfg.mac}: IP unknown")
        profile = await self._resolve_profile(self.ip, cfg)
        await _set_power(self.ip, cfg, on, outlet_id, profile)

    async def close(self) -> None:
        pass  # UDP — nothing to close

    async def _resolve_profile(self, ip: str, cfg: DeviceConfig) -> MiotProfile:
        """Return the MiotProfile for this device, detecting via miIO.info if needed."""
        model = cfg.hw_model or self._model
        if model and model in SUPPORTED_DEVICES:
            return SUPPORTED_DEVICES[model]

        # First contact or unknown model — ask the device
        loop = asyncio.get_running_loop()
        model = await loop.run_in_executor(None, partial(_fetch_model_sync, ip, cfg))
        if model not in SUPPORTED_DEVICES:
            raise DeviceOfflineError(
                f"Unsupported miio model '{model}' for {cfg.mac} — "
                "add it to SUPPORTED_DEVICES in miio.py"
            )
        self._model = model
        return SUPPORTED_DEVICES[model]


# ── Discovery ─────────────────────────────────────────────────────────────────

def _udp_discover_sync(broadcast: str, timeout: float = 3.0) -> dict[str, str]:
    """Send MiIO hello to broadcast; return {miio_id: ip}."""
    found: dict[str, str] = {}
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        sock.sendto(_HELLO, (broadcast, _MIIO_PORT))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(1024)
            except socket.timeout:
                break
            try:
                m = Message.parse(data)
                device_id_bytes = m.header.value.device_id  # type: ignore[union-attr]
                did = str(int.from_bytes(device_id_bytes, byteorder="big"))
                found[did] = addr[0]
            except Exception as e:
                logger.debug("Skipping malformed UDP packet from %s: %s", addr[0], e)
    except OSError as e:
        logger.warning("UDP discover on %s failed: %s", broadcast, e)
    finally:
        sock.close()
    return found


async def _broadcast_discover(
    broadcast: str, timeout: float = 3.0
) -> dict[str, str]:
    """Send MiIO hello to one broadcast; return {miio_id: ip}."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, partial(_udp_discover_sync, broadcast, timeout)
    )


async def _discover(cfg: DeviceConfig) -> str | None:
    """Search cfg.broadcast for a device matching cfg.miio_id; return IP or None."""
    results = await _broadcast_discover(cfg.broadcast)
    return results.get(cfg.miio_id or "")


async def scan(iface_pairs: list[tuple[str, str]], timeout: float = 3.0) -> list[DeviceConfig]:
    """Discover all MiIO devices across multiple broadcast addresses."""
    seen: dict[str, DeviceConfig] = {}

    async def _one(broadcast: str) -> None:
        loop = asyncio.get_running_loop()
        raw = await _broadcast_discover(broadcast, timeout)
        for miio_id, ip in raw.items():
            mac = await loop.run_in_executor(None, partial(mac_from_ip, ip))
            if mac and mac not in seen:
                seen[mac] = DeviceConfig(
                    id=mac_to_id(mac), mac=mac, type="miio",
                    broadcast=broadcast, last_known_ip=ip, miio_id=miio_id,
                )

    await asyncio.gather(*(_one(brd) for _, brd in iface_pairs), return_exceptions=True)
    return list(seen.values())


# ── Status / control ──────────────────────────────────────────────────────────

def _fetch_model_sync(ip: str, cfg: DeviceConfig) -> str:
    """Call miIO.info on the device and return the model string."""
    device = MiotDevice(ip=ip, token=cfg.miio_token)
    try:
        raw = device.send("miIO.info", [])
        info = raw[0] if isinstance(raw, list) else raw
        model = info.get("model") if isinstance(info, dict) else None
    except DeviceException as e:
        raise DeviceOfflineError(f"{cfg.mac} unreachable during model probe: {e}") from e
    if not model:
        raise DeviceOfflineError(f"{cfg.mac}: miIO.info returned no model string")
    return model


def _get_status_sync(ip: str, cfg: DeviceConfig, profile: MiotProfile) -> DeviceState:
    device = MiotDevice(ip=ip, token=cfg.miio_token)
    siid_map = profile.siid_map()
    all_outlet_siids = list(siid_map.keys())

    props = [{"did": cfg.miio_id, "siid": s, "piid": 1} for s in all_outlet_siids]
    if profile.power_siid is not None and profile.power_piid is not None:
        props.append({"did": cfg.miio_id, "siid": profile.power_siid, "piid": profile.power_piid})

    try:
        results = device.send("get_properties", props)
    except DeviceException as e:
        raise DeviceOfflineError(f"{cfg.mac} unreachable: {e}") from e

    ok = [r for r in results if r.get("code") == 0]
    switch_values = {r["siid"]: bool(r["value"]) for r in ok if r.get("piid") == 1}
    power_result = next(
        (r for r in ok
         if r.get("siid") == profile.power_siid and r.get("piid") == profile.power_piid),
        None,
    )
    watts = float(power_result["value"]) if power_result else None

    children = [
        ChildState(outlet_id=oid, hw_alias=alias, is_on=switch_values[siid])
        for siid, (oid, alias) in sorted(siid_map.items())
        if siid in switch_values
    ]

    return DeviceState(
        hw_alias=None,
        hw_model=profile.model,
        hw_is_strip=True,
        is_on=any(c.is_on for c in children),
        children=children,
        watts=watts,
    )


async def _get_status(ip: str, cfg: DeviceConfig, profile: MiotProfile) -> DeviceState:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_get_status_sync, ip, cfg, profile))


def _set_power_sync(
    ip: str, cfg: DeviceConfig, on: bool, outlet_id: str | None, profile: MiotProfile
) -> None:
    siid_map = profile.siid_map()
    outlet_id_to_siid = {oid: siid for siid, (oid, _) in siid_map.items()}

    if outlet_id is None and siid_map:
        raise ValueError(f"{cfg.mac} is a power strip — outlet_id is required")
    if outlet_id is None:
        siid = profile.main_siid
    elif outlet_id in outlet_id_to_siid:
        siid = outlet_id_to_siid[outlet_id]
    else:
        raise ValueError(f"Unknown outlet_id '{outlet_id}' for {profile.model}")

    device = MiotDevice(ip=ip, token=cfg.miio_token)
    try:
        device.send("set_properties",
                    [{"did": cfg.miio_id, "siid": siid, "piid": 1, "value": on}])
    except DeviceException as e:
        raise DeviceOfflineError(f"{cfg.mac} set_power failed: {e}") from e


async def _set_power(
    ip: str, cfg: DeviceConfig, on: bool, outlet_id: str | None, profile: MiotProfile
) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, partial(_set_power_sync, ip, cfg, on, outlet_id, profile))


def _require_token(cfg: DeviceConfig) -> None:
    if not cfg.miio_token or not _TOKEN_RE.match(cfg.miio_token):
        raise DeviceOfflineError(f"{cfg.mac}: invalid or missing MiIO token")

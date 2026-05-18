"""MiIO protocol backend — stateless UDP, hardcoded for cuco.plug.wp12 (WP12)."""

import asyncio
import logging
import re
import socket
import time
from functools import partial

from miio.exceptions import DeviceException
from miio.miot_device import MiotDevice
from miio.protocol import Message

from .core import (
    ChildState,
    DeviceBackend,
    DeviceConfig,
    DeviceOfflineError,
    DeviceState,
)

logger = logging.getLogger(__name__)

_MIIO_PORT = 54321
_HELLO = bytes.fromhex("21310020" + "ff" * 28)
_TOKEN_RE = re.compile(r"^[0-9a-fA-F]{32}$")

# MiOT property map for cuco.plug.wp12 (verified from miot-spec.org)
_MAIN_SIID = 2
_OUTLET_SIIDS = [3, 4, 5, 6, 7, 8]    # physical outlets 1–6
_USB_SIID = 9
_OUTLET_IDS = ["1", "2", "3", "4", "5", "6", "usb"]


class MiioBackend(DeviceBackend):
    # MiIO does not support hardware rename — labels live in DB only
    can_rename_outlet = False
    can_rename_device = False
    session_timeout = 0.0
    command_interval = 0.0

    def __init__(self) -> None:
        self.ip: str | None = None

    async def probe(self, cfg: DeviceConfig) -> DeviceState:
        _require_token(cfg)
        if not self.ip:
            ip = await _discover(cfg)
            if not ip:
                raise DeviceOfflineError(f"Cannot reach {cfg.mac}")
            self.ip = ip
        return await _get_status(self.ip, cfg)

    async def set_power(self, cfg: DeviceConfig, outlet_id: str | None, on: bool) -> None:
        _require_token(cfg)
        if not self.ip:
            raise DeviceOfflineError(f"{cfg.mac}: IP unknown")
        await _set_power(self.ip, cfg, on, outlet_id)

    async def close(self) -> None:
        pass  # UDP — nothing to close


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
                did = str(int.from_bytes(m.header.value.device_id, byteorder="big"))  # type: ignore[union-attr]
                found[did] = addr[0]
            except Exception:
                pass  # skip malformed packets
    except OSError as e:
        logger.warning(f"UDP discover on {broadcast} failed: {e}")
    finally:
        sock.close()
    return found


async def _discover(cfg: DeviceConfig) -> str | None:
    loop = asyncio.get_running_loop()
    results = await loop.run_in_executor(
        None, partial(_udp_discover_sync, cfg.broadcast)
    )
    return results.get(cfg.miio_id or "")


# ── Status / control ──────────────────────────────────────────────────────────

def _get_status_sync(ip: str, cfg: DeviceConfig) -> DeviceState:
    device = MiotDevice(ip=ip, token=cfg.miio_token)
    props = [{"did": cfg.miio_id, "siid": s, "piid": 1}
             for s in _OUTLET_SIIDS + [_USB_SIID]]
    try:
        results = device.send("get_properties", props)
    except DeviceException as e:
        raise DeviceOfflineError(f"{cfg.mac} unreachable: {e}") from e

    values = {r["siid"]: bool(r["value"]) for r in results if r.get("code") == 0}

    # TODO: device already tells us which siids exist (code==0 in results); build children
    #       from values.keys() so outlet count is dynamic instead of hardcoded via [:6].
    children = [
        ChildState(outlet_id=oid, hw_alias=f"Outlet {oid}", is_on=values.get(siid, False))
        for oid, siid in zip(_OUTLET_IDS[:6], _OUTLET_SIIDS)
    ]
    usb_on = values.get(_USB_SIID, False)
    children.append(ChildState(outlet_id="usb", hw_alias="USB", is_on=usb_on))

    return DeviceState(
        hw_alias=cfg.mac,
        hw_model="WP12",
        hw_is_strip=True,
        is_on=any(c.is_on for c in children),
        children=children,
    )


async def _get_status(ip: str, cfg: DeviceConfig) -> DeviceState:
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, partial(_get_status_sync, ip, cfg))


def _set_power_sync(ip: str, cfg: DeviceConfig, on: bool, outlet_id: str | None) -> None:
    if outlet_id is None:
        siid = _MAIN_SIID
    # TODO: replace parallel-list lookup with a dict {outlet_id: siid} (same refactor as _get_status_sync).
    elif outlet_id in _OUTLET_IDS[:6]:
        siid = _OUTLET_SIIDS[_OUTLET_IDS.index(outlet_id)]
    elif outlet_id == "usb":
        siid = _USB_SIID
    else:
        raise DeviceOfflineError(f"Unknown outlet_id '{outlet_id}'")

    device = MiotDevice(ip=ip, token=cfg.miio_token)
    try:
        device.send("set_properties",
                    [{"did": cfg.miio_id, "siid": siid, "piid": 1, "value": on}])
    except DeviceException as e:
        raise DeviceOfflineError(f"{cfg.mac} set_power failed: {e}") from e


async def _set_power(ip: str, cfg: DeviceConfig, on: bool, outlet_id: str | None) -> None:
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, partial(_set_power_sync, ip, cfg, on, outlet_id))


def _require_token(cfg: DeviceConfig) -> None:
    if not cfg.miio_token or not _TOKEN_RE.match(cfg.miio_token):
        raise DeviceOfflineError(f"{cfg.mac}: invalid or missing MiIO token")

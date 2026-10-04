"""Tuya local-protocol backend — encrypted LAN control via tinytuya."""

import asyncio
import base64
import ipaddress
import json
import logging
import select
import socket
import struct
import time
from collections.abc import Callable
from dataclasses import dataclass

import tinytuya
import tinytuya.scanner as _tuya_scanner

from ..core import (
    DeviceBackend,
    DeviceConfig,
    DeviceError,
    DeviceOfflineError,
    DeviceState,
    DeviceUnsupportedError,
    mac_to_id,
    normalize_mac,
)
from ..network import get_interface_pairs, mac_from_ip

logger = logging.getLogger(__name__)

_TIMEOUT = 8
_RETRIES = 2
_RETRY_DELAY = 0.5


# ── Device support list ───────────────────────────────────────────────────────

@dataclass
class DpsProfile:
    model: str
    switch: str
    phase_raw: str | None = None  # Raw DPS with V/A/W encoded as 8-byte big-endian


# Keyed by product_id (= productKey in UDP response, stored in DeviceConfig.tuya_product_id).
# Only devices listed here are supported — probe() raises for unknown product_ids.
SUPPORTED_DEVICES: dict[str, DpsProfile] = {
    "eev4qfltav8wc87e": DpsProfile(model="Breaker WIFI (dlq)", switch="16", phase_raw="6"),
}


def _get_profile(cfg: DeviceConfig) -> DpsProfile:
    product_id = cfg.tuya_product_id
    if not product_id or product_id not in SUPPORTED_DEVICES:
        raise DeviceUnsupportedError(
            f"Unsupported Tuya product_id '{product_id}' for {cfg.mac} — "
            "add it to SUPPORTED_DEVICES in tuya.py"
        )
    return SUPPORTED_DEVICES[product_id]


class TuyaBackend(DeviceBackend):
    can_rename_outlet = False
    can_rename_device = False
    session_timeout = 0.0   # every command opens and closes its own connection
    command_interval = 0.3

    def is_configured(self, cfg: DeviceConfig) -> bool:
        return bool(cfg.tuya_device_id and cfg.tuya_local_key)

    async def discover(self, cfg: DeviceConfig) -> str | None:
        # Only the configured subnet, like the other backends: no silent fallback to the rest
        iface_pairs = [pair for pair in get_interface_pairs() if pair[1] == cfg.broadcast]
        if not iface_pairs:
            # The discovery request carries a local IP, so it needs a matching interface
            logger.warning(
                "Tuya discovery for %s: broadcast %s is not on any interface of this host",
                cfg.mac, cfg.broadcast,
            )
            return None
        try:
            return await asyncio.to_thread(_sync_find, iface_pairs, cfg)
        except OSError as e:
            # Report the device as not found (503) rather than letting it surface as a 500
            logger.warning("Tuya discovery for %s failed: %s", cfg.mac, e)
            return None

    async def probe(self, cfg: DeviceConfig) -> DeviceState:
        _require_credentials(cfg)
        profile = _get_profile(cfg)
        try:
            return await asyncio.to_thread(_sync_probe, cfg, cfg.ip, profile)
        except DeviceError:
            raise
        except Exception as e:
            raise DeviceOfflineError(f"Tuya probe failed for {cfg.mac}: {e}") from e

    async def set_power(self, cfg: DeviceConfig, outlet_id: str | None, on: bool) -> None:
        # Single-switch devices have no outlets; ignoring outlet_id would toggle the whole
        # device and bypass its device_token (the API checks outlet_tokens instead)
        if outlet_id is not None:
            raise ValueError(f"Unknown outlet_id '{outlet_id}' for {cfg.mac}")
        _require_credentials(cfg)
        profile = _get_profile(cfg)
        try:
            await asyncio.to_thread(_sync_set_power, cfg, cfg.ip, on, profile)
        except DeviceError:
            raise
        except Exception as e:
            raise DeviceOfflineError(f"Tuya set_power failed for {cfg.mac}: {e}") from e

    async def close(self) -> None:
        pass


# ── Sync helpers (run in thread pool) ────────────────────────────────────────

def _sync_probe(cfg: DeviceConfig, ip: str, profile: DpsProfile) -> DeviceState:
    device = _make_device(cfg, ip)
    device.set_socketPersistent(True)
    try:
        result = device.status()
        _check_result(result)
        dps: dict = result.get("dps") or {}
        is_on = bool(dps.get(profile.switch, False))
        watts = _fetch_watts(device, profile)
    finally:
        device.close()
    return DeviceState(
        hw_alias=None, hw_model=profile.model, hw_is_strip=False,
        is_on=is_on, children=[], watts=watts,
    )


def _sync_set_power(
    cfg: DeviceConfig, ip: str, on: bool, profile: DpsProfile
) -> None:
    device = _make_device(cfg, ip)
    try:
        result = device.set_value(profile.switch, on)
        _check_result(result)
    finally:
        device.close()


def _fetch_watts(device: tinytuya.Device, profile: DpsProfile) -> float | None:
    """Request phase_raw DPS via updatedps; return watts or None on any failure."""
    if not profile.phase_raw:
        return None
    try:
        result = device.updatedps(index=[profile.phase_raw])
        raw_b64 = (result or {}).get("dps", {}).get(profile.phase_raw)
        if not isinstance(raw_b64, str):
            return None
        return _decode_phase_a(raw_b64)[2]
    except Exception as e:
        logger.debug("phase_a fetch failed: %s", e)
        return None


def _decode_phase_a(raw_b64: str) -> tuple[float, float, float]:
    """Decode 8-byte big-endian phase_a blob → (voltage V, current A, power W)."""
    # Format confirmed by HA core PR #63519 and tuya-local issue #1429
    raw = base64.b64decode(raw_b64)
    voltage = struct.unpack(">H", raw[0:2])[0] / 10.0
    current = struct.unpack(">I", b"\x00" + raw[2:5])[0] / 1000.0
    power_kw = struct.unpack(">I", b"\x00" + raw[5:8])[0] / 1000.0
    return voltage, current, power_kw * 1000.0


def _make_device(cfg: DeviceConfig, ip: str) -> tinytuya.Device:
    device = tinytuya.Device(
        dev_id=cfg.tuya_device_id,
        address=ip,
        local_key=cfg.tuya_local_key,
        connection_timeout=_TIMEOUT,
    )
    device.set_version(3.5)
    device.set_socketRetryLimit(_RETRIES)
    device.set_socketRetryDelay(_RETRY_DELAY)
    return device


def _check_result(result: dict | None) -> None:
    if result is None:
        return  # some devices return null on successful set — not an error
    if "Error" in result:
        # Offline, not rejected: tinytuya's local errors are timeouts (914), connection failures
        # (901) or undecodable replies (900/904, usually a wrong local key) — none means the
        # device understood the request and refused it
        err = result.get("Error", "unknown")
        code = result.get("Err", "?")
        raise DeviceOfflineError(f"Tuya error {code}: {err}")


# ── Credential validation ─────────────────────────────────────────────────────

def _require_credentials(cfg: DeviceConfig) -> None:
    if not cfg.tuya_device_id or not cfg.tuya_local_key:
        raise DeviceOfflineError(
            f"Missing tuya_device_id or tuya_local_key for {cfg.mac}"
        )


# ── Network scan ──────────────────────────────────────────────────────────────

_UDP_PORTS = (6666, 6667, 7000)   # v3.1 broadcasts, v3.2-3.4 broadcasts, v3.5 replies
# v3.5 devices only answer a discovery request, so it is repeated (tinytuya's BROADCASTTIME);
# the timeout leaves room for a second one in case the first is lost
_REQUEST_INTERVAL = 6.0
_SEARCH_TIMEOUT = 7.0

# (ip, gwId, payload) → True to stop listening
OnReply = Callable[[str, str, dict], bool]


async def scan(
    iface_pairs: list[tuple[str, str]], timeout: float = _SEARCH_TIMEOUT,
) -> list[DeviceConfig]:
    """Discover Tuya devices via encrypted UDP discovery on all local interfaces."""
    return await asyncio.to_thread(_sync_scan, iface_pairs, timeout)


def _sync_find(iface_pairs: list[tuple[str, str]], cfg: DeviceConfig) -> str | None:
    """IP of the device whose gwId is cfg.tuya_device_id, as soon as it answers."""
    found: list[str] = []

    def on_reply(ip: str, gwid: str, _payload: dict) -> bool:
        if gwid != cfg.tuya_device_id:
            return False
        # One ARP lookup, for the match only. As with Kasa, an unresolvable MAC is accepted.
        mac = mac_from_ip(ip)
        if mac and normalize_mac(mac) != cfg.mac:
            logger.warning("Tuya %s answered from %s, but that IP has MAC %s", gwid, ip, mac)
            return False
        found.append(ip)
        return True

    _listen(iface_pairs, _SEARCH_TIMEOUT, on_reply)
    return found[0] if found else None


def _sync_scan(iface_pairs: list[tuple[str, str]], timeout: float) -> list[DeviceConfig]:
    found: dict[str, DeviceConfig] = {}
    unresolved: dict[str, str] = {}   # ip → gwId of devices whose MAC ARP hasn't given yet

    def on_reply(ip: str, gwid: str, payload: dict) -> bool:
        if ip in found:
            return False
        # Device ids are derived from the MAC, so a device without one can't be added. Each
        # later reply from the same device is another chance for ARP.
        mac = mac_from_ip(ip) or mac_from_ip(ip)
        if not mac:
            unresolved[ip] = gwid
            return False
        unresolved.pop(ip, None)
        mac = normalize_mac(mac)
        found[ip] = DeviceConfig(
            id=mac_to_id(mac), mac=mac, type="tuya",
            broadcast=_iface_broadcast_for(ip, iface_pairs),
            last_known_ip=ip,
            tuya_device_id=gwid,
            tuya_product_id=payload.get("productKey"),
        )
        return False

    _listen(iface_pairs, timeout, on_reply)
    for ip, gwid in unresolved.items():
        logger.warning(
            "Tuya %s at %s answered the scan, but its MAC couldn't be resolved", gwid, ip,
        )
    seen: dict[str, DeviceConfig] = {}
    for dev in found.values():
        seen.setdefault(dev.mac, dev)
    return list(seen.values())


def _listen(iface_pairs: list[tuple[str, str]], timeout: float, on_reply: OnReply) -> None:
    """Request discovery every _REQUEST_INTERVAL; feed decoded replies to on_reply. Blocking."""
    own_ips = {local_ip for local_ip, _ in iface_pairs}
    # send_discovery_request keeps a sending socket in each entry; closed below
    targets: dict[str, dict] = {local_ip: {"broadcast": brd} for local_ip, brd in iface_pairs}
    socks: list[socket.socket] = []
    try:
        # Inside the try: a bind failing on a later port must still close the earlier sockets
        for port in _UDP_PORTS:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            socks.append(s)
            # Linux shares a UDP port only among sockets that all set the same option.
            # tinytuya-based tools set SO_REUSEPORT, others SO_REUSEADDR: set both.
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
            s.bind(("0.0.0.0", port))
            s.setblocking(False)

        deadline = time.monotonic() + timeout
        next_request = 0.0
        while (now := time.monotonic()) < deadline:
            if now >= next_request:
                _tuya_scanner.send_discovery_request(targets)
                next_request = now + _REQUEST_INTERVAL
            wait = min(deadline, next_request) - now
            ready, _, _ = select.select(socks, [], [], max(0.0, wait))
            for s in ready:
                try:
                    data, (ip, _) = s.recvfrom(4096)
                except OSError:
                    continue
                if ip in own_ips:
                    continue
                payload = _decode_broadcast(data)
                gwid = payload and (payload.get("gwId") or payload.get("devId"))
                if gwid and on_reply(ip, gwid, payload):
                    return
    finally:
        for s in socks:
            s.close()
        for target in targets.values():
            if sender := target.get("socket"):
                sender.close()


def _decode_broadcast(data: bytes) -> dict | None:
    """Decode any discovery packet: v3.1 plaintext, v3.2-3.4 (55AA) or v3.5 (6699)."""
    try:
        # What tinytuya's own scanner uses; it also tells v3.5 packets with and without a
        # return code apart, which a plain unpack_message does not
        payload = json.loads(tinytuya.decrypt_udp(data))
    except Exception as e:   # any UDP packet on these ports reaches here, not just Tuya's
        logger.debug("Ignoring undecodable discovery packet: %s", e)
        return None
    return payload if isinstance(payload, dict) else None


def _iface_broadcast_for(ip: str, iface_pairs: list[tuple[str, str]]) -> str:
    """Return broadcast of the interface subnet that contains ip."""
    ip_int = int(ipaddress.IPv4Address(ip))
    for local_ip, broadcast in iface_pairs:
        if int(ipaddress.IPv4Address(local_ip)) <= ip_int <= int(ipaddress.IPv4Address(broadcast)):
            return broadcast
    return iface_pairs[0][1] if iface_pairs else "255.255.255.255"


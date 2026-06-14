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
from dataclasses import dataclass

import tinytuya
import tinytuya.scanner as _tuya_scanner

from ..core import (
    DeviceBackend,
    DeviceConfig,
    DeviceOfflineError,
    DeviceState,
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
        raise DeviceOfflineError(
            f"Unsupported Tuya product_id '{product_id}' for {cfg.mac} — "
            "add it to SUPPORTED_DEVICES in tuya.py"
        )
    return SUPPORTED_DEVICES[product_id]


class TuyaBackend(DeviceBackend):
    can_rename_outlet = False
    can_rename_device = False
    session_timeout = 30.0
    command_interval = 0.3

    def __init__(self) -> None:
        self.ip: str | None = None

    def is_configured(self, cfg: DeviceConfig) -> bool:
        return bool(cfg.tuya_device_id and cfg.tuya_local_key)

    async def probe(self, cfg: DeviceConfig) -> DeviceState:
        _require_credentials(cfg)
        profile = _get_profile(cfg)
        if not cfg.last_known_ip and not self.ip:
            self.ip = await _discover_ip(cfg)
        try:
            state = await asyncio.to_thread(_sync_probe, cfg, self.ip, profile)
            self.ip = cfg.last_known_ip or self.ip
            return state
        except DeviceOfflineError:
            raise
        except Exception as e:
            raise DeviceOfflineError(f"Tuya probe failed for {cfg.mac}: {e}") from e

    async def set_power(self, cfg: DeviceConfig, outlet_id: str | None, on: bool) -> None:
        _require_credentials(cfg)
        profile = _get_profile(cfg)
        if not cfg.last_known_ip and not self.ip:
            self.ip = await _discover_ip(cfg)
        try:
            await asyncio.to_thread(_sync_set_power, cfg, self.ip, on, profile)
        except DeviceOfflineError:
            raise
        except Exception as e:
            raise DeviceOfflineError(f"Tuya set_power failed for {cfg.mac}: {e}") from e

    async def close(self) -> None:
        pass


# ── Sync helpers (run in thread pool) ────────────────────────────────────────

def _sync_probe(cfg: DeviceConfig, cached_ip: str | None, profile: DpsProfile) -> DeviceState:
    device = _make_device(cfg, cached_ip)
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
    cfg: DeviceConfig, cached_ip: str | None, on: bool, profile: DpsProfile
) -> None:
    device = _make_device(cfg, cached_ip)
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


def _make_device(cfg: DeviceConfig, cached_ip: str | None) -> tinytuya.Device:
    ip = cfg.last_known_ip or cached_ip
    if not ip:
        raise DeviceOfflineError(f"No IP known for {cfg.mac}")
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

_UDP_PORTS = (6666, 6667, 7000)
_SCAN_TIMEOUT = 5.0


async def _discover_ip(cfg: DeviceConfig) -> str | None:
    """UDP-scan all interfaces for cfg.mac; return its current IP or None."""
    iface_pairs = get_interface_pairs()
    for found in await asyncio.to_thread(_sync_discover, iface_pairs, _SCAN_TIMEOUT):
        if found.mac == cfg.mac:
            return found.last_known_ip
    return None


async def scan(iface_pairs: list[tuple[str, str]], timeout: float = _SCAN_TIMEOUT) -> list[DeviceConfig]:
    """Discover Tuya devices via encrypted UDP discovery on all local interfaces."""
    seen: dict[str, DeviceConfig] = {}
    for cfg in await asyncio.to_thread(_sync_discover, iface_pairs, timeout):
        seen.setdefault(cfg.mac, cfg)
    return list(seen.values())


def _sync_discover(iface_pairs: list[tuple[str, str]], timeout: float) -> list[DeviceConfig]:
    own_ips = {local_ip for local_ip, _ in iface_pairs}
    socks: list[socket.socket] = []
    for port in _UDP_PORTS:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.bind(("0.0.0.0", port))
        s.setblocking(False)
        socks.append(s)

    _tuya_scanner.send_discovery_request(
        {local_ip: {"broadcast": brd} for local_ip, brd in iface_pairs}
    )

    found: dict[str, DeviceConfig] = {}
    deadline = time.monotonic() + timeout
    try:
        while time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            ready, _, _ = select.select(socks, [], [], max(0.0, remaining))
            for s in ready:
                try:
                    data, (ip, _) = s.recvfrom(4096)
                except OSError:
                    continue
                if ip in own_ips or ip in found:
                    continue
                payload = _decode_broadcast(data)
                if not payload:
                    continue
                gwid = payload.get("gwId") or payload.get("devId")
                if not gwid:
                    continue
                mac = mac_from_ip(ip)
                if not mac:
                    continue
                mac = normalize_mac(mac)
                found[ip] = DeviceConfig(
                    id=mac_to_id(mac), mac=mac, type="tuya",
                    broadcast=_iface_broadcast_for(ip, iface_pairs),
                    last_known_ip=ip,
                    tuya_device_id=gwid,
                    tuya_product_id=payload.get("productKey"),
                )
    finally:
        for s in socks:
            s.close()

    return list(found.values())


def _decode_broadcast(data: bytes) -> dict | None:
    try:
        msg = tinytuya.unpack_message(data, hmac_key=tinytuya.udpkey)
        return json.loads(msg.payload)
    except Exception:
        pass
    try:
        # fallback for legacy v3.1 plaintext format
        return json.loads(_tuya_scanner.decrypt_udp(data))
    except Exception:
        return None


def _iface_broadcast_for(ip: str, iface_pairs: list[tuple[str, str]]) -> str:
    """Return broadcast of the interface subnet that contains ip."""
    ip_int = int(ipaddress.IPv4Address(ip))
    for local_ip, broadcast in iface_pairs:
        if int(ipaddress.IPv4Address(local_ip)) <= ip_int <= int(ipaddress.IPv4Address(broadcast)):
            return broadcast
    return iface_pairs[0][1] if iface_pairs else "255.255.255.255"


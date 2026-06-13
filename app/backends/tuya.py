"""Tuya local-protocol backend — encrypted LAN control via tinytuya."""

import asyncio
import logging
from functools import partial

import tinytuya

from ..core import (
    DeviceBackend,
    DeviceConfig,
    DeviceOfflineError,
    DeviceState,
    mac_to_id,
    normalize_mac,
)

logger = logging.getLogger(__name__)

_TIMEOUT = 8
_RETRIES = 2
_RETRY_DELAY = 0.5

# DPS IDs — verified against target device (category: dlq / 断路器)
# DPS "1" is read-only physical position feedback; "12" is the remote control switch
_DPS_SWITCH = "12"
_DPS_VOLTAGE = "101"            # voltage in V (straight integer, e.g. 242 = 242V)
_DPS_WATTS_CANDIDATES = ("9", "13", "15", "5")  # skip "19" (bytes) and "21" (bool)


class TuyaBackend(DeviceBackend):
    can_rename_outlet = False
    can_rename_device = False
    session_timeout = 30.0
    command_interval = 0.3

    def __init__(self) -> None:
        self.ip: str | None = None

    async def probe(self, cfg: DeviceConfig) -> DeviceState:
        _require_credentials(cfg)
        try:
            state = await asyncio.to_thread(_sync_probe, cfg, self.ip)
            self.ip = cfg.last_known_ip or self.ip
            return state
        except DeviceOfflineError:
            raise
        except Exception as e:
            raise DeviceOfflineError(f"Tuya probe failed for {cfg.mac}: {e}") from e

    async def set_power(self, cfg: DeviceConfig, outlet_id: str | None, on: bool) -> None:
        _require_credentials(cfg)
        try:
            await asyncio.to_thread(_sync_set_power, cfg, self.ip, on)
        except DeviceOfflineError:
            raise
        except Exception as e:
            raise DeviceOfflineError(f"Tuya set_power failed for {cfg.mac}: {e}") from e

    async def close(self) -> None:
        pass


# ── Sync helpers (run in thread pool) ────────────────────────────────────────

def _sync_probe(cfg: DeviceConfig, cached_ip: str | None) -> DeviceState:
    device = _make_device(cfg, cached_ip)
    result = device.status()
    _check_result(result)
    dps: dict = result.get("dps") or {}
    is_on = bool(dps.get(_DPS_SWITCH, False))
    watts = _extract_watts(dps)
    return DeviceState(
        hw_alias=None,
        hw_model=None,
        hw_is_strip=False,
        is_on=is_on,
        children=[],
        watts=watts,
    )


def _sync_set_power(cfg: DeviceConfig, cached_ip: str | None, on: bool) -> None:
    device = _make_device(cfg, cached_ip)
    result = device.set_value(_DPS_SWITCH, on)
    _check_result(result)


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


def _extract_watts(dps: dict) -> float | None:
    for key in _DPS_WATTS_CANDIDATES:
        val = dps.get(key)
        # Skip bool and non-numeric types — bool is a subclass of int so check first
        if val is None or isinstance(val, bool) or isinstance(val, (bytes, str)):
            continue
        try:
            w = float(val)
            if w == 0:
                continue
            # Some devices report in tenths of a watt
            return w / 10.0 if w > 2000 else w
        except (TypeError, ValueError):
            pass
    return None


# ── Credential validation ─────────────────────────────────────────────────────

def _require_credentials(cfg: DeviceConfig) -> None:
    if not cfg.tuya_device_id or not cfg.tuya_local_key:
        raise DeviceOfflineError(
            f"Missing tuya_device_id or tuya_local_key for {cfg.mac}. "
            "Use the tuya-sync endpoint to fetch credentials."
        )


# ── Network scan ──────────────────────────────────────────────────────────────

async def scan(broadcasts: list[str]) -> list[DeviceConfig]:
    """Discover Tuya devices via UDP broadcast (v3.1/v3.3 only).

    v3.4/v3.5 devices do not broadcast — use cloud_fetch() to obtain their credentials.
    """
    return await asyncio.to_thread(_sync_scan, broadcasts)


def _sync_scan(broadcasts: list[str]) -> list[DeviceConfig]:
    raw = tinytuya.deviceScan(verbose=False, maxretry=6, poll=False)
    results: list[DeviceConfig] = []
    for ip, info in raw.items():
        mac = normalize_mac(info.get("mac", ""))
        if not mac:
            continue
        version = str(info.get("version", "3.1"))
        results.append(DeviceConfig(
            id=mac_to_id(mac),
            mac=mac,
            type="tuya",
            broadcast=broadcasts[0] if broadcasts else "255.255.255.255",
            last_known_ip=ip,
            tuya_device_id=info.get("gwId"),
            tuya_local_key=None,    # not available from broadcast
            hw_model=info.get("productKey"),
        ))
    return results


# ── Cloud credential fetch ────────────────────────────────────────────────────

async def cloud_fetch(
    api_key: str,
    api_secret: str,
    region: str,
) -> list[dict]:
    """Fetch all device credentials from Tuya IoT Platform.

    Returns list of dicts with keys: gwId, localKey, mac, ip, name, productName.
    """
    return await asyncio.to_thread(_sync_cloud_fetch, api_key, api_secret, region)


def _sync_cloud_fetch(api_key: str, api_secret: str, region: str) -> list[dict]:
    cloud = tinytuya.Cloud(
        apiRegion=region,
        apiKey=api_key,
        apiSecret=api_secret,
        apiDeviceID=None,
    )
    devices = cloud.getdevices()
    if not isinstance(devices, list):
        raise RuntimeError(f"Tuya Cloud error: {devices}")

    results = []
    for dev in devices:
        results.append({
            "gwId": dev.get("id") or dev.get("gwId", ""),
            "localKey": dev.get("local_key") or dev.get("localKey", ""),
            "mac": dev.get("mac", ""),
            "ip": dev.get("ip", ""),
            "name": dev.get("name", ""),
            "productName": dev.get("product_name") or dev.get("productName", ""),
        })
    return results

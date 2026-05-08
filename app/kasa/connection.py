"""Stateless Kasa network functions: connect, discover, build state."""

import asyncio
import logging
from datetime import datetime, timezone

from kasa import Credentials, Device, DeviceConfig, Discover
from kasa.exceptions import AuthenticationError

from ..models import ChildState, DeviceState, KasaDeviceConfig
from ..utils import normalize_mac

logger = logging.getLogger(__name__)

CONNECTION_TIMEOUT = 10
CONNECTION_RETRIES = 3
RETRY_DELAY = 0.5


async def connect_device(
    ip: str, credentials: Credentials | None = None
) -> tuple[Device | None, str | None]:
    """Attempt connection without credentials first, then with credentials if auth is required."""
    last_error: str | None = None

    logger.debug(f"Connecting to {ip} without credentials...")
    config_no_auth = DeviceConfig(host=ip, credentials=None, timeout=CONNECTION_TIMEOUT)

    for attempt in range(CONNECTION_RETRIES):
        try:
            device = await Device.connect(config=config_no_auth)
            await device.update()
            logger.debug(f"Connected to {ip} without credentials")
            return device, None
        except AuthenticationError as e:
            logger.debug(f"Device at {ip} requires authentication")
            last_error = f"{type(e).__name__}: {e}"
            break
        except Exception as e:
            last_error = f"{type(e).__name__}: {e}"
            if attempt < CONNECTION_RETRIES - 1:
                logger.debug(f"Connection to {ip} failed (attempt {attempt + 1}): {e}")
                await asyncio.sleep(RETRY_DELAY)

    if credentials:
        logger.debug(f"Connecting to {ip} with credentials...")
        config_with_auth = DeviceConfig(
            host=ip, credentials=credentials, timeout=CONNECTION_TIMEOUT
        )

        for attempt in range(CONNECTION_RETRIES):
            try:
                device = await Device.connect(config=config_with_auth)
                await device.update()
                logger.debug(f"Connected to {ip} with credentials")
                return device, None
            except Exception as e:
                last_error = f"{type(e).__name__}: {e}"
                if attempt < CONNECTION_RETRIES - 1:
                    logger.debug(
                        f"Connection to {ip} with auth failed (attempt {attempt + 1}): {e}"
                    )
                    await asyncio.sleep(RETRY_DELAY)

    return None, last_error


async def discover_device_ip(device_info: KasaDeviceConfig) -> str | None:
    """Discover a single device's current IP via broadcast."""
    target_mac = device_info.mac
    found_ip: str | None = None

    async def on_discovered(device: Device) -> None:
        nonlocal found_ip
        device_mac = getattr(device, "mac", None)
        if device_mac:
            try:
                if normalize_mac(device_mac) == target_mac:
                    found_ip = device.host
                    logger.info(f"Discovered {target_mac} at {found_ip}")
            except ValueError:
                pass

    await Discover.discover(target=device_info.broadcast, on_discovered=on_discovered)
    return found_ip


async def discover_all(whitelist: dict[str, KasaDeviceConfig]) -> dict[str, str]:
    """Discover all whitelisted Kasa devices. Returns MAC -> IP mapping."""
    logger.info("Starting Kasa device discovery...")

    targets: dict[str, list[KasaDeviceConfig]] = {}
    for info in whitelist.values():
        targets.setdefault(info.broadcast, []).append(info)

    result: dict[str, str] = {}

    for target, devices in targets.items():
        logger.info(f"Discovering on {target}...")
        device_macs = {d.mac for d in devices}

        async def on_discovered(device: Device) -> None:
            device_mac = getattr(device, "mac", None)
            if device_mac:
                try:
                    mac = normalize_mac(device_mac)
                    if mac in device_macs:
                        result[mac] = device.host
                        logger.info(f"Found device: {whitelist[mac].name} at {device.host}")
                except ValueError:
                    pass

        await Discover.discover(target=target, on_discovered=on_discovered)

    logger.info(f"Kasa discovery complete: {len(result)}/{len(whitelist)} devices found")
    return result


def build_device_state(device_info: KasaDeviceConfig, device: Device) -> DeviceState:
    """Build an online DeviceState from a connected Device object."""
    is_strip = hasattr(device, "children") and len(device.children) > 0
    children = None
    if is_strip:
        children = [
            ChildState(
                id=child.id if hasattr(child, "id") else str(i),
                alias=child.alias,
                is_on=child.is_on,
            )
            for i, child in enumerate(device.children)
        ]

    return DeviceState(
        id=device_info.id,
        name=device_info.name,
        status="online",
        is_on=device.is_on,
        alias=device.alias,
        model=device.model,
        is_strip=is_strip,
        children=children,
        last_updated=datetime.now().isoformat(),
        group=device_info.group,
    )

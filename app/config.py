"""Configuration management — loads device config and provides ID resolution."""

import json
import logging
from pathlib import Path

from .models import DeviceInfo
from .registry import PROTOCOLS
from .utils import mac_to_id, normalize_mac

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_DIR = Path(__file__).parent.parent / "config"


class ConfigManager:
    """Loads and manages the configured device list."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self._config_dir = config_dir or DEFAULT_CONFIG_DIR
        self._devices_path = self._config_dir / "devices.json"
        self._devices: dict[str, DeviceInfo] = {}
        self._id_to_mac: dict[str, str] = {}

    def load(self) -> dict[str, DeviceInfo]:
        """Load device config from config/devices.json."""
        if not self._devices_path.exists():
            logger.warning(f"Device config not found: {self._devices_path}")
            self._devices = {}
            self._id_to_mac = {}
            return self._devices

        with open(self._devices_path) as f:
            data = json.load(f)

        devices: dict[str, DeviceInfo] = {}
        id_to_mac: dict[str, str] = {}
        skipped = 0

        for device in data.get("devices", []):
            try:
                mac = normalize_mac(device["mac"])
                device_id = mac_to_id(mac)
                name = device.get("name") or device_id
                device_type = device.get("type")

                if not device_type:
                    raise ValueError(
                        f"Device '{name}' ({mac}) is missing required 'type' field"
                    )

                spec = PROTOCOLS.get(device_type)
                if not spec:
                    raise ValueError(
                        f"Device '{name}' ({mac}) has unsupported type '{device_type}'"
                    )

                devices[mac] = spec.parser(device, mac, name)
                id_to_mac[device_id] = mac
                logger.debug(f"  [{device_type}] {name} ({mac})")

            except (ValueError, KeyError) as e:
                logger.error(f"Skipping invalid device entry: {e}")
                skipped += 1

        self._devices = devices
        self._id_to_mac = id_to_mac

        by_type = {}
        for info in devices.values():
            by_type[info.type] = by_type.get(info.type, 0) + 1
        breakdown = ", ".join(f"{t}: {n}" for t, n in by_type.items())
        suffix = f", {skipped} skipped due to errors" if skipped else ""
        logger.info(f"Loaded {len(devices)} devices ({breakdown}{suffix})")

        return self._devices

    def resolve_id(self, device_id: str) -> str | None:
        """Resolve device ID to MAC address. Returns None if not found."""
        return self._id_to_mac.get(device_id)

    def get_device_id(self, mac: str) -> str | None:
        """Get device ID for a MAC address. Returns None if not configured."""
        mac = normalize_mac(mac)
        if mac in self._devices:
            return self._devices[mac].id
        return None

    @property
    def devices(self) -> dict[str, DeviceInfo]:
        return self._devices

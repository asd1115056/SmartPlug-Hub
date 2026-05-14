"""Configuration management — loads device config and provides ID resolution."""

import json
import logging
from collections import Counter
from pathlib import Path

from .models import DeviceInfo
from .registry import PROTOCOLS
from .utils import mac_to_id, normalize_mac

logger = logging.getLogger(__name__)

class ConfigManager:
    """Loads and manages the configured device list."""

    def __init__(self, devices_path: Path) -> None:
        self._devices_path = devices_path
        self._devices: dict[str, DeviceInfo] = {}

    def load(self) -> dict[str, DeviceInfo]:
        """Load device config from config/devices.json."""
        if not self._devices_path.exists():
            logger.warning(f"Device config not found: {self._devices_path}")
            self._devices = {}
            return self._devices

        logger.debug(f"Loading device config from {self._devices_path}")
        with open(self._devices_path) as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError(
                f"{self._devices_path.name}: expected a JSON object at the root, "
                f"got {type(data).__name__}"
            )

        devices: dict[str, DeviceInfo] = {}
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

                devices[device_id] = spec.parser(device, mac, name)

            except (ValueError, KeyError, TypeError) as e:
                logger.error(f"Skipping invalid device entry: {e}")
                skipped += 1

        self._devices = devices

        # summarise load result grouped by device type
        breakdown = ", ".join(
            f"{t}: {n}" for t, n in Counter(i.type for i in devices.values()).items()
        )
        suffix = f", {skipped} skipped due to errors" if skipped else ""
        logger.info(f"Loaded {len(devices)} devices ({breakdown}{suffix})")

        return self._devices

    @property
    def devices(self) -> dict[str, DeviceInfo]:
        return self._devices

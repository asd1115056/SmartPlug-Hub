"""Parse raw device config dicts into MiIO-specific config objects."""

from ..models import MiioDeviceConfig


def parse_config(raw: dict, mac: str, name: str) -> MiioDeviceConfig:
    """Parse a raw device dict into a MiioDeviceConfig."""
    broadcast = raw.get("broadcast", "")
    token = raw.get("token", "")
    miio_id = raw.get("miio_id", "")

    return MiioDeviceConfig(
        mac=mac,
        name=name,
        type="miio",
        group=raw.get("group"),
        broadcast=broadcast,
        token=token,
        miio_id=miio_id,
    )

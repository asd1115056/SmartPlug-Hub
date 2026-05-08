"""Parse raw device config dicts into Kasa-specific config objects."""

from kasa import Credentials

from ..models import KasaDeviceConfig


def parse_config(raw: dict, mac: str, name: str) -> KasaDeviceConfig:
    """Parse a raw device dict into a KasaDeviceConfig."""
    broadcast = raw.get("broadcast")
    if not broadcast:
        raise ValueError(f"Kasa device '{name}' ({mac}) missing required 'broadcast' field")

    credentials = None
    username = raw.get("username")
    password = raw.get("password")
    if username and password:
        credentials = Credentials(username=username, password=password)

    return KasaDeviceConfig(
        mac=mac,
        name=name,
        type="kasa",
        group=raw.get("group"),
        broadcast=broadcast,
        credentials=credentials,
    )

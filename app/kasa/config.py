"""Kasa-specific device config model and parser."""

from dataclasses import dataclass

from kasa import Credentials

from ..models import DeviceInfo


@dataclass
class KasaDeviceConfig(DeviceInfo):
    """Kasa protocol-specific configuration."""

    broadcast: str = ""
    credentials: Credentials | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.broadcast:
            raise ValueError(f"KasaDeviceConfig '{self.name}' missing required 'broadcast' field")


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

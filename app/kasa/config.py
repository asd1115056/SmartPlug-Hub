"""Kasa-specific device config model and parser."""

from dataclasses import dataclass

from kasa import Credentials

from ..core.models import DeviceInfo


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
    if not isinstance(broadcast, str) or not broadcast.strip():
        raise ValueError(
            f"Kasa device '{name}' ({mac}): 'broadcast' must be a non-empty string, "
            f"got {type(broadcast).__name__!r}"
        )

    username = raw.get("username")
    password = raw.get("password")
    if (username is None) != (password is None):
        raise ValueError(
            f"Kasa device '{name}' ({mac}): 'username' and 'password' must both be provided or both omitted"
        )
    if username is not None and not isinstance(username, str):
        raise ValueError(f"Kasa device '{name}' ({mac}): 'username' must be a string")
    if password is not None and not isinstance(password, str):
        raise ValueError(f"Kasa device '{name}' ({mac}): 'password' must be a string")

    credentials = Credentials(username=username, password=password) if username else None

    return KasaDeviceConfig(
        mac=mac,
        name=name,
        type="kasa",
        group=raw.get("group"),
        broadcast=broadcast,
        credentials=credentials,
    )

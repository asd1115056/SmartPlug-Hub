"""In-memory device configuration — pure dataclass, not managed by SQLAlchemy."""

from dataclasses import dataclass


@dataclass
class DeviceConfig:
    """Snapshot of device configuration stored in RAM. Never attached to a DB session."""

    id: str
    mac: str
    name: str
    type: str
    broadcast: str
    group_name: str | None
    account_id: int | None
    # hardware cache (updated after successful probe)
    alias: str | None
    model: str | None
    is_strip: bool
    last_known_ip: str | None
    # MiIO only
    token: str | None
    miio_id: str | None

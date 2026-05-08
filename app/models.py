"""
Shared data types, exceptions, and backend ABC.
"""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Literal

from kasa import Credentials

from .utils import mac_to_id


# === Custom Exceptions ===
class DeviceOfflineError(Exception):
    """Device confirmed offline (cannot connect after retries)."""
    pass


class DeviceOperationError(Exception):
    """Operation failed but device may still be online."""
    pass


# === Device Configuration ===
@dataclass
class DeviceInfo:
    """Base class for all device configurations. Protocol-agnostic fields only."""

    mac: str
    name: str
    type: str  # "kasa" | "miio"
    id: str = ""
    group: str | None = None

    def __post_init__(self):
        if not self.id:
            self.id = mac_to_id(self.mac)


@dataclass
class KasaDeviceConfig(DeviceInfo):
    """Kasa protocol-specific configuration."""

    broadcast: str = ""
    credentials: Credentials | None = None

    def __post_init__(self):
        super().__post_init__()
        if not self.broadcast:
            raise ValueError(f"KasaDeviceConfig '{self.name}' missing required 'broadcast' field")


# === Device State ===
@dataclass
class ChildState:
    """State of a single child outlet on a power strip."""

    id: str
    alias: str
    is_on: bool


@dataclass
class DeviceState:
    """Device state snapshot.

    - status="online": is_on, alias, model, children are live data
    - status="offline": is_on=None (untrustworthy), alias/model/is_strip/children
      retain last known topology for UI display
    """

    id: str
    name: str
    status: Literal["online", "offline"]
    is_on: bool | None = None
    alias: str | None = None
    model: str | None = None
    is_strip: bool = False
    children: list[ChildState] | None = None
    last_updated: str | None = None  # ISO format
    group: str | None = None


def build_offline_state(
    device_info: DeviceInfo, previous: DeviceState | None = None
) -> DeviceState:
    """Build an offline DeviceState, preserving topology from previous state."""
    return DeviceState(
        id=device_info.id,
        name=device_info.name,
        status="offline",
        is_on=None,
        alias=previous.alias if previous else None,
        model=previous.model if previous else None,
        is_strip=previous.is_strip if previous else False,
        children=previous.children if previous else None,
        last_updated=previous.last_updated if previous else None,
        group=device_info.group,
    )


# === Command (internal, not exposed in API) ===
class CommandStatus(Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class Command:
    """A device control command submitted to the queue."""

    id: str
    device_id: str
    action: str  # "on" / "off"
    child_id: str | None = None
    status: CommandStatus = CommandStatus.QUEUED
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    result: DeviceState | None = None
    error: str | None = None
    _event: asyncio.Event = field(default_factory=asyncio.Event)


# === Backend ABC ===
class DeviceBackend(ABC):
    """Abstract base class for protocol backends."""

    session_timeout: float = 0.0
    # How long CommandQueue processor waits after last command before exiting.
    # 0 = exit immediately (stateless); >0 = keep session (e.g. Kasa TCP 30s).
    # CommandQueue only uses this number — it has no knowledge of TCP vs UDP.

    command_interval: float = 0.0
    # Minimum interval between consecutive commands (rate limiting).

    @abstractmethod
    async def execute_command(self, cmd: Command, cfg: DeviceInfo) -> DeviceState:
        """Execute a command. Called by CommandQueue processor."""

    async def cleanup(self, device_id: str) -> None:
        """Called when processor exits (idle timeout or shutdown). Default no-op."""

    @abstractmethod
    async def refresh(self, cfg: DeviceInfo) -> DeviceState:
        """Re-discover + get fresh state (offline recovery, initialization)."""

    @abstractmethod
    async def health_check(self, cfg: DeviceInfo) -> DeviceState | None:
        """Periodic poll. Return None to skip this device this cycle."""

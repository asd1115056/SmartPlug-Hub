"""Shared data types, exceptions, and backend ABC."""

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Generic, Literal, TypeVar

from kasa import Credentials

from .utils import mac_to_id


class DeviceOfflineError(Exception):
    """Device confirmed offline (cannot connect after retries)."""


class DeviceOperationError(Exception):
    """Operation failed but device may still be online."""


@dataclass
class DeviceInfo:
    """Base class for all device configurations. Protocol-agnostic fields only."""

    mac: str
    name: str
    type: str  # "kasa" | "miio"
    id: str = ""
    group: str | None = None

    def __post_init__(self) -> None:
        if not self.id:
            self.id = mac_to_id(self.mac)


@dataclass
class KasaDeviceConfig(DeviceInfo):
    """Kasa protocol-specific configuration."""

    broadcast: str = ""
    credentials: Credentials | None = None

    def __post_init__(self) -> None:
        super().__post_init__()
        if not self.broadcast:
            raise ValueError(f"KasaDeviceConfig '{self.name}' missing required 'broadcast' field")


@dataclass
class ChildState:
    """State of a single child outlet on a power strip."""

    id: str
    alias: str | None
    is_on: bool


@dataclass
class DeviceState:
    """Snapshot of a device's state.

    status="online":  is_on, alias, model, children reflect live data.
    status="offline": is_on=None; alias/model/is_strip/children retain last
                      known topology so the UI can still render the device.
    """

    id: str
    name: str
    type: str
    status: Literal["online", "offline"]
    is_on: bool | None = None
    alias: str | None = None
    model: str | None = None
    is_strip: bool = False
    children: list[ChildState] | None = None
    last_updated: str | None = None  # ISO 8601
    group: str | None = None


def build_offline_state(
    device_info: DeviceInfo, previous: DeviceState | None = None
) -> DeviceState:
    """Build an offline DeviceState, preserving topology from previous state."""
    return DeviceState(
        id=device_info.id,
        name=device_info.name,
        type=device_info.type,
        status="offline",
        is_on=None,
        alias=previous.alias if previous else None,
        model=previous.model if previous else None,
        is_strip=previous.is_strip if previous else False,
        children=previous.children if previous else None,
        last_updated=previous.last_updated if previous else None,
        group=device_info.group,
    )


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
    action: str  # "on" | "off"
    child_id: str | None = None
    status: CommandStatus = CommandStatus.QUEUED
    created_at: datetime = field(default_factory=datetime.now)
    completed_at: datetime | None = None
    result: DeviceState | None = None
    error: str | None = None
    _event: asyncio.Event = field(default_factory=asyncio.Event)


_Cfg = TypeVar("_Cfg", bound="DeviceInfo")


class DeviceBackend(ABC, Generic[_Cfg]):
    """Protocol backend interface.

    session_timeout: seconds CommandQueue processor stays alive after the last
        command. 0 = exit immediately (stateless, e.g. MiIO UDP); >0 = keep the
        connection open (e.g. Kasa TCP 30 s). CommandQueue uses only this number
        and has no knowledge of the underlying transport.
    command_interval: minimum seconds between consecutive commands (rate limit).
    """

    session_timeout: float = 0.0
    command_interval: float = 0.0

    @abstractmethod
    async def execute_command(self, cmd: Command, cfg: _Cfg) -> DeviceState:
        """Execute a command. Called by CommandQueue processor."""

    async def cleanup(self, device_id: str) -> None:
        """Called when the processor exits. Default no-op."""

    @abstractmethod
    async def refresh(self, cfg: _Cfg, previous: DeviceState | None = None) -> DeviceState:
        """Re-discover and return current state (offline recovery / init)."""

    @abstractmethod
    async def health_check(self, cfg: _Cfg, previous: DeviceState | None = None) -> DeviceState | None:
        """Periodic poll. Return None to skip this device this cycle."""

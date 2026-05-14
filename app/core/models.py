"""Shared data types, exceptions, and backend ABC."""

from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import ClassVar, Generic, TypeVar

from .utils import mac_to_id


class DeviceStatus(Enum):
    ONLINE = "online"
    OFFLINE = "offline"


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



@dataclass(frozen=True)
class ChildState:
    """State of a single child outlet on a power strip."""

    id: str
    alias: str | None
    is_on: bool


@dataclass(frozen=True)
class DeviceState:
    """Immutable snapshot of device-reported state. is_on is None when OFFLINE."""

    id: str
    status: DeviceStatus
    is_on: bool | None = None
    alias: str | None = None
    model: str | None = None
    children: tuple[ChildState, ...] | None = None
    last_updated: datetime | None = None

    @property
    def is_strip(self) -> bool:
        return self.children is not None


def make_offline_state(
    device_id: str, previous: DeviceState | None = None
) -> DeviceState:
    """Build an offline snapshot, preserving topology from previous if available."""
    return DeviceState(
        id=device_id,
        status=DeviceStatus.OFFLINE,
        alias=previous.alias if previous else None,
        model=previous.model if previous else None,
        children=previous.children if previous else None,
        last_updated=previous.last_updated if previous else None,
    )


@dataclass
class Device:
    """Aggregate: per-device config, backend, and current state in one place."""

    info: DeviceInfo
    backend: DeviceBackend  # forward ref — DeviceBackend defined below
    state: DeviceState


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
    _future: asyncio.Future[DeviceState] | None = field(default=None, init=False, repr=False)


_Cfg = TypeVar("_Cfg", bound="DeviceInfo")


@dataclass(frozen=True)
class BackendPolicy:
    """Queue-visible behavioral parameters for a DeviceBackend.

    session_timeout: seconds to keep the processor and connection alive after the
        last command. 0 = stateless (exit and close immediately after each command).
    command_interval: minimum seconds between consecutive commands (rate limit).
        0 = no rate limit.
    """

    session_timeout: float = 0.0
    command_interval: float = 0.0


class DeviceBackend(ABC, Generic[_Cfg]):
    """Protocol backend interface. One instance per device."""

    policy: ClassVar[BackendPolicy] = BackendPolicy()

    def __init__(self) -> None:
        self.ip: str | None = None  # last known IP, updated by the backend

    @abstractmethod
    async def execute_command(self, cmd: Command, cfg: _Cfg) -> DeviceState:
        """Execute a command. Backend owns retry, rediscovery, and connection lifecycle."""

    @abstractmethod
    async def fetch_state(self, cfg: _Cfg, ip: str) -> DeviceState | None:
        """One-shot: connect to ip, verify identity, read state, disconnect.
        Returns None if unreachable or identity mismatch."""

    @abstractmethod
    async def find_ip(self, cfg: _Cfg) -> str | None:
        """Broadcast to locate this device's current IP. Returns IP or None."""

    async def close(self) -> None:
        """Close any open connections on application shutdown."""

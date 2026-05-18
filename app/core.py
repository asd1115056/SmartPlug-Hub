"""Shared abstractions — exceptions, runtime models, device config, backend interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ── Exceptions ────────────────────────────────────────────────────────────────

class DeviceError(Exception):
    """Base for device-level errors."""

class DeviceOfflineError(DeviceError):
    """Operation attempted on an unreachable device."""

class DeviceNotFoundError(DeviceError):
    """device_id does not exist in the runtime registry."""


class AccountError(Exception):
    """Base for account-level errors."""

class AccountInUseError(AccountError):
    """Removing an account that still has devices bound to it."""


# ── Runtime models (RAM only) ─────────────────────────────────────────────────

@dataclass
class ChildState:
    outlet_id: str      # Kasa: child.device_id / MiIO: str(index)
    hw_alias: str | None
    is_on: bool


@dataclass
class DeviceState:
    hw_alias: str | None
    hw_model: str | None
    hw_is_strip: bool
    is_on: bool
    children: list[ChildState] = field(default_factory=list)


# ── Device config (passed to backends) ───────────────────────────────────────

@dataclass(frozen=True)
class DeviceConfig:
    id: str
    mac: str
    type: str           # "kasa" | "miio"
    broadcast: str
    last_known_ip: str | None
    username: str | None = None     # Kasa
    password: str | None = None     # Kasa
    miio_token: str | None = None
    miio_id: str | None = None


# ── Backend interface ─────────────────────────────────────────────────────────

class DeviceBackend(ABC):
    can_rename_outlet: bool = False
    can_rename_device: bool = False

    @abstractmethod
    async def probe(self, cfg: DeviceConfig) -> DeviceState:
        """Connect to the device and return its current state."""

    @abstractmethod
    async def set_power(self, cfg: DeviceConfig, outlet_id: str | None, on: bool) -> None:
        """Turn an outlet (or the whole device) on or off."""

    async def rename_outlet(self, cfg: DeviceConfig, outlet_id: str, name: str) -> None:
        raise NotImplementedError

    async def rename_device(self, cfg: DeviceConfig, name: str) -> None:
        raise NotImplementedError

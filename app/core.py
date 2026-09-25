"""Shared abstractions — exceptions, runtime models, device config, backend interface, utilities."""

import hashlib
import secrets
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


# ── Exceptions ────────────────────────────────────────────────────────────────

class DeviceError(Exception):
    """Base for device-level errors."""

class DeviceOfflineError(DeviceError):
    """Operation attempted on an unreachable device."""

class DeviceRejectedError(DeviceError):
    """Device is reachable but refused the command."""

class DeviceNotFoundError(DeviceError):
    """device_id does not exist in the runtime registry."""


# ── Runtime models (RAM only) ─────────────────────────────────────────────────

@dataclass
class ChildState:
    outlet_id: str      # Kasa: child.device_id / MiIO: str(index)
    hw_alias: str | None
    is_on: bool
    watts: float | None = None


@dataclass
class DeviceState:
    hw_alias: str | None
    hw_model: str | None
    hw_is_strip: bool
    is_on: bool
    children: list[ChildState] = field(default_factory=list)
    watts: float | None = None


# ── Device config (passed to backends) ───────────────────────────────────────

@dataclass(frozen=True)
class DeviceConfig:
    id: str
    mac: str
    type: str           # "kasa" | "miio" | "tuya"
    broadcast: str
    last_known_ip: str | None
    username: str | None = None     # Kasa
    password: str | None = None     # Kasa
    miio_token: str | None = None
    miio_id: str | None = None
    tuya_device_id: str | None = None
    tuya_local_key: str | None = None
    tuya_product_id: str | None = None
    hw_model: str | None = None

    @property
    def ip(self) -> str:
        """The address backends connect to; DeviceService resolves it before every command."""
        if self.last_known_ip is None:
            raise DeviceOfflineError(f"No IP known for {self.mac}")
        return self.last_known_ip


# ── Backend interface ─────────────────────────────────────────────────────────

class DeviceBackend(ABC):
    can_rename_outlet: bool = False
    can_rename_device: bool = False
    session_timeout: float = 0.0        # 0 = stateless (MiIO); >0 = keep TCP alive this long
    command_interval: float = 0.0       # minimum seconds between consecutive commands

    def is_configured(self, cfg: DeviceConfig) -> bool:
        """Return True if cfg has the minimum credentials needed to attempt a connection."""
        return False

    @abstractmethod
    async def discover(self, cfg: DeviceConfig) -> str | None:
        """Search the LAN for this device (by MAC or device id); return its IP, or None."""

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

    async def close(self) -> None:
        """Release any persistent connection. No-op by default."""


# ── Utilities ─────────────────────────────────────────────────────────────────

def normalize_mac(mac: str) -> str:
    """Normalize MAC to uppercase hex with no separators: 'AA:BB:CC' → 'AABBCC'."""
    return mac.replace(":", "").replace("-", "").upper()


def mac_to_id(mac: str) -> str:
    """Derive a stable 8-char device ID from a MAC address."""
    return hashlib.sha256(normalize_mac(mac).encode()).hexdigest()[:8]


def tokens_match(given: str | None, expected: str) -> bool:
    """Constant-time token comparison, so response timing doesn't leak the token."""
    if given is None:
        return False
    # Compare bytes: compare_digest rejects non-ASCII str, and tokens are user-chosen
    return secrets.compare_digest(given.encode(), expected.encode())

"""Protocol registry — single source of truth for supported backend protocols."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from ..kasa import KasaBackend, discover_all as kasa_discover
from ..miio import MiioBackend, discover_all as miio_discover
from .backend import DeviceBackend


@dataclass(frozen=True)
class ProtocolSpec:
    backend: Callable[[], DeviceBackend]  # zero-arg factory, one instance per device
    discover_all: Callable[[dict], Awaitable[dict[str, str]]]


# To add a new protocol: import its backend/discover, add one entry here.
PROTOCOLS: dict[str, ProtocolSpec] = {
    "kasa": ProtocolSpec(backend=KasaBackend, discover_all=kasa_discover),
    "miio": ProtocolSpec(backend=MiioBackend, discover_all=miio_discover),
}

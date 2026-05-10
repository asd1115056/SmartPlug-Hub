"""Protocol registry — single source of truth for supported backend protocols."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .kasa import KasaBackend, discover_all as kasa_discover, parse_config as kasa_parse
from .miio import MiioBackend, discover_all as miio_discover, parse_config as miio_parse
from .models import DeviceBackend, DeviceInfo, KasaDeviceConfig, MiioDeviceConfig


@dataclass(frozen=True)
class ProtocolSpec:
    parser: Callable[[dict, str, str], DeviceInfo]
    backend: Callable[[dict[str, str]], DeviceBackend]  # factory: ip_cache -> backend
    discover: Callable[[dict], Awaitable[dict[str, str]]]
    model: type[DeviceInfo]


# To add a new protocol: import its parser/backend/discover, add one entry here.
PROTOCOLS: dict[str, ProtocolSpec] = {
    "kasa": ProtocolSpec(
        parser=kasa_parse,
        backend=KasaBackend,
        discover=kasa_discover,
        model=KasaDeviceConfig,
    ),
    "miio": ProtocolSpec(
        parser=miio_parse,
        backend=MiioBackend,
        discover=miio_discover,
        model=MiioDeviceConfig,
    ),
}

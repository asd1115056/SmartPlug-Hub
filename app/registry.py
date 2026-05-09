"""Protocol registry — single source of truth for supported backend protocols."""

from dataclasses import dataclass
from typing import Callable

from .kasa import KasaBackend, discover_all as kasa_discover, parse_config as kasa_parse
from .models import KasaDeviceConfig


@dataclass(frozen=True)
class ProtocolSpec:
    parser: Callable    # (raw: dict, mac: str, name: str) -> DeviceInfo
    backend: type       # DeviceBackend subclass; __init__ takes ip_cache: dict
    discover: Callable  # async (known_devices: dict) -> dict[str, str]
    model: type         # DeviceInfo subclass used by this protocol


# To add a new protocol: import its parser/backend/discover, add one entry here.
PROTOCOLS: dict[str, ProtocolSpec] = {
    "kasa": ProtocolSpec(
        parser=kasa_parse,
        backend=KasaBackend,
        discover=kasa_discover,
        model=KasaDeviceConfig,
    ),
    # "miio": ProtocolSpec(
    #     parser=miio_parse,
    #     backend=MiioBackend,
    #     discover=miio_discover,
    #     model=MiioDeviceConfig,
    # ),
}

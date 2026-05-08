"""
Protocol registry — the single place to register a new backend protocol.

To add a new protocol (e.g. Tuya):
  1. Create app/tuya/ subpackage with parse_config, TuyaBackend, discover_all
  2. Add one entry to PROTOCOLS below
  3. Nothing else needs to change
"""

from dataclasses import dataclass
from typing import Callable

from .kasa import KasaBackend, discover_all as kasa_discover, parse_config as kasa_parse
from .models import KasaDeviceConfig


@dataclass(frozen=True)
class ProtocolSpec:
    parse_config: Callable  # (raw: dict, mac: str, name: str) -> DeviceInfo
    backend_class: type     # DeviceBackend subclass; __init__ takes ip_cache: dict
    discover_all: Callable  # async (whitelist: dict) -> dict[str, str]
    config_class: type      # DeviceInfo subclass used by this protocol


PROTOCOLS: dict[str, ProtocolSpec] = {
    "kasa": ProtocolSpec(
        parse_config=kasa_parse,
        backend_class=KasaBackend,
        discover_all=kasa_discover,
        config_class=KasaDeviceConfig,
    ),
    # "miio": ProtocolSpec(
    #     parse_config=miio_parse,
    #     backend_class=MiioBackend,
    #     discover_all=miio_discover,
    #     config_class=MiioDeviceConfig,
    # ),
}

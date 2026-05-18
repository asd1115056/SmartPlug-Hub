"""Load application settings from config/settings.toml."""

import tomllib
from pathlib import Path

_CONFIG_PATH = Path(__file__).parent.parent.parent / "config" / "settings.toml"

_data: dict = {}
if _CONFIG_PATH.exists():
    with _CONFIG_PATH.open("rb") as _f:
        _data = tomllib.load(_f)


def get_admin_token() -> str:
    return _data.get("admin", {}).get("token", "")

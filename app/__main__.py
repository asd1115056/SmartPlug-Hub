"""Entry point — run with `python -m app` or `smartplug-hub`."""

import argparse
import sys

import uvicorn

from .logging import build_log_config
from .main import SettingsError, load_admin_token


def main() -> None:
    parser = argparse.ArgumentParser(description="SmartPlug Hub")
    parser.add_argument(
        "--host", default="0.0.0.0", help="Address to listen on (default: all interfaces)",
    )
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--debug", action="store_true", help="Enable debug logging for app.*")
    args = parser.parse_args()
    # Checked here too so a bad settings file is one line, not a startup traceback
    try:
        load_admin_token()
    except SettingsError as e:
        sys.exit(f"Error: {e}")
    uvicorn.run(
        "app.main:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_config=build_log_config(args.debug),
        timeout_graceful_shutdown=5,
    )


if __name__ == "__main__":
    main()

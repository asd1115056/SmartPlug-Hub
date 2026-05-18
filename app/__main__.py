"""Entry point — run with `python -m app` or `smartplug-hub`."""

import argparse

import uvicorn

from .logging import build_log_config


def main() -> None:
    parser = argparse.ArgumentParser(description="SmartPlug Hub")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--debug", action="store_true", help="Enable debug logging for app.*")
    args = parser.parse_args()
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=args.port,
        reload=False,
        log_config=build_log_config(args.debug),
    )


if __name__ == "__main__":
    main()

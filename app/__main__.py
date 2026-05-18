"""Entry point — run with `python -m app` or `smartplug-hub`."""

import argparse

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="SmartPlug Hub")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    uvicorn.run("app.main:app", host="0.0.0.0", port=args.port, reload=False)


if __name__ == "__main__":
    main()

"""Entry point: python -m app  OR  uv run smartplug-hub"""

import os

import uvicorn


def main() -> None:
    port = int(os.getenv("PORT", "8000"))
    reload = os.getenv("RELOAD", "").lower() in ("1", "true", "yes")
    uvicorn.run("app.main:app", host="0.0.0.0", port=port, reload=reload)


if __name__ == "__main__":
    main()

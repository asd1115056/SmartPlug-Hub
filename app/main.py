"""FastAPI app — public API, SSE, static files, lifespan."""

import asyncio
import json
import logging
import tomllib
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .admin.router import router as admin_router
from .core import DeviceNotFoundError, DeviceOfflineError, DeviceRejectedError, tokens_match
from .db import DB_PATH, Database
from .device_service import DeviceEntry, DeviceService
from .schemas import DeviceOut, SetPowerRequest, build_device_out

logger = logging.getLogger(__name__)

# Anchored to the repo, not the working directory, so the service starts from anywhere
_ROOT = Path(__file__).resolve().parent.parent
_SETTINGS_PATH = _ROOT / "config" / "settings.toml"
_STATIC_DIR = _ROOT / "static"


class SettingsError(Exception):
    """config/settings.toml is missing or unusable."""


def load_admin_token(path: Path = _SETTINGS_PATH) -> str:
    if not path.exists():
        raise SettingsError(
            f"{path} not found: copy config/settings.toml.example to it and set [admin] token"
        )
    try:
        with path.open("rb") as f:
            cfg = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise SettingsError(f"{path} is not valid TOML: {e}") from e
    admin = cfg.get("admin")
    token = admin.get("token") if isinstance(admin, dict) else None
    if not isinstance(token, str) or not token.strip():
        raise SettingsError(f"{path} needs a non-empty token under [admin]")
    return token


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.admin_token = load_admin_token()

    db = Database(DB_PATH)
    await db.initialize()
    app.state.db = db

    svc = DeviceService(db)
    await svc.start()
    app.state.device_service = svc

    yield

    await svc.stop()
    await db.close()


app = FastAPI(lifespan=lifespan)
app.include_router(admin_router)
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


def _svc(request: Request) -> DeviceService:
    return request.app.state.device_service


def _visible_devices(svc: DeviceService) -> list[DeviceEntry]:
    return [e for e in svc.get_devices() if not e.is_hidden]


def _visible_device(svc: DeviceService, device_id: str) -> DeviceEntry:
    """A hidden device answers 404 exactly like a missing one, so its id can't be probed."""
    entry = svc.find_device(device_id)
    if entry is None or entry.is_hidden:
        raise HTTPException(status_code=404, detail="Device not found")
    return entry


# ── HTML pages ────────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse(_STATIC_DIR / "index.html")


@app.get("/admin")
async def admin_page() -> FileResponse:
    return FileResponse(_STATIC_DIR / "admin.html")


# ── Public API ────────────────────────────────────────────────────────────────

@app.get("/api/v1/devices", response_model=list[DeviceOut])
async def list_devices(svc: DeviceService = Depends(_svc)) -> list[DeviceOut]:
    return [build_device_out(e) for e in _visible_devices(svc)]


@app.get("/api/v1/devices/{device_id}", response_model=DeviceOut)
async def get_device(device_id: str, svc: DeviceService = Depends(_svc)) -> DeviceOut:
    return build_device_out(_visible_device(svc, device_id))


@app.patch("/api/v1/devices/{device_id}", response_model=DeviceOut)
async def set_power(
    device_id: str,
    body: SetPowerRequest,
    svc: DeviceService = Depends(_svc),
) -> DeviceOut:
    entry = _visible_device(svc, device_id)
    # Strips only expose per-outlet tokens, so a whole-strip command would need no token.
    # The backends re-check after connecting, for a device never polled (no DB snapshot yet).
    if body.outlet_id is None and entry.hw.is_strip:
        raise HTTPException(status_code=400, detail="outlet_id is required for a power strip")
    if body.outlet_id is not None:
        required_token = entry.outlet_tokens.get(body.outlet_id)
    else:
        required_token = entry.device_token
    if required_token is not None and not tokens_match(body.token, required_token):
        detail = "Token required" if body.token is None else "Invalid token"
        raise HTTPException(status_code=403, detail=detail)
    try:
        await svc.set_power(device_id, body.outlet_id, body.on)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")
    except ValueError as e:
        # Backends raise ValueError for an outlet_id the device doesn't have, or a missing
        # one on a strip the API couldn't recognise yet (no successful poll since startup)
        raise HTTPException(status_code=404, detail=str(e))
    except DeviceOfflineError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except DeviceRejectedError as e:
        # 502, not 503: the device was reached and gave a definitive refusal
        raise HTTPException(status_code=502, detail=str(e))
    return build_device_out(svc.get_device(device_id))


@app.post("/api/v1/devices/{device_id}/refresh", response_model=DeviceOut)
async def refresh_device(device_id: str, svc: DeviceService = Depends(_svc)) -> DeviceOut:
    _visible_device(svc, device_id)
    try:
        await svc.refresh(device_id)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")
    except DeviceOfflineError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except DeviceRejectedError as e:
        # 502, not 503: the device was reached and gave a definitive refusal
        raise HTTPException(status_code=502, detail=str(e))
    return build_device_out(svc.get_device(device_id))


# ── SSE ───────────────────────────────────────────────────────────────────────

@app.get("/api/v1/events")
async def sse_stream(request: Request, svc: DeviceService = Depends(_svc)) -> StreamingResponse:
    q = svc.subscribe()

    def _payload() -> str:
        devices = [build_device_out(e).model_dump(mode='json') for e in _visible_devices(svc)]
        return f"data: {json.dumps(devices)}\n\n"

    async def generate() -> AsyncGenerator[str, None]:
        try:
            yield _payload()
            while True:
                try:
                    await asyncio.wait_for(q.get(), timeout=5.0)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield _payload()
        except asyncio.CancelledError:
            pass
        finally:
            svc.unsubscribe(q)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

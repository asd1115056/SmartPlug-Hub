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
from .db import Database
from .device_service import DeviceService
from .schemas import DeviceOut, SetPowerRequest, build_device_out

logger = logging.getLogger(__name__)

# Anchored to the repo, not the working directory, so the service starts from anywhere
_ROOT = Path(__file__).resolve().parent.parent
_DB_PATH = _ROOT / "data" / "smartplug.db"
_SETTINGS_PATH = _ROOT / "config" / "settings.toml"
_STATIC_DIR = _ROOT / "static"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    with _SETTINGS_PATH.open("rb") as f:
        cfg = tomllib.load(f)
    app.state.admin_token = cfg["admin"]["token"]

    db = Database(_DB_PATH)
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
    return [build_device_out(e) for e in svc.get_devices()]


@app.get("/api/v1/devices/{device_id}", response_model=DeviceOut)
async def get_device(device_id: str, svc: DeviceService = Depends(_svc)) -> DeviceOut:
    try:
        return build_device_out(svc.get_device(device_id))
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")


@app.patch("/api/v1/devices/{device_id}", response_model=DeviceOut)
async def set_power(
    device_id: str,
    body: SetPowerRequest,
    svc: DeviceService = Depends(_svc),
) -> DeviceOut:
    try:
        entry = svc.get_device(device_id)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")
    # Strips only expose per-outlet tokens, so a whole-strip command would need no token.
    # The backends re-check after connecting, for the window before the first poll.
    if body.outlet_id is None and entry.state is not None and entry.state.hw_is_strip:
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
        devices = [build_device_out(e).model_dump(mode='json') for e in svc.get_devices()]
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

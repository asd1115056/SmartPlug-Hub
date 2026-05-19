"""FastAPI app — public API, SSE, static files, lifespan."""

import asyncio
import json
import logging
import tomllib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .admin.router import router as admin_router
from .core import DeviceNotFoundError, DeviceOfflineError
from .db import Database
from .device_service import DeviceService
from .schemas import DeviceOut, SetPowerRequest, build_device_out

logger = logging.getLogger(__name__)

_DB_PATH = Path("data/smartplug.db")
_SETTINGS_PATH = Path("config/settings.toml")


@asynccontextmanager
async def lifespan(app: FastAPI):
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
app.mount("/static", StaticFiles(directory="static"), name="static")


def _svc(request: Request) -> DeviceService:
    return request.app.state.device_service


# ── HTML pages ────────────────────────────────────────────────────────────────

@app.get("/")
async def index() -> FileResponse:
    return FileResponse("static/index.html")


@app.get("/admin")
async def admin_page() -> FileResponse:
    return FileResponse("static/admin.html")


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
        await svc.set_power(device_id, body.outlet_id, body.on)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")
    except DeviceOfflineError:
        raise HTTPException(status_code=503, detail="Device offline")
    return build_device_out(svc.get_device(device_id))


@app.post("/api/v1/devices/{device_id}/refresh", response_model=DeviceOut)
async def refresh_device(device_id: str, svc: DeviceService = Depends(_svc)) -> DeviceOut:
    try:
        await svc.refresh(device_id)
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")
    except DeviceOfflineError:
        raise HTTPException(status_code=503, detail="Device offline")
    return build_device_out(svc.get_device(device_id))


# ── SSE ───────────────────────────────────────────────────────────────────────

@app.get("/api/v1/events")
async def sse_stream(request: Request, svc: DeviceService = Depends(_svc)) -> StreamingResponse:
    q = svc.subscribe()

    def _payload() -> str:
        devices = [build_device_out(e).model_dump(mode='json') for e in svc.get_devices()]
        return f"data: {json.dumps(devices)}\n\n"

    async def generate():
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

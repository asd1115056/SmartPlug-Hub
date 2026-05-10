"""SmartPlug Hub - FastAPI backend with per-device command queue and multi-protocol support."""

import logging
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .device_manager import DeviceManager
from .models import DeviceOfflineError, DeviceOperationError

PROJECT_ROOT = Path(__file__).parent.parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

device_manager: DeviceManager | None = None


# === Pydantic Models ===
class ControlRequest(BaseModel):
    is_on: bool
    child_id: str | None = None


def _err(error: str, message: str) -> dict:
    return {"error": error, "message": message}


def _state_to_dict(state) -> dict:
    """Convert DeviceState dataclass to dict for JSON response."""
    d = asdict(state)
    if d.get("children") is None:
        d.pop("children", None)
    return d


# === Dependency ===
def get_device_manager() -> DeviceManager:
    if not device_manager:
        raise HTTPException(
            status_code=503,
            detail=_err("service_unavailable", "Device manager not initialized"),
        )
    return device_manager


# === Lifecycle ===
@asynccontextmanager
async def lifespan(app: FastAPI):
    global device_manager

    logger.info("Starting SmartPlug Hub...")
    device_manager = DeviceManager()
    await device_manager.initialize()

    yield

    logger.info("Shutting down SmartPlug Hub...")
    if device_manager:
        await device_manager.shutdown()


# === App ===
app = FastAPI(
    title="SmartPlug Hub",
    description="Multi-protocol web controller for smart plugs and power strips",
    lifespan=lifespan,
)


# === API v1 Endpoints ===
@app.get("/api/v1/devices")
def list_devices(dm: DeviceManager = Depends(get_device_manager)):
    """Get cached status of all devices (zero I/O)."""
    states = dm.get_all_states()
    return {"devices": [_state_to_dict(s) for s in states]}


@app.get("/api/v1/devices/{device_id}")
def get_device(device_id: str, dm: DeviceManager = Depends(get_device_manager)):
    """Get a single device's cached status."""
    try:
        state = dm.get_device_state(device_id)
        return _state_to_dict(state)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=_err("not_found", str(e)))


@app.patch("/api/v1/devices/{device_id}")
async def control_device(
    device_id: str,
    request: ControlRequest,
    dm: DeviceManager = Depends(get_device_manager),
):
    """Control a device (on/off). Blocks until operation completes."""
    action = "on" if request.is_on else "off"
    try:
        state = await dm.control_device(
            device_id=device_id,
            action=action,
            child_id=request.child_id,
        )
        return _state_to_dict(state)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=_err("invalid_request", str(e)))
    except DeviceOfflineError as e:
        raise HTTPException(status_code=503, detail=_err("offline", str(e)))
    except DeviceOperationError as e:
        if "timed out" in str(e).lower():
            raise HTTPException(status_code=504, detail=_err("timeout", str(e)))
        raise HTTPException(status_code=502, detail=_err("operation_failed", str(e)))
    except Exception as e:
        logger.error(f"Failed to control device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=_err("internal_error", str(e)))


@app.post("/api/v1/devices/{device_id}/refresh")
async def refresh_device(
    device_id: str, dm: DeviceManager = Depends(get_device_manager)
):
    """Refresh a single device (discover + connect). For offline recovery."""
    try:
        state = await dm.refresh_device(device_id)
        code = 200 if state.status == "online" else 503
        return JSONResponse(content=_state_to_dict(state), status_code=code)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=_err("not_found", str(e)))
    except Exception as e:
        logger.error(f"Failed to refresh device {device_id}: {e}")
        raise HTTPException(status_code=500, detail=_err("internal_error", str(e)))


# === Static Files & Root ===
app.mount("/static", StaticFiles(directory=PROJECT_ROOT / "static"), name="static")


@app.get("/")
async def root():
    return FileResponse(PROJECT_ROOT / "static/index.html")


# === Entry Point ===
def run():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    run()

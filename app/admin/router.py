"""Admin API — device management."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from ..backends.kasa import scan as kasa_scan
from ..backends.miio import scan as miio_scan
from ..backends.tuya import scan as tuya_scan
from ..core import DeviceNotFoundError, DeviceOfflineError, DeviceRejectedError, normalize_mac
from ..db import Database, Device as DeviceRow
from ..device_service import DeviceService
from ..network import get_interface_pairs
from ..schemas import (
    AddDeviceRequest,
    AdminDeviceOut,
    DiscoveredDeviceOut,
    SetNameRequest,
    SetOutletTokenRequest,
    UpdateDeviceRequest,
    build_admin_device_out,
)
from . import service
from .auth import require_admin

router = APIRouter(prefix="/admin/api", dependencies=[Depends(require_admin)])


def _db(request: Request) -> Database:
    return request.app.state.db


def _svc(request: Request) -> DeviceService:
    return request.app.state.device_service


async def _require_device(device_id: str, db: Database) -> DeviceRow:
    row = await db.get_device(device_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Device not found")
    return row


# ── Auth ──────────────────────────────────────────────────────────────────────

@router.get("/login")
async def login() -> dict:
    """Token validation endpoint — 200 means the token is valid."""
    return {"ok": True}


# ── Devices ───────────────────────────────────────────────────────────────────

@router.get("/devices", response_model=list[AdminDeviceOut])
async def list_devices(
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> list[AdminDeviceOut]:
    rows = await db.get_devices()
    entries = {e.config.id: e for e in svc.get_devices()}
    return [build_admin_device_out(row, entries.get(row.id)) for row in rows]


@router.post("/scan", response_model=list[DiscoveredDeviceOut])
async def scan_network(db: Database = Depends(_db)) -> list[DiscoveredDeviceOut]:
    iface_pairs = get_interface_pairs()
    if not iface_pairs:
        raise HTTPException(status_code=503, detail="No usable network interfaces found")

    existing_rows = await db.get_devices()
    existing: dict[str, DeviceRow] = {normalize_mac(d.mac): d for d in existing_rows}

    results = await asyncio.gather(
        kasa_scan(iface_pairs), miio_scan(iface_pairs), tuya_scan(iface_pairs),
        return_exceptions=True,
    )

    seen_macs: set[str] = set()
    found: list[DiscoveredDeviceOut] = []
    for r in results:
        if isinstance(r, list):
            for d in r:
                if d.mac in seen_macs:
                    continue
                seen_macs.add(d.mac)
                registered = existing.get(d.mac)
                found.append(DiscoveredDeviceOut(
                    mac=d.mac,
                    type=d.type,
                    broadcast=d.broadcast,
                    ip=d.last_known_ip or "",
                    model=d.hw_model,
                    miio_id=d.miio_id,
                    tuya_device_id=d.tuya_device_id,
                    tuya_local_key=d.tuya_local_key,
                    tuya_product_id=d.tuya_product_id,
                    is_registered=registered is not None,
                    registered_name=registered.name or registered.hw_alias if registered else None,
                ))
    return found


@router.post("/devices", response_model=AdminDeviceOut, status_code=201)
async def create_device(
    body: AddDeviceRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    try:
        row = await service.add_device(
            body.mac, body.type, body.broadcast, db, svc,
            group_name=body.group_name,
            kasa_username=body.kasa_username,
            kasa_password=body.kasa_password,
            miio_token=body.miio_token,
            miio_id=body.miio_id,
            tuya_device_id=body.tuya_device_id,
            tuya_local_key=body.tuya_local_key,
            tuya_product_id=body.tuya_product_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    return build_admin_device_out(row, svc.find_device(row.id))


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(
    device_id: str,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> None:
    await service.remove_device(device_id, db, svc)


@router.patch("/devices/{device_id}", response_model=AdminDeviceOut)
async def update_device(
    device_id: str,
    body: UpdateDeviceRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    """Partial update of name, group, device token and the type's credentials."""
    await _require_device(device_id, db)
    try:
        row = await service.update_device(
            device_id, body.model_dump(exclude_unset=True), db, svc,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except DeviceNotFoundError:
        raise HTTPException(status_code=404, detail="Device not found")
    return build_admin_device_out(row, svc.find_device(device_id))


@router.patch("/devices/{device_id}/outlets/{outlet_id}/name", response_model=AdminDeviceOut)
async def set_outlet_name(
    device_id: str,
    outlet_id: str,
    body: SetNameRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    row = await _require_device(device_id, db)
    try:
        await service.set_outlet_name(device_id, outlet_id, body.name, db, svc)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except DeviceOfflineError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except DeviceRejectedError as e:
        # 502, not 503: the device was reached and gave a definitive refusal
        raise HTTPException(status_code=502, detail=str(e))
    except DeviceNotFoundError:
        # Removed (or re-created by a credentials update) while the rename was queued
        raise HTTPException(status_code=404, detail="Device not found")
    return build_admin_device_out(row, svc.find_device(device_id))


@router.patch("/devices/{device_id}/outlets/{outlet_id}/token", response_model=AdminDeviceOut)
async def set_outlet_token(
    device_id: str,
    outlet_id: str,
    body: SetOutletTokenRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    await _require_device(device_id, db)
    token = body.token.strip() if body.token else None
    await db.set_outlet_token(device_id, outlet_id, token)
    svc.set_outlet_token(device_id, outlet_id, token)
    row = await db.get_device(device_id)
    assert row is not None
    return build_admin_device_out(row, svc.find_device(device_id))

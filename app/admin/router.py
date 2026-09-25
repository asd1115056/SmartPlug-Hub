"""Admin API — device management."""

import asyncio

from fastapi import APIRouter, Depends, HTTPException, Request

from ..backends.kasa import scan as kasa_scan
from ..backends.miio import scan as miio_scan
from ..backends.tuya import scan as tuya_scan
from ..core import DeviceOfflineError, DeviceRejectedError, normalize_mac
from ..db import Database, Device as DeviceRow
from ..device_service import DeviceService
from ..network import get_interface_pairs
from ..schemas import (
    AddDeviceRequest,
    AdminDeviceOut,
    DiscoveredDeviceOut,
    SetDeviceTokenRequest,
    SetGroupRequest,
    SetKasaCredentialsRequest,
    SetMiioCredentialsRequest,
    SetOutletTokenRequest,
    SetTuyaCredentialsRequest,
    SetNameRequest,
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
    all_outlet_tokens = await db.get_all_outlet_tokens()
    return [
        build_admin_device_out(row, entries.get(row.id), all_outlet_tokens.get(row.id, {}))
        for row in rows
    ]


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
    return build_admin_device_out(row, svc._devices.get(row.id))


@router.delete("/devices/{device_id}", status_code=204)
async def delete_device(
    device_id: str,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> None:
    await service.remove_device(device_id, db, svc)


@router.patch("/devices/{device_id}/group", response_model=AdminDeviceOut)
async def set_device_group(
    device_id: str,
    body: SetGroupRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    row = await _require_device(device_id, db)
    await service.set_device_group_name(device_id, body.group_name or None, db, svc)
    row.group_name = body.group_name or None
    return build_admin_device_out(row, svc._devices.get(device_id))


@router.patch("/devices/{device_id}/name", response_model=AdminDeviceOut)
async def set_device_name(
    device_id: str,
    body: SetNameRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    row = await _require_device(device_id, db)
    try:
        await service.set_device_name(device_id, body.name, db, svc)
    except DeviceOfflineError as e:
        raise HTTPException(status_code=503, detail=str(e))
    row.name = body.name
    return build_admin_device_out(row, svc._devices.get(device_id))


@router.patch("/devices/{device_id}/miio-credentials", response_model=AdminDeviceOut)
async def set_miio_credentials(
    device_id: str,
    body: SetMiioCredentialsRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    row = await _require_device(device_id, db)
    if row.type != "miio":
        raise HTTPException(status_code=400, detail="Device is not a MiIO device")
    await service.set_miio_credentials(device_id, body.miio_device_id, body.miio_device_token, db, svc)
    row = await db.get_device(device_id)
    assert row is not None
    return build_admin_device_out(row, svc._devices.get(device_id))


@router.patch("/devices/{device_id}/tuya-credentials", response_model=AdminDeviceOut)
async def set_tuya_credentials(
    device_id: str,
    body: SetTuyaCredentialsRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    row = await _require_device(device_id, db)
    if row.type != "tuya":
        raise HTTPException(status_code=400, detail="Device is not a Tuya device")
    await service.set_tuya_credentials(
        device_id, body.tuya_device_id, body.tuya_local_key, body.tuya_product_id, db, svc
    )
    row = await db.get_device(device_id)
    assert row is not None
    return build_admin_device_out(row, svc._devices.get(device_id))


@router.patch("/devices/{device_id}/kasa-credentials", response_model=AdminDeviceOut)
async def set_kasa_credentials(
    device_id: str,
    body: SetKasaCredentialsRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    row = await _require_device(device_id, db)
    if row.type != "kasa":
        raise HTTPException(status_code=400, detail="Device is not a Kasa device")
    await service.set_kasa_credentials(device_id, body.kasa_username, body.kasa_password, db, svc)
    row = await db.get_device(device_id)
    assert row is not None
    return build_admin_device_out(row, svc._devices.get(device_id))


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
    except asyncio.CancelledError:
        raise HTTPException(status_code=409, detail="Interrupted by a concurrent device refresh")
    outlet_tokens = (await db.get_all_outlet_tokens()).get(device_id, {})
    return build_admin_device_out(row, svc._devices.get(device_id), outlet_tokens)


@router.patch("/devices/{device_id}/token", response_model=AdminDeviceOut)
async def set_device_token(
    device_id: str,
    body: SetDeviceTokenRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    await _require_device(device_id, db)
    token = body.token.strip() if body.token else None
    await db.set_device_token(device_id, token)
    svc.set_device_token(device_id, token)
    row = await db.get_device(device_id)
    assert row is not None
    return build_admin_device_out(row, svc._devices.get(device_id))


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
    outlet_tokens = (await db.get_all_outlet_tokens()).get(device_id, {})
    return build_admin_device_out(row, svc._devices.get(device_id), outlet_tokens)

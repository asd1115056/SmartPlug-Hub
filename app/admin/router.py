"""Admin API — device and account management."""

from fastapi import APIRouter, Depends, HTTPException, Request

from ..core import AccountInUseError
from ..db import Database, Device as DeviceRow
from ..device_service import DeviceService
from ..schemas import (
    AccountOut,
    AddAccountRequest,
    AddDeviceRequest,
    AdminDeviceOut,
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


# ── Accounts ──────────────────────────────────────────────────────────────────

@router.get("/accounts", response_model=list[AccountOut])
async def list_accounts(db: Database = Depends(_db)) -> list[AccountOut]:
    accounts = await db.get_accounts()
    result = []
    for a in accounts:
        if a.id is not None:
            result.append(AccountOut(id=a.id, type=a.type, username=a.username))
    return result


@router.post("/accounts", response_model=AccountOut, status_code=201)
async def create_account(
    body: AddAccountRequest,
    db: Database = Depends(_db),
) -> AccountOut:
    try:
        account = await service.add_account(body.type, body.username, body.password, db)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    assert account.id is not None
    return AccountOut(id=account.id, type=account.type, username=account.username)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(
    account_id: int,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> None:
    try:
        await service.remove_account(account_id, db, svc)
    except AccountInUseError as e:
        raise HTTPException(status_code=409, detail=str(e))


# ── Devices ───────────────────────────────────────────────────────────────────

@router.get("/devices", response_model=list[AdminDeviceOut])
async def list_devices(
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> list[AdminDeviceOut]:
    rows = await db.get_devices()
    entries = {e.config.id: e for e in svc.get_devices()}
    return [build_admin_device_out(row, entries.get(row.id)) for row in rows]


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
            account_id=body.account_id,
            miio_token=body.miio_token,
            miio_id=body.miio_id,
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


@router.patch("/devices/{device_id}/name", response_model=AdminDeviceOut)
async def set_device_name(
    device_id: str,
    body: SetNameRequest,
    db: Database = Depends(_db),
    svc: DeviceService = Depends(_svc),
) -> AdminDeviceOut:
    row = await _require_device(device_id, db)
    await service.set_device_name(device_id, body.name, db, svc)
    row.name = body.name
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
    return build_admin_device_out(row, svc._devices.get(device_id))

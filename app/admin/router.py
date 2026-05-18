"""Admin API router: account and device management."""

from fastapi import APIRouter, Depends, HTTPException

from ..core.utils import mac_to_id, normalize_mac
from ..db import Account, DeviceInfo
from ..device_manager import DeviceManager
from ..schemas import (
    AccountResponse,
    AddAccountRequest,
    AddDeviceRequest,
    AdminDeviceDetail,
    RenameRequest,
)
from .auth import require_admin

router = APIRouter(prefix="/api/v1/admin", dependencies=[Depends(require_admin)])


def _get_dm() -> DeviceManager:
    from ..main import device_manager
    if not device_manager:
        raise HTTPException(status_code=503, detail="Device manager not initialized")
    return device_manager


# ── Accounts ─────────────────────────────────────────────────────────────────

@router.get("/accounts", response_model=list[AccountResponse])
async def list_accounts(dm: DeviceManager = Depends(_get_dm)):
    accounts = await dm.get_accounts()
    return [AccountResponse(id=a.id, type=a.type, label=a.label, username=a.username)
            for a in accounts if a.id is not None]


@router.post("/accounts", response_model=AccountResponse, status_code=201)
async def create_account(body: AddAccountRequest, dm: DeviceManager = Depends(_get_dm)):
    row = Account(type=body.type, label=body.label, username=body.username, password=body.password)
    saved = await dm.add_account(row)
    return AccountResponse(id=saved.id, type=saved.type, label=saved.label, username=saved.username)


@router.delete("/accounts/{account_id}", status_code=204)
async def delete_account(account_id: int, dm: DeviceManager = Depends(_get_dm)):
    await dm.remove_account(account_id)


# ── Devices ──────────────────────────────────────────────────────────────────

@router.get("/devices", response_model=list[AdminDeviceDetail])
async def list_devices_admin(dm: DeviceManager = Depends(_get_dm)):
    return [
        AdminDeviceDetail(
            id=d.info.id,
            mac=d.info.mac,
            name=d.info.name,
            type=d.info.type,
            broadcast=d.info.broadcast,
            group_name=d.info.group_name,
            account_id=d.info.account_id,
            alias=d.info.alias,
            model=d.info.model,
            is_strip=d.info.is_strip,
            last_known_ip=d.info.last_known_ip,
            token=d.info.token,
            miio_id=d.info.miio_id,
        )
        for d in dm.get_all_devices()
    ]


@router.post("/devices", status_code=201)
async def add_device(body: AddDeviceRequest, dm: DeviceManager = Depends(_get_dm)):
    try:
        mac = normalize_mac(body.mac)
        info = DeviceInfo(
            id=mac_to_id(mac),
            mac=mac,
            name=body.name,
            type=body.type,
            broadcast=body.broadcast,
            group_name=body.group_name,
            account_id=body.account_id,
            token=body.token,
            miio_id=body.miio_id,
        )
        await dm.add_device(info)
        return {"id": info.id}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/devices/{device_id}", status_code=204)
async def remove_device(device_id: str, dm: DeviceManager = Depends(_get_dm)):
    try:
        await dm.remove_device(device_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/devices/{device_id}/name", status_code=204)
async def rename_device(
    device_id: str, body: RenameRequest, dm: DeviceManager = Depends(_get_dm)
):
    try:
        await dm.rename_device(device_id, body.new_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.patch("/devices/{device_id}/outlets/{outlet_id}/label", status_code=204)
async def rename_outlet(
    device_id: str, outlet_id: str, body: RenameRequest, dm: DeviceManager = Depends(_get_dm)
):
    try:
        await dm.rename_outlet(device_id, outlet_id, body.new_name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

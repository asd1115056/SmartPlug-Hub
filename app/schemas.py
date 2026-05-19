"""Pydantic request/response models and DB+RAM serialization helpers."""

from datetime import datetime

from pydantic import BaseModel

from .db import Device as DeviceRow
from .device_service import DeviceEntry


# ── Response models ───────────────────────────────────────────────────────────

class OutletOut(BaseModel):
    outlet_id: str
    name: str
    is_on: bool


class DeviceOut(BaseModel):
    id: str
    name: str
    group_name: str | None
    type: str
    model: str | None
    is_strip: bool
    is_online: bool
    is_on: bool | None
    last_updated: datetime | None
    outlets: list[OutletOut]


class AdminDeviceOut(BaseModel):
    id: str
    mac: str
    type: str
    group_name: str | None
    account_id: int | None
    broadcast: str
    miio_token: str | None
    miio_id: str | None
    name: str | None
    hw_alias: str | None
    hw_model: str | None
    hw_is_strip: bool
    last_known_ip: str | None
    is_online: bool
    is_on: bool | None
    outlets: list[OutletOut]


class AccountOut(BaseModel):
    id: int
    type: str
    username: str


# ── Request models ────────────────────────────────────────────────────────────

class SetPowerRequest(BaseModel):
    outlet_id: str | None = None
    on: bool


class AddDeviceRequest(BaseModel):
    mac: str
    type: str
    broadcast: str
    account_id: int | None = None
    miio_token: str | None = None
    miio_id: str | None = None


class AddAccountRequest(BaseModel):
    type: str
    username: str
    password: str


class SetNameRequest(BaseModel):
    name: str


# ── Serialization helpers ─────────────────────────────────────────────────────

def _build_outlets(entry: DeviceEntry) -> list[OutletOut]:
    if not entry.state:
        return []
    result = []
    for child in entry.state.children:
        if entry.backend.can_rename_outlet:
            name = child.hw_alias or child.outlet_id
        else:
            name = entry.outlet_names.get(child.outlet_id) or child.hw_alias or child.outlet_id
        result.append(OutletOut(outlet_id=child.outlet_id, name=name, is_on=child.is_on))
    return result


def build_device_out(entry: DeviceEntry) -> DeviceOut:
    state = entry.state
    return DeviceOut(
        id=entry.config.id,
        name=entry.name or (state.hw_alias if state else None) or entry.config.mac,
        group_name=entry.group_name,
        type=entry.config.type,
        model=state.hw_model if state else None,
        is_strip=state.hw_is_strip if state else False,
        is_online=entry.is_online,
        is_on=state.is_on if state else None,
        last_updated=entry.last_updated,
        outlets=_build_outlets(entry),
    )


def build_admin_device_out(row: DeviceRow, entry: DeviceEntry | None) -> AdminDeviceOut:
    state = entry.state if entry else None
    return AdminDeviceOut(
        id=row.id,
        mac=row.mac,
        type=row.type,
        group_name=row.group_name,
        account_id=row.account_id,
        broadcast=row.broadcast,
        miio_token=row.miio_token,
        miio_id=row.miio_id,
        name=row.name,
        hw_alias=row.hw_alias,
        hw_model=row.hw_model,
        hw_is_strip=row.hw_is_strip,
        last_known_ip=row.last_known_ip,
        is_online=entry.is_online if entry else False,
        is_on=state.is_on if state else None,
        outlets=_build_outlets(entry) if entry else [],
    )

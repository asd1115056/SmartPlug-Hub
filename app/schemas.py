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
    watts: float | None
    has_token: bool = False


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
    watts: float | None
    has_token: bool = False


class AdminOutletOut(BaseModel):
    outlet_id: str
    name: str
    is_on: bool
    watts: float | None
    token: str | None


class AdminDeviceOut(BaseModel):
    id: str
    mac: str
    type: str
    group_name: str | None
    broadcast: str
    kasa_username: str | None
    kasa_password: str | None
    miio_token: str | None
    miio_id: str | None
    tuya_device_id: str | None
    tuya_local_key: str | None
    tuya_product_id: str | None
    name: str | None
    hw_alias: str | None
    hw_model: str | None
    hw_is_strip: bool
    last_known_ip: str | None
    device_token: str | None
    is_online: bool
    is_on: bool | None
    outlets: list[AdminOutletOut]


# ── Request models ────────────────────────────────────────────────────────────

class DiscoveredDeviceOut(BaseModel):
    mac: str
    type: str
    broadcast: str
    ip: str
    model: str | None = None
    miio_id: str | None = None
    tuya_device_id: str | None = None
    tuya_local_key: str | None = None
    tuya_product_id: str | None = None
    is_registered: bool = False
    registered_name: str | None = None


class SetPowerRequest(BaseModel):
    outlet_id: str | None = None
    on: bool
    token: str | None = None


class AddDeviceRequest(BaseModel):
    mac: str
    type: str
    broadcast: str
    ip: str | None = None            # from a scan; omitted → discovered on first contact
    group_name: str | None = None
    kasa_username: str | None = None
    kasa_password: str | None = None
    miio_token: str | None = None
    miio_id: str | None = None
    tuya_device_id: str | None = None
    tuya_local_key: str | None = None
    tuya_product_id: str | None = None


class UpdateDeviceRequest(BaseModel):
    """Partial update: only fields present in the body are changed; null clears a field."""
    name: str | None = None
    group_name: str | None = None
    device_token: str | None = None
    kasa_username: str | None = None
    kasa_password: str | None = None
    miio_id: str | None = None
    miio_token: str | None = None
    tuya_device_id: str | None = None
    tuya_local_key: str | None = None
    tuya_product_id: str | None = None


class SetNameRequest(BaseModel):
    name: str


class SetOutletTokenRequest(BaseModel):
    token: str | None = None



# ── Serialization helpers ─────────────────────────────────────────────────────

def _outlet_name(entry: DeviceEntry, child) -> str:
    if entry.backend.can_rename_outlet:
        return child.hw_alias or child.outlet_id
    return entry.outlet_names.get(child.outlet_id) or child.hw_alias or child.outlet_id


def _build_outlets(entry: DeviceEntry) -> list[OutletOut]:
    if not entry.state:
        return []
    return [
        OutletOut(
            outlet_id=c.outlet_id,
            name=_outlet_name(entry, c),
            is_on=c.is_on,
            watts=c.watts,
            has_token=c.outlet_id in entry.outlet_tokens,
        )
        for c in entry.state.children
    ]


def _build_admin_outlets(entry: DeviceEntry) -> list[AdminOutletOut]:
    if not entry.state:
        return []
    return [
        AdminOutletOut(
            outlet_id=c.outlet_id,
            name=_outlet_name(entry, c),
            is_on=c.is_on,
            watts=c.watts,
            token=entry.outlet_tokens.get(c.outlet_id),
        )
        for c in entry.state.children
    ]


def build_device_out(entry: DeviceEntry) -> DeviceOut:
    state = entry.state
    return DeviceOut(
        id=entry.config.id,
        name=entry.name or (state.hw_alias if state else None) or f"Unnamed ···{entry.config.mac[-4:]}",
        group_name=entry.group_name,
        type=entry.config.type,
        model=state.hw_model if state else None,
        is_strip=state.hw_is_strip if state else False,
        is_online=entry.is_online,
        is_on=state.is_on if state else None,
        last_updated=entry.last_updated,
        outlets=_build_outlets(entry),
        watts=state.watts if state else None,
        has_token=entry.device_token is not None,
    )


def build_admin_device_out(
    row: DeviceRow,
    entry: DeviceEntry | None,
) -> AdminDeviceOut:
    state = entry.state if entry else None
    return AdminDeviceOut(
        id=row.id,
        mac=row.mac,
        type=row.type,
        group_name=row.group_name,
        broadcast=row.broadcast,
        kasa_username=row.kasa_username,
        kasa_password=row.kasa_password,
        miio_token=row.miio_token,
        miio_id=row.miio_id,
        tuya_device_id=row.tuya_device_id,
        tuya_local_key=row.tuya_local_key,
        tuya_product_id=row.tuya_product_id,
        name=row.name,
        hw_alias=row.hw_alias,
        hw_model=row.hw_model,
        hw_is_strip=row.hw_is_strip,
        last_known_ip=row.last_known_ip,
        device_token=row.device_token,
        is_online=entry.is_online if entry else False,
        is_on=state.is_on if state else None,
        outlets=_build_admin_outlets(entry) if entry else [],
    )

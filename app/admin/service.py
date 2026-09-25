"""Admin CRUD operations — pure functions called after route validation."""

import logging
from typing import Any

from ..core import DeviceNotFoundError, mac_to_id, normalize_mac
from ..db import Database, Device as DeviceRow
from ..device_service import DeviceService

logger = logging.getLogger(__name__)


async def add_device(
    mac: str,
    device_type: str,
    broadcast: str,
    db: Database,
    svc: DeviceService,
    *,
    group_name: str | None = None,
    kasa_username: str | None = None,
    kasa_password: str | None = None,
    miio_token: str | None = None,
    miio_id: str | None = None,
    tuya_device_id: str | None = None,
    tuya_local_key: str | None = None,
    tuya_product_id: str | None = None,
) -> DeviceRow:
    row = DeviceRow(
        id=mac_to_id(mac),
        mac=normalize_mac(mac),
        type=device_type,
        broadcast=broadcast,
        group_name=group_name,
        kasa_username=kasa_username,
        kasa_password=kasa_password,
        miio_token=miio_token,
        miio_id=miio_id,
        tuya_device_id=tuya_device_id,
        tuya_local_key=tuya_local_key,
        tuya_product_id=tuya_product_id,
    )
    row = await db.add_device(row)
    svc.add_entry(row, {})
    logger.info("Device added: %s (%s)", row.id, row.mac)
    return row


async def remove_device(device_id: str, db: Database, svc: DeviceService) -> None:
    await svc.remove_entry(device_id)
    await db.remove_device(device_id)
    logger.info("Device removed: %s", device_id)


_COMMON_FIELDS = {"name", "group_name", "device_token"}
_CREDENTIAL_FIELDS = {
    "kasa": {"kasa_username", "kasa_password"},
    "miio": {"miio_id", "miio_token"},
    "tuya": {"tuya_device_id", "tuya_local_key", "tuya_product_id"},
}
_TRIMMED_FIELDS = {"name", "group_name", "device_token"}   # secrets are stored verbatim


async def update_device(
    device_id: str, fields: dict[str, Any], db: Database, svc: DeviceService,
) -> DeviceRow:
    """Apply a partial device edit to the DB and the running service in one step."""
    row = await db.get_device(device_id)
    if row is None:
        raise DeviceNotFoundError(device_id)
    credential_fields = _CREDENTIAL_FIELDS.get(row.type, set())
    if unknown := fields.keys() - _COMMON_FIELDS - credential_fields:
        raise ValueError(f"Not applicable to a {row.type} device: {', '.join(sorted(unknown))}")

    cleaned = {k: _clean(v, is_trimmed=k in _TRIMMED_FIELDS) for k, v in fields.items()}
    row = await db.update_device(device_id, cleaned)
    if row is None:
        raise DeviceNotFoundError(device_id)
    svc.update_device(row, is_reconnect=bool(cleaned.keys() & credential_fields))
    logger.info("Device %s updated: %s", device_id, ", ".join(sorted(cleaned)))
    return row


async def set_outlet_name(
    device_id: str, outlet_id: str, name: str, db: Database, svc: DeviceService
) -> None:
    entry = svc.get_device(device_id)
    if entry.backend.can_rename_outlet:
        await svc.rename_outlet(device_id, outlet_id, name)
    else:
        await db.set_outlet_name(device_id, outlet_id, name)
        svc.set_outlet_name(device_id, outlet_id, name)
    logger.info("Device %s outlet %s renamed to %r", device_id, outlet_id, name)


def _clean(value: str | None, *, is_trimmed: bool) -> str | None:
    if value is not None and is_trimmed:
        value = value.strip()
    return value or None   # "" means "clear", same as null

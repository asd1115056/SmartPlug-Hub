"""Admin CRUD operations — pure functions called after route validation."""

import logging

from ..core import mac_to_id, normalize_mac
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


async def set_device_name(device_id: str, name: str, db: Database, svc: DeviceService) -> None:
    await db.set_device_name(device_id, name)
    svc.set_name(device_id, name)
    logger.info("Device %s renamed to %r", device_id, name)


async def set_device_group_name(
    device_id: str, group_name: str | None, db: Database, svc: DeviceService
) -> None:
    await db.set_device_group_name(device_id, group_name)
    svc.set_group_name(device_id, group_name)
    logger.info("Device %s group set to %r", device_id, group_name)


async def set_kasa_credentials(
    device_id: str,
    kasa_username: str | None,
    kasa_password: str | None,
    db: Database,
    svc: DeviceService,
) -> None:
    await db.set_kasa_credentials(device_id, kasa_username, kasa_password)
    row = await db.get_device(device_id)
    if row:
        entry = svc._devices.get(device_id)
        outlet_names = entry.outlet_names if entry else {}
        outlet_tokens = entry.outlet_tokens if entry else {}
        await svc.remove_entry(device_id)
        svc.add_entry(row, outlet_names, outlet_tokens)
    logger.info("Device %s kasa credentials updated", device_id)


async def set_miio_credentials(
    device_id: str,
    miio_device_id: str | None,
    miio_device_token: str | None,
    db: Database,
    svc: DeviceService,
) -> None:
    await db.set_miio_credentials(device_id, miio_device_id, miio_device_token)
    row = await db.get_device(device_id)
    if row:
        entry = svc._devices.get(device_id)
        outlet_names = entry.outlet_names if entry else {}
        outlet_tokens = entry.outlet_tokens if entry else {}
        await svc.remove_entry(device_id)
        svc.add_entry(row, outlet_names, outlet_tokens)
    logger.info("Device %s miio credentials updated", device_id)


async def set_tuya_credentials(
    device_id: str,
    tuya_device_id: str | None,
    tuya_local_key: str | None,
    tuya_product_id: str | None,
    db: Database,
    svc: DeviceService,
) -> None:
    await db.set_tuya_credentials(device_id, tuya_device_id, tuya_local_key, tuya_product_id)
    row = await db.get_device(device_id)
    if row:
        entry = svc._devices.get(device_id)
        outlet_names = entry.outlet_names if entry else {}
        outlet_tokens = entry.outlet_tokens if entry else {}
        await svc.remove_entry(device_id)
        svc.add_entry(row, outlet_names, outlet_tokens)
    logger.info("Device %s tuya credentials updated", device_id)


async def set_outlet_name(
    device_id: str, outlet_id: str, name: str, db: Database, svc: DeviceService
) -> None:
    entry = svc.get_device(device_id)
    if entry.backend.can_rename_outlet:
        await entry.backend.rename_outlet(entry.config, outlet_id, name)
    else:
        await db.set_outlet_name(device_id, outlet_id, name)
        svc.set_outlet_name(device_id, outlet_id, name)
    logger.info("Device %s outlet %s renamed to %r", device_id, outlet_id, name)

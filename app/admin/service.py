"""Admin CRUD operations — pure functions called after route validation."""

import logging

from ..core import AccountInUseError, mac_to_id, normalize_mac
from ..db import Account, Database, Device as DeviceRow
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
    account_id: int | None = None,
    miio_token: str | None = None,
    miio_id: str | None = None,
) -> DeviceRow:
    row = DeviceRow(
        id=mac_to_id(mac),
        mac=normalize_mac(mac),
        type=device_type,
        broadcast=broadcast,
        group_name=group_name,
        account_id=account_id,
        miio_token=miio_token,
        miio_id=miio_id,
    )
    row = await db.add_device(row)
    accounts = {a.id: a for a in await db.get_accounts() if a.id is not None}
    svc.add_entry(row, accounts.get(account_id) if account_id else None, {})
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


async def add_account(account_type: str, username: str, password: str, db: Database) -> Account:
    account = await db.add_account(Account(type=account_type, username=username, password=password))
    logger.info("Account added: %s (%s)", account.username, account_type)
    return account


async def remove_account(account_id: int, db: Database, svc: DeviceService) -> None:
    devices = await db.get_devices()
    bound = [d for d in devices if d.account_id == account_id]
    if bound:
        raise AccountInUseError(f"Account {account_id} is used by {len(bound)} device(s)")
    await db.remove_account(account_id)
    logger.info("Account removed: %d", account_id)

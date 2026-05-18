"""Admin CRUD operations — pure functions called after route validation."""

from ..core import AccountInUseError, mac_to_id, normalize_mac
from ..db import Account, Database, Device as DeviceRow
from ..device_service import DeviceService


async def add_device(
    mac: str,
    device_type: str,
    broadcast: str,
    db: Database,
    svc: DeviceService,
    *,
    account_id: int | None = None,
    miio_token: str | None = None,
    miio_id: str | None = None,
) -> DeviceRow:
    row = DeviceRow(
        id=mac_to_id(mac),
        mac=normalize_mac(mac),
        type=device_type,
        broadcast=broadcast,
        account_id=account_id,
        miio_token=miio_token,
        miio_id=miio_id,
    )
    row = await db.add_device(row)
    accounts = {a.id: a for a in await db.get_accounts() if a.id is not None}
    svc.add_entry(row, accounts.get(account_id) if account_id else None, {})
    return row


async def remove_device(device_id: str, db: Database, svc: DeviceService) -> None:
    await svc.remove_entry(device_id)
    await db.remove_device(device_id)


async def set_device_name(device_id: str, name: str, db: Database, svc: DeviceService) -> None:
    await db.set_device_name(device_id, name)
    svc.set_name(device_id, name)


async def set_outlet_name(
    device_id: str, outlet_id: str, name: str, db: Database, svc: DeviceService
) -> None:
    entry = svc.get_device(device_id)
    if entry.backend.can_rename_outlet:
        await entry.backend.rename_outlet(entry.config, outlet_id, name)
    else:
        await db.set_outlet_name(device_id, outlet_id, name)
        svc.set_outlet_name(device_id, outlet_id, name)


async def add_account(account_type: str, username: str, password: str, db: Database) -> Account:
    return await db.add_account(Account(type=account_type, username=username, password=password))


async def remove_account(account_id: int, db: Database, svc: DeviceService) -> None:
    devices = await db.get_devices()
    bound = [d for d in devices if d.account_id == account_id]
    if bound:
        raise AccountInUseError(f"Account {account_id} is used by {len(bound)} device(s)")
    await db.remove_account(account_id)

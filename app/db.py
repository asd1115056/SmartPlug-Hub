"""SQLite persistence layer using SQLModel."""

import json
import logging
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from .core.utils import mac_to_id, normalize_mac

logger = logging.getLogger(__name__)


class Account(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    type: str  # "kasa" | "miio"
    username: str
    password: str


class DeviceInfo(SQLModel, table=True):
    # ── 共有 ──────────────────────────────────────────
    id: str = Field(primary_key=True)  # mac_to_id() 產生的 8 碼 hash
    mac: str = Field(unique=True, index=True)
    name: str
    type: str  # "kasa" | "miio"
    broadcast: str
    group_name: str | None = None
    account_id: int | None = Field(default=None, foreign_key="account.id")

    # ── 硬體快取（probe 後更新）─────────────────────────
    alias: str | None = None
    model: str | None = None
    is_strip: bool = False
    last_known_ip: str | None = None  # non-authoritative, for faster reconnect

    # ── MiIO only ─────────────────────────────────────
    token: str | None = None
    miio_id: str | None = None


class Outlet(SQLModel, table=True):
    device_id: str = Field(foreign_key="deviceinfo.id", primary_key=True)
    outlet_id: str = Field(primary_key=True)  # kasa: child.device_id; miio: index
    alias: str | None = None  # user-visible label


class Database:
    """Async SQLite database. One instance per application lifetime."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        url = f"sqlite+aiosqlite:///{path}"
        self._engine: AsyncEngine = create_async_engine(url, echo=False)

        @event.listens_for(self._engine.sync_engine, "connect")
        def _set_pragma(dbapi_conn, _record) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    async def initialize(self, devices_json_path: Path | None = None) -> None:
        """Create tables, then migrate from devices.json if the DB is empty."""
        async with self._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

        if devices_json_path and devices_json_path.exists():
            async with AsyncSession(self._engine) as session:
                result = await session.execute(select(DeviceInfo))
                if not result.scalars().first():
                    await self._migrate_from_json(session, devices_json_path)
                    await session.commit()

    async def close(self) -> None:
        await self._engine.dispose()

    # ── Account ──────────────────────────────────────────────────────────────

    async def get_all_accounts(self) -> list[Account]:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(select(Account))
            return list(result.scalars().all())

    async def add_account(self, row: Account) -> Account:
        async with AsyncSession(self._engine) as session:
            existing = await session.execute(
                select(Account).where(Account.username == row.username, Account.type == row.type)
            )
            if existing.scalars().first():
                raise ValueError(f"Account '{row.username}' ({row.type}) already exists")
            session.add(row)
            await session.commit()
            await session.refresh(row)
            return row

    async def remove_account(self, account_id: int) -> None:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(select(Account).where(Account.id == account_id))
            account = result.scalars().first()
            if account:
                await session.delete(account)
                await session.commit()

    # ── Device ───────────────────────────────────────────────────────────────

    async def get_all_devices(self) -> list[DeviceInfo]:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(select(DeviceInfo))
            return list(result.scalars().all())

    async def add_device(self, row: DeviceInfo) -> None:
        async with AsyncSession(self._engine) as session:
            existing = await session.execute(select(DeviceInfo).where(DeviceInfo.mac == row.mac))
            if existing.scalars().first():
                raise ValueError(f"Device with MAC '{row.mac}' already exists")
            session.add(row)
            await session.commit()

    async def remove_device(self, device_id: str) -> None:
        async with AsyncSession(self._engine) as session:
            outlets_result = await session.execute(
                select(Outlet).where(Outlet.device_id == device_id)
            )
            for outlet in outlets_result.scalars().all():
                await session.delete(outlet)
            result = await session.execute(
                select(DeviceInfo).where(DeviceInfo.id == device_id)
            )
            device = result.scalars().first()
            if device:
                await session.delete(device)
            await session.commit()

    async def update_device_cache(
        self,
        device_id: str,
        alias: str | None,
        model: str | None,
        is_strip: bool,
        ip: str | None,
    ) -> None:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                select(DeviceInfo).where(DeviceInfo.id == device_id)
            )
            device = result.scalars().first()
            if device:
                device.alias = alias
                device.model = model
                device.is_strip = is_strip
                device.last_known_ip = ip
                session.add(device)
                await session.commit()

    async def update_device_name(self, device_id: str, new_name: str) -> None:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                select(DeviceInfo).where(DeviceInfo.id == device_id)
            )
            device = result.scalars().first()
            if device:
                device.name = new_name
                session.add(device)
                await session.commit()

    # ── Outlet ───────────────────────────────────────────────────────────────

    async def get_outlets(self, device_id: str) -> list[Outlet]:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(
                select(Outlet).where(Outlet.device_id == device_id)
            )
            return list(result.scalars().all())

    async def get_all_outlets(self) -> dict[str, list[Outlet]]:
        async with AsyncSession(self._engine) as session:
            result = await session.execute(select(Outlet))
            outlets: dict[str, list[Outlet]] = {}
            for outlet in result.scalars().all():
                outlets.setdefault(outlet.device_id, []).append(outlet)
            return outlets

    async def upsert_outlet(self, outlet: Outlet) -> None:
        async with AsyncSession(self._engine) as session:
            existing = await session.get(Outlet, (outlet.device_id, outlet.outlet_id))
            if existing:
                existing.alias = outlet.alias
                session.add(existing)
            else:
                session.add(Outlet(
                    device_id=outlet.device_id,
                    outlet_id=outlet.outlet_id,
                    alias=outlet.alias,
                ))
            await session.commit()

    async def upsert_outlets(self, outlets: list[Outlet]) -> None:
        async with AsyncSession(self._engine) as session:
            for outlet in outlets:
                existing = await session.get(Outlet, (outlet.device_id, outlet.outlet_id))
                if existing:
                    existing.alias = outlet.alias
                    session.add(existing)
                else:
                    session.add(Outlet(
                        device_id=outlet.device_id,
                        outlet_id=outlet.outlet_id,
                        alias=outlet.alias,
                    ))
            await session.commit()

    # ── Migration ─────────────────────────────────────────────────────────────

    async def _migrate_from_json(self, session: AsyncSession, path: Path) -> None:
        """Import devices from legacy devices.json into the DB on first boot."""
        try:
            with open(path) as f:
                data = json.load(f)
        except Exception as e:
            logger.error(f"Migration: cannot read {path}: {e}")
            return

        if not isinstance(data, dict):
            logger.error("Migration: devices.json must be a JSON object")
            return

        # (type, username, password) → Account.id — avoid duplicate accounts
        account_cache: dict[tuple[str, str, str], int] = {}
        migrated = 0
        skipped = 0

        for entry in data.get("devices", []):
            try:
                mac = normalize_mac(entry["mac"])
                name = entry.get("name") or mac_to_id(mac)
                device_type = entry["type"]
                broadcast = entry["broadcast"]

                account_id: int | None = None
                username = entry.get("username")
                password = entry.get("password")
                if username and password:
                    key = (device_type, username, password)
                    if key not in account_cache:
                        account = Account(
                            type=device_type,
                            label=f"{device_type} ({username})",
                            username=username,
                            password=password,
                        )
                        session.add(account)
                        await session.flush()
                        assert account.id is not None
                        account_cache[key] = account.id
                    account_id = account_cache[key]

                device = DeviceInfo(
                    id=mac_to_id(mac),
                    mac=mac,
                    name=name,
                    type=device_type,
                    broadcast=broadcast,
                    group_name=entry.get("group"),
                    account_id=account_id,
                    token=entry.get("token"),
                    miio_id=entry.get("miio_id"),
                )
                session.add(device)
                migrated += 1

            except (KeyError, ValueError, TypeError) as e:
                logger.error(f"Migration: skipping invalid entry: {e}")
                skipped += 1

        suffix = f", {skipped} skipped" if skipped else ""
        logger.info(f"Migrated {migrated} devices from {path.name} into DB{suffix}")

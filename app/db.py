"""SQLite persistence — user intent and hardware snapshot cache."""

import logging
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import Field, SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

logger = logging.getLogger(__name__)


# ── Tables ────────────────────────────────────────────────────────────────────

class Account(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    type: str                           # "kasa" | "miio"
    username: str
    password: str


class Device(SQLModel, table=True):
    id: str = Field(primary_key=True)   # 8-char mac hash
    mac: str = Field(unique=True, index=True)
    account_id: int | None = Field(default=None, foreign_key="account.id")
    type: str                           # "kasa" | "miio"
    broadcast: str
    group_name: str | None = None

    # User intent — only written by rename API
    name: str | None = None             # null = fall back to hw_alias for display

    # MiIO connection credentials
    miio_token: str | None = None
    miio_id: str | None = None

    # Hardware snapshot — updated after each successful poll
    hw_alias: str | None = None
    hw_model: str | None = None
    hw_is_strip: bool = False
    last_known_ip: str | None = None    # non-authoritative, speeds up reconnect


class Outlet(SQLModel, table=True):
    device_id: str = Field(foreign_key="device.id", primary_key=True)
    outlet_id: str = Field(primary_key=True)  # Kasa: child.device_id / MiIO: str(index)
    name: str                           # only exists when user has explicitly renamed this outlet


# ── Database ──────────────────────────────────────────────────────────────────

class Database:
    """Async SQLite database. One instance per application lifetime."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._engine: AsyncEngine = create_async_engine(
            f"sqlite+aiosqlite:///{path}", echo=False
        )

        @event.listens_for(self._engine.sync_engine, "connect")
        def _set_pragma(dbapi_conn, _record) -> None:
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")   # concurrent reads during writes
            cursor.execute("PRAGMA busy_timeout=5000")  # retry for 5s before raising
            cursor.close()

    async def initialize(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)

    async def close(self) -> None:
        await self._engine.dispose()

    # ── Account ───────────────────────────────────────────────────────────────

    async def get_accounts(self) -> list[Account]:
        async with AsyncSession(self._engine) as session:
            return list((await session.exec(select(Account))).all())

    async def add_account(self, account: Account) -> Account:
        async with AsyncSession(self._engine) as session:
            dup = await session.exec(
                select(Account).where(Account.username == account.username,
                                      Account.type == account.type)
            )
            if dup.first():
                raise ValueError(f"Account '{account.username}' ({account.type}) already exists")
            session.add(account)
            await session.commit()
            await session.refresh(account)
            return account

    async def remove_account(self, account_id: int) -> None:
        async with AsyncSession(self._engine) as session:
            account = await session.get(Account, account_id)
            if account:
                await session.delete(account)
                await session.commit()

    # ── Device ────────────────────────────────────────────────────────────────

    async def get_devices(self) -> list[Device]:
        async with AsyncSession(self._engine) as session:
            return list((await session.exec(select(Device))).all())

    async def get_device(self, device_id: str) -> Device | None:
        async with AsyncSession(self._engine) as session:
            return await session.get(Device, device_id)

    async def add_device(self, device: Device) -> Device:
        async with AsyncSession(self._engine) as session:
            dup = await session.exec(select(Device).where(Device.mac == device.mac))
            if dup.first():
                raise ValueError(f"Device with MAC '{device.mac}' already exists")
            session.add(device)
            await session.commit()
            await session.refresh(device)
            return device

    async def remove_device(self, device_id: str) -> None:
        async with AsyncSession(self._engine) as session:
            outlets = await session.exec(
                select(Outlet).where(Outlet.device_id == device_id)
            )
            for outlet in outlets.all():
                await session.delete(outlet)
            device = await session.get(Device, device_id)
            if device:
                await session.delete(device)
            await session.commit()

    async def set_device_name(self, device_id: str, name: str) -> None:
        async with AsyncSession(self._engine) as session:
            device = await session.get(Device, device_id)
            if device:
                device.name = name
                session.add(device)
                await session.commit()

    async def set_device_group_name(self, device_id: str, group_name: str | None) -> None:
        async with AsyncSession(self._engine) as session:
            device = await session.get(Device, device_id)
            if device:
                device.group_name = group_name
                session.add(device)
                await session.commit()

    async def update_device_hw(
        self,
        device_id: str,
        *,
        hw_alias: str | None,
        hw_model: str | None,
        hw_is_strip: bool,
        last_known_ip: str | None,
    ) -> None:
        """Update the hardware snapshot after a successful poll."""
        async with AsyncSession(self._engine) as session:
            device = await session.get(Device, device_id)
            if device:
                device.hw_alias = hw_alias
                device.hw_model = hw_model
                device.hw_is_strip = hw_is_strip
                device.last_known_ip = last_known_ip
                session.add(device)
                await session.commit()

    # ── Outlet ────────────────────────────────────────────────────────────────

    async def get_all_outlet_names(self) -> dict[str, dict[str, str]]:
        """Return {device_id: {outlet_id: name}} for all user-set outlet names."""
        async with AsyncSession(self._engine) as session:
            rows = (await session.exec(select(Outlet))).all()
            names: dict[str, dict[str, str]] = {}
            for row in rows:
                names.setdefault(row.device_id, {})[row.outlet_id] = row.name
            return names

    async def set_outlet_name(self, device_id: str, outlet_id: str, name: str) -> None:
        async with AsyncSession(self._engine) as session:
            existing = await session.get(Outlet, (device_id, outlet_id))
            if existing:
                existing.name = name
                session.add(existing)
            else:
                session.add(Outlet(device_id=device_id, outlet_id=outlet_id, name=name))
            await session.commit()

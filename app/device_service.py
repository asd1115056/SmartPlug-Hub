"""Device lifecycle — startup, polling, command dispatch, SSE broadcast."""

import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from .command_queue import DeviceQueue
from .core import DeviceBackend, DeviceConfig, DeviceNotFoundError, DeviceOfflineError, DeviceState
from .db import Account, Database, Device as DeviceRow
from .backends.kasa import KasaBackend
from .backends.miio import MiioBackend

logger = logging.getLogger(__name__)

POLL_INTERVAL: float = 60.0


# ── Runtime entry ─────────────────────────────────────────────────────────────

@dataclass
class DeviceEntry:
    config: DeviceConfig
    backend: DeviceBackend
    queue: DeviceQueue
    name: str | None                # user-set name; None = fall back to state.hw_alias
    group_name: str | None
    state: DeviceState | None       # None until first successful poll
    is_online: bool
    last_updated: datetime | None   # UTC timestamp of last successful state update
    outlet_names: dict[str, str]    # outlet_id → user-set name, loaded from DB at startup


# ── Service ───────────────────────────────────────────────────────────────────

class DeviceService:
    """Owns all runtime device state: polling, command dispatch, SSE broadcast."""

    def __init__(self, db: Database, poll_interval: float = POLL_INTERVAL) -> None:
        self._db = db
        self._poll_interval = poll_interval
        self._devices: dict[str, DeviceEntry] = {}
        self._subscribers: set[asyncio.Queue[None]] = set()
        self._poll_task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        rows = await self._db.get_devices()
        accounts = {a.id: a for a in await self._db.get_accounts() if a.id is not None}
        outlet_names = await self._db.get_all_outlet_names()

        for row in rows:
            account = accounts.get(row.account_id) if row.account_id else None
            self._devices[row.id] = _make_entry(row, account, outlet_names.get(row.id, {}))

        self._poll_task = asyncio.create_task(self._poll_loop())
        by_type = {}
        for e in self._devices.values():
            by_type[e.config.type] = by_type.get(e.config.type, 0) + 1
        summary = ", ".join(f"{t}: {n}" for t, n in sorted(by_type.items()))
        logger.info("DeviceService started — %s", summary or "no devices")

    async def stop(self) -> None:
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        for entry in self._devices.values():
            await entry.queue.close()
        logger.info("DeviceService stopped")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_devices(self) -> list[DeviceEntry]:
        return list(self._devices.values())

    def get_device(self, device_id: str) -> DeviceEntry:
        entry = self._devices.get(device_id)
        if entry is None:
            raise DeviceNotFoundError(device_id)
        return entry

    async def set_power(self, device_id: str, outlet_id: str | None, on: bool) -> DeviceState:
        logger.debug("set_power %s outlet=%s on=%s", device_id, outlet_id, on)
        entry = self._get_entry(device_id)
        try:
            state = await entry.queue.submit(outlet_id, on)
        except DeviceOfflineError:
            self._mark_offline(device_id, entry)
            raise
        self._update_state(device_id, entry, state)
        return state

    async def refresh(self, device_id: str) -> DeviceState:
        """Force-close and re-probe. Useful for recovering an offline device."""
        entry = self._get_entry(device_id)
        await entry.queue.close()
        try:
            state = await entry.backend.probe(entry.config)
        except DeviceOfflineError:
            self._mark_offline(device_id, entry)
            raise
        self._update_state(device_id, entry, state)
        return state

    # ── SSE ──────────────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue[None]:
        q: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[None]) -> None:
        self._subscribers.discard(q)

    # ── Admin helpers (called after DB writes are committed) ──────────────────

    def add_entry(self, row: DeviceRow, account: Account | None, outlet_names: dict[str, str]) -> None:
        entry = _make_entry(row, account, outlet_names)
        self._devices[row.id] = entry
        asyncio.create_task(self._probe_one(row.id, entry))
        self._broadcast()

    async def remove_entry(self, device_id: str) -> None:
        entry = self._devices.pop(device_id, None)
        if entry:
            await entry.queue.close()
        self._broadcast()

    def set_name(self, device_id: str, name: str) -> None:
        entry = self._devices.get(device_id)
        if entry:
            entry.name = name
            self._broadcast()

    def set_outlet_name(self, device_id: str, outlet_id: str, name: str) -> None:
        entry = self._devices.get(device_id)
        if entry:
            entry.outlet_names[outlet_id] = name
            self._broadcast()

    # ── Internal ─────────────────────────────────────────────────────────────

    def _get_entry(self, device_id: str) -> DeviceEntry:
        entry = self._devices.get(device_id)
        if entry is None:
            raise DeviceNotFoundError(device_id)
        return entry

    def _update_state(self, device_id: str, entry: DeviceEntry, state: DeviceState) -> None:
        was_online = entry.is_online
        entry.state = state
        entry.is_online = True
        entry.last_updated = datetime.now(UTC)
        if not was_online:
            logger.info(f"Device {device_id} is now online")
        self._broadcast()
        asyncio.create_task(self._db.update_device_hw(
            device_id,
            hw_alias=state.hw_alias,
            hw_model=state.hw_model,
            hw_is_strip=state.hw_is_strip,
            last_known_ip=entry.backend.ip,
        ))

    def _mark_offline(self, device_id: str, entry: DeviceEntry) -> None:
        was_online = entry.is_online
        entry.is_online = False
        if was_online:
            logger.info(f"Device {device_id} is now offline")
        self._broadcast()

    def _broadcast(self) -> None:
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def _probe_one(self, device_id: str, entry: DeviceEntry) -> None:
        if entry.queue.is_active():
            logger.debug("Skipping %s — command in progress", device_id)
            return
        try:
            state = await entry.backend.probe(entry.config)
        except DeviceOfflineError as e:
            if entry.is_online:
                logger.warning("Device %s unreachable: %s", device_id, e)
            self._mark_offline(device_id, entry)
            return
        except Exception:
            logger.exception("Unexpected error probing %s", device_id)
            self._mark_offline(device_id, entry)
            return
        self._update_state(device_id, entry, state)

    async def _poll_loop(self) -> None:
        while True:
            logger.debug("Polling %d devices", len(self._devices))
            await asyncio.gather(*[
                self._probe_one(did, entry)
                for did, entry in list(self._devices.items())
            ])
            await asyncio.sleep(self._poll_interval)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(row: DeviceRow, account: Account | None) -> DeviceConfig:
    return DeviceConfig(
        id=row.id,
        mac=row.mac,
        type=row.type,
        broadcast=row.broadcast,
        last_known_ip=row.last_known_ip,
        username=account.username if account else None,
        password=account.password if account else None,
        miio_token=row.miio_token,
        miio_id=row.miio_id,
    )


def _make_backend(device_type: str) -> DeviceBackend:
    if device_type == "kasa":
        return KasaBackend()
    if device_type == "miio":
        return MiioBackend()
    raise ValueError(f"Unknown device type: {device_type!r}")


def _make_entry(row: DeviceRow, account: Account | None, outlet_names: dict[str, str]) -> DeviceEntry:
    config = _make_config(row, account)
    backend = _make_backend(row.type)
    return DeviceEntry(
        config=config,
        backend=backend,
        queue=DeviceQueue(row.id, backend, config),
        name=row.name,
        group_name=row.group_name,
        state=None,
        is_online=False,
        last_updated=None,
        outlet_names=outlet_names,
    )

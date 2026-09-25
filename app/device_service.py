"""Device lifecycle — startup, polling, command dispatch, SSE broadcast."""

import asyncio
import logging
from collections.abc import Coroutine
from dataclasses import dataclass, replace
from typing import Any
from datetime import UTC, datetime

from .command_queue import DeviceQueue
from .core import (
    DeviceBackend, DeviceConfig, DeviceNotFoundError, DeviceOfflineError, DeviceRejectedError,
    DeviceState,
)
from .db import Database, Device as DeviceRow
from .backends.kasa import KasaBackend
from .backends.miio import MiioBackend
from .backends.tuya import TuyaBackend

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
    outlet_tokens: dict[str, str]   # outlet_id → access token (only set outlets)
    device_token: str | None        # access token for whole-device on/off


# ── Service ───────────────────────────────────────────────────────────────────

class DeviceService:
    """Owns all runtime device state: polling, command dispatch, SSE broadcast."""

    def __init__(self, db: Database, poll_interval: float = POLL_INTERVAL) -> None:
        self._db = db
        self._poll_interval = poll_interval
        self._devices: dict[str, DeviceEntry] = {}
        self._subscribers: set[asyncio.Queue[None]] = set()
        self._poll_task: asyncio.Task[None] | None = None
        # The event loop only keeps weak references to tasks — hold fire-and-forget
        # tasks here so they can't be garbage-collected mid-run
        self._background_tasks: set[asyncio.Task[Any]] = set()

    async def start(self) -> None:
        rows = await self._db.get_devices()
        outlet_names = await self._db.get_all_outlet_names()
        outlet_tokens = await self._db.get_all_outlet_tokens()

        for row in rows:
            self._devices[row.id] = self._make_entry(
                row,
                outlet_names.get(row.id, {}),
                outlet_tokens.get(row.id, {}),
            )

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
        # Let pending DB writes finish before the caller closes the database
        await asyncio.gather(*self._background_tasks, return_exceptions=True)
        logger.info("DeviceService stopped")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_devices(self) -> list[DeviceEntry]:
        return list(self._devices.values())

    def find_device(self, device_id: str) -> DeviceEntry | None:
        return self._devices.get(device_id)

    def get_device(self, device_id: str) -> DeviceEntry:
        entry = self._devices.get(device_id)
        if entry is None:
            raise DeviceNotFoundError(device_id)
        return entry

    async def set_power(self, device_id: str, outlet_id: str | None, on: bool) -> DeviceState:
        logger.info("set_power %s outlet=%s on=%s", device_id, outlet_id, on)
        entry = self._get_entry(device_id)
        try:
            state = await entry.queue.submit(outlet_id, on)
        except DeviceOfflineError:
            self._mark_offline(device_id, entry)
            raise
        self._update_state(device_id, entry, state)
        return state

    async def rename_outlet(self, device_id: str, outlet_id: str, name: str) -> None:
        """Push a hardware alias change — serialized against power commands and polling."""
        entry = self._get_entry(device_id)

        async def action(backend: DeviceBackend, config: DeviceConfig) -> DeviceState:
            await backend.rename_outlet(config, outlet_id, name)
            # Outlet names are read from entry.state, so re-probe or the UI shows the old
            # alias until the next poll
            return await backend.probe(config)

        try:
            state = await entry.queue.run(action)
        except DeviceOfflineError:
            self._mark_offline(device_id, entry)
            raise
        self._update_state(device_id, entry, state)

    async def refresh(self, device_id: str) -> DeviceState:
        """Drop the connection and rediscover the device's IP — queued like any operation.

        If discovery finds nothing the known IP is kept, so polling doesn't start broadcasting.
        """
        entry = self._get_entry(device_id)

        async def action(backend: DeviceBackend, config: DeviceConfig) -> DeviceState:
            await backend.close()
            return await backend.probe(await self._discover(entry))

        try:
            state = await entry.queue.run(action)
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

    def add_entry(
        self,
        row: DeviceRow,
        outlet_names: dict[str, str],
        outlet_tokens: dict[str, str] | None = None,
    ) -> None:
        entry = self._make_entry(row, outlet_names, outlet_tokens or {})
        self._devices[row.id] = entry
        self._spawn(self._probe_one(row.id, entry))
        self._broadcast()

    async def remove_entry(self, device_id: str) -> None:
        entry = self._devices.pop(device_id, None)
        if entry:
            await entry.queue.close()
        self._broadcast()

    def update_device(self, row: DeviceRow, *, is_reconnect: bool) -> None:
        """Apply an edited device row in place — the queue and runtime state are kept."""
        entry = self._get_entry(row.id)
        # The IP is runtime state owned by this service; admin edits never carry it
        entry.config = replace(_make_config(row), last_known_ip=entry.config.last_known_ip)
        entry.name = row.name
        entry.group_name = row.group_name
        entry.device_token = row.device_token
        self._broadcast()
        if is_reconnect:
            self._spawn(self._probe_one(row.id, entry, is_reconnect=True))

    def set_outlet_name(self, device_id: str, outlet_id: str, name: str) -> None:
        entry = self._devices.get(device_id)
        if entry:
            entry.outlet_names[outlet_id] = name
            self._broadcast()

    def set_outlet_token(self, device_id: str, outlet_id: str, token: str | None) -> None:
        entry = self._devices.get(device_id)
        if entry:
            if token is None:
                entry.outlet_tokens.pop(outlet_id, None)
            else:
                entry.outlet_tokens[outlet_id] = token
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
            logger.info("Device %s is now online", device_id)
        self._broadcast()
        self._spawn(self._db.update_device_hw(
            device_id,
            hw_alias=state.hw_alias,
            hw_model=state.hw_model,
            hw_is_strip=state.hw_is_strip,
        ))

    async def _config_for(self, entry: DeviceEntry) -> DeviceConfig:
        """Config for the next command, discovering the IP first if none is known yet."""
        if entry.config.last_known_ip is None:
            return await self._discover(entry)
        return entry.config

    async def _discover(self, entry: DeviceEntry) -> DeviceConfig:
        """Broadcast for the device; on a miss the known IP (if any) is left untouched."""
        cfg = entry.config
        logger.info("Discovering %s on %s", cfg.id, cfg.broadcast)
        ip = await entry.backend.discover(cfg)
        if ip is None:
            raise DeviceOfflineError(f"Cannot reach {cfg.mac}: not found on {cfg.broadcast}")
        return self._set_ip(entry, ip)

    def _set_ip(self, entry: DeviceEntry, ip: str) -> DeviceConfig:
        """The only writer of a device's IP, in memory and in the DB."""
        if ip != entry.config.last_known_ip:
            logger.info("Device %s is at %s", entry.config.id, ip)
            entry.config = replace(entry.config, last_known_ip=ip)
            self._spawn(self._db.update_device(entry.config.id, {"last_known_ip": ip}))
        return entry.config

    def _spawn(self, coro: Coroutine[Any, Any, Any]) -> None:
        task = asyncio.create_task(coro)
        self._background_tasks.add(task)
        task.add_done_callback(self._on_background_done)

    def _on_background_done(self, task: asyncio.Task[Any]) -> None:
        self._background_tasks.discard(task)
        if not task.cancelled() and task.exception() is not None:
            logger.error("Background task failed", exc_info=task.exception())

    def _mark_offline(self, device_id: str, entry: DeviceEntry) -> None:
        was_online = entry.is_online
        entry.is_online = False
        if was_online:
            logger.info("Device %s is now offline", device_id)
        self._broadcast()

    def _broadcast(self) -> None:
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    async def _probe_one(
        self, device_id: str, entry: DeviceEntry, *, is_reconnect: bool = False,
    ) -> None:
        """Poll one device; is_reconnect drops the old session first (credentials changed)."""
        if not entry.backend.is_configured(entry.config):
            if is_reconnect:
                self._mark_offline(device_id, entry)  # credentials were cleared
            return
        if entry.queue.is_active() and not is_reconnect:
            logger.debug("Skipping %s — command in progress", device_id)
            return

        async def action(backend: DeviceBackend, config: DeviceConfig) -> DeviceState:
            if is_reconnect:
                await backend.close()
            return await backend.probe(config)

        try:
            state = await entry.queue.run(action)
        except DeviceNotFoundError:
            return  # removed while this poll cycle was running
        except DeviceOfflineError as e:
            if entry.is_online:
                logger.warning("Device %s unreachable: %s", device_id, e)
            self._mark_offline(device_id, entry)
            return
        except DeviceRejectedError as e:
            # Reachable but refused the query: not offline, just no fresh state this cycle
            logger.warning("Device %s rejected poll: %s", device_id, e)
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

    def _make_entry(
        self,
        row: DeviceRow,
        outlet_names: dict[str, str],
        outlet_tokens: dict[str, str] | None = None,
    ) -> DeviceEntry:
        backend = _make_backend(row.type)
        entry = DeviceEntry(
            config=_make_config(row),
            backend=backend,
            # Late-bound on purpose: resolved (and the IP discovered if missing) per command
            queue=DeviceQueue(row.id, backend, lambda: self._config_for(entry)),
            name=row.name,
            group_name=row.group_name,
            state=None,
            is_online=False,
            last_updated=None,
            outlet_names=outlet_names,
            outlet_tokens=outlet_tokens or {},
            device_token=row.device_token,
        )
        return entry


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_config(row: DeviceRow) -> DeviceConfig:
    return DeviceConfig(
        id=row.id,
        mac=row.mac,
        type=row.type,
        broadcast=row.broadcast,
        last_known_ip=row.last_known_ip,
        username=row.kasa_username,
        password=row.kasa_password,
        miio_token=row.miio_token,
        miio_id=row.miio_id,
        hw_model=row.hw_model,
        tuya_device_id=row.tuya_device_id,
        tuya_local_key=row.tuya_local_key,
        tuya_product_id=row.tuya_product_id,
    )


def _make_backend(device_type: str) -> DeviceBackend:
    if device_type == "kasa":
        return KasaBackend()
    if device_type == "miio":
        return MiioBackend()
    if device_type == "tuya":
        return TuyaBackend()
    raise ValueError(f"Unknown device type: {device_type!r}")

"""Manages all devices: DB-backed config, runtime state cache, and polling."""

import asyncio
import contextlib
import dataclasses
import logging
from typing import Literal

from .command_queue import CommandQueue, make_command
from .core.config import DeviceConfig
from .core.exceptions import DeviceOfflineError, DeviceOperationError
from .core.models import ChildState, Device, DeviceState, DeviceStatus, make_offline_state
from .core.registry import PROTOCOLS
from .core.utils import mac_to_id, normalize_mac
from .db import Account, Database, DeviceInfo, Outlet
from .schemas import AddDeviceRequest

logger = logging.getLogger(__name__)

POLL_INTERVAL: float = 60.0


class DeviceManager:
    """Manages all devices: DB-backed config, runtime state cache, polling."""

    def __init__(self, db: Database) -> None:
        self._db = db
        self._devices: dict[str, Device] = {}
        self._queue: CommandQueue | None = None
        self._poll_task: asyncio.Task | None = None
        self._subscribers: set[asyncio.Queue] = set()

    async def initialize(self) -> None:
        """Load from DB → discover → probe initial state → start polling."""
        configs = await self._db.get_all_devices()
        accounts = {a.id: a for a in await self._db.get_all_accounts() if a.id is not None}
        all_outlets = await self._db.get_all_outlets()

        for cfg in configs:
            spec = PROTOCOLS.get(cfg.type)
            if not spec:
                logger.error(f"Unknown protocol '{cfg.type}' for device '{cfg.name}', skipping")
                continue

            outlets = all_outlets.get(cfg.id, [])
            initial_state = DeviceState(
                id=cfg.id,
                status=DeviceStatus.OFFLINE,
                alias=cfg.alias,
                model=cfg.model,
                children=tuple(
                    ChildState(id=o.outlet_id, alias=o.alias, is_on=False)
                    for o in outlets
                ) if cfg.is_strip else None,
            )

            backend = spec.backend()
            backend.ip = cfg.last_known_ip
            if cfg.account_id:
                backend.configure(accounts.get(cfg.account_id))

            outlet_labels = {o.outlet_id: o.alias for o in outlets if o.alias}
            self._devices[cfg.id] = Device(
                config=cfg, backend=backend, state=initial_state,
                outlet_labels=outlet_labels,
            )

        for type_name, spec in PROTOCOLS.items():
            type_devices = {cfg.mac: cfg for cfg in configs if cfg.type == type_name}
            if not type_devices:
                continue

            logger.info(f"Discovering {type_name} devices ({len(type_devices)} configured)...")
            ip_map = await spec.discover_all(type_devices)

            for cfg in type_devices.values():
                device = self._devices.get(cfg.id)
                if not device:
                    continue
                if ip_map.get(cfg.mac):
                    device.backend.ip = ip_map[cfg.mac]

                if device.backend.ip:
                    try:
                        state = await device.backend.fetch_state(cfg, device.backend.ip)
                        if state:
                            await self._update_state(cfg.id, state, update_db_cache=True)
                            continue
                    except Exception as e:
                        logger.warning(f"Failed to probe {cfg.name} during init: {e}")

                self._log_status_change(cfg.name, None, device.state)

        self._queue = CommandQueue(devices=self._devices)
        self._poll_task = asyncio.create_task(self._polling_loop())

        online = sum(1 for d in self._devices.values() if d.state.status == DeviceStatus.ONLINE)
        logger.info(f"Initialization complete: {online}/{len(self._devices)} devices online")

    async def shutdown(self) -> None:
        """Cancel polling and close all backend connections."""
        if self._poll_task:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            logger.info("Polling stopped")

        if self._queue:
            await self._queue.shutdown()

        for device in self._devices.values():
            await device.backend.close()

        logger.info("All backend connections closed")

    async def set_device_power(
        self, device_id: str, action: Literal["on", "off"], child_id: str | None = None
    ) -> DeviceState:
        """Submit command to queue, wait for completion, update state cache."""
        if device_id not in self._devices:
            raise ValueError(f"Device {device_id} not found")
        if not self._queue:
            raise RuntimeError("Device manager not initialized")

        cmd = make_command(device_id, action, child_id)
        cmd = self._queue.submit(cmd)
        try:
            state = await self._queue.wait_for_command(cmd)
        except DeviceOfflineError:
            await self._update_state(
                device_id, make_offline_state(device_id, self._devices[device_id].state)
            )
            raise
        await self._update_state(device_id, state)
        return state

    async def refresh_device(self, device_id: str) -> DeviceState:
        """Re-discover and probe a single device. Useful for offline recovery."""
        device = self._devices.get(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        if device.backend.ip:
            logger.info(f"Refreshing {device.config.name} at cached IP {device.backend.ip}")
            state = await device.backend.fetch_state(device.config, device.backend.ip)
            if state:
                await self._update_state(device_id, state, update_db_cache=True)
                return state

        logger.info(f"Cached IP unreachable for {device.config.name}, rediscovering...")
        new_ip = await device.backend.find_ip(device.config)
        if new_ip:
            state = await device.backend.fetch_state(device.config, new_ip)
            if state:
                await self._update_state(device_id, state, update_db_cache=True)
                return state

        logger.warning(f"Could not reach {device.config.name} during refresh")
        state = make_offline_state(device_id, device.state)
        await self._update_state(device_id, state)
        return state

    def get_all_devices(self) -> list[Device]:
        return list(self._devices.values())

    def get_device(self, device_id: str) -> Device:
        device = self._devices.get(device_id)
        if device is None:
            raise ValueError(f"Device {device_id} not found")
        return device

    # ── Admin operations ─────────────────────────────────────────────────────

    async def add_device(self, body: AddDeviceRequest) -> Device:
        """Validate, persist to DB, add to RAM as OFFLINE, then probe in background."""
        mac = normalize_mac(body.mac)
        device_id = mac_to_id(mac)

        if device_id in self._devices:
            raise ValueError(f"Device with MAC '{body.mac}' already exists")

        spec = PROTOCOLS.get(body.type)
        if not spec:
            raise ValueError(f"Unsupported device type: {body.type}")

        info = DeviceInfo(
            id=device_id, mac=mac, name=body.name, type=body.type,
            broadcast=body.broadcast, group_name=body.group_name,
            account_id=body.account_id, token=body.token, miio_id=body.miio_id,
        )
        cfg = await self._db.add_device(info)

        backend = spec.backend()
        backend.ip = cfg.last_known_ip
        if cfg.account_id:
            accounts = {a.id: a for a in await self._db.get_all_accounts() if a.id is not None}
            backend.configure(accounts.get(cfg.account_id))

        device = Device(config=cfg, backend=backend, state=DeviceState(
            id=cfg.id, status=DeviceStatus.OFFLINE,
        ))
        self._devices[cfg.id] = device
        self._broadcast()

        asyncio.create_task(self._probe_new_device(device))
        return device

    async def _probe_new_device(self, device: Device) -> None:
        """Background probe after add_device — updates state and DB cache on success."""
        try:
            ip = await device.backend.find_ip(device.config)
            if not ip:
                return
            state = await device.backend.fetch_state(device.config, ip)
            if state:
                await self._update_state(device.config.id, state, update_db_cache=True)
        except Exception as e:
            logger.warning(f"Initial probe failed for new device {device.config.name}: {e}")

    async def remove_device(self, device_id: str) -> None:
        """Close backend, cancel its queue processor, remove from cache and DB."""
        device = self._devices.get(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        if self._queue:
            task = self._queue._processors.get(device_id)
            if task and not task.done():
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

        await device.backend.close()
        del self._devices[device_id]
        await self._db.remove_device(device_id)
        self._broadcast()

    async def rename_device(self, device_id: str, new_name: str) -> None:
        """Persist to DB and RAM first, then push to hardware (best-effort)."""
        device = self._devices.get(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")
        await self._db.update_device_name(device_id, new_name)
        device.config = dataclasses.replace(device.config, name=new_name)
        await device.backend.rename_device(device.config, new_name)
        self._broadcast()

    async def rename_outlet(self, device_id: str, outlet_id: str, new_name: str) -> None:
        """Rename outlet: push to hardware (if supported), persist to DB, update cache."""
        device = self._devices.get(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")

        await device.backend.rename_outlet(device.config, outlet_id, new_name)
        await self._db.upsert_outlet(Outlet(device_id=device_id, outlet_id=outlet_id, alias=new_name))
        device.outlet_labels[outlet_id] = new_name

        if device.state.children:
            new_children = tuple(
                dataclasses.replace(c, alias=new_name) if c.id == outlet_id else c
                for c in device.state.children
            )
            device.state = dataclasses.replace(device.state, children=new_children)
        self._broadcast()

    async def get_accounts(self) -> list[Account]:
        return await self._db.get_all_accounts()

    async def add_account(self, row: Account) -> Account:
        return await self._db.add_account(row)

    async def remove_account(self, account_id: int) -> None:
        affected = [d for d in self._devices.values() if d.config.account_id == account_id]
        if affected:
            names = ', '.join(d.config.name for d in affected)
            raise ValueError(
                f"Cannot delete: {len(affected)} device(s) still use this account ({names})"
            )
        await self._db.remove_account(account_id)

    # ── SSE ──────────────────────────────────────────────────────────────────

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue[None] = asyncio.Queue(maxsize=1)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    # ── Internal ─────────────────────────────────────────────────────────────

    def _apply_outlets(self, device: Device, state: DeviceState) -> DeviceState:
        """Overlay user outlet labels (RAM cache) onto state children."""
        if not state.children or not device.outlet_labels:
            return state
        new_children = tuple(
            dataclasses.replace(c, alias=device.outlet_labels.get(c.id, c.alias))
            for c in state.children
        )
        return dataclasses.replace(state, children=new_children)

    async def _update_state(
        self,
        device_id: str,
        new_state: DeviceState,
        update_db_cache: bool = False,
    ) -> None:
        """Single write point for the state cache."""
        device = self._devices[device_id]
        previous = device.state
        labeled = self._apply_outlets(device, new_state)
        device.state = labeled
        self._log_status_change(device.config.name, previous, labeled)
        self._broadcast()

        if update_db_cache and labeled.status == DeviceStatus.ONLINE:
            await self._db.update_device_cache(
                device_id,
                alias=labeled.alias,
                model=labeled.model,
                is_strip=labeled.is_strip,
                ip=device.backend.ip,
            )
            device.config = dataclasses.replace(
                device.config,
                alias=labeled.alias,
                model=labeled.model,
                is_strip=labeled.is_strip,
                last_known_ip=device.backend.ip,
            )
            if labeled.children:
                await self._db.upsert_outlets([
                    Outlet(device_id=device_id, outlet_id=c.id, alias=c.alias)
                    for c in labeled.children
                ])
                # Register hardware aliases for outlets that have no user label yet
                for c in labeled.children:
                    if c.id not in device.outlet_labels and c.alias:
                        device.outlet_labels[c.id] = c.alias

    def _broadcast(self) -> None:
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass

    @staticmethod
    def _log_status_change(
        name: str, previous: DeviceState | None, current: DeviceState
    ) -> None:
        if previous is None or previous.status != current.status:
            if current.status == DeviceStatus.ONLINE:
                logger.info(f"{name} is now online")
            else:
                logger.info(f"{name} is now offline")

    async def _poll_one(self, device_id: str, device: Device) -> None:
        """Poll a single device."""
        if self._queue and self._queue.has_active_processor(device_id):
            logger.debug(f"Polling skipping {device.config.name} — processor active")
            return
        if not device.backend.ip:
            logger.debug(f"Polling skipping {device.config.name} — no known IP")
            return
        try:
            state = await device.backend.fetch_state(device.config, device.backend.ip)
            await self._update_state(
                device_id,
                state or make_offline_state(device_id, device.state),
                update_db_cache=state is not None,
            )
        except (DeviceOfflineError, DeviceOperationError, asyncio.TimeoutError, OSError) as e:
            logger.warning(f"Polling probe failed for {device.config.name}: {e}")
            await self._update_state(device_id, make_offline_state(device_id, device.state))
        except Exception:
            logger.exception(f"Unexpected error polling {device.config.name}")
            await self._update_state(device_id, make_offline_state(device_id, device.state))

    async def _polling_loop(self) -> None:
        logger.debug(f"Polling started (interval={POLL_INTERVAL}s)")
        while True:
            await asyncio.sleep(POLL_INTERVAL)
            logger.debug("Polling cycle starting")
            await asyncio.gather(
                *[self._poll_one(did, dev) for did, dev in list(self._devices.items())],
                return_exceptions=True,
            )
            logger.debug("Polling cycle complete")

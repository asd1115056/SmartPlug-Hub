# SmartPlug Hub

A web-based controller for smart plugs and power strips. Supports multiple protocols (Kasa, MiIO) through a unified API and admin panel.

## Requirements

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager

## Quick Start

```bash
# Install dependencies
uv sync

# Configure admin token
cp config/settings.toml.example config/settings.toml
# Edit config/settings.toml and set a strong token

# Run the server
uv run smartplug-hub

# Open http://localhost:8000
# Admin panel at http://localhost:8000/admin
```

Options:

```text
--port PORT    Port to listen on (default: 8000)
--debug        Enable debug logging for app.* loggers
```

## Configuration

### `config/settings.toml`

```toml
[admin]
token = "change-me-to-a-strong-secret"
```

This token is required to access the admin panel at `/admin`.

### Adding Devices

Devices and accounts are managed through the admin panel — no config files needed.

1. **Add an account** — TP-Link credentials for Kasa devices that require authentication (newer KLAP-based firmware), or any label for MiIO
2. **Add a device** — MAC address, broadcast address, optional group name, optional account

**Scan Network** (recommended): click *Scan Network* in the Devices tab to auto-discover all Kasa and MiIO devices on every local network interface. Results show type, model, MAC, IP, and broadcast address — click *+ Add* on any row to pre-fill the Add Device form.

#### Finding your Kasa device MAC and credentials

```bash
uv run kasa discover
```

Newer Kasa devices (EP25, KP125M, etc.) require TP-Link account credentials. Older models (HS103, KP303, etc.) work without authentication.

#### Finding your MiIO device token and ID

MiIO requires a 32-character hex token and a numeric device ID.

- **Token**: visible in plaintext on **unprovisioned** devices via UDP discovery. For already-provisioned devices (token shows as `ffffffffffffffffffffffffffffffff`), extract it from the Xiaomi cloud using [Xiaomi Cloud Tokens Extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor).
- **Device ID**: returned alongside the token during discovery.

## Architecture

### Module Structure

```text
smartplug-hub/
├── app/
│   ├── backends/
│   │   ├── kasa.py          # Kasa backend — persistent TCP, reconnects on demand
│   │   └── miio.py          # MiIO backend — stateless UDP
│   ├── admin/
│   │   ├── auth.py          # Bearer token authentication
│   │   ├── router.py        # Admin API routes
│   │   └── service.py       # Admin CRUD operations (pure functions)
│   ├── __main__.py          # Entry point (uv run smartplug-hub)
│   ├── command_queue.py     # Per-device command serialization with session lifecycle
│   ├── core.py              # DeviceBackend ABC, DeviceConfig, DeviceState, exceptions
│   ├── db.py                # SQLite layer (devices, accounts, outlet names)
│   ├── device_service.py    # Runtime state: polling, command dispatch, SSE broadcast
│   ├── logging.py           # Rich handler + library log suppression
│   ├── main.py              # FastAPI app, public API, SSE, lifespan
│   └── schemas.py           # Pydantic request/response models
├── config/
│   ├── settings.toml        # Admin token (create from example)
│   └── settings.toml.example
├── data/
│   └── smartplug.db         # SQLite database (auto-created)
├── static/
│   ├── index.html           # Main web UI
│   ├── index.js             # Main page wiring (ES modules)
│   ├── admin.html           # Admin panel
│   ├── admin.js             # Admin panel wiring
│   ├── style.css
│   └── js/
│       ├── api.js           # Public API fetch wrappers
│       ├── devices.js       # Device card rendering
│       ├── notifications.js # Toast + notification bell
│       ├── sse.js           # SSE connection with auto-reconnect
│       └── admin/
│           ├── api.js       # Admin API fetch wrappers
│           ├── auth.js      # Token login + sessionStorage
│           ├── accounts.js  # Accounts CRUD UI
│           └── devices.js   # Devices CRUD + outlets modal
└── pyproject.toml
```

### Connection Strategy (Kasa)

Kasa devices use **short-term persistent TCP connections** managed per device:

- Connects on the first command (not at startup)
- Consecutive commands reuse the existing connection
- After 60 seconds of idle, the connection is automatically closed
- On first contact or after failure: try last known IP → broadcast discover → mark offline
- Use `POST /api/v1/devices/{id}/refresh` to trigger rediscovery for an offline device

### Connection Strategy (MiIO)

MiIO devices use **stateless UDP** — each command is an independent encrypted packet:

- Every command opens a UDP socket, sends the request, and closes immediately
- On first contact: try last known IP → broadcast discover
- On failure: mark offline (use `POST /refresh` to trigger rediscovery)

### Command Queue

Each device has its own `DeviceQueue` that serializes commands and manages the backend session lifecycle:

- Deduplicates identical pending commands (e.g. two rapid "turn on" clicks)
- Rate-limits commands per backend (`command_interval`)
- For stateful backends (Kasa): holds the TCP connection open between commands
- After each command, re-reads device state and broadcasts via SSE

### Real-time Updates (SSE)

The frontend subscribes to `GET /api/v1/events` (Server-Sent Events). State changes — from commands, refresh, or background polling — fan out immediately to all connected clients via a per-subscriber `asyncio.Queue`. The background loop polls all devices every 60 seconds to detect external state changes (physical button presses, Kasa app).

## API Reference

All public endpoints are under `/api/v1/`. Admin endpoints are under `/api/v1/admin/` and require `Authorization: Bearer <token>`.

### Public Endpoints

| Method  | Path                           | Description                                     |
|---------|--------------------------------|-------------------------------------------------|
| `GET`   | `/api/v1/devices`              | Cached status of all devices (zero I/O)         |
| `GET`   | `/api/v1/devices/{id}`         | Single device cached status                     |
| `PATCH` | `/api/v1/devices/{id}`         | Control device (on/off), blocks until complete  |
| `POST`  | `/api/v1/devices/{id}/refresh` | Force rediscovery for offline device            |
| `GET`   | `/api/v1/events`               | SSE stream — push on change, 5s keepalive       |

### Device Object

```json
{
  "id": "a1b2c3d4",
  "name": "Living Room Strip",
  "type": "kasa",
  "group_name": "Living Room",
  "model": "KP303",
  "is_strip": true,
  "is_online": true,
  "is_on": true,
  "last_updated": "2024-01-15T10:30:00+00:00",
  "watts": 42.5,
  "outlets": [
    { "outlet_id": "abc123", "name": "Outlet 1", "is_on": true, "watts": 42.5 },
    { "outlet_id": "def456", "name": "Outlet 2", "is_on": false, "watts": 0.0 }
  ]
}
```

`GET /api/v1/devices` returns a flat array of device objects. `is_on`, `outlets`, and `watts` are `null` until the first successful poll. `watts` is instantaneous power in watts; `null` if the device does not support energy monitoring.

### PATCH /api/v1/devices/{id}

Control a device or a single outlet. Blocks until the operation completes (or fails).

Request body:

```json
{ "outlet_id": "abc123", "on": true }
```

| Field       | Required | Description                                              |
|-------------|----------|----------------------------------------------------------|
| `on`        | Yes      | `true` to turn on, `false` to turn off                   |
| `outlet_id` | No       | Outlet ID for power strips; omit to control whole device |

Response (200): updated device object.

Error codes: `404` device not found, `503` device offline.

### POST /api/v1/devices/{id}/refresh

Force-closes the cached connection, clears the cached IP, and rediscovers the device from scratch. Useful when a device changes IP address.

Returns the updated device object. Returns `503` if the device is still unreachable after rediscovery.

### GET /api/v1/events

Server-Sent Events stream. Each event is a JSON array of all device objects (same shape as `GET /api/v1/devices`). A `: keepalive` comment is sent every 5 seconds when idle.

### Device ID

Devices are identified by an 8-character hex ID derived from their MAC address (first 8 characters of SHA-256). This remains stable even when the device's IP address changes.

Example: MAC `AA:BB:CC:DD:EE:FF` → ID `a1b2c3d4`

# SmartPlug Hub

A web-based controller for smart plugs and power strips. Supports multiple protocols (Kasa, MiIO, Tuya) through a unified API and admin panel.

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

Devices and accounts are managed through the admin panel at `/admin` — no config files needed.

**Scan Network**: click *Scan* at the top of the admin panel to discover Kasa, MiIO, and Tuya devices on every local network interface. Results are grouped by subnet and show type, model, IP, and MAC. Click *+ Add* on any row to immediately register the device. Click the device card to open its detail panel and set a name, group, or credentials.

#### Finding your Kasa device MAC and credentials

```bash
uv run kasa discover
```

Newer Kasa devices (EP25, KP125M, etc.) require TP-Link account credentials — enter them in the device's **Kasa** section in the detail panel. Older models (HS103, KP303, etc.) work without authentication.

#### Finding your MiIO device token and ID

MiIO requires a 32-character hex token and a numeric device ID.

- **Token**: visible in plaintext on **unprovisioned** devices via UDP discovery. For already-provisioned devices (token shows as `ffffffffffffffffffffffffffffffff`), use [Xiaomi Cloud Tokens Extractor](https://github.com/PiotrMachowski/Xiaomi-cloud-tokens-extractor) to retrieve it.
- **Device ID**: returned alongside the token during discovery.

#### Finding your Tuya device ID and local key

Tuya requires a **Device ID** (gwId) and a **Local Key** (16-character encryption key).

**Recommended**: use the tinytuya wizard — it fetches both automatically from the Tuya cloud:

```bash
uv run python -m tinytuya wizard
```

You will need a [Tuya IoT Platform](https://iot.tuya.com) developer account with an API Key and API Secret. The wizard writes `devices.json` containing the Device ID (`id`) and Local Key (`key`) for every device linked to your account.

> **Note**: Scan Network pre-fills the Device ID from the UDP discovery response. The Local Key is never transmitted over the network — it must be retrieved via the wizard or the Tuya IoT Platform web UI.

## Architecture

### Module Structure

```text
smartplug-hub/
├── app/
│   ├── backends/
│   │   ├── kasa.py          # Kasa backend — persistent TCP, reconnects on demand
│   │   ├── miio.py          # MiIO backend — stateless UDP
│   │   └── tuya.py          # Tuya backend — local encrypted LAN (tinytuya)
│   ├── admin/
│   │   ├── auth.py          # Bearer token authentication
│   │   ├── router.py        # Admin API routes
│   │   └── service.py       # Admin CRUD operations (pure functions)
│   ├── __main__.py          # Entry point (uv run smartplug-hub)
│   ├── command_queue.py     # Per-device command serialization with session lifecycle
│   ├── core.py              # DeviceBackend ABC, DeviceConfig, DeviceState, exceptions
│   ├── db.py                # SQLite layer (devices, outlet names, outlet tokens)
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
│           └── devices.js   # Device cards, scan results, detail panel
└── pyproject.toml
```

### Connection Strategy (Kasa)

Kasa devices use **short-term persistent TCP connections** managed per device:

- Connects on the first command (not at startup)
- Back-to-back commands reuse the existing connection
- After 20 seconds of idle, the connection is deterministically closed — well under the
  60s poll interval, so polling always re-establishes a fresh connection each cycle
  instead of holding one open indefinitely
- Connects to the last known IP; if it fails (or now answers as another device), the device is
  marked offline — no automatic rediscovery
- Broadcast discovery runs only when no IP is known: a newly added device, or after
  `POST /api/v1/devices/{id}/refresh`, which clears the IP

### Connection Strategy (MiIO)

MiIO devices use **stateless UDP** — each command is an independent encrypted packet:

- Every command opens a UDP socket, sends the request, and closes immediately
- Sends to the last known IP; on failure the device is marked offline
- Broadcast discovery runs only when no IP is known (new device, or after `POST /refresh`)

### Connection Strategy (Tuya)

Tuya devices use **local encrypted LAN protocol** via [tinytuya](https://github.com/jasonacox/tinytuya):

- Each command opens a TCP connection to the device's last known IP, sends the encrypted payload, and closes
- Broadcast discovery runs only when no IP is known (new device, or after `POST /refresh`)
- Protocol v3.5 with session key negotiation using the device's local key
- Requires `tuya_device_id` (gwId) and `tuya_local_key` set on the device record

### Scan Strategy (Tuya)

Tuya scan sends an **encrypted UDP discovery broadcast** on ports 6666, 6667, and 7000 using tinytuya's hardcoded `udpkey`. All Tuya protocol versions (v3.1 through v3.5) respond to this broadcast. The response includes `gwId` (Device ID), `productKey`, and `version` — no credentials needed. The Local Key is not in the response and must be entered manually from the Tuya IoT Platform.

### Command Queue

Each device has its own `DeviceQueue` that serializes *every* backend operation for that
device — power commands, hardware rename, forced refresh, and the periodic background
poll all go through the same queue, so exactly one is ever talking to the device at a time:

- Deduplicates identical pending power commands (e.g. two rapid "turn on" clicks)
- Rate-limits commands per backend (`command_interval`)
- For stateful backends (Kasa): holds the TCP connection open between back-to-back operations
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
  "has_token": false,
  "last_updated": "2024-01-15T10:30:00+00:00",
  "watts": 42.5,
  "outlets": [
    { "outlet_id": "abc123", "name": "Outlet 1", "is_on": true, "watts": 42.5, "has_token": true },
    { "outlet_id": "def456", "name": "Outlet 2", "is_on": false, "watts": 0.0, "has_token": false }
  ]
}
```

`GET /api/v1/devices` returns a flat array of device objects. `is_on`, `outlets`, and `watts` are `null` until the first successful poll. `watts` is instantaneous power in watts; `null` if the device does not support energy monitoring. `has_token` indicates whether a token is required to control the device or outlet.

### PATCH /api/v1/devices/{id}

Control a device or a single outlet. Blocks until the operation completes (or fails).

Request body:

```json
{ "outlet_id": "abc123", "on": true, "token": "secret" }
```

| Field       | Required | Description                                                  |
|-------------|----------|--------------------------------------------------------------|
| `on`        | Yes      | `true` to turn on, `false` to turn off                       |
| `outlet_id` | No       | Outlet ID for power strips; omit to control whole device     |
| `token`     | No       | Required if the device or outlet has an access token set     |

Response (200): updated device object.

Error codes: `403` missing or invalid token, `404` device not found, `503` device offline.

### POST /api/v1/devices/{id}/refresh

Force-closes the cached connection, clears the cached IP, and rediscovers the device from scratch. Useful when a device changes IP address.

Returns the updated device object. Returns `503` if the device is still unreachable after rediscovery.

### GET /api/v1/events

Server-Sent Events stream. Each event is a JSON array of all device objects (same shape as `GET /api/v1/devices`). A `: keepalive` comment is sent every 5 seconds when idle.

### Access Tokens (Admin)

Devices and individual outlets can be protected with an optional access token. When set, every `PATCH /api/v1/devices/{id}` request must include the correct `token` field or the server returns `403`.

Tokens are managed via the admin panel or the following admin API endpoints (require `Authorization: Bearer <admin-token>`):

| Method  | Path                                            | Description                        |
|---------|-------------------------------------------------|------------------------------------|
| `PATCH` | `/api/v1/admin/devices/{id}/token`              | Set or clear the device token      |
| `PATCH` | `/api/v1/admin/devices/{id}/outlets/{oid}/token`| Set or clear an outlet token       |

Request body for both: `{ "token": "secret" }` — send `null` or omit to clear.

### Device ID

Devices are identified by an 8-character hex ID derived from their MAC address (first 8 characters of SHA-256). This remains stable even when the device's IP address changes.

Example: MAC `AA:BB:CC:DD:EE:FF` → ID `a1b2c3d4`

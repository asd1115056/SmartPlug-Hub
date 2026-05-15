# SmartPlug Hub

A web-based controller for smart plugs and power strips. Supports multiple protocols (Kasa, MiIO) through a unified API, with more protocols easy to add.

## Requirements

- Python >= 3.12
- [uv](https://docs.astral.sh/uv/) package manager

## Quick Start

```bash
# Install dependencies
uv sync

# Configure devices (see Configuration section)
cp config/devices.example.json config/devices.json

# Run the server
uv run smartplug-hub
# Or with auto-reload for development
uv run uvicorn app.main:app --reload

# Open http://localhost:8000
```

## Configuration

### Device Whitelist (`config/devices.json`)

Copy `config/devices.example.json` to `config/devices.json` and add your devices.

```json
{
  "devices": [
    {
      "mac": "AA:BB:CC:DD:EE:FF",
      "name": "Living Room Strip",
      "type": "kasa",
      "broadcast": "192.168.1.255",
      "username": "your@email.com",
      "password": "your_password",
      "group": "Living Room"
    },
    {
      "mac": "11:22:33:44:55:66",
      "name": "Bedroom Plug (no auth needed)",
      "type": "kasa",
      "broadcast": "192.168.1.255",
      "group": "Bedroom"
    }
  ]
}
```

#### Common fields

| Field | Required | Description |
|-------|----------|-------------|
| `mac` | Yes | Device MAC address (formats: `AA:BB:CC:DD:EE:FF`, `AA-BB-CC-DD-EE-FF`, `AABBCCDDEEFF`) |
| `name` | No | Display name (defaults to device ID if omitted) |
| `type` | Yes | Protocol: `"kasa"` |
| `broadcast` | Yes | Broadcast address for discovery (e.g., `192.168.1.255`) |

#### Kasa-specific fields

| Field | Required | Description |
|-------|----------|-------------|
| `username` | No | TP-Link account email (for newer devices requiring authentication) |
| `password` | No | TP-Link account password |
| `group` | No | Tab group name in the web UI (e.g., `"Living Room"`). Devices without a group appear only in All. |

**Connection strategy:** The system first attempts to connect without credentials. If authentication is required, it retries with the provided credentials.

**Finding your Kasa device MAC address:**
```bash
uv run kasa discover
```

## Architecture

### Module Structure

```
app/
├── core/
│   ├── config.py        # Whitelist loading and ID resolution
│   ├── models.py        # Shared types, exceptions, DeviceBackend ABC
│   ├── registry.py      # Protocol registration
│   └── utils.py         # Shared utilities (e.g. MAC normalisation)
├── kasa/
│   ├── __init__.py      # Exports KasaBackend, discover_all
│   ├── backend.py       # KasaBackend: persistent TCP connection pool
│   ├── config.py        # KasaDeviceConfig dataclass
│   └── connection.py    # Stateless Kasa network functions
├── __main__.py          # Entry point (uv run smartplug-hub)
├── command_queue.py     # Protocol-agnostic per-device command queue
├── device_manager.py    # Facade: lifecycle, state cache, polling, SSE broadcast
└── main.py              # FastAPI routes and lifecycle
```

Adding a new protocol only requires a new `app/<protocol>/` subpackage — no changes to `app/core/` or `app/` root files.

### Connection Strategy (Kasa)

Kasa devices can't handle frequent TCP connections, but long-lived connections go stale. The solution is **short-term persistent connections** managed by `KasaBackend`:

- The command queue processor connects on the first command (not at startup)
- Consecutive commands to the same device reuse the connection
- After 60 seconds of idle, the connection is automatically closed
- On failure: retry with cached IP → discover new IP → retry → mark offline

### Backend ABC

All protocol backends implement `DeviceBackend`:

```
DeviceBackend (ABC)
  policy             # BackendPolicy: session_timeout, command_interval, command_timeout
  execute_command()  # Called by CommandQueue; owns retry, rediscovery, connection lifecycle
  fetch_state()      # One-shot: connect, verify identity, read state, disconnect
  find_ip()          # Broadcast to locate this device's current IP
  close()            # Close open connections on shutdown (default: no-op)
```

### Real-time Updates (SSE)

The frontend subscribes to `GET /api/v1/events` (Server-Sent Events). State changes — from commands, refresh, or the background polling loop — fan-out immediately to all connected clients via a per-subscriber `asyncio.Queue`. The background loop polls physical devices every 60 seconds to detect external changes (physical button, Kasa app).

## API Reference

All endpoints are under `/api/v1/`.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/devices` | Get cached status of all devices (zero I/O) |
| GET | `/api/v1/devices/{id}` | Get single device cached status |
| PATCH | `/api/v1/devices/{id}` | Control device (on/off), blocks until complete |
| POST | `/api/v1/devices/{id}/refresh` | Rediscover offline device |
| GET | `/api/v1/events` | SSE stream: push state on change, heartbeat every 30s when idle |

### Device ID

Devices are identified by an 8-character ID derived from their MAC address (SHA-256 hash).
This provides a stable identifier that doesn't change when the device's IP address changes.

Example: MAC `AA:BB:CC:DD:EE:FF` → ID `a1b2c3d4`

### Device Status

| Status    | Description |
|-----------|-------------|
| `online`  | Device is connected and responding |
| `offline` | Device unreachable; topology preserved for UI display |

### Examples

#### GET /api/v1/devices

Returns cached state of all devices. Zero I/O.

```json
{
  "devices": [
    {
      "id": "a1b2c3d4",
      "name": "Living Room Strip",
      "status": "online",
      "is_on": true,
      "alias": "TP-LINK_Power Strip_A1B2",
      "model": "KP303",
      "is_strip": true,
      "children": [
        { "id": "0", "alias": "Outlet 1", "is_on": true },
        { "id": "1", "alias": "Outlet 2", "is_on": false }
      ],
      "last_updated": "2024-01-15T10:30:00.000000",
      "group": "Living Room"
    }
  ]
}
```

#### PATCH /api/v1/devices/{id}

Control a device. Blocks until the operation completes (or fails).

Request:
```json
{
  "is_on": true,
  "child_id": "optional_outlet_id"
}
```

| Field | Required | Description |
|-------|----------|-------------|
| `is_on` | Yes | `true` to turn on, `false` to turn off |
| `child_id` | No | Outlet ID for power strips |

Response (200): Full `DeviceState` with updated values.

Error responses:

| Code | Meaning |
|------|---------|
| 400 | Invalid action or child_id |
| 503 | Device offline (retry + discover all failed) |
| 502 | Operation failed but device may still be online |
| 504 | Command queue timeout |

#### POST /api/v1/devices/{id}/refresh

Rediscover an offline device. Returns `DeviceState` with status code 200 (online) or 503 (still offline).

## Project Structure

```
smartplug-hub/
├── app/
│   ├── core/
│   │   ├── config.py           # Whitelist configuration
│   │   ├── models.py           # Shared types, exceptions, DeviceBackend ABC
│   │   ├── registry.py         # Protocol registration
│   │   └── utils.py            # Shared utilities
│   ├── kasa/
│   │   ├── __init__.py
│   │   ├── backend.py          # KasaBackend
│   │   ├── config.py           # KasaDeviceConfig
│   │   └── connection.py       # Stateless Kasa network functions
│   ├── __main__.py             # Entry point
│   ├── command_queue.py        # Protocol-agnostic command queue
│   ├── device_manager.py       # Facade combining all modules
│   └── main.py                 # FastAPI routes and lifecycle
├── config/
│   ├── devices.json            # Device whitelist (create from example)
│   └── devices.example.json
├── static/
│   ├── index.html              # Web UI
│   ├── app.js                  # Frontend logic
│   └── style.css
└── pyproject.toml
```

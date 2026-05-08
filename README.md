# Kasa Web Controller

A web-based controller for smart devices. Supports TP-Link Kasa devices through a unified API, with more protocols easy to add.

## Features

- Multi-protocol backend architecture (Kasa)
- MAC-based device identification (stable across IP changes)
- Per-device command queue with deduplication and concurrency control
- Short-term persistent connections for Kasa (30s idle disconnect)
- Automatic retry + rediscovery on connection failure
- Power strip support with individual outlet control
- Offline device handling with preserved topology
- Background health check for automatic state updates
- Web UI with Bootstrap 5, group tabs, and real-time search

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
uv run kasa-web
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
├── kasa/
│   ├── __init__.py      # Exports KasaBackend, discover_all
│   ├── connection.py    # Stateless Kasa network functions
│   └── backend.py       # KasaBackend: persistent TCP connection pool
├── miio/                # Phase 1 (in progress)
│   ├── __init__.py
│   ├── connection.py
│   └── backend.py
├── models.py            # DeviceInfo, KasaDeviceConfig, DeviceBackend ABC
├── config.py            # Whitelist loading and ID resolution
├── command_queue.py     # Protocol-agnostic per-device command queue
├── device_manager.py    # Thin facade: lifecycle, state cache
└── main.py              # FastAPI routes and lifecycle
```

Adding a new protocol only requires a new `app/<protocol>/` subpackage — no changes to `app/` root files.

### Connection Strategy (Kasa)

Kasa devices can't handle frequent TCP connections, but long-lived connections go stale. The solution is **short-term persistent connections** managed by `KasaBackend`:

- The command queue processor connects on the first command (not at startup)
- Consecutive commands to the same device reuse the connection
- After 30 seconds of idle, the connection is automatically closed
- On failure: retry with cached IP → discover new IP → retry → mark offline

### Backend ABC

All protocol backends implement `DeviceBackend`:

```
DeviceBackend (ABC)
  session_timeout    # How long CommandQueue processor stays alive after last command
  command_interval   # Rate limiting between commands
  execute_command()  # Called by CommandQueue for each command
  cleanup()          # Called on idle timeout or shutdown (default: no-op)
  refresh()          # Re-discover + get fresh state (offline recovery)
  health_check()     # Periodic poll (return None to skip this cycle)
```

## API Reference

All endpoints are under `/api/v1/`.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/v1/devices` | Get cached status of all devices (zero I/O) |
| GET | `/api/v1/devices/{id}` | Get single device cached status |
| PATCH | `/api/v1/devices/{id}` | Control device (on/off), blocks until complete |
| POST | `/api/v1/devices/{id}/refresh` | Rediscover offline device |

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

Returns cached state of all devices. Zero I/O, suitable for polling.

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
kasa-web-controller/
├── app/
│   ├── kasa/
│   │   ├── __init__.py
│   │   ├── connection.py       # Stateless Kasa network functions
│   │   └── backend.py          # KasaBackend
│   ├── __init__.py
│   ├── models.py               # Shared types, exceptions, DeviceBackend ABC
│   ├── config.py               # Whitelist configuration
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

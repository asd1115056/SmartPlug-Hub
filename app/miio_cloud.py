"""Xiaomi cloud token lookup — subprocess wrapper with captcha passthrough."""

import asyncio
import json
import logging
import re
import sys
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

_EXTRACTOR = Path(__file__).parent.parent / "vendor" / "xiaomi-extractor" / "token_extractor.py"

def _load_regions() -> tuple[str, ...]:
    m = re.search(r'^SERVERS\s*=\s*\[([^\]]+)\]', _EXTRACTOR.read_text(), re.MULTILINE)
    if not m:
        return ("cn", "de", "us", "ru", "tw", "sg", "in", "i2")
    return tuple(s.strip().strip('"').strip("'") for s in m.group(1).split(",") if s.strip())

REGIONS = _load_regions()
_ANSI = re.compile(r"\x1b\[[0-9;]*m")

# session_id → {proc, output_path, mac, auto_responded}
_sessions: dict[str, dict] = {}


def _strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


async def start_login(username: str, password: str, region: str, mac: str) -> dict:
    """Start Xiaomi cloud login. Returns {token, did} or {session_id, captcha_url}."""
    output_path = Path(f"/tmp/miio-{uuid.uuid4().hex}.json")
    session_id = uuid.uuid4().hex

    proc = await asyncio.create_subprocess_exec(
        sys.executable, str(_EXTRACTOR),
        "--username", username,
        "--password", password,
        "--server", region,
        "--output", str(output_path),
        "--log_level", "ERROR",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    _sessions[session_id] = {
        "proc": proc,
        "output_path": output_path,
        "mac": mac,
        "auto_responded": False,
    }
    return await _drive(session_id)


async def solve_captcha(session_id: str, solution: str) -> dict:
    """Submit captcha solution and continue login. Returns {token, did}."""
    session = _sessions.get(session_id)
    if not session:
        raise ValueError("Session not found or expired")
    proc: asyncio.subprocess.Process = session["proc"]
    proc.stdin.write((solution.strip() + "\n").encode())
    await proc.stdin.drain()
    return await _drive(session_id)


async def fetch_captcha_image(session_id: str) -> bytes:
    """Fetch captcha image bytes from the extractor's local HTTP server."""
    import requests
    try:
        loop = asyncio.get_event_loop()
        r = await loop.run_in_executor(None, lambda: requests.get("http://127.0.0.1:31415", timeout=5))
        return r.content
    except Exception as e:
        raise RuntimeError(f"Could not fetch captcha image: {e}") from e


async def _drive(session_id: str) -> dict:
    """Read subprocess stdout, auto-respond to prompts, pause when captcha input needed."""
    session = _sessions[session_id]
    proc: asyncio.subprocess.Process = session["proc"]
    output_path: Path = session["output_path"]
    mac: str = session["mac"]

    buf = ""
    captcha_url: str | None = None

    while True:
        try:
            chunk = await asyncio.wait_for(proc.stdout.read(512), timeout=30.0)
        except asyncio.TimeoutError:
            _cleanup(session_id)
            raise RuntimeError("Extractor timed out")

        if chunk:
            text = _strip_ansi(chunk.decode(errors="replace"))
            buf += text
            logger.debug("miio stdout: %r", text)

        # Auto-respond to login method selection
        if not session["auto_responded"] and "p/q:" in buf:
            proc.stdin.write(b"p\n")
            await proc.stdin.drain()
            session["auto_responded"] = True

        # Track captcha image URL (served at :31415 by the extractor)
        if "31415" in buf and captcha_url is None:
            captcha_url = "http://127.0.0.1:31415"

        # Pause here — subprocess is now blocked on input() for captcha solution
        if "Enter captcha" in buf:
            logger.info("miio-cloud: captcha required for %s", mac)
            return {"session_id": session_id, "challenge": "captcha",
                    "captcha_url": captcha_url or "http://127.0.0.1:31415"}

        # Pause here — subprocess is blocked on input() for 2FA code
        if "2FA Code:" in buf:
            logger.info("miio-cloud: 2FA required for %s", mac)
            return {"session_id": session_id, "challenge": "2fa"}

        # Output file is already written before this prompt — parse immediately
        if "Press ENTER" in buf:
            proc.stdin.write(b"\n")
            await proc.stdin.drain()
            if "Invalid captcha" in buf:
                _cleanup(session_id)
                raise RuntimeError("Invalid captcha — please try again")
            if "Invalid login or password" in buf:
                _cleanup(session_id)
                raise RuntimeError("Invalid login or password")
            if "Unable to log in" in buf:
                _cleanup(session_id)
                raise RuntimeError("Login failed — check credentials")
            break

        if not chunk:
            break  # EOF

    await proc.wait()
    return _parse_result(session_id, mac)


def _parse_result(session_id: str, mac: str) -> dict:
    session = _sessions.get(session_id, {})
    output_path: Path = session.get("output_path", Path("/nonexistent"))
    try:
        if not output_path.exists() or output_path.stat().st_size == 0:
            raise RuntimeError("Login failed — check credentials or try again")

        data: list[dict] = json.loads(output_path.read_text())
        target = mac.upper().replace("-", ":")
        for server_data in data:
            for home in server_data.get("homes", []):
                for device in home.get("devices", []):
                    device_mac = device.get("mac", "").upper().replace("-", ":")
                    if device_mac == target:
                        token = device.get("token")
                        did = device.get("did")
                        if token and did:
                            return {"token": token, "did": str(did)}
        raise ValueError(f"Device {mac} not found in cloud account")
    finally:
        _cleanup(session_id)


def _cleanup(session_id: str) -> None:
    session = _sessions.pop(session_id, None)
    if session:
        output_path: Path = session["output_path"]
        output_path.unlink(missing_ok=True)
        proc: asyncio.subprocess.Process = session["proc"]
        if proc.returncode is None:
            proc.kill()

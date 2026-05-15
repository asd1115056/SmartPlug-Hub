"""Connect and control a Kasa device by IP address."""

import asyncio
import sys
from pathlib import Path

from kasa import Device, Discover

sys.path.insert(0, str(Path(__file__).parent))
from utils import control_device, load_credentials, print_device_info


async def connect_device(host: str) -> Device | None:
    credentials = load_credentials()
    print(f"Connecting to {host}...")
    try:
        device = await Discover.discover_single(host, credentials=credentials)
        await device.update()
        return device
    except Exception as e:
        print(f"Failed to connect: {type(e).__name__}: {e}")
        return None


async def main(host: str, action: str | None = None, child_index: int | None = None) -> None:
    device = await connect_device(host)
    if not device:
        return
    try:
        print_device_info(device)
        if action:
            await control_device(device, action, child_index)
            print_device_info(device)
    finally:
        await device.disconnect()


def print_usage() -> None:
    print("Usage: python tests/kasa/test_device.py <host> [action] [child_index]")
    print()
    print("Arguments:")
    print("  host         Device IP address (required)")
    print("  action       on, off, toggle (optional)")
    print("  child_index  Outlet index for strips (optional, 0-based)")
    print()
    print("Examples:")
    print("  python tests/kasa/test_device.py 192.168.1.100")
    print("  python tests/kasa/test_device.py 192.168.1.100 on")
    print("  python tests/kasa/test_device.py 192.168.1.100 on 0")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    host = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else None
    child_index = int(sys.argv[3]) if len(sys.argv) > 3 else None
    asyncio.run(main(host, action, child_index))

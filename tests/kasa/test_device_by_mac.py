"""Find and control a Kasa device by MAC address."""

import asyncio
import sys
from pathlib import Path

from kasa import Device, Discover

sys.path.insert(0, str(Path(__file__).parent))
from utils import control_device, load_credentials, normalize_mac, print_device_info


async def find_device_by_mac(target_mac: str) -> Device | None:
    credentials = load_credentials()
    target_mac = normalize_mac(target_mac)
    print(f"Searching for device with MAC: {target_mac}")
    print("Discovering devices...\n")

    found_device = None

    async def on_device_discovered(device) -> None:
        nonlocal found_device
        device_mac = getattr(device, "mac", None)
        if device_mac and normalize_mac(device_mac) == target_mac:
            found_device = device
            print(f"Found! IP: {device.host}")

    await Discover.discover(on_discovered=on_device_discovered, credentials=credentials)
    return found_device


async def main(mac: str, action: str | None = None, child_index: int | None = None) -> None:
    device = await find_device_by_mac(mac)
    if not device:
        print(f"\nDevice with MAC {normalize_mac(mac)} not found.")
        return
    try:
        await device.update()
        print_device_info(device)
        if action:
            await control_device(device, action, child_index)
            print_device_info(device)
    finally:
        await device.disconnect()


def print_usage() -> None:
    print("Usage: python tests/kasa/test_device_by_mac.py <mac> [action] [child_index]")
    print()
    print("Arguments:")
    print("  mac          Device MAC address (required)")
    print("               Formats: AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, AABBCCDDEEFF")
    print("  action       on, off, toggle (optional)")
    print("  child_index  Outlet index for strips (optional, 0-based)")
    print()
    print("Examples:")
    print("  python tests/kasa/test_device_by_mac.py AA:BB:CC:DD:EE:FF")
    print("  python tests/kasa/test_device_by_mac.py AA-BB-CC-DD-EE-FF on")
    print("  python tests/kasa/test_device_by_mac.py AA:BB:CC:DD:EE:FF on 0")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print_usage()
        sys.exit(1)
    mac = sys.argv[1]
    action = sys.argv[2] if len(sys.argv) > 2 else None
    child_index = int(sys.argv[3]) if len(sys.argv) > 3 else None
    asyncio.run(main(mac, action, child_index))

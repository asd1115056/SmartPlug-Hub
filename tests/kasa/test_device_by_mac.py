"""Find and control a Kasa device by MAC address."""

import asyncio
import sys
from pathlib import Path

from kasa import Device, Discover

sys.path.insert(0, str(Path(__file__).parent))
from utils import control_device, load_credentials, normalize_mac, print_device_info


async def find_device_by_mac(target_mac: str, broadcast: str | None = None) -> Device | None:
    credentials = load_credentials()
    target_mac = normalize_mac(target_mac)
    print(f"Searching for device with MAC: {target_mac}")
    if broadcast:
        print(f"Broadcast target: {broadcast}")
    print("Discovering devices...\n")

    found_device = None

    async def on_device_discovered(device) -> None:
        nonlocal found_device
        device_mac = getattr(device, "mac", None)
        if device_mac and normalize_mac(device_mac) == target_mac:
            found_device = device
            print(f"Found! IP: {device.host}")

    discover_kwargs = {'on_discovered': on_device_discovered, 'credentials': credentials}
    if broadcast:
        discover_kwargs['target'] = broadcast
    await Discover.discover(**discover_kwargs)
    return found_device


async def main(mac: str, action: str | None = None, child_index: int | None = None, broadcast: str | None = None) -> None:
    device = await find_device_by_mac(mac, broadcast)
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
    _args = sys.argv[1:]
    _positional = [a for a in _args if not a.startswith('--')]
    if not _positional:
        print_usage()
        sys.exit(1)
    mac = _positional[0]
    action = _positional[1] if len(_positional) > 1 else None
    child_index = int(_positional[2]) if len(_positional) > 2 else None
    broadcast = None
    if '--broadcast' in _args:
        _idx = _args.index('--broadcast')
        if _idx + 1 < len(_args):
            broadcast = _args[_idx + 1]
    asyncio.run(main(mac, action, child_index, broadcast))

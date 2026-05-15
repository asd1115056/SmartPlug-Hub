"""Discover all Kasa devices on the local network."""

import asyncio
import sys
from pathlib import Path
from pprint import pprint

from kasa import Discover

sys.path.insert(0, str(Path(__file__).parent))
from utils import load_credentials


async def discover_devices(raw: bool = False) -> None:
    credentials = load_credentials()
    print("Using credentials from config/.env" if credentials else "No credentials found, discovering without")
    print("Discovering devices...\n")

    device_count = 0

    async def on_device_discovered(device) -> None:
        nonlocal device_count
        device_count += 1
        if raw:
            print(f"\n[{device.host}]")
            print("-" * 40)
            print("Device attributes:")
            pprint(vars(device))
            if hasattr(device, "_discovery_info"):
                print("\nDiscovery info:")
                pprint(device._discovery_info)
            print("=" * 60)
        else:
            try:
                await device.update()
                print(f"  IP: {device.host}")
                print(f"  MAC: {device.mac}")
                print(f"  Model: {device.model}")
                print(f"  Alias: {device.alias}")
            except Exception as e:
                print(f"  IP: {device.host}")
                print(f"  MAC: {getattr(device, 'mac', 'Unknown')}")
                print(f"  Model: {getattr(device, 'model', 'Unknown')}")
                print(f"  Error: {type(e).__name__}: {e}")
            print()

    if raw:
        print("=" * 60)

    found_devices = await Discover.discover(on_discovered=on_device_discovered, credentials=credentials)
    print(f"\nDiscovery complete. Found {device_count} device(s).")
    for device in found_devices.values():
        await device.disconnect()


if __name__ == "__main__":
    raw_mode = len(sys.argv) > 1 and sys.argv[1] == "--raw"
    asyncio.run(discover_devices(raw=raw_mode))

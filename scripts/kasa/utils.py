"""Shared helpers for Kasa integration scripts."""

import os
from pathlib import Path

from dotenv import load_dotenv
from kasa import Credentials, Device

_ENV_PATH = Path(__file__).parent.parent.parent / "config" / ".env"


def load_credentials() -> Credentials | None:
    if not _ENV_PATH.exists():
        return None
    load_dotenv(_ENV_PATH)
    username = os.getenv("KASA_USERNAME")
    password = os.getenv("KASA_PASSWORD")
    if not username or not password:
        return None
    return Credentials(username=username, password=password)


def normalize_mac(mac: str) -> str:
    clean = mac.upper().replace("-", "").replace(":", "").replace(".", "")
    return ":".join(clean[i:i + 2] for i in range(0, 12, 2))


def print_device_info(device: Device) -> None:
    print("\n=== Device Info ===")
    print(f"  Alias: {device.alias}")
    print(f"  Model: {device.model}")
    print(f"  Host: {device.host}")
    print(f"  MAC: {device.mac}")
    print(f"  Is On: {device.is_on}")
    if hasattr(device, "rssi") and device.rssi:
        print(f"  RSSI: {device.rssi}")
    if hasattr(device, "children") and device.children:
        print(f"\n=== Children ({len(device.children)} outlets) ===")
        for i, child in enumerate(device.children):
            print(f"  [{i}] {child.alias}: {'ON' if child.is_on else 'OFF'}")


async def control_device(device: Device, action: str, child_index: int | None = None) -> None:
    target = device
    target_name = device.alias
    if child_index is not None:
        if not hasattr(device, "children") or not device.children:
            print("Error: Device has no children (not a strip)")
            return
        if child_index < 0 or child_index >= len(device.children):
            print(f"Error: Invalid child index. Valid range: 0-{len(device.children) - 1}")
            return
        target = device.children[child_index]
        target_name = target.alias
    print(f"\nExecuting '{action}' on {target_name}...")
    if action == "on":
        await target.turn_on()
    elif action == "off":
        await target.turn_off()
    elif action == "toggle":
        if target.is_on:
            await target.turn_off()
        else:
            await target.turn_on()
    else:
        print(f"Unknown action: {action}")
        return
    await device.update()
    print(f"Done. {target_name} is now {'ON' if target.is_on else 'OFF'}")

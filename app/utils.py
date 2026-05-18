"""Shared utility functions."""

import hashlib


def normalize_mac(mac: str) -> str:
    """Normalize MAC to uppercase hex with no separators: 'AA:BB:CC' → 'AABBCC'."""
    return mac.replace(":", "").replace("-", "").upper()


def mac_to_id(mac: str) -> str:
    """Derive a stable 8-char device ID from a MAC address."""
    return hashlib.sha256(normalize_mac(mac).encode()).hexdigest()[:8]

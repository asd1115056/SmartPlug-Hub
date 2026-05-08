"""General-purpose utility functions."""

import hashlib


def normalize_mac(mac: str) -> str:
    """Normalize MAC address to uppercase with colons (AA:BB:CC:DD:EE:FF)."""
    clean = mac.upper().replace("-", "").replace(":", "").replace(".", "")
    if len(clean) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    return ":".join(clean[i : i + 2] for i in range(0, 12, 2))


def mac_to_id(mac: str) -> str:
    """Generate a stable 8-char device ID from MAC address (SHA-256)."""
    normalized = normalize_mac(mac)
    return hashlib.sha256(normalized.encode()).hexdigest()[:8]

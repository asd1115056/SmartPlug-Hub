"""
General-purpose utility functions.
"""


def normalize_mac(mac: str) -> str:
    """Normalize MAC address to uppercase with colons (AA:BB:CC:DD:EE:FF)."""
    clean = mac.upper().replace("-", "").replace(":", "").replace(".", "")
    if len(clean) != 12:
        raise ValueError(f"Invalid MAC address: {mac}")
    return ":".join(clean[i : i + 2] for i in range(0, 12, 2))


def mac_to_id(mac: str) -> str:
    """Generate a stable device ID from MAC address (8-char SHA-256 hash)."""
    import hashlib
    normalized = normalize_mac(mac)
    return hashlib.sha256(normalized.encode()).hexdigest()[:8]

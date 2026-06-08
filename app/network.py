"""Network utilities — interface enumeration and ARP-based MAC resolution."""

import re
import socket
import subprocess
import time


def get_broadcast_addresses() -> list[str]:
    """Return directed broadcast address for every active non-loopback IPv4 interface."""
    result = []
    try:
        out = subprocess.check_output(
            ["ip", "-o", "-4", "addr", "show"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except (subprocess.SubprocessError, FileNotFoundError):
        return result

    for line in out.splitlines():
        m = re.search(r"inet\s+(\S+)\s+brd\s+(\S+)", line)
        if not m:
            continue
        ip_str = m.group(1).split("/")[0]
        broadcast = m.group(2)
        # skip loopback (127.x) and link-local (169.254.x)
        if ip_str.startswith("127.") or ip_str.startswith("169.254."):
            continue
        result.append(broadcast)
    return result


def mac_from_ip(ip: str) -> str | None:
    """Return MAC for ip: send a UDP nudge to force kernel ARP, then read /proc/net/arp."""
    _udp_nudge(ip)
    time.sleep(0.05)
    return _read_arp(ip)


# ── Internal helpers ──────────────────────────────────────────────────────────

def _udp_nudge(ip: str) -> None:
    """Send a zero-byte UDP to ip:1 (discard port) to trigger kernel ARP resolution."""
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.settimeout(0.1)
        try:
            s.sendto(b"", (ip, 1))
        except OSError:
            pass


def _read_arp(ip: str) -> str | None:
    """Look up ip in /proc/net/arp; return normalized MAC (uppercase, no separators) or None."""
    try:
        with open("/proc/net/arp") as f:
            next(f)  # skip header
            for line in f:
                parts = line.split()
                if len(parts) < 4 or parts[0] != ip:
                    continue
                if parts[2] == "0x0":  # incomplete entry
                    continue
                mac = parts[3].replace(":", "").upper()
                if mac and mac != "000000000000":
                    return mac
    except OSError:
        pass
    return None

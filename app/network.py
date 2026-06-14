"""Network utilities — interface enumeration and ARP-based MAC resolution."""

import fcntl
import socket
import time

_SIOCGIFADDR    = 0x8915
_SIOCGIFBRDADDR = 0x8919
_IFREQ_SIZE     = 40   # sizeof(struct ifreq) on Linux x86_64
_IFNAMSIZ       = 16


def get_interface_pairs() -> list[tuple[str, str]]:
    """Return (local_ip, broadcast) for every active non-loopback IPv4 interface."""
    result = []
    try:
        names = [name for _, name in socket.if_nameindex()]
    except OSError:
        return result
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            for name in names:
                req = name.encode()[:_IFNAMSIZ - 1].ljust(_IFREQ_SIZE, b'\x00')
                try:
                    ip = socket.inet_ntoa(fcntl.ioctl(sock, _SIOCGIFADDR, req)[20:24])
                except OSError:
                    continue
                if ip.startswith('127.') or ip.startswith('169.254.'):
                    continue
                try:
                    brd = socket.inet_ntoa(fcntl.ioctl(sock, _SIOCGIFBRDADDR, req)[20:24])
                except OSError:
                    continue
                result.append((ip, brd))
    except OSError:
        pass
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

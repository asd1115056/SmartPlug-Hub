"""UDP broadcast discovery for MiIO devices — no python-miio required.

Sends the standard MiIO hello packet and prints all responding devices
with their IP and DID. Use this to find your device's miio_id before
adding it to devices.json.

Usage:
    python tests/miio/test_discover.py <broadcast> [timeout]

Arguments:
    broadcast   Broadcast address (e.g. 192.168.1.255)
    timeout     Seconds to wait for responses (default: 3)

Example:
    python tests/miio/test_discover.py 192.168.1.255
    python tests/miio/test_discover.py 192.168.1.255 5
"""

import socket
import struct
import sys
import time

_MIIO_PORT = 54321
_HELLO = bytes.fromhex('21310020' + 'ff' * 28)


def discover(broadcast: str, timeout: float = 3.0) -> list[dict]:
    """Send hello broadcast; return list of {ip, did} for all responders."""
    found: list[dict] = []
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(timeout)
        sock.sendto(_HELLO, (broadcast, _MIIO_PORT))
        print(f"Sent hello to {broadcast}:{_MIIO_PORT}, waiting {timeout}s...\n")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                data, addr = sock.recvfrom(1024)
                if len(data) >= 12:
                    did = str(struct.unpack('>I', data[8:12])[0])
                    found.append({"ip": addr[0], "did": did})
            except socket.timeout:
                break
    finally:
        sock.close()
    return found


def main(broadcast: str, timeout: float = 3.0) -> None:
    results = discover(broadcast, timeout)

    if not results:
        print("No MiIO devices found.")
        print("Check that the broadcast address is correct and devices are on the same network.")
        return

    print(f"Found {len(results)} device(s):\n")
    print(f"  {'IP':<18} {'DID (miio_id)'}")
    print(f"  {'-'*17} {'-'*20}")
    for r in results:
        print(f"  {r['ip']:<18} {r['did']}")
    print()
    print("Add the DID as 'miio_id' in your devices.json.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    broadcast_addr = sys.argv[1]
    wait = float(sys.argv[2]) if len(sys.argv) > 2 else 3.0
    main(broadcast_addr, wait)

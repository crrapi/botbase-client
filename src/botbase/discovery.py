"""Find consoles running sys-botbase on a local network."""
from __future__ import annotations

import ipaddress
import re
import socket
from concurrent.futures import ThreadPoolExecutor
from typing import List, Optional, Tuple

from .client import _bind_to_interface
from .constants import DEFAULT_PORT

_VERSION = re.compile(rb"^\d+(\.\d+)*\r?\n")


def local_ipv4(interface: Optional[str] = None) -> str:
    """The local IPv4 address used to reach the LAN (on `interface` if given). No packet is sent."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        if interface:
            _bind_to_interface(s, interface)
        s.connect(("192.0.2.1", 9))  # TEST-NET-1: only selects a route
        return s.getsockname()[0]
    finally:
        s.close()


def default_subnet(interface: Optional[str] = None) -> str:
    """The /24 around the local address, e.g. 192.168.1.0/24."""
    return str(ipaddress.ip_network(f"{local_ipv4(interface)}/24", strict=False))


def probe(host: str, port: int = DEFAULT_PORT, interface: Optional[str] = None,
          timeout: float = 0.6) -> Optional[str]:
    """Return the sys-botbase version at host:port, or None. Port 6000 is also X11's, so a
    host only counts when it answers getVersion with a version number."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        if interface:
            _bind_to_interface(s, interface)
        s.settimeout(timeout)
        s.connect((host, port))
        s.sendall(b"getVersion\r\n")
        s.settimeout(max(timeout, 1.5))  # a reply takes one 50 ms main-loop tick
        data = b""
        while b"\n" not in data and len(data) < 64:
            chunk = s.recv(64)
            if not chunk:
                break
            data += chunk
        return data.split(b"\n")[0].decode().strip() if _VERSION.match(data) else None
    except OSError:
        return None
    finally:
        s.close()


def discover(subnet: Optional[str] = None, port: int = DEFAULT_PORT, interface: Optional[str] = None,
             timeout: float = 0.6, workers: int = 64) -> List[Tuple[str, str]]:
    """Scan a subnet; return [(host, version)] for every sys-botbase that answers."""
    net = ipaddress.ip_network(subnet or default_subnet(interface), strict=False)
    if net.num_addresses > 4096:
        raise ValueError(f"{net} is too large to scan; use a /20 or smaller")
    hosts = [str(h) for h in net.hosts()]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        found = pool.map(lambda h: (h, probe(h, port, interface, timeout)), hosts)
        return [(h, v) for h, v in found if v]

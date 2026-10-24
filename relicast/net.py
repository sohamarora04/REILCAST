"""Socket helpers: multicast join/send, interface discovery, cross-platform quirks."""
import os
import socket
import time

from . import proto

DEFAULT_GROUP = "239.255.42.99"  # administratively-scoped (RFC 2365) multicast range


def enable_ansi():
    """Turn on ANSI escape handling on Windows 10+ terminals (no-op elsewhere)."""
    if os.name == "nt":
        os.system("")


def primary_ip():
    """Address of the interface the OS would use for outbound traffic (no packet is sent)."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def set_rcvbuf(sock, size=4 << 20):
    for sz in (size, size // 2, size // 4, 256 << 10):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, sz)
            return
        except OSError:
            continue


def mcast_recv_socket(group, port, iface):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):  # macOS / Linux; absent on Windows (REUSEADDR suffices there)
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    s.bind(("", port))  # wildcard bind: binding to the group address is not portable (fails on Windows)
    mreq = socket.inet_aton(group) + socket.inet_aton(iface)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_ADD_MEMBERSHIP, mreq)  # i.e. mcast_join()
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    set_rcvbuf(s)
    return s


def mcast_send_socket(iface, ttl=1):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, ttl)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_LOOP, 1)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_IF, socket.inet_aton(iface))
    return s


def udp_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("", 0))
    set_rcvbuf(s)
    return s


def probe_interface(iface, group=DEFAULT_GROUP, port=50999, timeout=0.6):
    """True if a multicast datagram sent via `iface` is received back by a member of the group."""
    rx = tx = None
    try:
        rx = mcast_recv_socket(group, port, iface)
        tx = mcast_send_socket(iface, 1)
        rx.settimeout(timeout)
        end = time.time() + timeout
        tx.sendto(proto.pack(proto.PROBE, 0, 0, 0, 0, b"ping"), (group, port))
        while time.time() < end:
            data, _ = rx.recvfrom(2048)
            p = proto.unpack(data)
            if p and p[0] == proto.PROBE:
                return True
    except OSError:
        return False
    finally:
        for s in (rx, tx):
            if s:
                s.close()
    return False


def pick_interface(preferred=None):
    """First interface on which multicast demonstrably works (LAN address first, then loopback)."""
    cands = [preferred] if preferred else []
    ip = primary_ip()
    if ip and ip not in cands:
        cands.append(ip)
    if "127.0.0.1" not in cands:
        cands.append("127.0.0.1")
    for c in cands:
        if probe_interface(c):
            return c
    return None

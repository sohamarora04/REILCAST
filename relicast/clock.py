"""High-resolution clock with injectable skew + a minimal SNTP (RFC 4330) client and server."""
import socket
import struct
import threading
import time

NTP_EPOCH = 2208988800  # seconds between 1900-01-01 and 1970-01-01

# Anchor wall-clock to perf_counter: Windows' time.time() can have ~15 ms granularity,
# perf_counter does not, so one-way delays stay meaningful on every OS.
_T0 = time.time()
_P0 = time.perf_counter()


def true_time():
    return _T0 + (time.perf_counter() - _P0)


class Clock:
    """A node's local clock. `skew` simulates a mis-set hardware clock; SNTP sets `correction`."""

    def __init__(self, skew=0.0):
        self.skew = skew
        self.correction = 0.0

    def raw(self):
        return true_time() + self.skew

    def now(self):
        return self.raw() + self.correction


def _to_ntp(t):
    t += NTP_EPOCH
    sec = int(t)
    return sec, int((t - sec) * (1 << 32))


def _from_ntp(sec, frac):
    return sec - NTP_EPOCH + frac / float(1 << 32)


class SntpServer(threading.Thread):
    """Tiny SNTP server answering with the (true) time of this process."""

    def __init__(self, host="", port=0):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind((host, port))
        self.sock.settimeout(0.3)
        self.port = self.sock.getsockname()[1]
        self._halt = threading.Event()
        self.served = 0

    def run(self):
        while not self._halt.is_set():
            try:
                data, addr = self.sock.recvfrom(512)
            except socket.timeout:
                continue
            except OSError:
                return
            t2 = true_time()
            if len(data) < 48:
                continue
            resp = bytearray(48)
            resp[0] = (0 << 6) | (4 << 3) | 4  # LI=0, VN=4, Mode=4 (server)
            resp[1] = 2  # stratum 2
            resp[24:32] = data[40:48]  # originate = client's transmit
            resp[16:24] = struct.pack("!II", *_to_ntp(t2))  # reference
            resp[32:40] = struct.pack("!II", *_to_ntp(t2))  # receive
            resp[40:48] = struct.pack("!II", *_to_ntp(true_time()))  # transmit
            self.sock.sendto(bytes(resp), addr)
            self.served += 1

    def stop(self):
        self._halt.set()
        try:
            self.sock.close()
        except OSError:
            pass


def sntp_query(server, clock, timeout=1.0):
    """One SNTP exchange. Returns (offset, delay) in seconds, as seen by `clock`'s raw time."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        req = bytearray(48)
        req[0] = (0 << 6) | (4 << 3) | 3  # LI=0, VN=4, Mode=3 (client)
        t1 = clock.raw()
        req[40:48] = struct.pack("!II", *_to_ntp(t1))
        s.sendto(bytes(req), server)
        data, _ = s.recvfrom(512)
        t4 = clock.raw()
    finally:
        s.close()
    if len(data) < 48:
        raise ValueError("short SNTP reply")
    t2 = _from_ntp(*struct.unpack("!II", data[32:40]))
    t3 = _from_ntp(*struct.unpack("!II", data[40:48]))
    offset = ((t2 - t1) + (t3 - t4)) / 2.0
    delay = (t4 - t1) - (t3 - t2)
    return offset, delay


def sntp_sync(server, clock, samples=5):
    """Take several samples, keep the min-delay one (RFC 4330 clock filter idea). Returns info dict."""
    best = None
    for _ in range(samples):
        try:
            off, dly = sntp_query(server, clock)
        except (OSError, ValueError):
            continue
        if best is None or dly < best[1]:
            best = (off, dly)
        time.sleep(0.01)
    if best is None:
        return {"ok": False, "offset": 0.0, "delay": 0.0}
    clock.correction = best[0]
    return {"ok": True, "offset": best[0], "delay": best[1]}

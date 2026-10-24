"""Receiver process: joins the session over TCP, syncs its clock via SNTP, receives data
(multicast / unicast UDP / TCP depending on mode), repairs losses with NACKs, reports stats."""
import hashlib
import json
import os
import random
import select
import socket
import struct
import time

from . import clock as clk
from . import net, proto

RTO = 0.04  # base retry timeout for a lost request (seconds)


class _Lines:
    """Newline-delimited JSON reader over a blocking socket."""

    def __init__(self, sock):
        self.sock, self.buf = sock, b""

    def pop(self):
        """Next complete buffered line (parsed) or None - never touches the socket."""
        if b"\n" not in self.buf:
            return None
        line, self.buf = self.buf.split(b"\n", 1)
        return json.loads(line.decode())

    def fill(self):
        d = self.sock.recv(65536)
        if not d:
            raise EOFError
        self.buf += d

    def read(self):
        while b"\n" not in self.buf:
            self.fill()
        return self.pop()


def _send(ctl, obj):
    ctl.sendall((json.dumps(obj) + "\n").encode())


class Receiver:
    def __init__(self, host, ctl_port, rid, loss=0.0, seed=1, skew_ms=0.0, iface="127.0.0.1", ntp=None, out_dir=None):
        self.out_dir = out_dir
        self.host, self.ctl_port, self.rid = host, ctl_port, rid
        self.rng = random.Random(seed * 1000 + rid)
        self.loss = loss
        self.clock = clk.Clock(skew_ms / 1000.0)
        self.iface = iface
        self.ntp = ntp  # optional (host, port) of an external SNTP server
        self.skew_ms = skew_ms
        # statistics
        self.recv = self.dups = self.nacks = self.suppressed = self.nack_bytes = 0
        self.round_due = 0.0
        self.owd, self.raw, self.jitter, self._prev, self.owd_ewma = [], [], 0.0, None, 0.0

    # ---- helpers ---------------------------------------------------------------
    def _drop(self):
        return self.loss > 0 and self.rng.random() < self.loss

    def _window(self):
        return min(0.1, max(0.01, 0.01 + 3 * (self.owd_ewma + 4 * self.jitter)))

    def _delay(self, attempt):
        if self.mode == "naive":
            return 0.0 if attempt == 0 else 0.08
        w = self._window()
        if attempt == 0:
            return self.rng.uniform(0, w)
        return RTO * (2 ** min(attempt - 1, 2)) + self.rng.uniform(0, w)

    def _note_data(self, ts_us):
        now, rawnow = self.clock.now(), self.clock.raw()
        o = now - ts_us / 1e6
        if self._prev is not None:
            self.jitter += (abs(o - self._prev) - self.jitter) / 16.0  # RFC 3550 estimator
        self._prev = o
        self.owd_ewma = o if not self.owd else self.owd_ewma + 0.125 * (o - self.owd_ewma)
        if len(self.owd) < 20000:
            self.owd.append(o)
            self.raw.append(rawnow - ts_us / 1e6)

    def _store(self, seq, payload):
        if seq >= self.chunks:
            return False
        if self.data[seq] is not None:
            self.dups += 1
            return False
        self.data[seq] = payload
        self.got += 1
        self.bm[seq >> 3] |= 1 << (seq & 7)
        self.missing.pop(seq, None)
        return True

    def _progress(self):
        _send(self.ctl, {"progress": True, "rid": self.rid, "have": self.got, "bitmap": self.bm.hex(),
                         "nacks": self.nacks, "suppressed": self.suppressed})

    # ---- main --------------------------------------------------------------------
    def run(self):
        self.ctl = socket.create_connection((self.host, self.ctl_port), timeout=15)
        self.ctl.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.lines = _Lines(self.ctl)
        meta = self.lines.read()
        self.meta, self.mode = meta, meta["mode"]
        if self.rid <= 0:
            self.rid = meta["rid"]
            self.rng = random.Random(self.rid * 7919)
        self.session, self.chunks = meta["session"], meta["chunks"]
        self.data = [None] * self.chunks
        self.got = 0
        self.bm = bytearray((self.chunks + 7) // 8)
        self.missing = {}  # seq -> [due, attempts]
        self.highest = -1
        self.t_start = None
        self.transport = None
        self.aborted = False
        self.sock = self.txsock = None
        self.info_sntp = clk.sntp_sync(self.ntp or (self.host, meta["sntp_port"]), self.clock)
        self.sntp = self.info_sntp
        mcast_possible = False
        if self.mode in ("naive", "relicast") and not os.environ.get("RELICAST_NO_MCAST"):  # env: test hotspot-blocked multicast
            try:
                self.sock = net.mcast_recv_socket(meta["group"], meta["port"], self.iface)
                self.txsock = net.mcast_send_socket(self.iface, meta.get("ttl", 1))
                self.nack_dest = (meta["group"], meta["port"])
                mcast_possible = True
            except OSError:
                self.sock = self.txsock = None
        elif self.mode == "udp":
            self.sock = net.udp_socket()
        _send(self.ctl, {"ready": True, "rid": self.rid,
                         "udp_port": self.sock.getsockname()[1] if self.mode == "udp" else 0,
                         "mcast_possible": mcast_possible, "sntp_offset": self.sntp["offset"],
                         "skew_ms": self.skew_ms})
        try:
            self._wait_start()
            if self.aborted:
                return
            self.deadline = time.time() + self.meta["timeout"]
            self.t_start = time.time()
            if self.transport == "tcp":
                self._run_tcp()
            else:
                self._run_udp(self.transport == "mcast")
        finally:
            self._report()

    def _wait_start(self):
        """Lobby phase: answer multicast probes until the sender says start (or abort)."""
        probe_until, probes = 0.0, 0
        mc = self.sock if self.mode in ("naive", "relicast") else None
        if mc:
            mc.setblocking(False)
        while True:
            socks = [self.ctl] + ([mc] if mc else [])
            r, _, _ = select.select(socks, [], [], 0.0 if b"\n" in self.lines.buf else 0.1)
            if mc in r:
                for _ in range(64):
                    try:
                        buf, _a = mc.recvfrom(4096)
                    except OSError:
                        break
                    p = proto.unpack(buf)
                    if p and p[0] == proto.PROBE and p[1] == self.session:
                        probes += 1
            cmd = None
            try:
                cmd = self.lines.pop()
                if cmd is None and self.ctl in r:
                    self.lines.fill()
                    cmd = self.lines.pop()
            except (EOFError, OSError, ValueError):
                self.aborted = True
                return
            if cmd is not None:
                if cmd.get("cmd") == "probe":
                    probe_until, probes = time.time() + 1.6, 0
                elif cmd.get("cmd") == "start":
                    self.transport = cmd["transport"]
                    return
                elif cmd.get("cmd") == "abort":
                    self.aborted = True
                    return
            if probe_until and time.time() >= probe_until:
                probe_until = 0.0
                _send(self.ctl, {"mcast_ok": probes > 0, "rid": self.rid, "probes": probes})

    def _ctl_closed_nb(self):
        self.ctl.setblocking(False)
        try:
            return self._ctl_closed()
        finally:
            self.ctl.setblocking(True)

    def _ctl_closed(self):
        """True if the sender hung up or told us to abort (checked while transferring)."""
        try:
            d = self.ctl.recv(4096, socket.MSG_PEEK)
        except (BlockingIOError, InterruptedError):
            return False
        except OSError:
            return True
        return (not d) or b'"abort"' in d

    def _run_tcp(self):
        s = self.ctl
        buf = self.lines.buf
        self.lines.buf = b""
        last = 0.0
        while self.got < self.chunks and time.time() < self.deadline:
            r, _, _ = select.select([s], [], [], 0.05)
            if r:
                d = s.recv(262144)
                if not d:
                    break
                buf += d
            while len(buf) >= 2:
                (n,) = struct.unpack_from("!H", buf)
                if len(buf) < 2 + n:
                    break
                pkt, buf = buf[2:2 + n], buf[2 + n:]
                p = proto.unpack(pkt)
                if p and p[0] in (proto.DATA, proto.REPAIR) and p[1] == self.session:
                    self.recv += 1
                    if self._store(p[2], p[5]) and p[0] == proto.DATA:
                        self._note_data(p[4])
            if time.time() - last > 0.1:
                last = time.time()
                self._progress()

    def _run_udp(self, multicast):
        sock = self.sock
        sock.setblocking(False)
        last = 0.0
        naive = self.mode == "naive"
        nack_mode = multicast
        while time.time() < self.deadline:
            now = time.time()
            if nack_mode and self.missing:
                self._fire_timers(now)
            if self.got >= self.chunks:
                break
            wait = 0.02
            if nack_mode and self.missing:
                wait = max(0.0005, min(wait, min(v[0] for v in self.missing.values()) - now))
            r, _, _ = select.select([sock], [], [], wait)
            fin = False
            if r:
                for _ in range(256):  # drain burst
                    try:
                        buf, _addr = sock.recvfrom(4096)
                    except (BlockingIOError, InterruptedError):
                        break
                    except OSError:
                        break
                    p = proto.unpack(buf)
                    if not p or p[1] != self.session:
                        continue
                    t, _s, seq, total, ts_us, payload = p
                    if t == proto.FIN:
                        fin = True
                    elif t in (proto.DATA, proto.REPAIR):
                        if self._drop():
                            continue
                        self.recv += 1
                        new = self._store(seq, payload)
                        if t == proto.DATA:
                            if new:
                                self._note_data(ts_us)
                            if nack_mode and seq > self.highest:
                                self._gap(seq - 1)
                                self.highest = seq
                    elif t == proto.HEARTBEAT and nack_mode:
                        if seq > self.highest:
                            self._gap(seq)
                            self.highest = seq
                    elif t == proto.NACK and nack_mode and not naive:
                        if not self._drop():
                            self._overheard(payload)
            if fin:
                break
            if time.time() - last > 0.1:
                last = time.time()
                self._progress()
                if self._ctl_closed_nb():
                    break

    def _gap(self, upto):
        now = time.time()
        if self.mode == "relicast":
            # gaps detected within one window share a request round -> one batched NACK per round
            if self.round_due < now:
                self.round_due = now + self.rng.uniform(0, self._window())
            due = self.round_due
        for q in range(self.highest + 1, upto + 1):
            if self.data[q] is None and q not in self.missing:
                self.missing[q] = [due if self.mode == "relicast" else now + self._delay(0), 0]

    def _fire_timers(self, now):
        due = [q for q, v in self.missing.items() if v[0] <= now]
        if not due:
            return
        ranges = proto.to_ranges(due)[:proto.MAX_RANGES]
        sent = set()
        for a, b in ranges:
            sent.update(range(a, b + 1))
        body = proto.pack_nack(self.rid, ranges)
        pkt = proto.pack(proto.NACK, self.session, 0, self.chunks, int(self.clock.now() * 1e6), body)
        try:
            self.txsock.sendto(pkt, self.nack_dest)
        except OSError:
            return
        self.nacks += 1
        self.nack_bytes += len(pkt) + proto.IP_UDP_OVERHEAD
        for q in sent:
            v = self.missing.get(q)
            if v:
                v[1] += 1
                v[0] = now + self._delay(v[1])

    def _overheard(self, payload):
        """SRM suppression: someone else already asked for (some of) what we are waiting for."""
        try:
            rid, ranges = proto.unpack_nack(payload)
        except struct.error:
            return
        if rid == self.rid:
            return
        now = time.time()
        hit = False
        for a, b in ranges:
            for q in range(a, min(b, self.chunks - 1) + 1):
                v = self.missing.get(q)
                if v and v[0] > now:  # our own request timer has not fired yet -> cancel/back off
                    v[1] += 1
                    v[0] = now + self._delay(v[1])
                    hit = True
        if hit:
            self.suppressed += 1

    def _save(self):
        os.makedirs(self.out_dir, exist_ok=True)
        base = os.path.basename(self.meta["name"]) or "received.bin"
        stem, ext = os.path.splitext(base)
        path, k = os.path.join(self.out_dir, base), 1
        while os.path.exists(path):
            path = os.path.join(self.out_dir, "%s (%d)%s" % (stem, k, ext))
            k += 1
        with open(path, "wb") as f:
            f.write(b"".join(self.data))
        return path

    def _report(self):
        self.saved_path = None
        complete = self.got >= self.chunks and not self.aborted
        ok = False
        if complete:
            h = hashlib.sha256(b"".join(self.data)).hexdigest()
            ok = h == self.meta["sha256"]
            if ok and self.out_dir:
                self.saved_path = self._save()
        o = sorted(self.owd)
        rep = {"done": True, "rid": self.rid, "complete": complete, "verified": ok, "got": self.got,
               "recv": self.recv, "dups": self.dups, "nacks": self.nacks, "suppressed": self.suppressed,
               "nack_bytes": self.nack_bytes, "owd_n": len(o), "owd_sum": sum(o),
               "owd_p95": o[int(0.95 * (len(o) - 1))] if o else 0.0, "owd_max": o[-1] if o else 0.0,
               "raw_sum": sum(self.raw), "jitter": self.jitter, "sntp_offset": self.sntp["offset"],
               "skew_ms": self.skew_ms, "bitmap": self.bm.hex(), "transport": self.transport,
               "saved_path": self.saved_path, "duration_s": (time.time() - self.t_start) if self.t_start else 0.0}
        self.report = rep
        try:
            _send(self.ctl, rep)
            time.sleep(0.05)
        except OSError:
            pass
        try:
            self.ctl.close()
        except OSError:
            pass

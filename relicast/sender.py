"""Sender: TCP control listener + SNTP server + data transmitter for all four transport modes."""
import hashlib
import json
import random
import select
import socket
import struct
import threading
import time
from collections import deque

from . import clock as clk
from . import net, proto

HB_INTERVAL = 0.05
REPAIR_HOLD = 0.006   # relicast: aggregate NACKs for this long before repairing
REPAIR_GUARD = 0.030  # relicast: ignore NACKs for data repaired this recently (they are in flight)
TCP_STALL = 0.020     # tcp mode: modelled stall after a lost segment (fast retransmit / RTO scaled to LAN)
TCP_OVERHEAD = 40     # IPv4 + TCP headers


class RateLimiter:
    """Shared link capacity in packets/second (also supplies the flow control UDP lacks)."""

    def __init__(self, pps):
        self.interval = 1.0 / pps
        self.t = time.perf_counter()
        self.lock = threading.Lock()

    def acquire(self):
        with self.lock:
            now = time.perf_counter()
            if self.t < now - 0.01:
                self.t = now - 0.01
            self.t += self.interval
            wait = self.t - now
        if wait > 0.0015:
            time.sleep(wait)


class Sender:
    def __init__(self, payload, mode, n, name="payload.bin", link_pps=4000, chunk=1024, loss=0.0,
                 shared_loss=0.0, seed=1, iface="127.0.0.1", group=net.DEFAULT_GROUP, port=0, ttl=1,
                 timeout=40.0, on_progress=None, ctl_port=0, wait_ready=20.0, pace_tcp=True, probe=False):
        self.mode, self.n, self.name = mode, n, name
        self.pace_tcp, self.probe = pace_tcp, probe
        self.phase, self.message = 'lobby', ''
        self.rinfo = {}          # rid -> {ip, transport, mcast_ok}
        self.cancelled = threading.Event()
        self.start_event = None
        self.tcp_rids, self.mc_rids = [], []
        self.chunk, self.loss, self.shared = chunk, loss, shared_loss
        self.iface, self.group, self.ttl = iface, group, ttl
        self.timeout, self.wait_ready, self.on_progress = timeout, wait_ready, on_progress
        self.rng = random.Random(seed)
        self.rate = RateLimiter(link_pps)
        self.size = len(payload)
        self.chunks_data = [payload[i:i + chunk] for i in range(0, len(payload), chunk)] or [b""]
        self.chunks = len(self.chunks_data)
        self.sha = hashlib.sha256(payload).hexdigest()
        self.session = random.getrandbits(32)
        self.clock = clk.Clock(0.0)
        self.lock = threading.Lock()
        # counters
        self.c = dict(data=0, repair=0, heartbeat=0, nack_rx=0, bytes=0, packets=0)
        self.ready, self.done, self.progress = {}, {}, {}
        self.udp_dest = {}
        self.conns = {}
        self.stop = threading.Event()
        self.srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.srv.bind(("", ctl_port))
        self.srv.listen(64)
        self.ctl_port = self.srv.getsockname()[1]
        self.sntp = clk.SntpServer()
        self.sntp.start()
        self.mport = port or random.randint(20000, 60000)
        self.t0 = None
        # multicast repair state
        self.repair_q, self.pending, self.last_repair, self.hold_at = deque(), set(), {}, None
        threading.Thread(target=self._accept, daemon=True).start()

    # ---- control plane ---------------------------------------------------------------
    def _meta(self):
        return {"session": self.session, "name": self.name, "size": self.size, "chunk": self.chunk,
                "chunks": self.chunks, "sha256": self.sha, "mode": self.mode, "group": self.group,
                "port": self.mport, "ttl": self.ttl, "sntp_port": self.sntp.port, "timeout": self.timeout}

    def _accept(self):
        self.srv.settimeout(0.3)
        while not self.stop.is_set():
            try:
                conn, addr = self.srv.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            self.next_rid = getattr(self, "next_rid", 0) + 1
            meta = self._meta()
            meta["rid"] = self.next_rid  # used by receivers that did not pick their own id
            try:
                conn.sendall((json.dumps(meta) + "\n").encode())
            except OSError:
                continue
            threading.Thread(target=self._reader, args=(conn, addr), daemon=True).start()

    def _reader(self, conn, addr):
        buf, rid = b"", None
        try:
            while True:
                d = conn.recv(65536)
                if not d:
                    return
                buf += d
                while b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                    m = json.loads(line.decode())
                    rid = m.get("rid", rid)
                    with self.lock:
                        if m.get("ready"):
                            self.ready[rid] = m
                            self.conns[rid] = conn
                            self.udp_dest[rid] = (addr[0], m["udp_port"])
                            self.rinfo[rid] = {"ip": addr[0], "transport": "pending", "mcast_ok": None,
                                               "mcast_possible": m.get("mcast_possible", False)}
                        elif "mcast_ok" in m:
                            self.rinfo.setdefault(rid, {})["mcast_ok"] = bool(m["mcast_ok"])
                        elif m.get("progress"):
                            self.progress[rid] = m
                        elif m.get("done"):
                            m["t"] = time.perf_counter()
                            self.done[rid] = m
                            return
        except (OSError, ValueError):
            return

    # ---- helpers ----------------------------------------------------------------------
    def _ts(self):
        return int(self.clock.now() * 1e6)

    def _count(self, kind, nbytes):
        self.c[kind] += 1
        self.c["packets"] += 1
        self.c["bytes"] += nbytes

    def _data_pkt(self, ptype, seq):
        return proto.pack(ptype, self.session, seq, self.chunks, self._ts(), self.chunks_data[seq])

    def _emit(self):
        if not self.on_progress or self.t0 is None:
            return
        with self.lock:
            recs = []
            nacks = sup = 0
            for rid in sorted(set(self.progress) | set(self.done)):
                m = self.done.get(rid) or self.progress.get(rid)
                recs.append({"rid": rid, "have": m.get("have", m.get("got", 0)), "bitmap": m.get("bitmap", ""),
                             "complete": rid in self.done and self.done[rid].get("complete", False)})
                nacks += m.get("nacks", 0)
                sup += m.get("suppressed", 0)
            ev = {"mode": self.mode, "elapsed": time.perf_counter() - self.t0, "chunks": self.chunks,
                  "receivers": recs,
                  "counters": {"data": self.c["data"], "repair": self.c["repair"], "heartbeat": self.c["heartbeat"],
                               "nack": nacks, "suppressed": sup, "sender_bytes": self.c["bytes"]}}
        try:
            self.on_progress(ev)
        except Exception:
            pass

    def _all_done(self):
        with self.lock:
            return len(self.done) >= getattr(self, 'n_active', self.n)

    # ---- run ---------------------------------------------------------------------------
    def _send_ctl(self, rid, obj):
        conn = self.conns.get(rid)
        if conn is None:
            return False
        try:
            conn.sendall((json.dumps(obj) + "\n").encode())
            return True
        except OSError:
            return False

    def cancel(self):
        self.cancelled.set()
        for rid in list(self.conns):
            self._send_ctl(rid, {"cmd": "abort"})

    def run(self, start_event=None):
        """Lobby -> (probe) -> transmit.  Without start_event, starts once n receivers are ready."""
        end = time.time() + self.wait_ready
        while not self.cancelled.is_set():
            with self.lock:
                nready = len(self.ready)
            if start_event is None:
                if nready >= self.n or time.time() > end:
                    break
            elif start_event.is_set():
                break
            time.sleep(0.03)
        if self.cancelled.is_set():
            self.phase = "cancelled"
            self.close()
            return None
        self.start_event = start_event
        self.n = len(self.ready) if start_event is not None else self.n
        self.n_active = self.n
        rids = sorted(self.ready)
        multicast = self.mode in ("naive", "relicast")
        if multicast and self.probe:
            self._probe(rids)
        for rid in rids:
            if self.mode == "tcp":
                tr = "tcp"
            elif self.mode == "udp":
                tr = "udp"
            else:
                ok = self.rinfo[rid].get("mcast_ok")
                tr = "mcast" if (ok is None and self.rinfo[rid].get("mcast_possible")) or ok else "tcp"
            self.rinfo[rid]["transport"] = tr
        self.mc_rids = [r for r in rids if self.rinfo[r]["transport"] == "mcast"]
        self.tcp_rids = [r for r in rids if self.rinfo[r]["transport"] == "tcp"]
        self.phase = "sending"
        self.t0 = time.perf_counter()
        for rid in rids:
            self._send_ctl(rid, {"cmd": "start", "transport": self.rinfo[rid]["transport"]})
        threading.Thread(target=self._ticker, daemon=True).start()
        try:
            {"tcp": self._tx_tcp, "udp": self._tx_udp, "naive": self._tx_mcast, "relicast": self._tx_mcast}[self.mode]()
        finally:
            t_end = time.perf_counter()
            self.stop_ticker = True
            self._emit()
            self.phase = "cancelled" if self.cancelled.is_set() else "done"
            self.close()
        return self._result(t_end)

    def _probe(self, rids):
        """Find out which receivers can actually hear multicast (hotspots/APs often block it)."""
        self.phase = "probing"
        for rid in rids:
            self._send_ctl(rid, {"cmd": "probe"})
        time.sleep(0.15)
        tx = net.mcast_send_socket(self.iface, self.ttl)
        for i in range(10):
            tx.sendto(proto.pack(proto.PROBE, self.session, i, 0, self._ts(), b"probe"), (self.group, self.mport))
            time.sleep(0.1)
        tx.close()
        end = time.time() + 4.0
        while time.time() < end:
            with self.lock:
                if all(self.rinfo[r].get("mcast_ok") is not None for r in rids):
                    break
            time.sleep(0.05)
        for r in rids:
            if self.rinfo[r].get("mcast_ok") is None:
                self.rinfo[r]["mcast_ok"] = False

    def _ticker(self):
        self.stop_ticker = False
        while not self.stop_ticker:
            self._emit()
            time.sleep(0.1)

    def close(self):
        self.stop.set()
        self.sntp.stop()
        try:
            self.srv.close()
        except OSError:
            pass

    # ---- mode: tcp ----------------------------------------------------------------------
    def _tx_tcp(self):
        ths = [threading.Thread(target=self._tcp_conn, args=(rid,)) for rid in list(self.tcp_rids)]
        for t in ths:
            t.start()
        for t in ths:
            t.join()
        self._wait_done(self.timeout)

    def _tcp_conn(self, rid):
        conn = self.conns.get(rid)
        if conn is None:
            return
        rng = random.Random(self.rng.random())
        p = 1 - (1 - self.loss) * (1 - self.shared)
        conn.settimeout(self.timeout)
        try:
            for seq in range(self.chunks):
                first = True
                while True:
                    if self.pace_tcp:
                        self.rate.acquire()
                    pkt = self._data_pkt(proto.DATA, seq)
                    wire = 2 + len(pkt) + TCP_OVERHEAD
                    with self.lock:
                        self._count("data" if first else "repair", wire)
                    first = False
                    if p > 0 and rng.random() < p:  # (emulated) segment loss: retransmit after a stall
                        time.sleep(TCP_STALL)
                        continue
                    conn.sendall(struct.pack("!H", len(pkt)) + pkt)
                    break
        except OSError:
            return

    # ---- mode: udp (raw, unicast copies, no recovery) ------------------------------------
    def _tx_udp(self):
        s = net.udp_socket()
        dests = [self.udp_dest[r] for r in sorted(self.ready)]
        for seq in range(self.chunks):
            pkt = self._data_pkt(proto.DATA, seq)
            for d in dests:
                self.rate.acquire()
                with self.lock:
                    self._count("data", len(pkt) + proto.IP_UDP_OVERHEAD)
                if self.shared and self.rng.random() < self.shared:
                    continue
                s.sendto(pkt, d)
        time.sleep(0.15)
        fin = proto.pack(proto.FIN, self.session, 0, self.chunks, self._ts())
        for _ in range(3):
            for d in dests:
                s.sendto(fin, d)
            time.sleep(0.02)
        self._wait_done(5.0)
        s.close()

    # ---- modes: naive / relicast multicast --------------------------------------------------
    def _tx_mcast(self):
        tcp_threads = [threading.Thread(target=self._tcp_conn, args=(rid,)) for rid in list(self.tcp_rids)]
        for t in tcp_threads:  # hotspot fallback: receivers that cannot hear multicast get TCP
            t.start()
        if not self.mc_rids:
            for t in tcp_threads:
                t.join()
            self._wait_done(self.timeout)
            return
        tx = net.mcast_send_socket(self.iface, self.ttl)
        rx = net.mcast_recv_socket(self.group, self.mport, self.iface)
        dest = (self.group, self.mport)
        th = threading.Thread(target=self._nack_listener, args=(rx,), daemon=True)
        th.start()
        hb_at, highest = 0.0, -1

        def heartbeat():
            pkt = proto.pack(proto.HEARTBEAT, self.session, max(highest, 0), self.chunks, self._ts())
            tx.sendto(pkt, dest)
            with self.lock:
                self._count("heartbeat", len(pkt) + proto.IP_UDP_OVERHEAD)

        def send_repairs():
            sent = 0
            while True:
                self._release_hold()
                with self.lock:
                    if not self.repair_q:
                        return sent
                    seq = self.repair_q.popleft()
                self.rate.acquire()
                pkt = self._data_pkt(proto.REPAIR, seq)
                tx.sendto(pkt, dest)
                with self.lock:
                    self._count("repair", len(pkt) + proto.IP_UDP_OVERHEAD)
                    self.last_repair[seq] = time.time()
                sent += 1
                if sent >= 8:
                    return sent

        for seq in range(self.chunks):
            if self.cancelled.is_set():
                break
            send_repairs()
            self.rate.acquire()
            pkt = self._data_pkt(proto.DATA, seq)
            with self.lock:
                self._count("data", len(pkt) + proto.IP_UDP_OVERHEAD)
            if not (self.shared and self.rng.random() < self.shared):  # shared = upstream loss
                tx.sendto(pkt, dest)
            highest = seq
            if time.time() - hb_at >= HB_INTERVAL:
                heartbeat()
                hb_at = time.time()
        end = time.time() + self.timeout
        while not self._all_done() and time.time() < end and not self.cancelled.is_set():
            if not send_repairs():
                time.sleep(0.001)
            if time.time() - hb_at >= HB_INTERVAL:
                heartbeat()
                hb_at = time.time()
        fin = proto.pack(proto.FIN, self.session, 0, self.chunks, self._ts())
        for _ in range(3):
            tx.sendto(fin, dest)
            time.sleep(0.01)
        for t in tcp_threads:
            t.join(timeout=2)
        self.stop_nack = True
        th.join(timeout=1)
        rx.close()
        tx.close()

    def _release_hold(self):
        with self.lock:
            if self.hold_at is not None and time.time() >= self.hold_at:
                self.repair_q.extend(sorted(self.pending))
                self.pending.clear()
                self.hold_at = None

    def _nack_listener(self, rx):
        self.stop_nack = False
        rx.settimeout(0.05)
        while not self.stop_nack:
            try:
                buf, _ = rx.recvfrom(4096)
            except socket.timeout:
                continue
            except OSError:
                return
            p = proto.unpack(buf)
            if not p or p[0] != proto.NACK or p[1] != self.session:
                continue
            if self.loss and self.rng.random() < self.loss:
                continue
            try:
                rid, ranges = proto.unpack_nack(p[5])
            except struct.error:
                continue
            now = time.time()
            with self.lock:
                self.c["nack_rx"] += 1
                for a, b in ranges:
                    for q in range(a, min(b, self.chunks - 1) + 1):
                        if self.mode == "naive":
                            self.repair_q.append(q)  # one repair per request: repair implosion
                        elif q not in self.pending and now - self.last_repair.get(q, -9) > REPAIR_GUARD:
                            self.pending.add(q)
                            if self.hold_at is None:
                                self.hold_at = now + REPAIR_HOLD

    def _wait_done(self, t):
        end = time.time() + t
        while time.time() < end and not self._all_done():
            time.sleep(0.01)

    # ---- result ---------------------------------------------------------------------------------
    def _result(self, t_end):
        with self.lock:
            done = dict(self.done)
            c = dict(self.c)
        last = max([d["t"] for d in done.values()] + [t_end]) if len(done) >= self.n else t_end
        dur = max(last - self.t0, 1e-6)
        per, got_sum, nacks, sup, dups, nack_bytes = [], 0, 0, 0, 0, 0
        owd_n = owd_sum = raw_sum = 0.0
        p95s, maxes, jit, offs, skews = [], [], [], [], []
        verified = 0
        all_rids = sorted(set(self.ready) | (set(range(1, self.n + 1)) if self.start_event is None else set()))
        for rid in all_rids:
            d = done.get(rid)
            if not d:
                per.append({"rid": rid, "complete": False, "time_s": None, "recv": 0, "dups": 0, "nacks": 0,
                            "suppressed": 0, "missing_final": self.chunks})
                continue
            got_sum += d["got"]
            nacks += d["nacks"]
            sup += d["suppressed"]
            dups += d["dups"]
            nack_bytes += d["nack_bytes"]
            verified += 1 if d["verified"] else 0
            owd_n += d["owd_n"]
            owd_sum += d["owd_sum"]
            raw_sum += d["raw_sum"]
            p95s.append(d["owd_p95"])
            maxes.append(d["owd_max"])
            jit.append(d["jitter"])
            offs.append(-d["sntp_offset"] * 1000)  # estimated clock error = -(correction)
            skews.append(d["skew_ms"])
            per.append({"rid": rid, "complete": d["complete"], "time_s": round(d["t"] - self.t0, 4),
                        "recv": d["recv"], "dups": d["dups"], "nacks": d["nacks"], "suppressed": d["suppressed"],
                        "missing_final": self.chunks - d["got"]})
        total_bytes = c["bytes"] + nack_bytes
        ratio = got_sum / float(max(1, self.n) * self.chunks)
        mean = lambda v: sum(v) / len(v) if v else 0.0
        return {
            "mode": self.mode, "n": self.n, "loss": self.loss, "shared_loss": self.shared, "size_bytes": self.size,
            "chunk": self.chunk, "chunks": self.chunks, "ok": verified == self.n or self.mode == "udp",
            "all_verified": verified == self.n, "delivery_ratio": round(ratio, 5),
            "duration_s": round(dur, 4), "goodput_mbps": round(self.n * self.size * 8 * ratio / dur / 1e6, 3),
            "sender_bytes": c["bytes"], "sender_packets": c["packets"], "data_packets": c["data"],
            "repair_packets": c["repair"], "heartbeat_packets": c["heartbeat"], "nack_packets": nacks,
            "nack_suppressed": sup, "dup_data": dups, "total_bytes": total_bytes,
            "overhead_ratio": round(total_bytes / float(self.size), 3),
            "owd_mean_ms": round(1000 * owd_sum / owd_n, 4) if owd_n else 0.0,
            "owd_p95_ms": round(1000 * mean(p95s), 4), "owd_max_ms": round(1000 * max(maxes or [0]), 4),
            "jitter_ms": round(1000 * mean(jit), 4),
            "owd_raw_mean_ms": round(1000 * raw_sum / owd_n, 4) if owd_n else 0.0,
            "sntp_offsets_ms": [round(x, 3) for x in offs], "skews_ms": [round(x, 3) for x in skews],
            "per_receiver": per, "interface": self.iface,
            "transports": {str(r): self.rinfo[r].get("transport") for r in self.rinfo},
        }

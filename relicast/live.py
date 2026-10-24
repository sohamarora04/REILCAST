"""Real-world mode: send an actual file to real devices on the LAN / hotspot, or receive one.

 * Discovery: the sender broadcasts a small UDP beacon (255.255.255.255 / subnet broadcast, port 5599);
   receivers listen for beacons and list the available transfers.
 * Send: lobby (receivers connect over TCP) -> optional multicast probe -> transfer -> result.
 * Receive: join a sender, receive over multicast+NACK / TCP / UDP, verify SHA-256, save to the inbox.
All state is exposed as plain dicts for the dashboard.
"""
import json
import os
import platform
import socket
import subprocess
import sys
import threading
import time

from . import __version__, engine, net
from .sender import Sender

BEACON_PORT = 5599
OUTBOX = os.path.join(os.path.expanduser("~"), "ReliCast", "outbox")
INBOX = os.path.join(os.path.expanduser("~"), "ReliCast", "received")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = ("relicast", "naive", "tcp", "udp")

_lock = threading.RLock()
_services_started = False
_seen = {}        # (host, port) -> beacon dict + last_seen
_send = None      # current LiveSend
_recv = None      # current LiveRecv


def info():
    return {"ip": net.primary_ip() or "127.0.0.1", "hostname": socket.gethostname(), "outbox": OUTBOX,
            "inbox": INBOX, "version": __version__, "platform": platform.platform()}


# ------------------------------------------------------------------ discovery ---------------
def _broadcast_targets(ip):
    t = [("255.255.255.255", BEACON_PORT), ("127.0.0.1", BEACON_PORT)]
    if ip and ip.count(".") == 3:
        t.append((ip.rsplit(".", 1)[0] + ".255", BEACON_PORT))  # directed broadcast, assuming /24
    return t


def _beacon_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
    while True:
        time.sleep(1.0)
        snd = _send
        if not snd or snd.phase not in ("lobby",):
            continue
        ip = info()["ip"]
        msg = json.dumps({"app": "relicast", "v": 1, "host": ip, "port": snd.sender.ctl_port,
                          "name": snd.file["name"], "size": snd.file["size"], "mode": snd.mode,
                          "sender": socket.gethostname()}).encode()
        for dest in _broadcast_targets(ip):
            try:
                s.sendto(msg, dest)
            except OSError:
                pass


def _listen_loop():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    if hasattr(socket, "SO_REUSEPORT"):
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except OSError:
            pass
    try:
        s.bind(("", BEACON_PORT))
    except OSError:
        return
    while True:
        try:
            data, addr = s.recvfrom(2048)
            m = json.loads(data.decode())
        except (OSError, ValueError):
            continue
        if m.get("app") != "relicast":
            continue
        m["last_seen"] = time.time()
        with _lock:
            _seen[(m["host"], m["port"])] = m


def start_services():
    global _services_started
    if _services_started:
        return
    _services_started = True
    for fn in (_beacon_loop, _listen_loop):
        threading.Thread(target=fn, daemon=True).start()


def recv_discover():
    now = time.time()
    with _lock:
        for k in [k for k, v in _seen.items() if now - v["last_seen"] > 4]:
            del _seen[k]
        return [{"host": v["host"], "port": v["port"], "name": v["name"], "size": v["size"], "mode": v["mode"],
                 "sender": v.get("sender", ""), "age_s": round(now - v["last_seen"], 1)} for v in _seen.values()]


# ------------------------------------------------------------------ send ---------------------
class LiveSend:
    def __init__(self, path, name, mode, rate_mbps):
        with open(path, "rb") as f:
            payload = f.read()
        if not payload:
            raise ValueError("file is empty")
        self.file = {"name": name, "size": len(payload),
                     "sha256": None}
        self.mode, self.rate = mode, rate_mbps
        pps = max(50, int(rate_mbps * 1e6 / 8 / (engine.CHUNK + 52)))
        secs = len(payload) / (rate_mbps * 1e6 / 8.0)
        self.iface = engine.get_iface()
        self.start_event = threading.Event()
        self.result, self.message, self.error = None, "", None
        self.live = None
        self.sender = Sender(payload, mode, 0, name=name, link_pps=pps, chunk=engine.CHUNK, iface=self.iface,
                             timeout=max(60.0, secs * 6 + 30), on_progress=self._on_progress, ctl_port=0,
                             wait_ready=24 * 3600, pace_tcp=False, probe=True)
        self.file["sha256"] = self.sender.sha
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    @property
    def phase(self):
        if self.error:
            return "error"
        return self.sender.phase

    def _on_progress(self, ev):
        self.live = ev

    def _run(self):
        try:
            self.result = self.sender.run(start_event=self.start_event)
        except Exception as e:  # surface to UI
            self.error = "%s: %s" % (type(e).__name__, e)

    def start(self):
        with self.sender.lock:
            n = len(self.sender.ready)
        if n == 0:
            raise ValueError("no receivers have joined yet")
        self.start_event.set()

    def cancel(self):
        self.sender.cancel()

    def state(self):
        s = self.sender
        prog = {}
        if self.live:
            for r in self.live["receivers"]:
                prog[r["rid"]] = r
        recvs = []
        with s.lock:
            infos = {rid: dict(v) for rid, v in s.rinfo.items()}
            done = dict(s.done)
        for rid in sorted(infos):
            i, pr, d = infos[rid], prog.get(rid, {}), done.get(rid)
            have = d["got"] if d else pr.get("have", 0)
            recvs.append({"rid": rid, "ip": i.get("ip"), "transport": i.get("transport"),
                          "mcast_ok": i.get("mcast_ok"), "have": have,
                          "pct": round(100.0 * have / s.chunks, 1), "complete": bool(d and d["complete"]),
                          "verified": d["verified"] if d else None})
        return {"phase": self.phase, "message": self.error or self.message, "file": self.file, "mode": self.mode,
                "rate_mbps": self.rate, "host": info()["ip"], "port": s.ctl_port, "receivers": recvs,
                "live": self.live, "result": self.result}


def _safe_join(base, name):
    p = os.path.realpath(os.path.join(base, os.path.basename(name)))
    if os.path.dirname(p) != os.path.realpath(base):
        raise ValueError("bad file name")
    return p


def send_open(path=None, name=None, mode="relicast", rate_mbps=8):
    global _send
    if mode not in MODES:
        raise ValueError("unknown protocol %r" % mode)
    rate_mbps = float(rate_mbps)
    if not 0.1 <= rate_mbps <= 1000:
        raise ValueError("rate must be between 0.1 and 1000 Mbps")
    if not path:
        if not name:
            raise ValueError("choose a file")
        path = _safe_join(OUTBOX, name)
    path = os.path.abspath(os.path.expanduser(path))
    if not os.path.isfile(path):
        raise ValueError("file not found: %s" % path)
    with _lock:
        if _send and _send.phase in ("lobby", "probing", "sending"):
            raise ValueError("a transfer is already open - cancel it first")
        _send = LiveSend(path, os.path.basename(path), mode, rate_mbps)
    return send_state()


def send_start():
    if not _send:
        raise ValueError("no open session")
    _send.start()
    return send_state()


def send_cancel():
    if _send:
        _send.cancel()
    return send_state()


def send_state():
    if not _send:
        return {"phase": "idle", "message": "", "file": None, "mode": None, "rate_mbps": None, "host": "",
                "port": 0, "receivers": [], "live": None, "result": None}
    return _send.state()


# ------------------------------------------------------------------ receive --------------------
class LiveRecv:
    """Runs `python -m relicast recv` as a child process and mirrors its progress via a private TCP
    observer is overkill - instead run the Receiver in-process in a thread and read its fields."""

    def __init__(self, host, port):
        from .receiver import Receiver
        self.host, self.port = host, port
        self.error, self.stats = None, None
        self.r = Receiver(host, port, 0, float(os.environ.get("RELICAST_LOSS", 0)), 1, 0.0, engine.get_iface(),
                          out_dir=INBOX)  # RELICAST_LOSS: test hook to emulate a lossy link
        self.t0 = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self):
        try:
            self.r.run()
        except Exception as e:
            self.error = "%s: %s" % (type(e).__name__, e)

    def cancel(self):
        self.r.aborted = True
        try:
            self.r.ctl.close()
        except Exception:
            pass

    def state(self):
        r = self.r
        meta = getattr(r, "meta", None)
        phase = "connecting"
        if self.error:
            phase = "error"
        elif meta:
            phase = "waiting"
            if getattr(r, "transport", None):
                phase = "receiving"
            if not self.thread.is_alive():
                phase = "done" if getattr(r, "report", None) else "error"
        st = {"phase": phase, "message": self.error or "", "host": self.host, "port": self.port,
              "name": meta["name"] if meta else "", "size": meta["size"] if meta else 0,
              "pct": 0.0, "have": 0, "chunks": meta["chunks"] if meta else 0,
              "bitmap": r.bm.hex() if meta else "", "transport": getattr(r, "transport", None),
              "saved_path": None, "verified": None, "stats": None}
        if meta:
            st["have"] = r.got
            st["pct"] = round(100.0 * r.got / max(1, r.chunks), 1)
            o = r.owd
            st["stats"] = {"nacks": r.nacks, "suppressed": r.suppressed, "recv": r.recv, "dups": r.dups,
                           "owd_mean_ms": round(1000 * sum(o) / len(o), 3) if o else 0.0,
                           "jitter_ms": round(1000 * r.jitter, 3),
                           "duration_s": round((time.time() - r.t_start), 2) if r.t_start and phase == "receiving" else
                           round(getattr(r, "report", {}).get("duration_s", 0.0), 2)}
            rep = getattr(r, "report", None)
            if rep:
                st["saved_path"], st["verified"] = rep.get("saved_path"), rep.get("verified")
                if not rep.get("complete") and phase == "done":
                    st["message"] = "incomplete: %d of %d chunks (raw UDP does not repair losses)" % (r.got, r.chunks)
        return st


def recv_join(host, port):
    global _recv
    with _lock:
        if _recv and _recv.state()["phase"] in ("connecting", "waiting", "receiving"):
            raise ValueError("already receiving - cancel first")
        _recv = LiveRecv(host, int(port))
    return recv_state()


def recv_cancel():
    if _recv:
        _recv.cancel()
    return recv_state()


def recv_state():
    if not _recv:
        return {"phase": "idle", "message": "", "host": "", "port": 0, "name": "", "size": 0, "pct": 0.0, "have": 0,
                "chunks": 0, "bitmap": "", "transport": None, "saved_path": None, "verified": None, "stats": None}
    return _recv.state()

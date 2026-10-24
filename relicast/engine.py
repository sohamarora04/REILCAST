"""Orchestration: spawn receiver processes, run one transfer, run comparisons and sweeps."""
import json
import os
import platform
import random
import subprocess
import sys
import time

from . import net
from .sender import Sender

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MODES = ["tcp", "udp", "naive", "relicast"]
LABELS = {"tcp": "TCP unicast", "udp": "Raw UDP unicast", "naive": "Multicast + immediate NACK",
          "relicast": "ReliCast (proposed)"}
LINK_PPS = 4000
CHUNK = 1024
_iface = None


def get_iface():
    global _iface
    if _iface is None:
        _iface = net.pick_interface()
        if _iface is None:
            raise RuntimeError("No network interface supports multicast loopback on this machine. "
                               "Connect to a Wi-Fi/LAN network and retry.")
    return _iface


def make_payload(size_kb, seed):
    rng = random.Random(seed)
    return rng.getrandbits(8 * size_kb * 1024).to_bytes(size_kb * 1024, "big")


def run_transfer(mode, n, loss, shared_loss, size_kb, seed=1, on_progress=None, link_pps=LINK_PPS,
                 payload=None, name=None):
    iface = get_iface()
    payload = payload if payload is not None else make_payload(size_kb, seed)
    s = Sender(payload, mode, n, name=name or "lecture_slides.bin", link_pps=link_pps, chunk=CHUNK, loss=loss,
               shared_loss=shared_loss, seed=seed, iface=iface, on_progress=on_progress,
               timeout=max(30.0, 3.0 * n * len(payload) / (link_pps * CHUNK) + 15))
    rng = random.Random(seed * 7919 + n)
    procs = []
    env = dict(os.environ, PYTHONPATH=ROOT + os.pathsep + os.environ.get("PYTHONPATH", ""))
    skews = []
    for rid in range(1, n + 1):
        skew = rng.choice([-1, 1]) * rng.uniform(100, 500)  # injected clock error, ms
        skews.append(skew)
        procs.append(subprocess.Popen(
            [sys.executable, "-m", "relicast", "recv", "--host", "127.0.0.1", "--port", str(s.ctl_port),
             "--rid", str(rid), "--loss", str(loss), "--seed", str(seed), "--skew-ms", "%.3f" % skew,
             "--iface", iface], cwd=ROOT, env=env, stdout=subprocess.DEVNULL))
    try:
        res = s.run()
    finally:
        for p in procs:
            try:
                p.wait(timeout=5)
            except subprocess.TimeoutExpired:
                p.kill()
    res["seed"] = seed
    return res


def run_comparison(params, on_progress=None, on_result=None, modes=None):
    out = {}
    for m in modes or MODES:
        r = run_transfer(m, int(params["n"]), float(params["loss"]), float(params["shared_loss"]),
                         int(params["size_kb"]), int(params.get("seed", 1)), on_progress=on_progress)
        out[m] = r
        if on_result:
            on_result(m, r)
    return out


def run_experiments(path, size_kb=512, reps=3, log=print):
    results_dir = os.path.dirname(path)
    os.makedirs(results_dir, exist_ok=True)
    data = {"meta": {"date": time.strftime("%Y-%m-%d %H:%M"), "platform": platform.platform(),
                     "python": platform.python_version(), "interface": get_iface(), "size_kb": size_kb,
                     "chunk": CHUNK, "link_pps": LINK_PPS, "reps": reps, "cpu_count": os.cpu_count()},
            "sweep_receivers": [], "sweep_loss": [], "demo": {}}

    def save():
        with open(path, "w") as f:
            json.dump(data, f, indent=1)

    log("== Sweep 1: receivers (loss 5%, shared 2%) ==")
    for n in (1, 2, 4, 8, 16):
        for m in MODES:
            for rep in range(reps):
                r = run_transfer(m, n, 0.05, 0.02, size_kb, seed=100 + rep)
                r["rep"] = rep
                data["sweep_receivers"].append(r)
                log("  n=%-2d %-8s rep%d  %.2fs  overhead %.2fx  delivery %.3f  nacks %d"
                    % (n, m, rep, r["duration_s"], r["overhead_ratio"], r["delivery_ratio"], r["nack_packets"]))
        save()
    log("== Sweep 2: loss (8 receivers) ==")
    for p in (0.0, 0.01, 0.02, 0.05, 0.10, 0.20):
        for m in MODES:
            for rep in range(reps):
                r = run_transfer(m, 8, p, 0.0, size_kb, seed=200 + rep)
                r["rep"] = rep
                data["sweep_loss"].append(r)
                log("  loss=%.2f %-8s rep%d  %.2fs  overhead %.2fx  delivery %.3f"
                    % (p, m, rep, r["duration_s"], r["overhead_ratio"], r["delivery_ratio"]))
        save()
    log("== Demo point (6 receivers, loss 8%, shared 3%) ==")
    for m in MODES:
        data["demo"][m] = run_transfer(m, 6, 0.08, 0.03, size_kb, seed=7)
    save()
    return data

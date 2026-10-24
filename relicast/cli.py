"""Command line: dashboard (default) | demo | experiments | send | recv"""
import argparse
import os
import subprocess
import sys
import time

from . import engine, net

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RESULTS = os.path.join(ROOT, "results")


class Tee:
    def __init__(self, path):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.f = open(path, "w")

    def __call__(self, msg=""):
        print(msg)
        sys.stdout.flush()
        self.f.write(msg + "\n")

    def close(self):
        self.f.close()


def comparison_table(res, log):
    rows = [("Mode", "Time(s)", "Sender MB", "Overhead", "Delivery", "NACKs", "Suppr.", "Repairs", "OWD ms", "Jitter ms")]
    for m in engine.MODES:
        r = res[m]
        rows.append((engine.LABELS[m], "%.2f" % r["duration_s"], "%.2f" % (r["sender_bytes"] / 1e6),
                     "%.2fx" % r["overhead_ratio"], "%.1f%%" % (100 * r["delivery_ratio"]), str(r["nack_packets"]),
                     str(r["nack_suppressed"]), str(r["repair_packets"]), "%.3f" % r["owd_mean_ms"],
                     "%.3f" % r["jitter_ms"]))
    w = [max(len(r[i]) for r in rows) for i in range(len(rows[0]))]
    line = "+" + "+".join("-" * (x + 2) for x in w) + "+"
    log(line)
    for i, r in enumerate(rows):
        log("| " + " | ".join(c.ljust(w[j]) for j, c in enumerate(r)) + " |")
        if i == 0:
            log(line)
    log(line)


def cmd_demo(a, log=print):
    iface = engine.get_iface()
    log("ReliCast demo | interface %s | %d receivers | loss %.0f%% (+%.0f%% shared) | %d KB file"
        % (iface, a.receivers, 100 * a.loss, 100 * a.shared, a.size_kb))
    log("Receiver clocks are skewed by +/-100..500 ms; SNTP must correct them before delays are measured.")
    tty = sys.stdout.isatty()
    res = {}
    for m in engine.MODES:
        last = [0.0]

        def prog(ev, m=m):
            if time.time() - last[0] < 0.25 or not tty:
                return
            last[0] = time.time()
            pct = 100 * sum(r["have"] for r in ev["receivers"]) / max(1, ev["chunks"] * a.receivers)
            bar = "#" * int(pct / 4)
            sys.stdout.write("\r  %-28s [%-25s] %5.1f%%  nack=%d repair=%d" % (
                engine.LABELS[m], bar, pct, ev["counters"]["nack"], ev["counters"]["repair"]))
            sys.stdout.flush()

        r = engine.run_transfer(m, a.receivers, a.loss, a.shared, a.size_kb, seed=a.seed, on_progress=prog)
        res[m] = r
        if tty:
            sys.stdout.write("\r" + " " * 100 + "\r")
        log("  %-28s done in %.2fs | delivery %.1f%% | verified %s | sender %.2f MB | NACKs %d (suppressed %d) | repairs %d"
            % (engine.LABELS[m], r["duration_s"], 100 * r["delivery_ratio"], r["all_verified"],
               r["sender_bytes"] / 1e6, r["nack_packets"], r["nack_suppressed"], r["repair_packets"]))
    log("")
    comparison_table(res, log)
    rl, tc = res["relicast"], res["tcp"]
    log("")
    log("ReliCast vs TCP-unicast: %.1fx fewer sender bytes, %.1fx faster. vs naive multicast: %.1fx fewer NACKs."
        % (tc["sender_bytes"] / max(1, rl["sender_bytes"]), tc["duration_s"] / max(1e-6, rl["duration_s"]),
           res["naive"]["nack_packets"] / max(1, rl["nack_packets"])))
    log("SNTP: injected skews (ms) %s" % ", ".join("%.0f" % x for x in rl["skews_ms"]))
    log("      estimated offsets   %s" % ", ".join("%.0f" % x for x in rl["sntp_offsets_ms"]))
    log("      one-way delay: raw (unsynchronised) %.1f ms  ->  SNTP-corrected %.3f ms" % (rl["owd_raw_mean_ms"], rl["owd_mean_ms"]))
    return res


def cmd_send(a):
    import threading
    from . import live
    live.start_services()
    st = live.send_open(path=a.file, mode=a.mode, rate_mbps=a.rate_mbps)
    print("Sharing %s (%.2f MB) with %s | session %s:%d" % (st["file"]["name"], st["file"]["size"] / 1e6, a.mode,
                                                         st["host"], st["port"]))
    print("On each receiving device run:  python run.py receive      (or   --host %s --port %d)" % (st["host"], st["port"]))
    print("Press Enter to START once all receivers have joined (Ctrl+C to cancel).")
    go = threading.Event()
    threading.Thread(target=lambda: (sys.stdin.readline(), go.set()), daemon=True).start()
    seen = 0
    while not go.is_set():
        st = live.send_state()
        if len(st["receivers"]) != seen:
            seen = len(st["receivers"])
            print("  receivers joined: %d  (%s)" % (seen, ", ".join(r["ip"] for r in st["receivers"])))
        time.sleep(0.2)
    live.send_start()
    while True:
        st = live.send_state()
        if st["phase"] == "probing":
            sys.stdout.write("\r  probing multicast reachability...            ")
        elif st["phase"] == "sending" and st["live"]:
            tot = sum(r["pct"] for r in st["receivers"]) / max(1, len(st["receivers"]))
            sys.stdout.write("\r  sending... avg %5.1f%%  repairs=%d nacks=%d    " % (
                tot, st["live"]["counters"]["repair"], st["live"]["counters"]["nack"]))
        elif st["phase"] in ("done", "error", "cancelled"):
            break
        sys.stdout.flush()
        time.sleep(0.2)
    print()
    r = st["result"]
    if r:
        print("Finished in %.2fs | all verified: %s | sender bytes %.2f MB | NACKs %d (suppressed %d) | repairs %d"
              % (r["duration_s"], r["all_verified"], r["sender_bytes"] / 1e6, r["nack_packets"], r["nack_suppressed"],
                 r["repair_packets"]))
        for rc in st["receivers"]:
            print("  receiver %d %-15s via %-5s %s" % (rc["rid"], rc["ip"], rc["transport"],
                                                    "OK" if rc["verified"] else "NOT VERIFIED"))
    else:
        print(st["message"] or st["phase"])


def cmd_receive(a):
    from . import live
    live.start_services()
    host, port = a.host, a.port
    if not host:
        print("Looking for senders on this network (Ctrl+C to quit)...")
        while True:
            found = live.recv_discover()
            if found:
                break
            time.sleep(0.3)
        for i, f in enumerate(found):
            print("  [%d] %s  (%.2f MB, %s) from %s %s:%d" % (i, f["name"], f["size"] / 1e6, f["mode"], f["sender"],
                                                           f["host"], f["port"]))
        k = 0
        if len(found) > 1:
            k = int(input("Join which one? "))
        host, port = found[k]["host"], found[k]["port"]
    if a.out:
        live.INBOX = a.out
    live.recv_join(host, port)
    while True:
        st = live.recv_state()
        sys.stdout.write("\r  %-10s %-24s %5.1f%%  via %s   " % (st["phase"], st["name"], st["pct"], st["transport"] or "-"))
        sys.stdout.flush()
        if st["phase"] in ("done", "error"):
            break
        time.sleep(0.2)
    print()
    if st["verified"]:
        print("Saved %s  (SHA-256 verified)" % st["saved_path"])
    else:
        print(st["message"] or "transfer failed")


def main():
    net.enable_ansi()
    ap = argparse.ArgumentParser(prog="relicast", description=__doc__)
    sub = ap.add_subparsers(dest="cmd")

    def common(p):
        p.add_argument("--receivers", type=int, default=6)
        p.add_argument("--loss", type=float, default=0.08)
        p.add_argument("--shared", type=float, default=0.03)
        p.add_argument("--size-kb", type=int, default=512)
        p.add_argument("--seed", type=int, default=7)

    d = sub.add_parser("dashboard", help="web dashboard (default)")
    d.add_argument("--port", type=int, default=8765)
    d.add_argument("--no-browser", action="store_true")
    d.add_argument("--lan", action="store_true", help="also serve the phone download/upload pages to the LAN")
    common(sub.add_parser("demo", help="terminal comparison of TCP / UDP / naive multicast / ReliCast"))
    e = sub.add_parser("experiments", help="full sweeps -> results/experiments.json")
    e.add_argument("--size-kb", type=int, default=512)
    e.add_argument("--reps", type=int, default=3)
    s = sub.add_parser("send", help="send a real file to receivers on the LAN / hotspot (terminal version)")
    s.add_argument("file")
    s.add_argument("--mode", choices=engine.MODES, default="relicast")
    s.add_argument("--rate-mbps", type=float, default=8.0)
    rc = sub.add_parser("receive", help="discover a sender on the LAN and receive its file")
    rc.add_argument("--host")
    rc.add_argument("--port", type=int)
    rc.add_argument("--out", default=None)
    r = sub.add_parser("recv", help="receiver process")
    r.add_argument("--host", required=True)
    r.add_argument("--port", type=int, required=True)
    r.add_argument("--rid", type=int, default=1)
    r.add_argument("--loss", type=float, default=0.0)
    r.add_argument("--seed", type=int, default=1)
    r.add_argument("--skew-ms", type=float, default=0.0)
    r.add_argument("--iface", default=None)
    r.add_argument("--out", default=None)
    argv = sys.argv[1:]
    if argv and argv[0].startswith("-") and argv[0] not in ("-h", "--help"):
        argv = ["dashboard"] + argv  # e.g. `python run.py --lan`
    a = ap.parse_args(argv)

    if a.cmd == "recv":
        from .receiver import Receiver
        iface = a.iface or net.pick_interface()
        Receiver(a.host, a.port, a.rid, a.loss, a.seed, a.skew_ms, iface, out_dir=a.out).run()
    elif a.cmd == "demo":
        t = Tee(os.path.join(RESULTS, "console_demo.txt"))
        cmd_demo(a, t)
        t.close()
    elif a.cmd == "experiments":
        t = Tee(os.path.join(RESULTS, "experiments_log.txt"))
        engine.run_experiments(os.path.join(RESULTS, "experiments.json"), a.size_kb, a.reps, t)
        t.close()
        a.receivers, a.loss, a.shared, a.size_kb, a.seed = 6, 0.08, 0.03, 512, 7
        t = Tee(os.path.join(RESULTS, "console_demo.txt"))
        cmd_demo(a, t)
        t.close()
    elif a.cmd == "send":
        cmd_send(a)
    elif a.cmd == "receive":
        cmd_receive(a)
    else:  # dashboard (default)
        from . import dashboard
        dashboard.serve(port=getattr(a, "port", 8765), open_browser=not getattr(a, "no_browser", False),
                        lan=getattr(a, "lan", False))

"""Generate all PNG charts and diagrams into results/figs/.  usage: make_charts.py [experiments.json]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Circle, Polygon, FancyArrowPatch
import numpy as np
from common import *

plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.25, "figure.dpi": 100, "savefig.dpi": 200, "savefig.bbox": "tight"})
SAVED = []


def save(fig, name):
    p = os.path.join(FIGS, name)
    fig.savefig(p, facecolor="white")
    plt.close(fig)
    SAVED.append(p)


def lines(ax, xs, fn, field_fmt=None, logx=False):
    for m in MODES:
        ys = [fn(m, x) for x in xs]
        ax.plot(xs, ys, marker="o", lw=2.4 if m == "relicast" else 1.8, color=COLOR[m], label=LABEL[m], zorder=3 if m == "relicast" else 2)


def charts(D):
    ns, ls = D.ns(), D.losses()
    n0, l0, s0 = D.demo_params()
    # 1 duration vs receivers
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    lines(ax, ns, lambda m, x: D.sn(m, x, "duration_s"))
    ax.set_xlabel("Number of receivers N"); ax.set_ylabel("Transfer duration (s)"); ax.set_xscale("log", base=2); ax.set_xticks(ns); ax.set_xticklabels(ns)
    ax.set_title("Transfer duration vs. number of receivers"); ax.legend(frameon=False)
    save(fig, "duration_vs_receivers.png")
    # 2 overhead vs receivers
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    lines(ax, ns, lambda m, x: D.sn(m, x, "overhead_ratio"))
    ax.set_xlabel("Number of receivers N"); ax.set_ylabel("Overhead ratio (total bytes / file size)"); ax.set_xscale("log", base=2); ax.set_xticks(ns); ax.set_xticklabels(ns)
    ax.set_title("Network overhead vs. number of receivers"); ax.legend(frameon=False)
    save(fig, "overhead_vs_receivers.png")
    # 3 duration vs loss
    pc = [x * 100 for x in ls]
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    lines(ax, pc, lambda m, x: D.sl(m, x / 100, "duration_s"))
    ax.set_xlabel("Per-receiver loss (%)"); ax.set_ylabel("Transfer duration (s)"); ax.set_title("Transfer duration vs. packet loss (N = %d)" % (D.sweep_l[0]["n"] if D.sweep_l else 8)); ax.legend(frameon=False)
    save(fig, "duration_vs_loss.png")
    # 4 delivery vs loss
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    lines(ax, pc, lambda m, x: D.sl(m, x / 100, "delivery_ratio") * 100)
    ax.set_xlabel("Per-receiver loss (%)"); ax.set_ylabel("Delivery ratio (%)"); ax.set_ylim(70, 102); ax.set_title("Delivery ratio vs. packet loss"); ax.legend(frameon=False, loc="lower left")
    save(fig, "delivery_vs_loss.png")
    # 5 NACK comparison at demo point
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    ms = [m for m in ["naive", "relicast"] if m in D.demo]
    x = np.arange(len(ms)); w = 0.26
    for i, (f, lab, hatch) in enumerate([("nack_packets", "NACKs sent", ""), ("nack_suppressed", "NACKs suppressed", "//"), ("repair_packets", "Repair packets", "..")]):
        vals = [D.d(m, f) for m in ms]
        bars = ax.bar(x + (i - 1) * w, vals, w, color=[COLOR[m] for m in ms], hatch=hatch, edgecolor="white", alpha=0.95 - 0.2 * i, label=lab)
        for b, v in zip(bars, vals): ax.text(b.get_x() + b.get_width() / 2, v, str(v), ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels([LABEL[m] for m in ms]); ax.set_ylabel("Packets (total over receivers)")
    ax.set_title("Feedback traffic at the demo point (N=%d, loss=%g%%)" % (n0, l0 * 100))
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(facecolor="#888", hatch=h, edgecolor="white", label=l) for h, l in [("", "NACKs sent"), ("//", "NACKs suppressed"), ("..", "Repair packets")]], frameon=False)
    save(fig, "nack_comparison.png")
    # 6 OWD / jitter
    fig, axs = plt.subplots(1, 2, figsize=(7.6, 3.6))
    xs = np.arange(len(MODES))
    for ax, fields, title in [(axs[0], [("owd_mean_ms", "mean"), ("owd_p95_ms", "p95")], "One-way delay (SNTP-corrected)"), (axs[1], [("jitter_ms", "jitter")], "Delay jitter")]:
        k = len(fields); w = 0.8 / k
        for j, (f, lab) in enumerate(fields):
            vals = [D.d(m, f) for m in MODES]
            bars = ax.bar(xs + (j - (k - 1) / 2) * w, vals, w, color=[COLOR[m] for m in MODES], alpha=1.0 if j == 0 else 0.55, edgecolor="white")
            for b, v in zip(bars, vals): ax.text(b.get_x() + b.get_width() / 2, v, "%.2f" % v, ha="center", va="bottom", fontsize=7)
        ax.set_xticks(xs); ax.set_xticklabels(["TCP", "UDP", "Naive", "ReliCast"]); ax.set_ylabel("ms"); ax.set_title(title, fontsize=10)
    axs[0].text(0.02, 0.95, "solid = mean, light = p95", transform=axs[0].transAxes, fontsize=8, va="top", color="#555")
    fig.tight_layout(); save(fig, "owd_jitter.png")
    # 7 SNTP skew vs estimate
    r = D.demo.get("relicast") or next(iter(D.demo.values()))
    fig, axs = plt.subplots(1, 2, figsize=(7.6, 3.6))
    sk, of = np.array(r["skews_ms"]), np.array(r["sntp_offsets_ms"])
    lim = max(abs(sk).max(), abs(of).max()) * 1.1
    axs[0].plot([-lim, lim], [-lim, lim], "--", color="#999", label="ideal y = x")
    axs[0].scatter(sk, of, s=60, color=COLOR["relicast"], zorder=3, label="receivers")
    axs[0].set_xlabel("Injected clock skew (ms)"); axs[0].set_ylabel("SNTP-estimated offset (ms)"); axs[0].set_title("SNTP estimate vs. true skew", fontsize=10); axs[0].legend(frameon=False)
    err = np.abs(of - sk)
    axs[1].bar(["Raw\n(no sync)", "SNTP-\ncorrected"], [abs(r["owd_raw_mean_ms"]), r["owd_mean_ms"]], color=["#9ca3af", COLOR["relicast"]])
    axs[1].set_yscale("log"); axs[1].set_ylabel("Mean |OWD| (ms, log scale)"); axs[1].set_title("Effect of clock correction (max err %.2f ms)" % err.max(), fontsize=10)
    for i, v in enumerate([abs(r["owd_raw_mean_ms"]), r["owd_mean_ms"]]): axs[1].text(i, v, "%.2f" % v, ha="center", va="bottom", fontsize=9)
    fig.tight_layout(); save(fig, "sntp_skew.png")
    # 8 bytes on wire
    fig, ax = plt.subplots(figsize=(6.4, 3.8))
    vals = [D.d(m, "total_bytes") / 1e6 for m in MODES]
    bars = ax.bar([LABEL[m] for m in MODES], vals, color=[COLOR[m] for m in MODES])
    for b, v, m in zip(bars, vals, MODES): ax.text(b.get_x() + b.get_width() / 2, v, "%.2f MB\n(%.2fx)" % (v, D.d(m, "overhead_ratio")), ha="center", va="bottom", fontsize=8)
    ax.axhline(D.demo["relicast"]["size_bytes"] / 1e6, color="#111", ls=":", lw=1); ax.text(-0.45, D.demo["relicast"]["size_bytes"] / 1e6, "file size", fontsize=8, va="bottom", ha="left", color="#fff")
    ax.set_ylabel("Bytes on the wire (MB)"); ax.set_title("Total bytes on the wire at demo point (N=%d)" % n0); ax.set_ylim(0, max(vals) * 1.2)
    plt.setp(ax.get_xticklabels(), fontsize=8)
    save(fig, "bytes_on_wire.png")


# ------------------------------------------------------------------ diagram helpers
def canvas(w, h, size):
    fig, ax = plt.subplots(figsize=size)
    ax.set_xlim(0, w); ax.set_ylim(0, h); ax.axis("off"); ax.grid(False)
    return fig, ax


def box(ax, x, y, w, h, text, fc="#eef2ff", ec="#4338ca", fs=8.5, bold=False, rounded=True, tc="#111", lw=1.3):
    p = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.02,rounding_size=0.8" if rounded else "square,pad=0", fc=fc, ec=ec, lw=lw, zorder=2)
    ax.add_patch(p)
    ax.text(x + w / 2, y + h / 2, text, ha="center", va="center", fontsize=fs, color=tc, fontweight="bold" if bold else "normal", zorder=3, linespacing=1.25)


def arrow(ax, p, q, color="#374151", style="-|>", ls="-", lw=1.4, rad=0.0, z=4):
    ax.add_patch(FancyArrowPatch(p, q, arrowstyle=style, mutation_scale=11, color=color, lw=lw, ls=ls, connectionstyle="arc3,rad=%g" % rad, zorder=z))


def diagrams():
    # ---- architecture
    fig, ax = canvas(120, 70, (10.5, 6.2))
    ax.add_patch(FancyBboxPatch((1, 4), 38, 62, boxstyle="round,pad=0.02,rounding_size=1.5", fc="#f0fdf4", ec="#16a34a", lw=2)); ax.text(20, 63, "SENDER PROCESS", ha="center", fontsize=11, fontweight="bold", color="#15803d")
    sb = [("File chunker\n+ SHA-256 (1 KB chunks)", 53), ("Link-rate pacer\n(pkts/s, flow control)", 43.5), ("Multicast TX socket\nDATA / REPAIR / HEARTBEAT / FIN", 34), ("Repair aggregator\n10 ms hold-off, union of ranges", 24.5), ("TCP control listener\nmeta JSON, final stats", 15), ("SNTP server (UDP)\nRFC 4330", 6)]
    for t, y in sb: box(ax, 5, y - 1, 30, 7.2, t, fc="#dcfce7", ec="#16a34a", fs=8)
    ax.add_patch(FancyBboxPatch((46, 6), 28, 58, boxstyle="round,pad=0.02,rounding_size=1.5", fc="#f8fafc", ec="#64748b", lw=1.5, ls="--")); ax.text(60, 61, "LAN / IP MULTICAST", ha="center", fontsize=10, fontweight="bold", color="#475569")
    box(ax, 49, 44, 22, 11, "UDP multicast group\n239.255.42.99:port\n(1 copy, TTL = 1)", fc="#fef3c7", ec="#d97706", fs=8.5)
    box(ax, 49, 28, 22, 9, "NACK feedback\n(multicast, heard by all\nreceivers + sender)", fc="#fee2e2", ec="#dc2626", fs=8)
    box(ax, 49, 14, 22, 9, "TCP control channel\n(unicast, per receiver)", fc="#e5e7eb", ec="#6b7280", fs=8.5)
    box(ax, 49, 7.5, 22, 4.5, "SNTP over UDP", fc="#e0e7ff", ec="#4338ca", fs=8)
    for k, y0 in enumerate([40, 18]):
        pass
    ax.add_patch(FancyBboxPatch((81, 4), 38, 62, boxstyle="round,pad=0.02,rounding_size=1.5", fc="#eff6ff", ec="#2563eb", lw=2)); ax.text(100, 63, "RECEIVER PROCESS 1 .. N", ha="center", fontsize=11, fontweight="bold", color="#1d4ed8")
    rb = [("Metrics: OWD, jitter,\nNACK / dup counters", 53), ("Multicast RX socket\nIP_ADD_MEMBERSHIP, SO_RCVBUF", 43.5), ("Gap detector\n(seq jump / heartbeat)", 34), ("NACK timer + suppression\nT ~ U[0, W), back-off", 24.5), ("Reassembler\n+ SHA-256 verify", 15), ("SNTP client\n5 samples, min-delay", 6)]
    for t, y in rb: box(ax, 85, y - 1, 30, 7.2, t, fc="#dbeafe", ec="#2563eb", fs=8)
    arrow(ax, (35, 37), (49, 49)); arrow(ax, (71, 49), (85, 47)); arrow(ax, (85, 28), (71, 32)); arrow(ax, (49, 30), (35, 29), color="#dc2626")
    arrow(ax, (35, 18), (49, 18.5), style="<|-|>"); arrow(ax, (71, 18.5), (85, 18), style="<|-|>"); arrow(ax, (35, 9), (49, 9.5), style="<|-|>"); arrow(ax, (71, 9.5), (85, 9), style="<|-|>")
    ax.text(60, 1.5, "Application Layer Framing: each datagram = 24-byte header + 1 KB chunk, independently decodable", ha="center", fontsize=8.5, style="italic", color="#475569")
    save(fig, "arch_diagram.png")

    # ---- sequence diagram
    fig, ax = canvas(100, 100, (8.2, 9.4))
    xs = {"S": 14, "G": 50, "R": 86}
    names = {"S": "Sender", "G": "Multicast group\n(other receivers)", "R": "Receiver k"}
    for k, x in xs.items():
        box(ax, x - 11, 92, 22, 6, names[k], fc="#e0e7ff", ec="#4338ca", fs=9, bold=True)
        ax.plot([x, x], [2, 92], color="#9ca3af", lw=1, ls="--", zorder=1)
    msgs = [("R", "S", 87, "1. TCP connect to control port", "#6b7280"), ("S", "R", 82, "2. meta JSON (id, size, chunks, sha256, group, sntp_port)", "#6b7280"),
            ("R", "S", 77, "3. SNTP request  (t1)", "#4338ca"), ("S", "R", 73, "4. SNTP reply (t2, t3) -> offset, delay", "#4338ca"),
            ("R", "G", 68, "5. IP_ADD_MEMBERSHIP (IGMP join)", "#d97706"), ("R", "S", 63, "6. TCP {ready:true, rid, udp_port}", "#6b7280"),
            ("S", "G", 57, "7. DATA seq 0..C-1 (paced multicast)", "#16a34a"), ("S", "G", 52, "8. HEARTBEAT (highest seq)", "#16a34a"),
            ("R", "G", 45, "9. random timer T in [0, W) -> NACK ranges", "#dc2626"), ("G", "R", 40.5, "(overheard NACK -> others suppress)", "#dc2626"),
            ("G", "S", 36, "10. NACK arrives; 10 ms hold-off, union", "#dc2626"), ("S", "G", 30, "11. REPAIR for union of missing ranges", "#16a34a"),
            ("R", "R", 24, "12. all chunks present -> verify SHA-256", "#111"), ("R", "S", 19, "13. TCP final stats JSON (recv, dups, nacks, OWD)", "#6b7280"),
            ("S", "G", 13, "14. FIN (multicast), close TCP", "#16a34a")]
    for a, b, y, t, c in msgs:
        if a == b:
            box(ax, xs[a] - 24, y - 2.2, 34, 4.4, t, fc="#fff", ec="#111", fs=7.4, rounded=True); continue
        dashed = "--" if t.startswith("(") else "-"
        arrow(ax, (xs[a], y), (xs[b], y), color=c, ls=dashed)
        ax.text((xs[a] + xs[b]) / 2, y + 1.2, t, ha="center", va="bottom", fontsize=7.6, color=c, bbox=dict(fc="white", ec="none", pad=0.6))
    ax.text(50, 96.5 + 0.1, "", fontsize=1)
    save(fig, "sequence_diagram.png")

    # ---- NACK timer flowchart
    fig, ax = canvas(110, 130, (7.4, 8.6))
    def dia(x, y, w, h, t):
        ax.add_patch(Polygon([(x, y + h / 2), (x + w / 2, y + h), (x + w, y + h / 2), (x + w / 2, y)], fc="#fef3c7", ec="#d97706", lw=1.3, zorder=2))
        ax.text(x + w / 2, y + h / 2, t, ha="center", va="center", fontsize=7.8, zorder=3)
    cx = 50; hw = 24
    box(ax, cx - hw, 120, 2 * hw, 8, "Gap detected:\nseq jump or HEARTBEAT > highest", fc="#dbeafe", ec="#2563eb", fs=8)
    box(ax, cx - hw, 105, 2 * hw, 9, "Compute missing ranges M;\nW = clamp(20 + 4(owd + 4 jit), 20, 200) ms", fc="#dbeafe", ec="#2563eb", fs=7.6)
    box(ax, cx - hw, 90, 2 * hw, 9, "Arm timer: T = U[0,1) * W * 2^k\n(k = retry count)", fc="#dbeafe", ec="#2563eb", fs=8)
    dia(cx - 20, 71, 40, 14, "NACK for a superset of M\nheard before T expires?")
    box(ax, cx - hw, 54, 2 * hw, 8, "T expires: multicast NACK(M)", fc="#fee2e2", ec="#dc2626", fs=8.3)
    dia(cx - 20, 34, 40, 14, "Still missing after\nrepair guard (30 ms)?")
    box(ax, cx - hw, 18, 2 * hw, 8, "Done: all chunks received\n-> verify SHA-256", fc="#dcfce7", ec="#16a34a", fs=8.3)
    box(ax, 78, 73, 30, 12, "Suppress: cancel timer,\nnack_suppressed += 1,\nk = k + 1, re-arm", fc="#fef9c3", ec="#ca8a04", fs=7.6)
    arrow(ax, (cx, 120), (cx, 114)); arrow(ax, (cx, 105), (cx, 99)); arrow(ax, (cx, 90), (cx, 85))
    arrow(ax, (cx, 71), (cx, 62)); ax.text(cx + 1.5, 66.5, "no", fontsize=8)
    arrow(ax, (cx + 20, 78), (78, 79)); ax.text(cx + 21, 80.5, "yes", fontsize=8)
    ax.plot([93, 93, cx + hw + 0.5], [85, 96, 96], color="#374151", lw=1.4, zorder=4); arrow(ax, (cx + hw + 4, 96), (cx + hw, 96))
    arrow(ax, (cx, 54), (cx, 48)); arrow(ax, (cx, 34), (cx, 26)); ax.text(cx + 1.5, 29.5, "no", fontsize=8)
    ax.plot([cx - 20, 8, 8, cx - hw - 4], [41, 41, 94, 94], color="#374151", lw=1.4, zorder=4); arrow(ax, (cx - hw - 4, 94), (cx - hw, 94))
    ax.text(9.5, 43, "yes: k = k + 1, re-arm", fontsize=8)
    save(fig, "nack_flowchart.png")

    # ---- receiver state diagram
    fig, ax = canvas(130, 50, (10.2, 3.9))
    st = [("CONNECT\n(TCP meta)", 8), ("SYNC\n(SNTP)", 30), ("JOINED\n(IGMP join,\nready)", 52), ("RECEIVING\n(DATA)", 74), ("REPAIRING\n(NACK timers)", 96), ("VERIFY\n(SHA-256)", 116)]
    cols = ["#e5e7eb", "#e0e7ff", "#fef3c7", "#dcfce7", "#fee2e2", "#dbeafe"]
    for (t, x), c in zip(st, cols):
        ax.add_patch(Circle((x, 25), 8.2, fc=c, ec="#374151", lw=1.4, zorder=2)); ax.text(x, 25, t, ha="center", va="center", fontsize=7.6, zorder=3)
    for (_, a), (_, b) in zip(st[:-1], st[1:]): arrow(ax, (a + 8.2, 25), (b - 8.2, 25))
    for x, t in [(19, "meta"), (41, "offset"), (63, "all N ready"), (85, "gap seen"), (106, "complete")]: ax.text(x, 36, t, ha="center", fontsize=7.5, color="#374151")
    arrow(ax, (92, 31.5), (78, 31.5), rad=0.5, color="#16a34a"); ax.text(85, 43, "repair received,\nno gap", ha="center", fontsize=7.5, color="#16a34a")
    arrow(ax, (100, 17), (92, 17), rad=-1.6, color="#dc2626"); ax.text(96, 5.5, "retry (back-off 2^k)", ha="center", fontsize=7.5, color="#dc2626")
    ax.add_patch(Circle((124.5, 25), 2.5, fc="#111", ec="#111")) if False else None
    save(fig, "state_diagram.png")

    # ---- discovery diagram (UDP broadcast beacons)
    fig, ax = canvas(120, 56, (9.6, 4.5))
    box(ax, 2, 18, 34, 22, "SENDER\nbeacon thread, every 1 s:\nsendto() JSON beacon\n{name,size,mode,ip:port}\nsocket has SO_BROADCAST", fc="#dcfce7", ec="#16a34a", fs=8, bold=False)
    ax.add_patch(FancyBboxPatch((46, 6), 30, 44, boxstyle="round,pad=0.02,rounding_size=1.5", fc="#fef3c7", ec="#d97706", lw=1.6, ls="--"))
    ax.text(61, 46, "UDP BROADCAST", ha="center", fontsize=10, fontweight="bold", color="#b45309")
    for y, t in [(36, "255.255.255.255:5599"), (28, "subnet x.y.z.255:5599"), (20, "127.0.0.1:5599 (same host)")]:
        box(ax, 49, y - 3, 24, 6, t, fc="#fffbeb", ec="#d97706", fs=7.5); arrow(ax, (36, 29), (49, y), color="#d97706")
    for i, nm in enumerate(["Receiver A", "Receiver B", "Receiver C"]):
        y = 38 - i * 14
        box(ax, 86, y - 4, 32, 9, nm + "\nbind(:5599) SO_REUSEADDR\nlist beacons seen < 4 s", fc="#dbeafe", ec="#2563eb", fs=7.5)
        arrow(ax, (73, 28), (86, y), color="#d97706")
    ax.text(60, 2, "Receiver picks a beacon, then opens TCP to ip:port from it (TCP lobby protocol)", ha="center", fontsize=8.5, style="italic", color="#475569")
    save(fig, "discovery_diagram.png")

    # ---- lobby / probe / fallback sequence
    fig, ax = canvas(120, 100, (9.4, 7.0))
    xs = {"S": 14, "A": 60, "B": 106}
    names = {"S": "Sender", "A": "Receiver A\n(multicast works)", "B": "Receiver B\n(multicast blocked)"}
    for k, x in xs.items():
        box(ax, x - 13, 92, 26, 7, names[k], fc="#e0e7ff", ec="#4338ca", fs=8.5, bold=True)
        ax.plot([x, x], [2, 92], color="#9ca3af", lw=1, ls="--", zorder=1)
    steps = [("S", "B", 87, "1. UDP broadcast beacon :5599 (heard by A and B)", "#d97706"), ("A", "S", 81, "2. TCP connect + meta; {ready, rid}", "#6b7280"),
             ("B", "S", 76, "2. TCP connect + meta; {ready, rid}", "#6b7280"), ("S", "S", 70, "3. user presses Start (lobby closes)", None),
             ("S", "A", 64, "4. {cmd: probe} on TCP; 10 PROBE datagrams to group", "#4338ca"), ("A", "S", 58, "5. {mcast_ok: true}", "#16a34a"),
             ("B", "S", 53, "5. no PROBE heard: timeout -> mcast_ok = false", "#dc2626"), ("S", "A", 46, "6. {cmd: start, transport: mcast}", "#16a34a"),
             ("S", "B", 41, "6. {cmd: start, transport: tcp}", "#6b7280"), ("S", "A", 34, "7. DATA / REPAIR multicast, NACK repair as in Fig 7.3", "#16a34a"),
             ("S", "B", 28, "7. same file over a TCP stream", "#6b7280"), ("A", "S", 21, "8. {progress} / {done, sha256 ok}", "#16a34a"),
             ("B", "S", 16, "8. {progress} / {done, sha256 ok}", "#6b7280"), ("S", "S", 9, "9. SHA-256 verified -> saved to ~/ReliCast/received", None)]
    for a, b_, y, t, c in steps:
        if a == b_:
            box(ax, xs[a] - 12, y - 2.6, 56, 5.2, t, fc="#fff", ec="#111", fs=7.8); continue
        arrow(ax, (xs[a], y), (xs[b_], y), color=c)
        ax.text((xs[a] + xs[b_]) / 2, y + 1.0, t, ha="center", va="bottom", fontsize=7.4, color=c, bbox=dict(fc="white", ec="none", pad=0.5))
    save(fig, "lobby_sequence.png")

    # ---- packet format
    fig, ax = canvas(100, 26, (9, 2.6))
    fields = [("magic\n'RC'", 2, "#e0e7ff"), ("type", 1, "#fef3c7"), ("flags", 1, "#fef3c7"), ("session id", 4, "#dcfce7"), ("seq", 4, "#dcfce7"), ("total", 4, "#dcfce7"), ("ts_us\n(SNTP-corrected sender time)", 8, "#fee2e2"), ("payload (<=1024 B chunk / NACK ranges)", 12, "#f3f4f6")]
    wts = [3, 2, 2, 4, 4, 4, 8, 12]; tot = sum(wts); x = 1
    for (t, w, c), wt in zip(fields, wts):
        ww = 98 * wt / tot
        box(ax, x, 6, ww, 12, t, fc=c, ec="#374151", fs=7 if w > 2 else 6.5, rounded=False); ax.text(x + ww / 2, 3, "%d B" % w if w < 12 else "variable", ha="center", fontsize=6.5, color="#555"); x += ww
    ax.text(50, 22, "ReliCast packet: 24-byte fixed header (network byte order, struct '!2sBBIIIQ') + payload", ha="center", fontsize=8.5, fontweight="bold")
    save(fig, "packet_format.png")


def main(path=None):
    D = Data(path)
    prep_screens(); charts(D); diagrams()
    print("charts:", len(SAVED), "->", FIGS)
    return SAVED


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)

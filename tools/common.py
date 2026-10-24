"""Shared helpers for the ReliCast documentation generators."""
import json, os, statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # .../relicast
RESULTS = os.path.join(ROOT, "results")
FIGS = os.path.join(RESULTS, "figs")
ASSETS = os.path.join(ROOT, "assets")
MODES = ["tcp", "udp", "naive", "relicast"]
LABEL = {"tcp": "TCP unicast", "udp": "Raw UDP unicast", "naive": "Naive multicast+NACK", "relicast": "ReliCast"}
COLOR = {"tcp": "#6b7280", "udp": "#d97706", "naive": "#dc2626", "relicast": "#16a34a"}
os.makedirs(FIGS, exist_ok=True)


def default_data_path():
    p = os.path.join(RESULTS, "experiments.json")
    return p if os.path.exists(p) else os.path.join(RESULTS, "experiments.sample.json")


def default_console_path():
    p = os.path.join(RESULTS, "console_demo.txt")
    return p if os.path.exists(p) else os.path.join(RESULTS, "console_demo.sample.txt")


def load_team():
    with open(os.path.join(ROOT, "team.json"), encoding="utf-8") as f:
        return json.load(f)


class Data:
    def __init__(self, path=None):
        self.path = path or default_data_path()
        with open(self.path, encoding="utf-8") as f:
            self.raw = json.load(f)
        self.meta = self.raw.get("meta", {})
        self.sweep_n = self.raw.get("sweep_receivers", [])
        self.sweep_l = self.raw.get("sweep_loss", [])
        self.demo = self.raw.get("demo", {})
        self.is_sample = "sample" in os.path.basename(self.path)

    # ---- aggregation
    def _rows(self, rows, mode, key, val):
        return [r for r in rows if r["mode"] == mode and abs(r[key] - val) < 1e-9]

    def mean(self, rows, mode, key, val, field):
        rs = self._rows(rows, mode, key, val)
        return statistics.mean(r[field] for r in rs) if rs else float("nan")

    def sn(self, mode, n, field):
        return self.mean(self.sweep_n, mode, "n", n, field)

    def sl(self, mode, loss, field):
        return self.mean(self.sweep_l, mode, "loss", loss, field)

    def ns(self):
        return sorted({r["n"] for r in self.sweep_n})

    def losses(self):
        return sorted({r["loss"] for r in self.sweep_l})

    def d(self, mode, field):
        return self.demo[mode][field]

    def demo_params(self):
        r = self.demo.get("relicast") or next(iter(self.demo.values()))
        return r["n"], r["loss"], r["shared_loss"]


def summary_text(D):
    """Plain-text results summary (rendered as an 'output screenshot')."""
    n, loss, sh = D.demo_params()
    L = []
    m = D.meta
    L.append("ReliCast experiment summary   (%s, %s, python %s)" % (m.get("date", "?"), m.get("platform", "?"), m.get("python", "?")))
    L.append("file=%d KB  chunk=%d B  link=%s pkt/s  reps=%s  iface=%s" % (m.get("size_kb", 0), m.get("chunk", 0), m.get("link_pps"), m.get("reps"), m.get("interface")))
    L.append("")
    L.append("== Sweep 1: receivers (loss=5%, shared=2%) -- mean duration s / overhead ratio ==")
    ns = D.ns()
    L.append("%-10s" % "mode" + "".join("  N=%-11d" % x for x in ns))
    for mo in MODES:
        L.append("%-10s" % mo + "".join("  %5.2fs/%-5.2fx" % (D.sn(mo, x, "duration_s"), D.sn(mo, x, "overhead_ratio")) for x in ns))
    L.append("")
    L.append("== Sweep 2: loss (N=8) -- mean duration s / delivery ratio ==")
    ls = D.losses()
    L.append("%-10s" % "mode" + "".join("  p=%-10s" % ("%g%%" % (x * 100)) for x in ls))
    for mo in MODES:
        L.append("%-10s" % mo + "".join("  %5.2fs/%-5.3f" % (D.sl(mo, x, "duration_s"), D.sl(mo, x, "delivery_ratio")) for x in ls))
    L.append("")
    L.append("== Demo point: N=%d loss=%g%% shared=%g%% ==" % (n, loss * 100, sh * 100))
    L.append("%-9s %7s %7s %8s %6s %6s %7s %8s %8s" % ("mode", "dur(s)", "ovhd", "deliv", "nack", "supp", "repair", "owd(ms)", "jit(ms)"))
    for mo in MODES:
        if mo in D.demo:
            r = D.demo[mo]
            L.append("%-9s %7.2f %6.2fx %8.3f %6d %6d %7d %8.2f %8.3f" % (mo, r["duration_s"], r["overhead_ratio"], r["delivery_ratio"], r["nack_packets"], r["nack_suppressed"], r["repair_packets"], r["owd_mean_ms"], r["jitter_ms"]))
    return "\n".join(L)


def prep_screens():
    """Crop the tall dashboard screenshots to their content -> results/figs/<name>_c.png."""
    from PIL import Image, ImageChops
    limits = {"dash_live": 1120, "dash_send": 760, "dash_sweep": 1100}
    for n, lim in limits.items():
        src = os.path.join(FIGS, n + ".png")
        if not os.path.exists(src):
            continue
        im = Image.open(src).convert("RGB")
        bg = Image.new("RGB", im.size, im.getpixel((5, im.height - 5)))
        bbox = ImageChops.difference(im, bg).getbbox()
        bottom = min(lim, (bbox[3] + 14) if bbox else im.height, im.height)
        im.crop((0, 0, im.width, bottom)).save(os.path.join(FIGS, n + "_c.png"))


def live_facts():
    """Numbers parsed from results/live_console.txt (None if missing)."""
    import re
    p = os.path.join(RESULTS, "live_console.txt")
    if not os.path.exists(p):
        return None
    t = open(p, encoding="utf-8", errors="replace").read()
    g = lambda pat, cast=float: (cast(re.search(pat, t).group(1)) if re.search(pat, t) else None)
    return {"size_mb": g(r"\(([\d.]+) MB\)"), "secs": g(r"Finished in ([\d.]+)s"), "bytes_mb": g(r"sender bytes ([\d.]+) MB"),
            "nacks": g(r"NACKs (\d+)", int), "repairs": g(r"repairs (\d+)", int), "joined": g(r"receivers joined: (\d+)", int),
            "verified": "all verified: True" in t, "same_sha": len(set(re.findall(r"^([0-9a-f]{64})", t, re.M))) == 1}

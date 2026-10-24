"""Generate a SYNTHETIC, schema-identical experiments.sample.json (+ console_demo.sample.txt).
Only used until the real results/experiments.json exists."""
import json, math, os, random, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import RESULTS, MODES

SIZE_KB, CHUNK, PPS, REPS = 512, 1024, 4000, 3
SIZE = SIZE_KB * 1024
C = math.ceil(SIZE / CHUNK)
WIRE = CHUNK + 24 + 28


def one(mode, n, loss, sh, rep, rng):
    j = lambda x, s=0.06: x * (1 + rng.uniform(-s, s))
    pe = sh + (1 - sh) * loss if mode in ("tcp", "udp") else loss
    pm = sh + (1 - sh) * loss                      # effective per-receiver miss prob (multicast)
    r = dict(mode=mode, n=n, loss=loss, shared_loss=sh, size_bytes=SIZE, chunk=CHUNK, chunks=C, seed=rep + 1, rep=rep)
    nack = supp = rep_pk = dup = 0
    if mode == "tcp":
        retx = C * n * pe
        dur = j(n * C / PPS + retx * 0.020 / max(1, n) * 0.5 + 0.05)
        sb = (C * n + retx) * (CHUNK + 24 + 40)
        dp, deliv, hb = C * n, 1.0, 0
        nb = 0
    elif mode == "udp":
        dur = j(n * C / PPS + 0.03)
        sb = C * n * WIRE
        dp, deliv, hb = C * n, (1 - pe), 0
        nb = 0
    else:
        lost_any = 1 - (1 - sh) * (1 - loss) ** n
        miss = C * n * pm
        if mode == "naive":
            nack = int(j(miss * 1.9 + 3 * n, 0.1)); supp = 0
            rep_pk = int(j(nack * 1.0 + 1, 0.1)); dup = int(rep_pk - miss * 0.6) if rep_pk > miss * 0.6 else 0
            dur = j(C / PPS + 0.08 * 2 + rep_pk / PPS * 1.2 + 0.03 * n / 8)
        else:
            nack = int(j(max(1, C * lost_any * (0.3 + 0.01 * n)), 0.1)); supp = int(j(max(0, miss - nack) * 0.8, 0.1))
            rep_pk = int(j(C * lost_any * 1.08 + 1, 0.06)); dup = int(j(miss * 0.04 + 1, 0.2))
            dur = j(C / PPS + 0.07 + rep_pk / PPS + 0.025)
        dp, deliv, hb = C, 1.0, int(dur * 12)
        sb = (dp + rep_pk + hb + 1) * WIRE
        nb = nack * (24 + 28 + 8 + 8 * 3)
    if mode in ("tcp", "udp"):
        nb = 0
    total = sb + nb
    gp = n * SIZE * 8 * deliv / dur / 1e6
    skews = [round(rng.choice([-1, 1]) * rng.uniform(100, 500), 1) for _ in range(n)]
    offs = [round(s + rng.gauss(0, 0.08), 2) for s in skews]
    owd = {"tcp": 0.55, "udp": 0.32, "naive": 0.38 + 0.02 * n, "relicast": 0.36}[mode]
    owd = j(owd, 0.15)
    per = []
    for k in range(n):
        comp = deliv >= 0.9999
        per.append(dict(rid=k + 1, complete=comp, time_s=round(dur * rng.uniform(0.9, 1.0), 3), recv=int(C * (1 - pm) + rep_pk / max(1, n)) if mode in ("naive", "relicast") else int(C * deliv),
                        dups=int(dup / n), nacks=int(nack / n), suppressed=int(supp / n), missing_final=0 if comp else int(C * (1 - deliv))))
    r.update(ok=True, all_verified=bool(deliv >= 0.9999), delivery_ratio=round(deliv, 4), duration_s=round(dur, 3), goodput_mbps=round(gp, 2),
             sender_bytes=int(sb), sender_packets=int(dp + rep_pk + hb), data_packets=int(dp), repair_packets=int(rep_pk), heartbeat_packets=int(hb),
             nack_packets=int(nack), nack_suppressed=int(supp), dup_data=int(dup), total_bytes=int(total), overhead_ratio=round(total / SIZE, 3),
             owd_mean_ms=round(owd, 3), owd_p95_ms=round(owd * 2.6, 3), owd_max_ms=round(owd * 11, 3), jitter_ms=round(owd * rng.uniform(0.3, 0.45), 3),
             owd_raw_mean_ms=round(owd + sum(skews) / n, 2), sntp_offsets_ms=offs, skews_ms=skews, per_receiver=per, interface="127.0.0.1")
    return r


def main():
    rng = random.Random(7)
    meta = dict(date="2026-10-20 (SYNTHETIC SAMPLE)", platform="macOS-14-arm64 (sample)", python="3.12", interface="127.0.0.1",
                size_kb=SIZE_KB, chunk=CHUNK, link_pps=PPS, reps=REPS)
    sw = [one(m, n, 0.05, 0.02, rep, rng) for m in MODES for n in [1, 2, 4, 8, 16] for rep in range(REPS)]
    sl = [one(m, 8, p, 0.0, rep, rng) for m in MODES for p in [0, 0.01, 0.02, 0.05, 0.10, 0.20] for rep in range(REPS)]
    demo = {m: one(m, 6, 0.08, 0.03, 0, rng) for m in MODES}
    out = dict(meta=meta, sweep_receivers=sw, sweep_loss=sl, demo=demo)
    json.dump(out, open(os.path.join(RESULTS, "experiments.sample.json"), "w"), indent=1)
    L = ["$ python run.py demo --receivers 6 --loss 0.08 --shared-loss 0.03", "[sample console output - synthetic]",
         "ReliCast demo  file=512 KB  chunks=%d  group=239.255.42.99  iface=127.0.0.1" % C, ""]
    for m in MODES:
        r = demo[m]
        L += ["[%s] starting transfer to 6 receivers ..." % m, "  SNTP: offsets(ms)=%s" % ", ".join("%.1f" % x for x in r["sntp_offsets_ms"]),
              "  done in %.2fs  delivery=%.3f  verified=%s" % (r["duration_s"], r["delivery_ratio"], r["all_verified"]),
              "  sender_bytes=%d  nack=%d suppressed=%d repair=%d  overhead=%.2fx" % (r["sender_bytes"], r["nack_packets"], r["nack_suppressed"], r["repair_packets"], r["overhead_ratio"]), ""]
    open(os.path.join(RESULTS, "console_demo.sample.txt"), "w").write("\n".join(L))
    print("sample written")


if __name__ == "__main__":
    main()

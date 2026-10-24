# ReliCast – design + shared contracts (source of truth for all components)

**Title:** ReliCast: NACK-Suppressed Reliable Multicast for LAN Content Distribution with SNTP-Synchronised Measurement
**Course:** Network Programming (23CS7PCNWP), BMSCE CSE, 2026-27. Guide: Dr. Anitha H M. Python 3.8+, stdlib only for the app; works on Windows/macOS/Linux.

## Use case
A teacher / admin pushes a file (slides, update package) to many laptops on one LAN. TCP-to-each costs N× sender traffic; raw UDP multicast is cheap but lossy. ReliCast = UDP multicast data + receiver-driven NACK repair, with SRM-style randomized NACK suppression, sender-side repair aggregation, TCP control channel, and SNTP-synchronised one-way-delay/jitter measurement.

## Research basis (the two papers used in the report)
1. S. Floyd, V. Jacobson, C.-G. Liu, S. McCanne, L. Zhang, "A Reliable Multicast Framework for Light-weight Sessions and Application Level Framing," IEEE/ACM Trans. Networking 5(6):784-803, Dec 1997 (SRM). Idea used: receiver-driven repair, randomized timers [0, W) for request, suppression when another receiver's request for the same data is heard, exponential back-off of retry timers.
2. B. Adamson, C. Bormann, M. Handley, J. Macker, "NACK-Oriented Reliable Multicast (NORM) Transport Protocol," RFC 5740, Nov 2009. Idea used: NACK-oriented, sender repair aggregation/hold-off, heartbeat/positive-ack-free design, scalability w.r.t. ACK implosion.
Supporting (cite only briefly, not as deep reviews): RFC 4330 SNTPv4 (D. Mills, 2006) for clock sync; RFC 1112 (Deering, 1989) host multicast.
**Research gap chosen:** SRM/NORM studies are mostly simulator (ns-2) based and do not report real-socket one-way delay/jitter because sender/receiver clocks are unsynchronised; also fixed suppression windows. Gap → implement on real sockets, adaptive window, SNTP-synchronised delay/jitter, compare with TCP-unicast and raw UDP baselines.

## Syllabus mapping (Unit → feature)
U1 sockets, byte order (`struct '!'`), TCP/UDP, buffer sizes (SO_RCVBUF) · U2 TCP control channel (session meta + final stats), socket options SO_REUSEADDR/SO_REUSEPORT/SO_RCVBUF/IP_MULTICAST_TTL/IP_MULTICAST_IF/IP_MULTICAST_LOOP, socket states · U3 UDP data path, lack of flow control (→ sender pacing), select() multiplexing, timeouts · U4/U5 broadcast vs unicast vs multicast comparison, mcast join (IP_ADD_MEMBERSHIP), TTL scope, **SNTP** (RFC 4330 client+server implemented in `clock.py`).

## Architecture
Processes: 1 sender (main process; also runs a tiny SNTP server and TCP control listener) + N receiver **processes** (`python -m relicast recv ...`).
1. Receiver opens TCP to sender control port → sender replies one JSON line (meta: session id, filename, size, chunk size, chunk count, sha256, mode, group, port, sntp_port, params).
2. Receiver SNTP-syncs (5 samples, min-delay sample used; receivers have **injected clock skew** ±100–500 ms to prove sync works), joins multicast group, sends `{"ready":true,"rid":k,"udp_port":p}`.
3. When all N ready, sender transmits at a fixed link rate (pkts/s, models a shared sender uplink; also solves UDP's lack of flow control).
4. Receivers detect gaps (seq jump, or heartbeat carrying highest seq), schedule NACKs, repair, verify SHA-256, send final stats JSON over TCP. Sender multicasts FIN.

Packet header (24 B, network order): magic `RC`(2) type(1) flags(1) session(4) seq(4) total(4) ts_us(8, SNTP-corrected sender time). Types: DATA, REPAIR, HEARTBEAT(seq=highest sent), NACK(payload: rid + list of inclusive seq ranges), FIN, PROBE.

### Modes (all 4 are implemented in `engine.py` and compared in the dashboard)
| mode id | label | transport | reliability | loss model |
|---|---|---|---|---|
| `tcp` | TCP unicast | N real TCP connections, same paced link | kernel TCP; loss emulated at segment level: lost segment re-sent on same stream after a 20 ms stall (documented model) | per-segment Bernoulli |
| `udp` | Raw UDP unicast | N UDP copies | none (shows delivery ratio < 100 %) | per-copy Bernoulli |
| `naive` | Multicast + immediate NACK | 1 multicast copy | NACK sent at once by every receiver, fixed 80 ms retry, no suppression; sender repairs per NACK immediately (NACK/repair implosion) | per-receiver + shared |
| `relicast` | **Proposed** | 1 multicast copy | randomized NACK timer in [0,W), suppression on overheard NACK, exponential back-off, sender repair hold-off 6 ms with union aggregation + 30 ms repair guard; W adapts: W = clamp(10 ms + 3·(owd_ewma+4·jitter), 10, 100 ms) | per-receiver + shared |
Loss parameters: `loss` = independent per-receiver (drop on arrival, applies to DATA/REPAIR/NACK), `shared_loss` = upstream loss (sender skips a first transmission for everybody; multicast modes only; for unicast modes treated as an additional independent per-copy drop probability).

## CONTRACT: engine result (one transfer)
`engine.run_transfer(mode, n, loss, shared_loss, size_kb, seed, on_progress=None) -> dict`
```
{ "mode": "relicast", "n": 6, "loss": 0.05, "shared_loss": 0.02, "size_bytes": 524288, "chunk": 1024, "chunks": 512, "seed": 1,
  "ok": true, "all_verified": true,            # every receiver's SHA-256 matched
  "delivery_ratio": 1.0,                        # mean over receivers of received_chunks/chunks at end
  "duration_s": 1.23,                           # tx start -> last receiver done (or timeout)
  "goodput_mbps": 20.1,                         # n*size*8*delivery / duration / 1e6
  "sender_bytes": 1234567, "sender_packets": 1500,   # on-the-wire (payload+24B hdr+28B IP/UDP; TCP counted as payload+hdr+40)
  "data_packets": 512, "repair_packets": 60, "heartbeat_packets": 25,
  "nack_packets": 14, "nack_suppressed": 31, "dup_data": 12,   # totals across receivers
  "total_bytes": 1250000,                       # sender_bytes + all NACK bytes
  "overhead_ratio": 2.38,                       # total_bytes / size_bytes   (1.0 = ideal single copy)
  "owd_mean_ms": 0.35, "owd_p95_ms": 0.9, "owd_max_ms": 4.2, "jitter_ms": 0.12,   # SNTP-corrected, DATA first transmissions
  "owd_raw_mean_ms": 312.4,                     # same samples WITHOUT sntp correction (shows skew)
  "sntp_offsets_ms": [-312.1, 140.0, ...],      # estimated offset per receiver
  "skews_ms": [-312.0, 140.2, ...],             # injected true skew per receiver
  "per_receiver": [ {"rid":1,"complete":true,"time_s":1.2,"recv":530,"dups":18,"nacks":3,"suppressed":7,"missing_final":0} ... ],
  "interface": "127.0.0.1" }
```
`on_progress(ev)` called ~10 Hz while running:
```
{ "mode":"relicast","elapsed":0.8,"chunks":512,
  "receivers":[{"rid":1,"have":300,"complete":false,"bitmap":"<hex, bit i = chunk i received>"} ...],
  "counters":{"data":512,"repair":20,"heartbeat":10,"nack":5,"suppressed":9,"sender_bytes":123456} }
```
`engine.run_comparison(params, on_progress=None, on_result=None, modes=None) -> dict[mode]=result`; params = {n, loss, shared_loss, size_kb, seed}. Runs modes sequentially; `on_result(mode, result)` after each. Blocking.

## CONTRACT: experiment output
`python run.py experiments` writes `results/experiments.json`:
```
{ "meta": {"date":..., "platform":..., "python":..., "interface":..., "size_kb":512, "chunk":1024, "link_pps":4000, "reps":3},
  "sweep_receivers": [result,...],  # mode in 4 modes, n in [1,2,4,8,16], loss=0.05, shared=0.02, reps (each result has "rep")
  "sweep_loss":      [result,...],  # n=8, loss in [0,0.01,0.02,0.05,0.10,0.20], shared=0.0
  "demo":            {"tcp":result,"udp":result,"naive":result,"relicast":result}  # n=6, loss=0.08, shared=0.03
}
```
and `results/console_demo.txt` (captured terminal output of the demo run).

## Dashboard (frontend) contract
`relicast/dashboard.py` + `relicast/static/dashboard.html` (single file, no CDN, no external assets – must work offline). stdlib `http.server` (ThreadingHTTPServer).
- `GET /` → html. `GET /api/state` → `{"phase":"idle|running|done|error","message":"","params":{...},"current_mode":"relicast","live":<last on_progress ev or null>,"results":{mode:result},"order":["tcp","udp","naive","relicast"]}`
- `POST /api/run` JSON `{n, loss, shared_loss, size_kb, modes?}` → starts `engine.run_comparison` in a background thread (409 if running) → `{"started":true}`.
- `GET /api/experiments` → contents of results/experiments.json (or `{}`) so the dashboard can also show the pre-computed sweeps.
`dashboard.serve(host="127.0.0.1", port=8765, open_browser=True)`.
UI: controls (receivers slider 1–32, loss %, shared loss %, file KB, Run button), live chunk-map per receiver for the running mode (grid cells), counters; after run, **side-by-side comparison of TCP vs UDP vs Naive vs ReliCast**: bar charts for duration, sender bytes / overhead ratio, NACK packets, delivery ratio, OWD/jitter, repair packets; a results table; "Sweep" tab drawing line charts from /api/experiments (duration & overhead vs receivers; duration & delivery vs loss). Pure canvas/SVG charts written by hand. Mode colours consistent: tcp #6b7280, udp #d97706, naive #dc2626, relicast #16a34a. Light+dark friendly, mobile-ok.

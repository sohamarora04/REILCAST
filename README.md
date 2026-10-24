# ReliCast — NACK-suppressed reliable multicast with SNTP-synchronised measurement

Network Programming (23CS7PCNWP) AAT project. Pure Python 3.8+ standard library — **no installs needed**. Works on Windows, macOS, Linux.

## Run (one command)

```
python run.py            # Windows: py run.py   (or double-click run.bat / run.command)
```
Opens the dashboard at http://127.0.0.1:8765 — set receivers / loss / file size, press **Run comparison**, and watch
TCP unicast, raw UDP, naive multicast and ReliCast transfer the same file side by side (live chunk map per receiver,
bytes, NACKs, delay, jitter, SNTP clock correction). The **Sweeps** tab shows the pre-computed experiments.

Other commands
```
python run.py demo           # same comparison in the terminal (writes results/console_demo.txt)
python run.py experiments    # full sweeps -> results/experiments.json (a few minutes)
python run.py send notes.pdf --mode relicast   # REAL transfer to other devices on the same Wi-Fi/hotspot (terminal)
python run.py receive                          # on each receiving laptop: auto-discovers the sender, saves to ~/ReliCast/received
python run.py --lan                            # dashboard + phone pages: phones open http://<laptop-ip>:8765/download or /upload
```

## How it works
* **TCP control channel** – receiver connects, gets session metadata (size, chunks, SHA-256), reports progress and final stats.
* **SNTP (RFC 4330)** – built-in client+server; every receiver's clock is deliberately skewed ±100–500 ms and corrected
  by SNTP before one-way delay/jitter are measured.
* **UDP multicast data path** – 1 KiB chunks, 24-byte network-order header, paced sender (UDP has no flow control).
* **ReliCast recovery (after SRM / NORM)** – receivers detect gaps (sequence jump or heartbeat), wait a random time in an
  adaptive window `W`, then multicast one batched NACK; receivers that overhear a NACK covering their gap suppress their own
  and back off; the sender aggregates NACKs for 6 ms and multicasts each repair once.
* Loss is injected at receivers (independent) and at the sender (shared/upstream), so results are reproducible on one machine.

## Troubleshooting
* Needs a network interface with multicast loopback; the app probes the LAN address then 127.0.0.1 automatically.
* Windows firewall prompt: allow Python on private networks.
* Port 8765 busy: `python run.py dashboard --port 9000`.

See `DESIGN.md` for protocol and data contracts, `ReliCast_Report.docx` / `ReliCast_PPT.pptx` for the write-up.

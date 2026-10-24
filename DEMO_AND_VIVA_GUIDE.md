# ReliCast — Demo + Viva Guide (read this before presenting)

## 1. One-line idea
**ReliCast sends one file to many computers at the same time using a single stream (multicast), and still guarantees every computer gets every byte, by letting receivers ask only for what they missed (NACK).**

Everyday analogy: a teacher reads a lecture aloud to 50 students (multicast = one voice, everybody hears).
TCP-to-each = the teacher goes to every student and reads it 50 times. If a student missed a sentence, they raise a hand
and say "repeat sentence 7" (NACK). If 30 students shout the same thing at once, that is chaos (NACK implosion) — so each
student waits a random moment, and if they hear someone else already asked, they stay quiet (NACK suppression).

## 2. Terms in simple words
| Term | Meaning (easy) |
|---|---|
| Socket | A "phone line" a program opens to send/receive data over the network. |
| TCP | Reliable, one-to-one connection. Guarantees delivery, but one copy per receiver (slow for many). |
| UDP | Fast "throw the packet" protocol. No guarantee: packets can be lost. |
| Unicast / Broadcast / Multicast | One-to-one / one-to-everyone on the network / one-to-a-chosen-group. |
| Multicast group (239.255.42.99) | A "radio channel" address. Receivers *join* it to listen; sender sends once. |
| IGMP / IP_ADD_MEMBERSHIP | The "join the channel" request (socket option) a receiver makes. |
| TTL | How many routers a packet may cross (1 = stay on this LAN). |
| ACK vs NACK | ACK = "I got it" (every receiver talks constantly). NACK = "I did NOT get #7" (talk only on loss). |
| ACK/NACK implosion | Hundreds of receivers replying at once and flooding the sender. |
| NACK suppression (SRM paper) | Wait a random time before complaining; if someone else already complained about the same packet, stay silent. |
| Repair / retransmission | Sender re-sends the lost packet — once, to everybody (multicast repair). |
| Heartbeat | Small periodic packet saying "I have sent up to #N" so receivers can notice missing packets at the end of the file. |
| Flow control / pacing | UDP has none, so our sender limits its speed (packets/second) to avoid overflowing buffers. |
| SO_REUSEADDR / SO_RCVBUF / IP_MULTICAST_TTL / SO_BROADCAST | Socket options we set (Unit 2): share a port, bigger receive buffer, multicast scope, allow broadcast. |
| select() | Lets one thread wait on several sockets at once (Unit 3 advanced I/O). |
| Byte order (network order) | Numbers in packet headers are packed big-endian (`struct '!'`), so all machines agree (Unit 1). |
| SNTP (RFC 4330) | Simple Network Time Protocol: asks a server for the time so two computers' clocks agree (Unit 5). |
| One-way delay (OWD) / Jitter | Time a packet takes sender→receiver / how much that time wobbles. Needs synchronised clocks → that's why SNTP. |
| SHA-256 | A fingerprint of the file; if sender's and receiver's fingerprints match, the file is bit-for-bit identical. |
| Goodput / Overhead ratio | Useful data rate / (total bytes put on the network ÷ file size). 1.0 = perfect, 18× = wasteful. |

## 3. How the project works (flow)
1. **Sender** opens a TCP *control* port, a tiny SNTP time server, and announces itself with a **UDP broadcast beacon** (port 5599) every second.
2. **Receivers** (`python run.py receive`) hear the beacon, connect over TCP, get the file info (name, size, chunk count, SHA-256, multicast address).
3. Receivers sync their clock with **SNTP** (we even *deliberately skew* clocks by ±100–500 ms in the benchmark to prove sync works) and **join the multicast group**.
4. Sender does a **multicast probe** (10 test packets). Receivers that cannot hear multicast (common on hotspots/AP isolation) are automatically served by **TCP instead** (hybrid fallback). Others use multicast.
5. File is cut into 1 KB **chunks** with a 24-byte header (type, session, sequence number, total, timestamp). Sent once to the group at a paced rate.
6. Receiver notices a gap (sequence jump, or heartbeat says "up to #500" but I only have 480) → waits random time → sends **one batched NACK** to the group → others who also miss the same chunks **stay silent** (suppressed, with exponential back-off if the repair itself is lost).
7. Sender collects NACKs for 6 ms, **merges them**, multicasts each missing chunk **once** (repair aggregation).
8. When a receiver has all chunks it checks **SHA-256**, saves the file to `~/ReliCast/received`, and reports stats over TCP. Sender sends FIN.

## 4. The four protocols we compare (same file, same receivers, same loss, same link speed)
| Mode | What it is | Result |
|---|---|---|
| TCP unicast | N separate TCP connections | Reliable but traffic grows ×N (e.g. ~18× file size for 16 receivers) |
| Raw UDP unicast | N UDP copies, no recovery | Fast-ish but **loses data** (delivery < 100 %) |
| Naive multicast | Multicast + everybody NACKs immediately | Reliable, cheap on data, but **NACK storm** (many NACKs, many duplicate repairs) |
| **ReliCast (ours)** | Multicast + randomized NACK timers + suppression + repair aggregation + adaptive window | Reliable, ~5× fewer bytes than TCP, ~2–3× fewer NACKs than naive in our runs |

## 5. Research basis (what to say)
* **SRM** — Floyd et al., IEEE/ACM Transactions on Networking, 1997: receiver-driven repair, random timers, suppression.
* **NORM** — RFC 5740 (IETF, 2009): NACK-oriented reliable multicast, repair aggregation.
* **Gap we address:** those works are mostly simulator-based (ns-2) and don't report *real-socket* one-way delay/jitter because clocks aren't synchronised; windows are fixed. **Our contribution:** a working implementation on real sockets, adaptive NACK window, SNTP-synchronised delay/jitter measurement, a real-world mode with automatic TCP fallback, and a four-way controlled comparison.
* Be honest: it is *not a new protocol invented from scratch* — it is an implementation and evaluation of SRM/NORM ideas with these additions.

## 6. How to run + demo (10 minutes)
**Start (nothing to install, only Python 3.8+):** `python run.py` (Mac: `python3 run.py`; or double-click `run.bat` / `run.command`). Browser opens at http://127.0.0.1:8765.

1. **Compare tab (2 min)** — set 6 receivers, 5 % loss, 2 % shared loss, 512 KB → *Run comparison*. Watch the live chunk map (green squares = received) for each protocol. Point at the verdict sentence and the bar charts: bytes on wire, NACKs, delivery %, delay/jitter. Show the **SNTP card**: injected clock error vs SNTP estimate; raw delay (~90 ms, wrong) vs corrected (~3 ms).
2. **Sweeps tab (1 min)** — scaling with receivers (TCP grows linearly, multicast stays flat) and with loss.
3. **Real transfer (4 min)** — *Send* tab: drag any file (PDF/photo), choose **ReliCast**, *Open session*. On a second laptop on the same Wi-Fi/hotspot run `python run.py receive` (or second terminal on same laptop). The receiver appears in the lobby → *Start transfer*. Show progress, repairs, "verified". Open the saved file in `~/ReliCast/received`. Optional: start a receiver with multicast blocked to show the TCP fallback badge.
4. **Terminal version (1 min)** — `python run.py demo` prints the same four-way comparison table.
5. **Phones** — `python run.py --lan` then phone opens `http://<laptop-ip>:8765/download` to download or `/upload` to send a file to the laptop (phones can't run Python, so they use HTTP).
6. Close with the report's conclusion: bytes ↓, NACKs ↓, delivery 100 %, clocks verified by SNTP.

**Before the demo checklist:** laptops on the same network (hotspot is fine), allow Python through the firewall (Windows prompt → *Private networks*), run `python run.py demo` once to be sure, keep a small and a medium file ready.

## 7. Syllabus mapping (say this to the teacher)
Unit 1: sockets, byte-order, TCP/UDP, buffer sizes · Unit 2: TCP client-server (control channel), socket options (SO_REUSEADDR, SO_RCVBUF, IP_MULTICAST_TTL/IF/LOOP, TCP_NODELAY) · Unit 3: UDP sockets, lack of flow control (pacing), select(), socket timeouts · Unit 4: broadcasting (beacon discovery, SO_BROADCAST), unicast vs broadcast vs multicast · Unit 5: multicasting (join/leave, TTL, multicast on LAN) and SNTP.

## 8. Likely teacher questions + answers
* **Why not just TCP?** TCP needs one connection per receiver → sender bandwidth ×N. Multicast sends once.
* **Why not plain UDP multicast?** Unreliable — we measured ~7–20 % data loss.
* **ACK vs NACK?** ACK-based protocols implode with many receivers; NACK-based send feedback only on loss.
* **Why random timers?** So identical complaints don't arrive together; the first one suppresses the rest.
* **Why SNTP?** One-way delay = receive time − send time needs both clocks equal. Without it, ~90 ms error swamps a ~3 ms real delay.
* **Is it really reliable?** Every receiver verifies SHA-256 of the whole file; mismatch = not saved.
* **What if the network blocks multicast?** Probe detects it; those receivers are served over TCP automatically.
* **Is ReliCast always fastest?** No. Naive multicast can finish slightly sooner because it repairs instantly; ReliCast trades a bit of latency for far less feedback and duplicate traffic (see report, honest discussion).
* **Limitations:** no encryption/authentication, file must fit in RAM, IPv4 only, TCP loss is modelled (kernel can't drop packets locally), benchmark run on one machine with receivers as separate processes; Wi-Fi APs often throttle/block multicast.
* **Future work:** FEC (forward error correction) parity packets, congestion control (TFRC), IPv6, encryption.

## 9. Summary paragraph (you can read this out)
"Our project, **ReliCast**, is a reliable file-distribution system built with socket programming in Python. Sending a file to many computers with **TCP** needs a separate connection for each receiver, so the sender's traffic grows with the number of receivers, while plain **UDP** (an unreliable, connectionless protocol) loses packets. We use **UDP multicast** (one transmission delivered to a whole group of receivers that have joined a multicast address) and add reliability ourselves: when a receiver detects a gap in the **sequence numbers** it sends a **NACK** (negative acknowledgement, i.e. a request only for the missing chunk). Following the **SRM** and **NORM** research papers, receivers wait a **random timer** before sending the NACK and stay silent if they overhear someone asking for the same chunk (**NACK suppression**, which avoids NACK implosion), and the sender merges requests and multicasts each repair once. A **TCP control channel** carries session information and statistics, **UDP broadcast beacons** let receivers discover senders, and a **multicast probe** automatically falls back to TCP for devices on networks that block multicast, such as some hotspots. We implemented **SNTP** (Simple Network Time Protocol) so that sender and receiver clocks agree and we can measure true **one-way delay** and **jitter**. Every file is checked with a **SHA-256** hash. In our experiments, with the identical file, receivers, loss and link speed, ReliCast delivered 100 % of the data using about five times fewer bytes than TCP and two to three times fewer NACKs than naive multicast, while raw UDP lost data. The system covers all five syllabus units: sockets and byte ordering, TCP client-server and socket options, UDP and advanced I/O, broadcasting, and multicasting with SNTP."

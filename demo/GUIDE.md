# ReliCast demo guide: Wireshark (real) + Packet Tracer (concept)

**Be upfront in the viva:** Packet Tracer cannot run our Python code and its end hosts cannot join multicast groups.
So we use **both**:

| Tool | What it shows | Real ReliCast packets? |
|---|---|---|
| **Wireshark** | TCP / UDP / naive multicast / ReliCast with 8 receivers, NACKs, repairs, SNTP | **Yes** |
| **Packet Tracer** | Network picture + TCP vs UDP behaviour with 8 receivers (simulation mode) | No, equivalent protocols |

> I could not generate a `.pkt` file: the format is encrypted and can only be created by Packet Tracer itself.
> Building it takes about 10 minutes with the steps in Part B. Save it as `ReliCast_Lab.pkt` afterwards.

---

## Part A: Wireshark demo (main demo, ~5 min)

### A1. Setup (once)
1. Install Wireshark. Copy `demo/relicast.lua` into Wireshark's personal plugins folder
   (*Help > About Wireshark > Folders > Personal Lua Plugins*). Restart Wireshark.
2. Check the app runs: `python3 run.py demo` (Mac/Linux) or `py run.py demo` (Windows).

### A2. Capture (Mac/Linux)
```bash
sudo ./demo/capture_modes.sh 8
```
This runs the 4 modes with **8 receivers**, 5 % loss, and writes `demo/captures/tcp.pcap`, `udp.pcap`, `naive.pcap`, `relicast.pcap`.

**Windows:** start Wireshark on the interface the app prints (loopback = *Npcap Loopback Adapter*), press Start, run
`py run.py demo --receivers 8`, then stop and save. (For one mode at a time, use the dashboard and its mode checkboxes.)

### A3. What to show for each file (open it, then use the filter)

| File | Filter | What you see | Say |
|---|---|---|---|
| `tcp.pcap` | `tcp` then *Statistics > Conversations > TCP* | **8 separate TCP conversations** (SYN, SYN-ACK, ACK each) | "Sender transmits the file 8 times" |
| `udp.pcap` | `udp` then *Statistics > Conversations > UDP* | 8 UDP streams, no ACK and no retransmission | "Fast, but lost packets are gone, so delivery is under 100 %" |
| `naive.pcap` | `relicast.type == 4` | A burst of **NACKs from many receivers at once** | "NACK implosion" |
| `relicast.pcap` | `ip.dst == 239.255.42.99` | **One** stream to the group address, serving all 8 | "Single copy for 8 receivers" |
| `relicast.pcap` | `relicast.type == 4` | Few NACKs (others are suppressed) | "Random timer + suppression" |
| `relicast.pcap` | `relicast.type == 2` | Repairs sent **once** to the group | "Repair aggregation" |
| `relicast.pcap` | `relicast.type == 3` | Heartbeats | "Detects tail loss" |
| any | `udp.port == 5599` | Broadcast beacon (255.255.255.255) | "Discovery by broadcast" |
| any | `ntp` (*Analyze > Decode As > UDP port > NTP*) | SNTP request/response | "Clock sync before measuring delay" |

The data port is random per run. The Lua plugin finds ReliCast packets by their `RC` magic bytes, so no setup is needed.

### A4. The 30-second comparison (bytes on the wire)
Open each file and note *Statistics > Capture File Properties > Bytes*:
`tcp ≈ 8× file`, `udp ≈ 8× file`, `relicast ≈ 1× file + repairs`.
This matches the dashboard's "overhead" bar chart.

### A5. Live demo (optional)
Start Wireshark capturing, then run the dashboard (`python3 run.py`) and press **Run comparison** with 8 receivers. Packets appear live.

---

## Part B: Packet Tracer lab (~10 min to build)

### B1. Build
1. Place **1 Server-PT**, **8 PC-PT**, **1 switch 2960**. Rename the server `Sender` and the PCs `Receiver1` to `Receiver8`.
2. Connect all with **Copper Straight-Through** cables (server to Fa0/1, PCs to Fa0/2 to Fa0/9).
3. Set IPs from `demo/packet_tracer/switch_and_ips.txt` (192.168.10.1 for the server, .11 to .18 for the PCs, mask 255.255.255.0).
4. Paste the switch config from the same file (optional; defaults also work).
5. On `Sender` > *Services*: turn **ON** HTTP, FTP, TFTP and NTP.
   (HTTP/FTP are TCP, TFTP and NTP are UDP.)

### B2. Demo 1: TCP unicast to 8 receivers
1. Click **Simulation** (bottom right), then *Edit Filters* and select only **TCP**, **HTTP** and **ARP**.
2. On each PC: *Desktop > Web Browser* and open `http://192.168.10.1`. Do it for 8 PCs.
3. Press *Auto Capture / Play*. Show the **SYN, SYN-ACK, ACK** handshake and **8 separate flows** leaving the Sender.
   Click a packet to see TCP flags, sequence and ACK numbers.

### B3. Demo 2: UDP unicast, no handshake
1. Filter: only **UDP**, **TFTP**, **NTP**.
2. On a PC: *Desktop > Command Prompt*: `tftp 192.168.10.1 get <file>` (add a file in Sender > Services > TFTP first).
3. Show there is no handshake and no connection state. NTP (UDP/123) is our SNTP equivalent: from a PC, set *Desktop > Date & Time*
   or use the NTP service client.

### B4. Demo 3: Broadcast (our discovery beacon)
Filter **ARP**/**ICMP**. In Simple PDU mode, click *Add Simple PDU* from Receiver1 to **192.168.10.255**. The switch floods it to all ports (one packet, everyone hears it).

### B5. Multicast (be honest)
Packet Tracer end hosts cannot join multicast groups, so this part is **only in Wireshark** (`ip.dst == 239.255.42.99`).
Show the Packet Tracer broadcast flooding as the closest visual, then say: "multicast delivers to group members only."

### B6. Save
*File > Save As* `ReliCast_Lab.pkt`.

---

## Part C: 2-minute viva script
1. "TCP: 8 receivers means 8 connections and 8× traffic" (Packet Tracer Demo 1 + `tcp.pcap`).
2. "UDP: no guarantee" (Packet Tracer Demo 2 + `udp.pcap` loss).
3. "Naive multicast: cheap but NACK storm" (`naive.pcap`, `relicast.type == 4`).
4. "ReliCast: one stream + suppressed NACKs + single repair, and the file is still verified with SHA-256."
5. "SNTP corrects clock skew before delay is measured" (`ntp` filter).

## Troubleshooting
* `tcpdump` shows nothing: the app fell back to loopback. The script picks `lo0` itself, but run it with `sudo`.
* No `RELICAST` rows: the Lua plugin isn't loaded (*Help > About Wireshark > Plugins*).
* Windows firewall: allow Python on private networks.

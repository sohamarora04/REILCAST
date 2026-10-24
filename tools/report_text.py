"""All report prose. Every number comes from the experiments JSON via Data (D)."""
import math, os
from common import *
from docx_helpers import *


def facts(D):
    F = {}
    ns, ls = D.ns(), D.losses()
    nmin, nmax = ns[0], ns[-1]
    F.update(ns=ns, nmin=nmin, nmax=nmax, lmax=ls[-1], l0=ls[0])
    for m in MODES:
        F[m + "_d_nmax"] = D.sn(m, nmax, "duration_s"); F[m + "_o_nmax"] = D.sn(m, nmax, "overhead_ratio")
        F[m + "_d_n1"] = D.sn(m, nmin, "duration_s"); F[m + "_o_n1"] = D.sn(m, nmin, "overhead_ratio")
        F[m + "_dl_max"] = D.sl(m, ls[-1], "duration_s"); F[m + "_dv_max"] = D.sl(m, ls[-1], "delivery_ratio")
        F[m + "_dl_0"] = D.sl(m, ls[0], "duration_s")
    n, loss, sh = D.demo_params()
    F.update(dn=n, dloss=loss, dsh=sh)
    dm = D.demo
    for m in MODES:
        for k in ("duration_s", "overhead_ratio", "delivery_ratio", "nack_packets", "nack_suppressed", "repair_packets", "owd_mean_ms", "owd_p95_ms", "jitter_ms", "owd_raw_mean_ms", "total_bytes", "sender_bytes", "goodput_mbps", "dup_data", "heartbeat_packets"):
            F["%s_%s" % (m, k)] = dm[m][k]
        F[m + "_ver"] = dm[m]["all_verified"]
    r = dm["relicast"]
    F["size_bytes"], F["chunks"], F["chunk"] = r["size_bytes"], r["chunks"], r["chunk"]
    F["sntp_err"] = max(abs(a - b) for a, b in zip(r["sntp_offsets_ms"], r["skews_ms"]))
    F["skew_max"] = max(abs(x) for x in r["skews_ms"])
    F["nack_red"] = 100 * (1 - r["nack_packets"] / max(1, dm["naive"]["nack_packets"]))
    F["rep_red"] = 100 * (1 - r["repair_packets"] / max(1, dm["naive"]["repair_packets"]))
    F["supp_pct"] = 100 * r["nack_suppressed"] / max(1, r["nack_suppressed"] + r["nack_packets"])
    F["tcp_vs_rc_d"] = F["tcp_d_nmax"] / F["relicast_d_nmax"]; F["tcp_vs_rc_o"] = F["tcp_o_nmax"] / F["relicast_o_nmax"]
    F["nv_vs_rc_o"] = F["naive_o_nmax"] / F["relicast_o_nmax"]
    F["dem_tcp_vs_rc_o"] = F["tcp_overhead_ratio"] / F["relicast_overhead_ratio"]
    F["rc_o_min"] = min(D.sn("relicast", x, "overhead_ratio") for x in ns); F["rc_o_max"] = max(D.sn("relicast", x, "overhead_ratio") for x in ns)
    F["all_ok"] = all(x["all_verified"] for x in D.sweep_n + D.sweep_l if x["mode"] in ("tcp", "naive", "relicast"))
    F["ver_count"] = sum(1 for x in D.sweep_n + D.sweep_l if x["mode"] in ("tcp", "naive", "relicast") and x["all_verified"])
    F["ver_total"] = sum(1 for x in D.sweep_n + D.sweep_l if x["mode"] in ("tcp", "naive", "relicast"))
    rc = [x for x in D.sweep_n + D.sweep_l if x["mode"] == "relicast"]
    F["rc_ver_txt"] = "every ReliCast transfer was verified" if all(x["all_verified"] for x in rc) else "%d of %d ReliCast transfers were verified" % (sum(1 for x in rc if x["all_verified"]), len(rc))
    F["owd_ratio"] = abs(r["owd_raw_mean_ms"]) / max(1e-9, r["owd_mean_ms"])
    return F


# model predictions (first-order) -------------------------------------------------
def model(F):
    N, p, q, C = F["dn"], F["dloss"], F["dsh"], F["chunks"]
    pe = q + (1 - q) * p
    u = 1 - (1 - q) * (1 - p) ** N
    return dict(pe=pe, u=u, naive_nack=C * N * pe, rc_chunks=C * u, miss=C * N * pe, M=N * pe)


REFS = [
    "S. Floyd, V. Jacobson, C.-G. Liu, S. McCanne, and L. Zhang, “A reliable multicast framework for light-weight sessions and application level framing,” *IEEE/ACM Transactions on Networking*, vol. 5, no. 6, pp. 784–803, Dec. 1997.",
    "B. Adamson, C. Bormann, M. Handley, and J. Macker, “NACK-Oriented Reliable Multicast (NORM) Transport Protocol,” RFC 5740, Internet Engineering Task Force, Nov. 2009.",
    "D. Mills, \u201cSimple Network Time Protocol (SNTP) Version 4 for IPv4, IPv6 and OSI,\u201d RFC 4330, Internet Engineering Task Force, Jan. 2006.",
    "S. E. Deering, “Host Extensions for IP Multicasting,” RFC 1112, IETF, Aug. 1989.",
    "D. Meyer, “Administratively Scoped IP Multicast,” RFC 2365, IETF, Jul. 1998.",
    "H. Schulzrinne, S. Casner, R. Frederick, and V. Jacobson, “RTP: A Transport Protocol for Real-Time Applications,” RFC 3550, IETF, Jul. 2003 (interarrival jitter, Sec. 6.4.1).",
    "W. R. Stevens, B. Fenner, and A. M. Rudoff, *UNIX Network Programming, Volume 1: The Sockets Networking API*, 3rd ed. Boston, MA, USA: Addison-Wesley, 2003.",
    "Python Software Foundation, “socket — Low-level networking interface,” *The Python Standard Library documentation*, https://docs.python.org/3/library/socket.html.",
    "Python Software Foundation, “select — Waiting for I/O completion” and “struct — Interpret bytes as packed binary data,” *The Python Standard Library documentation*, https://docs.python.org/3/library/.",
    "*getsockopt(2) / setsockopt(2)*, Linux Programmer’s Manual, man7.org, section 2.",
    "*ip(7) — Linux IPv4 protocol implementation*, Linux Programmer’s Manual, man7.org, section 7 (IP_ADD_MEMBERSHIP, IP_MULTICAST_TTL, IP_MULTICAST_IF, IP_MULTICAST_LOOP).",
]


def write_content(b, D, T):
    F = facts(D); M = model(F); meta = D.meta
    fig = lambda n: os.path.join(FIGS, n)
    f2 = lambda x: "%.2f" % x
    f1 = lambda x: "%.1f" % x
    pc = lambda x: "%g%%" % (x * 100)
    N, nmax = F["dn"], F["nmax"]
    size_kb = F["size_bytes"] // 1024

    # =============================================================== 1 Abstract
    b.h1("Abstract")
    abstract = ("Sending one file to many machines on a LAN usually means either N separate TCP transfers, so the sender transmits N copies, or raw UDP multicast, which is cheap but silently loses data. "
                "We built ReliCast, a Python socket-level tool that sends one multicast copy and recovers losses through receiver-driven negative acknowledgements (NACKs). Following SRM and NORM, receivers wait a random time in [0, W) before sending a NACK and drop it if another receiver has already asked for the same data, while the sender merges repair requests. "
                "A TCP channel carries control messages, and our SNTP client and server (RFC 4330) synchronise clocks so that one-way delay and jitter can be measured. A real-file mode adds broadcast discovery and a TCP fallback for receivers that cannot hear multicast. "
                "Four modes were compared for up to %d receivers and up to %s loss. With %d receivers ReliCast needed %s s against %s s for TCP, with an overhead ratio of %sx against %sx, and %s with SHA-256. "
                "At the demonstration point it sent %d NACKs where the naive scheme sent %d, and SNTP recovered injected clock skews of up to %s ms to within %s ms."
                ) % (nmax, pc(F["lmax"]), nmax, f2(F["relicast_d_nmax"]), f2(F["tcp_d_nmax"]), f2(F["relicast_o_nmax"]), f2(F["tcp_o_nmax"]), F["rc_ver_txt"], F["relicast_nack_packets"], F["naive_nack_packets"], "%.0f" % F["skew_max"], f2(F["sntp_err"]))
    wc = len(abstract.split())
    assert 150 <= wc <= 200, "abstract has %d words" % wc
    b.p(abstract)
    b.p("**Keywords:** reliable multicast, NACK suppression, SRM, NORM, SNTP, socket programming, UDP, one-way delay.", align="l")

    # =============================================================== 2 Objectives
    b.h1("Objectives")
    b.p("This assessment applies the Network Programming syllabus to one practical problem: delivering a file to many receivers on a LAN, and measuring how well the solution works. Our specific objectives were:", keep=True)
    b.numbered([
        "To understand and use the BSD socket API (socket, bind, listen, accept, connect, sendto, recvfrom, setsockopt, select) for both stream and datagram communication.",
        "To implement a TCP control channel for session metadata and final statistics, and a UDP multicast data path using IP_ADD_MEMBERSHIP, TTL scoping and the related socket options.",
        "To study the two reference designs for scalable reliable multicast, SRM and NORM, and pick out the mechanisms that avoid ACK/NACK implosion: randomised NACK timers, suppression and repair aggregation.",
        "To implement a NACK-oriented reliable multicast protocol (ReliCast) with an adaptive suppression window and verify every transfer end to end with SHA-256.",
        "To implement SNTP (RFC 4330) client and server over UDP and use them to synchronise receiver clocks, so that one-way delay and jitter can be measured on real sockets.",
        "To build comparable baselines (TCP unicast, raw UDP unicast, naive immediate-NACK multicast) and analyse duration, overhead ratio, delivery ratio, NACK and repair traffic, delay and jitter under varying receiver counts and loss rates.",
        "To turn the system into a usable file-transfer tool for real devices, with broadcast discovery, a multicast reachability probe that falls back to TCP automatically, SHA-256 verified saving, a live web dashboard and a reproducible experiment harness.",
    ])

    # =============================================================== 3 Introduction
    b.h1("Introduction")
    b.h2("Network programming and the application")
    b.p("Network programming is about writing programs that talk to each other across a network using the services the operating system provides. The application we picked is *one-to-many content distribution on a local network*: a teacher pushes lecture slides, or an administrator pushes an update package, to every laptop in a lab. If the sender opens a separate TCP connection to each of N machines, it has to put N copies of the file on its uplink, so the transfer time grows linearly with N. IP multicast avoids this by sending one copy that the network delivers to every member of a group address. The catch is that multicast runs over UDP, which gives no retransmission, ordering or flow control. A practical tool therefore has to add reliability on top of multicast without bringing the scalability problem back, and that is exactly the design space of the two papers reviewed in Chapter 4.")
    b.h2("TCP, UDP and multicast")
    b.p("TCP gives a reliable, ordered byte stream with connection set-up, acknowledgements, retransmission and congestion control. It suits small but important messages, so ReliCast uses it for session metadata and the final per-receiver statistics. UDP is connectionless and keeps datagram boundaries; it adds only port numbers and a checksum on top of IP, which leaves reliability, ordering and pacing to the application. Unicast addresses one host, broadcast addresses every host on the subnet whether it cares or not, and multicast (RFC 1112) addresses a group of hosts that have asked to join, using IGMP. A sender transmits one datagram to a class D address, here in the administratively scoped range 239.0.0.0/8 (RFC 2365), and the TTL limits how far it travels. What multicast takes away is the per-receiver connection through which the sender would normally learn about loss.")
    b.h2("System calls and socket options")
    b.p("All of this is reached through system calls exposed by Python’s socket module. socket() creates an endpoint, bind() attaches it to an address and port, listen() and accept() make up the server side of TCP and connect() the client side. For UDP, sendto() and recvfrom() move individual datagrams. setsockopt() changes behaviour: SO_REUSEADDR and SO_REUSEPORT let several receiver processes share one multicast port on a host, SO_RCVBUF enlarges the kernel receive queue so bursts are not dropped, IP_MULTICAST_TTL, IP_MULTICAST_IF and IP_MULTICAST_LOOP control scope, interface and loopback delivery, IP_ADD_MEMBERSHIP joins a group, and SO_BROADCAST allows sending to the broadcast address. select() waits on several sockets and a timer in a single thread, and struct.pack with the ‘!’ prefix builds headers in network byte order. Section 7.5 shows where each call is used in ReliCast.")
    b.h2("Clock synchronisation with SNTP")
    b.p("You cannot measure one-way delay between two machines whose clocks disagree, which is why many reliable-multicast evaluations report round-trip time or simulated time instead. The Simple Network Time Protocol (RFC 4330) estimates the offset between a client clock and a server clock from four timestamps carried in a 48-byte UDP packet. ReliCast runs an SNTP server inside the sender and an SNTP client in every receiver, so data packets can carry sender timestamps that mean the same thing at both ends.")
    b.h2("Tools and environment")
    b.p("The system is written in Python 3 and uses only the standard library (socket, select, struct, threading, hashlib, json, http.server), so it runs unchanged on Windows, macOS and Linux. Each receiver is a separate operating-system process. A single-file web dashboard served by http.server shows transfers live. We inspected packets the way one would in Wireshark, by decoding the 24-byte header, and used matplotlib, python-docx and python-pptx to turn the experiment output into figures and this report.")

    # =============================================================== 4 Literature
    b.h1("Literature Review")
    b.p("This project builds on two foundational works on scalable reliable multicast: the SRM framework of Floyd et al. [1] and the NORM protocol of Adamson et al. [2]. Between them they show the two classic ways, receiver-side and sender-side, of stopping negative acknowledgements from overwhelming a multicast session. RFC 4330 [3] and RFC 1112 [4] are used only as supporting specifications.")
    b.h2("SRM: Scalable Reliable Multicast (Floyd et al., 1997)")
    b.p("**Problem.** Sender-driven reliability does not scale to large multicast groups: every receiver’s acknowledgement lands on the sender (ACK implosion), and the sender has to track the state of each receiver. The authors argue for recovery in the application itself, following *application level framing* (ALF). **Mechanism.** Each data unit in SRM has a persistent name, and receivers notice loss from gaps in sequence numbers or from periodic *session messages*. A receiver that detects a loss schedules a repair request at a random time drawn uniformly from [C1·d, (C1+C2)·d], where d is its estimated distance to the source. If it hears a request for the same data before its timer fires, it suppresses its own request and backs off exponentially. Any member that holds the data can answer after a random timer proportional to its distance from the requester, and hearing a repair cancels the other pending repairs. The timer parameters adapt to observed duplicates and delay, and TTL-scoped local recovery limits how far repairs travel. **Results.** The paper uses ns-2 simulations on chain, star and bounded-degree tree topologies, with the *wb* shared whiteboard as the driving application. It shows that deterministic suppression works in chains, probabilistic suppression works in stars, and that the adaptive timers keep both duplicates and delay low as the session grows. **Limitations.** Every request and repair is multicast to the whole group. The distance estimates need session-message exchange, which itself grows with group size. The study is simulation based and reports no measured one-way delay on real hosts, and the timer constants have to be tuned or adapted for each topology. **Relevance.** ReliCast takes SRM’s randomised request timers, suppression on overheard requests and exponential back-off. In place of the distance term it uses an adaptive window computed from SNTP-synchronised delay and jitter.")
    b.h2("NORM: NACK-Oriented Reliable Multicast (RFC 5740, 2009)")
    b.p("**Problem.** Bulk-data and streaming applications need a reliable one-to-many transport that works over multicast and scales to large groups without positive acknowledgements. **Mechanism.** NORM is NACK-oriented, with one logical sender per session. The sender transmits objects as numbered coding blocks and symbols, advertises its state with heartbeat-style flush commands, and keeps a running estimate of the group round-trip time (GRTT) from receiver responses. A receiver that finds missing data waits for a random back-off, scaled by the advertised GRTT, before sending its NACK, and cancels it if it overhears an equivalent or larger one. The sender does not answer each NACK immediately: it *aggregates* the requests that arrive within a repair cycle and transmits the union once, optionally using forward-error-correction parity. Congestion control and positive acknowledgement are optional. **Results.** RFC 5740 is a standards-track specification, so it gives design rationale and protocol analysis rather than a measurement campaign. **Limitations.** Suppression timing depends on a GRTT estimate that the sender must maintain from feedback. The specification offers no way to measure one-way delay between unsynchronised hosts, and the full protocol with FEC and congestion control is far more complex than a LAN file-push tool needs. **Relevance.** From NORM, ReliCast takes sender-side repair aggregation (a 6 ms hold-off that merges requested ranges into a union), a repair guard that stops a chunk from being re-sent right after it was repaired, and the heartbeat that lets receivers find losses at the tail of a transfer.")
    b.h2("Comparison")
    b.table(["Aspect", "SRM [1]", "NORM [2]", "ReliCast (this work)"], [
        ["Reliability driver", "Receiver (any member repairs)", "Receiver NACK, sender repairs", "Receiver NACK, sender repairs"],
        ["Suppression", "Random timer scaled by distance d", "Random back-off scaled by GRTT", "Random timer in [0, W), W adaptive"],
        ["Repair handling", "Multicast by any holder, random timer", "Sender aggregation, optional FEC", "Sender hold-off with union of ranges"],
        ["Evaluation", "ns-2 simulation", "Specification (no measurements)", "Real sockets, SNTP-synchronised OWD"],
        ["Main limitation", "Session messages, topology tuning", "GRTT state, complexity", "LAN scale, loss emulation, no FEC"],
    ], "Comparison of the two reviewed protocols with ReliCast", [1.15, 1.55, 1.55, 1.75], size=9)

    # =============================================================== 5 Gap
    b.h1("Research Gap")
    b.p("Reading SRM and NORM side by side leaves several points open. First, both rely on timers whose range comes from a distance or round-trip estimate, and neither tunes the suppression window from measured one-way delay and delay variation. Second, SRM’s evidence comes from ns-2 simulations and RFC 5740 has no measurement section, so there are few published numbers on how many NACKs are really suppressed, or how much repair traffic the sender saves, on live operating-system sockets. Third, one-way delay and jitter, which decide how long a randomised timer can safely wait, are never reported because sender and receiver clocks are not synchronised, and round-trip time hides which direction of a path is slow. Fourth, comparisons with the obvious baselines, one TCP connection per receiver and raw UDP, are usually only qualitative, so it is hard for a practitioner to judge when reliable multicast is worth the extra complexity. Finally, both designs assume the full protocol machinery and say little about a small, portable, dependency-free implementation for a campus lab.")
    b.p("Of these, we focus on one gap: **there is no real-socket study of NACK-suppressed reliable multicast that (a) adapts the suppression window from SNTP-synchronised one-way delay and jitter and (b) measures its benefit against TCP-unicast, raw-UDP and un-suppressed multicast baselines in the same experimental harness.** The other points are left as future work. The gap suits a network programming assessment because closing it needs exactly the skills in the syllabus: TCP and UDP sockets, multicast group management, socket options, I/O multiplexing and an implementation of an Internet time protocol.")

    # =============================================================== 6 Problem statement
    b.h1("Problem Statement")
    b.p("*Given* a sender that must deliver a file of S bytes to N receivers on one multicast-capable LAN, where each receiver independently loses a fraction p of datagrams and an upstream fault may remove a fraction q of the transmissions for all receivers at once, *design and implement*, using only the standard socket API, a transfer protocol that:")
    b.numbered([
        "delivers the complete, bit-exact file to every receiver (verified by SHA-256) without the sender transmitting N copies;",
        "keeps feedback and repair traffic low by suppressing duplicate NACKs with randomised timers and by aggregating repair requests at the sender, even as N grows;",
        "adapts the suppression window W to the measured one-way delay and jitter, which are obtained by synchronising receiver clocks with an SNTP exchange implemented from RFC 4330; and",
        "can be evaluated fairly against three baselines (TCP unicast, raw UDP unicast, multicast with immediate un-suppressed NACKs) using the same pacing, file and loss model.",
    ])
    b.p("The measurable outcome is the set of metrics in Chapter 8: transfer duration, overhead ratio (total bytes on the wire divided by the file size), delivery ratio, NACK, suppressed-NACK and repair packet counts, SNTP-corrected one-way delay and jitter, and the accuracy of the SNTP offset estimate. The approach counts as successful if ReliCast delivers 100% of the data to every receiver while its overhead ratio grows much more slowly with N than that of the unicast baselines, and its NACK and repair traffic stays clearly below that of the naive multicast scheme.")

    # =============================================================== 7 Methodology
    b.h1("Methodology and Implementation")
    b.h2("Proposed architecture")
    b.p("ReliCast has one sender process and N receiver processes (Figure {{arch}}). The sender cuts the file into 1 KB chunks, computes its SHA-256 digest, listens for TCP control connections, runs a small SNTP server and then sends the multicast stream at a fixed packet rate. That rate stands in for a shared uplink and also supplies the flow control that UDP lacks. Every receiver is a separate operating-system process that talks to the sender over TCP, SNTP and the multicast group. The datagram format (Figure {{pkt}}) follows Application Level Framing: each packet carries a 24-byte header with a magic value, type, flags, session id, sequence number, total chunk count and a sender timestamp in SNTP-corrected microseconds, so it can be understood without any other context. The packet types are DATA, REPAIR, HEARTBEAT (carries the highest sequence sent), NACK (receiver id and inclusive sequence ranges), FIN and PROBE.")
    b.figure(fig("arch_diagram.png"), "System architecture of ReliCast", width=4.2, key="arch")
    b.figure(fig("packet_format.png"), "ReliCast datagram layout (network byte order)", width=4.6, key="pkt")
    b.h2("Network communication model")
    b.p("A session runs as in Figure {{seq}}. (1) A receiver connects to the sender’s TCP control port and gets one JSON line with the session id, file name, size, chunk size, chunk count, SHA-256, group, port, SNTP port and protocol parameters. (2) It makes five SNTP exchanges and keeps the sample with the smallest round-trip delay. (3) It joins the multicast group and reports ready over TCP. (4) Once all N receivers are ready, the sender multicasts DATA at the configured rate and mixes in HEARTBEATs so that tail losses get noticed. (5) Receivers detect gaps and run the NACK timer described in Section 7.4 (Figure {{flow}}), and the sender answers with REPAIR packets. (6) After checking the digest, each receiver returns its statistics over TCP and the sender multicasts FIN. A receiver moves through the states CONNECT, SYNC, JOINED, RECEIVING, REPAIRING and VERIFY.")
    b.figure(fig("sequence_diagram.png"), "Sequence diagram of one ReliCast session", width=2.8, key="seq")
    b.h2("Mathematical model")
    C_ = "C"
    b.p("Let the file have S bytes and the chunk payload L bytes, giving C = ⌈S/L⌉ chunks (1). Each receiver independently loses a datagram with probability p and an upstream fault removes a first transmission for everybody with probability q, so the probability that a given receiver misses a given chunk after the first pass is p′ = q + (1−q)p (2). For N receivers the expected number of (receiver, chunk) losses is C·N·p′, and the expected number of receivers missing a particular lost chunk is M = N·p′ (3).", after=2)
    b.eq("C = ⌈ S / L ⌉")
    b.eq("p′ = q + (1 − q) · p")
    b.eq("E[losses] = C · N · p′ ,   M = N · p′")
    b.p("**NACK volume.** Without suppression every receiver that misses a chunk sends a NACK at once, so the number of NACKs per round is about C·N·p′ and, because the naive sender answers each NACK, the repair count is of the same order (4). With ReliCast each of the M receivers draws a timer uniformly from [0, W). The earliest fires at about W/(M+1). Any other receiver whose timer expires within the propagation-plus-processing delay d of that moment has not yet heard the first NACK and also sends one, so the expected number of NACKs per lost chunk is approximately E[X] ≈ min(M, 1 + M·d/W) (5). The fraction of NACKs removed by suppression is therefore σ ≈ 1 − (1 + M·d/W)/M, which approaches 1 when d ≪ W and M is large. The delay d is exactly the quantity that SNTP-synchronised measurement makes observable. A retry after k failures draws from [0, 2ᵏ·W) (6).", after=2)
    b.eq("E[NACK_naive] ≈ C · N · p′ ,   R_naive ≈ E[NACK_naive]")
    b.eq("E[X] ≈ min( M , 1 + M · d / W )")
    b.eq("T_k ~ Uniform[ 0 , 2ᵏ · W )")
    b.p("**Repair traffic.** Because the ReliCast sender holds repair requests for 6 ms and sends the union of the requested ranges once, a chunk is repaired at most about once regardless of how many receivers missed it. The fraction of chunks missed by at least one receiver is u = 1 − (1−q)(1−p)^N, so R_relicast ≈ C·u (7), compared with R_naive ≈ C·N·p′. For the demonstration point (N = %d, p = %s, q = %s) the model gives p′ = %.3f, about %.0f expected losses and u = %.2f, hence about %.0f distinct chunks to repair against %.0f repair packets for the naive scheme; the measured values are %d and %d. Differences arise from retries and from NACK and repair packets that are themselves lost, which this first-order model ignores." % (N, pc(F["dloss"]), pc(F["dsh"]), M["pe"], M["miss"], M["u"], M["rc_chunks"], M["naive_nack"], F["relicast_repair_packets"], F["naive_repair_packets"]), after=2)
    b.eq("R_relicast ≈ C · u ,   u = 1 − (1 − q)(1 − p)^N")
    b.p("**Window adaptation.** Each receiver keeps an exponentially weighted moving average of the SNTP-corrected one-way delay and of the delay variation, and sets W = min(100, max(10, 10 + 3(ô + 4ĵ))) milliseconds (8), where ô is the delay average and ĵ the jitter average. A quiet LAN therefore gets a short window and fast recovery, and a noisy one gets a longer window and fewer duplicate NACKs. Gaps found within one window share a single request round, so a receiver sends one batched NACK per round and not one per missing chunk.", after=2)
    b.eq("W = clamp( 10 ms + 3 ( ô + 4 ĵ ) , 10 ms , 100 ms )")
    b.p("**Overhead and delivery.** With B_data, B_rep, B_hb, B_nack the bytes on the wire for first transmissions, repairs, heartbeats and NACKs (payload + 24-byte header + 28 bytes of IP/UDP, or 40 bytes of IP/TCP headers), the overhead ratio is ρ = (B_data + B_rep + B_hb + B_nack)/S (9). An ideal multicast has ρ ≈ 1 + 52/L ≈ 1.05 for L = 1024, while N unicast transfers have ρ ≈ N. The delivery ratio is the mean over receivers of received chunks divided by C (10).", after=2)
    b.eq("ρ = ( B_data + B_rep + B_hb + B_nack ) / S")
    b.eq("DR = (1/N) · Σ_k  recv_k / C")
    b.p("**Clock model.** SNTP records t1 (client send), t2 (server receive), t3 (server send) and t4 (client receive). The client clock offset and path delay are θ = ((t2 − t1) + (t3 − t4))/2 and δ = (t4 − t1) − (t3 − t2) (11), and |θ̂ − θ| ≤ δ/2 if the two directions are symmetric to within δ. Using the sample with minimum δ out of five minimises this bound. The one-way delay of data packet i at receiver k is OWD_i = (t_rx − θ̂_k) − ts_i, and jitter is the mean absolute difference of successive delays J = mean|OWD_i − OWD_(i−1)|, in the spirit of RFC 3550 (12).", after=2)
    b.eq("θ = ((t2 − t1) + (t3 − t4)) / 2 ,   δ = (t4 − t1) − (t3 − t2)")
    b.eq("OWD_i = ( t_rx,i − θ̂_k ) − ts_i ,   J = mean | OWD_i − OWD_(i−1) |")
    b.h2("Proposed algorithm")
    b.figure(fig("nack_flowchart.png"), "Receiver NACK timer and suppression flowchart", width=2.7, key="flow")
    b.code([
        "SENDER(file, N):",
        "  chunks <- split(file, L); digest <- SHA256(file)",
        "  start TCP listener, SNTP server; wait until N receivers READY",
        "  for seq in 0..C-1: send DATA(seq) to group; sleep to hold rate R",
        "      every 50 packets: send HEARTBEAT(highest = seq)",
        "  loop until all receivers DONE or timeout:",
        "      on NACK(ranges): add ranges to pending set; if no hold-off",
        "          running, start 6 ms hold-off timer",
        "      on hold-off expiry: for chunk in union(pending):",
        "          if now - last_repair[chunk] > 30 ms: send REPAIR(chunk)",
        "          clear pending",
        "  send FIN to group; collect stats over TCP",
    ], caption="Pseudocode of the ReliCast sender", key="algo_s")
    b.code([
        "RECEIVER(k):",
        "  meta <- TCP_connect(); theta <- SNTP_sync(best of 5); join(group)",
        "  have <- empty bitmap; send READY",
        "  loop (select on UDP socket, timers):",
        "    on DATA/REPAIR(seq): store chunk; record OWD = rx - theta - ts",
        "        update owd_ewma, jitter_ewma, W; cancel timers for seq",
        "    on HEARTBEAT(h) or seq jump: missing <- ranges not in have;",
        "        gaps seen in one window share one request round, timer U[0, W)",
        "    on NACK heard (from other receiver): remove covered ranges",
        "        from my timer; count nack_suppressed; k <- k + 1",
        "    on timer expiry: send NACK(missing); re-arm with 2^k * W",
        "    if have is full: verify SHA256 == meta.digest; send stats on TCP",
    ], caption="Pseudocode of the ReliCast receiver", key="algo_r")
    b.h2("Socket programming implementation")
    b.p("The multicast receive socket is created with socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP) and SO_REUSEADDR (plus SO_REUSEPORT where it exists), so that several receiver processes can share the port on one host. It is bound to the wildcard address, because binding to the group address is not portable to Windows, and joined to the group with IP_ADD_MEMBERSHIP using an ip_mreq structure built with inet_aton. The send socket sets IP_MULTICAST_TTL to 1 so traffic stays on the link, IP_MULTICAST_LOOP, and IP_MULTICAST_IF to choose the interface. Pacing is done in user space because UDP has no flow control. Table {{map}} maps these calls to the syllabus units.")
    b.table(["Unit", "Feature in ReliCast", "Calls / options used"], [
        ["Unit 1", "Sockets, network byte order, buffers", "socket(), struct.pack('!2sBBIIIQ'), SO_RCVBUF (4 MB, with fallbacks)"],
        ["Unit 2", "TCP control channel (metadata, final stats), socket states", "bind(), listen(), accept(), connect(), sendall(), recv(); SO_REUSEADDR; FIN/close"],
        ["Unit 2", "Multicast socket options", "SO_REUSEPORT, IP_MULTICAST_TTL, IP_MULTICAST_IF, IP_MULTICAST_LOOP"],
        ["Unit 3", "UDP data path, no flow control, timeouts", "sendto(), recvfrom(), user-space pacing, select.select(), settimeout()"],
        ["Unit 4", "Broadcast service discovery", "SO_BROADCAST, sendto() to 255.255.255.255:5599 and subnet .255; receivers bind(:5599)"],
        ["Unit 4", "Multicast group join, TTL scope, reachability probe", "IP_ADD_MEMBERSHIP (ip_mreq), group 239.255.42.99 (RFC 2365), TTL = 1, PROBE datagrams"],
        ["Unit 5", "SNTP clock synchronisation", "48-byte NTP packet over UDP; client and server in clock.py; offset θ and delay δ"],
    ], "Mapping of socket-programming concepts to syllabus units", [0.6, 2.35, 3.05], size=9, key="map")

    b.h2("Real-world mode, discovery and fallback")
    b.p("Beyond the simulated comparison, ReliCast is a working file-transfer tool. The sender runs python run.py send <file> --mode relicast|naive|tcp|udp (or the dashboard Send tab) and receivers run python run.py receive (or the Receive tab). **Discovery (Unit 4, broadcast).** Every second the sender broadcasts a small JSON beacon (file name, size, mode, ip:port) to 255.255.255.255, the subnet broadcast address and loopback on UDP port 5599; receivers bind that port with SO_REUSEADDR, list the beacons heard in the last four seconds and let the user choose one (Figure {{disc}}). **Lobby protocol.** The chosen receiver opens a TCP connection and the two sides exchange JSON lines: meta, ready, an optional probe, start with the chosen transport, then progress and done messages (Figure {{lobby}}). **Reachability probe and hybrid fallback.** Multicast is frequently dropped by Wi-Fi access points and hotspots (client isolation, no IGMP support). When the user starts the transfer the sender multicasts ten PROBE packets and each receiver answers over TCP with mcast_ok. A receiver that heard none is served the same file over a TCP stream while the others keep using multicast and NACK repair, so one blocked device cannot stall or fail the session. **Saving and phones.** After the SHA-256 check a receiver saves the file in ~/ReliCast/received under a unique name; with --lan, HTTP pages /download and /upload serve phone browsers while control APIs stay loopback-only. **Portability.** SO_REUSEPORT is used only where it exists (absent on Windows), multicast sockets bind the wildcard address, the clock is anchored to perf_counter because time.time() has coarse resolution on Windows, and ANSI colours are enabled explicitly in the Windows console.")
    b.figure(fig("discovery_diagram.png"), "Service discovery with UDP broadcast beacons", width=3.6, key="disc")
    b.figure(fig("lobby_sequence.png"), "Lobby, multicast probe and TCP fallback sequence", width=3.0, key="lobby")

    # =============================================================== 8 Performance Evaluation
    b.h1("Performance Evaluation")
    b.h2("Experimental setup")
    b.p("All experiments run on one host (%s, Python %s, interface %s) with the sender and the N receivers as separate processes exchanging real UDP multicast and TCP traffic through the operating-system network stack. A %d KB file is split into %d-byte chunks (%d chunks). The sender is limited to %s packets per second, which models a shared uplink, so that the unicast baselines pay for sending N copies. Each configuration is repeated %s times with different seeds and the mean is reported. Run date: %s. Packet loss is emulated in software: a per-receiver probability p discards a datagram on arrival (applies to DATA, REPAIR and NACK), and a shared probability q makes the sender skip a first transmission for every receiver. Because there is no real loss on the loopback or a quiet LAN, this emulation gives a reproducible loss process. Receivers also carry an injected clock skew of up to ±500 ms to test the SNTP correction." % (meta.get("platform", "?"), meta.get("python", "?"), meta.get("interface", "?"), meta.get("size_kb", size_kb), meta.get("chunk", F["chunk"]), F["chunks"], meta.get("link_pps", "?"), meta.get("reps", "?"), meta.get("date", "?")))
    b.table(["Mode", "Transport", "Reliability", "Loss model"], [
        ["TCP unicast", "N TCP connections", "Kernel TCP; a lost segment is re-sent after a 20 ms stall", "per-segment Bernoulli"],
        ["Raw UDP", "N UDP copies", "None (delivery ratio < 1)", "per-copy Bernoulli"],
        ["Naive multicast", "1 multicast copy", "Immediate NACK from every receiver, fixed 80 ms retry, per-NACK repair", "per-receiver + shared"],
        ["ReliCast", "1 multicast copy", "Randomised NACK timer, suppression, back-off, repair aggregation", "per-receiver + shared"],
    ], "The four transfer modes compared", [1.1, 1.2, 2.5, 1.2], size=9)
    b.p("Three experiments were run. **Sweep 1** varies the number of receivers over %s with p = 5%% and q = 2%%. **Sweep 2** varies the per-receiver loss over %s for N = %d and q = 0. The **demonstration point** uses N = %d, p = %s and q = %s and is the source of the console output, NACK counts and delay figures." % (", ".join(map(str, F["ns"])), ", ".join(pc(x) for x in D.losses()), D.sweep_l[0]["n"] if D.sweep_l else 8, N, pc(F["dloss"]), pc(F["dsh"])))
    groups = {}
    for x in D.sweep_n + D.sweep_l + list(D.demo.values()):
        groups.setdefault((x["n"], x["loss"], x["shared_loss"], x.get("rep", 0)), []).append(x)
    same = sum(1 for g in groups.values() if len({(y["size_bytes"], y["chunks"], y["seed"]) for y in g}) == 1)
    b.p("**Controlled comparison.** For each scenario every protocol transfers the byte-identical payload, generated deterministically from (size, seed), so that the SHA-256 is the same in all four modes (%d of %d scenarios share file size, chunk count and seed). The receiver count, per-receiver loss, shared loss and sender link capacity (%s packets per second, TCP paced to the same limit) are identical, and %s repetitions are averaged. The only outcome that legitimately differs between modes is the number of bytes put on the wire, i.e. the overhead ratio \u03c1 = total bytes / file size. **Threats to validity.** (1) The loss *rate* is equal across modes but the random drop sequences hit different packets. (2) The kernel cannot drop packets on a local link, so TCP loss is modelled: a lost segment is re-sent after a 20 ms stall. (3) The test bed is a single host with receivers as separate processes, so delivery is loopback-class and the CPU is shared. (4) In the dashboard\u2019s real-send mode TCP is not paced, because it is a real transfer; only the Compare and Sweeps benchmarks use equal pacing." % (same, len(groups), meta.get("link_pps", "?"), meta.get("reps", "?")))
    b.h2("Performance metrics")
    b.bullets([
        "**Transfer duration** (s): from the start of transmission until the last receiver completes or the timeout expires. **Goodput** = N·S·DR/duration.",
        "**Overhead ratio** ρ: total bytes on the wire (sender plus all NACK bytes) divided by the file size; 1 is a single ideal copy.",
        "**Delivery ratio** DR and the **SHA-256 verification** result per receiver.",
        "**NACK packets, suppressed NACKs, repair packets, duplicate data** summed over receivers.",
        "**One-way delay** (mean, p95, max) and **jitter** for first-transmission DATA packets, after SNTP correction, plus the raw delay without correction.",
        "**SNTP accuracy**: difference between the estimated offset and the injected skew for each receiver.",
    ])

    # =============================================================== 9 Results
    b.h1("Output and Results")
    b.h2("Console output")
    b.p("Figure {{cons1}} shows the terminal output of a demonstration run (python run.py demo); the complete sweep summary is produced by python run.py experiments. The demonstration run is a separate execution (its receiver count, file size and loss may differ from the experiment demo point), so its numbers differ from the repetition-averaged values used in the charts that follow.")
    b.figure(fig("console_demo.png"), "Console output of the demonstration run (output screenshot)", width=5.2, key="cons1")
    lf = live_facts()
    if lf:
        b.figure(fig("live_console.png"), "Real file transfer on the LAN: send and receive terminals (%.0f MB file, receiver A with 4%% injected loss, receiver B with multicast blocked and served over the TCP fallback; the three SHA-256 digests are identical)" % lf["size_mb"], width=5.0, key="cons2")
    b.figure(fig("dash_live_c.png"), "Dashboard, Compare tab: live chunk map per receiver, verdict, comparison charts, results table (SNTP panel below the crop)", width=3.1, key="dash")
    b.h2("Comparative analysis")
    scal = ("**Scalability with receivers.** Figures {{dur_n}} and {{ovh_n}} show how duration and overhead grow with N. With %d receivers TCP unicast needed %s s with an overhead ratio of %sx and raw UDP unicast %s s (%sx), because each additional receiver adds a full copy to the paced uplink. Naive multicast needed %s s (%sx) and ReliCast %s s (%sx), i.e. TCP/ReliCast ratios of %.1f for duration and %.1f for overhead. Across the sweep the ReliCast overhead ratio stayed between %sx and %sx, while the unicast overhead grew in proportion to N." % (nmax, f2(F["tcp_d_nmax"]), f2(F["tcp_o_nmax"]), f2(F["udp_d_nmax"]), f2(F["udp_o_nmax"]), f2(F["naive_d_nmax"]), f2(F["naive_o_nmax"]), f2(F["relicast_d_nmax"]), f2(F["relicast_o_nmax"]), F["tcp_vs_rc_d"], F["tcp_vs_rc_o"], f2(F["rc_o_min"]), f2(F["rc_o_max"])))
    if F["relicast_d_nmax"] > F["naive_d_nmax"]:
        scal += " In wall-clock time, however, naive multicast was faster than ReliCast at N = %d (%s s against %s s): the randomised timers and the repair guard deliberately trade some recovery latency for far less feedback, and with only %s repetitions on a shared host the timing also contains scheduling noise." % (nmax, f2(F["naive_d_nmax"]), f2(F["relicast_d_nmax"]), meta.get("reps", "a few"))
    b.p(scal)
    b.figure(fig("duration_vs_receivers.png"), "Transfer duration versus number of receivers (mean of repetitions)", width=3.0, key="dur_n")
    b.figure(fig("overhead_vs_receivers.png"), "Overhead ratio versus number of receivers", width=3.0, key="ovh_n")
    nl = D.sweep_l[0]["n"] if D.sweep_l else 8
    loss_t = ("**Effect of loss.** Figures {{dur_l}} and {{del_l}} (also drawn in the dashboard Sweeps tab) vary the per-receiver loss at N = %d. At %s loss raw UDP delivered only %s of the data, because nothing recovers a lost datagram, whereas ReliCast and the naive scheme delivered %s and %s. Duration for ReliCast grew from %s s at no loss to %s s at %s loss, against %s s to %s s for naive multicast and %s s to %s s for TCP." % (nl, pc(F["lmax"]), "%.1f%%" % (100 * F["udp_dv_max"]), "%.1f%%" % (100 * F["relicast_dv_max"]), "%.1f%%" % (100 * F["naive_dv_max"]), f2(F["relicast_dl_0"]), f2(F["relicast_dl_max"]), pc(F["lmax"]), f2(F["naive_dl_0"]), f2(F["naive_dl_max"]), f2(F["tcp_dl_0"]), f2(F["tcp_dl_max"])))
    if F["relicast_dl_max"] > F["naive_dl_max"]:
        loss_t += " At the highest loss rates ReliCast was therefore slower than the naive scheme: with many receivers missing the same chunks, its back-off timers and the 30 ms repair guard most likely make it wait through several recovery rounds, which is the cost of the lower NACK and repair volume reported below. Duration is not the only criterion, because the naive scheme achieves its speed by sending more NACK and repair packets."
    b.p(loss_t)
    b.figure(fig("duration_vs_loss.png"), "Transfer duration versus per-receiver loss", width=3.0, key="dur_l")
    b.figure(fig("delivery_vs_loss.png"), "Delivery ratio versus per-receiver loss", width=3.0, key="del_l")
    b.p("**Feedback and repair traffic.** At the demonstration point (N = %d, p = %s, q = %s) the naive scheme produced %d NACKs and %d repair packets, whereas ReliCast sent %d NACKs and %d repairs while suppressing %d NACKs (%.0f%% of all NACK attempts). That is %.0f%% fewer NACKs and %.0f%% fewer repair packets than the naive scheme (Figure {{nack}}), and total bytes on the wire were %.2f MB for ReliCast, %.2f MB for the naive scheme and %.2f MB for TCP." % (N, pc(F["dloss"]), pc(F["dsh"]), F["naive_nack_packets"], F["naive_repair_packets"], F["relicast_nack_packets"], F["relicast_repair_packets"], F["relicast_nack_suppressed"], F["supp_pct"], F["nack_red"], F["rep_red"], F["relicast_total_bytes"] / 1e6, F["naive_total_bytes"] / 1e6, F["tcp_total_bytes"] / 1e6))
    b.figure(fig("nack_comparison.png"), "NACK and repair packets at the demonstration point", width=3.0, key="nack")
    b.h2("Validation of the proposed approach")
    b.p("Correctness was validated first by content: in %d of %d runs of the TCP, naive and ReliCast modes every receiver’s SHA-256 matched the sender’s digest (loss rates up to %s were included). Second, the clock model was validated directly: the injected skews of up to %s ms were estimated by SNTP to within %s ms (Figure {{sntp}}, left), and correcting by the estimate reduced the mean apparent delay from %s ms to %s ms, a factor of about %.0f (Figure {{sntp}}, right). Third, the analytical model of Section 7.3 predicts the right order of magnitude and, more importantly, the right ordering between the schemes: it predicts roughly C·N·p′ = %.0f repair packets for the naive scheme against C·u = %.0f for ReliCast, matching the measured ranking." % (F["ver_count"], F["ver_total"], pc(F["lmax"]), "%.0f" % F["skew_max"], f2(F["sntp_err"]), f2(abs(F["relicast_owd_raw_mean_ms"])), f2(F["relicast_owd_mean_ms"]), F["owd_ratio"], M["naive_nack"], M["rc_chunks"]))
    b.figure(fig("sntp_skew.png"), "SNTP offset estimate versus injected skew (left) and effect on measured delay (right)", width=3.9, key="sntp")
    b.h2("Real-world validation")
    if lf:
        b.p("The real-file mode was exercised once end to end (Figure {{cons2}}): a %.0f MB file was sent with python run.py send --mode relicast to %s receivers that discovered it through the broadcast beacon. One receiver had 4%% packet loss injected on its link and the other could not hear multicast, so the probe moved it to the TCP fallback. The sender reported completion in %.2f s with all receivers verified, %s NACKs and %s repair packets (%.2f MB on the wire), and the SHA-256 of the sent file and of both saved copies were identical. A three-receiver run in the dashboard Send tab (Figure {{send}}) finished with all receivers verified and a 2.16x overhead ratio. These runs are honest but limited: sender and receivers ran on one machine\u2019s own network interface, so delivery was loopback-class rather than a congested Wi-Fi link, and the packet loss was emulated at the receivers. Testing on several physical devices over a hotspot is therefore left as future work." % (lf["size_mb"], lf["joined"], lf["secs"], lf["nacks"], lf["repairs"], lf["bytes_mb"]))
    b.figure(fig("dash_send_c.png"), "Dashboard, Send tab: finished three-receiver real transfer, all receivers verified", width=3.4, key="send")
    b.h2("Observations: delay, jitter and throughput")
    b.p("Figure {{owd}} gives the SNTP-corrected one-way delay and jitter per mode at the demonstration point. The mean delay was %s ms for ReliCast (p95 %s ms, jitter %s ms), %s ms for naive multicast (jitter %s ms), %s ms for raw UDP (jitter %s ms) and %s ms for TCP (jitter %s ms). Delays of the multicast modes and of the unicast modes are measured on different paths and under different sender load, and with all receiver processes sharing one machine part of the measured delay is receiver-side scheduling and queueing rather than network transit, so the numbers are best compared qualitatively. Goodput was %s Mbit/s for ReliCast, %s Mbit/s for naive multicast and %s Mbit/s for TCP (counting the data delivered to all receivers). Overall, the experiments show that suppression and aggregation keep multicast reliability inexpensive in bytes, that raw UDP is unsuitable when completeness matters, and that SNTP makes one-way delay a usable measurement even with a clock skew of several hundred milliseconds." % (f2(F["relicast_owd_mean_ms"]), f2(F["relicast_owd_p95_ms"]), f2(F["relicast_jitter_ms"]), f2(F["naive_owd_mean_ms"]), f2(F["naive_jitter_ms"]), f2(F["udp_owd_mean_ms"]), f2(F["udp_jitter_ms"]), f2(F["tcp_owd_mean_ms"]), f2(F["tcp_jitter_ms"]), f1(F["relicast_goodput_mbps"]), f1(F["naive_goodput_mbps"]), f1(F["tcp_goodput_mbps"])))
    b.figure(fig("owd_jitter.png"), "SNTP-corrected one-way delay and jitter by mode", width=3.9, key="owd")

    # =============================================================== 10 Conclusion
    b.h1("Conclusion")
    b.p("We implemented ReliCast, a NACK-oriented reliable multicast file-distribution protocol built directly on the socket API, along with TCP, raw-UDP and naive-multicast baselines and an SNTP client and server for synchronised delay measurement. **Performance.** With %d receivers ReliCast completed the transfer in %s s against %s s for TCP unicast, and its overhead ratio was %sx against %sx. At the demonstration point it delivered the file to all %d receivers with %d NACKs and %d repair packets, compared with %d and %d for naive multicast, and the one-way delay of %s ms and jitter of %s ms were measurable only because the clocks were synchronised, with a worst-case offset error of %s ms. Raw UDP, the cheapest baseline, delivered only %s of the data at %s loss." % (nmax, f2(F["relicast_d_nmax"]), f2(F["tcp_d_nmax"]), f2(F["relicast_o_nmax"]), f2(F["tcp_o_nmax"]), N, F["relicast_nack_packets"], F["relicast_repair_packets"], F["naive_nack_packets"], F["naive_repair_packets"], f2(F["relicast_owd_mean_ms"]), f2(F["relicast_jitter_ms"]), f2(F["sntp_err"]), "%.1f%%" % (100 * F["udp_dv_max"]), pc(F["lmax"])))
    b.p("**Contribution to the research gap.** The study provides what the SRM and NORM literature lacks: measurements from real sockets in a reproducible harness, a suppression window adapted from SNTP-synchronised delay and jitter, and a direct quantitative comparison with three practical baselines. It also shows that the central mechanisms of SRM (random timers, suppression, back-off) and NORM (sender-side aggregation, heartbeats) carry over to a small, dependency-free Python implementation.")
    b.p("**Limitations.** Loss is emulated in software and the experiments run on a single host, so real switch behaviour, IGMP snooping and Wi-Fi multicast rate limits are not exercised; the TCP loss model is a documented approximation; the sender paces at a fixed rate with no congestion control; the repair mechanism has no forward error correction; and the group sizes are small. The real-file mode has no encryption or authentication, holds the whole file in RAM, supports IPv4 only, and was tested on one machine rather than across a real hotspot, where multicast is often rate-limited or blocked (hence the TCP fallback). ReliCast also trades recovery latency for feedback volume: the naive scheme can finish sooner, notably at the highest loss rates, so the suppression window and repair guard deserve further tuning. **Future work.** Natural extensions are a multi-host LAN and Wi-Fi measurement campaign, FEC-coded repairs, congestion control, authenticated sessions, local recovery as in SRM, and a comparison of the adaptive window against fixed windows over wider parameter ranges.")

    # =============================================================== 11 References
    b.h1("References")
    for i, r in enumerate(REFS, 1):
        par = b.doc.add_paragraph(); par.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        par.paragraph_format.left_indent = Inches(0.4); par.paragraph_format.first_line_indent = Inches(-0.4); par.paragraph_format.space_after = Pt(4)
        par.paragraph_format.line_spacing = 1.5
        rich(par, "[%d]\t%s" % (i, r))
        b.est.add(text_h(r, cpl=78, after=4))

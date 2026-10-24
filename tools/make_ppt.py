"""Build ReliCast_PPT.pptx (16:9).   usage: make_ppt.py [experiments.json] [out.pptx]"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from PIL import Image
from common import *
from report_text import facts, REFS

NAVY, SLATE, GREEN, LIGHT, MUTED = RGBColor(0x11, 0x18, 0x27), RGBColor(0x37, 0x41, 0x51), RGBColor(0x16, 0xA3, 0x4A), RGBColor(0xF3, 0xF4, 0xF6), RGBColor(0x6B, 0x72, 0x80)
FONT = "Calibri"
W, H = 13.333, 7.5


def hexc(h): return RGBColor.from_string(h.lstrip("#").upper())


class Deck:
    def __init__(self, T):
        self.prs = Presentation(); self.prs.slide_width, self.prs.slide_height = Inches(W), Inches(H)
        self.T, self.n = T, 0

    def slide(self, title=None, notes=None, section=None):
        s = self.prs.slides.add_slide(self.prs.slide_layouts[6]); self.n += 1
        if title:
            bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.18), Inches(H)); bar.fill.solid(); bar.fill.fore_color.rgb = GREEN; bar.line.fill.background()
            self.text(s, title, 0.6, 0.3, 12.1, 0.9, 30, True, NAVY)
            ln = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(0.6), Inches(1.12), Inches(1.2), Inches(0.05)); ln.fill.solid(); ln.fill.fore_color.rgb = GREEN; ln.line.fill.background()
            self.text(s, "ReliCast  |  BMSCE CSE  |  Network Programming %s" % self.T["year"], 0.6, 7.05, 8, 0.3, 10, False, MUTED)
            self.text(s, str(self.n), 12.2, 7.05, 0.7, 0.3, 10, False, MUTED, align=PP_ALIGN.RIGHT)
        if notes: s.notes_slide.notes_text_frame.text = notes
        return s

    def text(self, s, text, x, y, w, h, size=18, bold=False, color=SLATE, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, italic=False):
        tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)); tf = tb.text_frame; tf.word_wrap = True; tf.vertical_anchor = anchor
        tf.margin_left = tf.margin_right = Inches(0.05)
        for i, line in enumerate(text.split("\n")):
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph(); p.alignment = align
            r = p.add_run(); r.text = line; f = r.font; f.size = Pt(size); f.bold = bold; f.italic = italic; f.color.rgb = color; f.name = FONT
        return tb

    def bullets(self, s, items, x, y, w, h, size=20, gap=8, color=SLATE):
        tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)); tf = tb.text_frame; tf.word_wrap = True
        for i, it in enumerate(items):
            lvl = 1 if it.startswith("  ") else 0
            p = tf.paragraphs[0] if i == 0 else tf.add_paragraph(); p.space_after = Pt(gap)
            txt = it.strip()
            r0 = p.add_run(); r0.text = ("•  " if lvl == 0 else "–  "); r0.font.color.rgb = GREEN; r0.font.size = Pt(size - 2 * lvl); r0.font.bold = True; r0.font.name = FONT
            if txt.startswith("**") and "**" in txt[2:]:
                head, rest = txt[2:].split("**", 1)
                r = p.add_run(); r.text = head; r.font.bold = True; r.font.size = Pt(size - 2 * lvl); r.font.color.rgb = NAVY; r.font.name = FONT
                txt = rest
            r = p.add_run(); r.text = txt; r.font.size = Pt(size - 2 * lvl); r.font.color.rgb = color; r.font.name = FONT
            if lvl: p.level = 1
        return tb

    def card(self, s, x, y, w, h, title, body, fill=LIGHT, accent=GREEN, tsize=18, bsize=14):
        r = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h)); r.adjustments[0] = 0.05
        r.fill.solid(); r.fill.fore_color.rgb = fill; r.line.color.rgb = accent; r.line.width = Pt(1.5)
        self.text(s, title, x + 0.15, y + 0.1, w - 0.3, 0.5, tsize, True, NAVY)
        self.text(s, body, x + 0.15, y + 0.62, w - 0.3, h - 0.7, bsize, False, SLATE)

    def pic(self, s, path, x, y, w, h, caption=None):
        if not os.path.exists(path):
            r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h)); r.fill.solid(); r.fill.fore_color.rgb = LIGHT; r.line.color.rgb = MUTED
            self.text(s, "[missing: %s]" % os.path.basename(path), x, y + h / 2 - 0.2, w, 0.4, 12, False, MUTED, PP_ALIGN.CENTER); return
        with Image.open(path) as im: ar = im.width / im.height
        ww, hh = (w, w / ar) if w / h < ar else (h * ar, h)
        s.shapes.add_picture(path, Inches(x + (w - ww) / 2), Inches(y + (h - hh) / 2), Inches(ww), Inches(hh))
        if caption: self.text(s, caption, x, y + h + 0.02, w, 0.3, 11, False, MUTED, PP_ALIGN.CENTER, italic=True)

    def takeaway(self, s, text):
        r = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(0.6), Inches(6.35), Inches(12.1), Inches(0.6)); r.adjustments[0] = 0.2
        r.fill.solid(); r.fill.fore_color.rgb = NAVY; r.line.fill.background()
        self.text(s, text, 0.8, 6.38, 11.7, 0.55, 15, True, RGBColor(255, 255, 255), anchor=MSO_ANCHOR.MIDDLE)


def build(D, T, out):
    F = facts(D); fig = lambda n: os.path.join(FIGS, n); f2 = lambda x: "%.2f" % x
    pc = lambda x: "%g%%" % (x * 100)
    d = Deck(T); nmax = F["nmax"]
    # 1 title
    s = d.slide()
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(W), Inches(H)); bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
    st = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(0.35), Inches(H)); st.fill.solid(); st.fill.fore_color.rgb = GREEN; st.line.fill.background()
    white, soft = RGBColor(255, 255, 255), RGBColor(0xD1, 0xD5, 0xDB)
    logo = os.path.join(ASSETS, "logo.png")
    if os.path.exists(logo): s.shapes.add_picture(logo, Inches(0.9), Inches(0.6), Inches(0.9), Inches(0.94))
    d.text(s, "B.M.S. College of Engineering  |  Department of Computer Science and Engineering", 2.0, 0.85, 10.5, 0.4, 16, False, soft)
    d.text(s, "ReliCast", 0.9, 2.0, 11.5, 1.1, 60, True, white)
    d.text(s, "NACK-Suppressed Reliable Multicast for LAN Content Distribution\nwith SNTP-Synchronised Measurement", 0.9, 3.1, 11.5, 1.3, 26, False, hexc("86EFAC"))
    names = "   |   ".join("%s (%s)" % (m["name"], m["usn"]) for m in T["members"])
    d.text(s, names, 0.9, 4.9, 11.8, 0.6, 15, False, white)
    d.text(s, "%s (%s) - Guide: %s, %s\n%s (%s)  |  Alternate Assessment Tool, %s" % (T["course_title"], T["course_code"], T["guide"], T["guide_designation"], "AAT Presentation", T["year"], T["year"]), 0.9, 5.7, 11.5, 0.9, 14, False, soft)
    s.notes_slide.notes_text_frame.text = "Introduce the team and the topic: reliable file distribution to many LAN receivers using multicast with NACK suppression."
    # 2 problem
    s = d.slide("Problem and use case", "A teacher or admin pushes a file to many laptops on one LAN.")
    d.bullets(s, ["**Use case: **push slides or an update package to every laptop in a lab",
                  "**TCP to each receiver: **sender transmits N copies, so time and bytes grow linearly with N",
                  "**Raw UDP multicast: **one copy, but no retransmission - data is silently lost",
                  "**Need: **one multicast copy + reliable repair that does not cause a NACK implosion",
                  "**Our answer: **ReliCast = multicast DATA + receiver-driven NACKs with randomised suppression + SNTP-synchronised measurement"], 0.6, 1.5, 7.3, 4.8, 20)
    d.card(s, 8.3, 1.6, 4.4, 1.9, "Measured at N = %d" % nmax, "TCP overhead %sx\nReliCast overhead %sx" % (f2(F["tcp_o_nmax"]), f2(F["relicast_o_nmax"])), bsize=20)
    d.card(s, 8.3, 3.8, 4.4, 1.9, "Raw UDP at %s loss" % pc(F["lmax"]), "Delivers only %.1f%% of the data" % (100 * F["udp_dv_max"]), accent=hexc("d97706"), bsize=20)
    # 3 why multicast
    s = d.slide("Why multicast?", "One copy on the wire regardless of N; the network replicates it.")
    d.bullets(s, ["**Unicast: **N copies leave the sender; overhead ratio ~ N", "**Broadcast: **reaches everyone, interested or not, one subnet only", "**Multicast (RFC 1112): **one datagram to a group address; receivers join via IGMP; TTL limits scope",
                  "**Price: **UDP semantics - the application must supply reliability and pacing"], 0.6, 1.5, 5.6, 4.6, 19)
    d.pic(s, fig("bytes_on_wire.png"), 6.4, 1.4, 6.4, 4.8, "Bytes on the wire at the demo point (N = %d)" % F["dn"])
    d.takeaway(s, "Demo point: TCP sent %.2f MB, naive multicast %.2f MB, ReliCast %.2f MB (file = %.2f MB)" % (F["tcp_total_bytes"] / 1e6, F["naive_total_bytes"] / 1e6, F["relicast_total_bytes"] / 1e6, F["size_bytes"] / 1e6))
    # 4 papers
    s = d.slide("Research papers reviewed", "Only the two foundational protocols, in depth.")
    d.card(s, 0.6, 1.5, 5.95, 4.7, "SRM - Floyd et al., IEEE/ACM ToN 1997",
           "Problem: ACK implosion; sender cannot track all receivers\nMechanism: random request timer in [C1*d, (C1+C2)*d]; suppress if another request is heard; exponential back-off; any member can repair; adaptive timers\nResults: ns-2 chain / star / tree topologies, wb whiteboard\nLimits: session-message overhead, multicast repairs, simulation only\nUsed here: random timers, suppression, back-off", bsize=14)
    d.card(s, 6.8, 1.5, 5.95, 4.7, "NORM - Adamson et al., RFC 5740, 2009",
           "Problem: scalable NACK-based reliability over multicast\nMechanism: GRTT-scaled random back-off, NACK suppression, sender repair aggregation, flush/heartbeat, optional FEC and congestion control\nResults: standards-track specification (no measurement campaign)\nLimits: GRTT state, no one-way-delay method, complex\nUsed here: repair hold-off + union, heartbeat", bsize=14, accent=hexc("2563eb"))
    d.text(s, "Supporting specs: RFC 4330 (SNTPv4), RFC 1112 (host multicast)", 0.6, 6.4, 12, 0.4, 14, False, MUTED, italic=True)
    # 5 gap
    s = d.slide("Research gap", "Narrowed from several gaps to one.")
    d.bullets(s, ["SRM / NORM windows come from distance or GRTT estimates - not tuned from measured one-way delay and jitter",
                  "SRM results are ns-2 simulations; RFC 5740 has no measurements - little data from real sockets",
                  "One-way delay needs synchronised clocks, so papers report RTT or simulated time",
                  "Comparisons with TCP-unicast and raw UDP baselines are mostly qualitative"], 0.6, 1.45, 12, 3.2, 18, 6)
    d.card(s, 0.6, 4.75, 12.1, 1.55, "Chosen gap", "A real-socket study of NACK-suppressed multicast with an SNTP-synchronised, delay-adaptive window, benchmarked against TCP, raw UDP and un-suppressed multicast in one harness.", bsize=17)
    # 6 architecture
    s = d.slide("System architecture", "One sender process, N receiver processes.")
    d.pic(s, fig("arch_diagram.png"), 0.6, 1.35, 12.1, 5.55)
    # 7 protocol
    s = d.slide("Protocol and packet format", "24-byte header in network byte order; ALF - each packet self-describing.")
    d.pic(s, fig("packet_format.png"), 0.6, 1.35, 12.1, 1.5)
    d.bullets(s, ["**DATA / REPAIR: **1 KB chunk, seq, total, SNTP-corrected sender timestamp", "**HEARTBEAT: **carries highest seq sent - exposes tail losses", "**NACK: **receiver id + inclusive seq ranges", "**FIN / PROBE: **end of session / interface test",
                  "**TCP control: **JSON meta (size, chunks, SHA-256, group, SNTP port) and final stats"], 0.6, 3.0, 6.0, 3.8, 17, 6)
    d.pic(s, fig("state_diagram.png"), 6.7, 3.1, 6.1, 2.4, "Receiver state machine")
    # 8 algorithm
    s = d.slide("Algorithm: NACK suppression", "Randomised timer, suppression on overheard NACK, back-off, sender hold-off and aggregation.")
    d.pic(s, fig("nack_flowchart.png"), 0.6, 1.3, 5.4, 5.6)
    d.bullets(s, ["**Timer: **T = U[0,1) x W x 2^k, W = clamp(20 + 4(owd + 4 jitter), 20, 200) ms",
                  "**Suppression: **an overheard NACK covering my gap cancels my timer",
                  "**Expected NACKs per lost chunk: **~ 1 + M*d/W (M receivers missing it, d = delay) vs M without suppression",
                  "**Sender: **10 ms hold-off, repair the union of ranges once, 30 ms repair guard",
                  "**Result at demo point: **%d NACKs vs %d naive (%.0f%% fewer); %d suppressed" % (F["relicast_nack_packets"], F["naive_nack_packets"], F["nack_red"], F["relicast_nack_suppressed"])], 6.3, 1.5, 6.5, 5, 17, 8)
    # 9 SNTP
    s = d.slide("SNTP: measuring one-way delay", "Receivers have injected clock skew of +/-100..500 ms; SNTP corrects it.")
    d.pic(s, fig("sntp_skew.png"), 0.6, 1.4, 7.4, 3.9)
    d.bullets(s, ["**Offset: **theta = ((t2 - t1) + (t3 - t4)) / 2", "**Delay: **delta = (t4 - t1) - (t3 - t2)", "**Best of 5 **samples (min delay) per receiver", "**OWD = **(t_rx - theta) - ts_sender"], 8.3, 1.5, 4.5, 3.8, 18, 8)
    d.takeaway(s, "Skews up to %.0f ms recovered to within %.2f ms; mean OWD %.1f ms raw -> %.2f ms corrected" % (F["skew_max"], F["sntp_err"], abs(F["relicast_owd_raw_mean_ms"]), F["relicast_owd_mean_ms"]))
    # 10 syllabus
    s = d.slide("Socket programming and syllabus mapping", "Every call used is a syllabus topic.")
    rows = [("Unit", "Feature", "Calls / options"),
            ("1", "Sockets, byte order, buffers", "socket(), struct '!2sBBIIIQ', SO_RCVBUF"),
            ("2", "TCP control channel, socket options", "bind / listen / accept / connect / sendall / recv; SO_REUSEADDR, SO_REUSEPORT, IP_MULTICAST_TTL / IF / LOOP"),
            ("3", "UDP data path, no flow control", "sendto / recvfrom, pacing, select(), timeouts"),
            ("4", "Unicast vs broadcast vs multicast", "IP_ADD_MEMBERSHIP (ip_mreq), 239.255.42.99, TTL scope"),
            ("5", "SNTP clock sync", "48-byte NTP packet over UDP, client + server (RFC 4330)")]
    tbl = s.shapes.add_table(len(rows), 3, Inches(0.6), Inches(1.5), Inches(12.1), Inches(4.6)).table
    for ci, wd in enumerate((0.9, 4.2, 7.0)): tbl.columns[ci].width = Inches(wd)
    for ri, row in enumerate(rows):
        for ci, v in enumerate(row):
            c = tbl.cell(ri, ci); c.text = v; p = c.text_frame.paragraphs[0]; p.runs[0].font.size = Pt(16 if ri else 17); p.runs[0].font.name = FONT; p.runs[0].font.bold = (ri == 0)
            p.runs[0].font.color.rgb = RGBColor(255, 255, 255) if ri == 0 else SLATE
            c.fill.solid(); c.fill.fore_color.rgb = NAVY if ri == 0 else (LIGHT if ri % 2 else RGBColor(255, 255, 255)); c.vertical_anchor = MSO_ANCHOR.MIDDLE
    # 11 demo
    s = d.slide("Demo and dashboard", "Run python run.py dashboard; compare the four modes live.")
    d.pic(s, fig("console_demo.png"), 0.6, 1.4, 7.0, 4.9, "Console demo run")
    dash = fig("dash_live_c.png")
    if os.path.exists(dash): d.pic(s, dash, 7.8, 1.35, 5.0, 3.5, "Dashboard: Compare tab")
    else:
        d.card(s, 7.8, 1.4, 5.0, 3.0, "Dashboard", "[screenshot placeholder]\nrelicast/results/figs/dashboard.png", bsize=14)
    d.bullets(s, ["Live chunk map, 8 charts, SNTP card", "Sweeps tab from experiments.json"], 7.8, 5.2, 5, 1.1, 15, 3)
    d.takeaway(s, "Demo: %d receivers, %s loss, %s shared loss, %d KB file - ReliCast %d NACKs (%d suppressed), verified: %s" % (F["dn"], pc(F["dloss"]), pc(F["dsh"]), F["size_bytes"] // 1024, F["relicast_nack_packets"], F["relicast_nack_suppressed"], F["relicast_ver"]))
    # 12-14 results
    s = d.slide("Results 1: scaling with receivers", "Duration and overhead versus N.")
    d.pic(s, fig("duration_vs_receivers.png"), 0.6, 1.3, 6.0, 4.5); d.pic(s, fig("overhead_vs_receivers.png"), 6.7, 1.3, 6.0, 4.5)
    d.text(s, "Controlled comparison: byte-identical payload (same SHA-256) in all 4 modes, same N / loss / %s pkt/s link (TCP paced too), %s reps averaged; only bytes on the wire may differ." % (D.meta.get("link_pps", "?"), D.meta.get("reps", "?")), 0.6, 5.85, 12.1, 0.45, 13, False, MUTED, italic=True)
    t = "N = %d: overhead TCP %sx vs ReliCast %sx; duration TCP %ss, naive %ss, ReliCast %ss" % (nmax, f2(F["tcp_o_nmax"]), f2(F["relicast_o_nmax"]), f2(F["tcp_d_nmax"]), f2(F["naive_d_nmax"]), f2(F["relicast_d_nmax"]))
    d.takeaway(s, t)
    s = d.slide("Results 2: effect of packet loss", "Duration and delivery ratio versus loss at N = 8.")
    d.pic(s, fig("duration_vs_loss.png"), 0.6, 1.35, 6.0, 4.8); d.pic(s, fig("delivery_vs_loss.png"), 6.7, 1.35, 6.0, 4.8)
    t = "At %s loss: UDP delivers %.1f%%; ReliCast and naive deliver 100%%" % (pc(F["lmax"]), 100 * F["udp_dv_max"])
    if F["relicast_dl_max"] > F["naive_dl_max"]: t += "; ReliCast pays latency (%ss vs %ss naive)" % (f2(F["relicast_dl_max"]), f2(F["naive_dl_max"]))
    d.takeaway(s, t)
    s = d.slide("Results 3: feedback traffic, delay and jitter", "NACK/repair counts and SNTP-corrected OWD at the demo point.")
    d.pic(s, fig("nack_comparison.png"), 0.6, 1.35, 5.6, 4.8); d.pic(s, fig("owd_jitter.png"), 6.4, 1.35, 6.4, 4.8)
    d.takeaway(s, "%.0f%% fewer NACKs and %.0f%% fewer repairs than naive multicast; OWD %s ms, jitter %s ms (ReliCast)" % (F["nack_red"], F["rep_red"], f2(F["relicast_owd_mean_ms"]), f2(F["relicast_jitter_ms"])))
    # real-world slides
    s = d.slide("Real-world mode: discovery and lobby", "python run.py send <file> / receive; dashboard Send and Receive tabs.")
    d.pic(s, fig("discovery_diagram.png"), 0.6, 1.4, 6.6, 3.3)
    d.bullets(s, ["**Send: **python run.py send <file> --mode relicast|naive|tcp|udp", "**Receive: **python run.py receive (or dashboard tabs)", "**Discovery: **UDP broadcast beacon on port 5599 every second (Unit 4)", "**Lobby: **TCP JSON lines - meta, ready, probe, start{transport}, progress, done", "**Saved **to ~/ReliCast/received after SHA-256 check", "**Phones: **/download and /upload pages with --lan"], 7.4, 1.4, 5.4, 5.2, 16, 6)
    d.text(s, "Cross-platform: no SO_REUSEPORT on Windows, wildcard multicast bind, perf_counter-anchored clock, ANSI enable", 0.6, 5.0, 6.6, 0.9, 13, False, MUTED, italic=True)
    s = d.slide("Multicast probe and TCP fallback", "Hotspots and APs often block multicast; hybrid delivery keeps the session alive.")
    d.pic(s, fig("lobby_sequence.png"), 0.6, 1.3, 7.2, 5.6)
    d.bullets(s, ["Sender multicasts 10 PROBE packets; each receiver replies mcast_ok over TCP", "Receivers that hear nothing are served over TCP", "Others keep multicast + NACK repair", "One blocked device never stalls the session"], 8.1, 1.6, 4.7, 4.5, 18, 10)
    s = d.slide("Real transfer evidence", "6 MB file, one receiver with 4% injected loss, one with multicast blocked.")
    d.pic(s, fig("live_console.png"), 0.6, 1.35, 7.4, 4.9, "Send / receive terminals")
    d.pic(s, fig("dash_send_c.png"), 8.2, 1.35, 4.6, 3.2, "Dashboard Send tab: all verified")
    d.bullets(s, ["Identical SHA-256 on all copies", "One machine, own interface: loopback-class delivery, emulated loss"], 8.2, 4.8, 4.6, 1.5, 14, 4)
    d.takeaway(s, "Honest scope: real multi-device hotspot testing is future work")
    # 15 conclusion
    s = d.slide("Conclusion", "Summarise findings, contribution and honest limits.")
    d.bullets(s, ["**Bytes: **ReliCast overhead stays %s-%sx for N up to %d; unicast grows ~ N" % (f2(F["rc_o_min"]), f2(F["rc_o_max"]), nmax),
                  "**Reliability: **100%% delivery with SHA-256 verification (%s); raw UDP only %.1f%% at %s loss" % (F["rc_ver_txt"], 100 * F["udp_dv_max"], pc(F["lmax"])),
                  "**Feedback: **randomised suppression + aggregation cut NACKs by %.0f%% and repairs by %.0f%% at the demo point" % (F["nack_red"], F["rep_red"]),
                  "**Measurement: **SNTP recovers skews within %.2f ms, making real-socket OWD and jitter measurable" % F["sntp_err"],
                  "**Limitation: **emulated loss, one host; at high loss ReliCast trades latency for fewer packets"], 0.6, 1.5, 12.1, 5, 20, 12)
    # 16 future
    s = d.slide("Future work", None)
    d.bullets(s, ["Multi-host LAN and Wi-Fi measurement campaign (IGMP snooping, multicast rates)", "FEC-coded repairs (NORM-style parity)", "Congestion control instead of a fixed pacing rate", "SRM-style local recovery and receiver-side repair", "Authenticated sessions; larger groups; wider comparison of adaptive vs fixed windows"], 0.6, 1.6, 12, 4.8, 22, 14)
    # 17 Q&A
    s = d.slide()
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, Inches(W), Inches(H)); bg.fill.solid(); bg.fill.fore_color.rgb = NAVY; bg.line.fill.background()
    d.text(s, "Questions?", 0, 2.6, W, 1.2, 54, True, white, PP_ALIGN.CENTER)
    d.text(s, "References: Floyd et al., IEEE/ACM ToN 1997 (SRM)  |  RFC 5740 (NORM)  |  RFC 4330 (SNTP)  |  RFC 1112", 0, 4.3, W, 0.5, 14, False, soft, PP_ALIGN.CENTER)
    d.prs.core_properties.title = "ReliCast"; d.prs.core_properties.author = ", ".join(m["name"] for m in T["members"])
    d.prs.save(out)
    return d.n


def main():
    a = sys.argv[1:]
    D = Data(a[0] if a else None); out = a[1] if len(a) > 1 else os.path.join(ROOT, "ReliCast_PPT.pptx")
    n = build(D, load_team(), out)
    from pptx import Presentation as P
    pr = P(out)
    print("data:", D.path); print("slides: %d, pictures: %d" % (len(pr.slides), sum(1 for s in pr.slides for sh in s.shapes if sh.shape_type == 13)))
    print("wrote", out)


if __name__ == "__main__":
    main()

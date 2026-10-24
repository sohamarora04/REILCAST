"""Render a text file as a terminal-style PNG.  usage: render_console.py in.txt out.png [title] [max_lines]"""
import os, sys, textwrap
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image, ImageDraw, ImageFont
from common import *

FONT = "/System/Library/Fonts/Menlo.ttc"


def render(text, out, title="Terminal", cols=100, max_lines=48, size=15):
    try:
        font = ImageFont.truetype(FONT, size)
    except Exception:
        font = ImageFont.load_default()
    mx = max((len(l) for l in text.replace("\t", "    ").splitlines()), default=0)
    cols = max(cols, min(mx, 140))
    lines = []
    for ln in text.replace("\t", "    ").splitlines():
        lines += textwrap.wrap(ln, cols, subsequent_indent="    ", drop_whitespace=False) or [""]
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + ["... (%d more lines)" % (len(lines) - max_lines + 1)]
    bb = font.getbbox("M")
    cw = font.getlength("M") if hasattr(font, "getlength") else bb[2]
    lh = int(size * 1.35)
    pad, bar = 18, 34
    W = int(cw * min(cols, max(len(l) for l in lines) + 1)) + 2 * pad
    W = max(W, 560)
    H = bar + pad * 2 + lh * len(lines)
    im = Image.new("RGB", (W, H), "#1e1e1e")
    d = ImageDraw.Draw(im)
    d.rectangle([0, 0, W, bar], fill="#3a3a3a")
    for i, c in enumerate(["#ff5f56", "#ffbd2e", "#27c93f"]):
        d.ellipse([14 + i * 22, 11, 26 + i * 22, 23], fill=c)
    d.text((W / 2 - len(title) * 3.5, 9), title, fill="#d4d4d4", font=ImageFont.truetype(FONT, 13) if os.path.exists(FONT) else font)
    y = bar + pad
    for ln in lines:
        col = "#d4d4d4"
        s = ln.lstrip()
        if ln.startswith("$"): col = "#4ec9b0"
        elif s.startswith("==") or s.startswith("[tcp]") or s.startswith("[udp]") or s.startswith("[naive]") or s.startswith("[relicast]"): col = "#dcdcaa"
        elif "verified=True" in ln or "delivery=1.000" in ln: col = "#6a9955"
        elif "ERROR" in ln or "verified=False" in ln: col = "#f48771"
        d.text((pad, y), ln, fill=col, font=font)
        y += lh
    im.save(out)
    return out


if __name__ == "__main__":
    if len(sys.argv) >= 3:
        render(open(sys.argv[1], encoding="utf-8", errors="replace").read(), sys.argv[2], *(sys.argv[3:4] or ["Terminal"]), **({"max_lines": int(sys.argv[4])} if len(sys.argv) > 4 else {}))
    else:
        D = Data()
        open(os.path.join(RESULTS, "experiments_summary.txt"), "w").write(summary_text(D))
        render(open(default_console_path(), encoding="utf-8", errors="replace").read(), os.path.join(FIGS, "console_demo.png"), "relicast - demo run")
        render(summary_text(D), os.path.join(FIGS, "console_summary.png"), "relicast - experiments summary", cols=110)
        print("console images written")

"""One-shot build: charts -> console renders -> report -> ppt.
usage (from relicast/):  ../.venv/bin/python tools/build_docs.py [experiments.json]
Edit relicast/team.json (names, USNs, guide, HoD) and simply re-run."""
import os, subprocess, sys
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from common import *


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else default_data_path()
    if not os.path.exists(path):
        import gen_sample; gen_sample.main(); path = default_data_path()
    if not os.path.exists(os.path.join(RESULTS, "console_demo.sample.txt")) and "sample" in path:
        import gen_sample; gen_sample.main()
    print("== data:", path, "| console:", default_console_path())
    import make_charts, render_console, make_report, make_ppt
    from common import Data, summary_text
    D = Data(path)
    print("== 1/4 charts"); make_charts.main(path)
    print("== 2/4 console renders")
    open(os.path.join(RESULTS, "experiments_summary.txt"), "w").write(summary_text(D))
    render_console.render(open(default_console_path(), encoding="utf-8", errors="replace").read(), os.path.join(FIGS, "console_demo.png"), "relicast - demo run")
    render_console.render(summary_text(D), os.path.join(FIGS, "console_summary.png"), "relicast - experiments summary", cols=110)
    lc = os.path.join(RESULTS, "live_console.txt")
    if os.path.exists(lc):
        render_console.render(open(lc, encoding="utf-8", errors="replace").read(), os.path.join(FIGS, "live_console.png"), "real file transfer on the LAN", cols=100)
    print("== 3/4 report")
    sys.argv = ["make_report.py", path]; make_report.main()
    print("== 4/4 slides")
    sys.argv = ["make_ppt.py", path]; make_ppt.main()


if __name__ == "__main__":
    main()

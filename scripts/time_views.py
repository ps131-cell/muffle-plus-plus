"""Render time of every view and workbench, for the table in docs/ux.md §6: AppTest on the release
bundle, with the load average beside each number.

    python scripts/time_views.py [--bundle outputs/demo_bundle.pt] [--out timing.json]

A server compiles the app once per process (its script cache, with Streamlit's "magic" pass);
AppTest makes a new cache on every run, which adds 0.4-0.8 s to each. One cache is shared here,
so a rerun costs what it costs on a server. To compare two trees, run this script from each in
turn, alternating, so both see the same load. Needs Linux or WSL (the app's budget module).
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VIEWS = ("Tests", "Timeline", "Evolution", "Import tests")
SLIDE = ("Pathology slide", None, "Diagnostic H&E section(s) (GDC, open access)")
PLAN = {  # file -> the tests to open: (type, month or None, name or None for the first)
    "SYNTHETIC-001": [("Lab", 24, "CA 15-3"),
                      ("ctDNA (liquid biopsy)", 21, "ctDNA panel (synthetic series)"),
                      ("Sequencing", 0, None), ("Imaging", 24, None),
                      ("Pathology report", -40, "Diagnosis"), ("Clinic note", 13, "Clinic visit")],
    "Case 299": [SLIDE, ("Data layer", None, "RNA-seq (STAR TPM)"), ("Document", None, None)],
    "Case 730": [SLIDE],
}


def load() -> str:
    return " ".join(Path("/proc/loadavg").read_text().split()[:3])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--bundle", default=str(ROOT / "outputs" / "demo_bundle.pt"))
    ap.add_argument("--out", default="timing.json")
    args = ap.parse_args()
    os.chdir(ROOT)
    os.environ["MUFFLE_BUNDLE"] = args.bundle
    os.environ.setdefault("MUFFLE_SLIDE_TILES", "off")
    for key in ("NEBIUS_API_KEY", "TAVILY_API_KEY"):  # no live calls while timing
        os.environ.pop(key, None)

    import streamlit.testing.v1.app_test as app_test
    import streamlit.testing.v1.local_script_runner as runner
    from streamlit.runtime.scriptrunner.script_cache import ScriptCache
    from streamlit.testing.v1 import AppTest

    cache = ScriptCache()
    app_test.ScriptCache = runner.ScriptCache = lambda: cache
    rows: list[dict] = []

    def record(what: str, secs: float, at) -> None:
        rows.append({"what": what, "secs": round(secs, 2), "load": load(),
                     "exceptions": [e.message[:200] for e in at.exception]})
        print(f"{secs:6.2f}s  load {load()}  {what}", rows[-1]["exceptions"] or "", flush=True)

    def timed(what: str, at, action=None) -> None:
        t = time.perf_counter()
        if action:
            action()
        at.run()
        record(what, time.perf_counter() - t, at)

    def rerun(what: str, at) -> None:
        times = []
        for _ in range(3):
            t = time.perf_counter()
            at.run()
            times.append(time.perf_counter() - t)
        record(f"{what} (median of 3)", statistics.median(times), at)

    t = time.perf_counter()
    at = AppTest.from_file(str(ROOT / "app" / "streamlit_app.py"), default_timeout=600)
    at.run()
    record("cold start to the patient list", time.perf_counter() - t, at)
    timed("patient list, rerun", at)
    for pid, picks in PLAN.items():
        timed(f"{pid}: open the file (Report)", at,
              lambda p=pid: at.selectbox(key="patient").select(p))
        rerun(f"{pid}: report rerun", at)
        for view in VIEWS:
            timed(f"{pid}: {view} view", at,
                  lambda v=view: at.segmented_control(key="view").set_value(v))
        at.segmented_control(key="view").set_value("Tests").run()
        df = next(d.value for d in at.dataframe if "Workbench" in d.value.columns)
        tests = [(k, None if m != m or m is None else int(m), n)  # m != m: NaN, no month
                 for k, m, n in zip(df["Type"], df["Month"], df["Test"], strict=True)]
        for kind, month, name in picks:
            hit = next((x for x in tests if x[0] == kind and (month is None or x[1] == month)
                        and (name is None or x[2] == name)), None)
            if hit is None:
                print(f"{pid}: no {kind} test, skipped", flush=True)
                continue
            timed(f"{pid}: workbench {kind}", at,
                  lambda h=hit, p=pid: at.session_state.__setitem__(f"picked-{p}", h))
            rerun(f"{pid}: workbench {kind}, rerun inside", at)
        at.segmented_control(key="view").set_value("Report").run()
    pages = {i.get("url_pathname"): h for h, i in at._registered_pages.items()}
    at._page_hash = pages["methods"]
    timed("Methods and validation", at)
    timed("Methods and validation, rerun", at)
    Path(args.out).write_text(json.dumps(rows, indent=1))
    print("wrote", args.out)


if __name__ == "__main__":
    main()

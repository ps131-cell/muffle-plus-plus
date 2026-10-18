"""Run the live case agent on a few held-out patients and save the notes for the demo.

The demo shows these when there is no Token Factory key, or once a session has used its live
notes. Notes hold only what the agent produced (derived numbers, gene names, links), so the file
is committed. Costs about $0.015 of Token Factory credit and up to 3 Tavily searches per case.

python scripts/save_demo_notes.py                      # 8 cases spread over the risk range
python scripts/save_demo_notes.py --cases 463 334      # these cohort indices (added/replaced)
"""

from __future__ import annotations

import argparse
import json
import os
from datetime import date
from pathlib import Path

from dotenv import load_dotenv

from muffle.demo import build_demo
from muffle.report.nemotron import run_case_agent, tavily_search

load_dotenv()


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--ckpt", default="outputs/tcga_fedavg.pt")
    p.add_argument("--data", default="data/tcga_brca")
    p.add_argument("--n-clients", type=int, default=3)
    p.add_argument("--cases", type=int, nargs="*", help="cohort indices (default: a spread)")
    p.add_argument("--percentiles", type=float, nargs="*",
                   default=[8, 25, 45, 60, 75, 88, 95, 99])
    p.add_argument("--out", type=Path, default=Path("app/saved_notes.json"))
    a = p.parse_args(argv)
    if not os.getenv("NEBIUS_API_KEY"):
        raise SystemExit("NEBIUS_API_KEY is not set: saved notes must come from the live agent")

    demo = build_demo(a.ckpt, a.data, a.n_clients)
    by_index = {c.index: c for c in demo.cases}
    if a.cases:
        picks = [by_index[i] for i in a.cases]
    else:  # the held-out case nearest each percentile; a different one if already taken
        picks = []
        for q in a.percentiles:
            free = [c for c in demo.cases if c not in picks]
            picks.append(min(free, key=lambda c: abs(c.percentile - q)))

    saved = json.loads(a.out.read_text()) if a.out.exists() else {}
    search = tavily_search if os.getenv("TAVILY_API_KEY") else None
    for case in picks:
        report = run_case_agent(demo.tools(case, search),
                                on_step=lambda s, i=case.index: print(f"  [{i}] {s}"))
        if report.mode == "offline":
            print(f"case {case.index}: agent unavailable ({report.notes}); not saved")
            continue
        saved[str(case.index)] = {"created": date.today().isoformat(),
                                  "ckpt": Path(a.ckpt).name, "report": report.to_dict()}
        print(f"case {case.index} ({case.label}): {report.tokens} tokens, "
              f"{len(report.issues)} grounding issues")
    a.out.write_text(json.dumps(saved, indent=1) + "\n")
    print(f"wrote {a.out} ({len(saved)} notes)")


if __name__ == "__main__":
    main()

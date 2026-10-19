"""Score the demo's synthetic timeline patient with the MSK-CHORD models (local only).

python scripts/make_timeline_patient.py        # after `make msk-chord`; ~1 min

Fits the evaluated landmark models (``muffle.longitudinal``, seeds 0-4) on MSK-CHORD, scores the
hand-written synthetic patient of ``muffle.timeline`` at each of its events, and writes only that
synthetic patient's record and scores, the aggregate test metrics and CIViC evidence (CC0) for its
drivers to app/timeline_synthetic.json. No MSK-CHORD patient and no model is saved.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from muffle import longitudinal, timeline
from muffle.report import civic


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--root", type=Path, default=longitudinal.ROOT)
    p.add_argument("--civic", type=Path, default=civic.CACHE, help="CIViC evidence TSV (cached)")
    p.add_argument("--out", type=Path, default=Path("app/timeline_synthetic.json"))
    args = p.parse_args(argv)
    res = longitudinal.evaluate(longitudinal.load(args.root), keep_models=True)
    drivers = {(g, c) for e in timeline.EVENTS for g, c in e.get("mutations", [])}
    table = civic.load_table(str(args.civic))
    evidence = {f"{g} {c}": civic.evidence(g, c, table=table) for g, c in sorted(drivers)}
    out = timeline.build(res, evidence)
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n")
    for u in out["updates"]:
        if "risk" in u:
            print(f"month {u['month']:>3}  risk {u['risk']:.2f}  baseline {u['baseline']:.2f}  "
                  f"(month-{u['landmark']} models)")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

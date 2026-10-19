"""Score the demo's synthetic timeline patient with the MSK-CHORD models (local only).

python scripts/make_timeline_patient.py                  # after `make msk-chord`; ~1 min on a Mac
python scripts/make_timeline_patient.py --evidence-only  # refresh only the CIViC items

Fits the evaluated landmark models (``muffle.longitudinal``, seeds 0-4) on MSK-CHORD, scores the
hand-written synthetic patient of ``muffle.timeline`` at each of its events, and writes only that
synthetic patient's record and scores, the aggregate test metrics and CIViC evidence (CC0) for its
drivers to app/timeline_synthetic.json. No MSK-CHORD patient and no model is saved.

``--evidence-only`` keeps the file's scores and metrics and recomputes only the CIViC items, with
no MSK-CHORD needed. A refit on another machine doesn't reproduce the published scores exactly:
on 2026-10-19 a Linux x86 refit moved month 12's risk from 88% to 90%, with the same library
versions as the Mac that made them.
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
    p.add_argument("--evidence-only", action="store_true",
                   help="keep --out's scores and metrics; recompute only the CIViC items")
    args = p.parse_args(argv)
    drivers = {(g, c) for e in timeline.EVENTS for g, c in e.get("mutations", [])}
    table = civic.load_table(str(args.civic))
    evidence = {f"{g} {c}": civic.evidence(g, c, table=table) for g, c in sorted(drivers)}
    if args.evidence_only:
        out = {**json.loads(args.out.read_text(encoding="utf-8")), "evidence": evidence}
    else:
        res = longitudinal.evaluate(longitudinal.load(args.root), keep_models=True)
        out = timeline.build(res, evidence)
    args.out.write_text(json.dumps(out, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for u in out["updates"]:
        if "risk" in u:
            print(f"month {u['month']:>3}  risk {u['risk']:.2f}  baseline {u['baseline']:.2f}  "
                  f"(month-{u['landmark']} models)")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()

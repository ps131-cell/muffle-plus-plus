"""Refresh the bundled ClinicalTrials.gov snapshot (app/trials_snapshot.json) that the Evolution
view falls back on when the registry can't be reached: for every gene of the driver panel
(muffle.data.tcga.DRIVERS) and of the synthetic record, the first page of recruiting or not yet
recruiting breast cancer trials that mention "<GENE> mutation" (muffle.report.trials).

python scripts/refresh_trials.py      # no key needed; one request per gene

Only gene names leave the machine. The snapshot carries its own date and ClinicalTrials.gov's
data timestamp, which the app shows next to it.
"""

from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from muffle.data.tcga import DRIVERS  # noqa: E402
from muffle.report import trials  # noqa: E402
from muffle.timeline import EVENTS  # noqa: E402


def main() -> None:
    genes = list(dict.fromkeys(DRIVERS + [g for e in EVENTS for g, _ in e.get("mutations", [])]))
    out = {"snapshot": date.today().isoformat(), "data_timestamp": trials.data_timestamp(),
           "query": {"condition": trials.CONDITION, "term": trials.term("<GENE>"),
                     "statuses": trials.STATUSES, "fields": trials.FIELDS,
                     "per_gene": trials.PAGE},
           "genes": {}}
    for g in genes:
        out["genes"][g] = trials.fetch(g)
        print(f"{g}: {out['genes'][g]['total']} trials, kept {len(out['genes'][g]['studies'])}")
        time.sleep(0.3)  # be gentle with the public API
    trials.SNAPSHOT.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print("wrote", trials.SNAPSHOT)


if __name__ == "__main__":
    main()

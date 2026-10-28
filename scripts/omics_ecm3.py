"""The ECM3 four-gene score for the bundled TCGA-BRCA cases (app/omics_ecm3.json).

Triulzi et al. 2013 (PLoS One 8:e56761, doi:10.1371/journal.pone.0056761) describe ECM3, an
extracellular-matrix gene-expression subtype of breast cancer, and a four-gene surrogate score:
the average expression of COL1A2, COL5A2, SPARC and LAMA4. The paper names the collagen gene
COL1A1 in its Results, Figure 2 and Figure S3 and COL1A2 in its Methods (the metagene), Figure S5
and the last paragraph of its Discussion; its qRT-PCR assays list COL1A2 (Hs00164099_m1) and no
COL1A1 assay, so the measured gene was COL1A2 and that is the one used here (``omics.ECM3_GENES``).

Score: each gene's log2(TPM + 1) (the hub's STAR TPM, as scripts/omics_scores.py reads it),
z-scored over the model's TCGA-BRCA cohort, then the mean over the genes measured
(``omics.ecm3_score``); per bundled case its cohort percentile and each gene's. No cutoff: the
paper's classifier was fitted on its own cohorts and the four-gene score was not validated
externally. Runs offline on the local files and ships only derived numbers (percentiles and the
score), never an expression vector. The release bundle carries COL1A2 only of the four among the
model's 1,000 RNA features, hence this script.

python scripts/omics_ecm3.py --data data/tcga_brca --raw data/raw/tcga_brca \
    --bundle outputs/demo_bundle.pt --out app/omics_ecm3.json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from omics_scores import expression  # noqa: E402  (round 1's reader)

from muffle.demo import load_bundle  # noqa: E402
from muffle.explain import risk_percentile as rank_percentile  # noqa: E402
from muffle.workbench import omics  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=Path("data/tcga_brca"))
    p.add_argument("--raw", type=Path, default=Path("data/raw/tcga_brca"))
    p.add_argument("--bundle", required=True)
    p.add_argument("--out", type=Path, default=Path("app/omics_ecm3.json"))
    args = p.parse_args()

    cohort = np.load(args.data / "cohort.npz")
    patients = [str(x) for x in cohort["patient"]]
    cases = {c.index: c for c in load_bundle(args.bundle).cases}
    x = expression(args.raw, patients, set(omics.ECM3_GENES))
    measured = [g for g in omics.ECM3_GENES if g in x.columns]
    z = (x[measured] - x[measured].mean()) / x[measured].std(ddof=0).replace(0, 1)
    score = omics.ecm3_score(z)
    print(f"RNA: {len(x)} tumors; genes measured {measured} of {list(omics.ECM3_GENES)}",
          flush=True)
    out_cases = {}
    for index, case in sorted(cases.items()):
        pid = patients[index]
        if pid not in score.index or np.isnan(score[pid]):
            continue
        out_cases[str(index)] = {
            "log_risk": round(float(case.log_risk), 6),  # the page's guard, as omics_scores.json
            "score": round(float(score[pid]), 3),
            "percentile": round(rank_percentile(score[pid], score.dropna().to_numpy()), 1),
            "genes": {g: round(rank_percentile(z.loc[pid, g], z[g].dropna().to_numpy()), 1)
                      for g in measured if not np.isnan(z.loc[pid, g])}}
    result = {
        "version": f"omics_ecm3 {date.today():%Y-%m-%d}",
        "genes": list(omics.ECM3_GENES), "measured": measured,
        "reference": {"cohort": "TCGA-BRCA primary tumors in the model's cohort (cohort.npz)",
                      "rna_tumors": int(score.notna().sum())},
        "method": "log2(TPM + 1), each gene z-scored over the cohort, the mean over the genes",
        "cases": out_cases}
    args.out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {args.out}: {len(out_cases)} cases", flush=True)


if __name__ == "__main__":
    main()

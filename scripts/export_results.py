"""Aggregate leave-one-site-out results for the demo app -> app/results_tcga_brca.json.

Reads the `python -m muffle.experiment` outputs (git-ignored, under outputs/experiments/) and
keeps only mean, sd and seed count of the pooled C-index per method: no patient-level data, so
the file can be committed and shipped with the hosted demo.

python scripts/export_results.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

# method key in the experiment JSON -> (label in the app, federated?, group)
METHODS = {
    "fedavg_residual": ("FedAvg, clinical-anchored residual", True, "main"),
    "fedavg": ("FedAvg, plain multi-omic fusion", True, "main"),
    "residual": ("Pooled data, clinical-anchored residual", False, "main"),
    "centralized": ("Pooled data, plain fusion", False, "main"),
    "local_only": ("One hospital alone", False, "main"),
    "only_clinical": ("Clinical only (stage, age, T/N/M)", False, "main"),
    "only_rna": ("RNA expression only", False, "single layer"),
    "only_methylation": ("Methylation only", False, "single layer"),
    "only_protein": ("Protein only", False, "single layer"),
    "only_genomic": ("Copy number only", False, "single layer"),
}


def loso(path: Path) -> tuple[dict, dict]:
    d = json.loads(path.read_text())
    out = {}
    for m in {m for r in d["loso_runs"].values() for m in r}:
        v = np.array([r[m]["pooled"] for r in d["loso_runs"].values() if m in r])
        out[m] = {"mean": round(float(v.mean()), 3), "sd": round(float(v.std(ddof=1)), 3),
                  "seeds": len(v)}
    return out, d["sites"]


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--experiments", type=Path, nargs="+",
                   default=[Path("outputs/experiments/tcga_brca_3clients.json"),
                            Path("outputs/experiments/tcga_brca_residual.json")],
                   help="later files win for methods in both")
    p.add_argument("--out", type=Path, default=Path("app/results_tcga_brca.json"))
    a = p.parse_args(argv)
    merged, sites = {}, None
    for f in a.experiments:
        res, sites = loso(f)
        merged.update(res)
    rows = [{"method": k, "label": label, "federated": fed, "group": group, **merged[k]}
            for k, (label, fed, group) in METHODS.items() if k in merged]
    a.out.write_text(json.dumps({
        "cohort": "TCGA-BRCA, overall survival",
        "protocol": "leave one hospital out: train on two hospitals, test on every patient of "
                    "the third; site-stratified pooled C-index, mean and sd over 5 seeds",
        "sites": sites, "methods": rows}, indent=1) + "\n")
    print(f"wrote {a.out} ({len(rows)} methods)")


if __name__ == "__main__":
    main()

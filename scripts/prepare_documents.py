"""Build app/documents/ (the bundled TCGA cases' pathology reports) and measure the extraction.

    python scripts/prepare_documents.py --reports ~/muffle-documents/download/TCGA_Reports.csv \
        --clinical ~/muffle-documents/xena/BRCA_clinicalMatrix

Inputs, all open access and kept outside the repo:
  --reports   TCGA-Reports (Kefeli and Tatonetti, Patterns 2024; Mendeley Data
              10.17632/hyg5xkznpx.1; CC BY 4.0): TCGA_Reports.csv, columns patient_filename
              ("TCGA-XX-XXXX.<uuid>") and text.
  --cohort    data/tcga_brca/cohort.npz: ``patient`` maps a cohort row (Case.index) to its barcode.
  --bundle    the published bundle (outputs/demo_bundle.pt = release demo-bundle-v2): which cases
              ship. Each case's age and stage are checked against the cohort row first.
  --clinical  UCSC Xena TCGA hub BRCA_clinicalMatrix (TCGA open-access clinical data): ER, PR,
              HER2, pT, pN, stage, histologic type, margins and node counts, the reference for
              the measurement. Local only; never written to the repo.

Writes app/documents/<barcode>.json for each bundled case with a report (its text, CC BY 4.0
with attribution) and app/documents/validation.json (aggregate counts only). Rules are written
on the "dev" half of the TCGA-BRCA reports (barcode hash even); numbers are reported on the
"test" half and on the bundled cases.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from datetime import date
from pathlib import Path

import numpy as np

from muffle.demo import load_bundle
from muffle.workbench.documents import RULES_VERSION, TCGA_REPORTS, extract

STAGE = {"I": 1, "II": 2, "III": 3, "IV": 4}
TYPES = {"Infiltrating Ductal Carcinoma": "invasive ductal carcinoma",
         "Infiltrating Lobular Carcinoma": "invasive lobular carcinoma",
         "Mixed Histology (please specify)": "mixed ductal and lobular carcinoma",
         "Mucinous Carcinoma": "mucinous carcinoma", "Metaplastic Carcinoma":
         "metaplastic carcinoma", "Medullary Carcinoma": "medullary carcinoma"}
FIELDS = {  # measured field -> what is compared
    "er": "ER status (positive / negative)",
    "pr": "PR status (positive / negative)",
    "her2": "HER2 status (positive / negative / equivocal; ISH first, then IHC)",
    "pT": "pT category (T1–T4, Tis, TX; suffix ignored)",
    "pN": "pN category (N0–N3, NX; suffix ignored)",
    "stage": "Stage group (I–IV; A–C ignored)",
    "histologic_type": "Histologic type (ductal, lobular, mixed, special types)",
    "margins": "Margins (negative / positive / close)",
    "nodes_examined": "Lymph nodes examined (count)",
    "nodes_positive": "Lymph nodes positive (count, H&E)",
}


def _first(facts: list[dict], field: str):
    return next((f["value"] for f in facts if f["field"] == field), None)


def predicted(facts: list[dict]) -> dict:
    """One value per measured field from a report's facts: the first place the report states it.
    HER2 for this comparison only: the ISH result if stated, else the status word, else the IHC
    score read by the ASCO/CAP bands (0 and 1+ negative, 2+ equivocal, 3+ positive); node counts:
    the total the report states, else the sum of its specimens' counts. The app itself shows
    every fact as written and never derives a status or a total."""
    out = {k: _first(facts, k) for k in ("er", "pr", "histologic_type", "margins")}
    ish, word, ihc = (_first(facts, k) for k in ("her2_ish", "her2", "her2_ihc"))
    out["her2"] = ({"amplified": "positive", "not amplified": "negative"}.get(ish) or word
                   or {"0": "negative", "1+": "negative", "2+": "equivocal",
                       "3+": "positive"}.get(ihc))
    pt, pn, stage = (_first(facts, k) for k in ("pT", "pN", "stage"))
    out["pT"] = re.sub(r"^y?pT(is|[0-4X]).*", r"T\1", pt) if pt else None
    out["pN"] = re.sub(r"^pN([0-3X]).*", r"N\1", pn) if pn else None
    out["stage"] = re.sub(r"^Stage (IV|I{1,3}|0).*", r"\1", stage) if stage else None
    for k in ("nodes_examined", "nodes_positive"):  # the stated total, else each specimen's
        total = next((f["value"] for f in facts if f["field"] == k
                      and f["rule"] in ("nodes label", "nodes status")), None)
        parts = [int(f["value"]) for f in facts if f["field"] == k and f["rule"] == "nodes k/n"]
        out[k] = int(total) if total is not None else sum(parts) if parts else None
    return out


def truth(row: dict) -> dict:
    """The TCGA clinical fields for one patient, on the same scales (None when not recorded)."""
    def status(v):
        v = (v or "").strip().lower()
        return v if v in ("positive", "negative", "equivocal") else None

    def count(v):
        try:
            return int(float(v))
        except (TypeError, ValueError):
            return None

    ish = status(row.get("lab_procedure_her2_neu_in_situ_hybrid_outcome_type"))
    t = re.match(r"T(is|[0-4X])", row.get("pathologic_T") or "")
    n = re.match(r"N[0-3X]", row.get("pathologic_N") or "")
    stage = re.match(r"Stage (IV|I{1,3}|0)", row.get("pathologic_stage") or "")
    margins = (row.get("margin_status") or "").strip().lower()
    return {
        "er": status(row.get("breast_carcinoma_estrogen_receptor_status")),
        "pr": status(row.get("breast_carcinoma_progesterone_receptor_status")),
        "her2": ish if ish in ("positive", "negative") else status(
            row.get("lab_proc_her2_neu_immunohistochemistry_receptor_status")),
        "pT": t.group(0) if t else None,
        "pN": n.group(0) if n else None,
        "stage": stage.group(1) if stage else None,
        "histologic_type": TYPES.get(row.get("histological_type") or ""),
        "margins": margins if margins in ("negative", "positive", "close") else None,
        "nodes_examined": count(row.get("lymph_node_examined_count")),
        "nodes_positive": count(row.get("number_of_lymphnodes_positive_by_he")),
    }


def measure(pairs: list[tuple[dict, dict]]) -> list[dict]:
    """Per field, over patients whose TCGA field holds a value: precision = right / extracted,
    recall = right / patients with a value."""
    rows = []
    for k, what in FIELDS.items():
        known = [(p[k], t[k]) for p, t in pairs if t[k] is not None]
        got = [(p, t) for p, t in known if p is not None]
        right = sum(p == t for p, t in got)
        rows.append({"field": k, "compared": what, "with_value": len(known),
                     "extracted": len(got), "right": right,
                     "precision": right / len(got) if got else None,
                     "recall": right / len(known) if known else None})
    return rows


def split(barcode: str) -> str:
    return "dev" if int(hashlib.sha1(barcode.encode()).hexdigest(), 16) % 2 == 0 else "test"


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--reports", type=Path, required=True)
    p.add_argument("--clinical", type=Path, required=True)
    p.add_argument("--cohort", type=Path, default=Path("data/tcga_brca/cohort.npz"))
    p.add_argument("--bundle", type=Path, default=Path("outputs/demo_bundle.pt"))
    p.add_argument("--out", type=Path, default=Path("app/documents"))
    a = p.parse_args(argv)

    cohort = np.load(a.cohort, allow_pickle=True)
    barcodes = cohort["patient"]
    csv.field_size_limit(10**9)
    reports: dict[str, list[dict]] = {}
    with open(a.reports, newline="") as f:
        for r in csv.DictReader(f):
            reports.setdefault(r["patient_filename"][:12], []).append(r)
    with open(a.clinical, newline="") as f:
        clinical = {r["sampleID"][:12]: r for r in csv.DictReader(f, delimiter="\t")
                    if r["sampleID"].endswith("-01")}

    demo = load_bundle(a.bundle)
    a.out.mkdir(parents=True, exist_ok=True)
    bundled = {}
    for c in demo.cases:
        age = float(cohort["age"][c.index])
        assert c.age is None or abs(c.age - age) < 0.6, f"case {c.index}: cohort row mismatch"
        assert c.stage is None or STAGE[c.stage] == cohort["stage"][c.index], c.index
        bc = str(barcodes[c.index])
        if bc not in reports:
            continue
        bundled[bc] = c.index
        docs = [{"id": r["patient_filename"], "title": "Pathology report (TCGA-Reports)",
                 "kind": "Document", "month": None, "text": r["text"],
                 "source": f"{TCGA_REPORTS} for {bc}"} for r in reports[bc]]
        (a.out / f"{bc}.json").write_text(json.dumps(
            {"barcode": bc, "case_index": c.index, "license": "CC BY 4.0", "source": TCGA_REPORTS,
             "documents": docs}, indent=1) + "\n")

    sets: dict[str, list] = {"dev": [], "test": [], "bundled": []}
    for bc in sorted(set(reports) & set(map(str, barcodes))):
        if bc not in clinical:
            continue
        facts = [f for r in reports[bc] for f in extract(r["text"])]
        pair = (predicted(facts), truth(clinical[bc]))
        sets[split(bc)].append(pair)
        if bc in bundled:
            sets["bundled"].append(pair)
    result = {"rules": RULES_VERSION, "measured": date.today().isoformat(),
              "reports": TCGA_REPORTS,
              "reference": "TCGA-BRCA clinical fields (UCSC Xena TCGA hub, BRCA_clinicalMatrix; "
                           "TCGA open access)",
              "sets": {k: {"patients": len(v), "fields": measure(v)} for k, v in sets.items()}}
    (a.out / "validation.json").write_text(json.dumps(result, indent=1) + "\n")
    print(f"{len(bundled)} bundled cases with a report written to {a.out}")
    for k, v in result["sets"].items():
        print(f"\n{k}: {v['patients']} patients")
        print("| Field | With a TCGA value | Extracted | Right | Precision | Recall |")
        print("|---|---|---|---|---|---|")
        for r in v["fields"]:
            pr = "–" if r["precision"] is None else f"{r['precision']:.0%}"
            rc = "–" if r["recall"] is None else f"{r['recall']:.0%}"
            print(f"| {r['compared']} | {r['with_value']} | {r['extracted']} | {r['right']} | "
                  f"{pr} | {rc} |")


if __name__ == "__main__":
    main()

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
import json
import re
from datetime import date
from pathlib import Path

import numpy as np

from muffle.demo import load_bundle
from muffle.workbench.documents import (
    NER_METHOD,
    RULES_VERSION,
    TCGA_REPORTS,
    comparable,
    extract,
    measurement_half,
    ner_facts,
)

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


def predicted(facts: list[dict]) -> dict:
    """One value per measured field from a report's facts (``documents.comparable``: the first
    place the report states it; HER2 ISH first, then the status word, then the IHC score by the
    ASCO/CAP bands; node counts the stated total, else the sum of each specimen's). The app
    itself shows every fact as written and never derives a status or a total."""
    got = comparable(facts)
    return {k: got[k][0] if k in got else None for k in FIELDS}


SCAN_NOTE = ("Scan reader: ibm-granite/granite-docling-258M on page images (pypdfium2, 144 dpi), "
             "DocTags converted to text by docling-core, in the local pipeline "
             "of this platform. Accuracy = 1 - edit distance / reference length, "
             "case and whitespace ignored. Synthetic scans: a bundled report's text typeset, "
             "rotated and speckled, so the reference is exact. Real scans: two bundled cases' "
             "original report PDFs from the NCI GDC (open access) with their text layer removed; "
             "the reference is TCGA-Reports' cleaned OCR of the same PDF, itself imperfect, so "
             "those numbers are a floor. \"Rules' facts kept\": facts the rules read in the "
             "reference that they also read in the scan's text. Four documents: a check, not a "
             "validation.")


def scan_what(row: dict) -> str:
    bc, bands = row["file"][:12], re.search(r"(\d+) bands per page", row["method"])
    what = (f"synthetic scan of {bc}'s report text" if "synthetic-scan" in row["file"]
            else f"{bc}'s original report PDF, text layer removed")
    return what + (f", read in {bands.group(1)} bands per page" if bands else "")


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


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--reports", type=Path, required=True)
    p.add_argument("--clinical", type=Path, required=True)
    p.add_argument("--cohort", type=Path, default=Path("data/tcga_brca/cohort.npz"))
    p.add_argument("--bundle", type=Path, default=Path("outputs/demo_bundle.pt"))
    p.add_argument("--out", type=Path, default=Path("app/documents"))
    p.add_argument("--scan", type=Path, nargs="+", help="scan_eval.json files from "
                   "documents_pipeline.py scan-eval: the scan reader's text accuracy")
    p.add_argument("--ner", type=Path, help="the model's spans on the held-out half "
                   "(scripts/documents_pipeline.py ner --reports ...); the bundled cases' come "
                   "from <out>/<barcode>.ner.json")
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

    spans: dict[str, dict] = {}  # barcode -> document id -> the model's spans
    if a.ner:
        spans = json.loads(a.ner.read_text())["patients"]
        for bc in bundled:
            p = a.out / f"{bc}.ner.json"
            if p.exists():
                spans[bc] = json.loads(p.read_text(encoding="utf-8"))["documents"]
    sets: dict[str, list] = {"dev": [], "test": [], "bundled": []}
    model: dict[str, list] = {"test": [], "bundled": []}
    for bc in sorted(set(reports) & set(map(str, barcodes))):
        if bc not in clinical:
            continue
        facts = [f for r in reports[bc] for f in extract(r["text"])]
        pair = (predicted(facts), truth(clinical[bc]))
        half = measurement_half(bc)
        sets[half].append(pair)
        if bc in bundled:
            sets["bundled"].append(pair)
        if bc in spans:
            mine = [f for r in reports[bc] for f in ner_facts(
                r["text"], spans[bc].get(r["patient_filename"], [])) if f["value"] is not None]
            for k in [half] * (half == "test") + ["bundled"] * (bc in bundled):
                model[k].append((predicted(mine), pair[1]))
    result = {"rules": RULES_VERSION, "measured": date.today().isoformat(),
              "reports": TCGA_REPORTS,
              "reference": "TCGA-BRCA clinical fields (UCSC Xena TCGA hub, BRCA_clinicalMatrix; "
                           "TCGA open access)",
              "sets": {k: {"patients": len(v), "fields": measure(v)} for k, v in sets.items()}}
    if a.ner:
        run = json.loads(a.ner.read_text())["run"]
        result["model"] = {"method": NER_METHOD, "run": run, "sets": {
            k: {"patients": len(v), "fields": measure(v)} for k, v in model.items()}}
    if a.scan:
        runs = [json.loads(p.read_text()) for p in a.scan]
        result["scan"] = {"measured": runs[0]["date"], "load": [s["load"] for s in runs],
                          "note": SCAN_NOTE, "rows": [{"what": scan_what(r), **{k: r[k] for k in (
                              "pages", "seconds", "characters", "char_accuracy", "word_accuracy",
                              "facts_reference", "facts_scan", "facts_same", "looped")}}
                              for s in runs for r in s["rows"]]}
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

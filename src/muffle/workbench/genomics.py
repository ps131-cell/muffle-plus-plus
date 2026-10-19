"""Genomics (tumor sequencing) workbench for a patient file (docs/WORKSPACE.md, "Tumor
sequencing (DNA)"): pure functions, no Streamlit, no model.

Every variant keeps three parts apart: **detection** (observed: which test, when, which sample;
allele fractions are not in GDC's open masked calls, so none is shown), **interpretation**
(hypothesis: CIViC evidence items, for clinician review, never a recommendation) and
**predicted effect** (hypothesis: only CIViC's own significance and direction wording). A gene
that was not tested is unknown, never wild type. One sample is one place and one time: with a
single sequencing, mutation status after treatment is unknown.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from muffle.data.tcga import DRIVERS
from muffle.report.case_tools import HYPOTHESIS, OBSERVED
from muffle.report.civic import CACHE, LEVELS

IMPLEMENTED, PLANNED = "implemented", "planned"
FOUND, NOT_FOUND = "found", "tested and not found"
NOT_TESTED = "not tested (unknown, not wild type)"
PANEL_NOT_STATED = "panel not stated (unknown, not wild type)"
ESTABLISHED, UNCERTAIN, NO_ITEMS = "established", "uncertain", "hypothesis only"
NO_ALLELE_FRACTION = "allele fraction: not available in the open masked calls"
NO_ALLELE_FRACTION_RECORD = "allele fraction: not stated in the record"
CIVIC = "CIViC clinical evidence summaries (civicdb.org, CC0)"
SYNTHETIC_JSON = Path(__file__).resolve().parents[3] / "app" / "timeline_synthetic.json"
PLANNED_ROWS = [
    ("ctDNA (liquid biopsy)", "variants over time with allele fractions; the practical follow-up "
                              "after a tissue sample"),
    ("allele fractions", "need the controlled-access calls or a local pipeline; the open masked "
                         "calls carry none"),
    ("read-level inspection", "aligned reads around each call (needs BAM access)"),
    ("pathway views", "which pathways the found variants sit in, with their references"),
]


def _events(events):
    if events is not None:
        return events
    from muffle.timeline import EVENTS  # keeps the import light for callers that pass events
    return EVENTS


def events_until(events, month: int | None):
    """The record up to and including ``month`` (a report version's month); all of it when
    ``month`` is None (the latest version, or a TCGA baseline that has no month)."""
    events = _events(events)
    return events if month is None else [e for e in events if e["month"] <= month]


def _synthetic_evidence() -> dict:
    if not SYNTHETIC_JSON.exists():
        return {}
    return json.loads(SYNTHETIC_JSON.read_text(encoding="utf-8")).get("evidence", {})


def _panel_test(file):
    return next((t for t in file.tests if t.kind == "Mutation panel"), None)


def _panel_names(test) -> list[str]:
    """The "GENE CHANGE" names of a TCGA mutation-panel test; [] when nothing in the panel."""
    return [] if test.result.startswith("none") else test.result.split(", ")


def _detections(file, events) -> list[dict]:
    """gene, change, month, sample, assay, test and allele fraction (never available: the open
    masked calls carry none, the synthetic record states none) per observed variant."""
    if file.kind == "synthetic":
        return [{"gene": g, "change": c, "month": e["month"], "sample": "bone biopsy",
                 "assay": "tumor sequencing panel", "test": "Tumor sequencing",
                 "allele_fraction": NO_ALLELE_FRACTION_RECORD}
                for e in events if "mutations" in e for g, c in e["mutations"]]
    test = _panel_test(file)
    if test is None:
        return []
    return [{"gene": n.partition(" ")[0], "change": n.partition(" ")[2], "month": None,
             "sample": "primary tumor (TCGA)",
             "assay": "exome sequencing, GDC open-access masked calls", "test": test.name,
             "allele_fraction": NO_ALLELE_FRACTION}
            for n in _panel_names(test)]


def variants(file, events=None, evidence: dict | None = None, lookup=None) -> list[dict]:
    """The observed variants of a ``muffle.workspace.PatientFile``, each with its detection,
    interpretation and predicted effect kept apart. ``evidence`` maps "GENE CHANGE" to CIViC
    items; ``lookup(gene, change)`` (e.g. ``muffle.report.civic.evidence``) serves a variant the
    mapping lacks; the synthetic file falls back to ``app/timeline_synthetic.json``."""
    events = _events(events)
    evidence = dict(evidence or {})
    if file.kind == "synthetic" and not evidence and lookup is None:
        evidence = _synthetic_evidence()
    out = []
    for d in _detections(file, events):
        name = f"{d['gene']} {d['change']}"
        items = evidence.get(name)
        if items is None:
            items = lookup(d["gene"], d["change"]) if lookup else []
        when = (f"month {d['month']}" if d["month"] is not None else
                "baseline: the one TCGA tumor sample (calendar date not in the open data)")
        levels = sorted(i.get("evidence_level", "") for i in items if i.get("evidence_level"))
        effect = [f"{i.get('significance', '')} ({i.get('direction', '')}) for "
                  f"{i.get('therapies', 'none named')}, level {i.get('evidence_level', '?')}"
                  for i in items]
        out.append({
            **d, "variant": name, "strongest_level": levels[0] if levels else None,
            "detection": {"evidence": OBSERVED, "test": d["test"], "when": when,
                          "sample": d["sample"], "assay": d["assay"],
                          "allele_fraction": d["allele_fraction"]},
            "interpretation": {"evidence": HYPOTHESIS, "source": CIVIC, "items": items,
                               "note": None if items else
                               "no CIViC item for this variant in breast cancer"},
            "effect": {"evidence": HYPOTHESIS, "statements": effect,
                       "note": ("CIViC's own significance and direction wording; nothing is "
                                "predicted here beyond it") if items else
                       "no CIViC statement: predicted effect unknown"},
        })
    return out


def panel_coverage(file, events=None) -> list[dict]:
    """Status per gene of the 16-gene TCGA driver panel (plus any found gene outside it):
    found, tested and not found, or not tested; the synthetic record names only what it found,
    so the rest of the panel is "panel not stated"."""
    events = _events(events)
    found = [d["gene"] for d in _detections(file, events)]
    if file.kind == "synthetic":
        rest = PANEL_NOT_STATED if any("mutations" in e for e in events) else NOT_TESTED
    else:
        rest = NOT_FOUND if _panel_test(file) is not None else NOT_TESTED
    genes = DRIVERS + [g for g in dict.fromkeys(found) if g not in DRIVERS]
    return [{"gene": g, "status": FOUND if g in found else rest} for g in genes]


def review_queue(variants: list[dict]) -> dict[str, list[str]]:
    """Variants by the strength of their CIViC evidence: established (any level A or B item),
    uncertain (only C, D or E), hypothesis only (no item)."""
    out = {ESTABLISHED: [], UNCERTAIN: [], NO_ITEMS: []}
    for v in variants:
        level = v["strongest_level"]
        key = NO_ITEMS if level is None else ESTABLISHED if level in "AB" else UNCERTAIN
        out[key].append(v["variant"])
    return out


def longitudinal(file, events=None) -> dict:
    """Sequencing timepoints and a plain statement of what one sample can and cannot say."""
    events = _events(events)
    points: dict[tuple, list[str]] = {}
    if file.kind == "synthetic":
        for e in events:
            if "mutations" in e:
                points[(e["month"], "bone biopsy")] = [f"{g} {c}" for g, c in e["mutations"]]
    elif (test := _panel_test(file)) is not None:
        points[(None, "primary tumor (TCGA)")] = _panel_names(test)
    rows = [{"month": m, "sample": s, "found": ", ".join(f) or "none of the panel"}
            for (m, s), f in points.items()]
    if not rows:
        statement = "not sequenced: mutation status is unknown (not wild type)"
    elif len(rows) == 1:
        when = (f"at month {rows[0]['month']}" if rows[0]["month"] is not None else
                "at baseline (the TCGA tumor sample)")
        statement = (f"sequenced once {when}: mutation status after treatment is unknown; repeat "
                     "tissue sequencing is rare, ctDNA is the practical follow-up, planned")
    else:
        statement = (f"sequenced {len(rows)} times: a variant found later may be newly acquired "
                     "or newly sampled (another place, more tumor DNA); inferring mutation order "
                     "needs linked samples, not shown here")
    return {"timepoints": rows, "statement": statement, "ctdna": PLANNED}


def data_card() -> dict:
    """The data and method card: sources, labels, limits, what is planned. No model."""
    cached = CACHE.exists()
    downloaded = (", downloaded " + datetime.fromtimestamp(CACHE.stat().st_mtime).date().isoformat()
                  if cached else ", not downloaded on this machine")
    return {
        "name": "Genomics workbench (tumor sequencing)",
        "status": IMPLEMENTED,
        "model": "none: observed calls and curated evidence, no prediction",
        "data": {"TCGA-BRCA": "GDC open-access masked somatic calls (exome), the 16-gene breast "
                              "cancer driver panel of src/muffle/data/tcga.py; no allele fractions",
                 "SYNTHETIC-001": "a hand-written record (synthetic, not a real person)",
                 "evidence": CIVIC + downloaded},
        "evidence_levels": LEVELS,
        "labels": {"detection": OBSERVED, "interpretation": HYPOTHESIS,
                   "predicted effect": HYPOTHESIS},
        "limits": ["one sample is one place and one time",
                   "tumor purity and sequencing depth are unknown, so a negative is not proof "
                   "of absence",
                   "panel genes only: nothing is said about genes outside the panel",
                   "no allele fractions in the open masked calls",
                   "CIViC items are evidence for clinician review, never a recommendation"],
        "planned": [{"what": w, "note": n, "status": PLANNED} for w, n in PLANNED_ROWS],
    }

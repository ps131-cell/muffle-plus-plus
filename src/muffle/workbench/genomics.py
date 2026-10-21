"""Genomics (tumor sequencing) workbench for a patient file (docs/WORKSPACE.md, "Tumor
sequencing (DNA)"): pure functions, no Streamlit, no model.

Every variant keeps its evidence apart, rung by rung: **detected** (observed: which test, when,
which sample; allele fractions are not in GDC's open masked calls, so none is shown),
**interpreted** (hypothesis: CIViC evidence items, for clinician review, never a recommendation),
**predicted effect** (model inference: AlphaMissense and the Ensembl VEP consequence, from
``muffle.workbench.genome``; without them, CIViC's own wording, as hypothesis),
**therapy evidence** (hypothesis, for clinician review) and **resistance mechanisms**
(hypothesis: CIViC resistance items and the literature cited in docs/VISION.md). A gene that was
not tested is unknown, never wild type. One sample is one place and one time: with a single
sequencing, mutation status after treatment is unknown.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from muffle.data.tcga import DRIVERS
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.report.civic import CACHE, LEVELS
from muffle.workspace import MARKS, card, finding_key, look

IMPLEMENTED, PLANNED = "implemented", "planned"
FOUND, NOT_FOUND = "found", "tested and not found"
NOT_TESTED = "not tested (unknown, not wild type)"
PANEL_NOT_STATED = "panel not stated (unknown, not wild type)"
ESTABLISHED, UNCERTAIN, NO_ITEMS = "established", "uncertain", "hypothesis only"
NO_ALLELE_FRACTION = "allele fraction: read counts not available for this sample"
NO_ALLELE_FRACTION_RECORD = "allele fraction: not stated in the record"
CIVIC = "CIViC clinical evidence summaries (civicdb.org, CC0)"
SYNTHETIC_JSON = Path(__file__).resolve().parents[3] / "app" / "timeline_synthetic.json"
VERDICTS = MARKS  # the report page's marks: reviewed, agree, disagree, second look
REVIEWED, AGREE, DISAGREE, SECOND_LOOK = MARKS
AROMATASE_INHIBITORS = {"letrozole", "anastrozole", "exemestane"}
DETECT = "serial ctDNA (planned), or a repeat biopsy"
# Resistance literature already cited in docs/VISION.md; nothing beyond it is claimed here.
LITERATURE = [
    {"alteration": "ESR1 mutation (ligand-binding domain)", "gene": "ESR1",
     "under": AROMATASE_INHIBITORS, "under_text": "an aromatase inhibitor (with palbociclib)",
     "source": "Bidard et al. 2022, PADA-1, Lancet Oncol",
     "url": "https://doi.org/10.1016/S1470-2045(22)00555-1",
     "level": "randomized phase 3 trial (literature, not a CIViC level)",
     "finding": "a rising ESR1 mutation in blood under aromatase inhibitor plus palbociclib, "
                "before progression; the trial switched to fulvestrant plus palbociclib "
                "(median PFS 11.9 vs 5.7 months)", "detect": DETECT},
    {"alteration": "ESR1 mutation (ligand-binding domain)", "gene": "ESR1",
     "under": AROMATASE_INHIBITORS, "under_text": "an aromatase inhibitor plus a CDK4/6 inhibitor",
     "source": "Bidard et al. 2025, SERENA-6, N Engl J Med",
     "url": "https://doi.org/10.1056/NEJMoa2502929",
     "level": "randomized phase 3 trial (literature, not a CIViC level)",
     "finding": "emerging ESR1 mutation found by ctDNA every 2 to 3 months; the trial switched "
                "to camizestrant (median PFS 16.0 vs 9.2 months)", "detect": DETECT},
]
PLANNED_ROWS = [
    ("ctDNA (liquid biopsy)", "variants over time with allele fractions; the practical follow-up "
                              "after a tissue sample"),
    ("read-level inspection", "aligned reads around each call (needs BAM access)"),
    ("copy-number segments", "arm-level versus focal changes need ASCAT's segments, not the "
                             "gene-level values shown"),
    ("allele-specific copy number", "loss of heterozygosity and the mutant copy count need "
                                    "allele-specific calls"),
    ("predicted effect beyond missense", "no predictor is shown for truncating, splice or "
                                         "in-frame changes"),
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


@lru_cache(maxsize=1)  # a file in the repo: read once per process
def _synthetic_evidence() -> dict:
    if not SYNTHETIC_JSON.exists():
        return {}
    return json.loads(SYNTHETIC_JSON.read_text(encoding="utf-8")).get("evidence", {})


def _panel_test(file):
    return next((t for t in file.tests if t.kind == "Mutation panel"), None)


def _panel_names(test) -> list[str]:
    """The "GENE CHANGE" names of a TCGA mutation-panel test; [] when nothing in the panel."""
    return [] if test.result.startswith("none") else test.result.split(", ")


def _af_text(reads: dict | None, name: str, default: str) -> str:
    r = (reads or {}).get(name)
    if not r or not r.get("depth"):
        return default
    return f"allele fraction {r['alt'] / r['depth']:.1%} ({r['alt']} of {r['depth']} reads)"


def _detections(file, events, reads: dict | None = None) -> list[dict]:
    """gene, change, month, sample, assay, test and allele fraction per observed variant; the
    allele fraction comes from ``reads`` ({"GENE CHANGE": {"alt", "depth"}}, the per-case GDC
    files' read counts) when given; the synthetic record states none."""
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
             "allele_fraction": _af_text(reads, n, NO_ALLELE_FRACTION)}
            for n in _panel_names(test)]


def variants(file, events=None, evidence: dict | None = None, lookup=None,
             reads: dict | None = None) -> list[dict]:
    """The observed variants of a ``muffle.workspace.PatientFile``, each with its detection,
    interpretation and predicted effect kept apart. ``evidence`` maps "GENE CHANGE" to CIViC
    items; ``lookup(gene, change)`` (e.g. ``muffle.report.civic.evidence``) serves a variant the
    mapping lacks; the synthetic file falls back to ``app/timeline_synthetic.json``; ``reads``
    gives TCGA variants their allele fraction (see ``_detections``)."""
    events = _events(events)
    evidence = dict(evidence or {})
    if file.kind == "synthetic" and not evidence and lookup is None:
        evidence = _synthetic_evidence()
    out = []
    for d in _detections(file, events, reads):
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
                       "note": ("CIViC's own significance and direction wording; a model's "
                                "prediction, where one exists, is shown apart") if items else
                       "no CIViC statement on the effect"},
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
        "model": "no model runs here: observed calls, curated evidence, and AlphaMissense's "
                 "precomputed predictions shown as model inference",
        "data": {"TCGA-BRCA": "GDC open-access masked somatic calls (exome), the 16-gene breast "
                              "cancer driver panel of src/muffle/data/tcga.py; allele fractions "
                              "from the per-case files' read counts; ASCAT3 gene-level copy "
                              "number",
                 "SYNTHETIC-001": "a hand-written record (synthetic, not a real person)",
                 "evidence": CIVIC + downloaded,
                 "literature": "resistance under endocrine therapy: PADA-1 (Bidard et al. 2022), "
                               "SERENA-6 (Bidard et al. 2025), as cited in docs/VISION.md"},
        "evidence_levels": LEVELS,
        "labels": {"detected": OBSERVED, "interpreted": HYPOTHESIS, "predicted effect": INFERENCE,
                   "therapy evidence": HYPOTHESIS, "resistance mechanisms": HYPOTHESIS,
                   "watchlist": HYPOTHESIS},
        "limits": ["one sample is one place and one time",
                   "tumor purity and sequencing depth are unknown, so a negative is not proof "
                   "of absence",
                   "panel genes only: nothing is said about genes outside the panel",
                   "allele fractions only for the TCGA cases (read counts); the synthetic "
                   "record states none",
                   "CIViC items are evidence for clinician review, never a recommendation"],
        "planned": [{"what": w, "note": n, "status": PLANNED} for w, n in PLANNED_ROWS],
    }


# ------------------------------------------------------------------ evidence ladder, resistance

def _year(item: dict) -> str:
    m = re.search(r"(19|20)\d\d", item.get("citation", "") or "")
    return m.group(0) if m else "year not stated"


def _item(r, match: str) -> dict:
    return {"molecular_profile": r["molecular_profile"], "match": match,
            "therapies": r["therapies"] or "none named", "evidence_level": r["evidence_level"],
            "level_meaning": LEVELS.get(r["evidence_level"], "unknown"),
            "significance": r["significance"], "direction": r["evidence_direction"],
            "disease": r["disease"], "citation": r["citation"], "url": r["evidence_civic_url"]}


def _therapies(item: dict) -> set[str]:
    return {t.strip().lower() for t in (item.get("therapies") or "").split(",") if t.strip()}


def resistance_items(gene: str, therapies: set[str], table=None, disease: str = "breast",
                     k: int = 8) -> list[dict]:
    """Accepted CIViC items with significance Resistance in ``disease`` for ``gene`` (any
    profile naming it; "" for none) or for any of ``therapies``; [] without a table."""
    if table is None or table.empty:
        return []
    t = table[(table["significance"] == "Resistance")
              & table["disease"].str.contains(disease, case=False, regex=False)]
    wanted = {x.lower() for x in therapies}
    out, seen = [], set()
    for _, r in t.iterrows():
        dup = (r["molecular_profile"], r["therapies"], r["citation"], r["evidence_level"])
        if dup in seen:  # CIViC holds the same association from one paper more than once
            continue
        in_gene = bool(gene) and re.search(rf"\b{re.escape(gene)}\b",
                                           r["molecular_profile"]) is not None
        shared = _therapies({"therapies": r["therapies"]}) & wanted
        if in_gene or shared:
            match = ("resistance item for the gene" if in_gene else
                     f"resistance item for the therapy ({', '.join(sorted(shared))})")
            seen.add(dup)
            out.append(_item(r, match))
    out.sort(key=lambda i: "ABCDE".find(i["evidence_level"]) % 6)
    return out[:k]


def variant_resistance(variant: dict, table=None) -> list[dict]:
    """CIViC resistance items for the variant's gene or for the therapies its items name."""
    therapies = set().union(set(), *(_therapies(i) for i in variant["interpretation"]["items"]))
    return resistance_items(variant["gene"], therapies, table)


def _predicted_rung(variant: dict, predicted: dict) -> dict:
    """Rung 3 from a model: AlphaMissense's score and class (model inference) and Ensembl VEP's
    consequence of the call (``muffle.workbench.genome.effect``)."""
    p, a = predicted["prediction"], predicted["annotation"]
    lines = []
    if p["score"] is not None:
        lines.append(f"{p['predictor']}: {p['score']:.3f}, {p['class']} (model inference; not "
                     "approved for clinical use)")
    elif not p["applies"]:
        lines.append(f"{p['predictor']}: not applicable (missense changes only)")
    protein = a["hgvsp"] or "no protein change"
    lines.append(f"consequence: {(a['consequence'] or '?').replace('_', ' ')} on "
                 f"{a['transcript'] or 'the canonical transcript'} ({protein}), Ensembl VEP")
    return {"rung": 3, "label": "predicted effect", "evidence": INFERENCE,
            "status": "present" if p["score"] is not None else "none", "lines": lines,
            "items": [], "strengthen": "a functional assay for this exact change; the predictor "
                                      "scores pathogenicity, not somatic oncogenicity"}


def ladder(variant: dict, resistance: list[dict] | None = None,
           predicted: dict | None = None) -> list[dict]:
    """Five rungs for one variant, each with its own evidence type and what would strengthen
    it: detected, interpreted, predicted effect, therapy evidence, resistance mechanisms.
    ``predicted``: the variant's ``muffle.workbench.genome.effect``; with it, rung 3 is the
    model's prediction (model inference), otherwise CIViC's own effect wording."""
    d, items = variant["detection"], variant["interpretation"]["items"]
    specific = [i for i in items if (i.get("match") or "").startswith("this variant")]
    levels = sorted({i.get("evidence_level", "?") for i in items})
    therapy = [i for i in items if i.get("significance") == "Sensitivity/Response"]
    resist = [i for i in items if i.get("significance") == "Resistance"]
    for i in resistance or []:
        if i["url"] not in {x.get("url") for x in resist}:
            resist.append(i)
    lit = [r for r in LITERATURE if r["gene"] == variant["gene"]]
    if not levels or levels[0] not in "AB":
        strengthen2 = "a level A or B item in this disease"
    elif not specific:
        strengthen2 = "an item for the variant itself rather than the gene"
    else:
        strengthen2 = ("nothing more from CIViC: a validated association for the variant itself; "
                       "what remains open is this patient's own response")
    rungs = [
        {"rung": 1, "label": "detected", "evidence": OBSERVED, "status": "observed",
         "lines": [f"{d['test']} · {d['sample']} · {d['when']}", d["allele_fraction"]],
         "items": [], "strengthen": "allele fraction and depth from the full calls; the same "
                                    "variant in a second sample (ctDNA or a repeat biopsy)"},
        {"rung": 2, "label": "interpreted", "evidence": HYPOTHESIS,
         "status": "present" if items else "none",
         "lines": [f"{i.get('evidence_level', '?')} ({LEVELS.get(i.get('evidence_level'), '?')})"
                   f" · {i.get('direction', '?')} · {i.get('citation', '?')} ({_year(i)}) · "
                   f"{i.get('match', '')}" for i in items]
                  or ["no CIViC item for this variant in breast cancer"],
         "items": items, "strengthen": strengthen2},
        {"rung": 3, "label": "predicted effect", "evidence": HYPOTHESIS,
         "status": "present" if items else "none",
         "lines": variant["effect"]["statements"] or [variant["effect"]["note"]], "items": [],
         "strengthen": "a functional assay for this exact change; CIViC's own wording is all "
                       "that is shown"},
        {"rung": 4, "label": "therapy evidence (for clinician review)", "evidence": HYPOTHESIS,
         "status": "present" if therapy else "none",
         "lines": [f"{i.get('therapies', '?')} · level {i.get('evidence_level', '?')} · "
                   f"{i.get('direction', '?')} · {i.get('disease', '?')} · "
                   f"{i.get('citation', '?')}" for i in therapy]
                  or ["no therapy item for this variant in breast cancer"],
         "items": therapy,
         "strengthen": "level A or B evidence in this disease and treatment line; never a "
                       "recommendation here"},
        {"rung": 5, "label": "resistance mechanisms", "evidence": HYPOTHESIS,
         "status": "present" if resist or lit else "none",
         "lines": [f"{i['molecular_profile']} · {i.get('therapies', '?')} · level "
                   f"{i.get('evidence_level', '?')} · {i.get('citation', '?')} · {i['match']}"
                   for i in resist]
                  + [f"{r['alteration']} under {r['under_text']} · {r['source']}" for r in lit]
                  or ["no resistance item for this gene or its therapies in breast cancer"],
         "items": resist, "literature": lit,
         "strengthen": "serial ctDNA while on therapy; a repeat biopsy at progression"},
    ]
    if predicted and predicted.get("found"):
        rungs[2] = _predicted_rung(variant, predicted)
    return rungs


def treatments(file, version: int | None = None) -> list[str]:
    """Treatments recorded in the file up to ``version`` (all when None), in record order."""
    vs = file.versions if version is None else file.versions[:version + 1]
    return list(dict.fromkeys(t for v in vs for t in v.treatments))


def watchlist(file, version: int | None = None, table=None) -> dict:
    """What to watch under the treatments recorded in the file: alterations known to emerge
    under them, each with its source, level and the test that would detect it. Hypothesis,
    never advice. Sources: the literature in docs/VISION.md and CIViC resistance items whose
    therapies include a recorded drug."""
    rx = treatments(file, version)
    rows = []
    for r in LITERATURE:
        under = sorted(set(rx) & r["under"])
        if under:
            rows.append({"under": ", ".join(under), "alteration": r["alteration"],
                         "finding": r["finding"], "source": r["source"], "url": r["url"],
                         "level": r["level"], "detect": r["detect"]})
    ais = sorted(set(rx) & AROMATASE_INHIBITORS)
    wanted = set(rx) | ({"aromatase inhibitor"} if ais else set())  # CIViC names the class too
    if rx and table is not None:
        for i in resistance_items("", wanted, table):
            under = sorted(_therapies(i) & wanted)
            under = [f"{', '.join(ais)} (aromatase inhibitor)" if u == "aromatase inhibitor"
                     else u for u in under]
            rows.append({"under": ", ".join(under),
                         "alteration": i["molecular_profile"],
                         "finding": f"{i['significance']} ({i['direction']}) to {i['therapies']}",
                         "source": f"CIViC: {i['citation']}", "url": i["url"],
                         "level": f"{i['evidence_level']} ({i['level_meaning']})",
                         "detect": DETECT})
    if rx and not rows:
        rows.append({"under": ", ".join(rx), "alteration": "none in this evidence set",
                     "finding": "no sourced alteration for these drugs in CIViC (breast) or the "
                                "cited literature", "source": "", "url": "", "level": "",
                     "detect": ""})
    return {"evidence": HYPOTHESIS, "use": "what to watch, never advice", "treatments": rx,
            "rows": rows, "note": "no treatment recorded in this file" if not rx else None}


def conflicts(items: list[dict]) -> list[dict]:
    """The same association (profile, therapies, significance) seen from both sides: items that
    support it and items that do not, each with level and year. Shown side by side, never
    averaged; associations with both sides come first."""
    groups: dict[tuple, dict] = {}
    for i in items:
        key = (i.get("molecular_profile", ""), i.get("therapies", ""), i.get("significance", ""))
        g = groups.setdefault(key, {"association": f"{key[0]} · {key[1]} · {key[2]}",
                                    "supports": [], "does_not_support": []})
        side = ("supports" if (i.get("direction") or "").lower() == "supports"
                else "does_not_support")
        g[side].append({**i, "year": _year(i)})
    return sorted(groups.values(),
                  key=lambda g: (not (g["supports"] and g["does_not_support"]), g["association"]))


def search(variants: list[dict], coverage: list[dict], query: str) -> dict:
    """Variants matching ``query``: a gene, "level A" (any item of that level), "resistance"
    (any resistance item), or text in the variant name, therapies or significance. A gene
    symbol the panel does not include is said so."""
    q = (query or "").strip()
    if not q:
        return {"variants": variants, "note": None}
    ql = q.lower()
    level = re.fullmatch(r"level\s*([a-e])", ql)

    def hit(v):
        items = v["interpretation"]["items"]
        if level:
            return any((i.get("evidence_level") or "").lower() == level.group(1) for i in items)
        if ql == "resistance":
            return any(i.get("significance") == "Resistance" for i in items)
        text = " ".join([v["variant"], *(f"{i.get('therapies', '')} {i.get('significance', '')}"
                                          for i in items)]).lower()
        return ql in text

    found = [v for v in variants if hit(v)]
    note = None
    if (not found and not level and re.fullmatch(r"[A-Za-z][A-Za-z0-9]{1,9}", q)
            and q.upper() not in {c["gene"] for c in coverage}):
        note = f"this panel does not include {q.upper()}"
    return {"variants": found, "note": note}


def provenance(file, events=None) -> list[tuple[str, str]]:
    """The sample strip: sample → site → date → assay → what it can and cannot show."""
    events = _events(events)
    cannot = ("allele fractions, copy number, clonal structure, germline variants, genes outside "
              "the panel, and anything that changed after this sample")
    can = "protein-altering somatic mutations in the panel genes, in this sample"
    if file.kind == "synthetic":
        seq = [e for e in events if "mutations" in e]
        if not seq:
            return [("sample", "none yet"), ("site", "—"), ("date", "—"), ("assay", "—"),
                    ("can show", "nothing: not sequenced, mutation status unknown"),
                    ("cannot show", "—")]
        return [("sample", "bone biopsy"), ("site", "bone (metastatic site)"),
                ("date", f"month {seq[-1]['month']}"), ("assay", "tumor sequencing panel"),
                ("can show", can), ("cannot show", cannot)]
    if _panel_test(file) is None:
        return [("sample", "primary tumor (TCGA)"), ("site", "breast (surgery)"),
                ("date", "not in the open data"), ("assay", "none: not sequenced"),
                ("can show", "nothing: mutation status unknown, not wild type"),
                ("cannot show", "—")]
    return [("sample", "primary tumor (TCGA)"), ("site", "breast (surgery)"),
            ("date", "not in the open data"),
            ("assay", "exome sequencing, GDC open-access masked somatic calls"),
            ("can show", can + "; with the same sample's read counts and ASCAT3 copy number: "
                               "allele fractions and gene-level copy number"),
            ("cannot show", "clonal structure for certain, germline variants, genes outside the "
                            "panel, and anything that changed after this sample")]


# ------------------------------------------------------------------ review marks and export

def variant_key(file, variant: dict) -> str:
    """The shared review key of a variant: ``finding_key(file, "variant", "GENE CHANGE", the
    sequencing test's month)`` (``workspace.FINDING_KINDS``)."""
    return finding_key(file, "variant", variant["variant"], variant["month"])


def item_key(file, variant: dict, item: dict, n: int = 0) -> str:
    """The shared review key of a CIViC item, the same one the report page uses."""
    return finding_key(file, "civic", variant["variant"], item.get("url") or f"item-{n}")


def add_mark(reviews: dict, key: str, what: str, verdict: str | None, initials: str = "",
             when: str | None = None) -> dict:
    """Store (or, with None, clear) one reviewer's mark in the shared store
    (``st.session_state.reviews``): {"what", "mark", "by", "at"} under a finding key, so the
    report page's one-file export carries it too. Returns ``reviews``."""
    if verdict is None:
        reviews.pop(key, None)
        return reviews
    if verdict not in VERDICTS:
        raise ValueError(f"verdict must be one of {VERDICTS}")
    reviews[key] = {"what": what, "mark": verdict, "by": initials.strip(),
                    "at": when or datetime.now().strftime("%Y-%m-%d %H:%M")}
    return reviews


def marks_of(reviews: dict, file) -> dict:
    """This file's marks from the shared store, whatever page made them."""
    return {k: r for k, r in reviews.items() if k.startswith(file.id + "|")}


def mark_text(review: dict | None) -> str:
    return (f"{review['mark']} ({review['by'] or 'no initials'}, {review['at']})" if review
            else "")


def report_markdown(file, variants: list[dict], ladders: dict[str, list[dict]],
                    watch: dict, reviews: dict, strip: list[tuple[str, str]]) -> str:
    """A Markdown report: sample strip, variant table, ladders with sources, watchlist, and
    this file's marks from the shared ``reviews`` store."""
    out = [f"# Genomics workbench · {file.id}", "", file.title, ""]
    if file.kind == "synthetic":
        out += [f"**{file.note}**", ""]
    out += ["## Sample", "", *(f"- {k}: {v}" for k, v in strip), "",
            "## Variants", "", "| Variant | Sample | When | Strongest CIViC level | Items |",
            "|---|---|---|---|---|"]
    for v in variants:
        out.append(f"| {v['variant']} | {v['sample']} | {v['detection']['when']} | "
                   f"{v['strongest_level'] or 'none'} | {len(v['interpretation']['items'])} |")
    if not variants:
        out.append("| none | | | | |")
    for v in variants:
        out += ["", f"## {v['variant']}: evidence ladder", ""]
        for r in ladders.get(v["variant"], []):
            out += [f"### {r['rung']}. {r['label']} [{r['evidence']}]", "",
                    *(f"- {line}" for line in r["lines"]),
                    f"- what would strengthen it: {r['strengthen']}", ""]
        urls = [i["url"] for i in v["interpretation"]["items"] if i.get("url")]
        if urls:
            out += ["Sources: " + ", ".join(urls), ""]
    out += ["## Resistance watchlist (hypothesis: what to watch, never advice)", ""]
    for r in watch["rows"]:
        out.append(f"- under {r['under']}: {r['alteration']} · {r['finding']} · {r['source']} "
                   f"{r['url']} · {r['level']} · detect with {r['detect']}")
    if watch["note"]:
        out.append(f"- {watch['note']}")
    out += ["", "## Review marks", ""]
    mine = marks_of(reviews, file)
    out += [f"- {r['what']}: {mark_text(r)}" for r in mine.values()] or ["- none"]
    out += ["", "CIViC items (civicdb.org, CC0) are evidence for clinician review, never a "
            "recommendation. Not tested means unknown, not wild type.", ""]
    return "\n".join(out)


# --------------------------------------------------- the workbench contract (WORKBENCHES.md §1)

def file_variants(file, version: int | None = None, lookup=None) -> tuple[list[dict], bool]:
    """``variants`` as of report version ``version`` and whether CIViC was available (the
    synthetic record's frozen items, or ``lookup`` for a TCGA file): without it a variant's
    evidence is unknown, never "none"."""
    month = None if version is None else file.versions[version].month
    return (variants(file, events_until(None, month), None, lookup),
            file.kind == "synthetic" or lookup is not None)


def _seq_opens(file, v: dict) -> tuple:
    t = next((t for t in file.tests if t.workbench == "mutations" and t.name == v["test"]
              and t.month == v["month"]), None)
    return () if t is None else ("Tests", t.kind, t.month, t.name)


def summary(file, version: int | None = None, lookup=None) -> dict:
    """The observed drivers with their strongest CIViC level (or "not sequenced")."""
    vs, civic = file_variants(file, version, lookup)
    seq = [t for v in file.versions[: (len(file.versions) if version is None else version + 1)]
           for t in v.tests if t.workbench == "mutations"]
    method = ("tumor sequencing panel in the record" if file.kind == "synthetic" else
              f"exome sequencing, GDC open-access masked somatic calls, {len(DRIVERS)}-gene "
              "breast cancer driver panel")
    if not seq:
        return {"workbench": "genomics", "title": "Tumor sequencing", "note": None, "cards": [
            card("Driver mutations", "not sequenced: unknown, not wild type", OBSERVED,
                 "no sequencing test in this file", "none", "none", "strong")]}
    if not vs:
        text, opens, focus = "sequenced: none of the panel's genes mutated", (
            "Tests", seq[-1].kind, seq[-1].month, seq[-1].name), None
    else:
        text = ", ".join(v["variant"] + (f" (CIViC level {v['strongest_level']})"
                                         if v["strongest_level"] else
                                         " (no CIViC breast cancer item)" if civic else "")
                         for v in vs) + ("" if civic else " · CIViC not loaded here")
        top = min(vs, key=lambda v: "ABCDEZ".find(v["strongest_level"] or "Z"))
        opens, focus = _seq_opens(file, top), {"variant": top["variant"]}
    return {"workbench": "genomics", "title": "Tumor sequencing", "note": None, "cards": [card(
        "Key drivers", text, f"{OBSERVED} (mutation), {HYPOTHESIS} (CIViC evidence, for "
        "clinician review)", ", ".join(dict.fromkeys(f"{t.name}" + (
            "" if t.month is None else f", month {t.month}") for t in seq)), method,
        "CIViC curated evidence levels (A validated … E inferential)", "strong", opens, focus)]}


def queue(file, version: int | None = None, lookup=None) -> list[dict]:
    """One item per observed variant, by the strength of its CIViC evidence: level A or B
    (consequence 2, trust strong), C to E (1, moderate), none (1, weak). Nothing without CIViC:
    an unknown evidence base is not a finding to triage."""
    vs, civic = file_variants(file, version, lookup)
    if not civic:
        return []
    out = []
    for v in vs:
        level, items = v["strongest_level"], v["interpretation"]["items"]
        if level is None:
            trust, consequence, why = "weak", 1, "no CIViC item for this variant in breast cancer"
        else:
            trust, consequence = ("strong", 2) if level in "AB" else ("moderate", 1)
            therapies = sorted({t for i in items if i.get("evidence_level") == level
                                for t in _therapies(i)})
            why = (f"CIViC level {level} ({LEVELS.get(level, '?')}): {len(items)} item(s); "
                   f"therapies named at that level: {', '.join(therapies) or 'none'}; evidence "
                   "for clinician review, never a recommendation")
        out.append(look(
            v["variant"], f"{v['variant']} ({v['sample']}, {v['detection']['when']})", why,
            f"{OBSERVED} (mutation), {HYPOTHESIS} (CIViC evidence)", trust, consequence,
            _seq_opens(file, v), source=f"{v['test']}, {v['detection']['when']}",
            key=variant_key(file, v), focus={"variant": v["variant"]}, month=v["month"],
            threshold="CIViC curated evidence levels"))
    return out


def report_csv(file, variants: list[dict], reviews: dict) -> str:
    """One row per variant and CIViC item (a variant without items gets one row), with the
    item's mark, or the variant's when the row has no item."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["variant", "gene", "change", "sample", "when", "assay", "allele_fraction",
                "strongest_level", "civic_items", "evidence_level", "therapies", "significance",
                "direction", "disease", "citation", "url", "marks"])
    for v in variants:
        d, items = v["detection"], v["interpretation"]["items"]
        base = [v["variant"], v["gene"], v["change"], v["sample"], d["when"], d["assay"],
                d["allele_fraction"], v["strongest_level"] or "", len(items)]
        for n, i in enumerate(items or [{}]):
            key = item_key(file, v, i, n) if items else variant_key(file, v)
            w.writerow(base + [i.get(k, "") for k in ("evidence_level", "therapies",
                                                      "significance", "direction", "disease",
                                                      "citation", "url")]
                       + [mark_text(reviews.get(key))])
    return buf.getvalue()

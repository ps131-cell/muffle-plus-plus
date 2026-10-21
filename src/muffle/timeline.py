"""A synthetic breast-cancer patient whose profile updates at every event (milestone 1, part 3).

SYNTHETIC: this patient was written by hand. It is not a real person and was not
sampled or copied from any dataset. Only the *structure* of its record (event types, units,
treatment classes, drug names) follows MSK-CHORD's cBioPortal timelines, so the MSK-CHORD risk
models of ``muffle.longitudinal`` score it with exactly the features they were evaluated on.

At every event from time 0 (the first tumor sequencing) on, the patient is re-scored for the
**risk of progression or death in the next 12 months** by the record-so-far models of the latest
landmark at or before that event: one model per evaluation seed (0-4), each trained on that
seed's 80% split. The risk shown is their mean and the range their spread; the diagnosis-only
baseline is scored the same way. What changed since the previous update is attributed one change
at a time against the previous record (approximate: changes interact, and the rest is reported).

``scripts/make_timeline_patient.py`` runs this locally against MSK-CHORD and writes only this
synthetic patient's record and scores (plus the aggregate test metrics) to
``app/timeline_synthetic.json``; no MSK-CHORD patient and no model leaves the machine.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from muffle.longitudinal import BASELINE, DAYS_PER_MONTH, DRIVERS, features

PATIENT_ID = "SYNTHETIC-001"
NOTICE = ("Synthetic patient: written by hand to show how a record grows, not a real person "
          "and not taken from any dataset. Its record follows the structure of MSK-CHORD "
          "timelines so the MSK-CHORD risk models can score it.")
MODEL_NOTE = ("Risk models trained locally on MSK-CHORD breast cancer timelines (Jee et al., "
              "Nature 2024; CC BY-NC-ND 4.0). Only this synthetic patient's scores and aggregate "
              "test metrics are published; no MSK-CHORD patient or model leaves the machine.")
STAGES = {1: "I", 2: "II", 3: "III", 4: "IV"}

# month: months after the first tumor sequencing (time 0); diagnosis comes earlier
EVENTS: list[dict] = [
    {"month": -40, "kind": "Diagnosis", "stage": 2, "hr": 1, "her2": 0,
     "text": "Invasive ductal carcinoma, stage II, hormone-receptor positive, HER2 negative"},
    {"month": -39, "kind": "Treatment",
     "treatments": [("Chemo", "DOXORUBICIN"), ("Chemo", "CYCLOPHOSPHAMIDE")],
     "text": "Adjuvant chemotherapy: doxorubicin + cyclophosphamide"},
    {"month": -36, "kind": "Treatment", "treatments": [("Chemo", "PACLITAXEL")],
     "text": "Adjuvant chemotherapy: paclitaxel"},
    {"month": -33, "kind": "Treatment", "treatments": [("Hormone", "LETROZOLE")],
     "text": "Adjuvant endocrine therapy: letrozole"},
    {"month": -2, "kind": "Lab", "ca153": 48, "text": "CA 15-3 48 U/mL (reference below 30)"},
    {"month": -1, "kind": "Imaging", "progression": True, "sites": ["Bone"],
     "text": "Imaging: new bone lesions, read as progression (metastatic recurrence)"},
    {"month": 0, "kind": "Sequencing", "mutations": [("PIK3CA", "H1047R")],
     "text": "Tumor sequencing of the bone biopsy: PIK3CA H1047R"},
    {"month": 1, "kind": "Clinic visit", "ecog": 1, "ca153": 46,
     "treatments": [("Targeted", "PALBOCICLIB"), ("Hormone", "FULVESTRANT")],
     "text": "ECOG 1; CA 15-3 46 U/mL; starts palbociclib + fulvestrant"},
    {"month": 4, "kind": "Lab", "ca153": 35, "text": "CA 15-3 35 U/mL"},
    {"month": 7, "kind": "Imaging", "ca153": 30, "ecog": 0,
     "text": "Imaging: stable disease; CA 15-3 30 U/mL; ECOG 0"},
    {"month": 11, "kind": "Lab", "ca153": 52, "text": "CA 15-3 52 U/mL (rising)"},
    {"month": 12, "kind": "Imaging", "progression": True, "sites": ["Liver"],
     "text": "Imaging: new liver lesions, read as progression"},
    {"month": 13, "kind": "Clinic visit", "ecog": 1, "treatments": [("Targeted", "ALPELISIB")],
     "text": "ECOG 1; adds alpelisib to fulvestrant"},
    {"month": 16, "kind": "Lab", "ca153": 41, "text": "CA 15-3 41 U/mL"},
    {"month": 19, "kind": "Imaging", "ca153": 34,
     "text": "Imaging: stable disease; CA 15-3 34 U/mL"},
    {"month": 24, "kind": "Clinic visit", "ecog": 1, "ca153": 31,
     "text": "Imaging stable; CA 15-3 31 U/mL; ECOG 1"},
]

# SYNTHETIC: a hand-written ctDNA (liquid biopsy) series for the same patient (docs/ctdna.md). It is
# a separate constant so that EVENTS, and the risk updates row-aligned with it in
# app/timeline_synthetic.json, never change; the risk models never saw it. No open serial breast
# ctDNA data exists (docs/model_survey.md §5), so every value here is invented to show how the
# ctDNA monitor reads a series. Months are the record's own timeline (it has no calendar dates);
# variant allele fractions are in percent of cell-free DNA; None = not detected (below the
# detection limit). Written to tell three stories: PIK3CA H1047R (found in the month-0 tumor
# sequencing) tracks burden, up before both progressions and down under treatment; ESR1 D538G
# emerges under letrozole and rises before the liver progression; DNMT3A R882H sits at a stable
# low fraction whatever the treatment, the pattern of clonal hematopoiesis.
CTDNA: dict = {
    "assay": "targeted cell-free DNA panel, plasma only, no matched white-cell sequencing "
             "(synthetic)",
    "synthetic": True,
    "detection_limit": 0.1,  # PLACEHOLDER: % variant allele fraction
    "variants": ("PIK3CA H1047R", "ESR1 D538G", "DNMT3A R882H"),
    "samples": [  # (month, PIK3CA H1047R, ESR1 D538G, DNMT3A R882H)
        {"month": m, "vaf": dict(zip(("PIK3CA H1047R", "ESR1 D538G", "DNMT3A R882H"), v,
                                     strict=True))}
        for m, *v in [(-12, 0.12, None, 0.42), (-6, 0.35, None, 0.45), (-2, 1.6, 0.18, 0.40),
                      (0, 2.4, 0.31, 0.47), (4, 0.9, 0.22, 0.44), (7, 0.3, 0.15, 0.41),
                      (9, 0.6, 0.4, 0.46), (11, 1.9, 1.1, 0.43), (13, 3.2, 2.0, 0.45),
                      (16, 1.1, 0.7, 0.48), (19, 0.4, 0.25, 0.44), (24, 0.18, None, 0.46)]],
}

# what the attribution calls each group of model features
GROUPS = {
    "diagnosis (stage, HR, HER2)": lambda c: c in BASELINE,
    "treatments so far": lambda c: c.startswith("rx_"),
    "progression history":
        lambda c: c in ("progressions_so_far", "months_since_progression"),
    "metastatic sites": lambda c: c == "metastatic_sites",
    "CA 15-3": lambda c: c.startswith("ca153_"),
    "CEA": lambda c: c.startswith("cea_"),
    "performance status (ECOG)": lambda c: c == "ecog_last",
    "sequenced drivers": lambda c: c.startswith("mut_"),
}


def tables(events: list[dict] = EVENTS) -> dict[str, pd.DataFrame]:
    """The record in the shape ``muffle.longitudinal.load`` returns, for one patient."""
    def rows(key, columns, make):
        return pd.DataFrame([[PATIENT_ID, e["month"] * DAYS_PER_MONTH, *r]
                             for e in events if key in e for r in make(e[key])],
                            columns=["PATIENT_ID", "day", *columns])

    dx = next(e for e in events if e["kind"] == "Diagnosis")
    patients = pd.DataFrame({"stage": [float(dx["stage"])], "hr": [float(dx["hr"])],
                             "her2": [float(dx["her2"])]}, index=[PATIENT_ID])
    return {
        "patients": patients,
        "treatment": rows("treatments", ["SUBTYPE", "AGENT"], lambda v: v),
        "progression": rows("progression", ["PROGRESSION"], lambda v: [["Y"]] if v else []),
        "sites": rows("sites", ["TUMOR_SITE"], lambda v: [[s] for s in v]),
        "ca153": rows("ca153", ["RESULT"], lambda v: [[str(v)]]),
        "cea": rows("cea", ["RESULT"], lambda v: [[str(v)]]),
        "ecog": rows("ecog", ["ECOG"], lambda v: [[str(v)]]),
        "drivers": rows("mutations", ["Hugo_Symbol", "HGVSp_Short"],
                        lambda v: [[g, f"p.{c}"] for g, c in v]),
    }


def observed(events: list[dict], month: float) -> list[list[str]]:
    """What the record says so far, as (finding, value) pairs: all **observed**."""
    past = [e for e in events if e["month"] <= month]

    def last(key):
        hit = [e for e in past if key in e]
        return hit[-1] if hit else None

    dx = next(e for e in past if e["kind"] == "Diagnosis")
    out = [["Diagnosis", f"stage {STAGES[dx['stage']]}, HR{'+' if dx['hr'] else '−'}, "
                         f"HER2{'+' if dx['her2'] else '−'} (month {dx['month']})"]]
    seq = last("mutations")
    if seq is None:
        out.append(["Driver mutations", "not sequenced yet (unknown, not wild type)"])
    else:
        found = {g for g, _ in seq["mutations"]}
        out.append(["Driver mutations", ", ".join(f"{g} {c}" for g, c in seq["mutations"])
                    + f" (month {seq['month']})"])
        out.append(["Sequenced, not found", ", ".join(g for g in DRIVERS if g not in found)])
    sites = [(s, e["month"]) for e in past for s in e.get("sites", [])]
    out.append(["Metastatic sites", ", ".join(f"{s} (month {m})" for s, m in sites) or "none"])
    prog = [e["month"] for e in past if e.get("progression")]
    out.append(["Progressions on imaging", f"{len(prog)}"
                + (f", last at month {prog[-1]}" if prog else "")])
    for key, name in (("ca153", "CA 15-3"), ("cea", "CEA")):
        e = last(key)
        out.append([f"Latest {name}", f"{e[key]} U/mL (month {e['month']})" if e
                    else "not measured"])
    e = last("ecog")
    out.append(["Latest ECOG", f"{e['ecog']} (month {e['month']})" if e else "not recorded"])
    rx = [f"{a.lower()} (month {e['month']})" for e in past for _, a in e.get("treatments", [])]
    out.append(["Treatments so far", ", ".join(rx) or "none"])
    return out


def _risks(models: list[tuple], x: pd.DataFrame) -> np.ndarray:
    """(seeds, rows) predicted probabilities."""
    return np.array([clf.predict_proba(x[cols])[:, 1] for clf, cols in models])


def _changed(a: pd.Series, b: pd.Series) -> bool:
    return not ((a == b) | (a.isna() & b.isna())).all()


def build(res: dict, evidence: dict | None = None, events: list[dict] = EVENTS) -> dict:
    """The synthetic patient's record, profile and risk updates, JSON-ready.

    ``res`` is ``muffle.longitudinal.evaluate(..., keep_models=True)``; ``evidence`` maps
    "GENE CHANGE" to CIViC items (``muffle.report.civic.evidence``) for the observed drivers."""
    landmarks = sorted(int(L) for L in res)
    models = {L: {name: [run["models"][name] for run in res[str(L)]["runs"]]
                  for name in ("baseline", "record_so_far")} for L in landmarks}
    data = tables(events)
    updates, prev = [], None
    for i, e in enumerate(events):
        u = {"event": i, "month": e["month"], "observed": observed(events, e["month"])}
        updates.append(u)
        if e["month"] < 0:
            continue
        L = max(m for m in landmarks if m <= e["month"])
        x = features(data, [PATIENT_ID], e["month"] * DAYS_PER_MONTH)
        r = _risks(models[L]["record_so_far"], x)[:, 0]
        b = _risks(models[L]["baseline"], x)[:, 0]
        u.update(landmark=L, risk=float(r.mean()), risk_range=[float(r.min()), float(r.max())],
                 baseline=float(b.mean()), baseline_range=[float(b.min()), float(b.max())])
        if prev is None:
            u["summary"] = (f"First estimate, at the first tumor sequencing: {u['risk']:.0%} "
                            f"(diagnosis-only baseline {u['baseline']:.0%}).")
        else:
            u.update(previous=prev["risk"], **_attribute(models, prev, L, x, u["risk"]))
        prev = {"x": x, "landmark": L, "risk": u["risk"]}
    return {
        "synthetic": True, "patient_id": PATIENT_ID, "notice": NOTICE, "model_note": MODEL_NOTE,
        "task": "risk of progression or death in the next 12 months",
        "events": [{k: e[k] for k in ("month", "kind", "text")} for e in events],
        "updates": updates,
        "models": {str(L): {"n": res[str(L)]["n"], "event_rate": res[str(L)]["event_rate"],
                            "auroc": res[str(L)]["record_so_far_auroc"],
                            "baseline_auroc": res[str(L)]["baseline_auroc"]}
                   for L in landmarks},
        "evidence": evidence or {},
    }


def _attribute(models: dict, prev: dict, L: int, x: pd.DataFrame, now: float) -> dict:
    """Split the change since the previous update: one changed feature group at a time (with
    the current model), the switch to a later landmark's model, and the rest (interactions)."""
    px = prev["x"]
    names, variants = [], []
    for name, member in GROUPS.items():
        cols = [c for c in x.columns if member(c)]
        if _changed(px.iloc[0][cols], x.iloc[0][cols]):
            v = px.copy()
            v[cols] = x[cols].to_numpy()
            names.append(name)
            variants.append(v)
    rec = models[L]["record_so_far"]
    base = float(_risks(rec, px).mean())  # the previous record, scored by the current model
    risks = _risks(rec, pd.concat(variants)).mean(axis=0) if variants else []
    changes = [{"what": n, "points": 100 * (float(r) - base)} for n, r in zip(names, risks,
                                                                              strict=True)]
    if L != prev["landmark"]:
        changes.append({"what": f"month-{L} model takes over",
                        "points": 100 * (base - prev["risk"])})
    rest = 100 * (now - prev["risk"]) - sum(c["points"] for c in changes)
    changes.append({"what": "interactions between changes", "points": rest})
    changes.sort(key=lambda c: -abs(c["points"]))
    return {"changes": changes, "summary": summary(prev["risk"], now, changes)}


def summary(before: float, now: float, changes: list[dict], k: int = 3) -> str:
    """One **model inference** sentence: the change and its largest parts."""
    delta = 100 * (now - before)
    parts = [f"{c['what']} {c['points']:+.0f}" for c in changes[:k] if abs(c["points"]) >= 0.5]
    head = (f"Risk of progression or death in the next 12 months {before:.0%} → {now:.0%} "
            f"({delta:+.0f} points)")
    return head + (": " + ", ".join(parts) + "." if parts else ".")

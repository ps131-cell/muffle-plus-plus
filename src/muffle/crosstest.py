"""Cross-test intelligence for a patient file (docs/WORKBENCHES.md §2 and §9): the version diff
in the three evidence columns, the discrepancy queue and "what would reduce uncertainty".

Pure functions over ``muffle.workspace.PatientFile``. Nothing here runs a model: the rules read
the file's observed pairs, tests, alerts and risk estimates. Every item carries its evidence type,
and every threshold its source; a placeholder says so. Treatment content is evidence for the
clinician's judgment, phrased as a question, never a recommendation (CLAUDE.md).
"""

from __future__ import annotations

import re
from statistics import median

from muffle.demo import ordinal
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workspace import ASSAYS, EGTM, MARKERS, RISK_JUMP, PatientFile

CONFIRM = ("a marker rise is unconfirmed until a second specimen within a month confirms it "
           f"({EGTM})")
CTDNA_SOURCE = ("PADA-1 (Bidard et al., Lancet Oncol 2022) and SERENA-6 (Bidard et al., NEJM "
                "2025): ESR1 mutations emerging in blood under aromatase inhibitors were caught "
                "by ctDNA before progression (docs/VISION.md); hypothesis for this patient")
ENDOCRINE = {"letrozole", "anastrozole", "exemestane", "tamoxifen", "fulvestrant", "elacestrant",
             "camizestrant"}
SITES = ("bone", "liver", "lung", "brain", "pleura", "skin", "lymph node", "peritoneum", "adrenal")
IMAGING_AGE = 6  # months; PLACEHOLDER: when the latest imaging counts as old after a marker rise

MARKER_NAMES = [name for name, _ in MARKERS.values()]
_RISE = re.compile(r"from (\S+) to (\S+)")
_DRIVER = re.compile(r"driver (\S+ \S+) has")


# ----------------------------------------------------------------------------- version diff

def _findings(pf: PatientFile, i: int) -> dict[str, dict[str, str]]:
    """Version i as {column: {finding: value}}. Tests accumulate (a test stays in the file);
    observed pairs, alerts and the risk estimate are the version's own."""
    v = pf.versions[i]
    cols: dict[str, dict[str, str]] = {OBSERVED: {}, INFERENCE: {}, HYPOTHESIS: {}}
    for name, value in v.observed:
        cols[OBSERVED][name] = value
    for t in (t for ver in pf.versions[:i + 1] for t in ver.tests):
        when = "" if t.month is None else f" (month {t.month})"
        cols[OBSERVED][f"{t.kind}: {t.name}{when}"] = t.result
    for a in v.alerts:
        col = (HYPOTHESIS if HYPOTHESIS in a.evidence
               else INFERENCE if a.evidence == INFERENCE else OBSERVED)
        cols[col][f"Alert: {a.what}"] = f"{a.source}; rule: {a.rule}"
    r = v.risk or {}
    if "value" in r:
        lo, hi = r["range"]
        cols[INFERENCE]["12-month risk"] = f"{r['value']:.0%}"
        cols[INFERENCE]["Risk range across seeds"] = f"{lo:.0%} to {hi:.0%}"
        cols[INFERENCE]["Diagnosis-only baseline"] = f"{r['baseline']:.0%}"
        cols[INFERENCE]["Landmark model"] = f"month-{r['landmark']} model"
    if "percentile" in r:
        cols[INFERENCE]["Cohort percentile"] = ordinal(r["percentile"])
        cols[INFERENCE]["Risk group"] = str(r["group"])
    return cols


def diff_versions(pf: PatientFile, a: int, b: int) -> list[dict]:
    """What differs between ``pf.versions[a]`` and ``pf.versions[b]``, per evidence column.
    Unchanged findings are left out; the attribution (``versions[b].changes``) is the shell's."""
    before, after, out = _findings(pf, a), _findings(pf, b), []
    for col in (OBSERVED, INFERENCE, HYPOTHESIS):
        for finding in dict.fromkeys([*before[col], *after[col]]):
            x, y = before[col].get(finding), after[col].get(finding)
            if x == y:
                continue
            status = "added" if x is None else "removed" if y is None else "changed"
            out.append({"column": col, "finding": finding, "before": x, "after": y,
                        "status": status})
    return out


# --------------------------------------------------------------------------- shared lookups

def _marker_rises(pf: PatientFile, i: int) -> list[tuple]:
    """(version index, alert, marker name, before, after) for every marker-rise alert so far."""
    out = []
    for j, v in enumerate(pf.versions[:i + 1]):
        for a in v.alerts:
            name = next((n for n in MARKER_NAMES if a.source.startswith(n)), None)
            if name and a.evidence == OBSERVED:
                m = _RISE.search(a.what)
                vals = (float(m.group(1)), float(m.group(2))) if m else (None, None)
                out.append((j, a, name, *vals))
    return out


def _imaging(pf: PatientFile, i: int) -> list[tuple[int, str]]:
    return [(t.month, t.result) for v in pf.versions[:i + 1] for t in v.tests
            if t.kind == "Imaging" and t.month is not None]


def _labs(pf: PatientFile, i: int, name: str) -> list[tuple[int, float]]:
    """(month, value) of one marker's Lab tests so far; the result reads '<value> <unit>'."""
    out = []
    for v in pf.versions[:i + 1]:
        for t in v.tests:
            if t.kind == "Lab" and t.name == name and t.month is not None:
                try:
                    out.append((t.month, float(t.result.split()[0])))
                except ValueError:
                    pass
    return out


def _driver_alerts(pf: PatientFile, i: int) -> list[tuple[int, object, str]]:
    """(version index, alert, variant) for sequenced drivers with level A or B evidence."""
    out = []
    for j, v in enumerate(pf.versions[:i + 1]):
        for a in v.alerts:
            if HYPOTHESIS in a.evidence and ("level A" in a.what or "level B" in a.what):
                m = _DRIVER.search(a.what)
                out.append((j, a, m.group(1) if m else a.what))
    return out


def _status(threshold: str) -> str:
    """Call a threshold a placeholder only when its own source says so."""
    return " (a placeholder, not validated)" if "placeholder" in threshold else ""


def _sites(text: str) -> set[str]:
    low = text.lower()
    return {s for s in SITES if s in low}


# ------------------------------------------------------------------------ discrepancy queue

def discrepancies(pf: PatientFile, i: int) -> list[dict]:
    """Tests that disagree as of version i. Each item says which two sources disagree, why that
    is a discrepancy, which test or document would settle it, and the evidence type."""
    out, v, now = [], pf.versions[i], pf.versions[i].month
    imaging = _imaging(pf, i)

    # 1. a marker rose while the latest imaging so far read stable
    if imaging:
        im_month, im_text = imaging[-1]
        for _, a, name, *_ in _marker_rises(pf, i):
            if "stable" in im_text.lower() and im_month < a.month:
                out.append({
                    "what": f"{name} rising while the latest imaging read stable",
                    "sources": [a.source, f"Imaging, month {im_month}"],
                    "months": [a.month, im_month],
                    "why": f"{a.what} at month {a.month}, but the latest imaging (month "
                           f"{im_month}) read: {im_text}. A marker can move before imaging "
                           "shows a change, or a single rise can be transient; the alert's "
                           f"threshold: {a.threshold}{_status(a.threshold)}.",
                    "would_settle": f"A second {name} specimen within a month ({CONFIRM}) and "
                                    "the next imaging.",
                    "evidence": OBSERVED})

    # 2. the 12-month risk jumped while every marker measured in this version fell
    prev = pf.versions[i - 1] if i > 0 else None
    if prev and prev.risk and v.risk and "value" in v.risk and "value" in prev.risk:
        jump = 100 * (v.risk["value"] - prev.risk["value"])
        fell, rose = [], []
        for name in MARKER_NAMES:
            labs = _labs(pf, i, name)
            this = [(m, x) for m, x in labs if m == now]
            earlier = [x for m, x in labs if m < now]
            if this and earlier:
                (fell if this[-1][1] < earlier[-1] else rose).append(
                    f"{name} {earlier[-1]:g} to {this[-1][1]:g}")
        if jump >= RISK_JUMP and fell and not rose:
            out.append({
                "what": "12-month risk up while the markers fell",
                "sources": [f"month-{v.risk.get('landmark')} model", f"Lab, month {now}"],
                "months": [now, now],
                "why": f"The model's 12-month risk rose {jump:+.0f} points since the previous "
                       f"version ({prev.risk['value']:.0%} to {v.risk['value']:.0%}; alert "
                       f"threshold {RISK_JUMP} points, a placeholder) while every marker measured "
                       f"in this version fell ({', '.join(fell)}). The rise comes from other "
                       "features (see what changed), not from the markers.",
                "would_settle": "The attribution under the report (which feature group moved "
                                "the estimate) and the next imaging.",
                "evidence": INFERENCE})

    # 3. two versions' summaries name different metastatic sites
    named = [(ver.month, _sites(ver.summary)) for ver in pf.versions[:i + 1]
             if _sites(ver.summary)]
    if len(named) >= 2:
        (m_old, old), (m_new, new) = named[-2], named[-1]
        missing = sorted(old - new)
        if missing:
            out.append({
                "what": "Metastatic sites named differently in two report versions",
                "sources": [f"Summary, month {m_old}", f"Summary, month {m_new}"],
                "months": [m_old, m_new],
                "why": f"The month-{m_old} summary names {', '.join(sorted(old))}; the "
                       f"month-{m_new} summary names {', '.join(sorted(new))} and no longer "
                       f"{', '.join(missing)}. A site that disappears from a report is either a "
                       "response or an omission.",
                "would_settle": "The imaging reports themselves (radiology workbench), read side "
                                "by side.",
                "evidence": OBSERVED})

    # 4. a sequenced driver with level A/B evidence and no treatment change recorded after it
    for j, a, variant in _driver_alerts(pf, i):
        if not any(ver.treatments for ver in pf.versions[j + 1:i + 1]):
            out.append({
                "what": f"Level A/B evidence for {variant} with no treatment change recorded",
                "sources": [a.source, f"Clinical record, month {now}"],
                "months": [a.month, now],
                "why": f"{a.what} (month {a.month}); as of month {now} the record shows no "
                       "treatment start after the sequencing. A question for the clinician: was "
                       "the evidence reviewed, or is a decision recorded elsewhere? The evidence "
                       "is CIViC's, for review, not a recommendation.",
                "would_settle": "The clinical record: a treatment entry or a note that the "
                                "evidence was reviewed (CIViC, curated evidence levels).",
                "evidence": HYPOTHESIS})
    return out


# ---------------------------------------------------------------- what would reduce uncertainty

def uncertainty_reducers(pf: PatientFile, i: int) -> list[dict]:
    """Open hypotheses as of version i and the test that would resolve each: evidence for the
    clinician's judgment, never an instruction."""
    out, v, now = [], pf.versions[i], pf.versions[i].month

    if now is not None:
        # an unconfirmed marker rise: no later specimen of that marker yet
        for _, a, name, lo, hi in _marker_rises(pf, i):
            if not any(m > a.month for m, _ in _labs(pf, i, name)):
                expect = (f"a second value near {hi:g} or above confirms the rise; a value back "
                          f"near {lo:g} means it was transient" if lo is not None else
                          "a second value confirms or withdraws the rise")
                out.append({
                    "open_question": f"Is the {name} rise at month {a.month} real? "
                                     "No second specimen yet.",
                    "test": f"Repeat {name} specimen within a month",
                    "expectation": expect,
                    "source": CONFIRM, "evidence": HYPOTHESIS})

        # not sequenced since the last tumor sequencing while on endocrine therapy
        seq = [t.month for ver in pf.versions[:i + 1] for t in ver.tests
               if t.kind == "Sequencing" and t.month is not None]
        endocrine = [(rx, ver.month) for ver in pf.versions[:i + 1] for rx in ver.treatments
                     if rx in ENDOCRINE]
        if seq and endocrine and now > seq[-1]:
            rx = ", ".join(f"{name} (month {m})" for name, m in endocrine)
            out.append({
                "open_question": f"Has the tumor acquired resistance alterations (ESR1 and "
                                 f"others) since the sequencing at month {seq[-1]}, under "
                                 f"endocrine therapy ({rx})?",
                "test": "ctDNA sequencing for ESR1 and other endocrine-resistance alterations",
                "expectation": "an emerging ESR1 mutation would be an observed finding that "
                               "changes the evidence base; none found narrows the hypothesis. "
                               "The cited trials followed patients on aromatase inhibitors; "
                               "this record's agents differ, so the transfer is a hypothesis.",
                "source": CTDNA_SOURCE, "evidence": HYPOTHESIS})

        # imaging older than IMAGING_AGE months while a marker rose since it
        imaging = _imaging(pf, i)
        rises = _marker_rises(pf, i)
        if imaging and rises:
            im_month = imaging[-1][0]
            after = [a for _, a, *_ in rises if a.month > im_month]
            if after and now - im_month > IMAGING_AGE:
                gaps = [b - a for (a, _), (b, _) in zip(imaging, imaging[1:], strict=False)]
                cadence = (f"this record's own cadence: imaging every {median(gaps):g} months "
                           f"(median of {len(gaps)} intervals)" if gaps else
                           "this record holds one imaging study, so it has no cadence yet")
                out.append({
                    "open_question": f"The latest imaging is {now - im_month} months old (month "
                                     f"{im_month}) and {after[-1].source} rose since it.",
                    "test": "Repeat imaging per the clinic's schedule",
                    "expectation": "imaging confirms progression, finds the marker rise "
                                   "unexplained, or reads stable",
                    "source": f"{cadence}; the {IMAGING_AGE}-month interval is a placeholder, "
                              "not a guideline", "evidence": HYPOTHESIS})

    # a TCGA case: a data layer not measured, and what measuring it would do to the estimate
    if pf.kind == "TCGA-BRCA":
        missing = dict(v.observed).get("Not measured", "none")
        what_if = pf.model.get("what_if", {})
        for layer in ([] if missing == "none" else missing.split(", ")):
            name = ASSAYS.get(layer, layer)
            numbers = what_if.get(layer)
            out.append({
                "open_question": f"Would the {layer} layer move the estimate? It was not "
                                 "measured, so the model scored it as missing (a mask), not as "
                                 "normal.",
                "test": name,
                "expectation": (f"what-if from the model: {numbers}" if numbers is not None else
                                "the model takes a mask per layer, so the layer would enter the "
                                "estimate directly; this file's model exposes no what-if numbers,"
                                " so the effect is named, not quantified"),
                "source": "model inference: the clinical-anchored residual model with a layer "
                          "mask (tests/test_model.py)",
                "evidence": INFERENCE})
    return out

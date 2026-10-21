"""Cross-test logic: version diff, discrepancy queue and uncertainty reducers."""

import json
from pathlib import Path

from muffle.crosstest import diff_versions, discrepancies, uncertainty_reducers
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workspace import EGTM, IMPLEMENTED, PLANNED, VALIDATED, Alert, PatientFile, Version
from muffle.workspace import Test as WorkspaceTest
from muffle.workspace import synthetic_file

ROOT = Path(__file__).resolve().parents[1]
DIFF_KEYS = {"column", "finding", "before", "after", "status"}
DISC_KEYS = {"what", "sources", "months", "why", "would_settle", "evidence", "rule", "basis",
             "trust", "consequence", "opens", "focus", "key"}
RED_KEYS = {"open_question", "test", "expectation", "source", "evidence"}
KINDS = {OBSERVED, INFERENCE, HYPOTHESIS}


def synthetic() -> PatientFile:
    tl = json.loads((ROOT / "app" / "timeline_synthetic.json").read_text(encoding="utf-8"))
    return synthetic_file(tl)


def version(month, observed=(), risk=None, summary="", alerts=(), tests=(), treatments=()):
    return Version(month, f"month {month}", "event", [list(p) for p in observed], risk, summary,
                   [], list(alerts), list(tests), list(treatments))


def handmade(versions, kind="synthetic", model=None) -> PatientFile:
    return PatientFile("HAND-001", kind, "Synthetic patient: written by hand", "Breast cancer",
                       versions, "synthetic", model or {})


def rise_alert(month, before, after):
    return Alert(f"CA 15-3 rose from {before:g} to {after:g} U/mL ({after / before - 1:+.0%}), "
                 "above the reference limit of 30", month, f"CA 15-3, month {month}", OBSERVED,
                 "above the reference limit and at least 25% above the previous value",
                 "limit from the record; 25% rise is a placeholder")


def lab(month, value):
    return WorkspaceTest("Lab", month, "CA 15-3", f"{value:g} U/mL", "labs", IMPLEMENTED)


def imaging(month, text):
    return WorkspaceTest("Imaging", month, "Imaging report", text, "imaging", PLANNED)


# ------------------------------------------------------------------------------ diff_versions

def test_diff_of_the_synthetic_file_across_the_month_12_progression():
    pf = synthetic()
    items = diff_versions(pf, 10, 11)  # month 11 (lab) -> month 12 (imaging progression)
    assert all(set(i) == DIFF_KEYS for i in items)
    assert {i["column"] for i in items} <= KINDS
    by = {(i["column"], i["finding"]): i for i in items}
    sites = by[(OBSERVED, "Metastatic sites")]
    assert sites["status"] == "changed"
    assert "Liver" in sites["after"] and "Liver" not in sites["before"]
    assert by[(OBSERVED, "Imaging: Imaging report (month 12)")]["status"] == "added"
    assert by[(INFERENCE, "12-month risk")] == {
        "column": INFERENCE, "finding": "12-month risk", "before": "37%", "after": "88%",
        "status": "changed"}
    assert by[(INFERENCE, "Landmark model")]["after"] == "month-12 model"
    status = {i["finding"]: i["status"] for i in items if i["finding"].startswith("Alert")}
    assert [s for f, s in status.items() if f.startswith("Alert: CA 15-3 rose")] == ["removed"]
    assert [s for f, s in status.items() if f.startswith("Alert: 12-month risk up")] == ["added"]
    assert all(i["column"] == INFERENCE for i in items if "risk up" in i["finding"])
    # unchanged findings are not listed; the attribution is not duplicated
    assert not [i for i in items if i["finding"] == "Diagnosis"]
    assert not [i for i in items if "progression history" in i["finding"]]
    assert diff_versions(pf, 11, 11) == []


def test_diff_puts_the_driver_alert_in_the_hypothesis_column():
    pf = synthetic()
    items = diff_versions(pf, 5, 6)  # month -1 -> month 0 (sequencing, level A evidence)
    hyp = [i for i in items if i["column"] == HYPOTHESIS]
    assert len(hyp) == 1 and hyp[0]["status"] == "added" and "PIK3CA H1047R" in hyp[0]["finding"]
    assert [i["finding"] for i in items if i["column"] == INFERENCE] == [
        "12-month risk", "Risk range across seeds", "Diagnosis-only baseline", "Landmark model"]


def test_diff_of_a_tcga_style_file_shows_percentile_and_group():
    a = version(None, [["Stage", "II"]], {"percentile": 40.0, "group": "medium"})
    b = version(None, [["Stage", "II"]], {"percentile": 81.3, "group": "high"})
    items = diff_versions(handmade([a, b], "TCGA-BRCA"), 0, 1)
    assert {(i["finding"], i["before"], i["after"]) for i in items} == {
        ("Cohort percentile", "40th", "81st"), ("Risk group", "medium", "high")}


# ------------------------------------------------------------------------------ discrepancies

def test_marker_rise_against_stable_imaging_in_the_synthetic_record():
    pf = synthetic()
    items = discrepancies(pf, 10)  # month 11
    assert all(set(i) == DISC_KEYS for i in items)
    marker = [i for i in items if i["what"].startswith("CA 15-3 rising")]
    assert len(marker) == 1
    m = marker[0]
    assert m["sources"] == ["CA 15-3, month 11", "Imaging, month 7"]
    assert m["months"] == [11, 7] and m["evidence"] == OBSERVED
    assert "stable" in m["why"] and "EGTM" in m["why"] and "placeholder" not in m["why"]
    assert "EGTM" in m["would_settle"] and "within a month" in m["would_settle"]
    # once imaging at month 12 read progression the disagreement is gone
    assert not [i for i in discrepancies(pf, 11) if i["what"].startswith("CA 15-3 rising")]
    # the driver question is open only until the treatment at month 1 is recorded
    assert [i["evidence"] for i in discrepancies(pf, 6)] == [HYPOTHESIS]
    assert "never" not in discrepancies(pf, 6)[0]["why"]
    assert not discrepancies(pf, 7)
    for i in range(len(pf.versions)):
        for d in discrepancies(pf, i):
            assert "should" not in d["why"].lower() and "should" not in d["would_settle"].lower()


def test_risk_jump_while_markers_fell_and_differing_sites():
    risk_a = {"value": 0.30, "range": [0.28, 0.32], "baseline": 0.4, "landmark": 0}
    risk_b = {"value": 0.55, "range": [0.5, 0.6], "baseline": 0.4, "landmark": 6}
    pf = handmade([
        version(0, risk=risk_a, summary="Imaging: lesions in bone and liver.", tests=[lab(0, 50)]),
        version(6, risk=risk_b, summary="Imaging: bone lesion stable.", tests=[lab(6, 40)]),
    ])
    items = discrepancies(pf, 1)
    kinds = {i["what"]: i for i in items}
    jump = kinds["12-month risk up while the markers fell"]
    assert jump["evidence"] == INFERENCE and jump["months"] == [6, 6]
    assert "+25 points" in jump["why"] and "CA 15-3 50 to 40" in jump["why"]
    sites = kinds["Metastatic sites named differently in two report versions"]
    assert sites["evidence"] == OBSERVED and "no longer liver" in sites["why"]
    assert sites["sources"] == ["Summary, month 0", "Summary, month 6"]
    assert not discrepancies(pf, 0)


def test_a_placeholder_threshold_is_named_as_one_only_when_the_alert_says_so():
    pf = handmade([version(2, tests=[imaging(2, "Imaging: stable disease")]),
                   version(5, alerts=[rise_alert(5, 20, 40)], tests=[lab(5, 40)])])
    why = discrepancies(pf, 1)[0]["why"]
    assert "25% rise is a placeholder (a placeholder, not validated)" in why


def test_a_file_with_one_version_and_no_alerts_has_nothing_to_queue():
    pf = handmade([version(None, [["Not measured", "methylation"]],
                           {"percentile": 7.0, "group": "low"})], "TCGA-BRCA")
    assert discrepancies(pf, 0) == []


# ----------------------------------------------------------------------- uncertainty_reducers

def test_reducers_in_the_synthetic_record():
    pf = synthetic()
    items = uncertainty_reducers(pf, 10)  # month 11
    assert all(set(i) == RED_KEYS for i in items)
    tests = [i["test"] for i in items]
    assert tests == ["Repeat CA 15-3 specimen within a month",
                     "ctDNA sequencing for ESR1 and other endocrine-resistance alterations"]
    repeat, ctdna = items
    assert EGTM in repeat["source"] and "52" in repeat["expectation"]
    assert "PADA-1" in ctdna["source"] and "SERENA-6" in ctdna["source"]
    assert "fulvestrant (month 1)" in ctdna["open_question"]
    assert all(i["evidence"] == HYPOTHESIS for i in items)
    # imaging at month 7 is 4 months old: below the (placeholder) 6-month age
    assert not [i for i in items if i["test"].startswith("Repeat imaging")]
    # the rise at month 11 is followed by a specimen at month 16
    assert not [i for i in uncertainty_reducers(pf, 13) if i["test"].startswith("Repeat CA")]
    # before the first sequencing there is nothing to resolve
    assert uncertainty_reducers(pf, 3) == []
    for i in range(len(pf.versions)):
        for r in uncertainty_reducers(pf, i):
            assert "should" not in r["open_question"].lower()
            assert "should" not in r["expectation"].lower()


def test_old_imaging_after_a_rise_cites_the_records_cadence_as_a_placeholder():
    pf = handmade([
        version(-5, tests=[imaging(-5, "Imaging: stable disease")]),
        version(2, tests=[imaging(2, "Imaging: stable disease")]),
        version(10, alerts=[rise_alert(10, 20, 40)], tests=[lab(10, 40)]),
    ])
    items = {i["test"]: i for i in uncertainty_reducers(pf, 2)}
    im = items["Repeat imaging per the clinic's schedule"]
    assert "8 months old" in im["open_question"]
    assert "every 7 months" in im["source"] and "placeholder" in im["source"]
    assert "Repeat CA 15-3 specimen within a month" in items
    assert "ctDNA" not in " ".join(items)  # never sequenced, no endocrine therapy


def test_missing_layer_in_a_tcga_case_names_the_assay_and_what_if_numbers_when_exposed():
    risk = {"percentile": 7.0, "group": "low"}
    v = version(None, [["Not measured", "methylation, protein"]], risk)
    plain = uncertainty_reducers(handmade([v], "TCGA-BRCA", {"status": VALIDATED}), 0)
    assert [i["test"] for i in plain] == ["DNA methylation array (450K)", "Protein array (RPPA)"]
    assert all(i["evidence"] == INFERENCE and "not quantified" in i["expectation"] for i in plain)
    rich = uncertainty_reducers(handmade([v], "TCGA-BRCA", {"what_if": {"protein": "+0.1"}}), 0)
    assert "what-if from the model: +0.1" in rich[1]["expectation"]
    assert "not quantified" in rich[0]["expectation"]
    none = version(None, [["Not measured", "none"]], {"percentile": 7.0, "group": "low"})
    assert uncertainty_reducers(handmade([none], "TCGA-BRCA"), 0) == []

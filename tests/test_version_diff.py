"""The version diff (muffle.version_diff): the risk delta against the model's own uncertainty, the
findings, tests, attention queue and summary note that changed between two report versions, on
the synthetic patient and on a TCGA file with imported tests."""

import json
from pathlib import Path
from types import SimpleNamespace

from muffle import version_diff as vd
from muffle.imports import imaging_test, lab_tests, parse_labs
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workspace import add_version, case_file, synthetic_file

ROOT = Path(__file__).resolve().parents[1]
SCORES = json.loads((ROOT / "app" / "omics_scores.json").read_text(encoding="utf-8"))
LABELS = (OBSERVED, INFERENCE, HYPOTHESIS)


def synthetic():
    return synthetic_file(json.loads((ROOT / "app" / "timeline_synthetic.json").read_text(
        encoding="utf-8")))


def tcga_with_imports():
    """Case 299 as the app builds it (its real precomputed scores), then two CA 15-3 values and
    an imaging report imported."""
    case = SimpleNamespace(index=299, site="site-2", percentile=88.0, group="high", age=55.0,
                           stage="III", layers=["clinical", "genomic", "rna", "protein"],
                           missing=["methylation"], mutations=["PIK3CA p.H1047R"],
                           log_risk=SCORES["cases"]["299"]["log_risk"])
    pf = case_file(case, 0.7)
    ok, _ = parse_labs(b"month,marker,value,unit\n0,CA 15-3,20,U/mL\n1,CA 15-3,45,U/mL\n")
    tests, observed = lab_tests(ok)
    pf = add_version(pf, tests, 1, "Imported lab results", "AB", "14:10", observed)
    scan = imaging_test("CT CAP", "New liver lesions, consistent with progression.", 3, "i1", "")
    return add_version(pf, [scan], 3, "Imported imaging report", "AB", "14:12")


def month(pf, m):
    return [v.month for v in pf.versions].index(m)


def test_a_risk_jump_beyond_the_five_models_spread_is_up_with_its_why():
    pf = synthetic()
    d = vd.diff(pf, month(pf, 11), month(pf, 12))  # imaging reads progression in the liver
    r = d["risk"]
    assert (r["kind"], r["direction"], r["shift"], r["exceeds"]) == ("probability", "up", "up",
                                                                      True)
    assert round(r["points"]) == 51 and r["models"] == (6, 12)
    assert r["text"].startswith("12-month risk +51 points (37% → 88%): beyond the 5 models' "
                                "spread") and "month-12 model takes over" in r["text"]
    assert r["uncertainty"]["before"][0] < r["before"] < r["uncertainty"]["before"][1]
    assert r["evidence"] == INFERENCE and [w["version"] for w in r["why"]] == [
        "month 12 · Imaging"]
    assert d["when"] == ("month 11", "month 12") and d["versions"] == 1
    assert vd.SNAPSHOT == d["snapshot"] and "not a trend" in d["snapshot"]


def test_a_move_inside_the_spread_is_within_and_the_order_does_not_matter():
    pf = synthetic()
    a, b = month(pf, 1), month(pf, 4)  # 52% → 50%; the 5-model ranges overlap
    r = vd.diff(pf, b, a)["risk"]
    assert (r["direction"], r["shift"], r["exceeds"]) == ("down", "within", False)
    assert "within the 5 models' spread" in r["text"]
    assert vd.diff(pf, b, a) == vd.diff(pf, a, b)
    same = vd.diff(pf, a, a)
    assert not (same["findings"] or same["tests"] or same["queue"] or same["note"])


def test_no_estimate_and_the_first_estimate_say_so_without_a_delta():
    pf = synthetic()
    before = vd.risk_delta(pf, 0, 1)
    assert before["shift"] == "none" and before["delta"] is None
    assert "no risk estimate in either version" in before["text"]
    first = vd.risk_delta(pf, month(pf, -1), month(pf, 0))
    assert first["text"].startswith("first risk estimate: 38%") and first["shift"] == "none"


def test_findings_tests_queue_and_note_carry_labels_and_where_they_open():
    pf = synthetic()
    a, b = month(pf, 11), month(pf, 12)
    d = vd.diff(pf, a, b)
    rec = {f["what"]: f for f in d["findings"] if f["where"] == "Record"}
    assert set(rec) == {"Metastatic sites", "Progressions on imaging"}
    assert rec["Metastatic sites"]["after"] == "Bone (month -1), Liver (month 12)"
    assert rec["Metastatic sites"]["evidence"] == OBSERVED and \
        rec["Metastatic sites"]["opens"] == ("Report",)
    cards = [f for f in d["findings"] if f["where"] != "Record"]
    assert cards and all(f["opens"] and f["status"] in vd.STATUS for f in cards)
    for f in d["findings"] + d["queue"] + d["note"]:
        assert any(label in f["evidence"] for label in LABELS), f
    assert [(t["test"].name, t["version"]) for t in d["tests"]] == [("Imaging report", b)]
    new = [q for q in d["queue"] if q["status"] == "added"]
    assert any(q["sos"] and q["what"] == "New metastatic site: liver" for q in new)
    assert all(q["opens"] for q in new if q["sos"])
    assert [n["status"] for n in d["note"]] == ["changed"] and d["note"][0]["evidence"] == \
        INFERENCE and "37% → 88%" in d["note"][0]["after"]
    c = d["counts"]
    assert c["tests"] == 1 and c["changed"] >= 2 and c["sos"] >= 3


def test_a_tcga_file_with_imports_keeps_its_risk_and_shows_what_arrived():
    pf = tcga_with_imports()
    d = vd.diff(pf, 0, 1)  # two CA 15-3 values imported
    r = d["risk"]
    assert (r["kind"], r["delta"], r["shift"], r["exceeds"]) == ("percentile", 0, "same", None)
    assert r["text"].startswith("risk unchanged: 88th percentile")
    assert "no per-patient interval" in r["uncertainty"]["what"]
    assert [t["test"].name for t in d["tests"]] == ["CA 15-3", "CA 15-3"]
    assert all(t["imported"].startswith("imported by AB at 14:10") for t in d["tests"])
    assert any(q["sos"] and q["what"].startswith("CA 15-3 rose from 20 to 45")
               for q in d["queue"] if q["status"] == "added")
    assert [(n["status"], n["after"]) for n in d["note"]] == [
        ("added", "The estimate rests on the tumor sample alone, which this import does not "
                  "change.")]
    assert any(f["where"] == "Record" and f["status"] == "added" for f in d["findings"])
    whole = vd.diff(pf, 0, 2)  # the baseline against the latest: both imports
    assert whole["versions"] == 2 and len(whole["tests"]) == 3
    assert whole["imported"] == [v.label for v in pf.versions[1:]]
    assert any(q["what"].startswith("New metastatic site") for q in whole["queue"])


def test_the_report_headers_delta_line():
    pf = synthetic()
    line = vd.version_delta_line(pf, month(pf, 12))
    assert line.startswith("Since the previous version (month 11): 12-month risk +51 points "
                           "(37% → 88%); 1 test added; ")
    assert "new in the attention queue (" in line and line.endswith(".")
    assert vd.version_delta_line(pf, 0) == ("The first report version: nothing earlier to "
                                            "compare it with.")
    within = vd.version_delta_line(pf, month(pf, 4))
    assert "-2 points (52% → 50%, within the 5 models' spread)" in within
    tc = vd.version_delta_line(tcga_with_imports(), 1)
    assert tc.startswith("Since the previous version (the tumor sample): risk unchanged (the "
                         "estimate rests on the tumor sample); 2 tests added; ")


def test_data_from_the_shells_memo_is_used_as_given():
    pf = synthetic()
    a, b = month(pf, 11), month(pf, 12)
    calls = []

    def data(j):
        calls.append(j)
        return {"sums": {}, "queue": []}

    d = vd.diff(pf, a, b, data)
    assert calls == [a, b] and d["queue"] == [] and all(f["where"] == "Record"
                                                        for f in d["findings"])


def test_inline_shows_only_the_words_that_changed():
    segs = vd.inline("month 19: DNMT3A R882H 0.44% (stable), ESR1 D538G 0.25% (falling)",
                     "month 24: DNMT3A R882H 0.46% (stable), ESR1 D538G not detected")
    assert [s for s in segs if s[0] != "same"] == [
        ("del", "19:"), ("ins", "24:"), ("del", "0.44%"), ("ins", "0.46%"),
        ("del", "0.25% (falling)"), ("ins", "not detected")]
    long = vd.inline("word " * 30 + "old end", "word " * 30 + "new end")
    assert long[0][0] == "same" and long[0][1].startswith("… ") and len(long[0][1]) < 50
    assert [s for s in long if s[0] != "same"] == [("del", "old"), ("ins", "new")]
    assert vd.similarity("CA 15-3 34 U/mL", "CA 15-3 34 U/mL") == 1.0
    assert vd.similarity("Risk 62% → 46% (-15 points): progression history -15.",
                         "Risk 46% → 60% (+14 points): month-24 model takes over +24.") < 0.6


def test_a_queue_item_rekeyed_by_a_newer_specimen_is_one_item_not_two():
    pf = synthetic()
    d = vd.diff(pf, month(pf, 19), month(pf, 24))  # the latest CA 15-3 moves to month 24
    whats = [q["what"] for q in d["queue"]]
    assert len(whats) == len(set(whats))  # nothing gone and back under the same words
    lab = [q for q in d["queue"] if "CA 15-3" in q["what"]]
    assert [(q["status"], q["before"]) for q in lab] == [
        ("changed", "CA 15-3 34 U/mL at month 19: above limit")]

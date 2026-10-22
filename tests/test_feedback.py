"""The feedback ledger (muffle.feedback): hand-made marks on the synthetic file and a TCGA case
become records with the model or rule behind each, disagreement rates, "open" targets, an export
that loads back, and the report's Feedback section. Nothing is trained."""

import json
from pathlib import Path
from types import SimpleNamespace

from muffle import feedback
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workspace import case_file, finding_key, report_markdown, synthetic_file

ROOT = Path(__file__).resolve().parents[1]


def files() -> dict:
    tl = json.loads((ROOT / "app" / "timeline_synthetic.json").read_text(encoding="utf-8"))
    case = SimpleNamespace(index=661, site="site-2", percentile=99.2, group="high", age=57.0,
                           stage="III", layers=["genomic", "rna", "protein", "clinical"],
                           missing=["methylation"], mutations=["PIK3CA p.H1047R"])
    return {pf.id: pf for pf in (synthetic_file(tl), case_file(case, 0.728))}


def marks(fs: dict) -> dict:
    syn, tcga = fs["SYNTHETIC-001"], fs["Case 661"]
    rise = next(a for a in syn.versions[10].alerts if "rose from" in a.what)  # month 11

    def m(what, mark, by, at):
        return {"what": what, "mark": mark, "by": by, "at": f"2026-10-22 {at}"}

    return {
        finding_key(syn, "alert", rise.month, rise.what): m(rise.what, "disagree", "AB", "09:00"),
        finding_key(syn, "risk", 12): m("Risk estimate, month 12", "agree", "PS", "09:01"),
        finding_key(syn, "lab", "ca153", 11): m("CA 15-3 52 U/mL", "second look", "PS", "09:02"),
        finding_key(syn, "civic", "PIK3CA H1047R", "https://civic/1"):
            m("PIK3CA H1047R: CIViC level A", "reviewed", "", "09:03"),
        finding_key(tcga, "variant", "PIK3CA H1047R", None):
            m("PIK3CA H1047R", "agree", "AB", "09:04"),
        finding_key(tcga, "omics", "subtype", "PAM50"): m("PAM50 LumA", "disagree", "AB", "09:05"),
        finding_key(tcga, "risk", None): m("Risk estimate, baseline", "disagree", "PS", "09:06"),
    }


def test_each_mark_names_its_model_or_rule_version_and_evidence_label():
    fs = files()
    records = feedback.ledger(marks(fs), fs, build="abc123")
    assert len(records) == 7 and records[0]["at"] == "2026-10-22 09:06"  # newest first
    by = {(x["patient"], x["kind"]): x for x in records}
    alert = by[("SYNTHETIC-001", "alert")]
    assert (alert["method"], alert["evidence"], alert["methods_card"]) == (
        "Tumor marker rise (EGTM)", OBSERVED, feedback.ALERTS)
    assert alert["method_version"] == "EGTM breast cancer recommendations, app build abc123"
    assert alert["patient_kind"] == "synthetic" and alert["schema"] == feedback.SCHEMA
    assert by[("SYNTHETIC-001", "risk")]["method"] == "MSK-CHORD landmark models"
    assert by[("Case 661", "risk")]["method"] == "Multi-omic survival model"
    assert by[("Case 661", "risk")]["evidence"] == INFERENCE
    assert by[("Case 661", "omics")]["method"] == "PAM50 subtype call"
    assert by[("SYNTHETIC-001", "civic")]["evidence"] == HYPOTHESIS
    assert by[("SYNTHETIC-001", "civic")]["reviewer"] == ""
    # every finding kind maps to a source, and every source to a Methods card
    for kind in feedback.FINDING_KINDS:
        name, label = feedback.source_of(f"X|{kind}|a|b|c")
        assert name in feedback.SOURCES and label
    risk_jump = feedback.source_of("SYNTHETIC-001|alert|12|12-month risk up +51 points",
                                   "12-month risk up +51 points")
    assert risk_jump == ("Risk jump alert", INFERENCE)


def test_rates_lines_reviewers_and_disagreed_findings():
    fs = files()
    records = feedback.ledger(marks(fs), fs)
    rates = {g["method"]: g for g in feedback.rates(records)}
    survival = rates["Multi-omic survival model"]
    assert (survival["n"], survival["disagree"], survival["rate"]) == (1, 1, 1.0)
    assert survival["low"] < 0.25 and survival["high"] == 1.0  # one mark says little
    assert rates["Variant calls"]["rate"] == 0
    kinds = {g["kind"]: g for g in feedback.rates(records, "kind")}
    assert (kinds["risk"]["n"], kinds["risk"]["disagree"], kinds["risk"]["agree"]) == (2, 1, 1)
    assert feedback.line(records, feedback.SURVIVAL) == \
        "1 finding reviewed, 1 disagreed this session (Multi-omic survival model)"
    assert feedback.line(records, feedback.LABS).startswith("1 finding reviewed, 0 disagreed")
    assert feedback.line(records, feedback.CTDNA) == "0 findings reviewed, 0 disagreed this session"
    assert [x["kind"] for x in feedback.disagreed(records)] == ["risk", "omics", "alert"]
    people = {r["reviewer"]: r for r in feedback.reviewers(records)}
    assert people["AB"]["n"] == 3 and people["AB"]["patients"] == 2
    assert people["no initials"]["reviewed"] == 1
    assert feedback.wilson(0, 0) == (0.0, 1.0)
    low, high = feedback.wilson(5, 10)
    assert round(low, 2) == 0.24 and round(high, 2) == 0.76


def test_open_lands_on_the_findings_test_or_view():
    fs = files()
    syn, tcga = fs["SYNTHETIC-001"], fs["Case 661"]
    keys = list(marks(fs))
    assert feedback.target(syn, keys[0]) == (("Tests", "Lab", 11, "CA 15-3"), None)
    assert feedback.target(syn, keys[1]) == (("Report",), None)
    assert feedback.target(syn, keys[2]) == (("Tests", "Lab", 11, "CA 15-3"),
                                             {"marker": "ca153", "month": 11})
    opens, focus = feedback.target(tcga, keys[4])
    assert opens[:3] == ("Tests", "Mutation panel", None) and focus == {"variant": "PIK3CA H1047R"}
    opens, focus = feedback.target(tcga, keys[5])
    assert opens[1] == "Data layer" and focus == {"omics": keys[5]}
    assert feedback.target(syn, finding_key(syn, "imaging", "report", 12, "Liver")) == (
        ("Tests", "Imaging", 12, "Imaging report"), {"site": "Liver"})
    assert feedback.target(syn, finding_key(syn, "evolution", "x", "1")) == (("Evolution",), None)
    assert feedback.target(syn, finding_key(syn, "alert", 99, "gone")) is None


def test_export_loads_back_and_the_boundary_rejects_what_does_not_fit():
    fs = files()
    reviews = marks(fs)
    records = feedback.ledger(reviews, fs)
    text = feedback.export(records)
    assert len(text.splitlines()) == 7 and json.loads(text.splitlines()[0])["key"]
    loaded, rejected = feedback.load(text.encode(), fs)
    assert loaded == reviews and not rejected

    good = json.loads(text.splitlines()[0])
    bad = [{**good, "schema": "muffle-feedback/0"}, {**good, "patient": "Case 9"},
           {**good, "mark": "maybe"}, {**good, "kind": "lab"}, {**good, "at": "yesterday"},
           {**good, "reviewer": "ABCDEFG"}, {**good, "finding": 3}, [1, 2]]
    lines = [json.dumps(b) for b in bad] + ["{not json"]
    loaded, rejected = feedback.load("\n".join(lines).encode(), fs)
    assert not loaded and len(rejected) == 9
    for n, why in enumerate(("schema", "not in this app", "mark", "does not name", "time",
                             "initials", "finding missing", "not a record", "not JSON"), 1):
        assert rejected[n - 1].startswith(f"line {n}: ") and why in rejected[n - 1], why
    assert feedback.load(b"\xff\xfe", fs) == ({}, ["the file is not UTF-8 text"])
    assert feedback.load(b" " * (feedback.MAX_BYTES + 1), fs)[1][0].startswith("the file is")

    # the later mark wins; the session's on a tie
    key = next(iter(reviews))
    older = {key: {**reviews[key], "mark": "agree", "at": "2026-10-21 08:00"}}
    newer = {key: {**reviews[key], "mark": "agree", "at": "2026-10-23 08:00"},
             "Case 661|cn|ERBB2": {"what": "ERBB2", "mark": "agree", "by": "", "at": "x"}}
    assert feedback.merge(reviews, older) == (reviews, 0, 0)
    merged, added, replaced = feedback.merge(reviews, newer)
    assert (added, replaced) == (1, 1) and merged[key]["mark"] == "agree"
    assert reviews[key]["mark"] == "disagree"  # the session's store is not changed in place


def test_the_report_export_gains_a_feedback_section():
    fs = files()
    syn = fs["SYNTHETIC-001"]
    page = report_markdown(syn, 11, reviews=marks(fs))
    section = page[page.index("## Feedback"):]
    assert "nothing is sent or trained" in section
    assert "- alert: 1 marked (1 disagree)" in section and "- lab: 1 marked (1 second look)" in \
        section
    assert "Disagreed: 1" in section and "Tumor marker rise (EGTM)" in section
    assert "Case 661" not in section  # this patient's marks only
    assert report_markdown(syn, 11).rstrip().endswith("- no marks")

"""The patient file as one product: every workbench's summary and queue (the contract), the
cross-test discrepancy rules, the merged attention queue, the header, the list's filters and the
export (docs/WORKBENCHES.md §1, §2, §9)."""

import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from muffle import crosstest, overview
from muffle.demo import build_demo
from muffle.imports import document_test, lab_tests, parse_labs
from muffle.models import MuffleNet
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workbench import documents, genomics, labs, omics, slides
from muffle.workspace import (
    CARD_KEYS,
    FINDING_KINDS,
    ITEM_KEYS,
    TRUST,
    PatientFile,
    Version,
    add_version,
    case_file,
    finding_key,
    report_markdown,
    synthetic_file,
)
from muffle.workspace import Test as WorkspaceTest

ROOT = Path(__file__).resolve().parents[1]
SCORES = json.loads((ROOT / "app" / "omics_scores.json").read_text(encoding="utf-8"))
LABELS = (OBSERVED, INFERENCE, HYPOTHESIS)


def synthetic() -> PatientFile:
    tl = json.loads((ROOT / "app" / "timeline_synthetic.json").read_text(encoding="utf-8"))
    return synthetic_file(tl)


def tcga(index: int, stage=None, slides=(), docs=None, mutations=None, layers=None,
         log_risk="real") -> PatientFile:
    """A bundled TCGA case as the app builds it, with its real precomputed scores."""
    case = SimpleNamespace(
        index=index, site="site-1", percentile=60.0, group="medium", age=55.0, stage=stage,
        layers=layers or ["clinical", "genomic", "rna", "protein"], missing=["methylation"],
        mutations=mutations, log_risk=SCORES["cases"][str(index)]["log_risk"]
        if log_risk == "real" else log_risk)
    return case_file(case, 0.7, slides=slides,
                     documents=documents.case_documents(index) if docs is None else docs)


def check_contract(pf: PatientFile, i: int, lookup=None):
    sums = overview.summaries(pf, i, lookup)
    assert set(sums) >= {"labs", "genomics", "slides", "omics", "documents"}
    for name, s in sums.items():
        assert set(s) == {"workbench", "title", "cards", "note"} and s["workbench"] == name
        assert s["cards"] or s["note"], name  # nothing to show says why
        for c in s["cards"]:
            assert tuple(c) == CARD_KEYS and c["trust"] in TRUST
            assert any(label in c["evidence"] for label in LABELS), c
            assert c["text"] and c["source"] and c["method"] and c["threshold"]
            assert not c["opens"] or c["opens"][0] in ("Tests", "Timeline", "Evolution")
            if c["opens"][:1] == ("Tests",):  # it opens a test the file holds at this version
                assert tuple(c["opens"][1:]) in {(t.kind, t.month, t.name) for v in
                                                 pf.versions[: i + 1] for t in v.tests}
    for q in overview.queues(pf, i, lookup).values():
        for x in q:
            assert tuple(x) == ITEM_KEYS and x["trust"] in TRUST and x["consequence"] in (1, 2, 3)
            assert any(label in x["evidence"] for label in LABELS), x
            assert x["key"].startswith(pf.id + "|") and x["key"].split("|")[1] in FINDING_KINDS
    return sums


# ------------------------------------------------------------------ the workbench contract

def test_every_workbench_summary_and_queue_on_the_synthetic_file():
    pf = synthetic()
    for i in range(len(pf.versions)):
        check_contract(pf, i)
    sums = check_contract(pf, 11)  # month 12
    lab = {c["what"]: c for c in sums["labs"]["cards"]}
    assert lab["Latest CA 15-3"]["text"] == "CA 15-3 52 U/mL at month 11: above limit, rising (L4)"
    assert lab["Rise not confirmed"]["text"] == (
        "CA 15-3 30 → 52 U/mL at month 11 (L4): next specimen due by month 12")
    assert lab["Rise not confirmed"]["trust"] == "moderate" and "EGTM" in \
        lab["Rise not confirmed"]["threshold"]
    drivers = sums["genomics"]["cards"][0]
    assert drivers["text"] == "PIK3CA H1047R (CIViC level A)"
    assert drivers["opens"] == ("Tests", "Sequencing", 0, "Tumor sequencing")
    assert not sums["omics"]["cards"] and "no expression" in sums["omics"]["note"]
    assert "public example region" in sums["slides"]["note"]
    doc = {c["what"]: c for c in sums["documents"]["cards"]}
    assert doc["Documented stage and receptors"]["text"] == \
        "Stage II; Hormone receptors positive; HER2 negative"
    assert doc["Documented stage and receptors"]["focus"]["doc"] == "m-40-diagnosis"

    q = {x["pointer"]: x for x in labs.queue(pf, 11)}
    assert (q["L4"]["consequence"], q["L4"]["trust"]) == (2, "moderate")  # rise above the limit
    assert q["L3"]["trust"] == "weak" and "falling" in q["L3"]["what"]  # placeholder fall rule
    assert "L1" not in q  # an older above-limit value stays in the lab workbench's own queue
    v = genomics.queue(pf, 11)
    assert [(x["pointer"], x["consequence"], x["trust"]) for x in v] == [
        ("PIK3CA H1047R", 2, "strong")]
    assert labs.summary(pf, 0)["note"] == "no lab results in this file"  # month -40


def test_a_tcga_case_built_from_the_test_cohort(cohort, small_cfg, tmp_path):
    np.savez(tmp_path / "cohort.npz", **cohort)
    torch.manual_seed(0)
    torch.save({"model": MuffleNet.from_config(small_cfg).state_dict(), "config": small_cfg},
               tmp_path / "m.pt")
    demo = build_demo(tmp_path / "m.pt", tmp_path, n_clients=3)
    case = demo.cases[0]
    case.mutations = ["PIK3CA p.H1047R"]
    pf = case_file(case, demo.c_index)
    sums = check_contract(pf, 0)
    assert pf.versions[0].risk["log_risk"] == case.log_risk
    # the test cohort's case is not the real TCGA case of that row: no precomputed scores
    assert omics.case_scores(pf) is None and not sums["omics"]["cards"]
    assert sums["genomics"]["cards"][0]["text"] == "PIK3CA H1047R · CIViC not loaded here"
    assert genomics.queue(pf, 0) == []  # unknown evidence is not a finding to triage
    found = genomics.queue(pf, 0, lookup=lambda gene, change: [
        {"evidence_level": "C", "therapies": "Alpelisib", "significance": "Sensitivity/Response"}])
    assert [(x["pointer"], x["consequence"], x["trust"]) for x in found] == [
        ("PIK3CA H1047R", 1, "moderate")]
    head = overview.header(pf, 0, sums, overview.attention(pf, 0, overview.queues(pf, 0), []))
    assert [c["what"] for c in head] == ["Stage and receptors", "Key drivers", "Cohort risk",
                                         "What to watch next", "SOS"]
    assert head[-1]["text"] == "nothing alarming in this version or before"


def test_slide_summary_and_queue_read_the_scored_sections():
    pf = tcga(299, slides=["TCGA-AN-A0AS-DX1"], docs=[])
    card = slides.summary(pf)["cards"][0]
    for part in ("main tumor 9.61 mm²", "6 of 12 front arcs infiltrative", "41 breakaway",
                 "immune pattern: desert"):
        assert part in card["text"]
    assert card["trust"] == "weak" and "placeholder" in card["threshold"]
    q = slides.queue(pf)
    assert [x["pointer"] for x in q] == [f"T{n}" for n in range(1, 10)]
    assert q[0]["focus"] == {"slide": "TCGA-AN-A0AS-DX1", "pointer": "T1", "tile": "r25c83"}
    assert q[0]["key"] == finding_key(pf, "slide", "TCGA-AN-A0AS-DX1", "r25c83")
    several = tcga(1043, slides=["TCGA-PL-A8LZ-DX1", "TCGA-PL-A8LZ-DX2", "TCGA-PL-A8LZ-DX3"])
    text = slides.summary(several)["cards"][0]["text"]
    assert "section TCGA-PL-A8LZ-DX3, the largest tumor of 3 sections" in text
    assert all(x["what"].endswith(x["focus"]["slide"]) for x in slides.queue(several))


def test_omics_summary_and_queue_use_the_precomputed_scores_of_this_build():
    pf = tcga(864)
    sums = omics.summary(pf)
    sub = {c["what"]: c for c in sums["cards"]}
    assert sub["PAM50 subtype"]["text"].startswith("Basal-like, margin 0.09 over")
    assert sub["PAM50 subtype"]["trust"] == "weak"  # under the placeholder margin
    assert sub["Recorded receptors"]["text"].startswith("ER negative, PR positive, HER2 positive")
    q = {x["pointer"]: x for x in omics.queue(pf)}
    assert q["ER: IHC vs RNA"]["consequence"] == 2 and q["PR: IHC vs RNA"]["consequence"] == 1
    assert q["HER2: IHC vs copy number"]["trust"] == "weak"  # 2x ploidy is a placeholder
    assert "borderline" in q["PAM50"]["what"]
    assert omics.case_scores(tcga(864, log_risk=0.123)) is None  # another build of the cohort


# -------------------------------------------------------------------- discrepancy rules

@pytest.fixture
def scores(monkeypatch):
    """Hand-made precomputed scores for "Case 7": receptors, a PAM50 call, an immune score."""
    def make(receptors, call="LumA", margin=0.3, immune=50.0):
        data = {"version": "test", "validation": {"pam50": {}, "receptors": {
            r: {"rna": {"cutoff_pct": 30.0, "auc": 0.95}, "protein": {"cutoff_pct": 30.0,
                                                                       "auc": 0.9}}
            for r in ("ER", "PR", "HER2")}},
            "cases": {"7": {"log_risk": 0.5, "receptors": receptors, "scores": {
                "proliferation": [0.0, 50.0], "immune": [1.0, immune]}, "pam50": {
                "call": call, "margin": margin, "cor": {call: 0.6, "LumB": 0.6 - margin},
                "published": None, "agrees": None, "genes": 50}}}}
        monkeypatch.setattr(omics, "scores", lambda path=None: data)
    return make


def case7(observed=(("Stage", "II"),), tests=(), versions=()) -> PatientFile:
    rna = WorkspaceTest("Data layer", None, "RNA-seq (STAR TPM)", "measured", "omics",
                        "implemented", {"layer": "rna"})
    v = Version(None, "Baseline", "sample", [list(p) for p in observed],
                {"percentile": 50.0, "group": "medium", "log_risk": 0.5}, "", [], [],
                [rna, *tests])
    return PatientFile("Case 7", "TCGA-BRCA", "hand-made", "Breast cancer", [v, *versions], "",
                       {"name": "m", "endpoint": "e", "status": "s"})


def doc(text: str, n: int = 1):
    test, _ = document_test("Document", f"Report {n}", text, None, f"d{n}", "hand-made")
    return test


def by_rule(pf: PatientFile, i: int = 0) -> dict:
    out = {}
    for d in crosstest.discrepancies(pf, i):
        assert {"what", "sources", "why", "would_settle", "evidence", "basis", "trust",
                "consequence", "opens", "key"} <= set(d)
        assert len(d["sources"]) == 2 and d["trust"] in TRUST
        out.setdefault(d["rule"], []).append(d)
    return out


def test_erbb2_copy_number_against_recorded_and_documented_her2(scores):
    scores({"HER2": {"status": "Negative", "ihc": "Negative", "cn": {"copies": 9.0,
                                                                       "ploidy": 3.0}}})
    rules = by_rule(case7(tests=[doc("HER2: negative (IHC 1+).")]))
    items = rules["ERBB2 copy number vs HER2"]
    assert {d["what"] for d in items} == {
        "ERBB2 copy number amplified, HER2 recorded negative (TCGA clinical data)",
        "ERBB2 copy number amplified, HER2 status negative (documented in Report 1)"}
    recorded = next(d for d in items if "recorded" in d["what"])
    assert recorded["key"] == "Case 7|omics|receptor|HER2: IHC vs copy number"  # the omics item
    assert recorded["consequence"] == 3 and recorded["trust"] == "weak"
    assert "in situ hybridization" in recorded["would_settle"].lower()
    assert "Wolff" in recorded["basis"]
    reducers = crosstest.uncertainty_reducers(case7(tests=[doc("HER2: negative.")]), 0)
    assert any(r["test"] == "HER2 in situ hybridization with the IHC" for r in reducers)


def test_esr1_rna_and_protein_against_recorded_and_documented_er(scores):
    scores({"ER": {"status": "Negative", "ihc": "Negative", "rna": {"pct": 90.0, "high": True},
                   "protein": {"pct": 85.0, "high": True}}})
    pf = case7(tests=[doc("Estrogen receptor (ER): positive, 95%.")])
    rules = by_rule(pf)
    er = rules["ER RNA and protein vs ER status"]
    assert [d["what"] for d in er] == [
        "ER recorded negative (TCGA clinical data); ESR1 RNA high, ER-alpha protein high"]
    assert er[0]["key"] == "Case 7|omics|receptor|ER: IHC vs RNA" and "Allison" in er[0]["basis"]
    assert "ER low positive" in er[0]["would_settle"]
    mixed = rules["documented vs recorded receptor"][0]
    assert mixed["what"] == "ER: ER status positive (documented in Report 1), recorded negative"
    assert mixed["focus"]["doc"] == "d1" and mixed["consequence"] == 3
    assert any(r["test"] == "Repeat ER immunohistochemistry with controls"
               for r in crosstest.uncertainty_reducers(pf, 0))


def test_pam50_basal_like_with_an_er_positive_status(scores):
    scores({"ER": {"status": "Positive", "ihc": "Positive", "rna": {"pct": 60.0, "high": True}}},
           call="Basal", margin=0.05)
    item = by_rule(case7())["PAM50 basal-like vs ER-positive"][0]
    assert item["trust"] == "weak" and "Prat" in item["basis"]  # a borderline call
    assert item["evidence"] == f"{INFERENCE} (PAM50 call), {OBSERVED} (ER status)"


def test_an_immune_desert_section_against_a_high_immune_rna_score(scores, monkeypatch):
    scores({}, immune=92.0)
    section = {"slide": "S1", "opens": ("Tests", "Pathology slide", None, "H&E"), "meta": {
        "numbers": {"immune_pattern": "desert", "unsure_share": 0.31},
        "head": {"accuracy_below_cutoff": 0.6, "accuracy_at_or_above_cutoff": 0.93,
                 "held_out": "3 slides"}}}
    monkeypatch.setattr(slides, "sections", lambda pf, version=None: [section])
    item = by_rule(case7())["slide immune vs RNA immune"][0]
    assert item["what"] == "Immune desert on section S1, high immune score in the RNA"
    assert "Salgado" in item["basis"] and item["opens"] == section["opens"]
    reducer = next(r for r in crosstest.uncertainty_reducers(case7(), 0)
                   if "second encoder" in r["test"])
    assert "60%" in reducer["source"] and "93%" in reducer["source"]
    scores({}, immune=40.0)
    assert "slide immune vs RNA immune" not in by_rule(case7())


def test_documents_that_disagree_and_documents_against_the_record(scores):
    scores({})
    pf = case7(observed=(("Stage", "II"), ("Laterality", "left")),
               tests=[doc("Left breast, mastectomy. ER: positive. Stage IIIA.", 1),
                      doc("Right breast biopsy. ER: negative.", 2)])
    rules = by_rule(pf)
    conflict = rules["documents disagree"][0]
    assert conflict["what"] == "ER status: the documents disagree"
    assert conflict["key"] == finding_key(pf, "document", "conflict", "ER status")
    assert conflict["consequence"] == 2 and "precision" in conflict["basis"]
    record = {d["what"] for d in rules["documented vs recorded"]}
    assert "Stage: documented Stage IIIA, recorded II" in record
    assert "Laterality: documented right, recorded left" in record
    assert any(r["test"].startswith("A re-read") for r in crosstest.uncertainty_reducers(pf, 0))


def test_an_imported_lab_value_against_the_recorded_value_of_that_month():
    pf = synthetic()
    tests, _ = lab_tests([{"month": 24, "key": "ca153", "marker": "CA 15-3", "value": 40.0,
                           "unit": "U/mL", "limit": None}])
    pf = add_version(pf, tests, 24, "Imported lab results", "AB", "12:00")
    item = by_rule(pf, len(pf.versions) - 1)["imported vs recorded lab"][0]
    assert item["what"] == "CA 15-3 at month 24: imported 40 U/mL, recorded 31 U/mL"
    assert item["trust"] == "strong" and item["focus"] == {"marker": "ca153", "month": 24}
    assert not by_rule(synthetic(), 15).get("imported vs recorded lab")


# ------------------------------------------------------------------ the attention queue

def test_one_queue_merges_alerts_discrepancies_and_workbench_items():
    pf = synthetic()
    dis = crosstest.discrepancies(pf, 11)
    q = overview.attention(pf, 11, overview.queues(pf, 11), dis)
    assert [x["n"] for x in q] == list(range(1, len(q) + 1)) and len(q) == 11
    assert [x["kind"] for x in q].count("evolution") == 3  # rows the record raises, weak trust
    assert all(a["priority"] >= b["priority"] for a, b in zip(q, q[1:], strict=False))
    assert q[0]["what"].startswith("Progression on imaging") and q[0]["new"]
    rise = next(x for x in q if x["what"].startswith("CA 15-3 rose"))
    # the alert and the lab workbench's flag of that value are one finding, under one key
    assert rise["pointer"] == "L4" and rise["key"] == finding_key(pf, "lab", "ca153", 11)
    assert rise["also"] == ["the labs workbench (L4)"] and rise["sos"]
    assert rise["focus"] == {"marker": "ca153", "month": 11}
    assert len({x["key"] for x in q}) == len(q)
    weak = overview.unsure(q, {})
    assert {x["trust"] for x in weak} == {"weak"}
    marked = {q[0]["key"]: {"mark": "second look"}}
    assert overview.unsure(q, marked)[0] is q[0]
    # month 11: the rise against stable imaging is a discrepancy of its own, kept apart
    q11 = overview.attention(pf, 10, overview.queues(pf, 10), crosstest.discrepancies(pf, 10))
    kinds = [x["kind"] for x in q11]
    assert "discrepancy" in kinds and kinds.count("SOS") == 4


def test_the_header_cards_and_open_sos_alerts():
    pf = synthetic()
    sums = overview.summaries(pf, 11)
    q = overview.attention(pf, 11, overview.queues(pf, 11), crosstest.discrepancies(pf, 11))
    head = overview.header(pf, 11, sums, q, {})
    assert [c["what"] for c in head] == ["Stage and receptors", "Key drivers", "Imaging",
                                         "12-month risk", "What to watch next", "SOS"]
    assert head[4]["evidence"] == HYPOTHESIS and head[4]["opens"] == ("Evolution",)
    stage = head[0]
    assert [k for k, *_ in stage["sides"]] == ["Recorded", "Documented"]
    assert head[2]["text"] == "month 12: Imaging: new liver lesions, read as progression"
    assert head[3]["evidence"] == INFERENCE and head[-1]["open"] == 7
    reviewed = {x["key"]: {"mark": "reviewed"} for x in q if x["sos"]}
    assert overview.header(pf, 11, sums, q, reviewed)[-1]["open"] == 0
    assert overview.absent(sums) == [
        "Slides: no scored section of this tumor: the slide workbench shows a public example "
        "region", "Expression: no expression, methylation or protein scores in this file"]


def test_imports_reach_the_timeline_diff_queue_and_export():
    pf = synthetic()
    ok, _ = parse_labs(b"month,marker,value,unit\n27,CA 15-3,45,U/mL\n", after=24)
    tests, observed = lab_tests(ok)
    pf = add_version(pf, tests, 27, "Imported lab results", "AB", "14:03", observed)
    i = len(pf.versions) - 1
    diff = crosstest.diff_versions(pf, i - 1, i)
    assert any(d["finding"] == "Lab: CA 15-3 (month 27)" and d["status"] == "added"
               for d in diff)
    q = overview.attention(pf, i, overview.queues(pf, i), crosstest.discrepancies(pf, i))
    rise = next(x for x in q if x["what"].startswith("CA 15-3 rose from 31 to 45"))
    assert rise["new"] and rise["pointer"] == "L8" and rise["opens"] == ("Tests", "Lab", 27,
                                                                         "CA 15-3")
    page = report_markdown(pf, i, reviews={}, summaries=overview.summaries(pf, i), queue=q)
    assert "Imported in this session" in page and "CA 15-3 rose from 31 to 45" in page
    # a TCGA file: its first lab values arrive by import and reach the lab cards
    t = tcga(299, docs=[])
    ok, _ = parse_labs(b"month,marker,value,unit\n0,CA 15-3,20,U/mL\n", after=None)
    t = add_version(t, lab_tests(ok)[0], 0, "Imported lab results", "AB", "14:05")
    assert labs.summary(t, 1)["cards"][0]["text"] == "CA 15-3 20 U/mL at month 0: within limit"
    assert labs.summary(t, 0)["note"] == "no lab results in this file"


def test_the_export_carries_cards_queue_discrepancies_placeholders_and_marks_by_kind():
    pf = synthetic()
    sums = overview.summaries(pf, 11)
    dis = crosstest.discrepancies(pf, 10)
    q = overview.attention(pf, 11, overview.queues(pf, 11), crosstest.discrepancies(pf, 11))
    reviews = {finding_key(pf, "lab", "ca153", 11): {"what": "L4", "mark": "agree", "by": "AB",
                                                     "at": "2026-10-21 09:00"},
               finding_key(pf, "alert", 12, "x"): {"what": "an alert", "mark": "reviewed",
                                                   "by": "", "at": "2026-10-21 09:01"}}
    page = report_markdown(pf, 11, reviews=reviews, disagree=dis, summaries=sums, queue=q)
    for part in ("## Findings by workbench", "### Blood and lab", "**Latest CA 15-3**",
                 "### Pathology slide", "- no scored section of this tumor",
                 "## Attention queue (ordered by consequence × trust", "1. [SOS alert]",
                 "[SOS alert] L4 · CA 15-3 rose", "Also raised by the labs workbench (L4).",
                 "Review: agree.", "Sources: CA 15-3, month 11 vs Imaging, month 7.",
                 "Attention queue: ordered by consequence × trust",
                 "12-month risk up +51 points (37% → 88%): placeholder",
                 "### alert\n- an alert: reviewed",
                 "### lab\n- L4: agree (AB, 2026-10-21 09:00)"):
        assert part in page, part


# --------------------------------------------------------------------- the patient list

def test_list_rows_search_and_filters():
    syn = synthetic()
    case = tcga(299, stage="II", slides=["TCGA-AN-A0AS-DX1"], mutations=["PIK3CA p.E545K"])
    other = tcga(864, stage="III", docs=[], mutations=[])
    rows = [{**overview.list_row(pf), "diagnosis": pf.diagnosis} for pf in (syn, case, other)]
    by = {r["id"]: r for r in rows}
    assert by["Case 299"]["subtype"] == "Luminal A" and by["Case 864"]["subtype"] == "Basal-like"
    assert by["SYNTHETIC-001"]["subtype"] == "not called" and by["SYNTHETIC-001"]["stage"] == "II"
    assert by["Case 299"]["holds"] == ["Genomics", "Slides", "Expression", "Documents"]
    assert by["SYNTHETIC-001"]["holds"] == ["Labs", "Genomics", "Documents", "Imaging"]

    def ids(**kw):
        return [r["id"] for r in overview.filter_rows(rows, **kw)]

    assert ids(query="pik3ca") == ["SYNTHETIC-001", "Case 299"]
    assert ids(query="basal") == ["Case 864"] and ids(query="luminal slides") == ["Case 299"]
    assert ids(subtypes=["Luminal A"]) == ["Case 299"] and ids(stages=["III"]) == ["Case 864"]
    assert ids(genes=["PIK3CA"]) == ["SYNTHETIC-001", "Case 299"]
    assert ids(holds=["Imaging"]) == ["SYNTHETIC-001"]
    assert ids(holds=["Slides", "Documents"]) == ["Case 299"]
    assert ids(open_sos=True) == ["SYNTHETIC-001"]
    seen = {k: {"mark": "reviewed"} for k in by["SYNTHETIC-001"]["alerts"]}
    assert ids(open_sos=True, reviews=seen) == []

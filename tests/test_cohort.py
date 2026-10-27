"""Across the patient files (muffle.cohort, docs/cohort.md): the index of every file's findings,
the search and its operators, the similarity lookup on hand-made profiles, the cohort position's
percentiles, and both on the app's Patients page and report (AppTest)."""

from urllib.parse import urlencode

import pytest

from muffle import cohort
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from tests.appfixture import shown
from tests.test_overview import synthetic, tcga


def entry(pid: str, what: str, text: str, label: str = OBSERVED) -> dict:
    return {"patient": pid, "what": what, "text": text, "label": label}


# --------------------------------------------------------------------------------------- index

def test_the_index_holds_every_kind_of_finding_with_its_label_and_link():
    case = tcga(299, stage="Stage IIIA", slides=["TCGA-AN-A0AS-DX1"],
                mutations=["MAP3K1 p.S588Ffs*3", "TP53 p.R110del"])
    index = cohort.build_index({"SYNTHETIC-001": synthetic(), case.id: case})
    kinds = {(e["patient"], e["kind"]) for e in index}
    for kind in ("profile", "finding card", "attention item", "variant", "documented fact",
                 "hypothesis"):
        assert (case.id, kind) in kinds, kind
    assert ("SYNTHETIC-001", "SOS alert") in kinds  # the alerts, through the one queue
    assert all(e["label"] in (OBSERVED, INFERENCE, HYPOTHESIS) for e in index)
    assert all(e["link"].startswith("?patient=") for e in index)
    slide = next(e for e in index if e["patient"] == case.id and e["what"] == "Slide picture")
    assert slide["label"] == INFERENCE and slide["opens"][:2] == ("Tests", "Pathology slide")
    assert "view=Tests" in slide["link"] and "test=Pathology+slide%7C%7C" in slide["link"]
    queue = next(e for e in index if e["patient"] == case.id and e["kind"] == "attention item"
                 and e["pointer"])
    assert urlencode({"pointer": queue["pointer"]}) in queue["link"]
    profile = next(e for e in index if e["patient"] == case.id and e["kind"] == "profile")
    assert "stage III" in profile["text"] and "PAM50 Luminal A" in profile["text"]
    assert "MAP3K1, TP53" in profile["text"] and profile["opens"] == ()
    # the synthetic patient's 12-month risk (MSK-CHORD models) is a card, never a profile field
    synthetic_profile = next(e for e in index if e["patient"] == "SYNTHETIC-001"
                             and e["kind"] == "profile")
    assert "risk group" not in synthetic_profile["text"]
    # the search finds each kind: a variant, a slide number, a fact, a hypothesis
    fact = next(e for e in index if e["patient"] == case.id and e["kind"] == "documented fact")
    for query, pid in (("MAP3K1", case.id), ("breakaway", case.id), ("level A", "SYNTHETIC-001"),
                       ("stage III MAP3K1", case.id), (f'"{fact["what"]}"', case.id)):
        assert pid in [p["patient"] for p in cohort.search(index, query)["patients"]], query


# -------------------------------------------------------------------------------------- search

def test_terms_read_phrases_qualifiers_and_status_words():
    assert cohort.terms("level A") == ["level a"]
    assert cohort.terms("stage III PIK3CA") == ["stage iii", "pik3ca"]
    assert cohort.terms("ER positive HER2 negative") == ["er positive", "her2 negative"]
    assert cohort.terms("ESR1 methylated") == ["esr1 methylated"]
    assert cohort.terms("HER2 disagree") == ["her2", "disagree"]
    assert cohort.terms('"tumor size" grade 3') == ["tumor size", "grade 3"]
    assert cohort.terms("  ") == []


@pytest.mark.parametrize("term, text, found", [
    ("basal", "PAM50 Basal-like, margin 0.30", True),
    ("methylated", "BRCA1 unmethylated (promoter)", False),
    ("esr1 methylated", "ESR1 methylated with low RNA", True),
    ("esr1 methylated", "none of ESR1, PGR, BRCA1 methylated", False),
    ("stage i", "stage II · ER positive", False),
    ("stage iii", "stage III · ER positive", True),
    ("level a", "PIK3CA H1047R (CIViC level A)", True),
    ("level a", "CIViC level AB", False),
    ("er positive", "ER negative, PR positive", False),
    ("er", "HER2 negative", False),
    ("washout", "C2 (MRI): washout curve (type III)", True),
])
def test_a_term_matches_at_a_word_start_and_a_short_last_word_whole(term, text, found):
    assert bool(cohort._pattern(term).search(text)) is found


def test_search_ranks_files_by_matching_findings_then_closeness_then_evidence():
    index = [
        entry("A", "Receptors", "HER2 IHC positive, ERBB2 RNA low; disagree", INFERENCE),
        entry("B", "HER2, IHC vs RNA: disagree", "HER2, IHC vs RNA: disagree: low RNA"),
        entry("B", "Receptors", "disagree: HER2 IHC positive, ERBB2 RNA low"),
        entry("C", "Documents", "the model's reading: 1 disagree"),  # no HER2: not listed
        entry("D", "Hypothesis", "HER2 status change; disagree in 20%", HYPOTHESIS),
        entry("E", "Recorded receptors", "HER2 disagree-ish", INFERENCE),
    ]
    found = cohort.search(index, "HER2 disagree")
    assert found["terms"] == ["her2", "disagree"] and not found["across"]
    order = [p["patient"] for p in found["patients"]]
    assert order[0] == "B" and "C" not in order  # two matching findings first
    assert order.index("E") < order.index("A")  # then the words closer together
    assert found["patients"][0]["findings"][0]["text"].startswith("disagree: HER2")  # closest
    # the evidence filter keeps only the findings of the labels asked for
    assert [p["patient"] for p in cohort.search(index, "HER2 disagree", [HYPOTHESIS])[
        "patients"]] == ["D"]
    # ties on matches and closeness: observed before model inference before hypothesis
    tie = [entry("H", "x", "basal", HYPOTHESIS), entry("I", "x", "basal", INFERENCE),
           entry("O", "x", "basal", OBSERVED)]
    assert [p["patient"] for p in cohort.search(tie, "basal")["patients"]] == ["O", "I", "H"]


def test_search_across_findings_only_when_no_finding_holds_every_word():
    index = [entry("A", "Slide picture", "immune pattern desert"),
             entry("A", "Key drivers", "TP53 R110del"),
             entry("B", "Key drivers", "TP53 R175H")]
    found = cohort.search(index, "TP53 desert")
    assert found["across"] and [p["patient"] for p in found["patients"]] == ["A"]
    assert len(found["patients"][0]["findings"]) == 2
    assert cohort.search(index, "lobular")["patients"] == []
    assert cohort.search(index, "")["patients"] == []


# ---------------------------------------------------------------------------------- similarity

def profile(pid, kind="TCGA-BRCA", **fields) -> dict:
    base = {"id": pid, "kind": kind, "pam50": "Luminal A", "stage": "II",
            "receptors": {"ER": "positive", "PR": "positive", "HER2": "negative"},
            "drivers": ["PIK3CA"], "cn": [], "risk_band": "low", "immune": "middle",
            "tests": ["Genomics", "Expression"], "scores": {}}
    return {**base, **fields}


def test_similar_patients_share_and_differ_field_by_field():
    me = profile("Case 1")
    others = {p["id"]: p for p in [
        me, profile("Case 2"),  # the same on every field
        profile("Case 3", pam50="Basal-like", drivers=["PIK3CA", "TP53"]),
        profile("Case 4", stage=None, cn=None),  # unknown, so not shared
        profile("SYNTHETIC-001", "synthetic"),  # never a candidate
    ]}
    sim = cohort.similar_patients(me, others, k=5)
    assert sim["method"] == cohort.LOOKUP and sim["candidates"] == 3
    near = {r["patient"]: r for r in sim["nearest"]}
    assert list(near) == ["Case 2", "Case 3", "Case 4"] and near["Case 2"]["score"] == 1
    three = near["Case 3"]
    assert three["score"] == pytest.approx((6 + 0 + 0.5) / 8)  # PAM50 differs, drivers 1 of 2
    assert {x["field"]: (x["this"], x["other"]) for x in three["differ"]} == {
        "PAM50 subtype": ("Luminal A", "Basal-like"),
        "mutated driver genes": ("PIK3CA", "PIK3CA, TP53")}
    assert near["Case 4"]["missing"] == ["stage", "copy-number calls"]
    assert near["Case 4"]["score"] == pytest.approx(6 / 8)
    assert cohort.similar_patients(me, others, k=1)["nearest"][0]["patient"] == "Case 2"


def test_a_record_stating_only_the_hormone_receptors_compares_as_hr():
    me = profile("SYNTHETIC-001", "synthetic", pam50=None, cn=None, risk_band=None, immune=None,
                 receptors={"HR": "positive", "HER2": "negative"})
    er_only = profile("Case 2", receptors={"ER": "positive", "PR": "negative", "HER2": "negative"})
    negative = profile("Case 3", receptors={"ER": "negative", "PR": "negative",
                                            "HER2": "negative"})
    near = {r["patient"]: r for r in cohort.similar_patients(
        me, {p["id"]: p for p in (me, er_only, negative)})["nearest"]}
    assert "receptor status" in [x["field"] for x in near["Case 2"]["shared"]]  # ER+ is HR+
    rec = next(x for x in near["Case 3"]["differ"] if x["field"] == "receptor status")
    assert rec["agree"] == 0.5  # HR differs, HER2 agrees
    assert set(near["Case 2"]["missing"]) == {"PAM50 subtype", "copy-number calls",
                                              "risk group", "RNA immune band"}


def test_profiles_of_real_files():
    p = cohort.profile(tcga(299, stage="Stage IIIA", mutations=["TP53 p.R110del"]))
    assert p["pam50"] == "Luminal A" and p["stage"] == "III" and p["drivers"] == ["TP53"]
    assert p["receptors"] == {"ER": "positive", "PR": "negative", "HER2": "negative"}
    assert "MYC amplification" in p["cn"] and p["risk_band"] == "medium"
    assert {"risk", "burden", "proliferation", "immune", "pi3k"} <= set(p["scores"])
    s = cohort.profile(synthetic())
    assert s["receptors"] == {"HR": "positive", "HER2": "negative"} and s["stage"] == "II"
    assert s["risk_band"] is None and s["scores"] == {}  # no MSK-CHORD output is compared
    assert cohort.profile(tcga(299, mutations=None))["drivers"] is None  # not sequenced


# ---------------------------------------------------------------------------- cohort position

def test_cohort_position_is_a_percentile_among_the_tcga_files():
    files = {f"Case {n}": profile(f"Case {n}", scores={"risk": float(n), "burden": 2.0})
             for n in range(1, 6)}
    files["Case 6"] = profile("Case 6", scores={"risk": 3.0})  # a tie, and no burden
    files["SYNTHETIC-001"] = profile("SYNTHETIC-001", "synthetic", scores={"risk": 99.0})
    pos = cohort.cohort_position(files["Case 3"], files)
    assert pos["method"] == cohort.POSITION and pos["cohort"] == 6
    assert pos["excluded"] == ["SYNTHETIC-001"] and pos["in_cohort"]
    risk = next(m for m in pos["metrics"] if m["key"] == "risk")
    assert risk["percentile"] == pytest.approx(100 * (2 + 0.5) / 5)  # 1, 2 below; 3 tied
    assert risk["n"] == 6 and "SYNTHETIC-001" not in risk["values"]
    burden = next(m for m in pos["metrics"] if m["key"] == "burden")
    assert burden["percentile"] == 50 and burden["n"] == 5  # every other file ties
    assert [m["key"] for m in cohort.cohort_position(files["Case 6"], files)["metrics"]] == [
        "risk"]  # only the scores the file has
    synthetic_pos = cohort.cohort_position(files["SYNTHETIC-001"], files)
    assert not synthetic_pos["in_cohort"] and synthetic_pos["metrics"] == []


# ------------------------------------------------------------------------------------- the app

@pytest.mark.filterwarnings("error")
def test_search_every_file_and_the_report_sections_in_the_app(app):
    at = app.new().run()
    assert not at.exception and "Searches the findings of all files" in shown(at)
    at.text_input(key="cohort-search").set_value("pik3ca").run()
    assert not at.exception
    rows = [m.value for m in at.markdown if m.value.startswith("**SYNTHETIC-001**")
            or m.value.startswith(f"**{app.case}**")]
    assert {r.split("**")[1] for r in rows} == {"SYNTHETIC-001", app.case}
    assert "(synthetic)" in next(r for r in rows if "SYNTHETIC" in r)
    assert "ranked by matching findings" in shown(at)
    first = rows[0].split("**")[1]
    at.button(key="cohort-open-0").click().run()  # lands in the file, on the finding
    assert not at.exception and at.selectbox(key="patient").value == first
    at.selectbox(key="patient").set_value(None).run()
    at.text_input(key="cohort-search").set_value("nothing-matches-this").run()
    assert "No finding in any file matches" in shown(at)

    at.selectbox(key="patient").select(app.case).run()
    at.segmented_control(key="view").set_value("Report").run()
    text = shown(at)
    assert not at.exception
    assert "**Where this patient sits** among the 4 TCGA files" in text
    assert "**Risk** ·" in text and "Percentiles, not a prognosis" in text
    assert "**Similar patients** · the 3 nearest of 3 TCGA files" in text
    assert cohort.LOOKUP in text and "the synthetic patient is never one" in text
    at.button(key=f"similar-{app.case}-0").click().run()  # opens that file's report
    assert not at.exception and at.selectbox(key="patient").value != app.case

    at.selectbox(key="patient").select("SYNTHETIC-001").run()
    at.segmented_control(key="view").set_value("Report").run()
    assert "is a synthetic patient, written by hand, and is not in this cohort" in shown(at)
    assert not at.exception

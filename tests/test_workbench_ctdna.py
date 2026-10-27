"""ctDNA monitor: rules over SYNTHETIC-001's synthetic series and over small hand-made series."""

from pathlib import Path

from muffle.timeline import CTDNA, EVENTS
from muffle.workbench import ctdna as wb
from muffle.workbench import labs
from muffle.workspace import CTDNA_KIND, FINDING_KINDS, finding_key, synthetic_file
from tests.test_workspace import timeline

ROOT = Path(__file__).resolve().parents[1]


def calls(rows, variant):
    return [(r["month"], r["call"]) for r in rows if r["variant"] == variant]


def test_the_synthetic_series_tells_its_three_stories():
    rows = wb.series_rows(CTDNA, EVENTS)
    assert len(rows) == 36 and all(r["synthetic"] and r["evidence"] == "observed" for r in rows)
    # PIK3CA H1047R tracks burden: up before both progressions (months -1 and 12), down under
    # treatment
    pik = dict(calls(rows, "PIK3CA H1047R"))
    assert [pik[m] for m in (-6, -2, 4, 7, 9, 11, 16, 19)] == [
        wb.RISING, wb.RISING, wb.FALLING, wb.FALLING, wb.RISING, wb.RISING, wb.FALLING,
        wb.FALLING]
    # ESR1 D538G emerges under letrozole and rises before the liver progression
    esr1 = dict(calls(rows, "ESR1 D538G"))
    assert (esr1[-12], esr1[-2], esr1[9], esr1[11]) == (
        wb.NOT_DETECTED, wb.NEW, wb.RISING, wb.RISING)
    new = next(r for r in rows if r["variant"] == "ESR1 D538G" and r["month"] == -2)
    assert new["therapy"] == ["letrozole"] and new["pointer"] == "C2"
    # one sample below the limit is not "cleared"
    last = next(r for r in rows if r["variant"] == "ESR1 D538G" and r["month"] == 24)
    assert last["call"] == wb.NOT_DETECTED and "1 of 2 consecutive samples" in last["rule"]
    # DNMT3A R882H: flat whatever the treatment
    assert {c for _, c in calls(rows, "DNMT3A R882H")} == {wb.DETECTED, wb.STABLE}


def test_origin_flags_possible_clonal_hematopoiesis_and_keeps_esr1():
    rows = wb.series_rows(CTDNA, EVENTS)
    vs = {v["variant"]: v for v in wb.variants(rows, EVENTS)}
    assert (vs["PIK3CA H1047R"]["origin"], vs["PIK3CA H1047R"]["in_picture"]) == (
        wb.TUMOR_MATCHED, True)
    # ESR1 is on the tumor panel and the month-0 biopsy did not find it, but ESR1 is not a
    # clonal-hematopoiesis gene: kept in the tumor picture, origin unconfirmed
    assert (vs["ESR1 D538G"]["origin"], vs["ESR1 D538G"]["in_picture"]) == (wb.NOT_IN_TUMOR, True)
    assert "on the tumor panel and was not found (month 0)" in vs["ESR1 D538G"]["why"]
    dnmt = vs["DNMT3A R882H"]
    assert (dnmt["origin"], dnmt["in_picture"], dnmt["flat"]) == (wb.POSSIBLE_CH, False, True)
    assert "not on the tumor panel" in dnmt["why"] and "Jaiswal" in wb.origin(
        "DNMT3A R882H", wb.tumor_sequencing(EVENTS))["source"]
    assert dnmt["detected"] == "0.4-0.48% in 12 of 12 samples"
    # a TP53 variant missing from the tissue is not flagged by gene: only the caveat (Razavi)
    assert wb.origin("TP53 R175H", wb.tumor_sequencing(EVENTS))["origin"] == wb.NOT_IN_TUMOR


def test_the_esr1_rule_is_evidence_for_review_with_the_trials_differences():
    rows = wb.series_rows(CTDNA, EVENTS)
    rule = wb.esr1_rule(rows, EVENTS)
    assert [(i["month"], i["applies"]) for i in rule] == [(-2, True), (9, False), (11, False)]
    first = dict((a, r) for a, _, r in rule[0]["compare"])
    assert first["Setting"] == "this record: Adjuvant endocrine therapy: letrozole"
    assert first["Progression"] == ("no progression on imaging recorded at or before this sample "
                                    "(the next, at month -1)")
    assert first["Adjuvant or metastatic"] == "this record's letrozole is adjuvant"
    assert first["What the record shows next"].startswith("month 1: ")
    assert rule[0]["use"] == "evidence for clinician review, never a recommendation to switch"
    assert any("doi:10.1016/S1470-2045(22)00555-1" in s for s in rule[0]["sources"])
    assert any("doi:10.1126/scitranslmed.aac7551" in s for s in rule[0]["sources"])
    assert "does not apply" in rule[1]["what"] and "palbociclib + fulvestrant" in rule[1]["what"]
    for i in rule:
        text = i["what"] + " ".join(r for _, _, r in i["compare"])
        assert "recommend" not in text and "should" not in text


def test_lead_and_lag_against_imaging_and_ca153_are_facts_of_the_record():
    rows = wb.series_rows(CTDNA, EVENTS)
    lag = {(x["variant"], x["month"]): x for x in wb.lead_lag(rows, EVENTS,
                                                               labs.results_table(EVENTS))}
    x = lag[("ESR1 D538G", 9)]
    assert x["what"] == ("ESR1 D538G rising at month 9 came 3 months before the progression on "
                         "imaging at month 12 and 2 months before CA 15-3 above limit, rising at "
                         "month 11 (L4)")
    assert (x["imaging_month"], x["ca153_month"]) == (12, 11)
    assert lag[("PIK3CA H1047R", -6)]["imaging_month"] == -1
    assert all("not a validated lead time" in v["caveat"] for v in lag.values())


def hand_made(*values, variant="PIK3CA H1047R", lod=0.1):
    return {"detection_limit": lod, "variants": (variant,), "samples": [
        {"month": m, "vaf": {variant: v}} for m, v in enumerate(values)]}


def test_calls_new_rising_falling_cleared_and_low_shedding_on_a_hand_made_series():
    rows = wb.series_rows(hand_made(0.5, 1.2, 0.5, None, 0.05, 0.3), EVENTS)
    assert [r["call"] for r in rows] == [wb.DETECTED, wb.RISING, wb.FALLING, wb.NOT_DETECTED,
                                         wb.CLEARED, wb.NEW]
    assert rows[4]["rule"].startswith("below the detection limit at 2 consecutive samples")
    assert rows[5]["rule"] == "detected after 2 sample(s) below the limit"
    assert [r["pointer"] for r in rows] == ["", "C1", "C2", "", "C3", "C4"]
    assert not any(r["synthetic"] for r in rows)  # a series not marked synthetic is not
    shed = wb.low_shedding(rows)
    assert [s["month"] for s in shed] == [3, 4] and "low shedding" in shed[0]["what"]
    assert wb.series_rows(hand_made(None, 0.2), [])[1]["call"] == wb.NEW  # no record: no therapy


def test_workspace_adds_one_ctdna_test_per_sample_in_the_right_version():
    pf = synthetic_file(timeline())
    tests = [t for t in pf.tests if t.kind == CTDNA_KIND]
    assert len(tests) == 12 and {t.workbench for t in tests} == {"ctdna"}
    assert all(t.details["synthetic"] and t.name == "ctDNA panel (synthetic series)"
               for t in tests)
    for v in pf.versions:  # each sample joins the first version at or after its month
        for t in v.tests:
            if t.kind == CTDNA_KIND:
                assert v.month >= t.month
    month9 = next(t for t in tests if t.month == 9)
    assert month9.result == "PIK3CA H1047R 0.6%, ESR1 D538G 0.4%, DNMT3A R882H 0.46%"
    month24 = next(t for t in tests if t.month == 24)
    assert "ESR1 D538G not detected (below 0.1%)" in month24.result
    assert "ctdna" in FINDING_KINDS
    assert finding_key(pf, "ctdna", "ESR1 D538G", 9) == "SYNTHETIC-001|ctdna|ESR1 D538G|9"


def test_rules_card_and_report_list_every_placeholder_and_source():
    rows = wb.series_rows(CTDNA, EVENTS)
    vs, rule = wb.variants(rows, EVENTS), wb.esr1_rule(rows, EVENTS)
    card = wb.rules_card(CTDNA)
    names = [t["name"] for t in card["thresholds"] if t["status"] == wb.PLACEHOLDER]
    assert names == ["detection limit", "rising", "falling", "cleared",
                     "flat whatever the treatment"]
    assert {t["status"] for t in card["thresholds"]} == {wb.PLACEHOLDER, wb.LITERATURE}
    md = wb.report_markdown("SYNTHETIC-001", rows, vs, rule,
                            wb.lead_lag(rows, EVENTS, labs.results_table(EVENTS)),
                            wb.low_shedding(rows), card,
                            {"SYNTHETIC-001|ctdna|ESR1 D538G|9": {
                                "what": "ESR1 D538G 0.4% at month 9: rising (C6)",
                                "mark": "agree", "by": "ab", "at": "12:00"}})
    assert md.startswith("# ctDNA monitor report: SYNTHETIC-001\n\nSynthetic series")
    assert "| C2 | -2 | ESR1 D538G | 0.18% | new |" in md
    assert "- DNMT3A R882H: possible clonal hematopoiesis" in md
    assert "## What ctDNA cannot see" in md and "- detection limit: 0.1% variant allele" in md
    assert "- ESR1 D538G 0.4% at month 9: rising (C6): agree (ab, 12:00)" in md
    assert "recommend" not in md.replace("never a recommendation", "").replace(
        "Nothing here is a recommendation", "")


def test_the_page_renders_labels_synthetic_and_stores_review_marks():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "workbenches" / "ctdna.py"),
                           default_timeout=60).run()
    assert not at.exception
    assert at.warning[0].value.startswith("Synthetic series: written by hand")
    headings = [m.value for m in at.markdown if m.value.startswith("#### ")]
    assert headings == ["#### Overview", "#### Allele fractions over time", "#### Details",
                        "#### Spot panel", "#### Model and validation card",
                        "#### What this test cannot see", "#### Export"]
    assert [e.label for e in at.expander][:6] == [
        "Calls per variant (3)", "ESR1 under an aromatase inhibitor, PADA-1 and SERENA-6 (3)",
        "Clonal hematopoiesis (1 possible)", "Against imaging and CA 15-3 (7)",
        "Every look-here item (8)", "Your review of the flagged findings (8)"]
    text = " ".join(e.value for e in [*at.markdown, *at.caption, *at.warning]).lower()
    assert not any(w in text for w in ("demo", "hackathon"))
    assert "12 plasma samples** (synthetic)" in " ".join(m.value for m in at.markdown)
    assert at.selectbox(key="SYNTHETIC-001_ctdna_spot").value.startswith("C14 · month 24")
    key = "SYNTHETIC-001|ctdna|ESR1 D538G|9"
    at.text_input(key="reviewer").set_value("ab").run()
    at.selectbox(key=f"mark_{key}").select("agree").run()
    assert at.session_state["reviews"][key]["mark"] == "agree"
    assert at.session_state["reviews"][key]["by"] == "ab"

    as_of = AppTest.from_string(f"""
import json, sys
sys.path[:0] = [{str(ROOT / "app")!r}, {str(ROOT / "src")!r}]
from workbenches.ctdna import render
from muffle.workspace import synthetic_file
tl = json.loads(open({str(ROOT / "app" / "timeline_synthetic.json")!r}, encoding="utf-8").read())
render(synthetic_file(tl), version=9)  # month 7
""", default_timeout=60).run()
    assert not as_of.exception and "6 plasma samples** (synthetic)" in " ".join(
        m.value for m in as_of.markdown)

    tcga = AppTest.from_string(f"""
import sys
sys.path[:0] = [{str(ROOT / "app")!r}, {str(ROOT / "src")!r}]
from types import SimpleNamespace
from workbenches.ctdna import render
from muffle.workspace import case_file
render(case_file(SimpleNamespace(index=1, site="site-0", percentile=50.0, group="medium",
                                 age=50.0, stage="II", layers=["clinical"], missing=[],
                                 mutations=None)))
""", default_timeout=60).run()
    assert not tcga.exception and tcga.info[0].value.startswith("No ctDNA in this file")


def test_the_page_overlays_ca153_marks_and_pins_from_the_spot_panel():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_file(str(ROOT / "app" / "workbenches" / "ctdna.py"),
                           default_timeout=60).run()
    assert not at.exception
    assert any(m.value.startswith(":material/lightbulb: **How to use") for m in at.markdown)
    charts = len(at.get("vega_lite_chart"))
    at.toggle(key="SYNTHETIC-001_ctdna_overlay").set_value(True).run()
    assert not at.exception and len(at.get("vega_lite_chart")) == charts - 1  # on one chart
    assert {b.label for b in at.button} >= {"Open the tumor sequencing (month 0)",
                                            "Open the Evolution view: what to watch next"}
    spot = at.selectbox(key="SYNTHETIC-001_ctdna_spot")
    spot.select(next(o for o in spot.options if "month 9 · ESR1" in o)).run()
    assert "##### ESR1 D538G at month 9" in " ".join(m.value for m in at.markdown)
    key = "SYNTHETIC-001|ctdna|ESR1 D538G|9"
    at.text_input(key="reviewer").set_value("ab").run()
    at.selectbox(key=f"spot_mark_{key}").select("second look").run()
    assert at.session_state["reviews"][key]["mark"] == "second look"
    assert at.selectbox(key=f"mark_{key}").value == "second look"  # the details agree
    at.checkbox(key=f"pin-{key}").check().run()
    assert at.session_state["pins"][key].startswith("ctDNA ESR1 D538G")

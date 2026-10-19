"""Blood and lab workbench: rules over the synthetic record and over small hand-made records."""

from muffle.timeline import EVENTS
from muffle.workbench.labs import (
    ABOVE,
    FALLING,
    FROM_RECORD,
    PLACEHOLDER,
    PLANNED_PANELS,
    RISING,
    WITHIN,
    look_here,
    quality_checks,
    results_table,
    rules_card,
    treatment_intervals,
)
from muffle.workspace import PLANNED


def test_results_table_on_the_synthetic_record():
    rows = results_table(EVENTS)
    assert [r["month"] for r in rows] == [-2, 1, 4, 7, 11, 16, 19, 24]
    assert {r["marker"] for r in rows} == {"CA 15-3"}  # CEA has no values
    by = {r["month"]: r for r in rows}
    assert by[-2]["flag"] == ABOVE and by[-2]["change"] is None and by[-2]["from_nadir"] is None
    assert by[-2]["event"].startswith("CA 15-3 48 U/mL")
    assert by[7]["value"] == 30 and by[7]["flag"] == WITHIN  # at the limit, not above it
    assert by[11]["flags"] == [ABOVE, RISING] and by[11]["flag"] == "above limit, rising"
    assert round(by[11]["change"], 2) == 0.73 and by[11]["per_month"] == 5.5
    assert round(by[11]["from_nadir"], 2) == 0.73
    assert by[16]["value"] == 41 and by[16]["flags"] == [ABOVE, FALLING]
    assert by[19]["flags"] == [ABOVE]  # 41 -> 34 is a 21% fall, below the rule's ratio
    for r in rows:
        assert r["unit"] == "U/mL" and r["reference"] == "below 30 U/mL"
        assert r["reference_source"] == "the record's lab report (month -2)"
        assert r["evidence"] == "observed"


def test_treatment_intervals_end_at_the_next_treatment_event_or_the_record_end():
    by = {i["agent"]: i for i in treatment_intervals(EVENTS)}
    assert (by["doxorubicin"]["start"], by["doxorubicin"]["end"]) == (-39, -36)
    assert by["cyclophosphamide"]["ended_by"] == "next treatment event (month -36)"
    assert (by["letrozole"]["start"], by["letrozole"]["end"]) == (-33, 1)
    assert (by["palbociclib"]["start"], by["palbociclib"]["end"]) == (1, 13)
    assert by["alpelisib"]["end"] == 24 and by["alpelisib"]["ended_by"].startswith("end of the")
    assert by["alpelisib"]["class"] == "Targeted"


def test_look_here_queue_is_latest_first_with_rule_source_and_status():
    queue = look_here(EVENTS)
    assert [(i["month"], i["flag"]) for i in queue] == [
        (24, ABOVE), (19, ABOVE), (16, ABOVE), (16, FALLING), (11, ABOVE), (11, RISING),
        (4, ABOVE), (4, FALLING), (1, ABOVE), (-2, ABOVE)]
    rising = next(i for i in queue if i["flag"] == RISING)
    assert rising["status"] == PLACEHOLDER and "placeholder" in rising["threshold"]
    assert rising["rule"] == "at least 25% above the previous value"
    above = next(i for i in queue if i["flag"] == ABOVE)
    assert above["status"] == FROM_RECORD
    assert above["threshold"] == "below 30 U/mL, from the record's lab report (month -2)"
    assert all(i["evidence"] == "observed" and i["event"] for i in queue)


def test_quality_checks_pass_on_the_record_except_cea_without_a_reference():
    checks = quality_checks(EVENTS)
    issues = [(c["check"], c["marker"]) for c in checks if not c["ok"]]
    assert issues == [("reference interval", "CEA")]
    gap = next(c for c in checks if c["marker"] == "CA 15-3" and c["check"].startswith("no gap"))
    assert gap["detail"] == "largest gap 5 months" and "placeholder" in gap["threshold"]
    assert next(c for c in checks if c["marker"] == "CEA" and "plausible" in c["check"])[
        "detail"] == "no results recorded"


def test_hand_made_record_a_gap_a_bad_value_a_missing_unit_and_no_reference():
    events = [{"month": 0, "ca153": 40, "cea": 2, "text": "first"},
              {"month": 9, "ca153": -1, "cea": 3, "text": "second"}]
    issues = {(c["check"], c["marker"]): c["detail"] for c in quality_checks(events)
              if not c["ok"]}
    assert issues[("no gap over 6 months", "CA 15-3")] == "month 0 to 9"
    assert issues[("values plausible (positive)", "CA 15-3")] == "-1 at month 9"
    assert ("reference interval", "CEA") in issues and len(issues) == 4

    unitless = quality_checks(events, markers={"cea": ("CEA", "")})
    assert next(c for c in unitless if c["check"] == "unit recorded")["ok"] is False

    cea = [r for r in results_table(events) if r["marker"] == "CEA"]
    assert cea[1]["reference"] == cea[1]["reference_source"] == "none in the record"
    assert cea[1]["flags"] == [RISING]  # a 50% rise is flagged even without a limit
    assert [i["flag"] for i in look_here(events) if i["marker"] == "CEA"] == [RISING]


def test_rules_card_has_no_model_and_every_threshold_a_source():
    card = rules_card()
    assert card["kind"].startswith("rules only") and card["validation"].startswith("none")
    assert card["evidence"] == "observed" and card["status"] == "implemented"
    for t in card["thresholds"]:
        assert t["source"] and t["status"] in (FROM_RECORD, PLACEHOLDER)
        assert ("placeholder" in t["source"]) == (t["status"] == PLACEHOLDER)
    assert [t["name"] for t in card["thresholds"]] == [
        "CA 15-3 reference limit", "rise", "fall", "gap"]
    assert any("noise" in f for f in card["known_failures"])
    assert any("assay method" in f for f in card["known_failures"])
    assert all(status == PLANNED for _, _, status in PLANNED_PANELS)


def test_the_page_renders_both_file_kinds_and_its_filter_works():
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    at = AppTest.from_file(str(root / "app" / "workbenches" / "labs.py"),
                           default_timeout=60).run()
    assert not at.exception
    assert "Synthetic patient" in at.warning[0].value
    assert len(at.expander) == 7 and len(at.dataframe[0].value) == 8
    at.checkbox[0].check().run()
    assert len(at.dataframe[0].value) == 7  # the month-7 value within the limit drops out

    tcga = AppTest.from_string(f"""
import sys
sys.path[:0] = [{str(root / "app")!r}, {str(root / "src")!r}]
from types import SimpleNamespace
from workbenches.labs import render
from muffle.workspace import case_file
render(case_file(SimpleNamespace(index=1, site="site-0", percentile=50.0, group="medium",
                                 age=50.0, stage="II", layers=["clinical"], missing=[],
                                 mutations=None)))
""", default_timeout=60).run()
    assert not tcga.exception
    assert "holds no lab results" in tcga.info[0].value and not tcga.dataframe[0].value.empty

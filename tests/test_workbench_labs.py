"""Blood and lab workbench: rules over the synthetic record and over small hand-made records."""

import pytest

from muffle.timeline import EVENTS
from muffle.imports import LAB_EXAMPLE, lab_tests, parse_labs
from muffle.workbench import labs_reference as ref
from muffle.workbench.labs import (
    ABOVE,
    BELOW,
    FALLING,
    FROM_RECORD,
    GRADED,
    GUIDELINE,
    LARGE_RISE,
    LITERATURE,
    NO_REFERENCE,
    PLACEHOLDER,
    PLANNED_PANELS,
    REFERENCE_LAB,
    RISING,
    WITHIN,
    baseline_band,
    confirmation_tracker,
    cross_analyte,
    cross_marker,
    kinetics,
    lead_lag,
    look_here,
    quality_checks,
    reference_table,
    report_markdown,
    results_table,
    rules_card,
    search,
    spot,
    therapy_windows,
    treatment_intervals,
)
from muffle.workspace import (
    MARKS,
    PLANNED,
    add_version,
    finding_key,
    record_events,
    synthetic_file,
)
from tests.test_workspace import timeline


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
    assert rising["status"] == LITERATURE and rising["threshold"].startswith("European Group")
    assert rising["rule"] == ("at least 25% above the previous value; unconfirmed until a "
                              "second specimen within a month")
    falling = next(i for i in queue if i["flag"] == FALLING)
    assert falling["status"] == PLACEHOLDER and "placeholder" in falling["threshold"]
    above = next(i for i in queue if i["flag"] == ABOVE)
    assert above["status"] == FROM_RECORD
    assert above["threshold"] == "below 30 U/mL, from the record's lab report (month -2)"
    assert all(i["evidence"] == "observed" and i["event"] for i in queue)


def test_quality_checks_pass_on_the_record_except_the_egtm_panel_without_cea():
    checks = quality_checks(EVENTS)
    issues = [(c["check"], c["marker"]) for c in checks if not c["ok"]]
    assert issues == [("EGTM panel (a MUC-1 marker with CEA)", "CEA")]
    gap = next(c for c in checks if c["marker"] == "CA 15-3" and c["check"].startswith("no gap"))
    assert gap["detail"] == "largest gap 5 months" and "placeholder" in gap["threshold"]
    assert {c["marker"] for c in checks} == {"CA 15-3", "CEA"}  # CEA only as the missing half


def test_hand_made_record_a_gap_a_bad_value_a_missing_unit_and_no_reference():
    events = [{"month": 0, "ca153": 40, "cea": 2, "text": "first"},
              {"month": 9, "ca153": -1, "cea": 3, "text": "second"}]
    issues = {(c["check"], c["marker"]): c["detail"] for c in quality_checks(events)
              if not c["ok"]}
    assert issues[("no gap over 6 months", "CA 15-3")] == "month 0 to 9"
    assert issues[("values plausible (positive)", "CA 15-3")] == "-1 at month 9"
    assert ("no gap over 6 months", "CEA") in issues and len(issues) == 3

    unitless = quality_checks(events, markers={"cea": ("CEA", "")})
    assert next(c for c in unitless if c["check"] == "unit recorded")["ok"] is False

    cea = [r for r in results_table(events) if r["marker"] == "CEA"]
    assert cea[1]["reference"] == "below 3 ng/mL"  # 3 is not above it: no above-limit flag
    assert cea[1]["reference_source"].startswith("Mayo Clinic Laboratories test catalog, test CEA")
    assert cea[1]["reference_status"] == REFERENCE_LAB
    assert cea[1]["flags"] == [RISING]  # the EGTM 50% rise
    assert [i["flag"] for i in look_here(events) if i["marker"] == "CEA"] == [RISING]

    # an analyte the table does not list, with no interval given: no out-of-interval flag
    other = [{"month": 0, "lab:ferritin": 80, "meta": {"lab:ferritin": {"name": "Ferritin",
                                                                        "unit": "ng/mL"}},
              "text": "a"}]
    r = results_table(other)[0]
    assert (r["marker"], r["unit"], r["reference"], r["panel"]) == (
        "Ferritin", "ng/mL", NO_REFERENCE, ref.UNLISTED)
    assert next(c for c in quality_checks(other) if c["check"] == "reference interval")[
        "ok"] is False


def test_rules_card_has_no_model_and_every_threshold_a_source():
    card = rules_card()
    assert card["kind"].startswith("rules only") and card["validation"].startswith("none")
    assert card["evidence"] == "observed" and card["status"] == "implemented"
    for t in card["thresholds"]:
        assert t["source"] and t["status"] in (FROM_RECORD, REFERENCE_LAB, LITERATURE, GUIDELINE,
                                               PLACEHOLDER)
        assert ("placeholder" in t["source"]) == (t["status"] == PLACEHOLDER)
    assert [(t["name"], t["status"]) for t in card["thresholds"]] == [
        ("CA 15-3 reference limit", FROM_RECORD), ("reference intervals", REFERENCE_LAB),
        ("rise (tumor markers)", LITERATURE), ("fall (tumor markers)", PLACEHOLDER),
        ("large rise or fall (other analytes)", PLACEHOLDER), ("low-count grades", GUIDELINE),
        ("adjusted calcium", LITERATURE), ("eGFR", LITERATURE), ("gap", PLACEHOLDER),
        ("cross-analyte window", PLACEHOLDER)]
    assert "EGTM" in card["validation"]
    assert any("noise" in f for f in card["known_failures"])
    assert any("assay method" in f for f in card["known_failures"])
    assert all(status == PLANNED for _, _, status in PLANNED_PANELS)


def test_pointers_are_shared_by_the_table_and_the_queue():
    rows = results_table(EVENTS)
    assert [(r["month"], r["pointer"]) for r in rows] == [
        (-2, "L1"), (1, "L2"), (4, "L3"), (7, ""), (11, "L4"), (16, "L5"), (19, "L6"), (24, "L7")]
    assert {i["month"]: i["pointer"] for i in look_here(EVENTS)}[11] == "L4"


def test_spot_panel_lists_the_rules_the_events_around_and_what_to_check():
    rows = results_table(EVENTS)
    s = spot(rows[4], rows, EVENTS)  # month 11
    assert [f["flag"] for f in s["fired"]] == [ABOVE, RISING]
    assert [e["month"] for e in s["events_around"]] == [11, 12, 13]
    assert len(s["check_by_eye"]) == 3 and "not a concern" in s["check_by_eye"][2]
    assert len(s["history"]) == 8 and s["evidence"] == "observed"
    high = [{"month": 0, "ca153": 20, "text": "a"}, {"month": 1, "ca153": 400, "text": "b"}]
    hr = results_table(high)
    assert "over 10x the limit" in spot(hr[1], hr, high)["check_by_eye"][2]


def test_kinetics_is_a_labeled_extrapolation_over_the_last_three_values():
    k = kinetics(results_table(EVENTS), "ca153")  # 41 at 16, 34 at 19, 31 at 24
    assert k["evidence"] == "model inference" and "placeholder" in k["method"]
    assert k["months"] == (16, 24) and k["direction"] == "falling"
    assert round(k["rate_per_month"], 4) == -0.0333 and round(k["halving_months"]) == 21
    assert tuple(round(x) for x in k["halving_months_range"]) == (11, 38)
    assert k["crossing"]["direction"] == "below" and round(k["crossing"]["months"], 1) == 1.0
    assert k["crossing"]["text"].endswith("would be crossed in about 1 month")
    assert tuple(round(x, 1) for x in k["crossing"]["range_months"]) == (0.5, 1.8)
    assert k["band"][0]["month"] == 24 and k["band"][0]["value"] == 31
    assert k["band"][-1]["lo"] <= k["band"][-1]["value"] <= k["band"][-1]["hi"]
    assert "not a prediction of progression" in k["caveat"]
    short = [{"month": 0, "ca153": 20, "text": "a"}, {"month": 3, "ca153": 25, "text": "b"}]
    assert kinetics(results_table(short), "ca153")["note"] == "needs at least 3 values, 2 recorded"
    rising = [{"month": m, "ca153": v, "text": "x"} for m, v in ((0, 10), (3, 14), (6, 20))]
    k = kinetics(results_table(rising), "ca153")
    assert k["direction"] == "rising" and k["crossing"]["direction"] == "above"
    assert round(k["doubling_months"]) == 6 and 0 < k["crossing"]["months"] < 6


def test_confirmation_tracker_follows_the_egtm_second_specimen_rule():
    t = confirmation_tracker(results_table(EVENTS))
    assert len(t) == 1 and t[0]["pointer"] == "L4" and t[0]["due_by"] == 12
    assert t[0]["outcome"] == "unconfirmed" and "month 16" in t[0]["detail"]
    assert t[0]["status"] == LITERATURE and t[0]["evidence"] == "observed"

    def record(third):
        return [{"month": 0, "ca153": 20, "text": "a"}, {"month": 2, "ca153": 30, "text": "b"},
                {"month": 3, "ca153": third, "text": "c"}]
    assert confirmation_tracker(results_table(record(28)))[0]["outcome"] == "confirmed"
    assert confirmation_tracker(results_table(record(22)))[0]["outcome"] == "withdrawn"
    open_rise = confirmation_tracker(results_table(record(28)[:2]))[0]
    assert open_rise["outcome"] == "unconfirmed" and open_rise["detail"].endswith("month 3")


def test_therapy_windows_mark_values_early_after_a_systemic_therapy_change():
    rows, intervals = results_table(EVENTS), treatment_intervals(EVENTS)
    w = therapy_windows(rows, intervals)
    assert [(x["month"], x["therapy"], x["months_after"]) for x in w] == [
        (1, "palbociclib + fulvestrant", 0)]
    assert "doi:10.1007/BF00311583" in w[0]["source"] and "placeholder" in w[0]["window"]
    assert [x["month"] for x in therapy_windows(rows, intervals, months=3)] == [1, 4, 16]


def test_baseline_band_is_the_longest_stable_run_labeled_by_its_months():
    band = baseline_band(results_table(EVENTS), "ca153")
    assert (band["months"], band["n"]) == ((16, 24), 3)
    assert (band["median"], band["lo"], band["hi"]) == (34, 31, 41)
    assert band["status"] == PLACEHOLDER and "placeholder" in band["method"]
    assert baseline_band(results_table(EVENTS[:9]), "ca153") is None  # runs of 2 only


def test_lead_lag_states_the_observed_order_against_imaging():
    out = lead_lag(results_table(EVENTS), EVENTS)
    assert [(x["imaging_month"], x["marker_month"], x["lead_months"]) for x in out] == [
        (-1, -2, 1), (7, 7, 0), (12, 11, 1), (19, 19, 0)]
    month12 = out[2]
    assert month12["pointer"] == "L4" and month12["progression"]
    assert month12["what"] == ("CA 15-3 above limit, rising at month 11 came 1 month before "
                               "the progression on imaging at month 12: concordant")
    assert out[3]["what"].endswith("discordant") and out[1]["what"].endswith("concordant")
    assert all(x["evidence"] == "observed" and "not a validated" in x["caveat"] for x in out)


def test_cross_marker_names_concordant_and_discordant_rises():
    view = cross_marker(results_table(EVENTS))
    assert view["pairs"] == [] and view["note"].startswith("CEA has no values")
    assert view["status"] == PLANNED and "correlation is not causation" in view["caveat"]
    both = [{"month": 0, "ca153": 20, "cea": 2, "text": "a"},
            {"month": 3, "ca153": 30, "cea": 2.1, "text": "b"},
            {"month": 6, "ca153": 40, "cea": 4, "text": "c"},
            {"month": 9, "ca153": 41, "cea": 4.1, "text": "d"}]
    pairs = cross_marker(results_table(both))["pairs"]
    assert [p["relation"] for p in pairs] == [
        "neither rising", "discordant: CA 15-3 rising, CEA not", "concordant rise",
        "neither rising"]
    assert pairs[2]["ca153_flag"] == pairs[2]["cea_flag"] == "above limit, rising"


@pytest.mark.parametrize("query, understood, n, answer", [
    ("above the limit", True, 7, "7 results above limit"),
    ("rising", True, 1, "1 result rising"),
    ("after palbociclib", True, 7, "7 results after palbociclib (started month 1)"),
    ("before letrozole", True, 0, "0 results before letrozole (started month -33) (none in "
                                  "the record)"),
    ("month 11", True, 1, "1 result at month 11"),
    ("L4", True, 1, "1 pointer L4"),
    ("ca 15-3", True, 8, "8 CA 15-3 results"),
    ("liver lesions", False, 0, "lab results can't see lesions: imaging does (the imaging "
                                "reports are in the record). Markers against imaging, and the "
                                "cross-analyte hypotheses, set the two side by side."),
    ("liver", False, 0, "no liver values on file, so this panel can't see that: a liver panel "
                        "(ALT, AST, GGT, Bilirubin (total)) would."),
    ("neutrophils", False, 0, "this record has no Neutrophils (absolute) result, so this panel "
                              "can't see it: a blood count panel would (neutropenia is the most "
                              "common grade 3-4 toxicity of palbociclib)."),
    ("ecog", False, 0, "this panel can't see that. It searches flags (above or below the limit, "
                       "rising, falling, large rise or fall, within limit), treatments (after "
                       "palbociclib, before letrozole), months (month 11), pointers (L5), "
                       "analytes and panels (liver, blood count)."),
])
def test_search_in_plain_words_with_an_honest_cant_answer(query, understood, n, answer):
    hit = search(query, results_table(EVENTS), treatment_intervals(EVENTS))
    assert (hit["understood"], len(hit["rows"]), hit["answer"]) == (understood, n, answer)


def test_search_names_an_unknown_treatment():
    hit = search("after bevacizumab", results_table(EVENTS), treatment_intervals(EVENTS))
    assert not hit["understood"] and hit["answer"].startswith("no treatment called bevacizumab")


def test_report_markdown_lists_numbers_flags_placeholders_and_review_marks():
    rows, iv = results_table(EVENTS), treatment_intervals(EVENTS)
    md = report_markdown("SYNTHETIC-001", rows, look_here(EVENTS), quality_checks(EVENTS),
                         rules_card(), kinetics(rows, "ca153"), confirmation_tracker(rows),
                         therapy_windows(rows, iv), baseline_band(rows, "ca153"),
                         lead_lag(rows, EVENTS),
                         {"SYNTHETIC-001|lab|ca153|11": {
                             "what": "CA 15-3 52 U/mL at month 11: above limit, rising (L4)",
                             "mark": "agree", "by": "ab", "at": "12:00"}})
    assert "| L4 | CA 15-3 | 11 | 52 U/mL | below 30 U/mL | above limit, rising | +73% |" in md
    assert "- L4 month 11, CA 15-3 52 U/mL: rising" in md and "European Group" in md
    assert "halving months: 21 (range 11 to 38)" in md
    assert "would be crossed in about 1 month" in md
    assert "## Placeholders" in md and "- fall (tumor markers):" in md and "- gap:" in md
    assert "## Reference intervals and their sources" in md
    assert "- kinetics method:" in md and "- therapy caution window:" in md
    assert "- CA 15-3 52 U/mL at month 11: above limit, rising (L4): agree (ab, 12:00)" in md
    assert "recommend" not in md.replace("Nothing here is a recommendation", "")
    assert report_markdown("X", rows, [], [], rules_card()).endswith("- none\n\n"
        "Rules: Lab result rules (blood and lab workbench); validation: none here: no cohort, "
        "no outcome, no assay study; the rise criterion is the EGTM guidance, not validated on "
        "this record.\n")


def results_of(at):
    """The results table: the first dataframe whose columns start with pointer and review."""
    return next(d.value for d in at.dataframe
                if list(d.value.columns)[:3] == ["pointer", "review", "marker"])


def test_the_page_renders_both_file_kinds_and_its_filter_works():
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    at = AppTest.from_file(str(root / "app" / "workbenches" / "labs.py"),
                           default_timeout=60).run()
    assert not at.exception
    assert "Synthetic patient" in at.warning[0].value
    details = [e.label for e in at.expander]
    assert {"Results (8)", "Rise confirmation, EGTM (1)", "Planned panels (4)"} <= set(details)
    assert len(results_of(at)) == 8
    at.checkbox[0].check().run()
    assert len(results_of(at)) == 7  # the month-7 value within the limit drops out
    text = " ".join(e.value for e in [*at.markdown, *at.caption, *at.warning, *at.info]
                    + [*at.subheader]).lower()
    assert "synthetic" in text and not any(w in text for w in ("demo", "hackathon"))
    overview = next(m.value for m in at.markdown if "results** for" in m.value)
    assert "L4: the rise at month 11 is **unconfirmed**" in overview
    assert "halving time about 21 months" in overview
    headings = [m.value for m in at.markdown if m.value.startswith("#### ")]
    assert headings == ["#### Overview", "#### Trends", "#### Details", "#### Spot panel",
                        "#### Model and validation card", "#### What this test cannot see",
                        "#### Export"]
    # the spot panel opens on the latest flagged value
    assert at.selectbox(key="SYNTHETIC-001_spot").value.startswith("L7 · month 24")
    # plain-word search
    at.text_input(key="SYNTHETIC-001_search").set_value("after palbociclib").run()
    assert "7 results after palbociclib" in " ".join(m.value for m in at.markdown)
    at.text_input(key="SYNTHETIC-001_search").set_value("liver lesions").run()
    assert at.warning[-1].value.startswith("lab results can't see lesions: imaging does")
    # a review mark lands in the workspace's store under finding_key, the table and the queue
    key = finding_key(synthetic_file(timeline()), "lab", "ca153", 11)
    assert key == "SYNTHETIC-001|lab|ca153|11"
    at.text_input(key="reviewer").set_value("ab").run()
    spot = at.selectbox(key="SYNTHETIC-001_spot")  # the mark is in the value's Spot panel
    spot.select(next(o for o in spot.options if o.startswith("L4 ·"))).run()
    assert list(at.selectbox(key=f"mark_{key}").options) == ["no mark", *MARKS]
    at.selectbox(key=f"mark_{key}").select("agree").run()
    done = at.session_state["reviews"][key]
    assert done == {"what": "CA 15-3 52 U/mL at month 11: above limit, rising (L4)",
                    "mark": "agree", "by": "ab", "at": done["at"]} and len(done["at"]) == 16
    at.selectbox(key="SYNTHETIC-001_labs_reviewed").select("reviewed").run()
    shown = results_of(at)
    assert list(shown["pointer"]) == ["L4"] and shown["review"].iloc[0] == "agree (ab)"
    assert "1 review mark." in next(m.value for m in at.markdown if "results** for" in m.value)
    at.selectbox(key=f"mark_{key}").select("no mark").run()
    assert key not in at.session_state["reviews"]

    as_of = AppTest.from_string(f"""
import json, sys
sys.path[:0] = [{str(root / "app")!r}, {str(root / "src")!r}]
from workbenches.labs import render
from muffle.workspace import synthetic_file
tl = json.loads(open({str(root / "app" / "timeline_synthetic.json")!r}, encoding="utf-8").read())
render(synthetic_file(tl), version=9)  # month 7: CA 15-3 30, within limit
""", default_timeout=60).run()
    assert not as_of.exception
    assert any(c.value.startswith("As of month 7 (month 7 · Imaging): 6 later events")
               for c in as_of.caption)
    assert len(results_of(as_of)) == 4 and "Results (4)" in [e.label for e in as_of.expander]

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
    assert "No lab results in this file" in tcga.info[0].value
    assert not tcga.table[0].value.empty  # the planned panels (a static finding table)


# -------------------------------------------------------------- any analyte: the reference table

def test_reference_table_rows_each_name_a_source_and_an_interval():
    table = reference_table()
    assert len(table) == len(ref.ANALYTES) == 19
    for row in table:
        assert row["source"] and row["why it matters here"] and row["why: source"]
        assert row["unit"] == next(iter(ref.ANALYTES[row["key"]]["units"]))
    by = {r["key"]: r for r in table}
    assert by["alt"]["interval"] == "female: 7-45 U/L; male: 7-55 U/L"
    assert by["anc"]["interval"] == "adults: 1.56-6.45 x10^9/L"
    assert by["ca153"]["source"].startswith(
        "Mayo Clinic Laboratories test catalog, test CA153 (mayocliniclabs.com/test-catalog/"
        "overview/81607), adult reference values, read 2026-10-20")
    assert by["phosphate"]["why: source"].startswith("placeholder")  # no citation checked
    assert {r["status"] for r in table} == {REFERENCE_LAB}
    assert by["egfr"]["derived"] and by["ca_adj"]["derived"] and not by["alp"]["derived"]


@pytest.mark.parametrize("key, value, unit, expected", [
    ("creatinine", 80, "µmol/L", 0.9048), ("creatinine", 80, "umol/L", 0.9048),
    ("calcium", 2.5, "mmol/L", 10.02), ("bilirubin", 17.1, "µmol/L", 1.0),
    ("albumin", 35, "g/L", 3.5), ("hemoglobin", 6.8, "mmol/L", 10.955),
    ("anc", 1500, "/µL", 1.5), ("platelets", 150, "10^9/L", 150.0),
    ("platelets", 150, "x10(9)/L", 150.0), ("alt", 1.0, "µkat/L", 60.0), ("cea", 4, "µg/L", 4.0),
    ("ca153", 30, "kU/L", 30.0)])
def test_units_convert_to_the_tables_unit(key, value, unit, expected):
    v, canonical = ref.convert(key, value, unit)
    assert v == pytest.approx(expected, abs=1e-3) and canonical == ref.ANALYTES[key]["unit"]


def test_unknown_units_names_grades_and_the_two_equations():
    with pytest.raises(ValueError, match="not one the reference table converts for CEA"):
        ref.convert("cea", 3, "mmol/L")
    assert ref.lookup("Alkaline Phosphatase") == "alp" and ref.lookup("CA 27-29") == "ca2729"
    assert ref.lookup("Haemoglobin") == "hemoglobin" and ref.lookup("ferritin") is None
    assert ref.custom_key("Free T4 (pmol)") == "lab:free-t4-pmol"
    assert [ref.ctcae_grade("anc", v, 1.56) for v in (1.55, 1.2, 0.7, 0.3, 2.0)] == [
        1, 2, 3, 4, None]
    assert [ref.ctcae_grade("hemoglobin", v, 11.6) for v in (11.0, 9.0, 7.5)] == [1, 2, 3]
    assert ref.ctcae_grade("alt", 100, 7) is None  # no grades for this analyte here
    assert ref.adjusted_calcium(10.0, 3.0) == 11.0  # Payne 1973: calcium - albumin + 4.0
    assert round(ref.egfr_ckd_epi_2021(1.0, 60, True), 1) == 64.5
    assert round(ref.egfr_ckd_epi_2021(1.0, 60, False), 1) == 86.2
    assert ref.interval("alt", None) == (7.0, 55.0, "sex not recorded: the wider of the female "
                                                    "(7-45) and male (7-55) intervals")
    assert ref.interval("alt", "female")[:2] == (7.0, 45.0)


def import_example():
    """SYNTHETIC-001 with the import dialog's example CSV (a CBC and chemistry) added."""
    pf = synthetic_file(timeline())
    ok, bad = parse_labs(LAB_EXAMPLE.encode(), after=pf.latest.month)
    tests, observed = lab_tests(ok)
    return add_version(pf, tests, 27, "Imported lab results", "AB", "14:03", observed), ok, bad


def test_an_imported_cbc_and_chemistry_csv_flows_through_end_to_end():
    pf, ok, bad = import_example()
    assert len(ok) == 29 and not bad
    calcium = next(r for r in ok if r["key"] == "calcium" and r["month"] == 27)
    assert (calcium["value"], calcium["unit"], calcium["reported"]) == (
        10.86, "mg/dL", "2.71 mmol/L")
    assert (calcium["low"], calcium["limit"]) == (8.617, 10.22)  # the lab's own, converted
    events = record_events(pf)
    rows = results_table(events)
    by = {(r["key"], r["month"]): r for r in rows}
    assert by[("calcium", 27)]["reference_source"] == "the imported lab report (month 27)"
    assert by[("calcium", 27)]["flags"] == [ABOVE]
    assert by[("ca_adj", 27)]["value"] == pytest.approx(11.56)
    assert by[("ca_adj", 27)]["evidence"] == "model inference"  # a published equation
    assert by[("anc", 27)]["flag"] == "below limit, CTCAE grade 2" and by[("anc", 27)]["grade"] == 2
    assert by[("wbc", 27)]["grade"] == 1 and by[("hemoglobin", 25)]["flags"] == [BELOW, GRADED]
    assert by[("alt", 27)]["flags"] == [ABOVE, LARGE_RISE]  # +61%: the placeholder change rule
    assert by[("ca153", 27)]["flags"] == [ABOVE, RISING]  # the EGTM rule, tumor markers only
    assert by[("bilirubin", 27)]["reference_status"] == REFERENCE_LAB  # none was imported
    assert (by[("lab:glucose", 27)]["marker"], by[("lab:glucose", 27)]["panel"]) == (
        "Glucose", ref.UNLISTED)
    assert by[("lab:glucose", 27)]["flags"] == [ABOVE]  # against its own lab's 3.9-5.5
    assert by[("platelets", 27)]["flags"] == []  # 142: within the wider of the two intervals
    female = {(r["key"], r["month"]): r for r in results_table(events, sex="female", age=62)}
    assert female[("platelets", 27)]["flags"] == [BELOW, GRADED]  # below the female 157
    assert round(female[("egfr", 27)]["value"], 1) == 71.8 and female[("egfr", 27)]["flags"] == []
    issues = {c["check"] for c in quality_checks(events) if not c["ok"]}
    assert issues == {"sex for sex-specific intervals", "eGFR inputs (age and sex)"}
    assert not [c for c in quality_checks(events, sex="female", age=62) if not c["ok"]]
    # the import re-ran the SOS rise rule, for the tumor marker only
    assert [a.what for a in pf.latest.alerts] == [
        "CA 15-3 rose from 31 to 44 U/mL (+42%), above the reference limit of 30",
        "CA 15-3 rose from 44 to 58 U/mL (+32%), above the reference limit of 30"]


def test_cross_analyte_hypotheses_name_the_imaging_report_and_the_other_causes():
    pf, _, _ = import_example()
    events = record_events(pf)
    rows = results_table(events)
    pointer = {r["pointer"]: r["key"] for r in rows if r["pointer"]}
    hyp = {h["site"]: h for h in cross_analyte(rows, events)}
    assert (hyp["Bone"]["imaging_month"], hyp["Liver"]["imaging_month"]) == (-1, 12)
    assert "new liver lesions" in hyp["Liver"]["hypothesis"]
    assert {h["evidence"] for h in hyp.values()} == {"hypothesis"}
    assert {pointer[p] for p in hyp["Bone"]["pointers"]} == {"alp", "calcium", "ca_adj"}
    assert {pointer[p] for p in hyp["Liver"]["pointers"]} == {"alp", "alt", "ast", "bilirubin"}
    assert any("normal GGT points to bone" in g for g in hyp["Bone"]["ggt"])
    assert "drug toxicity" in hyp["Liver"]["other_causes"]
    assert "doi:10.1056/NEJMcp042806" in hyp["Bone"]["source"]
    assert not cross_analyte(results_table(EVENTS), EVENTS)  # the record has no such values
    hit = search("liver", rows, treatment_intervals(events))
    assert hit["understood"] and hit["answer"] == "6 liver results"
    assert search("neutrophils", rows, treatment_intervals(events))["answer"] == (
        "2 Neutrophils (absolute) results")


def test_the_page_draws_an_imported_cbc_and_chemistry_series():
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    at = AppTest.from_string(f"""
import json, sys
sys.path[:0] = [{str(root / "app")!r}, {str(root / "src")!r}]
from workbenches.labs import render
from muffle.imports import LAB_EXAMPLE, lab_tests, parse_labs
from muffle.workspace import add_version, record_events, synthetic_file
tl = json.loads(open({str(root / "app" / "timeline_synthetic.json")!r}, encoding="utf-8").read())
pf = synthetic_file(tl)
ok, _ = parse_labs(LAB_EXAMPLE.encode(), after=24)
pf = add_version(pf, lab_tests(ok)[0], 27, "labs", "AB", "14:03")
render(pf, events=record_events(pf))
""", default_timeout=60).run()
    assert not at.exception
    assert [t.label for t in at.tabs] == ["Tumor markers", "Liver", "Bone and mineral", "Kidney",
                                          "Blood count", "General chemistry", ref.UNLISTED]
    assert "2 cross-analyte hypotheses (for clinician review)" in next(
        m.value for m in at.markdown if "results** for" in m.value)
    assert "next to the results imported in this session" in at.warning[0].value
    before = len(results_of(at))
    at.selectbox(key="SYNTHETIC-001_labs_sex").select("female").run()
    at.number_input(key="SYNTHETIC-001_labs_age").set_value(62).run()
    assert not at.exception and len(results_of(at)) == before + 2  # two eGFR values


def test_the_page_guides_a_first_reader_and_reaches_the_spot_panel_and_import():
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    at = AppTest.from_file(str(root / "app" / "workbenches" / "labs.py"),
                           default_timeout=60).run()
    assert not at.exception
    md = [m.value for m in at.markdown]
    assert any(m.startswith(":material/lightbulb: **How to use this page:** **Trends**")
               for m in md)
    # the look-here items are instructions with their reason, consequence and target
    assert any(m.startswith("`L4` Look at CA 15-3 52 U/mL at month 11: above limit, rising. "
                            "*Why:* above limit") and "*Consequence:* may change care. Opens L4 "
               "in the Spot panel." in m for m in md)
    # the Spot panel names its value, its evidence, method and threshold source, and pins it
    assert "##### CA 15-3 at month 24 · L7" in md
    assert any("Method: rules, version 2" in c.value and "Reference interval:" in c.value
               for c in at.caption)
    key = "SYNTHETIC-001|lab|ca153|24"
    at.checkbox(key=f"pin-{key}").check().run()
    assert at.session_state["pins"][key].startswith("CA 15-3 31 U/mL at month 24")
    at.checkbox(key=f"pin-{key}").uncheck().run()
    assert key not in at.session_state["pins"]
    # "Add CA 15-3 values…" opens the import dialog on lab results with the analyte typed in
    add = next(b for b in at.button if b.label == "Add CA 15-3 values…")
    add.click().run()
    assert not at.exception and at.session_state["import-kind"] == "Lab results (CSV)"

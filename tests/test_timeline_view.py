"""The Timeline view's data: lanes, treatment bars, what each version brought, the risk chart's
context and the export, on the synthetic file, a hand-made TCGA file and imports."""

import json
from pathlib import Path
from types import SimpleNamespace

from muffle import timeline_view as tv
from muffle.imports import imaging_test, lab_tests, parse_labs
from muffle.workspace import add_version, case_file, report_markdown, synthetic_file

ROOT = Path(__file__).resolve().parents[1]


def synthetic():
    return synthetic_file(json.loads((ROOT / "app" / "timeline_synthetic.json").read_text(
        encoding="utf-8")))


def imported(pf):
    """SYNTHETIC-001 with a CA 15-3 import at month 27, then an imaging report."""
    ok, _ = parse_labs(b"month,marker,value,unit\n27,CA 15-3,45,U/mL\n", after=24)
    tests, observed = lab_tests(ok)
    pf = add_version(pf, tests, 27, "Imported lab results", "AB", "14:03", observed)
    scan = imaging_test("CT CAP", "New pulmonary nodules, consistent with progression.", 27,
                        "import-2", "")
    return add_version(pf, [scan], 27, "Imported imaging report", "AB", "14:05")


def test_lanes_place_every_entry_of_the_synthetic_record_at_its_month_and_version():
    pf = synthetic()
    data = tv.lanes(pf)
    assert data["lanes"] == list(tv.LANES[:-1]) and data["empty"] == [tv.IMPORTED]
    assert "diagnosis at month -40" in data["axis"]
    pts = data["points"]
    nodes = [p for p in pts if p["mark"] == "version"]
    assert [p["version"] for p in nodes] == list(range(16))
    assert [p["month"] for p in nodes] == [v.month for v in pf.versions]
    # a ctDNA sample sits at its own month but opens the version it joined (month -2)
    month = {v.month: k for k, v in enumerate(pf.versions)}
    dna = next(p for p in pts if p["lane"] == "ctDNA" and p["month"] == -12)
    assert dna["version"] == month[-2] and "synthetic series" in dna["evidence"]
    # alerts on the lane of the test that raised them, with their evidence label and trust;
    # the two alerts of one imaging report share one point
    alerts = {(p["lane"], p["month"]): p for p in pts if p["mark"] == "alert"}
    assert set(alerts) == {("Imaging", -1), ("Sequencing and omics", 0),
                           ("Labs and tumor markers", 11), ("Imaging", 12),
                           ("Report versions", 12)}
    liver = alerts[("Imaging", 12)]
    assert "Progression on imaging" in liver["what"] and "New metastatic site: liver" in \
        liver["what"] and "observed; trust strong" in liver["evidence"]
    assert "placeholder" in alerts[("Report versions", 12)]["result"]  # the risk-jump rule
    assert all(p["source"] == "the record" for p in pts)


def test_treatment_bars_run_to_the_next_entry_that_does_not_name_them():
    bars = {s["drug"]: (s["start"], s["end"], s["open"]) for s in tv.spans(synthetic())}
    assert bars["letrozole"] == (-33, 1, False)
    assert bars["palbociclib"] == (1, 13, False)   # month 13 "adds alpelisib to fulvestrant"
    assert bars["fulvestrant"] == (1, 24, True) and bars["alpelisib"] == (13, 24, True)
    assert max(s["track"] for s in tv.spans(synthetic())) == 1  # two drugs at once at most


def test_changes_name_the_tests_record_alerts_and_risk_a_version_brought():
    pf = synthetic()
    c = tv.changes(pf, 11)  # month 12: imaging reads progression in the liver
    assert [t.name for t in c["tests"]] == ["Imaging report"]
    assert [o["what"] for o in c["observed"]] == ["Metastatic sites", "Progressions on imaging"]
    assert c["observed"][0]["after"] == "Bone (month -1), Liver (month 12)"
    assert any(a.what == "New metastatic site: liver" for a in c["alerts"])
    risk = {d["finding"]: (d["before"], d["after"]) for d in c["risk"]}
    assert risk["12-month risk"] == ("37%", "88%") and c["attribution"]
    first = tv.changes(pf, 0)  # the first version brings everything it holds
    assert all(o["before"] is None for o in first["observed"]) and not first["risk"]
    assert tv.changes(pf, 7)["treatments"] == ["palbociclib", "fulvestrant"]


def test_summary_changes_keep_added_changed_and_removed_cards_only():
    def card(what, text):
        return {"what": what, "text": text, "evidence": "observed", "trust": "strong",
                "opens": ("Tests", "Lab", 11, "CA 15-3"), "focus": {"marker": "ca153"}}

    before = {"labs": {"title": "Labs", "cards": [card("CA 15-3", "30 U/mL"), card("Same", "x"),
                                                  card("Gone", "y")]}}
    after = {"labs": {"title": "Labs", "cards": [card("CA 15-3", "52 U/mL"), card("Same", "x")]},
             "ctdna": {"title": "ctDNA", "cards": [card("ESR1", "new")]}}
    out = {(c["workbench"], c["what"]): c for c in tv.summary_changes(before, after)}
    assert set(out) == {("Labs", "CA 15-3"), ("Labs", "Gone"), ("ctDNA", "ESR1")}
    assert out[("Labs", "CA 15-3")]["status"] == "changed" and \
        out[("Labs", "CA 15-3")]["opens"] == ("Tests", "Lab", 11, "CA 15-3")
    assert out[("Labs", "Gone")]["status"] == "removed" and out[("Labs", "Gone")]["opens"] == ()
    assert out[("ctDNA", "ESR1")]["status"] == "added"
    assert tv.summary_changes(before, before) == []


def test_imports_grow_the_timeline_its_change_card_context_and_export():
    pf = imported(synthetic())
    data = tv.lanes(pf)
    assert data["empty"] == []
    nodes = [p for p in data["points"] if p["mark"] == "version"][-2:]
    assert [p["what"] for p in nodes] == ["month 27 · imported by AB at 14:03",
                                          "month 27 · imported by AB at 14:05"]
    assert nodes[1]["x"] > nodes[0]["x"] == 27  # two versions in one month: both clickable
    assert {p["tone"] for p in data["points"] if p["version"] >= 16} == {
        "imported in this session", "SOS alert"}
    lab = next(p for p in data["points"] if p["lane"] == tv.IMPORTED and p["mark"] == "test")
    assert lab["what"] == "CA 15-3" and lab["source"].startswith("imported by AB at 14:03")
    c = tv.changes(pf, 16)
    assert [t.name for t in c["tests"]] == ["CA 15-3"] and c["imported"].startswith(
        "imported by AB at 14:03")
    assert c["alerts"][0].what.startswith("CA 15-3 rose from 31 to 45")
    assert not c["risk"] and "No new risk estimate" in c["summary"]
    assert tv.context(pf, 16)["ca153"][-1]["value"] == 45.0
    assert tv.context(pf, 17)["imaging"][-1]["read"] == "progression"
    assert [s["end"] for s in tv.spans(pf) if s["open"]] == [27, 27]  # open bars reach the import
    page = report_markdown(pf, 17)
    assert "## Timeline: what each version brought" in page
    assert "- **month 27 · imported by AB at 14:03** (imported by AB at 14:03" in page
    assert "SOS alert: New metastatic site: lung [observed; trust moderate]" in page
    assert page.index("## Timeline") < page.index("## Imported in this session")


def test_context_is_as_of_the_version_and_cuts_bars_there():
    pf = synthetic()
    k = [v.month for v in pf.versions].index(7)
    ctx = tv.context(pf, k)
    assert [r["month"] for r in ctx["ca153"]] == [-2, 1, 4, 7]
    assert sorted({r["month"] for r in ctx["ctdna"]}) == [-12, -6, -2, 0, 4, 7]
    assert [(r["month"], r["read"]) for r in ctx["imaging"]] == [
        (-1, "progression"), (7, "no progression stated")]
    bars = {s["drug"]: (s["end"], s["open"]) for s in ctx["treatments"]}
    assert bars["palbociclib"] == (7, True) and "alpelisib" not in bars


def test_a_tcga_file_sits_at_its_sample_with_its_documents_dates_and_grows_with_imports():
    case = SimpleNamespace(index=1, site="site-1", percentile=40.0, group="medium", age=61.0,
                           stage="II", layers=["clinical", "rna"], missing=[],
                           mutations=["PIK3CA p.H1047R"])
    docs = [{"id": "d1", "title": "Surgical pathology", "text": "Received on 03/14/2009. "
             "Invasive ductal carcinoma, grade 2."},
            {"id": "d2", "title": "Addendum", "text": "ER positive."}]
    pf = case_file(case, 0.7, documents=docs)
    data = tv.lanes(pf)
    assert data["lanes"] == ["Report versions", "Sequencing and omics",
                             "Pathology and documents"] and "TCGA tumor sample" in data["axis"]
    assert {p["month"] for p in data["points"]} == {0}
    docs = next(p for p in data["points"] if p["lane"] == "Pathology and documents")
    assert docs["what"] == "Surgical pathology; Addendum"  # one version, lane and month: one point
    assert "Surgical pathology carries the date 03/14/2009" in docs["when"]
    assert "carries no date" in docs["when"]  # the addendum's text has none
    scan = imaging_test("CT", "New liver lesions, consistent with progression.", 3, "i1", "")
    grown = tv.lanes(add_version(pf, [scan], 3, "Imported imaging report", "CD", "15:00"))
    assert grown["lanes"][-1] == tv.IMPORTED
    assert [p["month"] for p in grown["points"] if p["mark"] == "version"] == [0, 3]
    assert tv.changes(pf, 0)["summary"].startswith("Model estimate")


def test_the_lane_charts_month_axis_title_is_two_lines():
    """QA R3-9: on one line it was cut at 800 px ("…diagnosis at mont")."""
    import sys

    sys.path.insert(0, str(ROOT / "app"))
    import charts

    spec = charts.event_lanes(tv.lanes(synthetic()), 15).to_dict()
    titles = [lay["encoding"]["x"].get("title") for lay in spec["layer"]
              if "x" in lay.get("encoding", {}) and "title" in lay["encoding"]["x"]]
    assert titles[0] == ["months from the first tumor sequencing",
                         "(month 0; diagnosis at month -40)"]

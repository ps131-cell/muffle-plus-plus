"""Genomics workbench: observed variants, CIViC interpretation, panel coverage, review queue."""

import json
from pathlib import Path
from types import SimpleNamespace

from muffle.data.tcga import DRIVERS
from muffle.report.case_tools import HYPOTHESIS, OBSERVED
from muffle.timeline import EVENTS
from muffle.workbench import genomics as g
from muffle.workspace import case_file, synthetic_file

ROOT = Path(__file__).resolve().parents[1]
CASE = dict(index=926, site="site-2", stage="III", age=55.0, percentile=99.0, group="high",
            layers=["clinical", "genomic", "rna", "protein"], missing=["methylation"],
            mutations=["PIK3CA p.H1047R", "TP53 p.R175H"])


def timeline() -> dict:
    return json.loads((ROOT / "app" / "timeline_synthetic.json").read_text(encoding="utf-8"))


def test_synthetic_variant_with_its_civic_items_from_the_json():
    tl = timeline()
    vs = g.variants(synthetic_file(tl))
    assert [v["variant"] for v in vs] == ["PIK3CA H1047R"]
    v = vs[0]
    assert v["month"] == 0 and v["sample"] == "bone biopsy"
    assert v["detection"]["evidence"] == OBSERVED
    assert v["detection"]["allele_fraction"] == "allele fraction: not stated in the record"
    assert v["interpretation"]["evidence"] == v["effect"]["evidence"] == HYPOTHESIS
    assert v["interpretation"]["items"] == tl["evidence"]["PIK3CA H1047R"]
    assert len(v["interpretation"]["items"]) == 3
    assert len(v["effect"]["statements"]) == 3
    assert all("Sensitivity/Response (Supports)" in s for s in v["effect"]["statements"])
    # the committed items are all level A, so the queue says established
    assert v["strongest_level"] == "A"
    assert g.review_queue(vs) == {g.ESTABLISHED: ["PIK3CA H1047R"], g.UNCERTAIN: [],
                                  g.NO_ITEMS: []}


def test_review_queue_depends_on_a_level_a_or_b_item():
    pf = synthetic_file(timeline())
    weak = {"PIK3CA H1047R": [{"evidence_level": "C", "significance": "Sensitivity/Response",
                               "direction": "Supports", "therapies": "Everolimus"},
                              {"evidence_level": "D", "significance": "Sensitivity/Response",
                               "direction": "Supports", "therapies": "Alpelisib"}]}
    vs = g.variants(pf, evidence=weak)
    assert vs[0]["strongest_level"] == "C"
    assert g.review_queue(vs)[g.UNCERTAIN] == ["PIK3CA H1047R"]
    strong = {"PIK3CA H1047R": [{"evidence_level": "D"}, {"evidence_level": "A"}]}
    assert g.review_queue(g.variants(pf, evidence=strong))[g.ESTABLISHED] == ["PIK3CA H1047R"]
    none = g.variants(pf, evidence={"PIK3CA H1047R": []})
    assert none[0]["interpretation"]["note"].startswith("no CIViC item")
    assert g.review_queue(none)[g.NO_ITEMS] == ["PIK3CA H1047R"]


def test_synthetic_coverage_and_longitudinal():
    pf = synthetic_file(timeline())
    cov = {c["gene"]: c["status"] for c in g.panel_coverage(pf)}
    assert cov["PIK3CA"] == g.FOUND and cov["TP53"] == g.PANEL_NOT_STATED and len(cov) == 16
    lon = g.longitudinal(pf, EVENTS)
    assert lon["timepoints"] == [{"month": 0, "sample": "bone biopsy", "found": "PIK3CA H1047R"}]
    assert lon["statement"].startswith("sequenced once at month 0: mutation status after "
                                       "treatment is unknown")


def test_events_until_a_version_month_hides_later_sequencing():
    pf = synthetic_file(timeline())
    before = g.events_until(EVENTS, pf.versions[5].month)  # month -1: imaging, before sequencing
    assert g.variants(pf, before) == []
    assert {c["status"] for c in g.panel_coverage(pf, before)} == {g.NOT_TESTED}
    assert g.longitudinal(pf, before)["statement"].startswith("not sequenced")
    at = g.events_until(EVENTS, pf.versions[6].month)  # month 0: the sequencing itself
    assert [v["variant"] for v in g.variants(pf, at)] == ["PIK3CA H1047R"]
    assert g.events_until(None, None) == EVENTS


def test_tcga_case_two_variants_and_fourteen_genes_tested_not_found():
    pf = case_file(SimpleNamespace(**CASE))
    vs = g.variants(pf, EVENTS, lookup=lambda gene, change: [])
    assert [v["variant"] for v in vs] == ["PIK3CA H1047R", "TP53 R175H"]
    assert vs[0]["month"] is None and vs[0]["sample"] == "primary tumor (TCGA)"
    assert "masked calls" in vs[0]["assay"]
    assert vs[0]["detection"]["allele_fraction"] == g.NO_ALLELE_FRACTION
    assert g.review_queue(vs)[g.NO_ITEMS] == ["PIK3CA H1047R", "TP53 R175H"]
    cov = g.panel_coverage(pf)
    assert [c["gene"] for c in cov] == DRIVERS
    assert sum(c["status"] == g.NOT_FOUND for c in cov) == 14
    assert {c["status"] for c in cov if c["gene"] in ("PIK3CA", "TP53")} == {g.FOUND}
    assert g.longitudinal(pf)["statement"].startswith("sequenced once at baseline")
    # the lookup serves variants the mapping lacks
    vs = g.variants(pf, EVENTS, evidence={"TP53 R175H": [{"evidence_level": "B"}]},
                    lookup=lambda gene, change: [{"evidence_level": "E"}])
    assert [v["strongest_level"] for v in vs] == ["E", "B"]


def test_not_sequenced_is_unknown_and_an_empty_panel_is_all_not_found():
    unsequenced = case_file(SimpleNamespace(**{**CASE, "mutations": None}))
    assert g.variants(unsequenced, EVENTS) == []
    assert {c["status"] for c in g.panel_coverage(unsequenced)} == {g.NOT_TESTED}
    assert g.longitudinal(unsequenced)["statement"].startswith("not sequenced")
    clean = case_file(SimpleNamespace(**{**CASE, "mutations": []}))
    assert g.variants(clean, EVENTS) == []
    assert {c["status"] for c in g.panel_coverage(clean)} == {g.NOT_FOUND}
    assert g.longitudinal(clean)["timepoints"][0]["found"] == "none of the panel"


def test_data_card_has_no_model_and_names_its_limits():
    card = g.data_card()
    assert card["status"] == g.IMPLEMENTED and card["model"].startswith("none")
    assert "no allele fractions" in card["data"]["TCGA-BRCA"]
    assert card["labels"]["detection"] == OBSERVED
    assert any("purity" in limit for limit in card["limits"])
    assert {p["status"] for p in card["planned"]} == {g.PLANNED}

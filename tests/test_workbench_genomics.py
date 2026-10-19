"""Genomics workbench: observed variants, CIViC interpretation, panel coverage, review queue,
the evidence ladder, the resistance watchlist, conflicts, search, provenance, marks, export."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from muffle.data.tcga import DRIVERS
from muffle.report.case_tools import HYPOTHESIS, OBSERVED
from muffle.timeline import EVENTS
from muffle.workbench import genomics as g
from muffle.workspace import case_file, synthetic_file

ROOT = Path(__file__).resolve().parents[1]
CASE = dict(index=926, site="site-2", stage="III", age=55.0, percentile=99.0, group="high",
            layers=["clinical", "genomic", "rna", "protein"], missing=["methylation"],
            mutations=["PIK3CA p.H1047R", "TP53 p.R175H"])
COLUMNS = ["molecular_profile", "disease", "therapies", "evidence_type", "evidence_direction",
           "evidence_level", "significance", "citation", "rating", "evidence_status",
           "evidence_civic_url"]
ROWS = [  # a small CIViC-shaped table (accepted Predictive items)
    ["RB1 Loss-of-function", "Breast Cancer", "Palbociclib", "Predictive", "Supports", "D",
     "Resistance", "Condorelli, 2018", "3", "accepted", "https://civicdb.org/e/1"],
    ["PTEN Loss", "Breast Cancer", "Alpelisib", "Predictive", "Supports", "D", "Resistance",
     "Juric, 2015", "3", "accepted", "https://civicdb.org/e/2"],
    ["ESR1 Y537S", "Breast Cancer", "Aromatase Inhibitor", "Predictive", "Supports", "B",
     "Resistance", "Fribbens, 2016", "4", "accepted", "https://civicdb.org/e/3"],
    ["PIK3CA H1047R", "Breast Cancer", "Trastuzumab", "Predictive", "Supports", "B",
     "Resistance", "Kim, 2016", "2", "accepted", "https://civicdb.org/e/4"],
    ["KRAS G12C", "Colorectal Cancer", "Cetuximab", "Predictive", "Supports", "A", "Resistance",
     "Ng, 2019", "3", "accepted", "https://civicdb.org/e/5"],
    ["PIK3CA H1047R", "Breast Cancer", "Alpelisib", "Predictive", "Supports", "A",
     "Sensitivity/Response", "Andre, 2019", "5", "accepted", "https://civicdb.org/e/6"],
]
A = {"evidence_level": "A", "level_meaning": "validated association", "significance":
     "Sensitivity/Response", "direction": "Supports", "therapies": "Alpelisib",
     "disease": "Breast Cancer", "citation": "Andre, 2019", "match": "this variant",
     "molecular_profile": "PIK3CA H1047R", "url": "https://civicdb.org/e/6"}
NOT_A = {**A, "direction": "Does Not Support", "evidence_level": "C", "citation": "Doe, 2021",
         "url": "https://civicdb.org/e/7"}
RESIST = {**A, "significance": "Resistance", "therapies": "Trastuzumab", "evidence_level": "B",
          "url": "https://civicdb.org/e/4", "citation": "Kim, 2016",
          "match": "any mutation in the gene"}


@pytest.fixture
def table():
    return pd.DataFrame(ROWS, columns=COLUMNS)


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
    assert g.provenance(pf, before)[0] == ("sample", "none yet")
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
    assert dict(g.provenance(unsequenced))["can show"].startswith("nothing")
    clean = case_file(SimpleNamespace(**{**CASE, "mutations": []}))
    assert g.variants(clean, EVENTS) == []
    assert {c["status"] for c in g.panel_coverage(clean)} == {g.NOT_FOUND}
    assert g.longitudinal(clean)["timepoints"][0]["found"] == "none of the panel"


def test_data_card_has_no_model_and_names_its_limits():
    card = g.data_card()
    assert card["status"] == g.IMPLEMENTED and card["model"].startswith("none")
    assert "no allele fractions" in card["data"]["TCGA-BRCA"]
    assert "PADA-1" in card["data"]["literature"]
    assert card["labels"]["detected"] == OBSERVED
    assert card["labels"]["watchlist"] == HYPOTHESIS
    assert any("purity" in limit for limit in card["limits"])
    assert {p["status"] for p in card["planned"]} == {g.PLANNED}


def test_ladder_has_five_rungs_each_with_its_evidence_type_and_a_way_to_strengthen_it(table):
    pf = synthetic_file(timeline())
    v = g.variants(pf, evidence={"PIK3CA H1047R": [A, RESIST]})[0]
    rungs = g.ladder(v, g.resistance_items("PIK3CA", {"alpelisib"}, table))
    assert [r["label"] for r in rungs] == ["detected", "interpreted", "predicted effect",
                                          "therapy evidence (for clinician review)",
                                          "resistance mechanisms"]
    assert [r["evidence"] for r in rungs] == [OBSERVED] + [HYPOTHESIS] * 4
    assert all(r["strengthen"] for r in rungs)
    assert rungs[0]["lines"] == ["Tumor sequencing · bone biopsy · month 0",
                                 "allele fraction: not stated in the record"]
    assert "Andre, 2019 (2019)" in rungs[1]["lines"][0]
    assert rungs[1]["strengthen"].startswith("nothing more from CIViC")  # level A, the variant
    assert rungs[3]["items"] == [A]
    # resistance: the variant's own resistance item, the table's items for the gene or the
    # therapy (not the colorectal one), no duplicate; no literature row for PIK3CA
    urls = [i["url"] for i in rungs[4]["items"]]
    assert urls == ["https://civicdb.org/e/4", "https://civicdb.org/e/2"]
    assert rungs[4]["literature"] == []
    # an empty variant: every hypothesis rung says so, and the first strengthening is level A/B
    empty = g.ladder(g.variants(pf, evidence={"PIK3CA H1047R": []})[0])
    assert [r["status"] for r in empty] == ["observed", "none", "none", "none", "none"]
    assert empty[1]["strengthen"] == "a level A or B item in this disease"
    assert empty[4]["lines"] == ["no resistance item for this gene or its therapies in breast "
                                 "cancer"]


def test_ladder_resistance_rung_cites_the_esr1_literature_for_an_esr1_variant():
    pf = synthetic_file(timeline())
    v = g.variants(pf, evidence={"PIK3CA H1047R": []})[0]
    esr1 = {**v, "gene": "ESR1", "change": "Y537S", "variant": "ESR1 Y537S"}
    rung = g.ladder(esr1)[4]
    assert rung["status"] == "present" and len(rung["literature"]) == 2
    assert any("PADA-1" in line for line in rung["lines"])
    assert any("SERENA-6" in line for line in rung["lines"])


def test_watchlist_follows_the_recorded_treatments(table):
    pf = synthetic_file(timeline())
    assert g.treatments(pf) == ["doxorubicin", "cyclophosphamide", "paclitaxel", "letrozole",
                                "palbociclib", "fulvestrant", "alpelisib"]
    assert g.treatments(pf, 0) == []  # the diagnosis version, before any treatment
    w = g.watchlist(pf, table=table)
    assert w["evidence"] == HYPOTHESIS and w["use"] == "what to watch, never advice"
    alterations = [(r["under"], r["alteration"]) for r in w["rows"]]
    assert alterations[:2] == [("letrozole", "ESR1 mutation (ligand-binding domain)")] * 2
    assert {r["source"] for r in w["rows"][:2]} == {"Bidard et al. 2022, PADA-1, Lancet Oncol",
                                                     "Bidard et al. 2025, SERENA-6, N Engl J Med"}
    assert ("letrozole (aromatase inhibitor)", "ESR1 Y537S") in alterations  # CIViC's class name
    assert ("palbociclib", "RB1 Loss-of-function") in alterations
    assert ("alpelisib", "PTEN Loss") in alterations
    assert not any("KRAS" in a for _, a in alterations)  # colorectal item excluded
    assert all(r["detect"] and r["level"] for r in w["rows"])
    # up to letrozole (version 3): the literature plus the aromatase-inhibitor item; the
    # chemotherapy drugs have no row in this table
    early = g.watchlist(pf, version=3, table=table)
    assert early["treatments"][-1] == "letrozole" and len(early["rows"]) == 3
    # no table: literature only; a TCGA case has no treatment and says so
    assert len(g.watchlist(pf)["rows"]) == 2
    tcga = g.watchlist(case_file(SimpleNamespace(**CASE)), table=table)
    assert tcga["rows"] == [] and tcga["note"] == "no treatment recorded in this file"


def test_conflicts_keep_both_sides_apart_with_level_and_year():
    out = g.conflicts([A, NOT_A, RESIST])
    assert out[0]["association"] == "PIK3CA H1047R · Alpelisib · Sensitivity/Response"
    assert [i["evidence_level"] for i in out[0]["supports"]] == ["A"]
    assert [(i["evidence_level"], i["year"]) for i in out[0]["does_not_support"]] == [("C",
                                                                                       "2021")]
    assert out[1]["does_not_support"] == [] and len(out) == 2  # one-sided groups come after


def test_search_by_gene_level_resistance_and_an_uncovered_gene():
    pf = case_file(SimpleNamespace(**CASE))
    vs = g.variants(pf, EVENTS, evidence={"PIK3CA H1047R": [A, RESIST], "TP53 R175H": []})
    cov = g.panel_coverage(pf)
    assert g.search(vs, cov, "")["variants"] == vs
    assert [v["variant"] for v in g.search(vs, cov, "tp53")["variants"]] == ["TP53 R175H"]
    assert [v["variant"] for v in g.search(vs, cov, "level A")["variants"]] == ["PIK3CA H1047R"]
    assert g.search(vs, cov, "level b")["variants"][0]["variant"] == "PIK3CA H1047R"
    assert [v["variant"] for v in g.search(vs, cov, "resistance")["variants"]] == \
        ["PIK3CA H1047R"]
    assert [v["variant"] for v in g.search(vs, cov, "alpelisib")["variants"]] == ["PIK3CA H1047R"]
    assert g.search(vs, cov, "BRCA1") == {"variants": [], "note": "this panel does not include "
                                                                  "BRCA1"}
    assert g.search(vs, cov, "GATA3")["note"] is None  # in the panel, just not mutated here
    assert g.search(vs, cov, "level Z")["note"] is None


def test_provenance_strip_for_both_file_kinds():
    strip = dict(g.provenance(synthetic_file(timeline())))
    assert strip["sample"] == "bone biopsy" and strip["date"] == "month 0"
    assert "allele fractions" in strip["cannot show"]
    tcga = dict(g.provenance(case_file(SimpleNamespace(**CASE))))
    assert tcga["date"] == "not in the open data" and "masked" in tcga["assay"]


def test_marks_and_exports():
    pf = synthetic_file(timeline())
    vs = g.variants(pf, evidence={"PIK3CA H1047R": [A]})
    marks = g.add_mark({}, "PIK3CA H1047R", g.AGREE, " ab ", "2026-10-19 10:00")
    g.add_mark(marks, A["url"], g.SECOND_LOOK, "", "2026-10-19 10:01")
    assert marks["PIK3CA H1047R"] == [{"verdict": "agree", "initials": "ab",
                                       "time": "2026-10-19 10:00"}]
    assert marks[A["url"]][0]["initials"] == "?"
    with pytest.raises(ValueError):
        g.add_mark(marks, "x", "maybe", "ab")
    ladders = {v["variant"]: g.ladder(v) for v in vs}
    md = g.report_markdown(pf, vs, ladders, g.watchlist(pf), marks, g.provenance(pf))
    assert md.startswith("# Genomics workbench · SYNTHETIC-001")
    assert "Synthetic patient" in md and "| PIK3CA H1047R | bone biopsy |" in md
    assert "### 1. detected [observed]" in md and "### 5. resistance mechanisms [hypothesis]" in md
    assert "PADA-1" in md and "agree (ab, 2026-10-19 10:00)" in md
    assert "never a recommendation" in md
    rows = list(csv_rows(g.report_csv(vs, marks)))
    assert rows[0][:3] == ["variant", "gene", "change"] and rows[0][-1] == "marks"
    assert rows[1][0] == "PIK3CA H1047R" and rows[1][9] == "A"
    assert rows[1][-1] == "needs a second look (?, 2026-10-19 10:01)"
    assert len(list(csv_rows(g.report_csv(g.variants(pf, evidence={"PIK3CA H1047R": []}),
                                          {})))) == 2  # a variant without items keeps one row


def csv_rows(text: str):
    import csv
    import io
    return csv.reader(io.StringIO(text))

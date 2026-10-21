"""Genomics workbench: observed variants, CIViC interpretation, panel coverage, review queue,
the evidence ladder, the resistance watchlist, conflicts, search, provenance, marks, export."""

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

from muffle.data.tcga import DRIVERS
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
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


def test_data_card_runs_no_model_and_names_its_limits():
    card = g.data_card()
    assert card["status"] == g.IMPLEMENTED and card["model"].startswith("no model runs here")
    assert "read counts" in card["data"]["TCGA-BRCA"]
    assert card["labels"]["predicted effect"] == INFERENCE
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


def test_marks_use_the_report_pages_finding_keys_and_store():
    pf = synthetic_file(timeline())
    v = g.variants(pf, evidence={"PIK3CA H1047R": [A]})[0]
    assert g.variant_key(pf, v) == "SYNTHETIC-001|variant|PIK3CA H1047R|0"
    tcga = case_file(SimpleNamespace(**CASE))
    assert g.variant_key(tcga, g.variants(tcga, EVENTS)[1]) == "Case 926|variant|TP53 R175H|None"
    assert g.item_key(pf, v, A) == "SYNTHETIC-001|civic|PIK3CA H1047R|https://civicdb.org/e/6"
    assert g.item_key(pf, v, {}, 2) == "SYNTHETIC-001|civic|PIK3CA H1047R|item-2"
    reviews = {"OTHER-1|alert|0|x": {"what": "x", "mark": "agree", "by": "zz", "at": "t"}}
    g.add_mark(reviews, g.variant_key(pf, v), "PIK3CA H1047R (bone biopsy)", g.AGREE, " ab ",
               "2026-10-19 10:00")
    assert reviews["SYNTHETIC-001|variant|PIK3CA H1047R|0"] == {
        "what": "PIK3CA H1047R (bone biopsy)", "mark": "agree", "by": "ab",
        "at": "2026-10-19 10:00"}
    g.add_mark(reviews, g.item_key(pf, v, A), "PIK3CA H1047R: CIViC level A", g.SECOND_LOOK, "",
               "2026-10-19 10:01")
    assert g.marks_of(reviews, pf).keys() == {
        "SYNTHETIC-001|variant|PIK3CA H1047R|0",
        "SYNTHETIC-001|civic|PIK3CA H1047R|https://civicdb.org/e/6"}
    assert g.mark_text(reviews[g.item_key(pf, v, A)]) == \
        "second look (no initials, 2026-10-19 10:01)"
    assert g.mark_text(None) == ""
    with pytest.raises(ValueError):
        g.add_mark(reviews, "x", "x", "maybe")
    g.add_mark(reviews, g.variant_key(pf, v), "", None)  # clears
    assert g.variant_key(pf, v) not in reviews and len(reviews) == 2
    assert g.VERDICTS == ("reviewed", "agree", "disagree", "second look")  # workspace.MARKS
    g.add_mark(reviews, g.variant_key(pf, v), "PIK3CA H1047R", g.REVIEWED, "ab", "t")
    assert reviews[g.variant_key(pf, v)]["mark"] == "reviewed"


def test_exports_carry_this_files_marks_from_the_shared_store():
    pf = synthetic_file(timeline())
    vs = g.variants(pf, evidence={"PIK3CA H1047R": [A]})
    v = vs[0]
    reviews = {"OTHER-1|alert|0|x": {"what": "x", "mark": "agree", "by": "zz", "at": "t"}}
    g.add_mark(reviews, g.variant_key(pf, v), "PIK3CA H1047R (bone biopsy)", g.AGREE, "ab",
               "2026-10-19 10:00")
    g.add_mark(reviews, g.item_key(pf, v, A), "PIK3CA H1047R: CIViC level A", g.SECOND_LOOK, "",
               "2026-10-19 10:01")
    g.add_mark(reviews, "SYNTHETIC-001|alert|11|CA 15-3 rose", "CA 15-3 rose", g.DISAGREE, "cd",
               "2026-10-19 10:02")
    ladders = {x["variant"]: g.ladder(x) for x in vs}
    md = g.report_markdown(pf, vs, ladders, g.watchlist(pf), reviews, g.provenance(pf))
    assert md.startswith("# Genomics workbench · SYNTHETIC-001")
    assert "Synthetic patient" in md and "| PIK3CA H1047R | bone biopsy |" in md
    assert "### 1. detected [observed]" in md and "### 5. resistance mechanisms [hypothesis]" in md
    assert "PADA-1" in md and "never a recommendation" in md
    assert "- PIK3CA H1047R (bone biopsy): agree (ab, 2026-10-19 10:00)" in md
    assert "- PIK3CA H1047R: CIViC level A: second look (no initials, 2026-10-19 10:01)" in md
    assert "- CA 15-3 rose: disagree (cd, 2026-10-19 10:02)" in md  # another page, same file
    assert "zz" not in md  # another file's mark stays out
    rows = list(csv_rows(g.report_csv(pf, vs, reviews)))
    assert rows[0][:3] == ["variant", "gene", "change"] and rows[0][-1] == "marks"
    assert rows[1][0] == "PIK3CA H1047R" and rows[1][9] == "A"
    assert rows[1][-1] == "second look (no initials, 2026-10-19 10:01)"  # the item's own mark
    bare = list(csv_rows(g.report_csv(pf, g.variants(pf, evidence={"PIK3CA H1047R": []}),
                                      reviews)))
    assert len(bare) == 2 and bare[1][-1] == "agree (ab, 2026-10-19 10:00)"  # the variant's


def csv_rows(text: str):
    import csv
    import io
    return csv.reader(io.StringIO(text))


# ---------------------------------------------------------------- the genome views (genome.py)

from muffle import evolution  # noqa: E402
from muffle.data.tcga import copy_number_calls  # noqa: E402
from muffle.report import vep  # noqa: E402
from muffle.workbench import genome as gx  # noqa: E402
from muffle.workspace import FINDING_KINDS, add_version, finding_key  # noqa: E402
from muffle.workspace import Test as RecordTest  # noqa: E402

CN = gx.load(gx.CN_JSON)
EFFECTS = gx.load(gx.EFFECT_JSON)


def tcga_case(index: int, **over):
    """A bundled TCGA case as the shipped genome numbers know it (index, percentile, drivers)."""
    c = CN["cases"][str(index)]
    muts = [d["variant"].replace(" ", " p.", 1) for d in c.get("drivers", [])]
    return SimpleNamespace(**{**CASE, "index": index, "percentile": c["percentile"],
                              "log_risk": c["log_risk"], "mutations": muts, **over})


def test_copy_number_calls_at_their_cutoffs_follow_the_models_rule():
    assert [gx.cn_call(c, 2) for c in (0, 1, 2, 3, 4, 5)] == [-2, -1, 0, 1, 2, 2]
    assert [gx.cn_call(c, 3) for c in (2, 3, 5, 6)] == [-1, 0, 1, 2]
    assert gx.cn_call(None, 2) is None and gx.cn_call(float("nan"), 2) is None
    cn = pd.DataFrame([[0, 1, 2, 3, 4, 2], [3, 3, 6, 2, 0, 3]], dtype=float)
    calls = copy_number_calls(cn)  # the rule that built the model's input
    for i, row in cn.iterrows():
        ploidy = max(1, round(float(row.median())))
        assert [gx.cn_call(c, ploidy) for c in row] == calls.iloc[i].astype(int).tolist()
    tags = {c["name"]: c["tag"] for c in gx.CUTOFFS}
    assert tags == {"ploidy estimate": gx.METHOD, "deep deletion": gx.DEFINITION,
                    "loss": gx.PLACEHOLDER, "gain": gx.PLACEHOLDER,
                    "amplification": gx.PLACEHOLDER}
    assert all(c["source"] for c in gx.CUTOFFS)


def test_shipped_copy_number_matches_the_model_and_percentiles_are_ordered():
    assert CN["checks"]["vaf_vs_read_counts"][0] == CN["checks"]["vaf_vs_read_counts"][1] > 0
    agree, total = CN["checks"]["calls_vs_bundle"]
    assert agree / total > 0.99  # the rest: symbols naming two loci (Y_RNA twice in the model)
    assert set(gx.INTEREST) | set(gx.PATHWAY_GENES) <= set(CN["genes"])
    for gene in ("ERBB2", "CCND1", "TP53"):
        pts = [(c["cn"][gene][0] / c["ploidy"], c["cn"][gene][1]) for c in CN["cases"].values()
               if "cn" in c and c["cn"][gene][0] is not None]
        pts.sort()
        assert all(0 <= p <= 100 for _, p in pts)
        pairs = list(zip(pts, pts[1:], strict=False))
        assert all(a[1] <= b[1] for a, b in pairs if a[0] < b[0])  # monotone
        assert all(a[1] == b[1] for a, b in pairs if a[0] == b[0])  # ties share a percentile
    shares = CN["genes"]["ERBB2"]["cohort_calls"]
    assert len(shares) == 5 and abs(sum(shares) - 1) < 0.01


def test_landscape_rows_in_genome_order_with_the_ploidy_override():
    block = CN["cases"]["61"]
    rows = gx.landscape(block, CN["genes"])
    assert [r["order"] for r in rows] == sorted(r["order"] for r in rows)
    erbb2 = next(r for r in rows if r["gene"] == "ERBB2")
    assert erbb2["call"] == gx.cn_call(erbb2["copies"], block["ploidy"]) == 2
    assert erbb2["share"] == CN["genes"]["ERBB2"]["cohort_calls"][4] and erbb2["interest"]
    assert "HER2 / RTK" in erbb2["pathways"] and erbb2["evidence"] == OBSERVED
    other = gx.landscape(block, CN["genes"], ploidy=10)
    assert next(r for r in other if r["gene"] == "ERBB2")["call"] == gx.cn_call(
        erbb2["copies"], 10)
    q = gx.cn_queue(rows, block)
    assert any(x.startswith("ERBB2 amplification") for x in q) and "placeholder" in q[-1]


def test_two_ploidy_estimates_that_disagree_are_flagged():
    assert gx.ploidy_check({"ploidy": 2.0, "absolute": {"ploidy": 2.3}})["disagree"] is False
    pc = gx.ploidy_check({"ploidy": 1.0, "absolute": {"ploidy": 2.1, "purity": 0.5}})
    assert pc["disagree"] and "in doubt" in pc["text"]
    assert gx.ploidy_check({"ploidy": 2.0}) is None and gx.ploidy_check(None) is None
    assert gx.cn_queue([], {"ploidy": 1.0, "absolute": {"ploidy": 2.1}})[0].startswith("Ploidy 1")


def test_numbers_are_shown_only_for_the_same_build():
    pf = case_file(tcga_case(61))
    assert gx.case_block(CN, pf) is CN["cases"]["61"]  # the file's log-risk matches
    assert gx.case_block(CN, pf, log_risk=CN["cases"]["61"]["log_risk"] + 0.5) is None
    other = case_file(tcga_case(61, log_risk=CN["cases"]["61"]["log_risk"] + 0.5))
    assert gx.case_block(CN, other) is None  # another build of the cohort
    old = tcga_case(61)
    del old.log_risk  # a file without the log-risk falls back to the risk percentile
    assert gx.case_block(CN, case_file(old)) is CN["cases"]["61"]
    moved = SimpleNamespace(**{**old.__dict__, "percentile": 99.0})
    assert gx.case_block(CN, case_file(moved)) is None
    assert gx.case_block(CN, synthetic_file(timeline())) is None
    assert gx.case_index(pf) == 61


def test_burden_count_rate_percentile_and_labeled_reference_lines():
    b = gx.burden(CN["cases"]["61"], CN)
    raw = CN["cases"]["61"]["burden"]
    assert b["measured"] and b["calls"] == raw["calls"]
    assert abs(b["rate"] - raw["calls"] / gx.EXOME_MB) < 1e-3 and gx.EXOME_MB == 38.0
    assert b["high"] == (raw["pct"] >= gx.HIGH_PCT) and b["above_keynote"] is (b["rate"] >= 10)
    assert b["evidence"]["count"] == OBSERVED and b["evidence"]["rate"].startswith("derived")
    high = next(c for c in CN["cases"].values() if c.get("burden", {}).get("pct", 0) >= 90)
    assert gx.burden(high, CN)["high"]
    assert gx.burden(None, CN) == {"measured": False, "note": "not sequenced: the burden is "
                                   "unknown"}


def test_allele_fractions_with_their_interval_and_the_clonal_range():
    assert gx.clonal_range(0.5, 2) == (0.25, 0.5)
    lo, hi = gx.clonal_range(1.0, 4)
    assert (lo, hi) == (0.25, 1.0) and gx.clonal_range(None, 2) is None
    block = {"absolute": {"purity": 0.5}, "drivers": [
        {"variant": "A X1Y", "class": "missense", "copies": 2},
        {"variant": "B X2Y", "class": "nonsense", "copies": 2},
        {"variant": "C X3Y", "class": "missense", "copies": 2, "dna_vaf": 0.3}]}
    reads = {"variants": [{"variant": "A X1Y", "alt": 40, "depth": 100},
                          {"variant": "B X2Y", "alt": 5, "depth": 200}]}
    a, b, c = gx.allele_fractions(block, reads)
    assert a["vaf"] == 0.4 and a["lo"] < 0.4 < a["hi"] and a["fit"] == "within the clonal range"
    assert b["fit"].startswith("below the clonal range")
    assert c["vaf"] == 0.3 and c["fit"].startswith("not assessed")
    assert a["evidence"]["reads"] == OBSERVED and a["evidence"]["fit"].startswith(INFERENCE)
    vaf = gx.load(gx.APP / "evolution_vaf.json")["cases"]["61"]
    real = gx.allele_fractions(CN["cases"]["61"], vaf)
    assert {x["variant"] for x in real} == {"PIK3CA E469delinsDK", "PIK3CA H1047R"}
    assert all(x["alt"] and x["depth"] for x in real)


def test_three_kinds_of_effect_evidence_stay_apart():
    ef = gx.effect("PIK3CA H1047R", EFFECTS)
    assert ef["found"] and ef["annotation"]["evidence"] == OBSERVED
    assert ef["interpretation"]["evidence"] == HYPOTHESIS
    assert ef["prediction"]["evidence"] == INFERENCE
    assert ef["prediction"]["class"] == "ambiguous"  # a known hotspot: predicted is not interpreted
    assert "Oncogenic" in ef["interpretation"]["somatic"]
    assert "not approved for, any clinical use" in ef["prediction"]["limits"]
    trunc = gx.effect("TP53 R196*", EFFECTS)
    assert trunc["prediction"]["applies"] is False and trunc["prediction"]["score"] is None
    assert gx.effect_text(trunc)["prediction"].startswith("not applicable")
    assert gx.effect("ABC X1Y", EFFECTS)["found"] is False
    rng = EFFECTS["alphamissense_class_ranges"]
    assert rng["likely_benign"][1] == 0.34 and rng["likely_pathogenic"][0] == 0.564
    text = gx.EFFECT_JSON.read_text()
    assert "COSV" not in text and "COSM" not in text  # COSMIC is excluded from the project
    rungs = g.ladder(g.variants(synthetic_file(timeline()))[0], predicted=ef)
    assert rungs[2]["evidence"] == INFERENCE and "AlphaMissense" in rungs[2]["lines"][0]


def test_vep_client_sends_names_only_and_drops_cosmic():
    assert vep.hgvs_protein("ESR1 D538G") == "ESR1:p.Asp538Gly"
    assert vep.hgvs_protein("TP53 R196*") == "TP53:p.Arg196Ter"
    assert vep.hgvs_protein("TP53 E285Rfs*54") is None
    assert vep.region("3", 100, "A", "G", "X Y") == "3 100 100 A/G + X_Y"
    assert vep.region("3", 100, "-", "TT", "X") == "3 101 100 -/TT + X"
    assert vep.region("3", 100, "ACG", "-", "X") == "3 100 102 ACG/- + X"
    rec = {"seq_region_name": "3", "start": 5, "allele_string": "A/G",
           "transcript_consequences": [
               {"canonical": 1, "mane_select": "NM_1", "consequence_terms": ["missense_variant"],
                "hgvsp": "P:p.H1R", "alphamissense": {"am_pathogenicity": 0.9,
                                                      "am_class": "likely_pathogenic"}}],
           "colocated_variants": [
               {"id": "COSV1", "clinvar_somatic_classification": "x"},
               {"id": "CM1", "clin_sig": ["pathogenic"]},
               {"id": "rs1", "clin_sig": ["pathogenic", "not_provided"],
                "var_synonyms": {"ClinVar": ["RCV1", "VCV9"], "COSMIC": ["COSM1"]}}]}
    p = vep.parse(rec)
    assert p["clinvar"] == {"germline": ["pathogenic"], "somatic": "", "record": "VCV9"}
    assert p["alphamissense"]["score"] == 0.9 and p["consequence"] == "missense_variant"


def test_pathway_table_integrity_and_identifiers():
    brief = {"ER signaling": {"ESR1", "GATA3", "FOXA1"}, "HER2 / RTK": {"ERBB2", "EGFR", "FGFR1"},
             "PI3K / AKT / mTOR": {"PIK3CA", "PTEN", "AKT1", "PIK3R1"},
             "Cell cycle": {"CCND1", "CDK4", "CDK6", "RB1", "CDKN2A"},
             "TP53 and DNA repair": {"TP53", "BRCA1", "BRCA2", "ATM", "PALB2"},
             "MAP kinase": {"NF1", "KRAS", "MAP3K1", "MAP2K4"}, "Chromatin": {"ARID1A", "KMT2C"}}
    for name, genes in brief.items():
        assert genes <= set(gx.PATHWAYS[name]["genes"]), name
        assert gx.PATHWAYS[name]["says"], name
        for key, says in gx.PATHWAYS[name]["says"]:
            assert key in gx.REFERENCES and says
    for cite, where, pmid, doi, title in gx.REFERENCES.values():
        assert pmid.isdigit() and doi.startswith("10.") and cite and where and title
    assert gx.VERIFIED == "2026-10-20"


def test_references_match_pubmed():
    """Every PMID's DOI as PubMed lists it (NCBI E-utilities); skipped offline."""
    import urllib.request
    ids = ",".join(r[2] for r in gx.REFERENCES.values())
    try:
        with urllib.request.urlopen("https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
                                    f"?db=pubmed&retmode=json&id={ids}", timeout=20) as r:
            result = json.load(r)["result"]
    except Exception as e:  # offline CI or NCBI down
        pytest.skip(f"PubMed not reachable: {e}")
    for _, _, pmid, doi, _ in gx.REFERENCES.values():
        dois = [a["value"].lower() for a in result[pmid]["articleids"] if a["idtype"] == "doi"]
        assert doi.lower() in dois, pmid


def test_pathway_map_marks_mutated_amplified_unknown_and_not_altered():
    rows = [{"gene": "ERBB2", "call": 2, "call_text": "amplification", "copies": 8, "pct": 99},
            {"gene": "PTEN", "call": -1, "call_text": "loss", "copies": 1, "pct": 5},
            {"gene": "AKT1", "call": 0, "call_text": "neutral", "copies": 2, "pct": 50}]
    nodes = {n["gene"]: n for n in gx.pathway_map(["PIK3CA H1047R"], rows, sequenced=False)}
    assert nodes["PIK3CA"]["status"] == "mutated" and nodes["ERBB2"]["status"] == "amplification"
    assert nodes["PTEN"]["status"] == "loss" and nodes["AKT1"]["status"] == "not altered"
    assert nodes["TP53"]["status"] == "not measured"  # unknown, never normal
    assert {n["gene"] for n in gx.pathway_map([], [], sequenced=True)
            if n["status"] == "not altered"} == set(gx.PATHWAY_GENES)
    s = {p["pathway"]: p for p in gx.pathway_summary(list(nodes.values()))}
    assert s["PI3K / AKT / mTOR"]["altered"] == ["PIK3CA (mutated)", "PTEN (loss)"]
    assert s["PI3K / AKT / mTOR"]["evidence"] == HYPOTHESIS
    assert all(src["pmid"] and src["says"] for p in s.values() for src in p["sources"])


def test_pathway_items_come_from_civic_for_its_genes(table):
    items = gx.pathway_items("PI3K / AKT / mTOR", table)
    assert items["total"] == 3 and items["items"][0]["evidence_level"] == "A"
    assert gx.pathway_items("Cell cycle", table)["items"][0]["molecular_profile"] == \
        "RB1 Loss-of-function"
    assert gx.pathway_items("Chromatin", None) == {"items": [], "total": 0}
    amp = pd.DataFrame([["ERBB2 Amplification", "Breast Cancer", "Trastuzumab", "Predictive",
                         "Supports", "A", "Sensitivity/Response", "X, 2001", "5", "accepted",
                         "https://civicdb.org/e/9"]], columns=COLUMNS)
    got = gx.cn_items("ERBB2", 2, amp)
    assert got["total"] == 1 and got["items"][0]["matches_call"] is True
    assert gx.cn_items("ERBB2", -1, amp)["items"][0]["matches_call"] is False


CTDNA = {"assay": "plasma panel (synthetic)", "synthetic": True, "detection_limit": 0.1,
         "variants": ("PIK3CA H1047R", "ESR1 D538G"),
         "samples": [{"month": -2, "vaf": {"PIK3CA H1047R": 1.6, "ESR1 D538G": None}},
                     {"month": 4, "vaf": {"PIK3CA H1047R": 0.9, "ESR1 D538G": 0.2}}]}


def test_longitudinal_table_keeps_not_resequenced_cells_blank():
    pf = synthetic_file(timeline())
    lon = gx.longitudinal_table(pf, None, CTDNA)
    assert [s["id"] for s in lon["samples"]] == ["ctDNA · month -2", "Tumor sequencing · month 0",
                                                 "ctDNA · month 4"]
    cells = {r["variant"]: [c["state"] for c in r["cells"]] for r in lon["rows"]}
    assert cells["PIK3CA H1047R"] == ["detected", "detected", "detected"]
    # month -2: the ctDNA assay looked and did not find it; month 0: the record's panel is not
    # stated, so the tissue cell is blank, never "absent"
    assert cells["ESR1 D538G"] == ["not detected", "blank", "detected"]
    text = {r["variant"]: [c["text"] for c in r["cells"]] for r in lon["rows"]}
    assert text["ESR1 D538G"][0] == "not detected (below 0.1%)" and text["ESR1 D538G"][1] == ""
    assert text["PIK3CA H1047R"][2] == "detected (0.9%)"
    assert "absent" not in json.dumps(lon["rows"])
    early = gx.longitudinal_table(pf, 5, CTDNA)  # month -1: only the month -2 ctDNA sample
    assert [s["id"] for s in early["samples"]] == ["ctDNA · month -2"]
    assert gx.longitudinal_table(pf, None, None)["notes"][0] == ("ctDNA series: not yet "
                                                                 "available in this record")


def test_longitudinal_table_adds_imported_sequencing_against_each_panel():
    pf = case_file(tcga_case(61))
    imported = RecordTest("Sequencing", 14, "Imported tumor sequencing",
                          "PIK3CA H1047R, ESR1 Y537S", "mutations", g.IMPLEMENTED,
                          {"variants": ["PIK3CA H1047R", "ESR1 Y537S"],
                           "panel": ["PIK3CA", "ESR1"], "vaf": {"ESR1 Y537S": 0.12}})
    pf2 = add_version(pf, [imported], 14, "Imported sequencing", "AB", "10:00")
    lon = gx.longitudinal_table(pf2, None, None, {"PIK3CA H1047R": 0.21})
    cells = {r["variant"]: [c["text"] for c in r["cells"]] for r in lon["rows"]}
    assert cells["PIK3CA H1047R"] == ["detected (21.0%)", "detected"]
    assert cells["ESR1 Y537S"] == ["not detected", "detected (12.0%)"]  # ESR1: in the TCGA panel
    assert cells["PIK3CA E469delinsDK"] == ["detected", "not detected"]  # PIK3CA: in its panel
    assert lon["samples"][1]["kind"] == "imported sequencing"


def test_variants_link_to_the_evolution_views_escape_routes():
    pf = synthetic_file(timeline())
    hs = evolution.hypothesis_set(pf, None)
    links = gx.escape_links("ESR1", hs)
    assert any(x["id"] == "esr1-ai" and x["raised"] for x in links)
    assert all(x["event"] and x["status"] for x in links)
    assert gx.escape_links("PIK3CA", None) == []


def test_search_answers_plain_words_and_says_what_it_cannot_see():
    rows = gx.landscape(CN["cases"]["61"], CN["genes"])
    nodes = gx.pathway_map(["PIK3CA H1047R"], rows, True)
    bur = gx.burden(CN["cases"]["61"], CN)
    amp = gx.search("amplified", rows, nodes, bur, ["PIK3CA H1047R"])
    assert "ERBB2" in amp["genes"] and amp["note"] is None
    assert gx.search("ERBB2", rows, nodes, bur, [])["pathways"] == ["HER2 / RTK"]
    assert gx.search("PI3K pathway", rows, nodes, bur, [])["pathways"] == ["PI3K / AKT / mTOR"]
    hb = gx.search("high burden", rows, nodes, bur, [])
    assert hb["burden"] is bur and (hb["note"] is None) == bur["high"]
    assert "not in the copy-number" in gx.search("lymphocytes", rows, nodes, bur, [])["note"]
    assert "can't answer" in gx.search("amplified", [], nodes, bur, [])["note"]


def test_new_finding_kinds_card_and_exports():
    assert "cn" in FINDING_KINDS and "pathway" in FINDING_KINDS
    pf = case_file(tcga_case(61))
    rows = gx.landscape(CN["cases"]["61"], CN["genes"])
    bur = gx.burden(CN["cases"]["61"], CN)
    nodes = gx.pathway_map([d["variant"] for d in CN["cases"]["61"]["drivers"]], rows, True)
    afs = gx.allele_fractions(CN["cases"]["61"], None)
    lon = gx.longitudinal_table(pf, None, None)
    reviews = {}
    g.add_mark(reviews, finding_key(pf, "cn", "ERBB2"), "ERBB2 copy number: amplification",
               g.AGREE, "ab", "t1")
    g.add_mark(reviews, finding_key(pf, "pathway", "HER2 / RTK"), "pathway HER2 / RTK",
               g.SECOND_LOOK, "", "t2")
    md = gx.report_markdown(pf, rows, bur, afs, nodes, EFFECTS, lon, reviews)
    assert "## Copy-number landscape" in md and "[placeholder]" in md
    assert "| ERBB2 |" in md and "AlphaMissense" in md and "(PMID 23000897)" in md
    assert "- ERBB2 copy number: amplification: agree (ab, t1)" in md
    assert "- pathway HER2 / RTK: second look (no initials, t2)" in md
    out = list(csv_rows(gx.landscape_csv(rows, reviews, pf)))
    assert out[0][0] == "gene" and any(r[0] == "ERBB2" and r[-1].startswith("agree") for r in out)
    found = gx.findings(pf, rows, bur, nodes, afs, EFFECTS)
    assert {f["kind"] for f in found} == {"cn", "burden", "variant", "pathway"}
    assert json.loads(gx.report_json(pf, found, reviews, {}))["review_marks"]
    card = gx.card(CN, EFFECTS, {"receptors": {"HER2": {"cn": {"n": 10, "sensitivity": 0.57,
                                                                "specificity": 0.98}}}})
    assert all(r["source"] and r["tag"] for r in card)
    assert any(r["tag"] == gx.PLACEHOLDER for r in card)
    assert "sensitivity 0.57" in next(r["source"] for r in card
                                      if r["what"].endswith("amplification"))


PAGE = """
import json, sys
sys.path.insert(0, {workbenches!r})
from types import SimpleNamespace
from muffle.workspace import case_file, synthetic_file
import genomics
{body}
"""


def test_genome_sections_render_on_the_shipped_numbers():
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    wbs = str(ROOT / "app" / "workbenches")
    case = tcga_case(61).__dict__
    at = AppTest.from_string(PAGE.format(workbenches=wbs, body=(
        f"genomics.render(case_file(SimpleNamespace(**{case!r})))")), default_timeout=120).run()
    assert not at.exception
    text = " ".join(e.value for k in ("markdown", "caption", "info", "warning", "subheader")
                    for e in getattr(at, k))
    assert "The tumor's genome" in text and "ABSOLUTE purity" in text
    assert "Spot: " in text and "somatic calls" in text and "AlphaMissense" in text
    assert "Rule: detected / not detected only where the sample looked" in text
    assert len(at.tabs) == 4
    tl = str(ROOT / "app" / "timeline_synthetic.json")
    syn = AppTest.from_string(PAGE.format(workbenches=wbs, body=(
        f"tl = json.loads(open({tl!r}, encoding='utf-8').read())\n"
        "genomics.render(synthetic_file(tl), evidence=tl['evidence'])")),
        default_timeout=120).run()
    assert not syn.exception
    text = " ".join(e.value for k in ("markdown", "caption", "info") for e in getattr(syn, k))
    assert "No copy number for this file" in text and "AlphaMissense" in text


def test_the_synthetic_ctdna_series_joins_the_variant_table():
    from muffle.timeline import CTDNA
    pf = synthetic_file(timeline())
    lon = gx.longitudinal_table(pf, None, CTDNA)
    assert len(lon["samples"]) == len(CTDNA["samples"]) + 1  # every ctDNA draw and the biopsy
    tissue = next(n for n, s in enumerate(lon["samples"]) if s["kind"] == "tumor sequencing")
    rows = {r["variant"]: r["cells"] for r in lon["rows"]}
    assert set(rows) == {"PIK3CA H1047R", *CTDNA["variants"]}
    assert rows["DNMT3A R882H"][tissue]["state"] == "blank"  # the biopsy never looked for it
    assert rows["ESR1 D538G"][0]["text"] == "not detected (below 0.1%)"  # month -12, below limit
    assert rows["PIK3CA H1047R"][tissue]["state"] == "detected"
    assert "synthetic" in " ".join(lon["notes"])


def test_the_patient_overview_gets_copy_number_and_burden():
    from muffle.workspace import CARD_KEYS, ITEM_KEYS
    pf = case_file(tcga_case(61))
    cards = gx.overview_cards(pf, CN)
    assert [c["what"] for c in cards] == ["Copy number", "Mutation burden"]
    assert set(cards[0]) == set(CARD_KEYS) and "ERBB2" in cards[0]["text"]
    assert "placeholder" in cards[0]["threshold"] and cards[0]["focus"] == {"gene": "PIK3CA"}
    assert cards[0]["opens"][0] == "Tests"
    items = gx.overview_items(pf, CN)
    erbb2 = next(i for i in items if i["pointer"] == "ERBB2")
    assert set(erbb2) == set(ITEM_KEYS) and erbb2["consequence"] == 2
    assert erbb2["key"] == finding_key(pf, "cn", "ERBB2") and erbb2["focus"] == {"gene": "ERBB2"}
    flagged = case_file(tcga_case(49))  # ploidy 1 by the median rule, 1.58 by ABSOLUTE
    items = gx.overview_items(flagged, CN)
    assert items[0]["pointer"] == "ploidy" and all(i["trust"] == "weak" for i in items[1:])
    assert gx.overview_cards(synthetic_file(timeline()), CN) == []
    summary = g.summary(pf)
    assert [c["what"] for c in summary["cards"]] == ["Key drivers", "Copy number",
                                                     "Mutation burden"]
    assert any(i["pointer"] == "ERBB2" for i in g.queue(pf))  # even without CIViC loaded

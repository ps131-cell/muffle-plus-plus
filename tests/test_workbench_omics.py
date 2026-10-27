"""The expression, methylation and protein workbench's arithmetic, on small synthetic matrices."""

import json

import numpy as np
import pandas as pd

from muffle.workbench import omics


def test_centroid_call_picks_the_nearest_centroid_and_skips_missing_genes():
    rng = np.random.default_rng(0)
    genes = [f"G{i}" for i in range(12)]
    cent = pd.DataFrame(rng.normal(size=(12, 3)), index=genes, columns=["LumA", "Basal", "Her2"])
    x = cent["Basal"] + rng.normal(scale=0.1, size=12)
    x.iloc[:2] = np.nan  # not measured
    call = omics.centroid_call(x, cent)
    assert call["call"] == "Basal" and call["genes"] == 10
    assert list(call["cor"])[0] == "Basal" and call["cor"]["Basal"] > 0.9
    assert call["margin"] == round(call["cor"]["Basal"] - sorted(call["cor"].values())[-2], 3)


def test_set_scores_are_cohort_z_scores_of_the_mean_gene_z():
    rng = np.random.default_rng(1)
    z = pd.DataFrame(rng.normal(size=(50, 6)), columns=list("ABCDEF"))
    z.loc[7, ["A", "B"]] = 5.0  # one tumor high on set {A, B}
    s = omics.set_scores(z, {"ab": ["A", "B", "not measured"], "cd": ("C", "D")})
    assert s["ab"].idxmax() == 7
    assert np.allclose(s.mean(), 0, atol=1e-9) and np.allclose(s.std(ddof=0), 1)


def test_youden_finds_the_separating_cutoff():
    v = [1, 2, 3, 4, 10, 11, 12, 13]
    pos = [False] * 4 + [True] * 4
    cut = omics.youden(v, pos)
    assert cut["cutoff"] == 10 and cut["sensitivity"] == cut["specificity"] == 1.0
    assert cut["auc"] == 1.0 and (cut["positives"], cut["negatives"]) == (4, 4)
    assert omics.youden([1, 1, 2, 2], [True, False, True, False])["auc"] == 0.5  # ties


def test_agreement_share_kappa_and_confusion():
    pred = ["LumA", "LumA", "Basal", "Normal", "LumA"]
    truth = ["LumA", "LumB", "Basal", "LumA", None]  # the last pair has no reference
    a = omics.agreement(pred, truth)
    assert (a["n"], a["agree"], a["share"]) == (4, 2, 0.5)
    assert a["confusion"]["LumA"] == {"Basal": 0, "LumA": 1, "Normal": 1}
    assert -1 <= a["kappa"] < 0.5
    perfect = omics.agreement(["A", "B"], ["A", "B"])
    assert perfect["share"] == 1 and perfect["kappa"] == 1


def test_her2_status_follows_asco_cap():
    assert omics.her2_status("Positive", None) == "Positive"
    assert omics.her2_status("Negative", "Positive") == "Negative"  # IHC 0/1+ stands
    assert omics.her2_status("Equivocal", "Positive") == "Positive"
    assert omics.her2_status("Equivocal", None) is None
    assert omics.her2_status("Indeterminate", "Negative") is None


def test_percentile_interpolates_cohort_quantiles():
    q = list(np.linspace(-2, 2, 11))  # deciles of a cohort from -2 to 2
    assert omics.percentile(0.0, q) == 50
    assert omics.percentile(-1.6, q) == 10
    assert omics.percentile(9, q) == 100 and omics.percentile(-9, q) == 0


CAL = {"ER": {"rna": {"cutoff_pct": 25.3, "auc": 0.96}, "protein": {"cutoff_pct": 28, "auc": 0.96}},
       "HER2": {"rna": {"cutoff_pct": 86, "auc": 0.81}, "protein": {"cutoff_pct": 77, "auc": 0.77}}}


def test_receptor_lines_compare_ihc_rna_copy_number_and_protein():
    rec = {"ER": {"status": "Positive", "ihc": "Positive", "rna": {"pct": 12.0, "high": False},
                  "protein": {"pct": 20.0, "high": False}},
           "HER2": {"status": "Positive", "ihc": "Equivocal", "fish": "Positive",
                    "rna": {"pct": 95.0, "high": True}, "cn": {"copies": 8.0, "ploidy": 3.0}}}
    lines = omics.receptor_lines(rec, CAL)
    by = {(x["receptor"], x["compare"]): x for x in lines}
    er = by[("ER", "IHC vs RNA")]
    assert er["status"] == omics.DISAGREE and "ER IHC positive" in er["text"]
    assert "ESR1 RNA at the 12th percentile, below" in er["text"]
    assert "(25th percentile)" in er["text"]
    assert "observed" in er["evidence"] and "calibrated" in er["evidence"]
    assert by[("ER", "protein vs RNA")]["status"] == omics.AGREE  # both low
    assert by[("ER", "protein vs RNA")]["text"].endswith("ER IHC positive. protein vs RNA: agree.")
    assert er["short"] == "ER IHC positive, ESR1 RNA low (12th percentile)"
    assert "RNA is not protein" in by[("ER", "protein vs RNA")]["check"]
    cn = by[("HER2", "IHC vs copy number")]
    assert cn["status"] == omics.AGREE and "amplified" in cn["text"]
    assert "placeholder" in cn["evidence"]
    assert "in situ hybridization positive" in by[("HER2", "IHC vs RNA")]["text"]
    none = omics.receptor_lines({"ER": {"status": None, "ihc": None,
                                        "rna": {"pct": 80.0, "high": True}}}, CAL)
    assert none[0]["status"] == omics.NO_COMPARISON and "not recorded" in none[0]["text"]


def test_look_here_lists_disagreements_borderline_calls_and_known_failures():
    case = {"pam50": {"call": "Normal", "published": "LumA", "agrees": False, "margin": 0.04}}
    lines = [{"receptor": "ER", "compare": "IHC vs RNA", "short": "x", "status": omics.DISAGREE},
             {"receptor": "PR", "compare": "IHC vs RNA", "short": "y", "status": omics.AGREE}]
    queue = omics.look_here(case, lines, ["rna", "genomic"])
    assert len(queue) == 4 and queue[0] == "ER, IHC vs RNA disagree: x"
    assert "Luminal A" in queue[1] and "borderline" in queue[2] and "Copy number" in queue[3]
    assert omics.look_here(None, [], ["rna"]) == []


def test_search_and_honest_answer():
    items = [{"kind": "feature", "name": "ESR1", "text": "RNA expression"},
             {"kind": "receptor", "name": "ER: IHC vs RNA", "text": "ESR1 ...: disagree, worth"},
             {"kind": "score", "name": "proliferation", "text": "PAM50 proliferation genes"}]
    assert len(omics.search("esr1", items)["hits"]) == 2
    assert [i["kind"] for i in omics.search("disagree", items)["hits"]] == ["receptor"]
    assert omics.search("", items)["hits"] == items
    miss = omics.search("TP53 mutation", items)
    assert miss["hits"] == [] and "genomics workbench" in miss["note"]


def test_exports_carry_this_files_omics_marks_only():
    findings = [{"kind": "feature", "layer": "rna", "name": "ESR1", "value": 1.2,
                 "percentile": 80, "evidence": "observed", "key": "Case 1|omics|rna|ESR1"}]
    reviews = {"Case 1|omics|rna|ESR1": {"what": "ESR1", "mark": "agree", "by": "PS",
                                         "at": "2026-10-20 10:00"},
               "Case 1|lab|ca153|1": {"what": "x", "mark": "agree", "by": "", "at": ""},
               "Case 2|omics|rna|ESR1": {"what": "x", "mark": "agree", "by": "", "at": ""}}
    data = json.loads(omics.report_json("Case 1", findings, reviews, {"data": "TCGA"}))
    assert list(data["review_marks"]) == ["Case 1|omics|rna|ESR1"]
    rows = omics.report_csv(findings, reviews).splitlines()
    assert rows[0].startswith("kind,layer,name") and rows[1].endswith("agree,PS,2026-10-20 10:00")


# --- round 2: protein pathways, promoter methylation, the immune picture ---------------------

def test_signed_scores_subtract_negative_regulators_and_rescale():
    rng = np.random.default_rng(2)
    z = pd.DataFrame(rng.normal(size=(60, 3)), columns=["AKT_pS473", "PTEN", "OTHER"])
    z.loc[3, ["AKT_pS473", "PTEN"]] = [4.0, -4.0]  # phospho-AKT up, PTEN (negative) down
    z.loc[5, ["AKT_pS473", "PTEN"]] = [4.0, 4.0]   # both up: the negative regulator cancels
    s = omics.signed_scores(z, {"PI3K": {"AKT_pS473": 1, "PTEN": -1, "absent": 1},
                                "none": {"absent": 1}})
    assert s["PI3K"].idxmax() == 3 and abs(s.at[5, "PI3K"]) < abs(s.at[3, "PI3K"]) / 2
    assert np.isclose(s["PI3K"].mean(), 0) and np.isclose(s["PI3K"].std(ddof=0), 1)
    assert s["none"].isna().all()  # no member measured: no score, never 0


def test_promoter_probes_core_promoter_transcript_and_index():
    man = pd.DataFrame([
        # BRCA1's core promoter in a shore: kept (island not required of a gene's probes)
        ("cg1", "17", "NBR2;BRCA1", "NR_003108;NM_007294", "TSS200;1stExon", "N_Shore"),
        ("cg2", "17", "BRCA1;NBR2", "NM_007294;NR_003108", "TSS1500;Body", "Island"),  # upstream
        ("cg3", "3", "RASSF1;RASSF1", "NM_007182;NM_170714", "TSS200;Body", "Island"),  # 1A
        ("cg4", "3", "RASSF1;RASSF1", "NM_170714;NM_007182", "TSS200;Body", "Island"),  # 1C
        ("cg5", "X", "XIST", "NR_001564", "TSS200", "Island"),                         # chr X
        ("cg6", "1", "", "", "", "Island"),                                            # no gene
    ], columns=["IlmnID", "CHR", "UCSC_RefGene_Name", "UCSC_RefGene_Accession",
                "UCSC_RefGene_Group", "Relation_to_UCSC_CpG_Island"])
    genes, index = omics.promoter_probes(man, {"BRCA1": None, "RASSF1": "NM_007182",
                                               "GSTP1": None})
    assert genes == {"BRCA1": ["cg1"], "RASSF1": ["cg3"], "GSTP1": []}
    assert index == ["cg2", "cg3", "cg4"]  # autosomal island probes in any promoter group


def test_promoter_beta_is_the_mean_over_measured_probes():
    betas = pd.DataFrame({"cg1": [0.1, np.nan], "cg2": [0.5, 0.7], "cg9": [0.9, 0.9]})
    out = omics.promoter_beta(betas, {"A": ["cg1", "cg2"], "B": ["absent"]})
    assert np.allclose(out["A"], [0.3, 0.7]) and out["B"].isna().all()


def _meth_case(beta: float, rna: float, gene: str = "BRCA1", er: str | None = None) -> dict:
    return {"methylation": {"genes": {gene: [beta, 90.0, 4]}, "index": [0.12, 50.0]},
            "rna_pct": {gene: rna}, "receptors": {"ER": {"status": er}} if er else {}}


def test_methylation_calls_at_the_cutoffs_and_the_rna_beside_them():
    cut, low = omics.METHYLATED, omics.RNA_LOW
    line = omics.methylation_lines(_meth_case(cut, low))[0]  # both at the cutoff: inclusive
    assert line["methylated"] and line["status"] == omics.CONSISTENT
    assert "consistent with silencing" in line["text"] and "the 90th percentile" in line["text"]
    high = omics.methylation_lines(_meth_case(cut + 0.2, low + 30))[0]
    assert high["status"] == omics.NOT_CONSISTENT and "not consistent" in high["text"]
    un = omics.methylation_lines(_meth_case(cut - 0.01, low))[0]
    assert not un["methylated"] and un["status"] == "unmethylated"
    assert "another reason" in un["text"]
    esr1 = omics.methylation_lines(_meth_case(0.6, 10, "ESR1", er="Positive"))[0]
    assert "ER recorded positive by IHC" in esr1["text"]
    # a transcript-specific promoter: the gene-level RNA cannot confirm it
    rassf1 = omics.methylation_lines(_meth_case(0.6, 10, "RASSF1"))[0]
    assert rassf1["status"] == omics.NO_COMPARISON and "RASSF1A with RASSF1C" in rassf1["text"]
    assert omics.methylation_lines({}) == []


def _immune(est: float, cyt: float = 50.0, prot: float | None = None, secs=()) -> dict | None:
    cs = {"estimate": {"immune": [0.0, est], "stromal": [0.0, 50.0]},
          "scores": {"immune": [0.0, cyt]}}
    if prot is not None:
        cs["rppa"] = {"immune": [0.0, prot, 8]}
    return omics.immune_picture(cs, list(secs))


def _section(share, pattern="desert"):
    return {"slide": "TCGA-XX-0000-DX1", "opens": (), "pattern": pattern, "zone": "front band",
            "til_share": share, "head_share": 0.0, "til_model": "m", "nuclei_per_mm2": None}


def test_immune_picture_agrees_disagrees_and_says_what_settles_it():
    hi = omics.IMMUNE_HIGH
    both_high = _immune(hi, prot=hi + 5)
    assert both_high["status"] == omics.AGREE and "Salgado" in both_high["settle"]
    split = _immune(90, cyt=90, secs=[_section(0.01)])  # high RNA, a desert on the slide
    assert split["status"] == omics.DISAGREE and split["crosstest"]  # the cross-test rule fires
    assert "a desert, under 5%" in split["text"] and "second lymphocyte model" in split["text"]
    not_desert = _immune(90, secs=[_section(0.2, "inflamed")])  # not a desert is not inflamed
    assert not_desert["status"] == omics.NO_COMPARISON and not not_desert["crosstest"]
    assert _immune(10, prot=90)["status"] == omics.DISAGREE  # RNA low, protein high
    assert _immune(50)["status"] == omics.NO_COMPARISON
    assert omics.immune_picture({"scores": {}}, []) is None  # no RNA


def test_rppa_rows_list_members_with_signs_and_values():
    cs = {"rppa": {"pathways": {"PI3K/AKT": [1.2, 88.0, 2]},
                   "antibodies": {"AKT_pS473": [1.5, 91.0], "PTEN": [-0.8, 20.0]}}}
    row = omics.rppa_rows(cs, {"rppa": {"left_out": ["GSK3_pS9"]}})[0]
    assert row["map"] == "PI3K / AKT / mTOR" and row["of"] == 9  # one member left out
    assert "+AKT_pS473 z +1.50 (91st)" in row["hover"] and "−PTEN z -0.80 (20th)" in row["hover"]
    assert "+PRAS40_pT246 not measured" in row["hover"]
    assert {m["antibody"]: m["gene"] for m in row["members"]}["PTEN"] == "PTEN"


def test_every_scored_antibody_has_a_gene_and_every_map_name_exists():
    from muffle.workbench.genome import PATHWAYS

    named = {a for p in omics.RPPA_PATHWAYS.values() for a in [*p["members"], *p["also"]]}
    assert named | set(omics.RPPA_IMMUNE) <= set(omics.ANTIBODY_GENES)
    assert {p["map"] for p in omics.RPPA_PATHWAYS.values()} - {None} <= set(PATHWAYS)
    assert all(s in (1, -1) for p in omics.RPPA_PATHWAYS.values() for s in p["members"].values())


def test_search_reads_every_word_and_word_starts():
    items = [{"kind": "pathway_protein", "name": "PI3K/AKT", "text": "PI3K/AKT protein pathway"},
             {"kind": "methylation", "name": "BRCA1", "text": "BRCA1 promoter unmethylated"},
             {"kind": "methylation", "name": "GSTP1", "text": "GSTP1 promoter methylated"},
             {"kind": "immune", "name": "immune picture", "text": "immune picture: agree"}]
    assert [i["name"] for i in omics.search("PI3K pathway", items)["hits"]] == ["PI3K/AKT"]
    assert [i["name"] for i in omics.search("methylated", items)["hits"]] == ["GSTP1"]
    assert [i["kind"] for i in omics.search("immune", items)["hits"]] == ["immune"]


def test_exports_keep_the_new_finding_kinds_marks():
    reviews = {"Case 1|pathway_protein|PI3K/AKT": {"mark": "agree"},
               "Case 1|methylation|BRCA1": {"mark": "second look"},
               "Case 1|variant|PIK3CA H1047R|None": {"mark": "agree"}}
    data = json.loads(omics.report_json("Case 1", [], reviews, {}))
    assert set(data["review_marks"]) == {"Case 1|pathway_protein|PI3K/AKT",
                                         "Case 1|methylation|BRCA1"}


# --- the shipped file ------------------------------------------------------------------------

def test_shipped_round2_scores_are_derived_numbers_with_the_guard():
    data = json.loads(omics.SCORES.read_text(encoding="utf-8"))
    assert data["version2"].startswith("omics-scores 2")
    named = {a for p in omics.RPPA_PATHWAYS.values() for a in [*p["members"], *p["also"]]}
    named |= set(omics.RPPA_IMMUNE)
    with_rppa = with_meth = 0
    for cs in data["cases"].values():
        assert isinstance(cs["log_risk"], float)  # the per-case guard stays
        rp = cs.get("rppa")
        if rp:
            with_rppa += 1
            assert set(rp["pathways"]) <= set(omics.RPPA_PATHWAYS)
            assert set(rp["antibodies"]) <= named  # never the whole array
            assert all(0 <= p <= 100 and 0 < n for _, p, n in rp["pathways"].values())
        m = cs.get("methylation")
        if m:
            with_meth += 1
            assert set(m["genes"]) <= set(omics.METHYLATION_GENES)
            assert all(0 <= b <= 1 and 0 <= p <= 100 for b, p, _ in m["genes"].values())
            assert 0 <= m["index"][0] <= 1
        for s in cs.get("slides", {}).values():
            assert {"pattern", "zones", "method_version"} <= set(s)
    assert with_rppa >= 30 and with_meth >= 20
    mm = data["methylation_markers"]
    assert all(mm["probes"][g] for g in omics.METHYLATION_GENES)
    assert all(mm["normal_median"][c] < omics.NORMAL_MAX for g in omics.METHYLATION_GENES
               for c in mm["probes"][g] if len(mm["probes"][g]) < len(mm["candidates"][g]))
    assert all(len(q) == 21 for q in mm["quantiles"].values())
    v = data["validation"]
    assert v["protein_vs_rna"]["ERALPHA"]["spearman"] > 0.8  # ER-alpha protein tracks ESR1 RNA
    assert set(v["methylation_vs_rna"]) == set(omics.METHYLATION_GENES)
    assert omics.SCORES.stat().st_size < 1_000_000  # light enough for the hosted app


def test_summary_and_queue_carry_the_round2_findings():
    from types import SimpleNamespace

    from muffle.workspace import ITEM_KEYS, case_file

    data = json.loads(omics.SCORES.read_text(encoding="utf-8"))

    def tcga(index, mutations=None, slides=()):
        case = SimpleNamespace(index=index, site="site-1", percentile=60.0, group="medium",
                               age=55.0, stage=None, layers=["clinical", "rna", "protein"],
                               missing=["genomic", "methylation"], mutations=mutations,
                               log_risk=data["cases"][str(index)]["log_risk"])
        return case_file(case, 0.7, slides=slides)

    assert data["cases"]["741"]["rppa"]["pathways"]["PI3K/AKT"][1] >= omics.PATHWAY_HIGH
    pf = tcga(741, mutations=["AKT1 p.E17K"])
    whats = {c["what"] for c in omics.summary(pf)["cards"]}
    assert {"Protein pathways (RPPA)", "Immune picture"} <= whats
    items = [x for x in omics.queue(pf) if x["pointer"] == "PI3K/AKT"]
    assert len(items) == 1 and "AKT1 E17K with high PI3K/AKT" in items[0]["what"]
    assert items[0]["key"] == "Case 741|pathway_protein|PI3K/AKT"
    assert set(items[0]) >= set(ITEM_KEYS) and "placeholder" in items[0]["threshold"]
    assert "clinician review" in items[0]["why"]
    assert not [x for x in omics.queue(tcga(741, mutations=[])) if x["pointer"] == "PI3K/AKT"]
    # a high immune RNA score against a desert section: the picture disagrees
    pf = tcga(1043, slides=["TCGA-PL-A8LZ-DX1", "TCGA-PL-A8LZ-DX2", "TCGA-PL-A8LZ-DX3"])
    card = next(c for c in omics.summary(pf)["cards"] if c["what"] == "Immune picture")
    assert "disagree" in card["text"] and "pathologist" in card["text"]


def test_scores_compare_with_the_cohort_and_outline_the_open_finding():
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    root = Path(__file__).resolve().parents[1]
    at = AppTest.from_string(f"""
import sys
sys.path[:0] = [{str(root / "app")!r}, {str(root / "src")!r}]
import pandas as pd
import streamlit as st
from workbenches.omics import score_bars
st.session_state.setdefault("spot", "k2")
score_bars(pd.DataFrame({{"set": ["e2f targets", "hypoxia"], "z": [1.2, -0.4],
                         "percentile": [88.0, 31.0], "key": ["k1", "k2"]}}), "set", "score", [],
           "spot", "bars", 80)
""", default_timeout=60).run()
    assert not at.exception
    spec = at.get("vega_lite_chart")[0].proto.spec
    assert "cohort z-score" in spec and "middle half" not in spec
    assert 'datum.key == \\"k2\\"' in spec  # the open finding is outlined
    at.toggle(key="bars-cohort").set_value(True).run()
    spec = at.get("vega_lite_chart")[0].proto.spec
    assert not at.exception and "cohort percentile (0 to 100)" in spec
    assert '"type": "rect"' in spec and '"type": "rule"' in spec  # middle half, median

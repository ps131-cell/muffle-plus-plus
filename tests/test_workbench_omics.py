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

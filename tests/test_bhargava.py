"""The Bhargava lab's findings applied (docs/decisions.md, 2026-10-28): the citations as data
(muffle.literature), the ECM3 four-gene score on the omics workbench, tissue by zone and the
border-collagen hypothesis on the slide workbench and in its export, and the Methods page's
evidence categories, EASSI-H lines and planned infrared modules."""

import json
import math
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from muffle import literature
from muffle.report.case_tools import HYPOTHESIS, INFERENCE
from muffle.workbench import invasion, omics
from tests.appfixture import shown

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
ECM3 = json.loads((APP / "omics_ecm3.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------- literature

def test_every_citation_has_a_doi_or_pmid_a_label_and_its_caveat():
    assert {"mittal2018", "tiwari2020", "mittal2019", "schnell2020", "mayerich2015", "lin2024",
            "bhargava2023", "triulzi2013"} <= set(literature.CITATIONS)
    for key, c in literature.CITATIONS.items():
        assert c["doi"].startswith("10.") or c["pmid"].isdigit(), key
        assert c["pmid"].isdigit() and c["doi"].startswith("10."), key  # both, checked on PubMed
        assert c["authors"] and c["title"] and c["journal"] and c["finding"], key
        assert 2000 < c["year"] < 2027, key
        assert c["category"] in [*literature.CATEGORIES, "review"], key
        assert set(c["caveat"]) == {"n", "centres", "external_validation"}, key
    tiwari = literature.CITATIONS["tiwari2020"]["caveat"]
    assert tiwari == {"n": "42 tumors", "centres": "one", "external_validation": "no"}
    assert literature.cite("tiwari2020").startswith("Tiwari et al. 2020, Sci Rep")
    assert "doi:10.1038/s41598-020-62403-2" in literature.cite("tiwari2020")


def test_every_module_has_a_category_and_an_eassi_h_line():
    for key, m in literature.MODULES.items():
        cat = literature.category(key)
        assert cat["category"] in literature.CATEGORIES or cat["category"].startswith("n/a"), key
        assert cat["chip"].startswith("evidence category"), key
        line = literature.eassi_h(key)
        for part in ("Data:", "n:", "split:", "external validation:", "result:"):
            assert part in line, (key, part)
        assert not m["external"].startswith("yes"), key  # nothing here is externally validated
    assert literature.category("risk_model")["chip"] == ("evidence category IV: prognosis or "
                                                         "prediction")
    assert "0.728" in literature.eassi_h("risk_model")
    assert "91.9%" in literature.eassi_h("tissue_head")


def test_the_infrared_modules_are_planned_with_their_reason_and_citations():
    planned = literature.planned_modules()
    assert len(planned) == 3
    for p in planned:
        assert p["status"] == literature.PLANNED and p["reason"] == "no infrared data in this project"
        assert p["citations"] and all("doi:10." in c for c in p["citations"])
    assert all(k in literature.CITATIONS for p in literature.PLANNED_MODULES
               for k in p["citations"])
    assert "neither the laboratory nor the Cancer Center at Illinois" in literature.INDEPENDENCE


# ------------------------------------------------------------------------------------- ECM3

def test_the_ecm3_score_is_the_mean_of_the_measured_genes_z_scores():
    z = pd.DataFrame({"COL1A2": [1.0, -1.0, np.nan], "COL5A2": [0.0, -1.0, np.nan],
                      "SPARC": [2.0, 0.5, np.nan], "LAMA4": [1.0, np.nan, np.nan],
                      "ESR1": [9.0, 9.0, 9.0]}, index=["a", "b", "c"])
    s = omics.ecm3_score(z)
    assert s["a"] == pytest.approx(1.0) and s["b"] == pytest.approx(-0.5)  # LAMA4 missing
    assert math.isnan(s["c"])
    assert omics.ecm3_score(z.drop(columns="LAMA4"))["a"] == pytest.approx(1.0)
    assert omics.ECM3_GENES == ("COL1A2", "COL5A2", "SPARC", "LAMA4")


def test_the_shipped_ecm3_scores_are_derived_numbers_with_the_guard():
    assert ECM3["genes"] == list(omics.ECM3_GENES) == ECM3["measured"]
    scores = json.loads((APP / "omics_scores.json").read_text(encoding="utf-8"))["cases"]
    assert set(ECM3["cases"]) == set(scores)  # the bundled TCGA files
    for idx, rec in ECM3["cases"].items():
        assert set(rec) == {"log_risk", "score", "percentile", "genes"}  # no vector, no cutoff
        assert rec["log_risk"] == pytest.approx(scores[idx]["log_risk"], abs=1e-3)
        assert 0 <= rec["percentile"] <= 100
        assert set(rec["genes"]) <= set(omics.ECM3_GENES)
    assert not any(k in json.dumps(ECM3).lower() for k in ("high", "low", "cutoff"))


def pf_for(index: str):
    rec = ECM3["cases"][index]
    return SimpleNamespace(kind="TCGA-BRCA", id=f"Case {index}",
                           versions=[SimpleNamespace(risk={"log_risk": rec["log_risk"]})])


SYNTHETIC = SimpleNamespace(kind="synthetic", id="SYNTHETIC-001",
                            versions=[SimpleNamespace(risk={"value": 0.1})])


def test_ecm3_card_content_measured_not_measured_and_a_missing_gene(monkeypatch):
    e = omics.ecm3(pf_for("299"))
    assert e["measured"] and e["percentile"] == ECM3["cases"]["299"]["percentile"]
    assert e["evidence"] == INFERENCE and "HR 3.0, 95% CI 1.3–7.0" in e["hypothesis"]
    assert "grade III" in e["hypothesis"] and "never a recommendation" in e["hypothesis"]
    assert "percentile of 1,059 TCGA-BRCA tumors" in e["text"] and not e["missing"]
    syn = omics.ecm3(SYNTHETIC)
    assert not syn["measured"] and "not measured" in syn["text"] and "synthetic" in syn["text"]
    other = pf_for("299")
    other.versions[0].risk = {"log_risk": 9.0}  # another build of the cohort: not shown
    assert not omics.ecm3(other)["measured"]
    data = json.loads(json.dumps(ECM3))
    del data["cases"]["299"]["genes"]["LAMA4"]
    monkeypatch.setattr(omics, "ecm3_data", lambda: data)
    e = omics.ecm3(pf_for("299"))
    assert e["missing"] == ["LAMA4"] and "not measured: LAMA4" in e["text"]


@pytest.mark.parametrize("who", ["299", "926", "SYNTHETIC-001"])
def test_the_ecm3_card_on_the_omics_page(who):
    from streamlit.testing.v1 import AppTest

    if who != "SYNTHETIC-001" and who not in ECM3["cases"]:
        pytest.skip(f"Case {who} has no ECM3 score")
    rec = ECM3["cases"].get(who)
    script = f"""
import sys
from types import SimpleNamespace
sys.path[:0] = [{str(APP)!r}, {str(ROOT / 'src')!r}]
from workbenches import omics as page
pf = SimpleNamespace(kind={'"synthetic"' if rec is None else '"TCGA-BRCA"'},
                     id={("SYNTHETIC-001" if rec is None else f"Case {who}")!r},
                     versions=[SimpleNamespace(risk={({"value": 0.1} if rec is None else
                                                      {"log_risk": rec["log_risk"]})!r})])
page.ecm3_section(pf)
"""
    at = AppTest.from_string(script, default_timeout=60).run()
    assert not at.exception, at.exception
    text = shown(at)
    assert HYPOTHESIS in text and "Triulzi" in text and "COL1A2" in text
    if rec is None:
        assert "not measured" in text and "synthetic" in text
        assert not at.metric
    else:
        assert at.metric[0].label == "ECM3 score, cohort percentile"
        assert "high" not in at.metric[0].value.lower()  # no cutoff
        assert list(at.dataframe[0].value["Gene"]) == list(omics.ECM3_GENES)


# ------------------------------------------------------------------------------ the slides

def test_tissue_by_zone_shares_the_usable_tiles_per_zone():
    t = pd.DataFrame({
        "zone": ["core"] * 4 + ["front band"] * 4 + ["peritumoral"] * 2,
        "label": ["tumor", "tumor", "stroma", "necrosis", "tumor", "stroma", "stroma",
                  "lymphocytes", "fat", "dcis"],
        "qc": [invasion.QC_OK] * 9 + ["pen ink"]})
    z = invasion.tissue_by_zone(t)
    assert z["core"]["tiles"] == 4 and z["core"]["shares"]["tumor"] == 0.5
    assert z["front band"]["shares"]["stroma"] == 0.5
    assert z["peritumoral"]["tiles"] == 1 and z["peritumoral"]["shares"]["fat"] == 1.0  # QC
    for v in z.values():
        assert sum(v["shares"].values()) + v["other"] == pytest.approx(1.0)
    empty = invasion.tissue_by_zone(t[t["zone"] != "core"])
    assert empty["core"] == {"tiles": 0, "shares": None, "other": None}
    assert "Mittal et al. 2019" in invasion.ZONE_PRECEDENT
    assert "42-tumor, single-centre" in invasion.TSR_ECM3_HYPOTHESIS
    assert "only the H&E stroma share is measured" in invasion.TSR_ECM3_HYPOTHESIS


RESULTS = APP / "workbenches" / "slides_results"
CASES = json.loads((RESULTS / "cases.json").read_text()) if (RESULTS / "cases.json").exists() \
    else {}


@pytest.mark.parametrize("idx", ["299", "926"])
def test_the_slide_page_and_its_export_show_tissue_by_zone_and_the_hypothesis(idx):
    from streamlit.testing.v1 import AppTest

    from muffle.workbench import slide_export
    from tests.test_slide_map import PAGE, section

    if idx not in CASES:
        pytest.skip(f"Case {idx} is not shipped")
    at = AppTest.from_string(PAGE.format(app=str(APP), src=str(ROOT / "src"), idx=idx,
                                         slides=CASES[idx]), default_timeout=240).run()
    assert not at.exception, at.exception
    assert any(e.label.startswith("Tissue by zone") for e in at.expander)
    text = " ".join(e.value for e in [*at.markdown, *at.caption])
    assert invasion.TSR_ECM3_HYPOTHESIS in text and "Mittal et al. 2019" in text
    meta, res, _, _ = section(CASES[idx][0])
    md = slide_export.report_markdown(f"Case {idx}", meta["slide"], meta, res, marks={})
    assert "## Tissue by zone (model inference)" in md
    assert "**Stroma and ECM3 (hypothesis).**" in md and "Tiwari et al. 2020" in md


# ------------------------------------------------------------------------------- Methods

def test_the_methods_page_carries_categories_eassi_h_and_the_planned_block(app):
    at = app.new().run()
    pages = {i.get("url_pathname"): h for h, i in at._registered_pages.items()}
    at._page_hash = pages["methods"]
    at.run()
    assert not at.exception
    text = shown(at)
    assert "Planned: infrared chemical imaging" in [s.value for s in at.subheader]
    for module in ("risk_model", "tissue_head", "nuclei", "til_second", "invasion", "pam50",
                   "ecm3", "radiology", "documents"):
        assert literature.eassi_h(module) in text, module
    assert "evidence category IV: prognosis or prediction" in text
    assert literature.INDEPENDENCE in text
    for p in literature.planned_modules():
        assert p["name"] in text

import pandas as pd
import pytest

from muffle.report import civic
from muffle.report.case_tools import observed_facts
from muffle.report.nemotron import run_case_agent
from tests.test_agent import make_tools

COLUMNS = ["molecular_profile", "disease", "therapies", "evidence_type", "evidence_direction",
           "evidence_level", "significance", "citation", "rating", "evidence_status",
           "evidence_civic_url"]
ROWS = [
    ["PIK3CA H1047R", "Breast Cancer", "Alpelisib", "Predictive", "Supports", "D",
     "Sensitivity/Response", "Smith, 2020", "3", "accepted", "https://civicdb.org/evidence/1"],
    ["PIK3CA Mutation", "Her2-receptor Negative Breast Cancer", "Everolimus", "Predictive",
     "Supports", "C", "Sensitivity/Response", "Lee, 2018", "4", "accepted",
     "https://civicdb.org/evidence/2"],
    ["PIK3CA Mutation", "Breast Cancer", "Trastuzumab", "Predictive", "Supports", "B",
     "Resistance", "Kim, 2016", "2", "accepted", "https://civicdb.org/evidence/3"],
    ["PIK3CA H1047R", "Colorectal Cancer", "Cetuximab", "Predictive", "Supports", "B",
     "Resistance", "Ng, 2019", "3", "accepted", "https://civicdb.org/evidence/4"],
    ["PIK3CA H1047R", "Breast Cancer", "", "Prognostic", "Supports", "B", "Poor Outcome",
     "Ox, 2017", "3", "accepted", "https://civicdb.org/evidence/5"],
    ["PIK3CA H1047R OR PIK3CA H1047Y OR PIK3CA H1047L", "Breast Cancer", "Fulvestrant,Alpelisib",
     "Predictive", "Supports", "A", "Sensitivity/Response", "Andre, 2019", "5", "accepted",
     "https://civicdb.org/evidence/6"],
    ["PIK3CA H1047R AND PTEN Loss", "Breast Cancer", "Nothing", "Predictive", "Supports", "A",
     "Sensitivity/Response", "Co, 2021", "5", "accepted", "https://civicdb.org/evidence/7"],
    ["PIK3CA Mutation", "Breast Cancer", "Alpelisib", "Predictive", "Supports", "A",
     "Sensitivity/Response", "Juric, 2019", "3", "accepted", "https://civicdb.org/evidence/8"],
    ["PIK3CA H1047R", "Breast Cancer", "Everolimus", "Predictive", "Supports", "C",
     "Sensitivity/Response", "Sun, 2016", "4", "accepted", "https://civicdb.org/evidence/9"],
]


@pytest.fixture
def table(tmp_path):
    path = tmp_path / "civic.tsv"
    pd.DataFrame(ROWS, columns=COLUMNS).to_csv(path, sep="\t", index=False)
    return civic.load_table(str(path), download=False)


def test_evidence_ranks_by_level_then_rating_then_specificity(table):
    items = civic.evidence("PIK3CA", "p.H1047R", "breast", k=10, table=table)
    # A (compound, rating 5) > A (gene, 3) > B (gene) > C (exact, 4) > C (gene, 4) > D (exact)
    assert [i["url"][-1] for i in items] == ["6", "8", "3", "9", "2", "1"]
    assert items[0]["match"] == "this variant (the profile also covers H1047Y, H1047L)"
    assert items[1]["match"] == "any mutation in the gene" and items[3]["match"] == "this variant"
    assert items[1]["level_meaning"] == "validated association"
    assert "7" not in [i["url"][-1] for i in items]  # an AND profile never matches
    assert all("Colorectal" not in i["disease"] for i in items)  # other cancers excluded
    assert set(items[0]) == {"molecular_profile", "match", "therapies", "evidence_level",
                             "level_meaning", "significance", "direction", "disease",
                             "citation", "url"}
    # the k cut happens after ranking, so the level-A items survive a small k
    top2 = civic.evidence("PIK3CA", "H1047R", table=table, k=2)
    assert [i["url"][-1] for i in top2] == ["6", "8"]
    assert civic.evidence("PIK3CA", "H1047Y", table=table, k=1)[0]["url"][-1] == "6"
    assert civic.evidence("ESR1", "Y537S", table=table) == []
    assert civic.load_table("/nonexistent/civic.tsv", download=False) is None


def test_agent_reports_mutations_as_observed_and_civic_as_hypothesis(table, monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    tools = make_tools()
    tools.observed = observed_facts("II", 57.0, ["PIK3CA p.H1047R"])
    tools.evidence = lambda gene, change, cancer: civic.evidence(gene, change, cancer,
                                                                 table=table)
    assert tools.observed_findings()["sequenced_driver_mutations"] == ["PIK3CA H1047R"]
    assert "treatment_evidence" in {s["function"]["name"] for s in tools.specs()}
    r = tools.treatment_evidence()
    assert r["evidence_type"] == "hypothesis" and "clinician review" in r["use"]
    assert r["variants"][0]["civic_items"][0]["therapies"] == "Fulvestrant,Alpelisib"
    text = run_case_agent(tools).text
    assert "[Observed] Driver mutations: PIK3CA H1047R" in text
    assert "[Hypothesis] CIViC, level A" in text and "https://civicdb.org/evidence/6" in text

    unsequenced = make_tools()
    unsequenced.observed = observed_facts("II", 57.0, None)
    unsequenced.evidence = tools.evidence
    assert unsequenced.observed_findings()["sequenced_driver_mutations"] == "not sequenced"
    assert "treatment_evidence" not in {s["function"]["name"] for s in unsequenced.specs()}

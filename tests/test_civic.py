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
]


@pytest.fixture
def table(tmp_path):
    path = tmp_path / "civic.tsv"
    pd.DataFrame(ROWS, columns=COLUMNS).to_csv(path, sep="\t", index=False)
    return civic.load_table(str(path), download=False)


def test_evidence_exact_variant_first_then_gene_level_by_level(table):
    items = civic.evidence("PIK3CA", "p.H1047R", "breast", k=5, table=table)
    assert [i["url"][-1] for i in items] == ["1", "3", "2"]  # exact, then B before C
    assert items[0]["match"] == "this variant" and items[1]["match"] == "any mutation in the gene"
    assert items[1]["level_meaning"] == "clinical evidence"
    assert all("Colorectal" not in i["disease"] for i in items)  # other cancers excluded
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
    assert r["variants"][0]["civic_items"][0]["therapies"] == "Alpelisib"
    text = run_case_agent(tools).text
    assert "[Observed] Driver mutations: PIK3CA H1047R" in text
    assert "[Hypothesis] CIViC, level D" in text and "https://civicdb.org/evidence/1" in text

    unsequenced = make_tools()
    unsequenced.observed = observed_facts("II", 57.0, None)
    unsequenced.evidence = tools.evidence
    assert unsequenced.observed_findings()["sequenced_driver_mutations"] == "not sequenced"
    assert "treatment_evidence" not in {s["function"]["name"] for s in unsequenced.specs()}

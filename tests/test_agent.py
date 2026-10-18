"""Nemotron case agent against a fake OpenAI-style client (no network)."""

import copy
import json
import re
from types import SimpleNamespace

import pytest
import torch

from muffle.models import MuffleNet
from muffle.report import nemotron
from muffle.report.case_tools import CaseTools
from muffle.report.nemotron import MAX_TOKENS, WRITER_MAX_TOKENS, run_case_agent
from tests.conftest import SMALL_DIMS


class FakeClient:
    """Mimics ``client.chat.completions.create``; each script step is a reply or a function of
    the request kwargs returning one (or raising)."""

    def __init__(self, *script):
        self.script, self.calls = list(script), []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def _create(self, **kw):
        self.calls.append(copy.deepcopy(kw))
        step = self.script.pop(0) if len(self.script) > 1 else self.script[0]
        return step(kw) if callable(step) else step


def reply(content=None, calls=(), tokens=100, finish_reason="stop"):
    tool_calls = [SimpleNamespace(id=f"call_{name}_{i}", type="function",
                                  function=SimpleNamespace(name=name, arguments=json.dumps(args)))
                  for i, (name, args) in enumerate(calls)]
    msg = SimpleNamespace(content=content, tool_calls=tool_calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason=finish_reason)],
                           usage=SimpleNamespace(total_tokens=tokens))


def make_tools(names=True, search=None, missing=("protein",)):
    torch.manual_seed(0)
    model = MuffleNet(SMALL_DIMS, hidden=16, latent=4, head_hidden=4)
    cohort_x = {m: torch.randn(50, d) for m, d in SMALL_DIMS.items()}
    with torch.no_grad():
        risks = model(cohort_x, torch.ones(50, len(SMALL_DIMS))).numpy()
    x = {m: torch.randn(1, d) for m, d in SMALL_DIMS.items()}
    mask = torch.ones(1, len(SMALL_DIMS))
    for m in missing:
        mask[0, list(SMALL_DIMS).index(m)] = 0
    feature_names = {m: [f"{m.upper()}G{i}" for i in range(d)] for m, d in SMALL_DIMS.items()}
    return CaseTools(model, x, mask, risks, "breast", feature_names if names else None, 0.71,
                     search)


def test_tool_call_round_trip():
    searched = []

    def search(genes, cancer, topic, k):
        searched.append((genes, cancer, topic))
        return [{"title": "A study", "url": "https://example.org/a", "snippet": "survival"}]

    def search_top_genes(kw):  # round 3: search the genes top_features returned
        feats = json.loads(kw["messages"][-1]["content"])["features"]
        return reply(calls=[("search_literature", {"genes": [f["name"] for f in feats[:2]]})])

    tools = make_tools(search=search)
    client = FakeClient(
        reply(calls=[("predict_risk", {}), ("modality_contributions", {})]),
        reply(calls=[("top_features", {"modality": "rna", "k": 3})]),
        search_top_genes,
        reply("DONE"),
        reply("<think>plan</think>**Summary** high risk.\n\n**Literature** https://example.org/a"),
    )
    report = run_case_agent(tools, client=client, model="nvidia/test", writer="nvidia/writer")

    assert report.mode == "agent" and report.model == "nvidia/test"
    assert report.writer == "nvidia/writer" and not report.issues and not report.revised
    assert report.text.startswith("**Summary**") and "<think>" not in report.text
    assert [c.name for c in report.trace] == ["predict_risk", "modality_contributions",
                                              "top_features", "search_literature"]
    assert [c.round for c in report.trace] == [1, 1, 2, 3]
    assert report.tokens == 500 and len(client.calls) == 5
    assert all("error" not in c.result for c in report.trace)
    assert report.trace[0].result["risk_group"] in {"low", "medium", "high"}
    assert "protein" not in report.trace[1].result["log_risk_added_by_layer"]
    assert len(report.trace[2].result["features"]) == 3
    assert searched and searched[0][1:] == ("breast", "prognosis")

    planner, writer = client.calls[:-1], client.calls[-1]
    for kw in planner:
        assert kw["model"] == "nvidia/test"
        assert kw["max_tokens"] <= MAX_TOKENS and kw["tool_choice"] == "auto"
        assert {t["function"]["name"] for t in kw["tools"]} == {
            "predict_risk", "modality_contributions", "top_features", "search_literature"}
    # the writer gets every tool output, without tools and without the tools' reading notes
    assert writer["model"] == "nvidia/writer" and "tools" not in writer
    assert writer["max_tokens"] == WRITER_MAX_TOKENS
    evidence = writer["messages"][1]["content"]
    assert "https://example.org/a" in evidence and "cohort_percentile" in evidence
    assert '"note"' not in evidence and "not an omic layer" in evidence
    assert '"log_risk":' not in evidence and "cohort_median_log_risk" not in evidence
    # every tool call is answered with its id, in order
    final = planner[-1]["messages"]
    asked = [c["id"] for m in final if m["role"] == "assistant" for c in m["tool_calls"]]
    answered = [m["tool_call_id"] for m in final if m["role"] == "tool"]
    assert asked == answered and len(answered) == 4
    # only derived, rounded numbers leave the machine: raw omics floats never appear
    payload = json.dumps([kw["messages"] for kw in client.calls])
    assert not re.findall(r"\d\.\d{5,}", payload)
    for v in tools.x["rna"][0, :5].tolist():
        assert repr(v) not in payload


def test_tool_rounds_are_capped():
    client = FakeClient(lambda kw: reply("final note") if "tools" not in kw
                        else reply(calls=[("predict_risk", {})]))
    report = run_case_agent(make_tools(), client=client, max_rounds=2)
    assert len(client.calls) == 3 and "tools" not in client.calls[-1]
    assert report.text == "final note" and len(report.trace) == 2


def test_planner_without_risk_gets_the_fixed_plan():
    client = FakeClient(reply("DONE"), reply("**Summary** note"))
    report = run_case_agent(make_tools(), client=client)
    assert [c.name for c in report.trace] == ["predict_risk", "modality_contributions",
                                              "top_features"]
    assert report.mode == "agent" and "fixed tool sequence" in report.notes[0]


def test_writer_failure_falls_back_to_the_planner_model():
    def writer_down(kw):
        if kw["model"] == "nvidia/writer":
            raise ApiError(404)
        return reply("**Summary** written by the planner model")

    client = FakeClient(reply(calls=[("predict_risk", {})]), reply("DONE"), writer_down)
    report = run_case_agent(make_tools(), client=client, model="nvidia/test",
                            writer="nvidia/writer")
    assert report.mode == "agent" and report.writer == "nvidia/test"
    assert report.text.startswith("**Summary** written by the planner")
    assert report.notes == ["writer nvidia/writer: Token Factory unavailable (HTTP 404)"]


def test_planner_is_reminded_once_to_search():
    def search(genes, cancer, topic, k):
        return [{"gene": genes[0], "title": "t", "url": "https://example.org/a", "snippet": ""}]

    def search_first_gene(kw):
        assert kw["messages"][-1]["content"] == nemotron.SEARCH_NUDGE
        feats = json.loads(kw["messages"][-3]["content"])["features"]
        return reply(calls=[("search_literature", {"genes": [feats[0]["name"]]})])

    client = FakeClient(
        reply(calls=[("predict_risk", {}), ("modality_contributions", {})]),
        reply(calls=[("top_features", {"modality": "rna", "k": 2})]),
        reply("DONE"), search_first_gene, reply("DONE"), reply("**Summary** note"))
    report = run_case_agent(make_tools(search=search), client=client)
    assert [c.name for c in report.trace][-1] == "search_literature"
    assert len(client.calls) == 6  # 5 planner turns (one reminder) + writer
    # without a search backend there is no reminder
    client = FakeClient(reply(calls=[("predict_risk", {})]), reply("DONE"), reply("note"))
    run_case_agent(make_tools(), client=client)
    assert len(client.calls) == 3


def test_cut_off_note_falls_back_to_the_planner_model():
    def writer(kw):
        if kw["model"] == "nvidia/writer":
            return reply("**Summary** half a no", finish_reason="length")
        return reply("**Summary** whole note")

    client = FakeClient(reply(calls=[("predict_risk", {})]), reply("DONE"), writer)
    report = run_case_agent(make_tools(), client=client, model="nvidia/test",
                            writer="nvidia/writer")
    assert report.text == "**Summary** whole note" and report.writer == "nvidia/test"
    assert "cut off" in report.notes[0]


def test_grounding_check_asks_for_one_rewrite():
    invented = "**Summary** 99th percentile; see BRCA1 and https://made.up/paper."
    client = FakeClient(reply(calls=[("predict_risk", {})]), reply("DONE"), reply(invented),
                        reply("**Summary** the tools' numbers only."))
    report = run_case_agent(make_tools(), client=client)
    assert report.revised and report.issues == [] and "tools' numbers" in report.text
    fix = client.calls[-1]["messages"][-1]["content"]
    assert "99th" in fix and "BRCA1" in fix and "https://made.up/paper" in fix


def test_unhelpful_rewrite_keeps_the_note_and_its_issues():
    invented = "**Summary** risk 0.987, gene TP53."
    client = FakeClient(reply(calls=[("predict_risk", {})]), reply("DONE"), reply(invented))
    report = run_case_agent(make_tools(), client=client)
    assert not report.revised and report.text == invented
    assert {i["text"] for i in report.issues} == {"0.987", "TP53"}
    assert len(client.calls) == 4  # planner x2, writer, one rewrite


def test_rejected_tool_calling_falls_back_to_fixed_plan():
    class Rejected(Exception):
        status_code = 400

    def reject(kw):
        raise Rejected("tools not supported")

    client = FakeClient(reject, reply("one-shot summary"))
    report = run_case_agent(make_tools(names=False), client=client)
    assert report.mode == "fixed plan" and report.text == "one-shot summary"
    assert "tools" not in client.calls[1]
    assert [c.name for c in report.trace] == ["predict_risk", "modality_contributions",
                                              "top_features"]


def test_offline_fallback_without_key(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    monkeypatch.setattr(nemotron, "make_client", lambda: pytest.fail("no client offline"))
    search = lambda *a: pytest.fail("no literature search offline")  # noqa: E731
    report = run_case_agent(make_tools(search=search))
    assert report.mode == "offline" and report.tokens == 0
    assert "percentile" in report.text and "NEBIUS_API_KEY" in report.text
    assert [c.name for c in report.trace] == ["predict_risk", "modality_contributions",
                                              "top_features"]


def test_bad_tool_calls_return_errors():
    tools = make_tools(search=lambda *a: pytest.fail("search must not run"))
    assert "error" in tools.call("rm_rf", {})
    assert "error" in tools.call("top_features", {"modality": "protein"})  # missing layer
    assert "error" in tools.call("top_features", "{not json")
    assert "error" in tools.call("search_literature", {"genes": ["TP53"]})  # not from tools
    # literature search is only offered with real gene names and a search backend
    assert "search_literature" not in {s["function"]["name"] for s in make_tools().specs()}
    names = {s["function"]["name"] for s in make_tools(names=False, search=print).specs()}
    assert "search_literature" not in names


def test_predict_risk_points_to_percentile_not_sign():
    r = make_tools().predict_risk()
    assert "cohort_median_log_risk" in r and "not by the sign" in r["note"]
    assert {"log_risk", "cohort_median_log_risk"} <= nemotron.WRITER_DROPS


def test_zero_score_features_are_dropped_and_not_searched():
    tools = make_tools(search=lambda *a: pytest.fail("no search without features"))
    tools.x = {m: torch.zeros_like(v) for m, v in tools.x.items()}  # gradient x input = 0
    r = tools.top_features("rna", 5)
    assert r["features"] == [] and "name no features" in r["note"]
    trace = nemotron.fixed_plan(tools)
    assert [c.name for c in trace] == ["predict_risk", "modality_contributions", "top_features"]


class ApiError(Exception):
    def __init__(self, status_code=None):
        super().__init__("Error code: %s - {'detail': '...'}" % status_code)
        self.status_code = status_code


def fail(error):
    def step(kw):
        raise error
    return step


def test_api_errors_fall_back_offline():
    report = run_case_agent(make_tools(), client=FakeClient(fail(ApiError(402))))
    assert report.mode == "offline" and report.notes == [
        "Token Factory unavailable (HTTP 402, out of credit)"]
    assert "out of credit" in report.text and "percentile" in report.text


def test_error_mid_run_keeps_tokens_and_goes_offline():
    client = FakeClient(reply(calls=[("predict_risk", {})], tokens=120), fail(TimeoutError()))
    report = run_case_agent(make_tools(), client=client)
    assert report.mode == "offline" and report.tokens == 120
    assert report.notes == ["Token Factory unavailable (TimeoutError)"]


def test_failed_summary_after_rejected_tools_goes_offline():
    client = FakeClient(fail(ApiError(400)), fail(ApiError(503)))
    report = run_case_agent(make_tools(), client=client)
    assert report.mode == "offline" and "HTTP 503" in report.notes[0]


def test_tavily_search_keeps_results_that_name_the_gene(monkeypatch):
    import tavily

    queries = []

    class FakeTavily:
        def __init__(self, api_key):
            assert api_key == "test-key"

        def search(self, query, max_results, include_domains=None):
            queries.append((query, include_domains))
            gene = query.split('"')[1]
            return {"results": [
                {"title": f"{gene} and survival", "url": f"https://pubmed.org/{gene}",
                 "content": "breast cancer " + "x" * 400},
                {"title": f"{gene} in coronary artery disease", "url": f"https://heart.org/{gene}",
                 "content": "atherosclerosis"},
                {"title": "Breast cancer survival rates", "url": "https://generic.org",
                 "content": "general statistics"},
                {"title": "Protocol", "url": f"https://cdn.clinicaltrials.gov/large-docs/{gene}/"
                 f"NCT0274361{len(gene)}/Prot_SAP_000.pdf",
                 "content": f"targets {gene} in breast tumor cells"},
            ]}

    monkeypatch.setenv("TAVILY_API_KEY", "test-key")
    monkeypatch.setattr(tavily, "TavilyClient", FakeTavily)
    res = nemotron.tavily_search(["GATA3", "ESR1", "PRAME", "TP53"], "breast", "prognosis", 10)
    assert len(queries) == nemotron.SEARCH_QUERIES_PER_REPORT  # TP53 not queried
    assert all("generic" not in r["url"] and "heart" not in r["url"] for r in res)
    assert [r["gene"] for r in res] == ["GATA3", "GATA3", "ESR1", "ESR1", "PRAME", "PRAME"]
    assert {r["url"] for r in res if r["gene"] == "GATA3"} == {
        "https://pubmed.org/GATA3", "https://cdn.clinicaltrials.gov/large-docs/GATA3/"
        "NCT02743615/Prot_SAP_000.pdf"}
    assert all(len(r["snippet"]) <= 300 for r in res)

    queries.clear()
    trials = nemotron.tavily_search(["PRAME"], "breast", "clinical_trials", 5)
    assert queries == [('"PRAME" breast cancer', ["clinicaltrials.gov"])]
    assert trials[1]["url"] == "https://clinicaltrials.gov/study/NCT02743615"
    assert trials[1]["title"].startswith("NCT02743615: ")


def test_tavily_search_prefers_this_cancer_and_drops_duplicate_papers(monkeypatch):
    import tavily

    class FakeTavily:
        def __init__(self, api_key):
            pass

        def search(self, query, max_results, include_domains=None):
            return {"results": [
                {"title": "VAV3 oncogene is a poor prognostic factor in breast cancer patients",
                 "url": "https://pmc.org/1", "content": "VAV3 ..."},
                {"title": "(PDF) VAV3 oncogene is a poor prognostic factor in breast... : Onc Lett",
                 "url": "https://ovid.com/2", "content": "VAV3 in breast cancer"},
                {"title": "VAV3 in esophageal cancer", "url": "https://pmc.org/3",
                 "content": "VAV3 tumour stages"},
            ]}

    monkeypatch.setenv("TAVILY_API_KEY", "k")
    monkeypatch.setattr(tavily, "TavilyClient", FakeTavily)
    assert [r["url"] for r in nemotron.tavily_search(["VAV3"], "breast")] == ["https://pmc.org/1"]


def test_title_key_and_gene_match():
    key = nemotron._title_key
    assert key("Frontiers | PIGR predicts good clinical outcomes and plays a tumor sup...") == \
        key("PIGR predicts good clinical outcomes and plays a tumor suppressor role")
    assert key("(PDF) ELOVL2: a novel tumor suppressor attenuating tamoxifen resistance ...") == \
        key("a novel tumor suppressor attenuating tamoxifen resistance in breast cancer")
    assert nemotron._names_gene("VAV3", "Vav3 oncogene in breast cancer")
    assert not nemotron._names_gene("CAMP", "cAMP signalling in breast cancer")
    assert not nemotron._names_gene("CAMP", "18. McCabe A, Camp RL, Rimm DL")
    assert nemotron._names_gene("PIGR", "PIGR predicts good clinical outcomes")
    assert nemotron._names_gene("ESR1", "ESR1-positive breast tumours")
    assert not nemotron._names_gene("ESR1", "ESR10 and pESR1")  # whole symbols only


def test_clinical_features_cannot_be_searched():
    tools = make_tools(search=lambda *a: pytest.fail("clinical fields are not genes"))
    feats = tools.top_features("clinical", 3)["features"]
    assert feats
    r = tools.call("search_literature", {"genes": [feats[0]["name"]]})
    assert "error" in r and "not returned yet" in r["error"]


def test_empty_search_says_there_is_nothing_to_cite():
    tools = make_tools(search=lambda *a: [])
    gene = tools.top_features("rna", 1)["features"][0]["name"]
    r = tools.search_literature([gene])
    assert r["results"] == [] and "nothing to cite" in r["note"]

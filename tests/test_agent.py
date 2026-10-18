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
from muffle.report.nemotron import MAX_TOKENS, run_case_agent
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


def reply(content=None, calls=(), tokens=100):
    tool_calls = [SimpleNamespace(id=f"call_{name}_{i}", type="function",
                                  function=SimpleNamespace(name=name, arguments=json.dumps(args)))
                  for i, (name, args) in enumerate(calls)]
    msg = SimpleNamespace(content=content, tool_calls=tool_calls or None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
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
        reply("<think>plan</think>**Summary** high risk.\n\n**Literature** https://example.org/a"),
    )
    report = run_case_agent(tools, client=client, model="nvidia/test")

    assert report.mode == "agent" and report.model == "nvidia/test"
    assert report.text.startswith("**Summary**") and "<think>" not in report.text
    assert [c.name for c in report.trace] == ["predict_risk", "modality_contributions",
                                              "top_features", "search_literature"]
    assert [c.round for c in report.trace] == [1, 1, 2, 3]
    assert report.tokens == 400 and len(client.calls) == 4
    assert all("error" not in c.result for c in report.trace)
    assert report.trace[0].result["risk_group"] in {"low", "medium", "high"}
    assert "protein" not in report.trace[1].result["log_risk_added_by_layer"]
    assert len(report.trace[2].result["features"]) == 3
    assert searched and searched[0][1:] == ("breast", "prognosis")

    for kw in client.calls:
        assert kw["max_tokens"] <= MAX_TOKENS and kw["tool_choice"] == "auto"
        assert {t["function"]["name"] for t in kw["tools"]} == {
            "predict_risk", "modality_contributions", "top_features", "search_literature"}
    # every tool call is answered with its id, in order
    final = client.calls[-1]["messages"]
    asked = [c["id"] for m in final if m["role"] == "assistant" for c in m["tool_calls"]]
    answered = [m["tool_call_id"] for m in final if m["role"] == "tool"]
    assert asked == answered and len(answered) == 4
    # only derived, rounded numbers leave the machine: raw omics floats never appear
    payload = json.dumps([kw["messages"] for kw in client.calls])
    assert not re.findall(r"\d\.\d{5,}", payload)
    for v in tools.x["rna"][0, :5].tolist():
        assert repr(v) not in payload


def test_tool_rounds_are_capped():
    client = FakeClient(lambda kw: reply("final note") if kw["tool_choice"] == "none"
                        else reply(calls=[("predict_risk", {})]))
    report = run_case_agent(make_tools(), client=client, max_rounds=2)
    assert len(client.calls) == 3 and client.calls[-1]["tool_choice"] == "none"
    assert report.text == "final note" and len(report.trace) == 2


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
    assert "sign of log_risk" in nemotron.AGENT_SYSTEM


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

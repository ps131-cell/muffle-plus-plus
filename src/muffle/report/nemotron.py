"""Tumor-board case agent: NVIDIA Nemotron on Nebius Token Factory, calling our own tools.

The federated model produces the numbers; Nemotron decides which of them to look at. It gets the
case header (cancer type, which data layers exist), calls tools from ``case_tools`` — risk and
percentile, per-layer contributions, top features, and Tavily literature/trial search when gene
names are known — then writes a cautious summary citing only those tool outputs. Tool rounds and
tokens are capped per report (free hackathon credits). Only derived numbers and gene names are
sent, never raw omics.

Without NEBIUS_API_KEY the same tools run in a fixed order and the offline template is returned,
so tests and the demo work with no network.

Env vars: NEBIUS_API_KEY (required for live calls), NEMOTRON_MODEL, TAVILY_API_KEY (optional).
List available model ids with:  python -m muffle.report.nemotron --list-models
One live case from a checkpoint: python -m muffle.report.nemotron --agent --patient 0
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, field

from dotenv import load_dotenv

from muffle.report.case_tools import CaseTools, parse_arguments

load_dotenv()  # repo-root .env (git-ignored); real environment variables take precedence

TOKEN_FACTORY_URL = os.getenv("TOKEN_FACTORY_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
DEFAULT_MODEL = os.getenv("NEMOTRON_MODEL", "nvidia/Nemotron-3-Nano")  # check --list-models

MAX_TOOL_ROUNDS = 4       # model turns that may call tools; one more turn writes the report
MAX_CALLS_PER_ROUND = 4   # extra parallel calls in one turn are dropped
MAX_TOKENS = 900          # per completion

SYSTEM = (
    "You are an oncology research assistant summarizing output from a federated survival model "
    "for a tumor board. Be precise and cautious: this is a research prototype, not a diagnosis. "
    "Explain the risk estimate, which data layers drove it, and what would change confidence. "
    "Never invent patient details. Use short sections: Summary, Drivers, Caveats, Literature."
)

AGENT_SYSTEM = (
    "You are an oncology research assistant preparing a tumor-board note from MuFFLe++, a "
    "federated multi-omic survival model. You cannot see patient data; use the tools to get the "
    "model's outputs for this case. Call only the tools you need, a few at a time: usually the "
    "risk first, then which data layers drove it, then the top features of the most influential "
    "layer(s), then literature on those genes if a search tool is offered.\n"
    "When done, write the note in Markdown with exactly these sections: **Summary**, **Drivers**, "
    "**Caveats**, **Literature**. Cite only numbers, features and references returned by tools; "
    "never invent patient details, genes or papers. In Literature list only URLs returned by "
    "search_literature, or say that no search was run. Mention missing data layers and the "
    "model's validation C-index in Caveats. This is a research prototype, not a diagnosis. "
    "Keep the note under 250 words."
)


@dataclass
class ToolCall:
    round: int  # 0 = fixed plan (no LLM planning)
    name: str
    arguments: dict
    result: dict


@dataclass
class CaseReport:
    text: str
    trace: list[ToolCall]
    mode: str  # "agent" (Nemotron chose the tools) | "fixed plan" | "offline"
    model: str | None = None
    tokens: int = 0
    notes: list[str] = field(default_factory=list)


def make_client():
    from openai import OpenAI

    return OpenAI(base_url=TOKEN_FACTORY_URL, api_key=os.environ["NEBIUS_API_KEY"], timeout=60)


def run_case_agent(tools: CaseTools, client=None, model: str = DEFAULT_MODEL,
                   max_rounds: int = MAX_TOOL_ROUNDS, max_tokens: int = MAX_TOKENS) -> CaseReport:
    """Let Nemotron pick tools for this case, then write the note. ``client`` is any
    OpenAI-compatible client (tests pass a fake); without one and without NEBIUS_API_KEY the
    offline template is returned."""
    if client is None:
        if not os.getenv("NEBIUS_API_KEY"):
            trace = fixed_plan(tools, search=False)
            return CaseReport(offline_summary(_facts(tools, trace)), trace, "offline")
        client = make_client()

    messages = [{"role": "system", "content": AGENT_SYSTEM},
                {"role": "user", "content": "Case (JSON):\n" + json.dumps(tools.case_header())
                 + "\n\nPrepare the tumor-board note."}]
    specs, trace, tokens = tools.specs(), [], 0
    for rnd in range(1, max_rounds + 2):
        last = rnd > max_rounds
        if last:
            messages.append({"role": "user", "content": "Tool budget used up. Write the note "
                             "now from the tool outputs above."})
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, tools=specs,
                tool_choice="none" if last else "auto", temperature=0.2, max_tokens=max_tokens)
        except Exception as e:
            if rnd > 1 or getattr(e, "status_code", None) != 400:
                raise
            # endpoint/model rejected tool calling: run the tools ourselves, one summary call
            return _fixed_plan_report(tools, client, model, f"tool calling rejected ({e})"[:300])
        tokens += getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0
        choice = resp.choices[0]
        calls = (choice.message.tool_calls or [])[:MAX_CALLS_PER_ROUND]
        if last or not calls:
            text = _strip_think(choice.message.content or "")
            notes = [] if text else [f"empty reply (finish_reason={choice.finish_reason})"]
            return CaseReport(text or "_Nemotron returned no text._", trace, "agent", model,
                              tokens, notes)
        messages.append({"role": "assistant", "content": choice.message.content or "",
                         "tool_calls": [{"id": c.id, "type": "function",
                                         "function": {"name": c.function.name,
                                                      "arguments": c.function.arguments}}
                                        for c in calls]})
        for c in calls:
            result = tools.call(c.function.name, c.function.arguments)
            args = parse_arguments(c.function.arguments)
            trace.append(ToolCall(rnd, c.function.name,
                                  {"_raw": c.function.arguments} if args is None else args, result))
            messages.append({"role": "tool", "tool_call_id": c.id, "content": json.dumps(result)})
    raise AssertionError("unreachable: the last round always returns")


def fixed_plan(tools: CaseTools, search: bool = True) -> list[ToolCall]:
    """The tool sequence the agent usually picks, run without an LLM (offline / fallback)."""
    trace = [ToolCall(0, n, {}, tools.call(n, {}))
             for n in ("predict_risk", "modality_contributions")]
    contrib = trace[1].result.get("delta_log_risk_when_removed") or {}
    strongest = max(contrib, key=lambda m: abs(contrib[m])) if contrib else tools.available[0]
    args = {"modality": strongest, "k": 5}
    trace.append(ToolCall(0, "top_features", args, tools.call("top_features", args)))
    if search and tools.can_search:
        args = {"genes": [f["name"] for f in trace[2].result["features"][:3]]}
        trace.append(ToolCall(0, "search_literature", args, tools.call("search_literature", args)))
    return trace


def _fixed_plan_report(tools: CaseTools, client, model: str, why: str) -> CaseReport:
    trace = fixed_plan(tools)
    refs = next((c.result.get("results") for c in trace if c.name == "search_literature"), None)
    text = summarize(_facts(tools, trace), refs, model, client)
    return CaseReport(text, trace, "fixed plan", model, notes=[why])


def _facts(tools: CaseTools, trace: list[ToolCall]) -> dict:
    r = {c.name: c.result for c in trace}
    return build_facts(tools.cancer, r["predict_risk"]["log_risk"],
                       r["predict_risk"]["cohort_percentile"],
                       r["modality_contributions"]["delta_log_risk_when_removed"],
                       [(f["name"], f["score"]) for f in r["top_features"]["features"]],
                       tools.c_index)


def _strip_think(text: str) -> str:
    """Reasoning models may prepend <think>…</think>; keep only the answer."""
    return re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()


def build_facts(cancer: str, risk: float, percentile: float, contributions: dict[str, float],
                features: list[tuple[str, float]], c_index: float | None = None) -> dict:
    return {
        "cancer_type": cancer,
        "predicted_log_risk": round(risk, 3),
        "risk_percentile_vs_cohort": round(percentile, 1),
        "modality_contributions_log_risk": {k: round(v, 3) for k, v in contributions.items()},
        "top_features_grad_x_input": [(n, round(s, 4)) for n, s in features],
        "model_validation_c_index": None if c_index is None else round(c_index, 3),
        "model": "MuFFLe++ federated DeepSurv, trained across hospitals without sharing data",
    }


def tavily_search(genes: list[str], cancer: str, topic: str = "prognosis",
                  k: int = 3) -> list[dict]:
    """Tavily web search on gene names only (the case_tools ``Search`` signature)."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    q = " ".join(genes)
    if topic == "clinical_trials":
        res = client.search(f"{q} {cancer} cancer clinical trial", max_results=k,
                            include_domains=["clinicaltrials.gov"])
    else:
        res = client.search(f"{q} prognosis {cancer} cancer survival", max_results=k)
    return [{"title": r["title"], "url": r["url"], "snippet": (r.get("content") or "")[:300]}
            for r in res.get("results", [])]


def literature(features: list[tuple[str, float]], cancer: str, k: int = 3) -> list[dict]:
    if not os.getenv("TAVILY_API_KEY"):
        return []
    return tavily_search([n for n, _ in features[:3]], cancer, "prognosis", k)


def offline_summary(facts: dict) -> str:
    drivers = sorted(facts["modality_contributions_log_risk"].items(), key=lambda kv: -abs(kv[1]))
    lines = [f"Summary: risk at the {facts['risk_percentile_vs_cohort']:.0f}th percentile of the "
             f"{facts['cancer_type']} cohort.",
             "Drivers: " + ", ".join(f"{m} ({v:+.2f})" for m, v in drivers),
             "Caveats: offline template — set NEBIUS_API_KEY for the Nemotron-written report."]
    return "\n\n".join(lines)  # blank lines so st.markdown keeps them as separate paragraphs


def summarize(facts: dict, refs: list[dict] | None = None, model: str = DEFAULT_MODEL,
              client=None) -> str:
    """Single-call summary of precomputed facts (no tools); the agent's fallback."""
    if client is None:
        if not os.getenv("NEBIUS_API_KEY"):
            return offline_summary(facts)
        client = make_client()
    user = "Model output (JSON):\n" + json.dumps(facts, indent=2)
    if refs:
        user += "\n\nCandidate literature (cite only these, by URL):\n" + json.dumps(refs, indent=2)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=700,
    )
    return _strip_think(resp.choices[0].message.content or "")


def _list_models():
    for m in make_client().models.list():
        if "nemotron" in m.id.lower() or "nvidia" in m.id.lower():
            print(m.id)


def _agent_cli(ckpt: str, data: str, patient: int, cancer: str):
    """Run the agent on one patient of a cohort and print the tool trace and the note."""
    from pathlib import Path

    import torch

    from muffle.config import load_config
    from muffle.data.dataset import MultiOmicDataset
    from muffle.train_local import load_checkpoint

    cfg = load_config()
    model = load_checkpoint(Path(ckpt), cfg).eval()
    ds = MultiOmicDataset(Path(data) / "cohort.npz", model.modality_dims)
    with torch.no_grad():
        risks = model(ds.x, ds.mask).numpy()
    x = {m: v[patient : patient + 1] for m, v in ds.x.items()}
    search = tavily_search if os.getenv("TAVILY_API_KEY") else None
    report = run_case_agent(CaseTools(model, x, ds.mask[patient : patient + 1], risks, cancer,
                                      search=search))
    print(f"mode={report.mode} model={report.model} tokens={report.tokens} notes={report.notes}")
    for c in report.trace:
        print(f"[{c.round}] {c.name}({json.dumps(c.arguments)}) -> {json.dumps(c.result)}")
    print("\n" + report.text)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--list-models", action="store_true")
    p.add_argument("--agent", action="store_true", help="run the case agent on one patient")
    p.add_argument("--ckpt", default="outputs/centralized.pt")
    p.add_argument("--data", default="data/synthetic")
    p.add_argument("--patient", type=int, default=0)
    p.add_argument("--cancer", default="breast")
    a = p.parse_args()
    if a.list_models:
        _list_models()
    elif a.agent:
        _agent_cli(a.ckpt, a.data, a.patient, a.cancer)
    else:
        demo = build_facts("breast", 0.84, 81.0, {"rna": 0.41, "clinical": 0.22, "genomic": 0.05},
                           [("ESR1", -0.12), ("MKI67", 0.09)], 0.71)
        print(summarize(demo))

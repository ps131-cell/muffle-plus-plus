"""Tumor-board case agent: NVIDIA Nemotron on Nebius Token Factory, calling our own tools.

The federated model produces the numbers; Nemotron decides which of them to look at, in three
steps:

1. **Plan (Nemotron 3 Super, fast):** gets the case header (cancer type, which data layers exist)
   and calls tools from ``case_tools`` — risk and percentile, per-layer contributions, top
   features, and Tavily literature/trial search when gene names are known — until it has enough.
2. **Write (Nemotron 3 Ultra, reasoning):** turns the tool outputs into the tumor-board note.
   If Ultra fails or returns nothing, Super writes it instead.
3. **Check (no LLM):** ``grounding.check_note`` looks for numbers, genes and links in the note
   that no tool returned; if it finds any, the writer gets one chance to fix them, and whatever
   remains is shown with the note.

This follows the track's advice: Ultra for serious reasoning, Super for the fast everyday calls.
Tool rounds and tokens are capped per report, and every call counts against a hard $25.50
spending cap (``budget``; once reached, reports fall back to the offline template). Only derived
numbers and gene names are sent, never raw omics.

Without NEBIUS_API_KEY the same tools run in a fixed order and the offline template is returned,
so tests and the demo work with no network. A failed live call (no credit, bad key, rate limit,
timeout) falls back to that same offline report with the reason in ``notes``, so the demo never
shows a traceback.

Env vars: NEBIUS_API_KEY (required for live calls), NEMOTRON_MODEL (planner),
NEMOTRON_WRITER_MODEL (writer), TAVILY_API_KEY (optional).
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

from muffle.report.budget import BudgetedClient, BudgetExceeded
from muffle.report.case_tools import CaseTools, parse_arguments
from muffle.report.grounding import check_note, describe

load_dotenv()  # repo-root .env (git-ignored); real environment variables take precedence

TOKEN_FACTORY_URL = os.getenv("TOKEN_FACTORY_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
DEFAULT_MODEL = os.getenv("NEMOTRON_MODEL") or "nvidia/nemotron-3-super-120b-a12b"
WRITER_MODEL = os.getenv("NEMOTRON_WRITER_MODEL") or "nvidia/Nemotron-3-Ultra-550b-a55b"

MAX_TOOL_ROUNDS = 6       # planner turns that may call tools
MAX_CALLS_PER_ROUND = 4   # extra parallel calls in one turn are dropped
MAX_TOKENS = 900          # per planner completion
WRITER_MAX_TOKENS = 3000  # the writer reasons before it writes; reasoning tokens count as output
MAX_REVISIONS = 1         # rewrites after the grounding check finds unsupported items
WRITER_DROPS = {"note", "log_risk", "cohort_median_log_risk"}  # tool-result keys the writer skips

AGENT_SYSTEM = (
    "You are the planning step of a tumor-board case agent for MuFFLe++, a federated multi-omic "
    "survival model. You cannot see patient data; use the tools to get the model's outputs for "
    "this case. Call only the tools you need; several tools can be called in one turn. Usually: "
    "predict_risk and modality_contributions together, then top_features of the most "
    "influential layer(s), then, if search_literature is offered, literature on up to 3 named "
    "genes among those features, best known first (skip unnamed ids such as AC138356.2); for a "
    "gene that is a drug target you may also search topic clinical_trials.\n"
    "A separate writer turns the tool outputs into the note, so do not write it yourself: when "
    "you have what you need, reply with the single word DONE."
)

SEARCH_NUDGE = ("search_literature has not been called. If any feature returned so far is a "
                "named gene, search the best known ones (up to 3); otherwise reply DONE.")

WRITER_SYSTEM = (
    "You write tumor-board notes from the outputs of MuFFLe++, a federated multi-omic survival "
    "model trained across hospitals without sharing patient data. You get the case header and "
    "the tool outputs as JSON. Write the note in Markdown with exactly these sections: "
    "**Summary**, **Drivers**, **Caveats**, **Literature**.\n"
    "Rules:\n"
    "- Summary: the patient's risk as a cohort percentile (write '81st percentile', not '81%') "
    "and the risk group.\n"
    "- Drivers: every layer in log_risk_added_by_layer, largest effect first, clinical "
    "included. For each, say whether it raises or lowers the predicted risk and by how much "
    "('lowers risk by 0.12', never a minus sign), then the top features the tools returned for "
    "it. Clinical data (age, stage, T/N/M) is never an omic layer; the others are.\n"
    "- Quote numbers as the tools gave them (rounding is fine). Don't compute new numbers, "
    "ratios or probabilities.\n"
    "- Name only genes and features that tools returned; if top_features returned none for a "
    "layer, name none from it.\n"
    "- Caveats: the missing data layers, the model's validation C-index, and that this is a "
    "research prototype, not a diagnosis.\n"
    "- Literature: only URLs returned by search_literature, with their titles and the gene each "
    "is about; if the search returned nothing, say no relevant publications were found; if no "
    "search was run, say so. Never invent papers.\n"
    "Don't restate these rules or explain how to read the numbers. Keep the note under 250 words."
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
    model: str | None = None   # planner
    tokens: int = 0
    notes: list[str] = field(default_factory=list)
    writer: str | None = None  # the model that wrote the note
    issues: list[dict] = field(default_factory=list)  # grounding check: unsupported items left
    revised: bool = False      # the writer rewrote the note after the grounding check


def make_client():
    from openai import OpenAI

    return BudgetedClient(OpenAI(base_url=TOKEN_FACTORY_URL, api_key=os.environ["NEBIUS_API_KEY"],
                                 timeout=60))


def run_case_agent(tools: CaseTools, client=None, model: str = DEFAULT_MODEL,
                   writer: str = WRITER_MODEL, max_rounds: int = MAX_TOOL_ROUNDS,
                   max_tokens: int = MAX_TOKENS) -> CaseReport:
    """Let Nemotron (``model``) pick tools for this case, then ``writer`` writes the note and the
    grounding check runs on it. ``client`` is any OpenAI-compatible client (tests pass a fake);
    without one and without NEBIUS_API_KEY the offline template is returned."""
    if client is None:
        if not os.getenv("NEBIUS_API_KEY"):
            return _offline_report(tools)
        client = make_client()

    messages = [{"role": "system", "content": AGENT_SYSTEM},
                {"role": "user", "content": "Case (JSON):\n" + json.dumps(tools.case_header())
                 + "\n\nGather what the tumor-board note needs."}]
    specs, trace, tokens, notes = tools.specs(), [], 0, []
    nudged = False
    for rnd in range(1, max_rounds + 1):
        try:
            resp = client.chat.completions.create(
                model=model, messages=messages, tools=specs, tool_choice="auto",
                temperature=0.2, max_tokens=max_tokens)
        except Exception as e:
            if rnd == 1 and getattr(e, "status_code", None) == 400:
                # endpoint/model rejected tool calling: run the tools ourselves, then write
                return _write(tools, fixed_plan(tools), client, writer, model, "fixed plan",
                              notes=[f"tool calling rejected ({e})"[:300]])
            return _offline_report(tools, unavailable(e), tokens)
        tokens += _usage(resp)
        calls = (resp.choices[0].message.tool_calls or [])[:MAX_CALLS_PER_ROUND]
        if not calls and not nudged and rnd < max_rounds and tools.can_search and tools.seen \
                and not any(c.name == "search_literature" for c in trace):
            # the planner sometimes stops before the literature step: remind it once
            nudged = True
            messages += [{"role": "assistant", "content": resp.choices[0].message.content or ""},
                         {"role": "user", "content": SEARCH_NUDGE}]
            continue
        if not calls:
            break
        messages.append({"role": "assistant", "content": resp.choices[0].message.content or "",
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
    if not any(c.name == "predict_risk" and "error" not in c.result for c in trace):
        notes.append("the planner did not get the risk, so the fixed tool sequence ran too")
        trace += fixed_plan(tools)
    return _write(tools, trace, client, writer, model, "agent", tokens, notes)


def _write(tools: CaseTools, trace: list[ToolCall], client, writer: str, planner: str,
           mode: str, tokens: int = 0, notes: list[str] | None = None) -> CaseReport:
    """The writer turns the tool outputs into the note (the planner model writes it if the
    writer fails); then the grounding check, and at most MAX_REVISIONS rewrites."""
    notes = list(notes or [])
    # the writer reads risk by percentile, so it gets no log-risk values (their sign misleads)
    evidence = {"case": tools.case_header(),
                "tool_outputs": [{"tool": c.name, "arguments": c.arguments,
                                  "result": {k: v for k, v in c.result.items()
                                             if k not in WRITER_DROPS}}
                                 for c in trace]}
    messages = [{"role": "system", "content": WRITER_SYSTEM},
                {"role": "user", "content": "Case header and tool outputs (JSON):\n"
                 + json.dumps(evidence, indent=1) + "\n\nWrite the tumor-board note."}]
    text, used = "", None
    for m in dict.fromkeys([writer, planner]):
        try:
            text, n, why = _complete(client, m, messages)
        except Exception as e:
            notes.append(f"writer {m}: {unavailable(e)}")
            continue
        tokens += n
        if text:
            used = m
            break
        notes.append(f"writer {m}: {why}")
    if used is None:
        return _offline_report(tools, notes[-1], tokens)

    issues, revised = check_note(text, evidence, tools.names), False
    for _ in range(MAX_REVISIONS if issues else 0):
        fix = messages + [
            {"role": "assistant", "content": text},
            {"role": "user", "content": "A check against the tool outputs found these items in "
             f"your note that no tool returned: {describe(issues)}. Rewrite the whole note so "
             "every number, gene and link comes from the tool outputs: correct or drop them."}]
        try:
            new, n, _ = _complete(client, used, fix)
        except Exception as e:
            notes.append(f"rewrite skipped: {unavailable(e)}")
            break
        tokens += n
        new_issues = check_note(new, evidence, tools.names) if new else issues
        if new and len(new_issues) < len(issues):
            text, issues, revised = new, new_issues, True
    return CaseReport(text, trace, mode, planner, tokens, notes, used, issues, revised)


def _complete(client, model: str, messages: list[dict]) -> tuple[str, int, str]:
    """(text, tokens, why there's no text). A reply cut off at max_tokens counts as no text:
    a half note is worse than the fallback."""
    resp = client.chat.completions.create(model=model, messages=messages, temperature=0.2,
                                          max_tokens=WRITER_MAX_TOKENS)
    choice = resp.choices[0]
    if choice.finish_reason == "length":
        return "", _usage(resp), f"reply cut off at {WRITER_MAX_TOKENS} tokens"
    text = _strip_think(choice.message.content or "")
    return text, _usage(resp), "" if text else "returned no text"


def _usage(resp) -> int:
    return getattr(getattr(resp, "usage", None), "total_tokens", 0) or 0


def fixed_plan(tools: CaseTools, search: bool = True) -> list[ToolCall]:
    """The tool sequence the agent usually picks, run without an LLM (offline / fallback)."""
    trace = [ToolCall(0, n, {}, tools.call(n, {}))
             for n in ("predict_risk", "modality_contributions")]
    contrib = trace[1].result.get("log_risk_added_by_layer") or {}
    strongest = max(contrib, key=lambda m: abs(contrib[m])) if contrib else tools.available[0]
    args = {"modality": strongest, "k": 5}
    trace.append(ToolCall(0, "top_features", args, tools.call("top_features", args)))
    if search and tools.can_search and trace[2].result.get("features"):
        args = {"genes": [f["name"] for f in trace[2].result["features"][:3]]}
        trace.append(ToolCall(0, "search_literature", args, tools.call("search_literature", args)))
    return trace


def _offline_report(tools: CaseTools, why: str | None = None, tokens: int = 0) -> CaseReport:
    trace = fixed_plan(tools, search=False)
    facts = _facts(tools, trace)
    if why is None:
        return CaseReport(offline_summary(facts), trace, "offline")
    return CaseReport(offline_summary(facts, why), trace, "offline", tokens=tokens, notes=[why])


HTTP_REASONS = {401: "invalid API key", 402: "out of credit", 403: "access denied",
                429: "rate limited"}


def unavailable(e: Exception) -> str:
    """Short reason for a failed Token Factory call: status code or error type only, never the
    request (which carries the key in its headers)."""
    if isinstance(e, BudgetExceeded):
        return str(e)
    status = getattr(e, "status_code", None)
    what = (f"HTTP {status}" + (f", {HTTP_REASONS[status]}" if status in HTTP_REASONS else "")
            if status else type(e).__name__)
    return f"Token Factory unavailable ({what})"


def _facts(tools: CaseTools, trace: list[ToolCall]) -> dict:
    r = {c.name: c.result for c in trace}
    return build_facts(tools.cancer, r["predict_risk"]["log_risk"],
                       r["predict_risk"]["cohort_percentile"],
                       r["modality_contributions"]["log_risk_added_by_layer"],
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


SEARCH_QUERIES_PER_REPORT = 3  # Tavily queries (credits) per search_literature call
RESULTS_PER_GENE = 2
CANCER_WORDS = re.compile(r"cancer|tumou?r|carcinoma|neoplas|oncolog|metasta", re.I)


def tavily_search(genes: list[str], cancer: str, topic: str = "prognosis",
                  k: int = 5) -> list[dict]:
    """Tavily web search on gene names only (the case_tools ``Search`` signature).

    One query per gene (at most SEARCH_QUERIES_PER_REPORT), and only results whose title or
    snippet name that gene and mention cancer are kept: a combined query, or an unnamed id like
    AC138356.2, otherwise returns generic survival pages (or papers on other diseases) that would
    read like citations. When some hits name this cancer type, the others are dropped. The same
    paper on two sites (PMC and a publisher, say) is kept once. Clinical-trial hits (protocol
    PDFs on cdn.clinicaltrials.gov) are linked as their study page, titled with the NCT id."""
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    out, seen = [], set()
    for gene in genes[:SEARCH_QUERIES_PER_REPORT]:
        if topic == "clinical_trials":
            res = client.search(f'"{gene}" {cancer} cancer', max_results=5,
                                include_domains=["clinicaltrials.gov"])
        else:
            res = client.search(f'"{gene}" {cancer} cancer prognosis survival', max_results=5)
        hits = []
        for r in res.get("results", []):
            title, text = r.get("title") or "", r.get("content") or ""
            both = f"{title} {text}"
            if not CANCER_WORDS.search(both) or not re.search(
                    rf"(?<![\w-]){re.escape(gene)}(?![\w-])", both, re.I):
                continue
            url = r["url"]
            nct = re.search(r"NCT\d{8}", url)
            if topic == "clinical_trials" and nct:
                url = f"https://clinicaltrials.gov/study/{nct.group()}"
                title = f"{nct.group()}: {title}"
            hits.append({"gene": gene, "title": title, "url": url, "snippet": text[:300],
                         "this_cancer": cancer.lower() in both.lower()})
        if any(h["this_cancer"] for h in hits):
            hits = [h for h in hits if h["this_cancer"]]
        kept = 0
        for h in hits:
            key = _title_key(h["title"])  # generic titles ("Protocol") don't identify a paper
            if kept == RESULTS_PER_GENE or h["url"] in seen or (len(key) >= 25 and key in seen):
                continue
            seen.update({h["url"], key})
            kept += 1
            out.append({k_: v for k_, v in h.items() if k_ != "this_cancer"})
    return out[:k]


def _title_key(title: str) -> str:
    """Same paper on two sites: "(PDF) Vav3 oncogene is ... : Oncology Letters" vs "Vav3 oncogene
    is ... patients" -> the first 40 letters of the title proper."""
    title = re.sub(r"^\(pdf\)\s*|\[pdf\]\s*", "", title.strip(), flags=re.I)
    title = re.split(r"\s[|:–]\s|\.\.\.|…", title)[0]
    return re.sub(r"[^a-z0-9]", "", title.lower())[:40]


def offline_summary(facts: dict,
                    why: str = "set NEBIUS_API_KEY for the Nemotron-written report") -> str:
    drivers = sorted(facts["modality_contributions_log_risk"].items(), key=lambda kv: -abs(kv[1]))
    lines = [f"Summary: risk at the {facts['risk_percentile_vs_cohort']:.0f}th percentile of the "
             f"{facts['cancer_type']} cohort.",
             "Drivers: " + ", ".join(f"{m} ({v:+.2f})" for m, v in drivers),
             f"Caveats: offline template — {why}."]
    return "\n\n".join(lines)  # blank lines so st.markdown keeps them as separate paragraphs


def _list_models():
    for m in make_client().models.list():
        if "nemotron" in m.id.lower() or "nvidia" in m.id.lower():
            print(m.id)


def _agent_cli(ckpt: str, data: str, patient: int, cancer: str, n_clients: int,
               config: str | None = None, writer: str = WRITER_MODEL):
    """Run the agent on one patient of a cohort and print the tool trace and the note."""
    from pathlib import Path

    import numpy as np
    import torch

    from muffle.data.dataset import MultiOmicDataset, feature_names
    from muffle.train_local import heldout_c_index, load_model

    model, cfg = load_model(Path(ckpt), config)
    cohort = Path(data) / "cohort.npz"
    ds = MultiOmicDataset(cohort, cfg["modalities"])
    with torch.no_grad():
        risks = model(ds.x, ds.mask).numpy()
    x = {m: v[patient : patient + 1] for m, v in ds.x.items()}
    search = tavily_search if os.getenv("TAVILY_API_KEY") else None
    c = float(np.mean(list(heldout_c_index(model, Path(data), n_clients, cfg).values())))
    report = run_case_agent(CaseTools(model, x, ds.mask[patient : patient + 1], risks, cancer,
                                      feature_names(cohort, cfg["modalities"]), c, search),
                            writer=writer)
    print(f"mode={report.mode} planner={report.model} writer={report.writer} "
          f"tokens={report.tokens} revised={report.revised} notes={report.notes}")
    if report.mode != "offline":
        print("grounding: " + (describe(report.issues) if report.issues else "every number, "
                               "gene and link is in the tool outputs"))
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
    p.add_argument("--n-clients", type=int, default=3,
                   help="sites whose validation splits give the held-out C-index (as the demo)")
    p.add_argument("--config", default=None,
                   help="only for checkpoints without a stored config (raw NVFlare models)")
    p.add_argument("--writer", default=WRITER_MODEL, help="model that writes the note")
    a = p.parse_args()
    if a.list_models:
        _list_models()
    elif a.agent:
        _agent_cli(a.ckpt, a.data, a.patient, a.cancer, a.n_clients, a.config, a.writer)
    else:
        p.print_help()

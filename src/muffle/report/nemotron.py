"""Clinician-facing prognosis summary written by NVIDIA Nemotron via Nebius Token Factory.

The federated model produces numbers (risk, percentile, which data layers drove it, top genes);
Nemotron turns them into a cautious, readable summary and, with Tavily enabled, cites recent
literature on the top features. Only derived, de-identified numbers are sent — never raw omics.

Env vars: NEBIUS_API_KEY (required for live calls), NEMOTRON_MODEL, TAVILY_API_KEY (optional).
List available model ids with:  python -m muffle.report.nemotron --list-models
"""

from __future__ import annotations

import argparse
import json
import os

from dotenv import load_dotenv

load_dotenv()  # repo-root .env (git-ignored); real environment variables take precedence

TOKEN_FACTORY_URL = os.getenv("TOKEN_FACTORY_BASE_URL", "https://api.tokenfactory.nebius.com/v1")
DEFAULT_MODEL = os.getenv("NEMOTRON_MODEL", "nvidia/Nemotron-3-Nano")  # check --list-models

SYSTEM = (
    "You are an oncology research assistant summarizing output from a federated survival model "
    "for a tumor board. Be precise and cautious: this is a research prototype, not a diagnosis. "
    "Explain the risk estimate, which data layers drove it, and what would change confidence. "
    "Never invent patient details. Use short sections: Summary, Drivers, Caveats, Literature."
)


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


def literature(features: list[tuple[str, float]], cancer: str, k: int = 3) -> list[dict]:
    if not os.getenv("TAVILY_API_KEY"):
        return []
    from tavily import TavilyClient

    client = TavilyClient(api_key=os.environ["TAVILY_API_KEY"])
    genes = ", ".join(n for n, _ in features[:3])
    res = client.search(f"{genes} prognosis {cancer} cancer survival", max_results=k)
    return [{"title": r["title"], "url": r["url"]} for r in res.get("results", [])]


def offline_summary(facts: dict) -> str:
    drivers = sorted(facts["modality_contributions_log_risk"].items(), key=lambda kv: -abs(kv[1]))
    lines = [f"Summary: risk at the {facts['risk_percentile_vs_cohort']:.0f}th percentile of the "
             f"{facts['cancer_type']} cohort.",
             "Drivers: " + ", ".join(f"{m} ({v:+.2f})" for m, v in drivers),
             "Caveats: offline template — set NEBIUS_API_KEY for the Nemotron-written report."]
    return "\n\n".join(lines)  # blank lines so st.markdown keeps them as separate paragraphs


def summarize(facts: dict, refs: list[dict] | None = None, model: str = DEFAULT_MODEL) -> str:
    if not os.getenv("NEBIUS_API_KEY"):
        return offline_summary(facts)
    from openai import OpenAI

    client = OpenAI(base_url=TOKEN_FACTORY_URL, api_key=os.environ["NEBIUS_API_KEY"])
    user = "Model output (JSON):\n" + json.dumps(facts, indent=2)
    if refs:
        user += "\n\nCandidate literature (cite only these, by URL):\n" + json.dumps(refs, indent=2)
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}],
        temperature=0.2,
        max_tokens=700,
    )
    return resp.choices[0].message.content


def _list_models():
    from openai import OpenAI

    client = OpenAI(base_url=TOKEN_FACTORY_URL, api_key=os.environ["NEBIUS_API_KEY"])
    for m in client.models.list():
        if "nemotron" in m.id.lower() or "nvidia" in m.id.lower():
            print(m.id)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--list-models", action="store_true")
    if p.parse_args().list_models:
        _list_models()
    else:
        demo = build_facts("breast", 0.84, 81.0, {"rna": 0.41, "clinical": 0.22, "genomic": 0.05},
                           [("ESR1", -0.12), ("MKI67", 0.09)], 0.71)
        print(summarize(demo))

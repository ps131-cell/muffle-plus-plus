"""Tools the Nemotron case agent can call, bound to one patient.

Each tool runs our own code locally (the trained MuffleNet, ``muffle.explain``, Tavily) and
returns a small JSON-able dict. Tool results are sent to Token Factory, so they hold only derived
numbers (log-risk, percentile, contributions, attribution scores), coarse recorded facts (stage,
age band) and feature/gene names — never the patient's raw omics values.

Every result carries an ``evidence_type`` (docs/VISION.md): "observed" (recorded or measured for
this patient), "model inference" (a prediction, with its uncertainty) or "hypothesis" (leads such
as literature, not findings about this patient).
"""

from __future__ import annotations

import json
from collections.abc import Callable

import numpy as np
import torch

from muffle import explain
from muffle.models import MuffleNet

LAYERS = {"clinical": "clinical: age, stage, T/N/M, histology (not an omic layer)",
          "rna": "omic: gene expression (RNA-seq)",
          "genomic": "omic: gene-level copy number",
          "methylation": "omic: DNA methylation (CpG sites)",
          "protein": "omic: protein levels (RPPA)"}
MAX_FEATURES = 10
MAX_SEARCH_GENES = 3  # one Tavily query each
TOPICS = ("prognosis", "clinical_trials")
OBSERVED, INFERENCE, HYPOTHESIS = "observed", "model inference", "hypothesis"


def age_band(age: float | None) -> str:
    """Coarse age for the LLM: the note never needs the exact age."""
    if age is None or age != age:  # None or NaN
        return "not recorded"
    return "under 50" if age < 50 else "50-64" if age < 65 else "65 or older"


def observed_facts(stage: str | None = None, age: float | None = None) -> dict:
    """Recorded clinical facts for ``observed_findings`` (stage "I".."IV" or None)."""
    return {"recorded_stage": stage or "not recorded", "age_band": age_band(age)}

# search(genes, cancer, topic, k) -> [{"title", "url", "snippet"}]; see nemotron.tavily_search
Search = Callable[[list[str], str, str, int], list[dict]]


def _fn(name: str, description: str, properties: dict | None = None,
        required: list[str] | None = None) -> dict:
    return {"type": "function", "function": {
        "name": name, "description": description,
        "parameters": {"type": "object", "properties": properties or {},
                       "required": required or []}}}


class CaseTools:
    """The agent's view of one case. ``call(name, arguments)`` never raises: bad calls come back
    as ``{"error": ...}`` so the model can correct itself."""

    def __init__(self, model: MuffleNet, x: dict[str, torch.Tensor], mask: torch.Tensor,
                 cohort_risks: np.ndarray, cancer: str,
                 feature_names: dict[str, list[str]] | None = None,
                 c_index: float | None = None, search: Search | None = None,
                 offsets: dict[str, float] | None = None, observed: dict | None = None):
        self.model, self.x, self.mask = model.eval(), x, mask
        self.observed = observed or {}  # observed_facts(...): recorded stage, age band
        self.offsets = offsets  # explain.cohort_offsets: contributions vs a typical patient
        self.cohort = np.asarray(cohort_risks, dtype=float)
        self.cancer, self.c_index = cancer, c_index
        self.names = feature_names or {}
        self.search = search
        self.available = [m for j, m in enumerate(model.names) if mask[0, j] > 0]
        self.missing = [m for m in model.names if m not in self.available]
        self._seen: set[str] = set()  # omic names top_features returned; search is limited to them

    @property
    def seen(self) -> set[str]:
        """Omic feature names returned so far (the genes search_literature accepts)."""
        return set(self._seen)

    @property
    def can_search(self) -> bool:
        """Literature search only makes sense with real gene names (not synthetic indices)."""
        return self.search is not None and bool(self.names)

    def case_header(self) -> dict:
        return {
            "cancer_type": self.cancer,
            "available_data_layers": self.available,
            "missing_data_layers": self.missing,
            "data_layers": {m: LAYERS.get(m, m) for m in self.model.names},
            "model": "MuFFLe++ DeepSurv (Cox) on masked multi-omic fusion, trained with "
                     "federated averaging across hospitals without sharing patient data",
            "model_validation_c_index": None if self.c_index is None else round(self.c_index, 3),
            "feature_names": "gene/feature symbols" if self.names
                             else "anonymous indices (synthetic data), not gene names",
        }

    def specs(self) -> list[dict]:
        specs = [
            _fn("observed_findings", "What was actually recorded or measured for this patient "
                "(evidence type: observed): which data layers exist, the recorded stage and age "
                "band. Call it first."),
            _fn("predict_risk", "Predicted log-risk for this patient, its percentile in the "
                "cohort, and the risk group (cohort tertiles)."),
            _fn("modality_contributions", "How much each available data layer raises or lowers "
                "this patient's predicted log-risk compared with a typical patient in the cohort."),
            _fn("top_features", "Top features of one data layer by gradient x input attribution "
                "(positive pushes risk up).",
                {"modality": {"type": "string", "enum": self.available},
                 "k": {"type": "integer", "minimum": 1, "maximum": MAX_FEATURES}},
                ["modality"]),
        ]
        if self.can_search:
            specs.append(_fn(
                "search_literature", f"Web search (Tavily) for publications or clinical trials "
                f"on up to {MAX_SEARCH_GENES} genes returned by top_features for an omic layer, in "
                "this cancer type, best known first. Pick named genes (e.g. GATA3), not unnamed "
                "ids such as AC138356.2 or RNU6-607P, which find nothing.",
                {"genes": {"type": "array", "items": {"type": "string"},
                           "maxItems": MAX_SEARCH_GENES},
                 "topic": {"type": "string", "enum": list(TOPICS)}},
                ["genes"]))
        return specs

    def call(self, name: str, arguments: str | dict | None) -> dict:
        tools = {s["function"]["name"]: getattr(self, s["function"]["name"]) for s in self.specs()}
        if name not in tools:
            return {"error": f"unknown tool {name!r}; available: {sorted(tools)}"}
        args = parse_arguments(arguments)
        if args is None:
            return {"error": "arguments must be a JSON object"}
        try:
            return tools[name](**args)
        except (TypeError, ValueError) as e:
            return {"error": str(e)}

    # --- tools -----------------------------------------------------------------------------

    def observed_findings(self) -> dict:
        return {"evidence_type": OBSERVED,
                "measured_data_layers": self.available, "not_measured": self.missing,
                **(self.observed or observed_facts()),
                "note": "recorded facts, not predictions; a layer that was not measured is "
                        "unknown, not normal"}

    def predict_risk(self) -> dict:
        with torch.no_grad():
            risk = self.model(self.x, self.mask).item()
        return {
            "evidence_type": INFERENCE,
            "uncertainty": "the model ranks patients correctly in about "
                           f"{round(100 * self.c_index)}% of comparable pairs (validation "
                           "C-index)" if self.c_index else "validation C-index not available",
            "log_risk": round(risk, 3),
            "cohort_percentile": int(explain.risk_percentile(risk, self.cohort)),
            "risk_group": explain.risk_group(risk, self.cohort),
            "cohort_size": len(self.cohort),
            "cohort_median_log_risk": round(float(np.median(self.cohort)), 3),
            "note": "Judge the patient's standing by cohort_percentile and risk_group, not by the "
                    "sign of log_risk: log-risk is measured from the model's baseline, not from "
                    "the cohort median. Higher means shorter expected survival; it is not an "
                    "absolute probability.",
        }

    def modality_contributions(self) -> dict:
        _, contrib = explain.modality_contributions(self.model, self.x, self.mask, self.offsets)
        out = {"evidence_type": INFERENCE,
               "log_risk_added_by_layer": {m: round(v, 3) for m, v in contrib.items()},
               "compared_with": "a typical patient in the cohort" if self.offsets
                                else "the same patient without that layer",
               "available_data_layers": self.available, "missing_data_layers": self.missing,
               "note": "positive = this layer raises the patient's predicted risk; negative = "
                       "it lowers it"}
        if not contrib:
            out["note"] = "only one data layer is available, so contributions are undefined"
        return out

    def top_features(self, modality: str, k: int = 5) -> dict:
        if modality not in self.available:
            raise ValueError(f"modality must be one of the available layers {self.available}")
        k = max(1, min(int(k), MAX_FEATURES))
        # features whose score rounds to 0 (e.g. all-zero mutation inputs) explain nothing
        feats = [(n, s) for n, s in explain.top_features(self.model, self.x, self.mask, modality,
                                                         self.names.get(modality), k)
                 if round(s, 4) != 0]
        if modality != "clinical":  # age, stage... are not genes
            self._seen.update(n for n, _ in feats)
        out = {"evidence_type": INFERENCE, "modality": modality, "method": "gradient x input",
               "features": [{"name": n, "score": round(s, 4)} for n, s in feats],
               "note": "positive score pushes risk up"}
        if not feats:
            out["note"] = ("no single feature in this layer moves this patient's risk measurably "
                           "(every |score| < 0.0001), so name no features from this layer")
        return out

    def search_literature(self, genes: list[str], topic: str = "prognosis") -> dict:
        if topic not in TOPICS:
            raise ValueError(f"topic must be one of {list(TOPICS)}")
        genes = [g for g in genes if isinstance(g, str)][:MAX_SEARCH_GENES]
        unknown = [g for g in genes if g not in self._seen]
        if not genes or unknown:
            raise ValueError("genes must come from earlier top_features results"
                             + (f"; not returned yet: {unknown}" if unknown else ""))
        try:
            results = self.search(genes, self.cancer, topic, 5)
        except Exception as e:  # network/quota errors shouldn't sink the report
            return {"error": f"literature search failed ({type(e).__name__})"}
        out = {"evidence_type": HYPOTHESIS, "genes": genes, "topic": topic, "results": results,
               "about": "published leads on these genes in this cancer, not findings about this "
                        "patient"}
        if not results:
            out["note"] = "no result names these genes, so there is nothing to cite"
        return out


def parse_arguments(arguments: str | dict | None) -> dict | None:
    """Tool-call arguments arrive as a JSON string (OpenAI format); None if not an object."""
    if isinstance(arguments, dict):
        return arguments
    try:
        args = json.loads(arguments or "{}")
    except json.JSONDecodeError:
        return None
    return args if isinstance(args, dict) else None

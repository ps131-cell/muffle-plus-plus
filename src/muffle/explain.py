"""Per-patient explanations that feed the Nemotron report.

* modality contributions: how much the predicted log-risk moves when each available modality
  is masked out (the model was trained with modality dropout, so this is in-distribution),
  minus that layer's average effect over the cohort (``cohort_offsets``). Masking a layer shifts
  almost every patient's risk the same way, so without the offset a high-risk patient could show
  every layer "lowering" risk; with it, a contribution reads "compared with a typical patient".
* top features: gradient x input on the strongest modality
"""

from __future__ import annotations

import numpy as np
import torch

from muffle.models import MuffleNet


@torch.no_grad()
def masked_effects(model: MuffleNet, x: dict[str, torch.Tensor], mask: torch.Tensor):
    """Log-risk minus log-risk with each modality masked out, for every row: (base [N],
    {modality: [N]}). Rows lacking the modality, or having only one, get NaN."""
    model.eval()
    base = model(x, mask)
    out = {}
    for j, m in enumerate(model.names):
        ablated = mask.clone()
        ablated[:, j] = 0
        eff = base - model(x, ablated)
        out[m] = torch.where((mask[:, j] > 0) & (mask.sum(1) > 1), eff, torch.nan).numpy()
    return base.numpy(), out


def cohort_offsets(model: MuffleNet, x: dict[str, torch.Tensor], mask: torch.Tensor):
    """Each modality's average masked effect over the cohort rows that have it."""
    _, eff = masked_effects(model, x, mask)
    return {m: float(np.nanmean(e)) for m, e in eff.items() if np.isfinite(e).any()}


def modality_contributions(model: MuffleNet, x: dict[str, torch.Tensor], mask: torch.Tensor,
                           offsets: dict[str, float] | None = None):
    """x: {modality: [1, d]}, mask: [1, M]. Returns (log-risk, {modality: delta log-risk}) for
    the present modalities; with ``offsets`` (``cohort_offsets``) relative to a typical
    patient."""
    base, eff = masked_effects(model, x, mask)
    offsets = offsets or {}
    return float(base[0]), {m: float(e[0]) - offsets.get(m, 0.0) for m, e in eff.items()
                            if np.isfinite(e[0])}


def top_features(model: MuffleNet, x, mask, modality: str, names: list[str] | None, k: int = 10):
    model.eval()
    xm = {m: v.clone().requires_grad_(m == modality) for m, v in x.items()}
    model(xm, mask).sum().backward()
    score = (xm[modality].grad * xm[modality]).detach().numpy()[0]
    idx = np.argsort(-np.abs(score))[:k]
    names = names or [f"{modality}_{i}" for i in range(len(score))]
    return [(names[i], float(score[i])) for i in idx]


def risk_percentile(risk: float, cohort_risks: np.ndarray) -> float:
    return float((cohort_risks < risk).mean() * 100)


def risk_group(risk: float, cohort_risks: np.ndarray) -> str:
    """Cohort tertile: low / medium / high."""
    lo, hi = np.quantile(cohort_risks, [1 / 3, 2 / 3])
    return "low" if risk <= lo else "medium" if risk <= hi else "high"

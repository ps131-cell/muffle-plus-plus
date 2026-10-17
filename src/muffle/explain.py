"""Per-patient explanations that feed the Nemotron report.

* modality contributions: how much the predicted log-risk moves when each available modality
  is masked out (the model was trained with modality dropout, so this is in-distribution)
* top features: gradient x input on the strongest modality
"""

from __future__ import annotations

import numpy as np
import torch

from muffle.models import MuffleNet


@torch.no_grad()
def modality_contributions(model: MuffleNet, x: dict[str, torch.Tensor], mask: torch.Tensor):
    """x: {modality: [1, d]}, mask: [1, M]. Returns {modality: delta log-risk} for present ones."""
    model.eval()
    base = model(x, mask).item()
    out = {}
    for j, m in enumerate(model.names):
        if mask[0, j] == 0 or mask[0].sum() <= 1:
            continue
        ablated = mask.clone()
        ablated[0, j] = 0
        out[m] = base - model(x, ablated).item()
    return base, out


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

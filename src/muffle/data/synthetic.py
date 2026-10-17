"""Synthetic multi-omic survival cohort.

Every patient has a few latent biological factors. Each omic layer is a noisy (partly
nonlinear) view of those factors, and the true hazard depends on them plus age/stage, so a
model that integrates modalities should beat any single one. Use this to develop the model and
FL plumbing before real TCGA data is harmonized.
"""

from __future__ import annotations

import numpy as np

from muffle.config import MODALITIES


def make_cohort(
    n_patients: int = 900,
    dims: dict[str, int] | None = None,
    n_factors: int = 6,
    censor_rate: float = 0.4,
    seed: int = 0,
) -> dict[str, np.ndarray]:
    dims = dims or {"genomic": 200, "rna": 1000, "methylation": 500, "protein": 100, "clinical": 8}
    rng = np.random.default_rng(seed)
    z = rng.normal(size=(n_patients, n_factors))

    def view(d: int, nonlinear: bool, noise: float) -> np.ndarray:
        w = rng.normal(scale=1 / np.sqrt(n_factors), size=(n_factors, d))
        # each feature only loads on a subset of factors -> sparse, realistic-ish blocks
        w *= rng.random((n_factors, d)) < 0.3
        x = z @ w
        if nonlinear:
            x = np.tanh(x) + 0.3 * x**2
        return (x + rng.normal(scale=noise, size=x.shape)).astype(np.float32)

    out: dict[str, np.ndarray] = {}
    if "genomic" in dims:
        g = view(dims["genomic"], nonlinear=False, noise=1.0)
        out["x_genomic"] = (g > 1.2).astype(np.float32)  # sparse binary "mutated" calls
    if "rna" in dims:
        out["x_rna"] = view(dims["rna"], nonlinear=True, noise=0.8)
    if "methylation" in dims:
        out["x_methylation"] = view(dims["methylation"], nonlinear=False, noise=1.0)
    if "protein" in dims:
        out["x_protein"] = view(dims["protein"], nonlinear=True, noise=0.6)

    age = rng.normal(60, 10, n_patients)
    stage = np.clip(np.round(1.5 + 0.6 * z[:, 0] + rng.normal(0, 0.7, n_patients)), 1, 4)
    if "clinical" in dims:
        clin = np.zeros((n_patients, dims["clinical"]), dtype=np.float32)
        clin[:, 0] = (age - 60) / 10
        clin[:, 1] = (stage - 2.5) / 1.1
        if dims["clinical"] > 2:
            clin[:, 2:] = rng.normal(size=(n_patients, dims["clinical"] - 2))  # noise covariates
        out["x_clinical"] = clin

    beta = np.array([0.8, -0.6, 0.5, 0.4, -0.3, 0.2][:n_factors])
    log_hazard = z @ beta + 0.3 * np.sin(2 * z[:, 1]) + 0.02 * (age - 60) + 0.35 * (stage - 2.5)
    t_event = rng.exponential(scale=36 * np.exp(-log_hazard))  # months
    t_censor = rng.uniform(0, np.quantile(t_event, 1 - censor_rate / 2) * 2, n_patients)
    out["time"] = np.minimum(t_event, t_censor).astype(np.float32)
    out["event"] = (t_event <= t_censor).astype(np.float32)
    out["stage"] = stage.astype(np.float32)  # kept for heterogeneous partitioning only

    present = [m for m in MODALITIES if f"x_{m}" in out]
    out["mask"] = np.ones((n_patients, len(MODALITIES)), dtype=np.float32)
    for j, m in enumerate(MODALITIES):
        if m not in present:
            out["mask"][:, j] = 0
    out["true_log_hazard"] = log_hazard.astype(np.float32)
    return out

"""Per-modality preprocessing for real data (TCGA / CPTAC / CHIMERA).

In the federated setting each site fits these on its *own* data. The feature list itself
(which genes / CpGs / proteins) must be agreed across sites beforehand; see
``harmonize_features``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def log_zscore(x: pd.DataFrame, pseudocount: float = 1.0) -> pd.DataFrame:
    """RNA-seq counts/TPM or proteomic intensities -> log -> per-feature z-score."""
    lx = np.log1p(x.clip(lower=0) / pseudocount)
    return (lx - lx.mean()) / lx.std(ddof=0).replace(0, 1)


def beta_to_m(beta: pd.DataFrame, eps: float = 1e-6) -> pd.DataFrame:
    """Methylation beta values (0..1) -> M-values, which behave better in linear models."""
    b = beta.clip(eps, 1 - eps)
    return np.log2(b / (1 - b))


def top_variance(x: pd.DataFrame, k: int) -> list[str]:
    return x.var().sort_values(ascending=False).index[:k].tolist()


def drop_sparse(x: pd.DataFrame, max_missing: float = 0.2) -> pd.DataFrame:
    return x.loc[:, x.isna().mean() <= max_missing]


def harmonize_features(site_feature_lists: list[list[str]], how: str = "intersection") -> list[str]:
    """Agree on a common feature space. Only feature *names* are shared, never values."""
    sets = [set(f) for f in site_feature_lists]
    common = set.intersection(*sets) if how == "intersection" else set.union(*sets)
    return sorted(common)


def align(x: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """Reorder to the agreed feature list; features a site lacks become 0 (post z-score mean)."""
    return x.reindex(columns=features).fillna(0.0)

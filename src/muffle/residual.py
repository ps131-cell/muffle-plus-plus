"""Clinical-anchored residual model (#25): omics may only add to the clinical risk.

1. anchor:   train only the ``model.always_keep`` layers (clinical); every other layer is
             masked out, so this is the clinical-only model.
2. residual: freeze the anchor's encoder and head, then train the other layers' heads on top,
             so they can only learn what the anchor misses.
3. gate:     log-risk = anchor + λ · residual, with λ picked on an inner validation split cut
             from the training data (λ = 0 is the anchor alone); then both stages are refit on
             all of the training data. When the data carry tissue source sites (TCGA), the
             inner split holds out whole sites: omic signal that only works inside the
             hospitals it was learned at (batch effects) must not earn a λ > 0.

The result is an ordinary additive MuffleNet with ``residual_scale = λ``, so the app, agent
and checkpoints work unchanged (store λ as cfg["model"]["residual_scale"]).
"""

from __future__ import annotations

import numpy as np
import torch
from torch.utils.data import ConcatDataset, DataLoader, Dataset, Subset

from muffle.engine import evaluate, train_epochs
from muffle.models import MuffleNet

LAMBDAS = (0.0, 0.25, 0.5, 0.75, 1.0)
INNER_FRACTION = 0.2


class MaskedView(Dataset):
    """A dataset whose availability mask is multiplied by ``keep`` (1 = keep that column)."""

    def __init__(self, ds: Dataset, keep: torch.Tensor):
        self.ds, self.keep = ds, keep

    def __len__(self) -> int:
        return len(self.ds)

    def __getitem__(self, i: int):
        x, mask, t, e = self.ds[i]
        return x, mask * self.keep, t, e


def item_groups(ds: Dataset) -> np.ndarray | None:
    """Per-item site codes through Subset / ConcatDataset wrappers (None if any part lacks them)."""
    if isinstance(ds, Subset):
        g = item_groups(ds.dataset)
        return None if g is None else g[np.asarray(ds.indices)]
    if isinstance(ds, ConcatDataset):
        parts = [item_groups(d) for d in ds.datasets]
        return None if any(p is None for p in parts) else np.concatenate(parts)
    return getattr(ds, "groups", None)


def inner_split(n: int, fraction: float, seed: int, groups: np.ndarray | None = None,
                min_groups: int = 5) -> tuple[list[int], list[int]]:
    """(train, val) indices. With enough groups, val is whole groups (sites), else patients."""
    rng = np.random.default_rng(seed)
    if groups is not None and len(np.unique(groups)) >= min_groups:
        val_groups: list = []
        for g in rng.permutation(np.unique(groups)):
            if np.isin(groups, val_groups).sum() >= fraction * n:
                break
            val_groups.append(g)
        is_val = np.isin(groups, val_groups)
    else:
        is_val = np.zeros(n, dtype=bool)
        is_val[rng.permutation(n)[: max(1, int(round(n * fraction)))]] = True
    return np.flatnonzero(~is_val).tolist(), np.flatnonzero(is_val).tolist()


def client_inner_split(train_ds: Dataset, cfg: dict) -> tuple[list[int], list[int]]:
    """The FL client's split of its own training data: it trains on the first part and keeps
    the second (whole tissue source sites when known) for choosing λ afterwards."""
    return inner_split(len(train_ds), INNER_FRACTION, cfg["train"]["seed"] + 1,
                       item_groups(train_ds))


def federated_lambda(model: MuffleNet, sites: list[Dataset], cfg: dict, device: str = "cpu",
                     lambdas: tuple[float, ...] = LAMBDAS) -> tuple[float, dict[float, float]]:
    """Choose λ for an FL residual model by federated evaluation.

    ``sites`` are the clients' training splits. Each client scores every λ on the held-out part
    of its own training data (client_inner_split) and shares only two numbers per λ, the
    concordant and comparable pair counts; λ maximizes the summed (site-stratified) C-index.
    """
    from muffle.metrics import concordance_counts

    totals = {lam: [0.0, 0.0] for lam in lambdas}
    model = model.to(device).eval()
    for train in sites:
        _, va = client_inner_split(train, cfg)
        x, mask, t, e = next(iter(DataLoader(Subset(train, va), batch_size=len(va))))
        x, mask = {m: v.to(device) for m, v in x.items()}, mask.to(device)
        for lam in lambdas:
            model.residual_scale = lam
            with torch.no_grad():
                n, d = concordance_counts(t, e, model(x, mask).cpu())
            totals[lam][0] += n
            totals[lam][1] += d
    scores = {lam: n / d if d else float("nan") for lam, (n, d) in totals.items()}
    best = max(lambdas, key=lambda lam: (round(scores[lam], 3), -lam))
    model.residual_scale = best
    return best, scores


def _loader(ds: Dataset, cfg: dict) -> DataLoader:
    bs = cfg["train"]["batch_size"]
    return DataLoader(ds, batch_size=bs, shuffle=True, drop_last=len(ds) > bs)


def two_stage(train_ds: Dataset, cfg: dict, device: str = "cpu") -> MuffleNet:
    """Anchor first, then the residual layers with the anchor frozen (residual_scale = 1)."""
    torch.manual_seed(cfg["train"]["seed"])
    model = MuffleNet.from_config({**cfg, "model": {**cfg["model"], "residual_scale": 1.0}})
    anchor = [m for m in model.names if m in model.always_keep]
    if model.fusion != "additive" or not anchor:
        raise ValueError("the residual model needs model.fusion: additive and model.always_keep")
    t = cfg["train"]
    keep_anchor = 1 - model._droppable.clone()  # 1 for the anchor's mask columns
    train_epochs(model, _loader(MaskedView(train_ds, keep_anchor), cfg), t["epochs"], t["lr"],
                 t["weight_decay"], device)
    frozen = [p for m in anchor for p in (*model.encoders[m].parameters(),
                                          *model.heads[m].parameters())]
    for p in frozen:
        p.requires_grad_(False)
    train_epochs(model, _loader(train_ds, cfg), t["epochs"], t["lr"], t["weight_decay"], device)
    for p in frozen:
        p.requires_grad_(True)
    return model


def fit_residual(train_ds: Dataset, cfg: dict, device: str = "cpu",
                 lambdas: tuple[float, ...] = LAMBDAS, inner_fraction: float = 0.2,
                 inner_splits: int = 3):
    """Returns (model, chosen λ, {λ: mean inner-validation C-index}).

    λ is scored on ``inner_splits`` different inner splits and averaged: one small held-out
    set of sites is too noisy to choose from.
    """
    groups = item_groups(train_ds)
    scores = {lam: 0.0 for lam in lambdas}
    for k in range(inner_splits):
        tr, va = inner_split(len(train_ds), inner_fraction, cfg["train"]["seed"] + 1 + k, groups)
        model = two_stage(Subset(train_ds, tr), cfg, device)
        for lam in lambdas:
            model.residual_scale = lam
            scores[lam] += evaluate(model, Subset(train_ds, va), device)["c_index"] / inner_splits
    best = max(lambdas, key=lambda lam: (round(scores[lam], 3), -lam))  # ties: smaller λ
    final = two_stage(train_ds, cfg, device)
    final.residual_scale = best
    return final.eval(), best, scores

"""Modality encoders + masked late fusion + DeepSurv-style Cox head.

LayerNorm (not BatchNorm) is used so plain FedAvg works without FedBN tricks; switching to
BatchNorm + keeping BN stats local is a personalization experiment for later.
"""

from __future__ import annotations

import torch
from torch import nn


class MLPEncoder(nn.Module):
    def __init__(self, in_dim: int, hidden: int, latent: int, dropout: float):
        super().__init__()
        self.net = nn.Sequential(
            nn.Dropout(dropout / 2),  # input dropout helps on wide omic vectors
            nn.Linear(in_dim, hidden),
            nn.LayerNorm(hidden),
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(hidden, latent),
            nn.LayerNorm(latent),
            nn.GELU(),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(x)


class MuffleNet(nn.Module):
    """forward(inputs: {modality: [B, d_m]}, mask: [B, M]) -> log-risk [B].

    fusion="concat": one head over all modality embeddings (+ the mask).
    fusion="additive": one small Cox head per modality; log-risk is the sum over the modalities
    a patient has, plus a learned offset for each missing one. A weak, noisy layer can then only
    add its own term instead of diluting a strong one (e.g. clinical stage on TCGA-BRCA).

    modality_dropout hides each available modality with this probability during training, except
    those in ``always_keep`` (e.g. clinical data every patient has; dropping it would teach the
    model to lean on the weaker layers).

    Constructor arguments are stored as same-named attributes so NVFlare's job API can
    serialize the initial model.
    """

    def __init__(
        self,
        modality_dims: dict[str, int],
        hidden: int = 256,
        latent: int = 64,
        head_hidden: int = 64,
        dropout: float = 0.2,
        modality_dropout: float = 0.0,
        fusion: str = "concat",
        always_keep: list[str] | tuple[str, ...] = (),
    ):
        super().__init__()
        if fusion not in ("concat", "additive"):
            raise ValueError(f"unknown fusion {fusion!r}")
        self.modality_dims = dict(modality_dims)
        self.hidden, self.latent, self.head_hidden = hidden, latent, head_hidden
        self.dropout, self.modality_dropout = dropout, modality_dropout
        self.fusion = fusion
        self.always_keep = list(always_keep)
        self.names = list(self.modality_dims)
        self.register_buffer("_droppable", torch.tensor(
            [m not in self.always_keep for m in self.names], dtype=torch.float32),
            persistent=False)

        small = lambda d: min(hidden, max(16, 4 * d))  # noqa: E731  clinical gets a narrow encoder
        self.encoders = nn.ModuleDict(
            {m: MLPEncoder(d, small(d), latent, dropout) for m, d in self.modality_dims.items()}
        )
        n = len(self.names)

        def cox_head(in_dim: int) -> nn.Sequential:
            return nn.Sequential(
                nn.Linear(in_dim, head_hidden),
                nn.GELU(),
                nn.Dropout(dropout),
                nn.Linear(head_hidden, 1, bias=False),  # Cox models have no intercept
            )

        if fusion == "concat":
            self.head = cox_head(n * latent + n)  # + mask so the head knows what's missing
        else:
            self.heads = nn.ModuleDict({m: cox_head(latent) for m in self.names})
            self.missing = nn.Parameter(torch.zeros(n))  # log-risk offset per absent modality

    def _train_time_mask(self, mask: torch.Tensor) -> torch.Tensor:
        if not self.training or self.modality_dropout <= 0:
            return mask
        keep = (torch.rand_like(mask) > self.modality_dropout).float()
        keep = torch.maximum(keep, 1 - self._droppable)  # always_keep columns are never hidden
        new = mask * keep
        # never hide every modality a patient has
        empty = new.sum(1) == 0
        new[empty] = mask[empty]
        return new

    def embed(self, inputs: dict[str, torch.Tensor], mask: torch.Tensor) -> torch.Tensor:
        mask = self._train_time_mask(mask)
        zs = [self.encoders[m](inputs[m]) * mask[:, j : j + 1] for j, m in enumerate(self.names)]
        return torch.cat(zs + [mask], dim=1)

    def forward(self, inputs: dict[str, torch.Tensor], mask: torch.Tensor) -> torch.Tensor:
        if self.fusion == "additive":
            mask = self._train_time_mask(mask)
            parts = torch.stack(
                [self.heads[m](self.encoders[m](inputs[m])).squeeze(-1) for m in self.names], 1)
            return (parts * mask + self.missing * (1 - mask)).sum(1)
        return self.head(self.embed(inputs, mask)).squeeze(-1)

    @classmethod
    def from_config(cls, cfg: dict) -> "MuffleNet":
        return cls(cfg["modalities"], **cfg["model"])

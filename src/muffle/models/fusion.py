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
    ):
        super().__init__()
        self.modality_dims = dict(modality_dims)
        self.hidden, self.latent, self.head_hidden = hidden, latent, head_hidden
        self.dropout, self.modality_dropout = dropout, modality_dropout
        self.names = list(self.modality_dims)

        small = lambda d: min(hidden, max(16, 4 * d))  # noqa: E731  clinical gets a narrow encoder
        self.encoders = nn.ModuleDict(
            {m: MLPEncoder(d, small(d), latent, dropout) for m, d in self.modality_dims.items()}
        )
        n = len(self.names)
        self.head = nn.Sequential(
            nn.Linear(n * latent + n, head_hidden),  # + mask so the head knows what's missing
            nn.GELU(),
            nn.Dropout(dropout),
            nn.Linear(head_hidden, 1, bias=False),  # Cox models have no intercept
        )

    def _train_time_mask(self, mask: torch.Tensor) -> torch.Tensor:
        if not self.training or self.modality_dropout <= 0:
            return mask
        keep = (torch.rand_like(mask) > self.modality_dropout).float()
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
        return self.head(self.embed(inputs, mask)).squeeze(-1)

    @classmethod
    def from_config(cls, cfg: dict) -> "MuffleNet":
        return cls(cfg["modalities"], **cfg["model"])

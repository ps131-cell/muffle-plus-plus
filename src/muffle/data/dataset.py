from __future__ import annotations

from pathlib import Path

import numpy as np
import torch
from torch.utils.data import Dataset

from muffle.config import MODALITIES


class MultiOmicDataset(Dataset):
    """Loads one site's ``.npz``. Each item: ({modality: tensor}, mask[M], time, event)."""

    def __init__(self, arrays: dict[str, np.ndarray] | str | Path, modalities: dict[str, int]):
        if not isinstance(arrays, dict):
            with np.load(arrays) as f:
                arrays = {k: f[k] for k in f.files}
        n = len(arrays["time"])
        self.x = {}
        for m, d in modalities.items():
            key = f"x_{m}"
            self.x[m] = torch.as_tensor(
                arrays[key] if key in arrays else np.zeros((n, d), np.float32), dtype=torch.float32
            )
            if self.x[m].shape[1] != d:
                raise ValueError(f"{m}: data has {self.x[m].shape[1]} features, config says {d}")
        cols = [MODALITIES.index(m) for m in modalities]
        self.mask = torch.as_tensor(arrays["mask"][:, cols], dtype=torch.float32)
        self.time = torch.as_tensor(arrays["time"], dtype=torch.float32)
        self.event = torch.as_tensor(arrays["event"], dtype=torch.float32)

    def __len__(self) -> int:
        return len(self.time)

    def __getitem__(self, i: int):
        return {m: x[i] for m, x in self.x.items()}, self.mask[i], self.time[i], self.event[i]

    def split(self, val_fraction: float, seed: int = 0) -> tuple[torch.utils.data.Subset, ...]:
        g = torch.Generator().manual_seed(seed)
        n_val = max(1, int(round(len(self) * val_fraction)))
        perm = torch.randperm(len(self), generator=g).tolist()
        return (
            torch.utils.data.Subset(self, perm[n_val:]),
            torch.utils.data.Subset(self, perm[:n_val]),
        )

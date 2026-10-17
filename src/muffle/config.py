from __future__ import annotations

from pathlib import Path

import yaml

# Canonical modality order; the availability mask columns follow this order.
MODALITIES = ("genomic", "rna", "methylation", "protein", "clinical")

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "default.yaml"


def load_config(path: str | Path | None = None) -> dict:
    with open(path or DEFAULT_CONFIG) as f:
        cfg = yaml.safe_load(f)
    unknown = set(cfg["modalities"]) - set(MODALITIES)
    if unknown:
        raise ValueError(f"Unknown modalities in config: {sorted(unknown)}")
    return cfg

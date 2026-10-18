from __future__ import annotations

from pathlib import Path

import yaml

# Canonical modality order; the availability mask columns follow this order.
MODALITIES = ("genomic", "rna", "methylation", "protein", "clinical")

DEFAULT_CONFIG = Path(__file__).resolve().parents[2] / "configs" / "default.yaml"

# How the pooled cohort is split into FL clients; see muffle.data.partition.
DATA_DEFAULTS = {"partition": "stage-skew", "simulate_gaps": True}


def _merge(base: dict, override: dict) -> dict:
    out = dict(base)
    for k, v in override.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def load_config(path: str | Path | None = None) -> dict:
    """Load a YAML config. ``base: other.yaml`` (relative to this file) is loaded first and
    overridden key by key, so dataset configs only list what differs from default.yaml."""
    path = Path(path or DEFAULT_CONFIG)
    with open(path) as f:
        cfg = yaml.safe_load(f)
    if "base" in cfg:
        cfg = _merge(load_config(path.parent / cfg.pop("base")), cfg)
    cfg["data"] = {**DATA_DEFAULTS, **cfg.get("data", {})}
    unknown = set(cfg["modalities"]) - set(MODALITIES)
    if unknown:
        raise ValueError(f"Unknown modalities in config: {sorted(unknown)}")
    return cfg

"""Non-federated baselines.

  centralized:  pool every site (upper bound FL should approach)
  local-only:   each site trains alone (lower bound FL should beat)

python -m muffle.train_local --data data/synthetic --mode both
python -m muffle.train_local ... --fl-ckpt <FL_global_model.pt>   # add FedAvg, same val splits
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import ConcatDataset, DataLoader

from muffle.config import load_config
from muffle.data.dataset import MultiOmicDataset
from muffle.data.partition import partition_cohort
from muffle.engine import evaluate, train_epochs
from muffle.models import MuffleNet


def site_files(data_dir: Path, n_clients: int) -> list[Path]:
    client_dir = data_dir / f"clients_{n_clients}"
    files = sorted(client_dir.glob("site-*.npz"))
    if len(files) != n_clients:
        with np.load(data_dir / "cohort.npz") as f:
            files = partition_cohort({k: f[k] for k in f.files}, n_clients, client_dir)
    return files


def fit(train_ds, val_ds, cfg, device):
    torch.manual_seed(cfg["train"]["seed"])
    model = MuffleNet.from_config(cfg)
    loader = DataLoader(train_ds, batch_size=cfg["train"]["batch_size"], shuffle=True,
                        drop_last=True)
    train_epochs(model, loader, cfg["train"]["epochs"], cfg["train"]["lr"],
                 cfg["train"]["weight_decay"], device)
    return model, evaluate(model, val_ds, device)


def load_checkpoint(path: Path, cfg: dict) -> MuffleNet:
    """Load outputs/centralized.pt or an NVFlare global model; both store {"model": state_dict}."""
    blob = torch.load(path, map_location="cpu", weights_only=False)
    model = MuffleNet.from_config(blob.get("config") or cfg)
    model.load_state_dict({k: torch.as_tensor(v) for k, v in blob["model"].items()})
    return model


def results_table(results: dict[str, dict[str, float]]) -> str:
    """Markdown table: one row per site, one column per training mode."""
    sites = list(next(iter(results.values())))
    lines = ["| site | " + " | ".join(results) + " |", "|---" * (len(results) + 1) + "|"]
    lines += [f"| {s} | " + " | ".join(f"{r[s]:.3f}" for r in results.values()) + " |"
              for s in sites]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, default=Path("data/synthetic"))
    p.add_argument("--config", default=None)
    p.add_argument("--n-clients", type=int, default=3)
    p.add_argument("--mode", choices=["centralized", "local", "both"], default="both")
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    p.add_argument("--save", type=Path, default=Path("outputs/centralized.pt"))
    p.add_argument("--fl-ckpt", type=Path, default=None,
                   help="NVFlare global model to score on the same per-site validation splits")
    args = p.parse_args(argv)
    cfg = load_config(args.config)

    splits = []
    for f in site_files(args.data, args.n_clients):
        ds = MultiOmicDataset(f, cfg["modalities"])
        splits.append((f.stem, *ds.split(cfg["train"]["val_fraction"], cfg["train"]["seed"])))

    results = {}
    if args.mode in ("centralized", "both"):
        model, _ = fit(ConcatDataset([s[1] for s in splits]), splits[0][2], cfg, args.device)
        results["centralized"] = {name: evaluate(model, va, args.device)["c_index"]
                                  for name, _, va in splits}
        args.save.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"model": model.cpu().state_dict(), "config": cfg}, args.save)
        print(f"saved centralized model -> {args.save}")
    if args.mode in ("local", "both"):
        results["local_only"] = {name: fit(tr, va, cfg, args.device)[1]["c_index"]
                                 for name, tr, va in splits}
    if args.fl_ckpt:
        model = load_checkpoint(args.fl_ckpt, cfg)
        results["fedavg"] = {name: evaluate(model, va, args.device)["c_index"]
                             for name, _, va in splits}
    print(json.dumps(results, indent=2))
    print(results_table(results))
    return results


if __name__ == "__main__":
    main()

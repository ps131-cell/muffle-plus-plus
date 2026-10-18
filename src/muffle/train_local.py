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

from muffle.config import DATA_DEFAULTS, load_config
from muffle.data.dataset import MultiOmicDataset
from muffle.data.partition import partition_cohort
from muffle.engine import evaluate, train_epochs
from muffle.models import MuffleNet


def client_dir(data_dir: Path, n_clients: int, cfg: dict | None = None) -> Path:
    """Where the per-client site-k.npz files live; the name encodes how they were split."""
    data = {**DATA_DEFAULTS, **(cfg or {}).get("data", {})}  # old checkpoints have no "data"
    gaps = "" if data["simulate_gaps"] else "_nogaps"
    return Path(data_dir) / f"clients_{n_clients}_{data['partition']}{gaps}"


def site_files(data_dir: Path, n_clients: int, cfg: dict | None = None) -> list[Path]:
    """Per-client files, partitioning data_dir/cohort.npz first if needed (cfg["data"])."""
    data = {**DATA_DEFAULTS, **(cfg or {}).get("data", {})}
    out = client_dir(data_dir, n_clients, cfg)
    files = sorted(out.glob("site-*.npz"))
    if len(files) != n_clients:
        with np.load(Path(data_dir) / "cohort.npz") as f:
            gaps = None if data["simulate_gaps"] else [[]]
            files = partition_cohort({k: f[k] for k in f.files}, n_clients, out,
                                     mode=data["partition"], gaps=gaps)
    return files


def heldout_c_index(model: MuffleNet, data_dir: Path, n_clients: int, cfg: dict) -> dict:
    """C-index per site on the validation splits `make compare` scores (never trained on)."""
    out = {}
    for f in site_files(Path(data_dir), n_clients, cfg):
        _, val = MultiOmicDataset(f, cfg["modalities"]).split(
            cfg["train"]["val_fraction"], cfg["train"]["seed"])
        out[f.stem] = evaluate(model, val)["c_index"]
    return out


def fit(train_ds, val_ds, cfg, device):
    torch.manual_seed(cfg["train"]["seed"])
    model = MuffleNet.from_config(cfg)
    # keep the last partial batch for small sites, else a site with < batch_size train patients
    # would take no optimizer steps at all
    loader = DataLoader(train_ds, batch_size=cfg["train"]["batch_size"], shuffle=True,
                        drop_last=len(train_ds) > cfg["train"]["batch_size"])
    train_epochs(model, loader, cfg["train"]["epochs"], cfg["train"]["lr"],
                 cfg["train"]["weight_decay"], device)
    return model, evaluate(model, val_ds, device)


def load_checkpoint(path: Path, cfg: dict) -> MuffleNet:
    """Load outputs/centralized.pt or an NVFlare global model; both store {"model": state_dict}."""
    return load_model(path, cfg)[0]


def load_model(path: Path, config: dict | str | Path | None = None) -> tuple[MuffleNet, dict]:
    """(model in eval mode, its config) from a checkpoint.

    Checkpoints from train_local and ``fedavg_job.py --save`` carry their config; a raw NVFlare
    FL_global_model.pt does not, so ``config`` (a dict or YAML path; default config if None)
    must describe the same architecture.
    """
    blob = torch.load(path, map_location="cpu", weights_only=False)
    cfg = blob.get("config") or (config if isinstance(config, dict) else load_config(config))
    model = MuffleNet.from_config(cfg)
    model.load_state_dict({k: torch.as_tensor(v) for k, v in blob["model"].items()})
    return model.eval(), cfg


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
    for f in site_files(args.data, args.n_clients, cfg):
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

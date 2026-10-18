"""Training script executed at each FL site (NVFlare Client API).

Each round: receive global weights -> evaluate them on this site's validation split (that's
the number that matters: how good is the *shared* model here) -> train locally -> send back.
Raw data never leaves this process; only ``model.state_dict()`` does.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import nvflare.client as flare
import torch
from torch.utils.data import DataLoader

from muffle.config import load_config
from muffle.data.dataset import MultiOmicDataset
from muffle.engine import evaluate, train_epochs
from muffle.models import MuffleNet


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", required=True, help="folder with site-1.npz, site-2.npz, ...")
    p.add_argument("--config", default=None)
    p.add_argument("--local-epochs", type=int, default=None)
    p.add_argument("--prox-mu", type=float, default=None)
    p.add_argument("--seed", type=int, default=None, help="overrides train.seed (val split)")
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.seed is not None:
        cfg["train"]["seed"] = args.seed
        torch.manual_seed(args.seed)
    epochs = args.local_epochs or cfg["train"]["local_epochs"]
    prox_mu = cfg["fl"]["prox_mu"] if args.prox_mu is None else args.prox_mu
    device = "cuda" if torch.cuda.is_available() else "cpu"

    flare.init()
    site = flare.get_site_name()  # "site-1", "site-2", ...
    ds = MultiOmicDataset(Path(args.data_dir) / f"{site}.npz", cfg["modalities"])
    train_ds, val_ds = ds.split(cfg["train"]["val_fraction"], cfg["train"]["seed"])
    loader = DataLoader(train_ds, batch_size=cfg["train"]["batch_size"], shuffle=True,
                        drop_last=len(train_ds) > cfg["train"]["batch_size"])
    model = MuffleNet.from_config(cfg)
    print(f"[{site}] n_train={len(train_ds)} n_val={len(val_ds)} "
          f"modalities={ds.mask.mean(0).round(decimals=2).tolist()} device={device}")

    while flare.is_running():
        received = flare.receive()
        global_params = {k: torch.as_tensor(v) for k, v in received.params.items()}
        model.load_state_dict(global_params)
        global_metrics = evaluate(model, val_ds, device)
        print(f"[{site}] round {received.current_round}: global C-index on local val = "
              f"{global_metrics['c_index']:.3f}")

        stats = train_epochs(
            model, loader, epochs, cfg["train"]["lr"], cfg["train"]["weight_decay"], device,
            prox_mu=prox_mu, global_params=global_params,
        )
        flare.send(
            flare.FLModel(
                params={k: v.cpu() for k, v in model.state_dict().items()},
                metrics={"c_index": global_metrics["c_index"],
                         "val_loss": global_metrics["val_loss"],
                         "train_loss": stats["train_loss"]},
                meta={"NUM_STEPS_CURRENT_ROUND": stats["steps"]},
            )
        )


if __name__ == "__main__":
    main()

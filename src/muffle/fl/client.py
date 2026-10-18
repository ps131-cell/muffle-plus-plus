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
from torch.utils.data import DataLoader, Subset

from muffle.config import load_config
from muffle.data.dataset import MultiOmicDataset
from muffle.engine import evaluate, train_epochs
from muffle.models import MuffleNet
from muffle.residual import MaskedView, client_inner_split


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data-dir", required=True, help="folder with site-1.npz, site-2.npz, ...")
    p.add_argument("--config", default=None)
    p.add_argument("--local-epochs", type=int, default=None)
    p.add_argument("--prox-mu", type=float, default=None)
    p.add_argument("--seed", type=int, default=None, help="overrides train.seed (val split)")
    p.add_argument("--residual-from", type=int, default=None,
                   help="clinical-anchored residual model (muffle.residual): train only the "
                        "anchor before this round, then the other layers with the anchor frozen")
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
    residual = args.residual_from is not None
    if residual:  # keep some of our own sites out of training, for choosing λ afterwards
        train_ds = Subset(train_ds, client_inner_split(train_ds, cfg)[0])
    loader = DataLoader(train_ds, batch_size=cfg["train"]["batch_size"], shuffle=True,
                        drop_last=len(train_ds) > cfg["train"]["batch_size"])
    model = MuffleNet.from_config(cfg)
    anchor_loader, anchor_params = None, []
    if residual:
        anchor_loader = DataLoader(MaskedView(train_ds, 1 - model._droppable.clone()),
                                   batch_size=cfg["train"]["batch_size"], shuffle=True,
                                   drop_last=len(train_ds) > cfg["train"]["batch_size"])
        anchor_params = [p for m in model.always_keep for p in
                         (*model.encoders[m].parameters(), *model.heads[m].parameters())]
    print(f"[{site}] n_train={len(train_ds)} n_val={len(val_ds)} "
          f"modalities={ds.mask.mean(0).round(decimals=2).tolist()} device={device}")

    while flare.is_running():
        received = flare.receive()
        global_params = {k: torch.as_tensor(v) for k, v in received.params.items()}
        model.load_state_dict(global_params)
        global_metrics = evaluate(model, val_ds, device)
        print(f"[{site}] round {received.current_round}: global C-index on local val = "
              f"{global_metrics['c_index']:.3f}")

        anchor_phase = residual and received.current_round < args.residual_from
        for p in anchor_params:  # frozen once the residual phase starts
            p.requires_grad_(anchor_phase)
        stats = train_epochs(
            model, anchor_loader if anchor_phase else loader, epochs, cfg["train"]["lr"],
            cfg["train"]["weight_decay"], device,
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

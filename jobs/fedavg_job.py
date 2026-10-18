"""Build the MuFFLe++ FedAvg/FedProx job with NVFlare's Recipe API and run it in the simulator.

python jobs/fedavg_job.py --data data/synthetic --n-clients 3 --rounds 10
python jobs/fedavg_job.py ... --prox-mu 0.01        # FedProx (proximal term in local training)
python jobs/fedavg_job.py ... --gpu 0               # put simulated clients on GPU 0 (Nebius)

The same recipe object can later be executed with PocEnv / ProdEnv for a real multi-machine run.
"""

from __future__ import annotations

import argparse
from pathlib import Path

from nvflare.app_opt.pt.recipes.fedavg import FedAvgRecipe
from nvflare.recipe.sim_env import SimEnv

from muffle.config import load_config
from muffle.train_local import client_dir, site_files

CLIENT_SCRIPT = Path(__file__).resolve().parents[1] / "src" / "muffle" / "fl" / "client.py"


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--data", type=Path, default=Path("data/synthetic"))
    p.add_argument("--config", default=None)
    p.add_argument("--n-clients", type=int, default=3)
    p.add_argument("--rounds", type=int, default=10)
    p.add_argument("--local-epochs", type=int, default=None)
    p.add_argument("--prox-mu", type=float, default=None)
    p.add_argument("--seed", type=int, default=None, help="overrides train.seed (val split)")
    p.add_argument("--client-dir", type=Path, default=None,
                   help="use these site-1..site-n.npz instead of partitioning --data")
    p.add_argument("--workspace", default="workspaces")
    p.add_argument("--gpu", default=None, help="e.g. 0, or 0,1 to spread clients over GPUs")
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.client_dir:
        data_dir = args.client_dir.resolve()
        n = len(list(data_dir.glob("site-*.npz")))
        if n != args.n_clients:
            raise SystemExit(f"{data_dir} has {n} site files, --n-clients is {args.n_clients}")
    else:
        site_files(args.data, args.n_clients, cfg)  # partitions the cohort if not already done
        data_dir = client_dir(args.data, args.n_clients, cfg).resolve()

    train_args = f"--data-dir {data_dir}"
    if args.config:
        train_args += f" --config {Path(args.config).resolve()}"
    if args.local_epochs:
        train_args += f" --local-epochs {args.local_epochs}"
    if args.prox_mu is not None:
        train_args += f" --prox-mu {args.prox_mu}"
    if args.seed is not None:
        train_args += f" --seed {args.seed}"

    recipe = FedAvgRecipe(
        name="muffle_fedavg",
        # dict form: the server rebuilds the model from its import path + constructor args
        model={"class_path": "muffle.models.fusion.MuffleNet",
               "args": {"modality_dims": cfg["modalities"], **cfg["model"]}},
        min_clients=args.n_clients,
        num_rounds=args.rounds,
        train_script=str(CLIENT_SCRIPT),
        train_args=train_args,
        key_metric="c_index",  # keep the best global model by validation C-index
        key_metric_mode="max",
    )

    env_kwargs = dict(num_clients=args.n_clients, num_threads=args.n_clients,
                      workspace_root=str(Path(args.workspace).resolve()))
    if args.gpu is not None:
        env_kwargs["gpu_config"] = args.gpu
    run = recipe.execute(env=SimEnv(**env_kwargs))
    print("status:", run.get_status())
    print("result:", run.get_result())


if __name__ == "__main__":
    main()

"""Write a synthetic pooled cohort to <out>/cohort.npz (partitioning happens at train time)."""

import argparse
from pathlib import Path

import numpy as np

from muffle.config import load_config
from muffle.data.synthetic import make_cohort

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--out", type=Path, default=Path("data/synthetic"))
    p.add_argument("--n-patients", type=int, default=900)
    p.add_argument("--config", default=None)
    p.add_argument("--seed", type=int, default=0)
    args = p.parse_args()

    cohort = make_cohort(args.n_patients, load_config(args.config)["modalities"], seed=args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.out / "cohort.npz", **cohort)
    print(f"{args.n_patients} patients, event rate {cohort['event'].mean():.2f} "
          f"-> {args.out / 'cohort.npz'}")

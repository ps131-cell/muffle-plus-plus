"""Repeated comparison on one cohort: centralized vs local-only vs FedAvg, plus single-modality
baselines, over several seeds.

python -m muffle.experiment --data data/tcga_brca --config configs/tcga_brca.yaml --seeds 0 1 2 3 4
python -m muffle.experiment ... --methods centralized local_only     # skip FedAvg (fast)

Per seed, every client's patients are split into train/val with that seed and every method is
scored on the same validation patients. FedAvg runs the real NVFlare simulator job
(jobs/fedavg_job.py) and is scored with its final global model, after fl.rounds rounds
(default: as many passes over each patient as the baselines, epochs / local_epochs).

"pooled" is the site-stratified C-index (metrics.stratified_concordance): patients are only
paired within a site, so per-site local-only models with different risk scales pool fairly.
Results go to outputs/experiments/<name>.json; the printed table is mean ± sd over seeds.

--loso adds leave-one-site-out: each site in turn is held out completely; centralized, FedAvg
and the single-modality models train on the other sites' training splits, local-only is every
other site's own model, and all are scored on every patient of the held-out site (a hospital
that never shared data). Whole held-out sites give much tighter estimates than val splits.
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import ConcatDataset, DataLoader

from muffle.config import load_config
from muffle.data.dataset import MultiOmicDataset
from muffle.metrics import concordance_counts, stratified_concordance
from muffle.residual import federated_lambda, fit_residual
from muffle.train_local import fit, load_checkpoint, site_files

ROOT = Path(__file__).resolve().parents[2]
FL_JOB = ROOT / "jobs" / "fedavg_job.py"
FL_CKPT = Path("muffle_fedavg/server/simulate_job/app_server/FL_global_model.pt")
METHODS = ("centralized", "local_only", "fedavg", "single_modality", "residual",
           "fedavg_residual")


def fl_rounds(cfg: dict) -> int:
    """fl.rounds, else as many passes over the data as the baselines get."""
    return cfg["fl"].get("rounds") or max(1, cfg["train"]["epochs"] // cfg["train"]["local_epochs"])


def with_seed(cfg: dict, seed: int) -> dict:
    cfg = copy.deepcopy(cfg)
    cfg["train"]["seed"] = seed
    return cfg


def load_splits(files: list[Path], cfg: dict) -> list[tuple[str, object, object]]:
    """[(site, train, val)] using cfg's val_fraction and seed (same split as the FL client)."""
    out = []
    for f in files:
        ds = MultiOmicDataset(f, cfg["modalities"])
        out.append((f.stem, *ds.split(cfg["train"]["val_fraction"], cfg["train"]["seed"])))
    return out


@torch.no_grad()
def site_counts(model: torch.nn.Module, ds, device: str = "cpu") -> tuple[float, float]:
    model.to(device).eval()
    x, mask, t, e = next(iter(DataLoader(ds, batch_size=len(ds))))
    risk = model({m: v.to(device) for m, v in x.items()}, mask.to(device)).cpu()
    return concordance_counts(t, e, risk)


def score(counts: dict[str, tuple[float, float]]) -> dict[str, float]:
    """Per-site C-index plus the site-stratified pooled C-index."""
    out = {s: (n / d if d else float("nan")) for s, (n, d) in counts.items()}
    out["pooled"] = stratified_concordance(counts.values())
    return out


def centralized(splits, cfg, device) -> dict[str, float]:
    model, _ = fit(ConcatDataset([tr for _, tr, _ in splits]), splits[0][2], cfg, device)
    return score({s: site_counts(model, va, device) for s, _, va in splits})


def residual(splits, cfg, device) -> dict[str, float]:
    """Clinical-anchored residual model (muffle.residual), trained centrally; also returns λ."""
    model, lam, _ = fit_residual(ConcatDataset([tr for _, tr, _ in splits]), cfg, device)
    return {**score({s: site_counts(model, va, device) for s, _, va in splits}), "lambda": lam}


def local_only(splits, cfg, device) -> dict[str, float]:
    return score({s: site_counts(fit(tr, va, cfg, device)[0], va, device)
                  for s, tr, va in splits})


def single_modality(files, cfg, device) -> dict[str, dict[str, float]]:
    """Centralized model on one data layer at a time (same patients and splits)."""
    out = {}
    for m, d in cfg["modalities"].items():
        cfg_m = copy.deepcopy(cfg)
        cfg_m["modalities"] = {m: d}
        out[f"only_{m}"] = centralized(load_splits(files, cfg_m), cfg_m, device)
    return out


def run_fl_job(data: Path, config: str | None, n_clients: int, rounds: int, seed: int,
               workspace: Path, cfg: dict, clients: Path | None = None,
               residual: bool = False) -> torch.nn.Module:
    """Run jobs/fedavg_job.py in the NVFlare simulator; return its final global model."""
    shutil.rmtree(workspace, ignore_errors=True)  # a fresh simulator workspace per run
    cmd = [sys.executable, str(FL_JOB), "--data", str(data), "--n-clients", str(n_clients),
           "--rounds", str(rounds), "--seed", str(seed), "--workspace", str(workspace)]
    if config:
        cmd += ["--config", str(config)]
    if clients:
        cmd += ["--client-dir", str(clients)]
    if residual:
        cmd += ["--residual"]
    r = subprocess.run(cmd, capture_output=True, text=True, cwd=ROOT)
    ckpt = workspace / FL_CKPT
    if r.returncode or not ckpt.exists():
        raise RuntimeError(f"FL job failed for seed {seed}:\n"
                           f"{r.stdout[-3000:]}\n{r.stderr[-3000:]}")
    return load_checkpoint(ckpt, cfg)


def fedavg(data: Path, config: str | None, n_clients: int, rounds: int, seed: int,
           workspace: Path, splits, cfg, device) -> dict[str, float]:
    model = run_fl_job(data, config, n_clients, rounds, seed, workspace, cfg)
    return score({s: site_counts(model, va, device) for s, _, va in splits})


def fedavg_residual(data: Path, config: str | None, n_clients: int, rounds: int, seed: int,
                    workspace: Path, splits, cfg, device) -> dict[str, float]:
    """Two-phase FL residual model; λ by federated evaluation on the clients' own held-out
    sites (muffle.residual.federated_lambda)."""
    model = run_fl_job(data, config, n_clients, rounds, seed, workspace, cfg, residual=True)
    lam, _ = federated_lambda(model, [tr for _, tr, _ in splits], cfg, device)
    return {**score({s: site_counts(model, va, device) for s, _, va in splits}), "lambda": lam}


def leave_one_site_out(files: list[Path], cfg: dict, methods: list[str], device: str,
                       fl: dict | None = None) -> dict[str, dict[str, float]]:
    """Hold out each site in turn; score on all of its patients. ``fl`` holds the
    run_fl_job arguments (data, config, rounds, seed, workspace) when FedAvg is wanted."""
    splits = load_splits(files, cfg)
    counts: dict[str, dict[str, tuple[float, float]]] = {m: {} for m in methods}
    single = {}  # modality -> (cfg with only that modality, its splits): same patients/indices
    if "single_modality" in methods:
        for m, d in cfg["modalities"].items():
            cfg_m = copy.deepcopy(cfg)
            cfg_m["modalities"] = {m: d}
            single[m] = (cfg_m, load_splits(files, cfg_m))
    lambdas: list[float] = []  # residual model's λ per held-out site
    fl_lambdas: list[float] = []
    for held, f in zip([s for s, _, _ in splits], files, strict=True):
        test = MultiOmicDataset(f, cfg["modalities"])
        others = [(s, tr, va) for s, tr, va in splits if s != held]
        if "centralized" in methods:
            model, _ = fit(ConcatDataset([tr for _, tr, _ in others]), others[0][2], cfg, device)
            counts["centralized"][held] = site_counts(model, test, device)
        if "residual" in methods:
            model, lam, _ = fit_residual(ConcatDataset([tr for _, tr, _ in others]), cfg, device)
            counts["residual"][held] = site_counts(model, test, device)
            lambdas.append(lam)
        if "local_only" in methods:  # every other hospital's own model, pairs summed = mean
            per = [site_counts(fit(tr, va, cfg, device)[0], test, device) for _, tr, va in others]
            counts["local_only"][held] = (sum(n for n, _ in per), sum(d for _, d in per))
        clients = None
        if fl and {"fedavg", "fedavg_residual"} & set(methods):
            clients = fl["workspace"] / f"clients-without-{held}"
            shutil.rmtree(clients, ignore_errors=True)
            clients.mkdir(parents=True)
            names = [s for s, _, _ in splits]
            for k, (s, _, _) in enumerate(others, 1):  # NVFlare site names are site-1..site-n
                shutil.copy(files[names.index(s)], clients / f"site-{k}.npz")
        if "fedavg" in methods and fl:
            model = run_fl_job(fl["data"], fl["config"], len(others), fl["rounds"], fl["seed"],
                               fl["workspace"] / f"without-{held}", cfg, clients)
            counts["fedavg"][held] = site_counts(model, test, device)
        if "fedavg_residual" in methods and fl:
            model = run_fl_job(fl["data"], fl["config"], len(others), fl["rounds"], fl["seed"],
                               fl["workspace"] / f"residual-without-{held}", cfg, clients,
                               residual=True)
            lam, _ = federated_lambda(model, [tr for _, tr, _ in others], cfg, device)
            counts["fedavg_residual"][held] = site_counts(model, test, device)
            fl_lambdas.append(lam)
        for m, (cfg_m, splits_m) in single.items():
            train = ConcatDataset([tr for s, tr, _ in splits_m if s != held])
            model, _ = fit(train, splits_m[0][2], cfg_m, device)
            counts.setdefault(f"only_{m}", {})[held] = site_counts(
                model, MultiOmicDataset(f, cfg_m["modalities"]), device)
    out = {m: score(c) for m, c in counts.items() if c}
    if lambdas:
        out["residual"]["lambda"] = float(np.mean(lambdas))
    if fl_lambdas:
        out["fedavg_residual"]["lambda"] = float(np.mean(fl_lambdas))
    return out


def site_summary(files: list[Path]) -> dict[str, dict[str, int]]:
    out = {}
    for f in files:
        with np.load(f) as z:
            out[f.stem] = {"patients": len(z["time"]), "deaths": int(z["event"].sum())}
    return out


def summarize(runs: dict[int, dict[str, dict[str, float]]], sites: dict) -> str:
    """Markdown table: mean ± sd over seeds, one row per method."""
    methods = list(next(iter(runs.values())))
    cols = ["pooled", *sites]
    head = ["method", "pooled"] + [f"{s} (n={v['patients']}, {v['deaths']} deaths)"
                                   for s, v in sites.items()]
    lines = ["| " + " | ".join(head) + " |", "|---" * len(head) + "|"]
    for m in methods:
        cells = []
        for c in cols:
            v = np.array([runs[s][m][c] for s in runs], dtype=float)
            v = v[~np.isnan(v)]
            cells.append("n/a" if not len(v) else f"{v.mean():.3f}" if len(v) == 1
                         else f"{v.mean():.3f} ± {v.std(ddof=1):.3f}")
        lines.append(f"| {m} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=Path("data/synthetic"))
    p.add_argument("--config", default=None)
    p.add_argument("--n-clients", type=int, default=3)
    p.add_argument("--seeds", type=int, nargs="+", default=[0, 1, 2])
    p.add_argument("--rounds", type=int, default=None,
                   help="default: fl.rounds, else epochs / local_epochs")
    p.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    p.add_argument("--loso", action="store_true", help="also run leave-one-site-out")
    p.add_argument("--name", default=None, help="default: <data dir>_<n>clients")
    p.add_argument("--out", type=Path, default=Path("outputs/experiments"))
    p.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu")
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    rounds = args.rounds or fl_rounds(cfg)
    if not (cfg["model"].get("fusion") == "additive" and cfg["model"].get("always_keep")):
        skip = [m for m in args.methods if m in ("residual", "fedavg_residual")]
        if skip:
            args.methods = [m for m in args.methods if m not in skip]
            print(f"skipping {skip}: needs model.fusion: additive and model.always_keep")
    name = args.name or f"{args.data.name}_{args.n_clients}clients"
    files = site_files(args.data, args.n_clients, cfg)
    sites = site_summary(files)
    print(f"{name}: {sites}", flush=True)

    runs: dict[int, dict[str, dict[str, float]]] = {}
    loso_runs: dict[int, dict[str, dict[str, float]]] = {}
    for seed in args.seeds:
        t0, cfg_s = time.time(), with_seed(cfg, seed)
        ws = (Path("workspaces/experiments") / name / f"seed{seed}").resolve()
        splits = load_splits(files, cfg_s)
        res: dict[str, dict[str, float]] = {}
        if "centralized" in args.methods:
            res["centralized"] = centralized(splits, cfg_s, args.device)
        if "local_only" in args.methods:
            res["local_only"] = local_only(splits, cfg_s, args.device)
        if "fedavg" in args.methods:
            res["fedavg"] = fedavg(args.data, args.config, args.n_clients, rounds, seed, ws,
                                   splits, cfg_s, args.device)
        if "single_modality" in args.methods:
            res.update(single_modality(files, cfg_s, args.device))
        if "residual" in args.methods:
            res["residual"] = residual(splits, cfg_s, args.device)
        if "fedavg_residual" in args.methods:
            res["fedavg_residual"] = fedavg_residual(args.data, args.config, args.n_clients,
                                                     rounds, seed, ws, splits, cfg_s, args.device)
        runs[seed] = res
        pooled = ", ".join(f"{m} {r['pooled']:.3f}" for m, r in res.items())
        print(f"seed {seed} ({time.time() - t0:.0f}s): pooled C-index {pooled}", flush=True)
        if args.loso:
            t0 = time.time()
            fl = dict(data=args.data, config=args.config, rounds=rounds, seed=seed, workspace=ws)
            loso_runs[seed] = leave_one_site_out(files, cfg_s, args.methods, args.device, fl)
            pooled = ", ".join(f"{m} {r['pooled']:.3f}" for m, r in loso_runs[seed].items())
            print(f"seed {seed} leave-one-site-out ({time.time() - t0:.0f}s): {pooled}",
                  flush=True)

    table = summarize(runs, sites)
    loso_table = summarize(loso_runs, sites) if loso_runs else None
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"{name}.json"
    path.write_text(json.dumps({"data": str(args.data), "config": args.config,
                                "n_clients": args.n_clients, "fl_rounds": rounds,
                                "sites": sites, "runs": runs, "table": table,
                                "loso_runs": loso_runs, "loso_table": loso_table}, indent=1))
    print("Per-site validation splits (C-index, mean ± sd over seeds)\n" + table)
    if loso_table:
        print("\nLeave one site out (column = held-out site, all its patients)\n" + loso_table)
    print(f"-> {path}")
    return runs


if __name__ == "__main__":
    main()

"""Calibration and fairness checks on cross-site predictions (#5).

python -m muffle.calibration --data data/tcga_brca --config configs/tcga_brca.yaml --seed 0

Every patient gets a prediction from a model that never saw their hospital: each FL client
(hospital) is held out in turn, the model trains on the other hospitals' training splits, and
it scores every patient of the held-out one. A Cox model only gives a relative log-risk r, so
survival curves use the Breslow baseline hazard of that fold's training patients:
S(t | x) = exp(-H0(t) · exp(r)). In a real federation H0 can be built from per-site binned
risk-set sums; here it is computed directly.

Reported, pooled over all patients:
  * time-dependent AUC at the horizons (cumulative/dynamic, scikit-survival)
  * Brier score per horizon and integrated Brier score, next to the Kaplan-Meier
    "no model" reference (same survival probability for everyone)
  * calibration at one horizon: predicted vs Kaplan-Meier observed death probability by
    predicted-risk quintile
  * C-index by slice (age group, stage, hospital); pairs only within a hospital, because each
    hospital's scores come from a different fold model
"""

from __future__ import annotations

import argparse
import copy
import json
import shutil
from pathlib import Path

import numpy as np
import torch
from sksurv.metrics import brier_score, cumulative_dynamic_auc, integrated_brier_score
from sksurv.util import Surv
from torch.utils.data import ConcatDataset, DataLoader

from muffle.config import load_config
from muffle.data.dataset import MultiOmicDataset
from muffle.data.tcga import CLINICAL_FEATURES
from muffle.metrics import concordance_counts, stratified_concordance
from muffle.residual import federated_lambda, fit_residual
from muffle.train_local import fit, site_files

HORIZONS = (24.0, 36.0, 60.0)  # months
GRID = np.linspace(24.0, 60.0, 25)  # every 1.5 months; contains the horizons
METHODS = ("clinical", "residual", "fedavg_residual")


# --- survival curves ------------------------------------------------------------------------

def breslow(risk, time, event) -> tuple[np.ndarray, np.ndarray]:
    """Breslow cumulative baseline hazard at each distinct event time: (times, H0)."""
    risk, time, event = (np.asarray(a, dtype=float) for a in (risk, time, event))
    w = np.exp(risk - risk.max())  # rescaled for stability; undone below
    times = np.unique(time[event > 0])
    steps = [event[time == t].sum() / w[time >= t].sum() for t in times]
    return times, np.cumsum(steps) * np.exp(-risk.max())


def survival_at(risk, base: tuple[np.ndarray, np.ndarray], horizons) -> np.ndarray:
    """S(h | x) = exp(-H0(h) · exp(r)) for each patient (rows) and horizon (columns)."""
    times, h0 = base
    idx = np.searchsorted(times, np.asarray(horizons, dtype=float), side="right") - 1
    h0_at = np.where(idx >= 0, h0[np.clip(idx, 0, None)], 0.0)
    return np.exp(-np.outer(np.exp(np.asarray(risk, dtype=float)), h0_at))


def kaplan_meier(time, event, horizon: float) -> float:
    """Kaplan-Meier survival probability at ``horizon``."""
    time, event = np.asarray(time, dtype=float), np.asarray(event, dtype=float)
    s = 1.0
    for t in np.unique(time[(event > 0) & (time <= horizon)]):
        s *= 1 - event[time == t].sum() / (time >= t).sum()
    return s


# --- metrics --------------------------------------------------------------------------------

def survival_metrics(time, event, risk, surv: np.ndarray, grid=GRID,
                     horizons=HORIZONS) -> dict:
    """Time-dependent AUC and Brier scores at the horizons, integrated Brier over ``grid``,
    each Brier next to the Kaplan-Meier reference. ``surv`` is S(t | x) on ``grid``."""
    y = Surv.from_arrays(np.asarray(event) > 0, np.asarray(time, dtype=float))
    grid, horizons = np.asarray(grid, dtype=float), np.asarray(horizons, dtype=float)
    cols = [int(np.argmin(np.abs(grid - h))) for h in horizons]
    auc, _ = cumulative_dynamic_auc(y, y, np.asarray(risk, dtype=float), horizons)
    _, bs = brier_score(y, y, surv[:, cols], horizons)
    km = np.tile([kaplan_meier(time, event, g) for g in grid], (len(time), 1))
    _, bs_km = brier_score(y, y, km[:, cols], horizons)
    return {"horizons": horizons.tolist(), "td_auc": auc.tolist(), "brier": bs.tolist(),
            "brier_km": bs_km.tolist(), "ibs": float(integrated_brier_score(y, y, surv, grid)),
            "ibs_km": float(integrated_brier_score(y, y, km, grid))}


def calibration_table(time, event, surv_h: np.ndarray, horizon: float, groups: int = 5):
    """Predicted vs Kaplan-Meier observed death probability at ``horizon`` by risk quantile."""
    pred = 1 - np.asarray(surv_h, dtype=float)
    edges = np.quantile(pred, np.linspace(0, 1, groups + 1))
    bins = np.clip(np.searchsorted(edges, pred, side="right") - 1, 0, groups - 1)
    rows = []
    for g in range(groups):
        sel = bins == g
        if not sel.any():
            continue
        rows.append({"group": g + 1, "n": int(sel.sum()), "deaths": int(np.sum(event[sel])),
                     "predicted": float(pred[sel].mean()),
                     "observed": 1 - kaplan_meier(time[sel], event[sel], horizon)})
    n = sum(r["n"] for r in rows)
    ice = sum(r["n"] * abs(r["predicted"] - r["observed"]) for r in rows) / n
    return {"horizon": horizon, "rows": rows, "mean_abs_error": float(ice)}


def cindex_by_slice(time, event, risk, labels, sites) -> dict[str, dict]:
    """Site-stratified C-index for each slice label, with its size and deaths."""
    out = {}
    for lab in sorted(set(labels), key=str):
        sel = np.asarray(labels) == lab
        counts = [concordance_counts(time[sel & (sites == s)], event[sel & (sites == s)],
                                     risk[sel & (sites == s)]) for s in np.unique(sites[sel])]
        out[str(lab)] = {"n": int(sel.sum()), "deaths": int(event[sel].sum()),
                         "c_index": stratified_concordance(counts)}
    return out


def age_group(age: np.ndarray) -> np.ndarray:
    return np.select([age < 50, age < 65], ["<50", "50-64"], ">=65").astype(object)


def stage_group(stage: np.ndarray, unknown: np.ndarray) -> np.ndarray:
    g = np.select([stage <= 1, stage <= 2], ["I", "II"], "III-IV").astype(object)
    g[unknown > 0] = "unknown"
    return g


# --- cross-site predictions -----------------------------------------------------------------

@torch.no_grad()
def _risk(model, ds, device="cpu") -> np.ndarray:
    model.to(device).eval()
    x, mask, _, _ = next(iter(DataLoader(ds, batch_size=len(ds))))
    return model({m: v.to(device) for m, v in x.items()}, mask.to(device)).cpu().numpy()


def _times(ds) -> tuple[np.ndarray, np.ndarray]:
    _, _, t, e = next(iter(DataLoader(ds, batch_size=len(ds))))
    return t.numpy(), e.numpy()


def _train_model(method: str, train_sets: list, cfg: dict, device: str, fl: dict | None,
                 held: str, files_others: list[Path]):
    pooled = ConcatDataset(train_sets)
    if method == "clinical":
        cfg_c = copy.deepcopy(cfg)
        cfg_c["modalities"] = {"clinical": cfg["modalities"]["clinical"]}
        return fit(pooled, train_sets[0], cfg_c, device)[0], cfg_c
    if method == "residual":
        return fit_residual(pooled, cfg, device)[0], cfg
    if method == "fedavg_residual":
        from muffle.experiment import run_fl_job  # NVFlare only needed for this method

        clients = fl["workspace"] / f"clients-without-{held}"
        shutil.rmtree(clients, ignore_errors=True)
        clients.mkdir(parents=True)
        for k, f in enumerate(files_others, 1):
            shutil.copy(f, clients / f"site-{k}.npz")
        model = run_fl_job(fl["data"], fl["config"], len(files_others), fl["rounds"], fl["seed"],
                           fl["workspace"] / f"residual-without-{held}", cfg, clients,
                           residual=True)
        federated_lambda(model, train_sets, cfg, device)  # sets model.residual_scale
        return model, cfg
    raise ValueError(f"unknown method {method!r}")


def cross_site_predictions(files: list[Path], cfg: dict, method: str, grid=GRID,
                           device: str = "cpu", fl: dict | None = None) -> dict[str, np.ndarray]:
    """Risk, survival on ``grid`` and slice labels for every patient, each predicted by a
    model trained without that patient's hospital (FL client)."""
    v, t = cfg["train"]["val_fraction"], cfg["train"]["seed"]
    parts = []
    for held in files:
        others = [f for f in files if f != held]
        cfg_m = cfg if method != "clinical" else {
            **cfg, "modalities": {"clinical": cfg["modalities"]["clinical"]}}
        train_sets = [MultiOmicDataset(f, cfg_m["modalities"]).split(v, t)[0] for f in others]
        model, cfg_used = _train_model(method, train_sets, cfg, device, fl, held.stem, others)
        pooled = ConcatDataset(train_sets)
        tr_t, tr_e = _times(pooled)
        base = breslow(_risk(model, pooled, device), tr_t, tr_e)
        test = MultiOmicDataset(held, cfg_used["modalities"])
        risk = _risk(model, test, device)
        with np.load(held) as z:
            parts.append({
                "risk": risk, "surv": survival_at(risk, base, grid),
                "time": z["time"], "event": z["event"], "site": np.full(len(risk), held.stem),
                "age": z["age"], "stage": z["stage"],
                "stage_unknown": z["x_clinical"][:, CLINICAL_FEATURES.index("stage_unknown")]})
    return {k: np.concatenate([p[k] for p in parts]) for k in parts[0]}


def report(pred: dict[str, np.ndarray], grid=GRID, horizons=HORIZONS,
           calib_horizon: float = 36.0) -> dict:
    t, e, r, s = pred["time"], pred["event"], pred["risk"], pred["site"]
    counts = [concordance_counts(t[s == x], e[s == x], r[s == x]) for x in np.unique(s)]
    j = int(np.argmin(np.abs(np.asarray(grid) - calib_horizon)))
    return {
        "c_index": stratified_concordance(counts),
        **survival_metrics(t, e, r, pred["surv"], grid, horizons),
        "calibration": calibration_table(t, e, pred["surv"][:, j], calib_horizon),
        "by_age": cindex_by_slice(t, e, r, age_group(pred["age"]), s),
        "by_stage": cindex_by_slice(t, e, r, stage_group(pred["stage"], pred["stage_unknown"]), s),
        "by_hospital": cindex_by_slice(t, e, r, s, s),
    }


def markdown(results: dict[str, dict]) -> str:
    """Side-by-side tables for several methods."""
    methods = list(results)
    first = results[methods[0]]
    hz = [f"{h / 12:g}y" for h in first["horizons"]]
    head = "| metric | " + " | ".join(methods) + " |\n" + "|---" * (len(methods) + 1) + "|"
    lines = ["### Discrimination and error (all patients, cross-site)", head]
    lines.append("| C-index (site-stratified) | " + " | ".join(
        f"{results[m]['c_index']:.3f}" for m in methods) + " |")
    for i, h in enumerate(hz):
        lines.append(f"| AUC at {h} | " + " | ".join(
            f"{results[m]['td_auc'][i]:.3f}" for m in methods) + " |")
    for i, h in enumerate(hz):
        lines.append(f"| Brier at {h} (KM ref {first['brier_km'][i]:.3f}) | " + " | ".join(
            f"{results[m]['brier'][i]:.3f}" for m in methods) + " |")
    lines.append(f"| Integrated Brier (KM ref {first['ibs_km']:.3f}) | " + " | ".join(
        f"{results[m]['ibs']:.3f}" for m in methods) + " |")
    lines.append("| Calibration error at 3y (mean abs, quintiles) | " + " | ".join(
        f"{results[m]['calibration']['mean_abs_error']:.3f}" for m in methods) + " |")
    for key, title in (("by_age", "age"), ("by_stage", "stage"), ("by_hospital", "hospital")):
        lines += ["", f"### C-index by {title} (n, deaths)",
                  "| slice | " + " | ".join(methods) + " |", "|---" * (len(methods) + 1) + "|"]
        for lab, v in first[key].items():
            lines.append(f"| {lab} (n={v['n']}, {v['deaths']}) | " + " | ".join(
                f"{results[m][key][lab]['c_index']:.3f}" for m in methods) + " |")
    for m in methods:
        rows = results[m]["calibration"]["rows"]
        lines += ["", f"### Calibration at 3 years: {m} (predicted vs observed death risk)",
                  "| risk quintile | n | deaths | predicted | observed (KM) |",
                  "|---|---|---|---|---|"]
        lines += [f"| {r['group']} | {r['n']} | {r['deaths']} | {r['predicted']:.3f} | "
                  f"{r['observed']:.3f} |" for r in rows]
    return "\n".join(lines)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=Path("data/tcga_brca"))
    p.add_argument("--config", default="configs/tcga_brca.yaml")
    p.add_argument("--n-clients", type=int, default=3)
    p.add_argument("--seed", type=int, default=0)
    p.add_argument("--methods", nargs="+", choices=METHODS, default=list(METHODS))
    p.add_argument("--out", type=Path, default=Path("outputs/calibration"))
    args = p.parse_args(argv)

    from muffle.experiment import fl_rounds, with_seed

    cfg = with_seed(load_config(args.config), args.seed)
    files = site_files(args.data, args.n_clients, cfg)
    ws = (Path("workspaces/calibration") / f"seed{args.seed}").resolve()
    fl = dict(data=args.data, config=args.config, rounds=fl_rounds(cfg), seed=args.seed,
              workspace=ws)
    results = {}
    for m in args.methods:
        pred = cross_site_predictions(files, cfg, m, fl=fl)
        results[m] = report(pred)
        print(f"{m}: C-index {results[m]['c_index']:.3f}, td-AUC "
              f"{', '.join(f'{a:.3f}' for a in results[m]['td_auc'])}", flush=True)
    args.out.mkdir(parents=True, exist_ok=True)
    md = markdown(results)
    (args.out / f"{args.data.name}_seed{args.seed}.md").write_text(md + "\n")
    (args.out / f"{args.data.name}_seed{args.seed}.json").write_text(json.dumps(results, indent=1))
    print(md)
    return results


if __name__ == "__main__":
    main()

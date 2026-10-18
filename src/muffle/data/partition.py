"""Split a pooled cohort into simulated hospitals (FL clients).

Two kinds of heterogeneity are simulated, as in the plan:
  * statistical: clients can be skewed toward early or late stage (Dirichlet over stage)
  * modality gaps: some clients never collected certain omics (whole modality missing)

For real TCGA data, mode "site" keeps each tissue source site (the hospital that collected the
samples, cohort["tss"]) whole inside one client, and the modality gaps are the real ones.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np

from muffle.config import MODALITIES

# Modalities each simulated site lacks; cycles if there are more sites than entries.
DEFAULT_GAPS: list[list[str]] = [
    [],
    ["protein"],
    ["methylation", "protein"],
    ["genomic"],
    ["protein", "rna"],
]

PER_PATIENT_KEYS = ("time", "event", "mask", "stage", "true_log_hazard", "tss", "age")


def split_by_group(groups: np.ndarray, n_clients: int) -> list[np.ndarray]:
    """Keep every group (e.g. a TCGA tissue source site) whole; balance clients by patients.

    Groups go largest first onto the client with the fewest patients so far (deterministic).
    """
    names, counts = np.unique(groups, return_counts=True)
    if len(names) < n_clients:
        raise ValueError(f"{len(names)} sites can't fill {n_clients} clients")
    members: list[list[str]] = [[] for _ in range(n_clients)]
    sizes = np.zeros(n_clients, dtype=int)
    for i in np.argsort(-counts, kind="stable"):
        k = int(np.argmin(sizes))
        members[k].append(names[i])
        sizes[k] += counts[i]
    return [np.flatnonzero(np.isin(groups, m)) for m in members]


def split_indices(
    stage: np.ndarray, n_clients: int, mode: str = "stage-skew", alpha: float = 1.0, seed: int = 0,
    groups: np.ndarray | None = None,
) -> list[np.ndarray]:
    rng = np.random.default_rng(seed)
    n = len(stage)
    if mode == "iid":
        return [np.sort(p) for p in np.array_split(rng.permutation(n), n_clients)]
    if mode == "site":
        if groups is None:
            raise ValueError("partition mode 'site' needs a per-patient site code (cohort['tss'])")
        return split_by_group(groups, n_clients)
    if mode != "stage-skew":
        raise ValueError(f"unknown partition mode {mode!r}")
    buckets: list[list[int]] = [[] for _ in range(n_clients)]
    for s in np.unique(stage):
        idx = rng.permutation(np.flatnonzero(stage == s))
        props = rng.dirichlet([alpha] * n_clients)
        cuts = (np.cumsum(props) * len(idx)).astype(int)[:-1]
        for k, part in enumerate(np.split(idx, cuts)):
            buckets[k].extend(part.tolist())
    # make sure no client is tiny: top up from the largest
    min_size = max(20, n // (4 * n_clients))
    for k in range(n_clients):
        while len(buckets[k]) < min_size:
            donor = max(range(n_clients), key=lambda j: len(buckets[j]))
            buckets[k].append(buckets[donor].pop())
    return [np.sort(np.array(b)) for b in buckets]


def subset(
    cohort: dict[str, np.ndarray], idx: np.ndarray, drop: list[str]
) -> dict[str, np.ndarray]:
    out = {}
    for key, val in cohort.items():
        if key.startswith("x_") or key in PER_PATIENT_KEYS:
            out[key] = val[idx].copy()
    for m in drop:
        if f"x_{m}" in out:
            out[f"x_{m}"][:] = 0
        out["mask"][:, MODALITIES.index(m)] = 0
    return out


def partition_cohort(
    cohort: dict[str, np.ndarray],
    n_clients: int,
    out_dir: str | Path,
    mode: str = "stage-skew",
    gaps: list[list[str]] | None = None,
    seed: int = 0,
) -> list[Path]:
    """Write one ``site-{k}.npz`` per client (1-based, matching NVFlare site names).

    ``gaps=[[]]`` keeps every modality as measured (real data); None simulates DEFAULT_GAPS.
    """
    gaps = gaps if gaps is not None else DEFAULT_GAPS
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    parts = split_indices(cohort["stage"], n_clients, mode, seed=seed, groups=cohort.get("tss"))
    for k, idx in enumerate(parts):
        site = subset(cohort, idx, gaps[k % len(gaps)])
        path = out_dir / f"site-{k + 1}.npz"
        np.savez_compressed(path, **site)
        paths.append(path)
    return paths

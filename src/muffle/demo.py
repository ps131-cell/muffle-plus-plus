"""What the demo app shows, computed once from a trained model and the hospitals' data.

``build_demo`` reads the FL clients' site files (what each hospital actually has), scores every
patient, and keeps the held-out ones: each hospital's validation split, which the federated model
never trained on. The cohort-wide risks are the reference for percentiles and risk groups, and
the per-layer offsets make contributions read "compared with a typical patient".

The hosted demo will load the same ``Demo`` from a small bundle instead of the data (step 3), so
the app only touches this structure, never the cohort files.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import torch

from muffle.config import DATA_DEFAULTS
from muffle.data.dataset import MultiOmicDataset, feature_names, split_positions
from muffle.data.partition import split_indices
from muffle.explain import cohort_offsets, risk_group, risk_percentile
from muffle.models import MuffleNet
from muffle.report.case_tools import CaseTools, Search
from muffle.train_local import heldout_c_index, load_model, site_files

STAGES = {1: "I", 2: "II", 3: "III", 4: "IV"}


def ordinal(x: float) -> str:
    """82.7 -> '82nd' (rounded down: the riskiest patient is 99th, not 100th)."""
    n = int(x)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


@dataclass
class Case:
    """One held-out patient. ``row`` indexes ``Demo.x`` / ``Demo.mask``."""
    row: int
    index: int        # row in cohort.npz (``make agent-tcga PATIENT=<index>``)
    site: str         # the hospital (FL client) the patient belongs to
    log_risk: float
    percentile: float
    group: str
    age: float | None
    stage: str | None  # "I".."IV"; None if unknown or not recorded
    layers: list[str]
    missing: list[str]

    @property
    def label(self) -> str:
        bits = [f"Case {self.index}", f"{ordinal(self.percentile)} percentile ({self.group} risk)"]
        if self.stage:
            bits.append(f"stage {self.stage}")
        if self.age is not None:
            bits.append(f"age {self.age:.0f}")
        if self.missing:
            bits.append("no " + ", ".join(self.missing))
        return " · ".join(bits)


@dataclass
class Site:
    name: str
    patients: int
    deaths: int
    heldout: int
    coverage: dict[str, float]  # share of patients with each data layer


@dataclass
class Demo:
    model: MuffleNet
    cfg: dict
    cancer: str
    x: dict[str, torch.Tensor]   # held-out cases' inputs, row-aligned with ``cases``
    mask: torch.Tensor
    cohort_risks: np.ndarray     # every patient: the percentile / risk-group reference
    offsets: dict[str, float]
    names: dict[str, list[str]]  # feature names per layer ({} for synthetic data)
    c_index_by_site: dict[str, float]
    cases: list[Case]
    sites: list[Site]
    heldout_time: np.ndarray     # survival of the held-out cases (risk-group curves)
    heldout_event: np.ndarray
    notes: dict = field(default_factory=dict)  # saved case notes by cohort index

    @property
    def c_index(self) -> float:
        return float(np.mean(list(self.c_index_by_site.values())))

    def inputs(self, case: Case, hide: list[str] | tuple = ()):
        """(x, mask) for one case; ``hide`` masks layers out (what-if)."""
        x = {m: v[case.row : case.row + 1] for m, v in self.x.items()}
        mask = self.mask[case.row : case.row + 1].clone()
        for m in hide:
            mask[0, self.model.names.index(m)] = 0
        return x, mask

    def tools(self, case: Case, search: Search | None = None) -> CaseTools:
        x, mask = self.inputs(case)
        return CaseTools(self.model, x, mask, self.cohort_risks, self.cancer, self.names,
                         self.c_index, search, self.offsets)


def build_demo(ckpt: str | Path, data_dir: str | Path, n_clients: int = 3,
               config: str | None = None, cancer: str = "breast") -> Demo:
    model, cfg = load_model(Path(ckpt), config)
    data_dir = Path(data_dir)
    cohort = data_dir / "cohort.npz"
    data = {**DATA_DEFAULTS, **cfg.get("data", {})}
    with np.load(cohort) as f:
        parts = split_indices(f["stage"], n_clients, data["partition"], seed=0,
                              groups=f["tss"] if "tss" in f.files else None)
    names = feature_names(cohort, cfg["modalities"])
    clinical = names.get("clinical", [])
    unknown_col = clinical.index("stage_unknown") if "stage_unknown" in clinical else None

    all_x, all_mask, held, sites = [], [], [], []
    for k, path in enumerate(site_files(data_dir, n_clients, cfg)):
        with np.load(path) as f:
            arrays = {key: f[key] for key in f.files}
        ds = MultiOmicDataset(arrays, cfg["modalities"])
        if len(ds) != len(parts[k]):
            raise ValueError(f"{path} doesn't match the cohort split; delete it to rebuild")
        _, val = split_positions(len(ds), cfg["train"]["val_fraction"], cfg["train"]["seed"])
        all_x.append(ds.x)
        all_mask.append(ds.mask)
        sites.append(Site(path.stem, len(ds), int(ds.event.sum()), len(val),
                          {m: float(ds.mask[:, j].mean()) for j, m in enumerate(model.names)}))
        for pos in val:
            stage = None
            if "stage" in arrays and (unknown_col is None
                                      or arrays["x_clinical"][pos, unknown_col] <= 0):
                stage = STAGES.get(int(arrays["stage"][pos]))
            held.append((path.stem, int(parts[k][pos]), ds, pos,
                         float(arrays["age"][pos]) if "age" in arrays else None, stage))

    x_all = {m: torch.cat([x[m] for x in all_x]) for m in cfg["modalities"]}
    mask_all = torch.cat(all_mask)
    with torch.no_grad():
        cohort_risks = model(x_all, mask_all).numpy()

    x = {m: torch.stack([ds.x[m][pos] for _, _, ds, pos, _, _ in held]) for m in model.names}
    mask = torch.stack([ds.mask[pos] for _, _, ds, pos, _, _ in held])
    with torch.no_grad():
        risks = model(x, mask).numpy()
    cases = []
    for row, (site, index, _, _, age, stage) in enumerate(held):
        layers = [m for j, m in enumerate(model.names) if mask[row, j] > 0]
        cases.append(Case(row, index, site, float(risks[row]),
                          risk_percentile(risks[row], cohort_risks),
                          risk_group(risks[row], cohort_risks), age, stage, layers,
                          [m for m in model.names if m not in layers]))
    time = np.array([float(ds.time[pos]) for _, _, ds, pos, _, _ in held])
    event = np.array([float(ds.event[pos]) for _, _, ds, pos, _, _ in held])
    return Demo(model, cfg, cancer, x, mask, cohort_risks, cohort_offsets(model, x_all, mask_all),
                names, heldout_c_index(model, data_dir, n_clients, cfg), cases, sites, time,
                event)


def kaplan_meier(time: np.ndarray, event: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Product-limit survival estimate evaluated at ``grid``."""
    surv = np.ones_like(grid, dtype=float)
    s = 1.0
    for t in np.unique(time[event == 1]):
        at_risk, deaths = (time >= t).sum(), ((time == t) & (event == 1)).sum()
        s *= 1 - deaths / at_risk
        surv[grid >= t] = s
    return surv


def km_by_group(demo: Demo, months: float = 60, points: int = 61
                ) -> dict[str, tuple[np.ndarray, np.ndarray, int]]:
    """Kaplan-Meier survival of the held-out cases per risk group: {group: (months, survival,
    patients)}. Stops at 5 years: past that, fewer than ~20 held-out patients per group remain."""
    groups = np.array([c.group for c in demo.cases])
    grid = np.linspace(0, months, points)
    return {g: (grid, kaplan_meier(demo.heldout_time[groups == g],
                                   demo.heldout_event[groups == g], grid),
                int((groups == g).sum()))
            for g in ("low", "medium", "high") if (groups == g).any()}

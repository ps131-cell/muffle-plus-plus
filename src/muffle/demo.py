"""What the demo app shows, computed once from a trained model and the hospitals' data.

``build_demo`` reads the FL clients' site files (what each hospital actually has), scores every
patient, and keeps the held-out ones: each hospital's validation split, which the federated model
never trained on. The cohort-wide risks are the reference for percentiles and risk groups, and
the per-layer offsets make contributions read "compared with a typical patient".

The hosted demo loads the same ``Demo`` from a small bundle instead (``save_bundle`` /
``load_bundle``): the model weights, a few dozen held-out cases' inputs and derived numbers
(cohort risks, offsets, per-site C-index, risk-group survival curves), so the app never needs
the cohort files and the server gets no other patient-level data.
"""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path

import numpy as np
import torch

from muffle.config import DATA_DEFAULTS
from muffle.data.dataset import MultiOmicDataset, feature_names, split_positions
from muffle.data.partition import split_indices
from muffle.explain import cohort_offsets, risk_group, risk_percentile
from muffle.models import MuffleNet
from muffle.report import civic
from muffle.report.case_tools import CaseTools, Evidence, Search, observed_facts
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
    mutations: list[str] | None = None  # sequenced drivers; None = not sequenced

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
    km: dict[str, tuple[list[float], list[float], int]]  # held-out risk-group survival curves
    heldout_patients: int        # all held-out patients (``cases`` may be a subset)
    heldout_deaths: int
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

    def tools(self, case: Case, search: Search | None = None,
              evidence: Evidence | None = None) -> CaseTools:
        x, mask = self.inputs(case)
        return CaseTools(self.model, x, mask, self.cohort_risks, self.cancer, self.names,
                         self.c_index, search, self.offsets,
                         observed_facts(case.stage, case.age, case.mutations), evidence)


def evidence_lookup() -> Evidence | None:
    """``civic.evidence`` once CIViC's table is loaded (CC0, ~4 MB, downloaded on first use and
    cached under data/raw/civic/), or None if the download or the parse fails: the app then
    runs without the treatment_evidence tool instead of showing a traceback."""
    try:
        table = civic.load_table()
    except Exception:  # no network, a changed schema, an unwritable cache dir
        return None
    return civic.evidence if table is not None else None


def sequenced_mutations(arrays: dict, pos: int) -> list[str] | None:
    """A patient's observed driver mutations from cohort / site arrays; None if not sequenced."""
    if "mut_status" not in arrays or np.isnan(arrays["mut_status"][pos]).all():
        return None
    return [m for m in str(arrays["mut_changes"][pos]).split(";") if m]


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
                         float(arrays["age"][pos]) if "age" in arrays else None, stage,
                         sequenced_mutations(arrays, pos)))

    x_all = {m: torch.cat([x[m] for x in all_x]) for m in cfg["modalities"]}
    mask_all = torch.cat(all_mask)
    with torch.no_grad():
        cohort_risks = model(x_all, mask_all).numpy()

    x = {m: torch.stack([ds.x[m][pos] for _, _, ds, pos, _, _, _ in held]) for m in model.names}
    mask = torch.stack([ds.mask[pos] for _, _, ds, pos, _, _, _ in held])
    with torch.no_grad():
        risks = model(x, mask).numpy()
    cases = []
    for row, (site, index, _, _, age, stage, muts) in enumerate(held):
        layers = [m for j, m in enumerate(model.names) if mask[row, j] > 0]
        cases.append(Case(row, index, site, float(risks[row]),
                          risk_percentile(risks[row], cohort_risks),
                          risk_group(risks[row], cohort_risks), age, stage, layers,
                          [m for m in model.names if m not in layers], muts))
    time = np.array([float(ds.time[pos]) for _, _, ds, pos, _, _, _ in held])
    event = np.array([float(ds.event[pos]) for _, _, ds, pos, _, _, _ in held])
    return Demo(model, cfg, cancer, x, mask, cohort_risks, cohort_offsets(model, x_all, mask_all),
                names, heldout_c_index(model, data_dir, n_clients, cfg), cases, sites,
                km_by_group(time, event, [c.group for c in cases]), len(cases), int(event.sum()))


def kaplan_meier(time: np.ndarray, event: np.ndarray, grid: np.ndarray) -> np.ndarray:
    """Product-limit survival estimate evaluated at ``grid``."""
    surv = np.ones_like(grid, dtype=float)
    s = 1.0
    for t in np.unique(time[event == 1]):
        at_risk, deaths = (time >= t).sum(), ((time == t) & (event == 1)).sum()
        s *= 1 - deaths / at_risk
        surv[grid >= t] = s
    return surv


def km_by_group(time: np.ndarray, event: np.ndarray, groups: list[str], months: float = 60,
                points: int = 61) -> dict[str, tuple[list[float], list[float], int]]:
    """Kaplan-Meier survival per risk group: {group: (months, survival, patients)}. Stops at 5
    years: past that, fewer than ~20 held-out patients per group remain."""
    groups = np.asarray(groups)
    grid = np.linspace(0, months, points)
    return {g: (grid.tolist(), kaplan_meier(time[groups == g], event[groups == g], grid).tolist(),
                int((groups == g).sum()))
            for g in ("low", "medium", "high") if (groups == g).any()}


def pick_cases(demo: Demo, n: int = 40, keep: list[int] | tuple = ()) -> list[int]:
    """Cohort indices of ~``n`` cases for the hosted demo: every case in ``keep`` (those with saved
    notes), then cases spread evenly over the risk range."""
    known = {c.index for c in demo.cases}
    chosen = [i for i in keep if i in known]
    ranked = sorted(demo.cases, key=lambda c: c.percentile)
    for pos in np.linspace(0, len(ranked) - 1, n).round().astype(int):
        if len(chosen) < n and ranked[pos].index not in chosen:
            chosen.append(ranked[pos].index)
    return chosen


def subset(demo: Demo, indices: list[int]) -> Demo:
    """The same demo with only these cases (by cohort index), rows renumbered."""
    by_index = {c.index: c for c in demo.cases}
    cases = [by_index[i] for i in indices]
    rows = [c.row for c in cases]
    return Demo(demo.model, demo.cfg, demo.cancer, {m: v[rows] for m, v in demo.x.items()},
                demo.mask[rows], demo.cohort_risks, demo.offsets, demo.names,
                demo.c_index_by_site,
                [Case(**{**asdict(c), "row": r}) for r, c in enumerate(cases)], demo.sites,
                demo.km, demo.heldout_patients, demo.heldout_deaths, demo.notes)


BUNDLE_FORMAT = ("muffle-demo-bundle", 1)
RELEASE_URL = re.compile(r"https://github\.com/([^/]+)/([^/]+)/releases/download/([^/]+)/([^/?]+)")


def fetch_bundle(url: str, dest: str | Path, token: str | None = None) -> Path:
    """Download a bundle once (kept at ``dest``). A GitHub release asset of a private repo needs a
    token with read access to the repo's contents; a public one needs none."""
    dest = Path(dest)
    if dest.exists():
        return dest
    m = RELEASE_URL.fullmatch(url)
    if m and token:  # private repo: find the asset through the API, then download its bytes
        owner, repo, tag, name = m.groups()
        auth = {"Authorization": f"Bearer {token}", "X-GitHub-Api-Version": "2022-11-28"}
        req = urllib.request.Request(
            f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}", headers=auth)
        with urllib.request.urlopen(req, timeout=30) as r:
            assets = {a["name"]: a["url"] for a in json.load(r)["assets"]}
        if name not in assets:
            raise FileNotFoundError(f"release {tag} has no asset {name}")
        req = urllib.request.Request(assets[name],
                                     headers={**auth, "Accept": "application/octet-stream"})
    else:
        req = urllib.request.Request(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".part")
    with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
        f.write(r.read())
    tmp.replace(dest)
    return dest


def save_bundle(demo: Demo, path: str | Path) -> Path:
    """Everything the app needs, as tensors and plain Python types (``torch.load`` with
    ``weights_only=True`` reads it, so loading a downloaded bundle can't run code)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({
        "format": list(BUNDLE_FORMAT), "model": demo.model.state_dict(), "cfg": demo.cfg,
        "cancer": demo.cancer, "x": demo.x, "mask": demo.mask,
        "cohort_risks": torch.as_tensor(demo.cohort_risks, dtype=torch.float32),
        "offsets": demo.offsets, "names": demo.names, "c_index_by_site": demo.c_index_by_site,
        "cases": [asdict(c) for c in demo.cases], "sites": [asdict(s) for s in demo.sites],
        "km": {g: list(v) for g, v in demo.km.items()},
        "heldout_patients": demo.heldout_patients, "heldout_deaths": demo.heldout_deaths,
    }, path)
    return path


def load_bundle(path: str | Path) -> Demo:
    b = torch.load(path, map_location="cpu", weights_only=True)
    if tuple(b.get("format", ())) != BUNDLE_FORMAT:
        raise ValueError(f"{path} is not a {BUNDLE_FORMAT[0]} v{BUNDLE_FORMAT[1]} file")
    model = MuffleNet.from_config(b["cfg"])
    model.load_state_dict(b["model"])
    return Demo(model.eval(), b["cfg"], b["cancer"], b["x"], b["mask"],
                b["cohort_risks"].numpy(), b["offsets"], b["names"], b["c_index_by_site"],
                [Case(**c) for c in b["cases"]], [Site(**s) for s in b["sites"]],
                {g: tuple(v) for g, v in b["km"].items()}, b["heldout_patients"],
                b["heldout_deaths"])

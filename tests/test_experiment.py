import json

import numpy as np
import yaml

from muffle.config import DEFAULT_CONFIG, MODALITIES, load_config
from muffle.data.partition import partition_cohort, split_by_group
from muffle.experiment import leave_one_site_out
from muffle.experiment import main as experiment
from muffle.metrics import concordance_counts, concordance_index, stratified_concordance
from muffle.train_local import client_dir, site_files
from tests.conftest import SMALL_DIMS


def test_config_base_is_merged(tmp_path):
    path = tmp_path / "child.yaml"
    path.write_text(yaml.safe_dump({"base": str(DEFAULT_CONFIG), "train": {"epochs": 3},
                                    "data": {"partition": "site"}}))
    cfg, default = load_config(path), load_config()
    assert cfg["train"]["epochs"] == 3 and cfg["train"]["lr"] == default["train"]["lr"]
    assert cfg["data"] == {"partition": "site", "simulate_gaps": True}
    assert "base" not in cfg and cfg["modalities"] == default["modalities"]


def test_split_by_group_keeps_sites_whole():
    groups = np.array(["A"] * 50 + ["B"] * 30 + ["C"] * 25 + ["D"] * 5 + ["E"] * 5)
    parts = split_by_group(groups, 2)
    assert sorted(np.concatenate(parts).tolist()) == list(range(len(groups)))
    site_sets = [set(groups[p]) for p in parts]
    assert not site_sets[0] & site_sets[1]
    assert sorted(len(p) for p in parts) == [55, 60]


def test_site_partition_keeps_real_gaps(cohort, tmp_path):
    cohort = dict(cohort)
    rng = np.random.default_rng(0)
    cohort["tss"] = rng.choice(["AA", "BB", "CC", "DD", "EE"], len(cohort["time"]))
    cohort["mask"] = cohort["mask"].copy()
    cohort["mask"][::4, MODALITIES.index("protein")] = 0  # a "real" gap
    paths = partition_cohort(cohort, 3, tmp_path, mode="site", gaps=[[]])
    seen = []
    for path in paths:
        with np.load(path) as f:
            seen.append(set(f["tss"]))
            assert f["mask"][:, MODALITIES.index("rna")].min() == 1  # nothing blanked
    assert sum(len(s) for s in seen) == 5 and set().union(*seen) == {"AA", "BB", "CC", "DD", "EE"}


def test_stratified_concordance_pools_pairs_within_sites():
    t1, e1, r1 = np.array([1.0, 2, 3]), np.array([1.0, 1, 0]), np.array([3.0, 2, 1])
    t2, e2, r2 = np.array([1.0, 2]), np.array([1.0, 0]), np.array([0.0, 5])  # wrong order
    a, b = concordance_counts(t1, e1, r1), concordance_counts(t2, e2, r2)
    assert a == (3.0, 3.0) and b == (0.0, 1.0)
    assert stratified_concordance([a, b]) == 0.75
    assert concordance_index(t1, e1, r1) == 1.0


def test_experiment_runs_without_fl(cohort, tmp_path):
    data = tmp_path / "data"
    data.mkdir()
    np.savez_compressed(data / "cohort.npz", **cohort)
    config = tmp_path / "small.yaml"
    config.write_text(yaml.safe_dump({
        "base": str(DEFAULT_CONFIG), "modalities": SMALL_DIMS,
        "model": {"hidden": 16, "latent": 4, "head_hidden": 4},
        "train": {"epochs": 2, "batch_size": 64}}))
    out = tmp_path / "out"
    runs = experiment(["--data", str(data), "--config", str(config), "--seeds", "0", "1",
                       "--methods", "centralized", "local_only", "single_modality",
                       "--out", str(out), "--name", "t"])
    assert set(runs[0]) == {"centralized", "local_only", *(f"only_{m}" for m in SMALL_DIMS)}
    assert all(0 <= r["pooled"] <= 1 for r in runs[1].values())
    saved = json.loads((out / "t.json").read_text())
    assert "| centralized |" in saved["table"] and saved["sites"]["site-1"]["patients"] > 0
    cfg = load_config(config)
    assert len(site_files(data, 3, cfg)) == 3 and client_dir(data, 3, cfg).name == \
        "clients_3_stage-skew"


def test_leave_one_site_out_without_fl(cohort, tmp_path):
    cfg = load_config()
    cfg["modalities"] = SMALL_DIMS
    cfg["model"].update(hidden=16, latent=4, head_hidden=4, fusion="additive")
    cfg["train"]["epochs"] = 2
    np.savez_compressed(tmp_path / "cohort.npz", **cohort)
    files = site_files(tmp_path, 3, cfg)
    res = leave_one_site_out(files, cfg, ["centralized", "local_only"], "cpu")
    assert set(res) == {"centralized", "local_only"}
    for scores in res.values():
        assert set(scores) == {"site-1", "site-2", "site-3", "pooled"}
        assert 0 <= scores["pooled"] <= 1

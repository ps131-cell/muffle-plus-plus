import pytest
import numpy as np
import torch
from torch.utils.data import DataLoader

from muffle.config import MODALITIES
from muffle.data.dataset import MultiOmicDataset, feature_names
from muffle.data.partition import partition_cohort
from muffle.engine import evaluate, train_epochs
from muffle.metrics import concordance_index
from muffle.models import MuffleNet
from muffle.train_local import load_checkpoint, load_model, results_table


def test_synthetic_signal_is_learnable(cohort):
    # the true hazard should rank patients well; otherwise the generator is broken
    assert concordance_index(cohort["time"], cohort["event"], cohort["true_log_hazard"]) > 0.7
    assert 0.3 < cohort["event"].mean() < 0.9


def test_partition(cohort, tmp_path):
    paths = partition_cohort(cohort, 3, tmp_path, gaps=[[], ["protein"], ["rna", "protein"]])
    sizes = []
    for k, path in enumerate(paths):
        with np.load(path) as f:
            sizes.append(len(f["time"]))
            mask = f["mask"]
            if k == 2:
                assert mask[:, MODALITIES.index("rna")].sum() == 0
                assert np.all(f["x_rna"] == 0)
            if k == 0:
                assert mask.min() == 1
    assert sum(sizes) == len(cohort["time"]) and min(sizes) >= 20


def test_training_beats_random(cohort, small_cfg):
    torch.manual_seed(0)
    ds = MultiOmicDataset(cohort, small_cfg["modalities"])
    tr, va = ds.split(0.25)
    model = MuffleNet.from_config(small_cfg)
    before = evaluate(model, va)["c_index"]
    train_epochs(model, DataLoader(tr, batch_size=64, shuffle=True), epochs=30, lr=3e-3)
    after = evaluate(model, va)["c_index"]
    assert after > 0.65 and after > before


def test_load_checkpoint_accepts_nvflare_global_model(small_cfg, tmp_path):
    # NVFlare's PTFileModelPersistor saves {"model": state_dict, "train_conf": ...}, no "config"
    model = MuffleNet.from_config(small_cfg)
    path = tmp_path / "FL_global_model.pt"
    torch.save({"model": model.state_dict(), "train_conf": {"train": {"model": "MuffleNet"}}}, path)
    loaded = load_checkpoint(path, small_cfg)
    assert all(torch.equal(v, loaded.state_dict()[k]) for k, v in model.state_dict().items())
    table = results_table({"centralized": {"site-1": 0.71}, "fedavg": {"site-1": 0.7}})
    assert "| site-1 | 0.710 | 0.700 |" in table


def test_fedprox_term_runs(cohort, small_cfg):
    ds = MultiOmicDataset(cohort, small_cfg["modalities"])
    model = MuffleNet.from_config(small_cfg)
    anchor = {k: v.clone() for k, v in model.state_dict().items()}
    stats = train_epochs(model, DataLoader(ds, batch_size=64), 1, 1e-3, prox_mu=0.1,
                         global_params=anchor)
    assert stats["steps"] > 0 and np.isfinite(stats["train_loss"])


def test_dataset_keeps_first_features_when_config_asks_for_fewer(cohort):
    ds = MultiOmicDataset(cohort, {"rna": 10, "clinical": 8})
    assert ds.x["rna"].shape[1] == 10
    assert np.array_equal(ds.x["rna"].numpy(), cohort["x_rna"][:, :10])
    with pytest.raises(ValueError):
        MultiOmicDataset(cohort, {"rna": cohort["x_rna"].shape[1] + 1})


def test_load_model_uses_stored_config_else_the_given_one(small_cfg, tmp_path):
    cfg = {**small_cfg, "model": {**small_cfg["model"], "fusion": "additive"}}
    model = MuffleNet.from_config(cfg)
    with_cfg, raw = tmp_path / "saved.pt", tmp_path / "FL_global_model.pt"
    torch.save({"model": model.state_dict(), "config": cfg}, with_cfg)
    torch.save({"model": model.state_dict()}, raw)  # what NVFlare's persistor writes
    loaded, got = load_model(with_cfg)  # no config needed: it's in the file
    assert got == cfg and loaded.fusion == "additive" and not loaded.training
    loaded, got = load_model(raw, cfg)
    assert all(torch.equal(v, loaded.state_dict()[k]) for k, v in model.state_dict().items())


def test_feature_names_follow_config_sizes(cohort, tmp_path):
    path = tmp_path / "cohort.npz"
    names = np.array([f"G{i}" for i in range(cohort["x_rna"].shape[1])])
    np.savez(path, **cohort, names_rna=names)
    assert feature_names(path, {"rna": 3, "clinical": 8}) == {"rna": ["G0", "G1", "G2"]}

import numpy as np
import torch
from torch.utils.data import DataLoader

from muffle.config import MODALITIES
from muffle.data.dataset import MultiOmicDataset
from muffle.data.partition import partition_cohort
from muffle.engine import evaluate, train_epochs
from muffle.metrics import concordance_index
from muffle.models import MuffleNet


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


def test_fedprox_term_runs(cohort, small_cfg):
    ds = MultiOmicDataset(cohort, small_cfg["modalities"])
    model = MuffleNet.from_config(small_cfg)
    anchor = {k: v.clone() for k, v in model.state_dict().items()}
    stats = train_epochs(model, DataLoader(ds, batch_size=64), 1, 1e-3, prox_mu=0.1,
                         global_params=anchor)
    assert stats["steps"] > 0 and np.isfinite(stats["train_loss"])

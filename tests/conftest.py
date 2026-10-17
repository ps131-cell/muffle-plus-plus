import pytest

from muffle.data.synthetic import make_cohort

SMALL_DIMS = {"genomic": 20, "rna": 50, "methylation": 30, "protein": 10, "clinical": 8}


@pytest.fixture(scope="session")
def small_cfg():
    return {
        "modalities": SMALL_DIMS,
        "model": {"hidden": 32, "latent": 8, "head_hidden": 8, "dropout": 0.1,
                  "modality_dropout": 0.0},
        "train": {"batch_size": 64, "lr": 3e-3, "weight_decay": 0.0, "epochs": 30,
                  "local_epochs": 1, "val_fraction": 0.25, "seed": 0},
        "fl": {"prox_mu": 0.0},
    }


@pytest.fixture(scope="session")
def cohort():
    return make_cohort(600, SMALL_DIMS, seed=1)

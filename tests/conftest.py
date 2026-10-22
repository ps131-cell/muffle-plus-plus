import pytest

from muffle.data.synthetic import make_cohort

SMALL_DIMS = {"genomic": 20, "rna": 50, "methylation": 30, "protein": 10, "clinical": 8}


@pytest.fixture(autouse=True)
def _spend_ledger(tmp_path, monkeypatch):
    """Keep tests away from the real Token Factory spend ledger in the home directory, and from
    downloading slide tile pyramids."""
    monkeypatch.setenv("MUFFLE_SPEND_LEDGER", str(tmp_path / "spend.json"))
    monkeypatch.delenv("TOKEN_FACTORY_BUDGET_USD", raising=False)
    monkeypatch.setenv("MUFFLE_SLIDE_TILES", "off")


@pytest.fixture(autouse=True)
def _strict_pages(monkeypatch):
    """A workbench page that draws a part of the shared skeleton out of order fails its test
    (``workbenches._page``); in front of a clinician it is drawn as asked."""
    monkeypatch.setenv("MUFFLE_STRICT_PAGES", "1")


@pytest.fixture(autouse=True)
def _arrow_strict(monkeypatch):
    """A table Streamlit can't hand to Arrow as it is fails the page's test: Streamlit would
    otherwise re-type its columns silently, logging only at INFO level."""
    try:
        from streamlit import dataframe_util
    except ImportError:
        return

    def refuse(df):
        raise AssertionError(f"mixed column types reached Arrow: {list(df.columns)}")

    monkeypatch.setattr(dataframe_util, "fix_arrow_incompatible_column_types", refuse)


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


@pytest.fixture
def app(cohort, small_cfg, tmp_path, monkeypatch):
    """The whole app under AppTest on a bundle built from the test cohort
    (``tests.appfixture.make_app``)."""
    from tests.appfixture import make_app

    return make_app(cohort, small_cfg, tmp_path, monkeypatch)

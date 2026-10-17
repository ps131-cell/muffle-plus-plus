import numpy as np
import pytest

from muffle.metrics import concordance_index


def test_perfect_and_reversed():
    t = np.array([1, 2, 3, 4, 5.0])
    e = np.ones(5)
    assert concordance_index(t, e, -t) == 1.0
    assert concordance_index(t, e, t) == 0.0


def test_random_is_half():
    rng = np.random.default_rng(0)
    t = rng.exponential(size=2000)
    e = rng.random(2000) < 0.7
    assert abs(concordance_index(t, e, rng.normal(size=2000)) - 0.5) < 0.03


def test_matches_lifelines():
    lifelines = pytest.importorskip("lifelines.utils")
    rng = np.random.default_rng(1)
    t, e, r = rng.exponential(size=300), rng.random(300) < 0.6, rng.normal(size=300)
    # lifelines expects higher score = longer survival
    assert concordance_index(t, e, r) == pytest.approx(lifelines.concordance_index(t, -r, e))

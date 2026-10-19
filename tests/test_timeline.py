"""The synthetic timeline patient, scored by models fit on a tiny fake study (no real data)."""

import json

import pytest

from muffle.longitudinal import evaluate, features, load
from muffle.timeline import DAYS_PER_MONTH, EVENTS, PATIENT_ID, build, observed, tables
from tests.test_longitudinal import make_study


@pytest.fixture(scope="module")
def built(tmp_path_factory):
    root = tmp_path_factory.mktemp("study")
    make_study(root, n=160, seed=2)
    res = evaluate(load(root), seeds=(0, 1), landmarks=(0, 12), keep_models=True)
    return build(res, evidence={"PIK3CA H1047R": [{"therapies": "x", "evidence_level": "C"}]})


def test_features_see_only_the_record_so_far():
    data = tables()
    at = {m: features(data, [PATIENT_ID], m * DAYS_PER_MONTH).iloc[0] for m in (0, 11, 12, 24)}
    assert at[0]["progressions_so_far"] == 1 and at[11]["progressions_so_far"] == 1
    assert at[12]["progressions_so_far"] == 2 and at[12]["metastatic_sites"] == 2
    assert at[0]["mut_PIK3CA"] == 1 and at[0]["mut_TP53"] == 0
    assert at[0]["rx_targeted"] == 0 and at[24]["rx_targeted"] == 2
    assert at[24]["ca153_tests"] == 8 and at[24]["ca153_last"] > 0
    assert at[24]["cea_last"] != at[24]["cea_last"]  # never measured: missing, not zero


def test_profile_says_unknown_before_sequencing():
    before = dict(observed(EVENTS, -1))
    after = dict(observed(EVENTS, 0))
    assert before["Driver mutations"].startswith("not sequenced")
    assert "Sequenced, not found" not in before
    assert after["Driver mutations"].startswith("PIK3CA H1047R")
    assert "TP53" in after["Sequenced, not found"]


def test_build_scores_every_event_from_time_zero(built):
    assert built["synthetic"] is True and "Synthetic" in built["notice"]
    json.dumps(built)  # JSON-ready: no models or frames inside
    scored = [u for u in built["updates"] if "risk" in u]
    assert len(built["updates"]) == len(EVENTS)
    assert [u["month"] for u in scored] == [e["month"] for e in EVENTS if e["month"] >= 0]
    for u in built["updates"]:
        assert ("risk" in u) == (u["month"] >= 0)
    first, *rest = scored
    assert "previous" not in first and first["summary"].startswith("First estimate")
    for u in scored:
        assert u["landmark"] <= u["month"] and u["landmark"] in (0, 12)
        lo, hi = u["risk_range"]
        assert 0 <= lo <= u["risk"] <= hi <= 1
    for prev, u in zip(scored, rest, strict=False):
        assert u["previous"] == pytest.approx(prev["risk"])
        total = sum(c["points"] for c in u["changes"])  # the parts add up to the change
        assert total == pytest.approx(100 * (u["risk"] - u["previous"]))
    switch = next(u for u in scored if u["month"] == 12)
    assert any(c["what"] == "month-12 model takes over" for c in switch["changes"])

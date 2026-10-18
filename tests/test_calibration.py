import numpy as np

from muffle.calibration import (
    GRID,
    HORIZONS,
    age_group,
    breslow,
    calibration_table,
    cindex_by_slice,
    cross_site_predictions,
    kaplan_meier,
    markdown,
    report,
    survival_at,
)
from muffle.config import load_config
from muffle.train_local import site_files
from tests.conftest import SMALL_DIMS


def _survival_data(n=400, seed=0):
    rng = np.random.default_rng(seed)
    risk = rng.normal(size=n)
    t_event = rng.exponential(40 * np.exp(-risk))
    t_cens = rng.uniform(0, 120, n)
    return risk, np.minimum(t_event, t_cens), (t_event <= t_cens).astype(float)


def test_breslow_with_zero_risk_is_nelson_aalen_close_to_km():
    _, time, event = _survival_data()
    base = breslow(np.zeros_like(time), time, event)
    s = survival_at(np.zeros(1), base, [36.0])[0, 0]
    assert abs(s - kaplan_meier(time, event, 36.0)) < 0.02


def test_survival_falls_with_risk_and_time():
    risk, time, event = _survival_data()
    s = survival_at(np.array([-1.0, 0.0, 1.0]), breslow(risk, time, event), [12, 36, 60])
    assert np.all(np.diff(s, axis=0) < 0) and np.all(np.diff(s, axis=1) <= 0)


def test_calibration_table_and_slices():
    risk, time, event = _survival_data()
    surv = survival_at(risk, breslow(risk, time, event), [36.0])[:, 0]
    tab = calibration_table(time, event, surv, 36.0)
    assert sum(r["n"] for r in tab["rows"]) == len(time) and tab["mean_abs_error"] < 0.1
    sites = np.where(np.arange(len(time)) % 2, "A", "B")
    slices = cindex_by_slice(time, event, risk, age_group(np.linspace(30, 80, len(time))), sites)
    assert set(slices) == {"<50", "50-64", ">=65"}
    assert all(v["c_index"] > 0.6 for v in slices.values())


def test_cross_site_report_on_a_tiny_tcga_like_cohort(cohort, tmp_path):
    cohort = dict(cohort)
    rng = np.random.default_rng(0)
    cohort["tss"] = rng.choice(list("ABCDEF"), len(cohort["time"]))
    cohort["age"] = rng.uniform(30, 85, len(cohort["time"])).astype(np.float32)
    cohort["time"] = cohort["time"] * 3  # follow-up long enough for the 5-year horizon
    np.savez_compressed(tmp_path / "cohort.npz", **cohort)
    cfg = load_config()
    cfg["modalities"] = SMALL_DIMS
    cfg["model"].update(hidden=16, latent=4, head_hidden=4, fusion="additive",
                        always_keep=["clinical"])
    cfg["train"]["epochs"] = 2
    cfg["data"] = {"partition": "site", "simulate_gaps": False}
    files = site_files(tmp_path, 3, cfg)
    pred = cross_site_predictions(files, cfg, "clinical")
    assert pred["surv"].shape == (len(cohort["time"]), len(GRID))
    res = report(pred)
    assert len(res["td_auc"]) == len(HORIZONS) and 0 <= res["c_index"] <= 1
    assert "| C-index (site-stratified) |" in markdown({"clinical": res})

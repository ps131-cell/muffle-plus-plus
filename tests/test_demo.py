"""Demo data: held-out cases are exactly each hospital's validation split, mapped to cohort rows."""

import numpy as np
import torch

from muffle.data.dataset import MultiOmicDataset, split_positions
from muffle.demo import build_demo, kaplan_meier, km_by_group, ordinal
from muffle.models import MuffleNet
from muffle.report.nemotron import CaseReport, ToolCall


def test_build_demo_lists_the_held_out_patients(cohort, small_cfg, tmp_path):
    np.savez(tmp_path / "cohort.npz", **cohort)
    torch.manual_seed(0)
    model = MuffleNet.from_config(small_cfg)
    torch.save({"model": model.state_dict(), "config": small_cfg}, tmp_path / "m.pt")
    demo = build_demo(tmp_path / "m.pt", tmp_path, n_clients=3)

    sites = sorted((tmp_path / "clients_3_stage-skew").glob("site-*.npz"))
    n_val = [len(split_positions(len(MultiOmicDataset(f, small_cfg["modalities"])),
                                 0.25, 0)[1]) for f in sites]
    assert len(demo.cases) == sum(n_val) == len(demo.heldout_time)
    assert [s.heldout for s in demo.sites] == n_val
    assert sum(s.patients for s in demo.sites) == len(cohort["time"]) == len(demo.cohort_risks)
    # each case's cohort index points at the same patient (survival matches)
    assert np.allclose(demo.heldout_time, cohort["time"][[c.index for c in demo.cases]])
    assert len({c.index for c in demo.cases}) == len(demo.cases)
    # a case's inputs give its stored risk; hiding a layer masks it
    case = next(c for c in demo.cases if len(c.layers) > 1)
    x, mask = demo.inputs(case)
    with torch.no_grad():
        assert abs(demo.model(x, mask).item() - case.log_risk) < 1e-5
    _, hidden = demo.inputs(case, [case.layers[0]])
    assert hidden.sum() == mask.sum() - 1
    assert set(demo.offsets) <= set(model.names)
    assert demo.tools(case).predict_risk()["risk_group"] == case.group
    assert {g for g in km_by_group(demo)} <= {"low", "medium", "high"}


def test_kaplan_meier_and_ordinal():
    t, e = np.array([1.0, 2, 3, 4]), np.array([1, 0, 1, 0])
    assert np.allclose(kaplan_meier(t, e, np.array([0.5, 1, 2.5, 3, 5])),
                       [1, 0.75, 0.75, 0.375, 0.375])
    assert [ordinal(x) for x in (1, 2, 3, 11, 12, 22, 81.9, 99.9)] == [
        "1st", "2nd", "3rd", "11th", "12th", "22nd", "81st", "99th"]


def test_case_report_round_trips_through_json():
    import json
    r = CaseReport("**Summary** x", [ToolCall(1, "predict_risk", {}, {"cohort_percentile": 81})],
                   "agent", "m", 10, ["n"], "w", [{"kind": "gene", "text": "TP53"}], True)
    assert CaseReport.from_dict(json.loads(json.dumps(r.to_dict()))) == r

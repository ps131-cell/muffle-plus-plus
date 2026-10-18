"""Demo data: held-out cases are exactly each hospital's validation split, mapped to cohort rows."""

import numpy as np
import torch

from muffle.data.dataset import MultiOmicDataset, split_positions
from muffle.demo import (
    build_demo,
    fetch_bundle,
    kaplan_meier,
    load_bundle,
    ordinal,
    pick_cases,
    save_bundle,
    subset,
)
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
    assert len(demo.cases) == sum(n_val) == demo.heldout_patients
    assert [s.heldout for s in demo.sites] == n_val
    assert sum(s.patients for s in demo.sites) == len(cohort["time"]) == len(demo.cohort_risks)
    # each case's cohort index points at the same patient (clinical data is never dropped)
    assert np.allclose(demo.x["clinical"].numpy(),
                       cohort["x_clinical"][[c.index for c in demo.cases]])
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
    assert set(demo.km) <= {"low", "medium", "high"}
    assert sum(n for _, _, n in demo.km.values()) == demo.heldout_patients
    assert demo.heldout_deaths == int(cohort["event"][[c.index for c in demo.cases]].sum())

    # the hosted bundle: a subset of cases, same predictions, nothing else patient-level
    keep = [demo.cases[5].index, demo.cases[0].index]
    picked = pick_cases(demo, 10, keep)
    assert picked[:2] == keep and len(picked) == len(set(picked)) == 10
    small = subset(demo, picked)
    path = save_bundle(small, tmp_path / "bundle.pt")
    url_copy = fetch_bundle(path.as_uri(), tmp_path / "dl" / "bundle.pt")  # no network: file URL
    loaded = load_bundle(url_copy)
    assert [c.index for c in loaded.cases] == picked
    assert [c.row for c in loaded.cases] == list(range(10))
    assert loaded.heldout_patients == demo.heldout_patients and loaded.km == demo.km
    assert np.allclose(loaded.cohort_risks, demo.cohort_risks)
    for c in loaded.cases:
        x, mask = loaded.inputs(c)
        with torch.no_grad():
            assert abs(loaded.model(x, mask).item() - c.log_risk) < 1e-5
    assert loaded.tools(loaded.cases[0]).modality_contributions() == \
        demo.tools(demo.cases[5]).modality_contributions()


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

"""The workspace pages render: the patient list and both kinds of patient file in every view
(Streamlit's AppTest, on a bundle built from the test cohort; no network, no keys)."""

import sys
from pathlib import Path

import numpy as np
import pytest
import torch

from muffle.demo import build_demo, pick_cases, save_bundle, subset
from muffle.hotreload import source_digest
from muffle.models import MuffleNet
from muffle.report import civic

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "streamlit_app.py"
VIEWS = ("Tests", "Timeline", "Import tests", "Report")


def shown(at) -> str:
    return " ".join(e.value for kind in ("title", "header", "subheader", "markdown", "caption",
                                         "info") for e in getattr(at, kind))


def test_patient_files_render_in_every_view(cohort, small_cfg, tmp_path, monkeypatch):
    np.savez(tmp_path / "cohort.npz", **cohort)
    torch.manual_seed(0)
    torch.save({"model": MuffleNet.from_config(small_cfg).state_dict(), "config": small_cfg},
               tmp_path / "m.pt")
    demo = build_demo(tmp_path / "m.pt", tmp_path, n_clients=3)
    demo.cases[0].mutations = ["PIK3CA p.H1047R"]
    bundle = save_bundle(subset(demo, pick_cases(demo, 4, [demo.cases[0].index])),
                         tmp_path / "bundle.pt")
    monkeypatch.setenv("MUFFLE_BUNDLE", str(bundle))
    for key in ("NEBIUS_API_KEY", "TAVILY_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr(civic, "load_table", lambda *a, **k: None)  # no CIViC download
    # this process already runs this code, so the app's hot-reload guard must not purge it
    monkeypatch.setattr(sys, "_muffle_code_digest",
                        source_digest([APP.parent, ROOT / "src" / "muffle"]), raising=False)

    at = AppTest.from_file(str(APP), default_timeout=120).run()
    assert not at.exception
    patients = at.dataframe[0].value["Patient"].tolist()
    case = f"Case {demo.cases[0].index}"
    assert patients[0] == "SYNTHETIC-001" and case in patients

    at.selectbox(key="patient").select("SYNTHETIC-001").run()
    assert not at.exception and "is synthetic" in at.warning[0].value
    for view in VIEWS:
        at.segmented_control(key="view").set_value(view).run()
        assert not at.exception, view
    at.select_slider(key="version-SYNTHETIC-001").set_value(11).run()  # month 12
    assert "New metastatic site: liver" in shown(at) and "placeholder threshold" in shown(at)
    at.segmented_control(key="view").set_value("Tests").run()
    assert "Lab workbench" in shown(at) and "Flag, month 11" in shown(at)

    at.selectbox(key="patient").select(case).run()
    assert "Mutation workbench" in shown(at) and "PIK3CA H1047R" in shown(at)
    for view in VIEWS:
        at.segmented_control(key="view").set_value(view).run()
        assert not at.exception, view
    assert "Tumor-board note" in shown(at) and "nothing alarming" in shown(at)

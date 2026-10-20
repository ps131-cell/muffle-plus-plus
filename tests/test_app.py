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


def button(at, label: str):
    return next(b for b in at.button if b.label == label)


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
    assert "1/7 · Progression on imaging" in shown(at)  # 3 alerts now, 4 earlier; strongest first
    assert "New metastatic site: liver" in shown(at)
    button(at, "Open the test").click().run()  # lands on the imaging report behind the alert
    assert at.segmented_control(key="view").value == "Tests"
    assert "Imaging report, month 12" in shown(at)
    at.segmented_control(key="view").set_value("Report").run()
    button(at, "▶").click().run()
    button(at, "▶").click().run()
    assert "3/7 · 12-month risk up" in shown(at) and "placeholder threshold" in shown(at)
    button(at, "Mark reviewed").click().run()
    assert "✓ reviewed" in shown(at) and not at.exception
    assert [b.label for b in at.get("download_button")] == [
        "Download this report version (Markdown)"]
    at.segmented_control(key="view").set_value("Tests").run()
    at.session_state["picked-SYNTHETIC-001"] = ("Lab", 11, "CA 15-3")
    at.run()  # the lab page as of month 12: the month-11 rise is a flagged result
    assert "Blood and lab workbench" in shown(at) and not at.exception
    assert any("month 11: CA 15-3 52" in e.label for e in at.expander)
    at.session_state["picked-SYNTHETIC-001"] = ("Pathology report", -40, "Diagnosis")
    at.run()  # the slide workbench, on a public example region, saying it isn't this patient
    assert "Pathology slides" in shown(at) and "nothing below is this patient's tissue" in shown(at)
    assert not at.exception
    at.segmented_control(key="view").set_value("Timeline").run()  # compare month 11 with 12
    assert "~ Metastatic sites" in shown(at) and "12-month risk" in shown(at)
    at.segmented_control(key="view").set_value("Report").run()
    at.select_slider(key="version-SYNTHETIC-001").set_value(10).run()  # month 11
    assert "CA 15-3 rising while the latest imaging read stable" in shown(at)
    assert "Repeat CA 15-3 specimen within a month" in shown(at) and not at.exception

    at.selectbox(key="patient").select(case).run()
    at.segmented_control(key="view").set_value("Tests").run()
    assert "Genomics workbench" in shown(at) and "PIK3CA H1047R" in shown(at)
    for view in VIEWS:
        at.segmented_control(key="view").set_value(view).run()
        assert not at.exception, view
    assert "Tumor-board note" in shown(at) and "nothing alarming" in shown(at)

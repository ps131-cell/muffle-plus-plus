"""The workspace pages render: the patient list and both kinds of patient file in every view
(Streamlit's AppTest, on a bundle built from the test cohort; no network, no keys)."""

import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest
import torch

from muffle import evolution, workspace
from muffle.demo import build_demo, pick_cases, save_bundle, subset
from muffle.hotreload import source_digest
from muffle.imports import lab_tests, parse_labs
from muffle.models import MuffleNet
from muffle.report import civic, trials

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "streamlit_app.py"
VIEWS = ("Tests", "Timeline", "Evolution", "Import tests", "Report")


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

    def offline(*a, **k):
        raise OSError("no registry calls in tests")

    monkeypatch.setattr(trials, "CACHE", tmp_path / "trials")  # the trials come from the snapshot
    monkeypatch.setattr(trials, "_get", offline)
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
    button(at, "Open the Evolution view").click().run()  # the report's hook, as of month 12
    assert at.segmented_control(key="view").value == "Evolution"
    assert "Tumor evolution and treatment evidence" in shown(at) and not at.exception
    assert "ESR1 ligand-binding-domain mutation" in shown(at) and "snapshot" in shown(at)
    tl = json.loads((APP.parent / "timeline_synthetic.json").read_text(encoding="utf-8"))
    key = evolution.hypothesis_set(workspace.synthetic_file(tl), 11)["items"][0]["key"]
    mark = f"evo-mark-{hashlib.sha1(key.encode()).hexdigest()[:10]}"
    at.segmented_control(key=mark).set_value("agree").run()  # joins the file's review list
    assert at.session_state["reviews"][key]["mark"] == "agree"
    at.segmented_control(key="view").set_value("Report").run()
    assert any("2 marked" in e.label for e in at.expander)  # the alert above and this one
    at.select_slider(key="version-SYNTHETIC-001").set_value(10).run()  # month 11
    assert "CA 15-3 rising while the latest imaging read stable" in shown(at)
    assert "Repeat CA 15-3 specimen within a month" in shown(at) and not at.exception

    # the clinical documents workbench opens from a clinic note
    at.select_slider(key="version-SYNTHETIC-001").set_value(15).run()
    at.segmented_control(key="view").set_value("Tests").run()
    at.session_state["picked-SYNTHETIC-001"] = ("Clinic note", 13, "Clinic visit")
    at.run()
    assert "Clinical documents" in shown(at) and "documented facts" in shown(at)
    assert not at.exception
    # an import (what the Import tests dialog stores) adds a version and re-runs the rise rule
    ok, _ = parse_labs(b"month,marker,value,unit\n27,CA 15-3,45,U/mL\n", after=24)
    tests, observed = lab_tests(ok)
    at.session_state["imports"] = {"SYNTHETIC-001": [{"kind": "Lab results", "rejected": [],
                                                      "version": {
        "tests": tests, "month": 27, "event": "Imported lab results", "observed": observed,
        "by": "AB", "at": "14:03"}}]}
    at.session_state["picked-SYNTHETIC-001"] = ("Lab", 27, "CA 15-3")
    at.run()
    at.select_slider(key="version-SYNTHETIC-001").set_value(16).run()
    assert any("month 27: CA 15-3 45" in e.label for e in at.expander) and not at.exception
    at.segmented_control(key="view").set_value("Report").run()
    assert "month 27 · imported by AB at 14:03" in shown(at)
    assert "CA 15-3 rose from 31 to 45 U/mL (+45%)" in shown(at) and not at.exception
    at.segmented_control(key="view").set_value("Import tests").run()
    assert "Imported in this session" in shown(at) and "kept for this browser session only" in \
        shown(at)
    at.segmented_control(key="view").set_value("Timeline").run()
    assert not at.exception

    at.selectbox(key="patient").select(case).run()
    at.segmented_control(key="view").set_value("Tests").run()
    assert "Genomics workbench" in shown(at) and "PIK3CA H1047R" in shown(at)
    for kind, layer in (("Data layer", "rna"), ("Clinical record", "clinical")):
        at.session_state[f"picked-{case}"] = (kind, None, workspace.ASSAYS[layer])
        at.run()  # the omics workbench; this test cohort has no precomputed scores
        assert "Expression, methylation and protein" in shown(at) and not at.exception, layer
        assert "No precomputed subtype" in " ".join(w.value for w in at.warning)
    at.selectbox(key=f"omics-spot-{case}").select_index(0).run()
    next(s for s in at.segmented_control if s.label == "Your mark").set_value("agree").run()
    assert any(k.startswith(f"{case}|omics|") for k in at.session_state.reviews)
    for view in VIEWS:
        at.segmented_control(key="view").set_value(view).run()
        assert not at.exception, view
    assert "Tumor-board note" in shown(at) and "nothing alarming" in shown(at)

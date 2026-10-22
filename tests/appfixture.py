"""The whole app under AppTest, on a bundle built from the test cohort: no network, no keys, no
CIViC download, the trials from their snapshot, and the test cohort's first case standing in
for a TCGA patient with a processed public MRI. The ``app`` fixture (tests/conftest.py) returns
``make_app``'s namespace: ``app.new()`` is a fresh AppTest, ``app.demo`` the loaded cases,
``app.case`` that first case's file id and ``app.shipped`` the MRI studies it borrows."""

import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import torch

from muffle.demo import build_demo, pick_cases, save_bundle, subset
from muffle.hotreload import source_digest
from muffle.models import MuffleNet
from muffle.report import civic, trials
from muffle.workbench import radiology

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app" / "streamlit_app.py"
RESULTS = ROOT / "app" / "workbenches" / "radiology_results"


def make_app(cohort, small_cfg, tmp_path, monkeypatch) -> SimpleNamespace:
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
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
    # the test cohort's first case stands in for a TCGA patient with a processed public MRI
    shipped = [s for v in radiology.load_index(RESULTS).values() for s in v
               if s["modality"] == "MR"]
    monkeypatch.setattr(radiology, "load_index",
                        lambda folder: {demo.cases[0].index: shipped[:1]})
    # this process already runs this code, so the app's hot-reload guard must not purge it
    monkeypatch.setattr(sys, "_muffle_code_digest",
                        source_digest([APP.parent, ROOT / "src" / "muffle"]), raising=False)
    return SimpleNamespace(new=lambda: AppTest.from_file(str(APP), default_timeout=120),
                           demo=demo, case=f"Case {demo.cases[0].index}", shipped=shipped)


def shown(at) -> str:
    """The page's text: titles, headings, Markdown, captions and info boxes."""
    return " ".join(e.value for kind in ("title", "header", "subheader", "markdown", "caption",
                                         "info") for e in getattr(at, kind))


def button(at, label: str):
    return next(b for b in at.button if b.label == label)


def popovers(at) -> dict[str, str]:
    """Every popover on the page: its label -> the Markdown and captions inside it."""
    out: dict[str, str] = {}

    def text(node) -> list[str]:
        if getattr(node, "type", None) in ("markdown", "caption"):
            return [str(node.value)]
        return [t for k in sorted(getattr(node, "children", {}) or {})
                for t in text(node.children[k])]

    def walk(node) -> None:
        if getattr(node, "type", None) == "popover":
            out[node.proto.popover.label] = " ".join(text(node))
        for k in sorted(getattr(node, "children", {}) or {}):
            walk(node.children[k])

    walk(at.main)
    return out

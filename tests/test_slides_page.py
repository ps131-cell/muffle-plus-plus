"""The pathology slide page on a patient's own scored section (app/workbenches/slides_results)."""

import json
from pathlib import Path

import pandas as pd

from muffle.workbench import invasion as inv

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "app" / "workbenches" / "slides_results"


def first_case():
    index = RESULTS / "cases.json"
    if not index.exists():
        return None, []
    cases = json.loads(index.read_text())
    for idx, names in cases.items():
        names = [n for n in names if (RESULTS / n / "summary.json").exists()]
        if names:
            return idx, names
    return None, []


def test_results_hold_only_derived_numbers_and_small_crops():
    idx, names = first_case()
    if idx is None:
        return
    for name in names:
        folder = RESULTS / name
        size = sum(p.stat().st_size for p in folder.rglob("*") if p.is_file())
        assert size < 3e6, (name, size)
        crops = list((folder / "crops").glob("*.jpg"))
        assert len(crops) <= 60
        tiles = pd.read_json(folder / "tiles.json", orient="split")
        assert {"row", "col", "qc"} <= set(tiles.columns)
        assert not any(c.startswith("emb") for c in tiles.columns)
        meta = json.loads((folder / "summary.json").read_text())
        assert meta["slide"] == name and meta["head"]["classes"]
        assert "not validated on breast" in meta["status"] or "pretrained" in meta["status"]
        assert meta["scored"]["scored_tiles"] + meta["scored"]["skipped_tiles"] == \
            meta["scored"]["tissue_tiles_total"]
        res = inv.analyze_slide(tiles, meta["head"]["classes"])
        assert res["summary"]["usable_tiles"] > 0


def test_slides_page_renders_the_patients_own_section():
    from streamlit.testing.v1 import AppTest

    idx, names = first_case()
    if idx is None:
        return
    at = AppTest.from_string(f"""
import sys
sys.path[:0] = [{str(ROOT / "app")!r}, {str(ROOT / "src")!r}]
from types import SimpleNamespace
from workbenches.slides import render
from muffle.workspace import case_file
render(case_file(SimpleNamespace(index={idx}, site="site-0", percentile=50.0, group="medium",
                                 age=50.0, stage="II", layers=["clinical"], missing=[],
                                 mutations=None), slides={names!r}))
""", default_timeout=180).run()
    assert not at.exception, at.exception
    text = " ".join(e.value for e in [*at.markdown, *at.caption, *at.info, *at.warning]).lower()
    assert "the patient's own" in text and "2d snapshot" in text
    assert "weak until validated" in text and "placeholder" in text
    assert "what this test cannot see" in text and "not reviewed by a pathologist" in text
    assert "known failures" in text and "0.785" in text
    assert not any(w in text for w in ("demo", "hackathon"))
    labels = [b.label for b in at.get("download_button")]
    assert any("JSON" in lab for lab in labels) and any("PNG" in lab for lab in labels)
    if len(names) > 1:
        assert "the sections compared" in text

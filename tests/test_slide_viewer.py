"""The slide viewer: Deep Zoom pyramid math, the mapping from the scored tile grid to pyramid
pixels on the eight shipped sections, the overlay the browser draws, the nucleus table, the
static-serving setup, and the page's two paths (viewer, and the tile map when the pyramid
can't be had) under AppTest. No network: conftest switches tile downloads off."""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from muffle.workbench import invasion as inv
from muffle.workbench import viewer

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "app" / "workbenches" / "slides_results"
MANIFEST = json.loads((RESULTS / "pyramids.json").read_text())
CASES = json.loads((RESULTS / "cases.json").read_text())


def test_deep_zoom_levels_and_tiles():
    assert viewer.dz_levels(1, 1) == [(1, 1)]
    levels = viewer.dz_levels(19920, 5025)
    assert len(levels) == 16 and levels[-1] == (19920, 5025) and levels[0] == (1, 1)
    assert levels[-2] == (9960, 2513) and levels[-3] == (4980, 1257)  # halved, rounding up
    tiles = viewer.dz_tiles(19920, 5025)
    assert tiles[-1] == (79, 20) and tiles[0] == (1, 1)
    assert sum(c * r for c, r in tiles) == 2134  # what scripts/slide_pyramid.py wrote
    assert viewer.level_drop(0.2527) == 2 and viewer.level_drop(0.248) == 2
    assert viewer.level_drop(0.504) == 1 and viewer.level_drop(1.0) == 0
    assert viewer.level_drop(0.25, 2.0) == 3


def test_every_shipped_pyramid_matches_its_math_and_its_grid():
    """Each section's manifest entry has the levels and tile count its size implies, sits at
    about 1 µm/px, and the scored grid lands inside it with tiles of 112 µm."""
    shipped = {s for names in CASES.values() for s in names}
    assert shipped <= set(MANIFEST["slides"])
    for slide, entry in MANIFEST["slides"].items():
        w, h = entry["width"], entry["height"]
        assert entry["levels"] == len(viewer.dz_levels(w, h)), slide
        assert entry["tiles"] == sum(c * r for c, r in viewer.dz_tiles(w, h, entry["tile_size"]))
        assert 0.95 <= entry["mpp"] <= 1.05 and entry["format"] == "jpeg", slide
        assert len(entry["sha256"]) == 64 and entry["zip"] == f"{slide}.zip"
        meta = json.loads((RESULTS / slide / "summary.json").read_text())
        frame = viewer.tile_frame(meta, entry)
        assert math.isclose(frame["t"] * entry["mpp"], 112, rel_tol=0.01), slide
        assert math.isclose(entry["mpp"], meta["base_mpp"] * entry["downsample"], rel_tol=1e-3)
        tiles = pd.read_json(RESULTS / slide / "tiles.json", orient="split")
        x0, y0 = viewer.to_pyramid(tiles.row.min(), tiles.col.min(), frame)
        x1, y1 = viewer.to_pyramid(tiles.row.max() + 1, tiles.col.max() + 1, frame)
        assert x0 >= 0 and y0 >= 0 and x1 <= w + 1 and y1 <= h + 1, slide


def test_tile_frame_follows_the_scored_window():
    meta = {"step_base_px": 452, "scored": {"origin_tile": [-31, 23]}}
    frame = viewer.tile_frame(meta, {"downsample": 4})
    assert frame == {"x0": 2599.0, "y0": -3503.0, "t": 113.0}
    assert viewer.to_pyramid(31, 0, frame) == (2599.0, 0.0)  # grid row 31 is the slide's row 0
    assert viewer.to_pyramid(0.5, 1.5, frame) == (2599.0 + 169.5, -3503.0 + 56.5)


def test_outline_merges_runs_and_faces_only_what_it_should():
    one = np.zeros((3, 3), bool)
    one[1, 1] = True
    assert sorted(viewer.outline(one)) == sorted([[1, 1, 2, 1], [1, 2, 2, 2], [1, 1, 1, 2],
                                                  [2, 1, 2, 2]])
    block = np.zeros((4, 4), bool)
    block[1:3, 1:3] = True
    assert len(viewer.outline(block)) == 4  # one merged segment per side
    tissue = np.zeros((4, 4), bool)
    tissue[1:3, 3] = True  # tissue only to the right of the block
    assert viewer.outline(block, against=tissue) == [[3, 1, 3, 3]]


def test_nucleus_table_round_trip_and_kinds():
    nuclei = pd.DataFrame({
        "row": [0, 0, 1, 1, 1, 1, 1, 1, 1, 1],
        "col": [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
        "x_um": [10.0, 50.0, 10.0, 15.0, 20.0, 80.0, 82.0, 84.0, 86.0, 88.0],
        "y_um": [10.0, 50.0, 10.0, 12.0, 14.0, 80.0, 82.0, 84.0, 86.0, 88.0],
        "area_um2": [30.0, 60.0, 50.0, 55.0, 60.0, 50.0, 50.0, 50.0, 50.0, 50.0],
        "solidity": [0.95, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8, 0.8]})
    back = viewer.cells_frame({"cells": viewer.cells_json(nuclei)})
    pd.testing.assert_frame_equal(back.sort_values(["row", "x_um"]).reset_index(drop=True),
                                  nuclei.sort_values(["row", "x_um"]).reset_index(drop=True),
                                  check_dtype=False)
    tiles = pd.DataFrame({"row": [0, 1], "col": [0, 0], "p_tumor": [0.9, 0.4],
                          "main_tumor": [True, False], "zone": ["core", "front band"]})
    kinds = viewer.cell_kinds(nuclei, tiles)
    assert list(kinds[:2]) == [1, 2]       # lymphocyte-like; tumor candidate (P ≥ 0.5)
    assert list(kinds[2:5]) == [3, 3, 3]   # three close candidates outside the tumor: a bud
    assert list(kinds[5:]) == [0] * 5      # five in one cluster: more than 4, not a bud
    assert viewer.cells_frame({}).empty


def first_counted_slide() -> str:
    return next(s for names in CASES.values() for s in names
                if json.loads((RESULTS / s / "nuclei.json").read_text()).get("cells"))


def test_overlay_payload_from_a_shipped_section():
    import sys

    sys.path.insert(0, str(ROOT / "app"))
    from workbenches.slides import load_slide

    slide = first_counted_slide()
    result = load_slide(RESULTS / slide)
    classes = result["meta"]["head"]["classes"]
    res = inv.analyze_slide(result["tiles"], classes)
    cells = viewer.cells_frame(result["nuclei"])
    ov = viewer.overlay(res, classes, cells)
    n = len(res["tiles"])
    assert all(len(v) == n for v in ov["tiles"].values())
    assert ov["grid"] == {"rows": res["grid_shape"][0], "cols": res["grid_shape"][1]}
    assert ov["front"] and [q["pointer"] for q in ov["queue"]] == \
        [q["pointer"] for q in res["queue"]]
    assert len(ov["arcs"]) == len(res["arcs"]) and len(ov["regions"]) == len(res["risk"]["cards"])
    assert all(r["outline"] for r in ov["regions"]) and all(s["outline"] for s in ov["islands"])
    assert sum(len(v) for v in ov["cells"].values()) == 4 * len(cells)
    # the viewer's breakaway members reproduce the pipeline's per-tile cluster counts
    t = res["tiles"].set_index(["row", "col"])
    for key, flat in ov["cells"].items():
        r, c = (int(v) for v in key.split("_"))
        members = sum(1 for k in flat[3::4] if k == 3)
        buds = int(t.loc[(r, c), "buds"])
        assert buds <= members <= 4 * buds, (key, buds, members)
    assert len(json.dumps(ov)) < 3e6


def test_static_serving_is_configured_and_tiles_stay_out_of_git():
    config = (ROOT / ".streamlit" / "config.toml").read_text()
    assert "enableStaticServing = true" in config
    assert (ROOT / "app" / "static" / ".gitkeep").exists()
    ignored = (ROOT / ".gitignore").read_text().splitlines()
    assert "/app/static/slides/" in ignored
    assert "/app/workbenches/slide_viewer_frontend/static/" in ignored
    front = ROOT / "app" / "workbenches" / "slide_viewer_frontend"
    assert {"index.html", "viewer.js", "openseadragon.min.js", "openseadragon-LICENSE.txt"} <= {
        p.name for p in front.iterdir()}
    assert "openseadragon 6.1.1" in (front / "openseadragon.min.js").read_text()[:200]


def test_tiles_go_with_the_component_until_static_serving_is_on():
    """Streamlit reads enableStaticServing when the server starts: until then the sections are
    unpacked into the component's own folder, which is served with the component."""
    import sys

    from streamlit import config

    sys.path.insert(0, str(ROOT / "app"))
    from workbenches import slide_viewer as sv

    before = config.get_option("server.enableStaticServing")
    try:
        config.set_option("server.enableStaticServing", False)
        assert sv.served() == (sv.FALLBACK, "static/slides")
        assert sv.FALLBACK.is_relative_to(sv.FRONTEND)
        config.set_option("server.enableStaticServing", True)
        assert sv.served() == (sv.STATIC, "../../app/static/slides")
    finally:
        config.set_option("server.enableStaticServing", before)


def page(slide_dir: str, case: str, slides: list[str]) -> str:
    return f"""
import sys
sys.path[:0] = [{str(ROOT / "app")!r}, {str(ROOT / "src")!r}]
from pathlib import Path
from types import SimpleNamespace
from streamlit import config
config.set_option("server.enableStaticServing", True)
from workbenches import slide_viewer
slide_viewer.STATIC = Path({slide_dir!r})
from workbenches.slides import render
from muffle.workspace import case_file
render(case_file(SimpleNamespace(index={case}, site="site-0", percentile=50.0, group="medium",
                                 age=50.0, stage="II", layers=["clinical"], missing=[],
                                 mutations=None), slides={slides!r}))
"""


def test_page_falls_back_to_the_tile_map_without_a_pyramid(tmp_path):
    from streamlit.testing.v1 import AppTest

    case, slides = next((k, v) for k, v in CASES.items() if len(v) == 1)
    at = AppTest.from_string(page(str(tmp_path), case, slides), default_timeout=180)
    hs = json.loads((RESULTS / slides[0] / "summary.json").read_text())["hotspot"]
    if hs:  # the Spot panel on the counting field's own tile: one review mark, no clash
        at.session_state[f"Case {case}|{slides[0]}-spot"] = f"r{hs['row']}c{hs['col']}"
    at.run()
    assert not at.exception, at.exception
    info = " ".join(e.value for e in at.info).lower()
    assert "slide viewer is not available here" in info and "switched off" in info
    assert any(r.label == "Layer" for r in at.radio)  # the tile map's layer control
    assert not list(tmp_path.iterdir())               # nothing downloaded


def test_page_shows_the_viewer_when_the_pyramid_is_there(tmp_path):
    from streamlit.testing.v1 import AppTest

    case, slides = next((k, v) for k, v in CASES.items() if len(v) > 1)
    for slide in slides:  # a served pyramid is a folder with its .dzi (the tiles aren't read)
        (tmp_path / slide).mkdir()
        (tmp_path / slide / f"{slide}.dzi").write_text("<Image/>")
    at = AppTest.from_string(page(str(tmp_path), case, slides), default_timeout=180).run()
    assert not at.exception, at.exception
    text = " ".join(e.value for e in at.caption).lower()
    assert "µm per pixel" in text and "minimap" in text and "openseadragon" in text
    assert "not registered" in text and "linked by physical size" in text  # side by side
    assert "slide viewer is not available" not in " ".join(e.value for e in at.info).lower()
    assert not any(r.label == "Layer" for r in at.radio)  # no tile map next to the viewer
    for slide in slides:
        written = list((tmp_path / slide).glob("overlay-*.json"))
        assert len(written) == 1, slide
        ov = json.loads(written[0].read_text())
        assert {"tiles", "front", "arcs", "queue", "cells", "classes"} <= set(ov)

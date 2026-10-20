"""Pathology slide workbench: geometry and quality rules on a hand-made tile grid, and the page."""

from pathlib import Path

import numpy as np
import pandas as pd

from muffle.workbench.slides import (
    CLASSES,
    CUTOFFS,
    PLACEHOLDER,
    QC_BLUR,
    QC_GLASS,
    QC_INK,
    QC_OK,
    TILE_UM,
    analyze,
    quality,
)

ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = ROOT / "app" / "workbenches" / "slides_example"


def fake_tiles(h=16, w=16, classes=CLASSES) -> pd.DataFrame:
    """A 16×16 region: a confident tumor square in the middle (rows 4–11, cols 4–11), stroma
    around it, one glass tile, one ink tile, one blurry tile and one unsure tile."""
    rows = []
    for r in range(h):
        for c in range(w):
            p = {k: 0.02 for k in classes}
            if 4 <= r <= 11 and 4 <= c <= 11:
                p["tumor"] = 0.9
            else:
                p["stroma"] = 0.9
            if (r, c) == (0, 0):  # unsure: split between stroma and lymphocytes
                p = {k: 0.05 for k in classes}
                p["stroma"], p["lymphocytes"] = 0.45, 0.4
            rows.append({"row": r, "col": c, "x": c * 448, "y": r * 448, "edges": 0.1,
                         "structure_cov": 0.9, "ink_bluegreen": 0.0, "ink_black": 0.0,
                         "ink_red": 0.0, "blur": 0.01, **{f"p_{k}": v for k, v in p.items()}})
    df = pd.DataFrame(rows)
    df.loc[(df.row == 15) & (df.col == 15), "edges"] = 0.001          # glass
    df.loc[(df.row == 15) & (df.col == 14), "ink_bluegreen"] = 0.5    # pen ink
    df.loc[(df.row == 15) & (df.col == 13), "blur"] = 0.0001          # blur
    return df


def test_quality_rules_in_the_colon_analyzer_order():
    q = quality(fake_tiles())
    df = fake_tiles()
    at = lambda r, c: q[(df.row == r) & (df.col == c)].item()  # noqa: E731
    assert at(15, 15) == QC_GLASS and at(15, 14) == QC_INK and at(15, 13) == QC_BLUR
    assert (q == QC_OK).sum() == 16 * 16 - 3


def test_tumor_front_zones_and_summary():
    res = analyze(fake_tiles())
    df, s = res["tiles"], res["summary"]
    assert res["grid_shape"] == [16, 16] and s["tiles"] == 256 and s["usable_tiles"] == 253
    assert s["excluded"] == {QC_GLASS: 1, QC_INK: 1, QC_BLUR: 1}
    # the 8×8 tumor square loses its 4 corners to the 3×3 smoothing: 60 tiles, and the 24
    # remaining edge tiles are the front
    assert df["tumor"].sum() == 60 and s["satellite_pieces"] == 0
    assert s["tumor_mm2"] == round(60 * (TILE_UM / 1000) ** 2, 2)
    assert df["front"].sum() == 24 and s["front_length_mm"] == round(24 * TILE_UM / 1000, 2)
    centre = df[(df.row == 7) & (df.col == 7)].iloc[0]
    assert centre["label"] == "tumor" and centre["zone"] == "front band"  # 3.4 tiles = 380 µm
    corner = df[(df.row == 0) & (df.col == 15)].iloc[0]
    assert corner["zone"] in ("peritumoral", "outside") and not corner["tumor"]
    assert s["facing"] == {"stroma": 1.0}
    assert s["zone_tiles"]["core"] == 0  # an 8-tile square has no tile > 500 µm inside
    unsure = df[(df.row == 0) & (df.col == 0)].iloc[0]
    assert unsure["unsure"] and unsure["top_p"] == 0.45
    assert s["unsure_share"] == round(1 / 253, 3)
    assert abs(sum(s["tissue_fractions"].values()) - 1) < 0.01


def test_every_cutoff_names_a_source_and_placeholders_are_tagged():
    tags = {tag for _, tag, _ in CUTOFFS.values()}
    assert tags <= {PLACEHOLDER, "literature", "measured", "design"}
    assert CUTOFFS["unsure_below"][1] == PLACEHOLDER
    rules = [k for k in CUTOFFS if k.startswith(("glass", "ink", "blur"))]
    assert rules and all(CUTOFFS[k][1] == PLACEHOLDER for k in rules)


def test_example_result_holds_only_derived_numbers():
    if not (EXAMPLE / "tiles.csv").exists():
        return
    tiles = pd.read_csv(EXAMPLE / "tiles.csv")
    assert {"row", "col", "qc", "edges", "blur"} <= set(tiles.columns)
    probs = tiles[[c for c in tiles.columns if c.startswith("p_")]]
    assert np.allclose(probs.sum(axis=1), 1, atol=0.01)
    assert not any(c.startswith("emb") or c == "bcss_label" for c in tiles.columns)
    res = analyze(tiles, [c[2:] for c in probs.columns])
    assert res["summary"]["usable_tiles"] > 0


def test_slides_page_renders_for_both_file_kinds():
    from streamlit.testing.v1 import AppTest

    page = str(ROOT / "app" / "workbenches" / "slides.py")
    at = AppTest.from_file(page, default_timeout=90).run()
    assert not at.exception
    text = " ".join(e.value for e in [*at.markdown, *at.caption, *at.info, *at.warning]).lower()
    assert "nothing below is this patient's tissue" in text
    assert not any(w in text for w in ("demo", "hackathon"))
    if (EXAMPLE / "tiles.csv").exists():
        assert "placeholder" in text and "what this map cannot see" in text
        assert "held out" in text and "not reviewed by a pathologist" in text

    tcga = AppTest.from_string(f"""
import sys
sys.path[:0] = [{str(ROOT / "app")!r}, {str(ROOT / "src")!r}]
from types import SimpleNamespace
from workbenches.slides import render
from muffle.workspace import case_file
render(case_file(SimpleNamespace(index=1, site="site-0", percentile=50.0, group="medium",
                                 age=50.0, stage="II", layers=["clinical"], missing=[],
                                 mutations=None)))
""", default_timeout=90).run()
    assert not tcga.exception
    assert "holds no slide image" in tcga.info[0].value

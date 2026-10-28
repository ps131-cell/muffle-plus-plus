"""The slide map ported from the team's Colon Tumor Front Analyzer (``muffle.workbench.tile_map``,
``slide_search``, ``slide_export``): its data layer on the shipped sections, and the slide page
on Case 299, Case 926 (its known-failure note) and Case 730 (a windowed section) under
AppTest."""

import io
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from PIL import Image

from muffle.workbench import invasion as inv
from muffle.workbench import slide_export, slide_search, tile_map
from muffle.workbench.slides import COLORS, LABELS, QC_UNLIKE

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "app" / "workbenches" / "slides_results"
CASES = json.loads((RESULTS / "cases.json").read_text()) if (RESULTS / "cases.json").exists() \
    else {}


def section(name: str):
    folder = RESULTS / name
    meta = json.loads((folder / "summary.json").read_text())
    tiles = pd.read_json(folder / "tiles.json", orient="split")
    nuc = json.loads((folder / "nuclei.json").read_text())
    if nuc.get("tiles") and nuc["tiles"].get("data"):
        tiles = tiles.merge(pd.DataFrame(nuc["tiles"]["data"], columns=nuc["tiles"]["columns"]),
                            on=["row", "col"], how="left")
    res = inv.analyze_slide(tiles, meta["head"]["classes"])
    thumb = Image.open(folder / "thumbnail.jpg").convert("RGB")
    data = tile_map.build(res["tiles"], meta["head"]["classes"], res["grid_shape"], thumb.size,
                          meta, key=f"test-{name}")
    return meta, res, data, thumb


@pytest.fixture(scope="module")
def s299():
    if "299" not in CASES:
        pytest.skip("Case 299's section is not shipped")
    return section(CASES["299"][0])


def png_size(raw: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(raw)).size


def test_overlay_is_one_pixel_per_tile_and_the_scan_is_the_thumbnail(s299):
    meta, res, data, thumb = s299
    g = data.geom
    for mode in tile_map.modes(data, res):
        assert png_size(tile_map.overlay_png(data, mode)) == (g["cols"], g["rows"]), mode
    assert png_size(tile_map.scan_jpeg(thumb, data)) == thumb.size
    assert tile_map.map_image(thumb, data, "tissue", 0.5).size == thumb.size
    rgba = tile_map.tile_rgba(data, "tissue")
    tumor = np.flatnonzero((data.label == data.classes.index("tumor")) & data.ok)[0]
    assert tuple(rgba[data.rows[tumor], data.cols[tumor], :3]) == tile_map.hex_rgb(COLORS["tumor"])
    bad = np.flatnonzero(~data.ok)[0]
    assert tuple(rgba[data.rows[bad], data.cols[bad], :3]) == \
        tile_map.hex_rgb(tile_map.NOT_ANALYZED)
    qc = tile_map.tile_rgba(data, "qc")
    unlike = np.flatnonzero(data.reason == QC_UNLIKE)
    if len(unlike):
        assert tuple(qc[data.rows[unlike[0]], data.cols[unlike[0]], :3]) == tile_map.hex_rgb(
            tile_map.QC_COLORS[QC_UNLIKE])
    assert qc[data.rows[tumor], data.cols[tumor], 3] == 0  # a passed tile has no QC colour


def test_the_legend_names_the_head_classes_the_zones_and_the_exclusions(s299):
    meta, res, data, _ = s299
    tissue = [text for text, _ in tile_map.legend_items(data, "tissue")]
    for k in meta["head"]["classes"]:
        assert any(t.startswith(LABELS[k]) for t in tissue), k
    assert f"Excluded · {int((~data.ok).sum())} squares" in tissue
    zones = [text for text, _ in tile_map.legend_items(data, "zones")]
    assert "Invasive front" in zones and "Tumor core" in zones
    risk = " ".join(text for text, _ in tile_map.legend_items(data, "risk", res))
    assert "Level 3" in risk and "points" in risk
    assert "immune" in tile_map.modes(data, res)  # nuclei were counted on this section


def test_the_hover_box_names_the_class_its_labels_and_finds_the_clicked_tile(s299):
    _, _, data, _ = s299
    groups = tile_map.hover_groups(data)
    names = {LABELS[k] for k in data.classes}
    assert sum(len(idx) for _, idx in groups) == len(data.rows)
    for (cls, cert, zone), _ in groups:
        assert cls in names or cls.startswith("Excluded: "), cls
        assert cert in ("Confident", "Unsure here", "Not scored")
        text = tile_map.group_template((cls, cert, zone))
        assert "Model inference" in text and "(placeholder)" in text and "r%{customdata[2]}" in text
    fig, first = tile_map.figure(data, b"jpeg", {"tissue": b"png"}, {"tissue": []})
    i, j = 3, 0
    assert tile_map.clicked_tile(data, first + i, j, None, first) == int(groups[i][1][j])
    assert tile_map.clicked_tile(data, 99, None, [[7]], first) == 7  # a marker's tile index


def test_the_figure_has_the_views_slider_pointers_and_the_slides_shape(s299):
    meta, res, data, thumb = s299
    modes = tile_map.modes(data, res)
    overlays = {m: tile_map.overlay_png(data, m) for m in modes}
    legends = {m: tile_map.legend_items(data, m, res) for m in modes}
    markers = [{"r": q["row"], "c": q["col"], "label": q["pointer"], "color": "#2468c0"}
               for q in res["queue"]]
    fig, _ = tile_map.figure(data, tile_map.scan_jpeg(thumb, data), overlays, legends,
                             markers=markers, res=res)
    labels = [b.label for b in fig.layout.updatemenus[0].buttons]
    assert labels == ["Tissue", "Zones", "Risk", "Flags", "Certainty", "Quality", "Immune"]
    assert len(fig.layout.sliders[0].steps) == 21 and fig.layout.yaxis.scaleanchor == "x"
    assert [a.text for a in fig.layout.annotations] == [f"<b>{q['pointer']}</b>"
                                                        for q in res["queue"]]
    for b in fig.layout.updatemenus[0].buttons:  # each view shows its own picture only
        shown = [i for i in range(1, 1 + len(modes)) if b.args[0]["visible"][i]]
        assert shown == [1 + labels.index(b.label)]


def test_a_kept_figure_draws_exactly_as_the_built_one(s299):
    """The pages keep a map's figure as its plain dict (memory pass): st.plotly_chart must send
    the browser the same spec, byte for byte, and the kept dict must not be copied per rerun."""
    import plotly.io as pio
    import plotly.tools

    meta, res, data, thumb = s299
    modes = tile_map.modes(data, res)
    fig, _ = tile_map.figure(data, tile_map.scan_jpeg(thumb, data),
                             {m: tile_map.overlay_png(data, m) for m in modes},
                             {m: tile_map.legend_items(data, m, res) for m in modes}, res=res)
    kept = tile_map.frozen(fig)

    def sent(f):  # what st.plotly_chart (Streamlit 1.66) puts in the element
        return pio.to_json(plotly.tools.return_figure_from_figure_or_data(f, True),
                           validate=False)

    assert sent(kept) == sent(fig)
    assert kept.to_dict() is kept.to_dict()


def test_search_maps_words_to_classes_zones_flags_and_pointers(s299):
    _, res, data, _ = s299
    assert slide_search.understand("lymphocytes at the border") == (["lymphocytes"], [],
                                                                    "front band")
    assert slide_search.understand("necrosis in the core") == (["necrosis"], [], "core")
    assert slide_search.understand("invasive carcinoma") == (["tumor"], [], None)
    assert slide_search.understand("satellite tumor") == ([], ["island"], None)
    hit = slide_search.search(data, "lymphocytes at the border", res)
    assert hit["understood"] and hit["zone"] == "front band"
    assert (hit["values"][data.zone != "front band"] == 0).all()
    assert [s["label"] for s in hit["spots"]] == [f"Q{n}" for n in range(1, len(hit["spots"]) + 1)]
    assert any("Lymphocytes" in u for u in hit["used"])
    t2 = res["queue"][1]
    hit = slide_search.search(data, "show me T2", res)
    assert hit["spots"] == [{"r": t2["row"], "c": t2["col"], "score": 1.0, "label": "T2"}]
    hit = slide_search.search(data, "HER2 status", res)
    assert not hit["understood"] and "can't see" in hit["message"]
    hit = slide_search.search(data, "carcinoma", res)  # absolute: the spot's score is its value
    assert hit["spots"] and hit["spots"][0]["score"] == pytest.approx(hit["values"].max())
    alpha = tile_map.tile_rgba(data, "match", values=hit["values"])[data.rows, data.cols, 3]
    assert (alpha[(hit["values"] < tile_map.MATCH_MIN) & data.ok] == 0).all()
    assert (alpha[hit["values"] >= tile_map.MATCH_MIN] >= 150).all()
    hit = slide_search.search(data, "unlike training", res)
    assert hit["understood"] and any("unlike training tissue" in u for u in hit["used"])
    assert set(np.flatnonzero(hit["values"] > 0)) <= set(np.flatnonzero(~data.ok))
    assert not slide_search.search(data, "zebra", res)["understood"]


def test_export_makes_a_labelled_png_and_a_markdown_report(s299):
    meta, res, data, thumb = s299
    raw = slide_export.map_png(thumb, data, "zones", title="TCGA-AN-A0AS-DX1",
                               legend=tile_map.legend_items(data, "zones", res))
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = png_size(raw)
    assert w > thumb.width and h > thumb.height  # the title above, the key below
    q = res["queue"][0]
    md = slide_export.report_markdown(
        "Case 299", meta["slide"], meta, res, marks={(q["row"], q["col"]): {"mark": "agree"}},
        notes="Check T1 at 20x.", cutoffs=inv.CUTOFFS, known_failures=inv.KNOWN_FAILURES)
    assert md.startswith(f"# Pathology slide report: {meta['slide']}")
    for text in ("model inference", "hypothesis", "Every cutoff and its source",
                 "Known failures", "Check T1 at 20x.", "not a diagnosis", "1 of"):
        assert text in md, text
    assert all(f"| {p['pointer']} |" in md for p in res["queue"])


def test_a_windowed_section_paints_the_grid_beyond_the_slide_as_glass():
    name = next((n for names in CASES.values() for n in names
                 if json.loads((RESULTS / n / "summary.json").read_text())["scored"][
                     "origin_tile"][0] < 0), None)
    if name is None:
        pytest.skip("no shipped window reaches past the slide's edge")
    meta, _, data, thumb = section(name)
    r0, c0, r1, c1 = data.geom["slide_box"]
    assert r0 == -meta["scored"]["origin_tile"][0] > 0
    scan = Image.open(io.BytesIO(tile_map.scan_jpeg(thumb, data))).convert("RGB")
    top = np.asarray(scan)[: int(r0 * data.geom["step_y"]) - 2]
    assert np.abs(top.astype(int) - tile_map.GLASS_TINT).max() < 12  # glass, not black


PAGE = """
import sys
sys.path[:0] = [{app!r}, {src!r}]
from types import SimpleNamespace
from workbenches.slides import render
from muffle.workspace import case_file
render(case_file(SimpleNamespace(index={idx}, site="site-0", percentile=50.0, group="medium",
                                 age=50.0, stage="II", layers=["clinical"], missing=[],
                                 mutations=None), slides={slides!r}))
"""


@pytest.mark.parametrize("idx", ["299", "926", "730"])
def test_the_slide_page_draws_the_map_on_three_cases(idx):
    from streamlit.testing.v1 import AppTest

    if idx not in CASES:
        pytest.skip(f"Case {idx} is not shipped")
    slides = CASES[idx]
    at = AppTest.from_string(PAGE.format(app=str(ROOT / "app"), src=str(ROOT / "src"), idx=idx,
                                         slides=slides), default_timeout=240).run()
    assert not at.exception, at.exception
    charts = at.get("plotly_chart")
    assert len(charts) == 1
    spec = json.loads(charts[0].proto.spec)
    labels = [b["label"] for b in spec["layout"]["updatemenus"][0]["buttons"]]
    assert labels[:4] == ["Tissue", "Zones", "Risk", "Flags"]
    text = " ".join([*(e.value for e in [*at.markdown, *at.caption, *at.warning, *at.info]),
                     *(e.label for e in at.expander)])
    assert "Slide map" in text and "squares ≈ 1 mm" in text
    assert not any(w in text.lower() for w in ("demo", "hackathon"))
    meta = json.loads((RESULTS / slides[0] / "summary.json").read_text())
    for note in meta.get("known_failures", []):  # Case 926's note stays on the page
        assert f"Known failure on this section: {note}" in text
    if meta["scored"].get("window_side_tiles"):  # Case 730: a windowed section says so
        assert "Only the tumor-centred window was scored" in text
    labels = [b.label for b in at.get("download_button")]
    assert any("Markdown" in lab for lab in labels) and any("PNG" in lab for lab in labels)
    k = f"Case {idx}|{slides[0]}"
    at.text_input(key=f"{k}-search").set_value("necrosis in the core").run()
    assert not at.exception, at.exception
    answer = " ".join(e.value for e in at.caption)
    assert "matched Necrosis or debris" in answer
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)
    if "Nothing reaches 15%" in answer:  # nothing to colour: the usual views stay (as R4-8)
        assert spec["layout"]["updatemenus"][0]["buttons"][0]["label"] == "Tissue"
        assert "The map below colours every square" not in answer
    else:  # one view: coloured by match
        assert not spec["layout"].get("updatemenus")


@pytest.mark.parametrize("idx", ["563", "299"])
def test_the_slide_page_speaks_plainly_and_its_spot_panel_wraps(idx):
    """QA R3-4: "skipped (the budget for this PC's CPU)", "this PC" on the slide page; plain words
    now ("not scored", the computer that scored the sections). R3-11: the Spot panel's pictures and
    "Zoom to the cells" sat in a third-width column (the label cut, the pictures over the words at
    800 px); they share a row that wraps, never fixed columns."""
    from streamlit.testing.v1 import AppTest

    from tests.test_states import in_columns

    if idx not in CASES:
        pytest.skip(f"Case {idx} is not shipped")
    at = AppTest.from_string(PAGE.format(app=str(ROOT / "app"), src=str(ROOT / "src"), idx=idx,
                                         slides=CASES[idx]), default_timeout=240).run()
    assert not at.exception, at.exception
    text = " ".join(e.value for e in [*at.markdown, *at.caption, *at.warning, *at.info])
    for machine in ("this PC", "PC's", "budget", "were skipped"):
        assert machine not in text, machine
    meta = json.loads((RESULTS / CASES[idx][0] / "summary.json").read_text())
    if meta["scored"].get("skipped_tiles"):  # Case 563: 10,712 tiles outside its window
        assert f"{meta['scored']['skipped_tiles']} tissue tiles outside the scored window were " \
               "not scored" in text
    if (ROOT / "app" / "static" / "slides").is_dir():  # the viewer's pyramids (not in CI)
        assert "Zoom to the cells" in [b.label for b in at.button]
    assert not in_columns(at), in_columns(at)

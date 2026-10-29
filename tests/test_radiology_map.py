"""The radiology scan map (``muffle.workbench.radiology_map``, ``radiology_search``,
``radiology_export``; docs/radiology.md §8): its data layer on the shipped studies and the public
example pair, and the radiology page under AppTest for every file that holds imaging and for the
example pair."""

import io
import json
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from muffle.workbench import radiology as rad
from muffle.workbench import radiology_export as rx
from muffle.workbench import radiology_map as rm
from muffle.workbench import radiology_search as rs

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "app" / "workbenches" / "radiology_results"
INDEX = rad.load_index(RESULTS)


def strip(study: dict, key: str) -> np.ndarray:
    d = study["display"]
    return np.asarray(Image.open(Path(study["folder"]) / f"{key}.jpg").convert("L")).reshape(
        d["slices"], d["rows"], d["cols"])


def png_size(raw: bytes) -> tuple[int, int]:
    return Image.open(io.BytesIO(raw)).size


@pytest.fixture(scope="module")
def mri():
    """Case 563's study (three candidates, C2 washes out), its subtraction, skin and nipples."""
    study = rad.load_study(RESULTS / "TCGA-BH-A0H5")
    if study is None:
        pytest.skip("case 563's study is not shipped")
    sub = strip(study, "sub")
    skin = rad.skin_rows(strip(study, "pre")).astype(np.int16)
    return study, sub, skin, rm.nipples(skin, study["display"])


def slice_of(mri, cid: str = "C1"):
    study, sub, skin, nips = mri
    c = next(c for c in study["candidates"] if c["id"] == cid)
    i = rm.ld_index(study, c)
    return c, i, rm.mri_slice(study, i, sub, skin, nips)


def test_layers_are_one_pixel_per_shown_pixel_and_sit_on_the_contours(mri):
    from scipy import ndimage

    study = mri[0]
    d = study["display"]
    c1, i, m = slice_of(mri)
    assert rm.modes(m) == ["lesion", "kinetics", "enhancement"]  # Change needs a second date
    for mode in rm.modes(m):
        assert png_size(rm.overlay_png(m, mode)) == (d["cols"], d["rows"]), mode
    inside = rm.fill_polygons(c1["per_slice"][str(i)]["contours"], d["rows"], d["cols"])
    lesion, kin = rm.overlay_rgba(m, "lesion"), rm.overlay_rgba(m, "kinetics")
    assert (lesion[inside][:, :3] == rm.hex_rgb(rm.CANDIDATE_COLORS["C1"])).all()
    assert (kin[inside][:, :3] == rm.hex_rgb(rm.CURVE_COLORS[c1["kinetics"]["delayed"]])).all()
    band = m.pix["band"] == 1  # outside the contour, within the placeholder margin
    dist = ndimage.distance_transform_edt(~inside) * d["pixel_mm"]
    assert band.any() and not (band & inside).any()
    assert dist[band].max() <= rad.CUTOFFS["margin_band_mm"][0] + 1e-9
    enh = rm.overlay_rgba(m, "enhancement")  # display bins from a quarter of the brightest
    assert (enh[m.pix["sub"] < 0.25 * 255][:, 3] == 0).all() and enh[..., 3].any()
    ln = next(x for x in rm.contour_lines(study, i) if x["id"] == "C1")
    poly = c1["per_slice"][str(i)]["contours"][0]  # pixel centres at integers: half a pixel on
    assert (ln["x"][0], ln["y"][0]) == (poly[0][0] + 0.5, poly[0][1] + 0.5)
    assert m.square == rm.square_px(d["pixel_mm"]) == 4  # about 4.5 mm at 1.133 mm per pixel


def test_the_map_cutoffs_and_legends_carry_their_sources(mri):
    assert rad.CUTOFFS["margin_band_mm"][1] == rad.PLACEHOLDER
    assert rad.CUTOFFS["map_square_mm"][1] == rad.DESIGN
    names = [what for what, _ in rad.PLACEHOLDERS]
    assert "margin_band_mm" in names and "map_square_mm" not in names
    _, _, m = slice_of(mri)
    kin = [t for t, _ in rm.legend_items(m, "kinetics")]
    assert kin[:3] == ["Persistent (I): above +10%", "Plateau (II): within ±10%",
                       "Washout (III): below −10%"]
    assert "Cutoffs: literature, placeholder" in kin
    lesion = " ".join(t for t, _ in rm.legend_items(m, "lesion"))
    assert all(f"{c} contour (MedSAM)" in lesion for c in ("C1", "C2", "C3"))
    assert "Margin band ≤ 3 mm" in lesion and "Search limit (cleft + 10 mm)" in lesion
    assert "display bins" in " ".join(t for t, _ in rm.legend_items(m, "enhancement"))
    assert all(len(rm.legend_items(m, md)) <= 6 for md in rm.modes(m))


def test_hover_boxes_are_fixed_size_labelled_and_name_their_square(mri):
    _, i, m = slice_of(mri)
    groups = rm.hover_groups(m)
    assert sum(len(idx) for _, idx in groups) == len(m.sq_r)
    lines = set()
    for texts, idx in groups:
        template = rm.group_template(m, texts)
        assert rm.RULE in template and "Model inference" in template
        assert "slice %{customdata[4]}" in template and "r%{y:.0f}c%{x:.0f}" in template
        lines.add(template.count("<br>"))
        data = rm.hover_data(m, idx)
        assert data.dtype == np.int16 and (data[:, 4] == i + 1).all()
    assert len(lines) == 1  # every box holds the same lines: one size
    regions = {texts[0] for texts, _ in groups}
    assert any(r.startswith("C1 · inside the contour") for r in regions)
    assert "C1 · margin band (≤ 3 mm)" in regions and "Breast tissue" in regions
    # a click: a typed array reaches Streamlit as {"0": …}; the point's x and y are its centre
    assert rm.clicked({"0": 13, "1": 40, "2": 33, "3": 96, "4": i + 1}, 70, 142) == \
        ("square", i, 142, 70)
    assert rm.clicked([["cand:C2"]]) == ("cand", "C2") and rm.clicked(None) is None
    j = rm.square_at(m, 142, 70)
    assert j is None or rm.square_name(m, j).startswith("r14")


def test_the_window_keeps_its_controls_inside_the_chart(mri):
    study, sub, skin, nips = mri
    c1, i, m = slice_of(mri)
    shown = list(range(i - 2, i + 3))
    early = strip(study, "early")
    frames = []
    for k in shown:
        mk = rm.mri_slice(study, k, sub, skin, nips)
        frames.append(rm.frame_of(mk, rm.scan_jpeg(early[k]),
                                  {md: rm.overlay_png(mk, md) for md in rm.modes(mk)},
                                  rm.candidate_pointers(study, k)))
    legends = {md: rm.legend_items(m, md) for md in rm.modes(m)}
    zoom = rm.zoom_box(m, 120, 60)
    fig, first = rm.figure(frames, legends, active_frame=2, study=study, zoom=zoom,
                           total=study["display"]["slices"], uirevision="test")
    assert [b.label for b in fig.layout.updatemenus[0].buttons] == ["Lesion", "Kinetics",
                                                                   "Enhancement"]
    opacity, slices = fig.layout.sliders
    assert opacity.currentvalue.prefix == "Colour layer " and len(opacity.steps) == 21
    assert slices.currentvalue.prefix == "Slice " and slices.active == 2
    assert [s.method for s in slices.steps] == ["animate"] * 5
    assert [s.label for s in slices.steps] == [str(k + 1) for k in shown]
    assert len(fig.frames) == 5 and all(f.traces == fig.frames[0].traces for f in fig.frames)
    for f in fig.frames:  # a frame changes the slice's data, never what a view button shows
        assert all(t.visible is None for t in f.data)
    for b in fig.layout.updatemenus[0].buttons:  # each view shows its own overlay only
        shown_overlays = [k for k in (1, 2, 3) if b.args[0]["visible"][k]]
        assert len(shown_overlays) == 1
    assert list(fig.layout.xaxis.range) == [zoom[1], zoom[3]]
    assert fig.layout.uirevision == "test" and fig.layout.yaxis.scaleanchor == "x"
    assert [a.text for a in fig.layout.annotations][0].startswith("<b>C")
    assert isinstance(first, int) and fig.data[first].type == "scattergl"


def test_pointers_mark_the_candidates_on_their_slice_and_elsewhere(mri):
    study = mri[0]
    _, i, m = slice_of(mri)
    ps = rm.candidate_pointers(study, i, {"C1": ["contour unsure on 0 slices"]})
    assert {p["id"] for p in ps if p["on"]} == {c["id"] for c in study["candidates"]
                                                if str(i) in c["per_slice"]}
    for p in ps:
        if not p["on"]:
            assert p["label"] == f"{p['id']} · slice {p['slice'] + 1}"
            assert p["color"] == rm.OFF_SLICE
    assert "contour unsure" in next(p for p in ps if p["id"] == "C1")["hover"]


def test_search_maps_known_words_and_says_what_a_map_cannot_see(mri):
    study, sub, skin, _ = mri
    kw = dict(sub=sub, skin=skin)
    washout = [c["id"] for c in study["candidates"] if c["kinetics"]["delayed"] == "washout"]
    hit = rs.search(study, "washout", **kw)
    assert hit["understood"] and washout == ["C2"]
    assert [s["label"] for s in hit["spots"]] == [f"Q{n}" for n in range(1, len(hit["spots"]) + 1)]
    assert hit["spots"][0]["cand"] == "C2"
    c2 = next(c for c in study["candidates"] if c["id"] == "C2")
    assert set(np.flatnonzero(hit["volume"].reshape(len(hit["volume"]), -1).max(1))) <= \
        {int(k) for k in c2["per_slice"]}  # only C2's slices light up
    hit = rs.search(study, "enhancing lesion", **kw)
    assert hit["understood"] and len(hit["used"]) == 2
    hit = rs.search(study, "spiculated margin", **kw)
    assert hit["understood"] and "cannot read spiculation" in hit["used"][0]
    hit = rs.search(study, "show me C3", **kw)
    c3 = next(c for c in study["candidates"] if c["id"] == "C3")
    assert hit["spots"][0]["label"] == "C3" and hit["spots"][0]["slice"] == rm.ld_index(study,
                                                                                        c3)
    assert "largest" in rs.search(study, "largest", **kw)["used"][0]
    assert rs.search(study, "near the chest wall", **kw)["understood"]
    for words in ("calcifications", "lymph node", "histology", "receptor status", "grade",
                  "HER2", "is it cancer"):
        hit = rs.search(study, words, **kw)
        assert not hit["understood"] and "can't see" in hit["message"], words
    assert "One study date" in rs.search(study, "did it grow", **kw)["message"]
    hit = rs.search(study, "zebra", **kw)
    assert not hit["understood"] and "No known words" in hit["message"]
    assert rs.understand("type III") == ["washout"] and rs.understand("fast wash-in") == ["fast"]


def test_mammograms_get_the_density_view_and_search_by_view():
    folder = next((s["folder"] for v in INDEX.values() for s in v if s["modality"] == "MG"),
                  None)
    if folder is None:
        pytest.skip("no mammography study is shipped")
    study = rad.load_study(RESULTS / folder)
    maps = {}
    for n, v in enumerate(study["views"]):
        img = np.asarray(Image.open(Path(study["folder"]) / v["image"]).convert("L"))
        maps[v["key"]] = rm.mammo_view(study, v, img, n)
        m = maps[v["key"]]
        assert rm.modes(m) == ["density"] and png_size(rm.overlay_png(m, "density")) == \
            img.shape[::-1]
        assert abs(m.info["dense_share"] - v["dense"]["dense_fraction"]) < 0.05  # copy vs original
        legend = " ".join(t for t, _ in rm.legend_items(m, "density"))
        assert "placeholder" in legend and f"MONAI density {m.info['monai']['density_class']}" \
            in legend
        template = rm.group_template(m, rm.hover_groups(m)[0][0])
        assert "Dense px" in template and "mammoscreen" in template and rm.RULE in template
    hit = rs.search(study, "dense", views=maps)
    assert hit["understood"] and hit["spots"] and all("view" in s for s in hit["spots"])
    assert rs.values_for(hit, maps["R-CC"]).shape == (len(maps["R-CC"].sq_r),)
    assert "No lesion detector" in rs.search(study, "mass", views=maps)["message"]
    assert "can't see" in rs.search(study, "microcalcifications", views=maps)["message"]


def test_the_example_pairs_change_layer_compares_two_dates_without_new_or_gone():
    loaded = rad.load_pair(rad.EXAMPLE)
    if not loaded:
        pytest.skip("the example pair is not in this checkout")
    pair, earlier, later = loaded
    ch = rad.pair_change(pair, earlier, later)
    c1 = next(c for c in later["candidates"] if c["id"] == "C1")
    i = rm.ld_index(later, c1)
    d = later["display"]
    now = {c["id"]: rm.fill_polygons(c["per_slice"][str(i)]["contours"], d["rows"], d["cols"])
           for c in later["candidates"] if str(i) in c["per_slice"]}
    ed = earlier["display"]
    before = {c["id"]: rad.aligned_view(
        rad.candidate_mask(c, (ed["slices"], ed["rows"], ed["cols"])).astype(np.uint8) * 255, ed,
        d, ch["registration"], "axial", i) > 127 for c in earlier["candidates"]}
    layer = rm.change_layer(later, earlier, ch, i, now, before)
    assert set(np.unique(layer["classes"])) <= {0, 1, 2, 3, 4, 5}
    assert layer["classes"].any() and layer["unreliable"]  # 99 of 112 blocks are unreliable
    skin = rad.skin_rows(strip(later, "pre")).astype(np.int16)
    m = rm.mri_slice(later, i, strip(later, "sub"), skin, rm.nipples(skin, d), layer)
    assert rm.modes(m)[-1] == "change"
    names = [t for t, _ in rm.legend_items(m, "change")]
    assert "Alignment unreliable here" in names and "Later date only" in names
    assert not any(w in " ".join(names).lower() for w in (" new", "gone", "forecast"))
    tint = rm.overlay_rgba(m, "change")
    assert (tint[layer["classes"] == 1][:, :3] == rm.hex_rgb(rm.CHANGE[1][1])).all()


def test_exports_make_a_labelled_png_and_a_markdown_study_report(mri):
    study = mri[0]
    _, i, m = slice_of(mri)
    img = strip(study, "early")[i]
    raw = rx.map_png(img, m, "lesion", study=study, markers=rm.candidate_pointers(study, i),
                     title="TCGA-BH-A0H5", subtitle="test")
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    w, h = png_size(raw)
    assert w > img.shape[1] and h > img.shape[0]  # enlarged, a title above and a key below
    look = [{"pointer": "C2", "what": "C2: washout curve (type III)", "why": "a model contour",
             "evidence": "model inference", "trust": "weak", "key": "k1"}]
    md = rx.report_markdown("Case 563", study, look=look, marks={"k1": {"mark": "agree"}},
                            overview="**Observed** report facts.",
                            known_failures=rad.KNOWN_FAILURES)
    assert md.startswith("# Radiology study report: Breast MRI")
    for text in ("## What was imaged (observed)", "## Measurements (model inference",
                 "## Look here (1 of 1 marked by you)", "| agree |", "## Change over time",
                 "One MR study date on file", "## Every cutoff and its source",
                 "## Known failures", "not a diagnosis", "No BI-RADS assessment",
                 "literature, placeholder until calibrated"):
        assert text in md, text
    assert all(f"| {k} |" in md for k in rad.CUTOFFS)
    mg = next((s for v in INDEX.values() for s in v if s["modality"] == "MG"), None)
    if mg:
        md = rx.report_markdown("Case 926", rad.load_study(RESULTS / mg["folder"]), look=[],
                                marks={})
        assert "## Density and scores (model inference)" in md and "No lesion detector" in md


# --- the page, under AppTest ------------------------------------------------------------------
PAGE = """
import sys
sys.path[:0] = [{app!r}, {src!r}]
from types import SimpleNamespace
from muffle.workspace import case_file
from workbenches.radiology import render
pf = case_file(SimpleNamespace(index={idx}, site="site-0", percentile=50.0, group="medium",
                               age=50.0, stage="II", layers=["clinical"], missing=[],
                               mutations=None), None, imaging={studies!r})
for t in pf.tests:
    if t.workbench == "imaging" and {example!r}:
        t.details["root"] = "example"
render(pf)
"""
FILES = sorted(INDEX)


def page(idx, studies, example=False):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(PAGE.format(app=str(ROOT / "app"), src=str(ROOT / "src"), idx=idx,
                                         studies=studies, example=example),
                             default_timeout=300).run()
    assert not at.exception, at.exception
    return at


def words(at) -> str:
    return " ".join([*(e.value for e in [*at.markdown, *at.caption, *at.warning, *at.info]),
                     *(e.label for e in at.expander)])


def check_map(at, study: dict, key0: str) -> dict:
    charts = at.get("plotly_chart")
    assert len(charts) == 1
    spec = json.loads(charts[0].proto.spec)
    text = words(at)
    assert "Scan map" in text and "One square ≈" in text
    assert not any(w in text.lower() for w in ("demo", "hackathon"))
    labels = [b.label for b in at.get("download_button")]
    assert any("Markdown" in x for x in labels) and any("PNG" in x for x in labels)
    if study["modality"] == "MR":
        views = [b["label"] for b in spec["layout"]["updatemenus"][0]["buttons"]]
        assert views[:3] == ["Lesion", "Kinetics", "Enhancement"]
        assert len(spec["layout"]["sliders"]) == 2 and 1 < len(spec["frames"]) <= 15
        assert "the map holds slices" in text and "**C1** ·" in text  # the Spot panel's story
    else:
        assert not spec["layout"].get("updatemenus") and len(spec["layout"]["sliders"]) == 1
        assert "Dense pixels" in json.dumps(spec["data"])
    return spec


@pytest.mark.parametrize("idx", FILES)
def test_the_page_draws_the_map_for_every_file_with_imaging(idx):
    studies = INDEX[idx]
    study = rad.load_study(RESULTS / studies[0]["folder"])
    at = page(idx, studies)
    key0 = f"rad-Case {idx}-{study['barcode']}"
    check_map(at, study, key0)
    at.text_input(key=f"{key0}-search").set_value(
        "washout" if study["modality"] == "MR" else "dense").run()
    assert not at.exception, at.exception
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)
    answer = " ".join(e.value for e in at.caption)
    assert "matched" in answer
    if "Nothing reaches 15%" in answer:  # said, and the usual views stay (QA R4-8)
        assert "The map colours every square" not in answer
        if study["modality"] == "MR":
            views = [b["label"] for b in spec["layout"]["updatemenus"][0]["buttons"]]
            assert views[:3] == ["Lesion", "Kinetics", "Enhancement"]
        assert "Match over 50%" not in json.dumps(spec["data"])
    else:
        assert not spec["layout"].get("updatemenus")  # one view: by match
    if study["modality"] == "MR" and not any(c["kinetics"].get("delayed") == "washout"
                                             for c in study["candidates"]):
        assert "Nothing reaches 15%" in answer  # said, not hidden
    # a square opened in the Spot panel (as a click on the map would)
    mem = at.session_state["rad_map_memory"][key0]
    if study["modality"] == "MR":
        c1 = study["candidates"][0]
        i = rm.ld_index(study, c1)
        s = c1["per_slice"][str(i)]
        row, col = int((s["box"][1] + s["box"][3]) / 2), int((s["box"][0] + s["box"][2]) / 2)
        mem["spot"] = {"kind": "square", "at": i, "row": row, "col": col}
    else:
        mem["spot"] = {"kind": "square", "at": "R-CC", "row": 250, "col": 120}
    at.run()
    assert not at.exception, at.exception
    text = words(at)
    assert "**Square r" in text and "Why this colour:" in text and "What to check by eye:" in text


def test_the_linked_cc_and_mlo_views_share_a_row_that_wraps():
    """QA R4-16: the mammogram's "CC and MLO, linked" put two 260 px views in st.columns(2): at
    800 px each half was narrower than its picture (8 px past the page, the captions over each
    other). They sit in a horizontal container now, one box of CC_MLO_WIDTH each, and wrap."""
    idx = next((i for i, v in INDEX.items() if v[0]["modality"] == "MG"), None)
    if idx is None:
        pytest.skip("no mammography study is shipped")
    at = page(idx, INDEX[idx])
    from workbenches.radiology import CC_MLO_WIDTH

    found = []

    def walk(node, path):
        if getattr(node, "type", None) == "image" and "behind the nipple" in str(node.proto):
            found.append(path)
        for k in sorted(getattr(node, "children", {}) or {}):
            walk(node.children[k], [*path, node])

    walk(at._tree, [])
    assert len(found) == 2, "the CC and MLO views were not drawn"
    for path in found:
        assert not any(getattr(n, "type", None) == "column" for n in path)
        row, box = [n for n in path if getattr(n, "type", None) == "flex_container"][-2:]
        assert row.proto.flex_container.direction == 2 and row.proto.flex_container.wrap
        assert box.proto.width_config.pixel_width == CC_MLO_WIDTH == 260


def test_an_mri_page_shows_the_example_pair_on_the_map_in_its_change_view():
    idx = next((i for i in FILES if INDEX[i][0]["modality"] == "MR"), None)
    if idx is None or not rad.example_studies():
        pytest.skip("no MRI study or no example pair in this checkout")
    at = page(idx, INDEX[idx])
    at.session_state[f"rad-Case {idx}-ex-open"] = True  # the lazy section, opened
    at.run()
    assert not at.exception, at.exception
    charts = at.get("plotly_chart")
    assert len(charts) == 2  # the file's own map, then the example's
    spec = json.loads(charts[1].proto.spec)
    menu = spec["layout"]["updatemenus"][0]
    assert [b["label"] for b in menu["buttons"]][-1] == "Change" and menu["active"] == 3
    text = words(at)
    assert "not new, not gone" in text and "not a forecast" in text and "no mark" in text


def test_the_page_shows_the_example_pair_with_its_change_view():
    studies = rad.example_studies()
    if not studies:
        pytest.skip("the example pair is not in this checkout")
    at = page(0, studies, example=True)
    earlier = rad.load_study(rad.EXAMPLE / studies[0]["folder"])
    check_map(at, earlier, f"rad-Case 0-{earlier['barcode']}")
    assert "public example" in words(at).lower()
    at.segmented_control(key="rad-study-Case 0").set_value(studies[1]["name"]).run()
    assert not at.exception, at.exception
    spec = json.loads(at.get("plotly_chart")[0].proto.spec)
    assert [b["label"] for b in spec["layout"]["updatemenus"][0]["buttons"]][-1] == "Change"
    assert "Alignment unreliable here" in json.dumps(spec["data"])

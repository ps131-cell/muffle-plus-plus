"""Pathology slide workbench for a patient file (docs/WORKSPACE.md, "Pathology slides";
docs/WORKBENCHES.md §5; docs/pathology.md).

streamlit run app/workbenches/slides.py        # standalone page on the example region

The workspace pages call ``render(file, version=None)`` with a ``muffle.workspace.PatientFile``;
it draws inside the current container only. When ``slides_results/<slide>/`` holds the
patient's own scored diagnostic section(s) (``scripts/slide_pipeline.py``), the page shows
them: the slide map (the section's scan with the analysis on top in seven views, the team's
Colon Tumor Front Analyzer's map adapted to breast: ``muffle.workbench.tile_map``), the slide
viewer down to single cells, the direction of invasion (arrows and a rose), breakaway
candidates with the counting field, immune pattern, satellite islands, the risk map with its
cards, a Spot panel per tile, search, review marks and notes, a comparison of two sections, the
model and validation card and export. Otherwise it shows the pipeline on a public example region
and says so. Every class is a model inference; every cutoff names its source; nothing here is a
diagnosis.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sys
import threading
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))
if str(APP) not in sys.path:  # standalone: streamlit run app/workbenches/slides.py
    sys.path.insert(0, str(APP))

import altair as alt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle.report.case_tools import INFERENCE, OBSERVED  # noqa: E402
from muffle.workbench import invasion as inv  # noqa: E402
from muffle.workbench.slides import (  # noqa: E402
    CUTOFFS,
    LABELS,
    PLACEHOLDER,
    QC_OK,
    TILE_UM,
    analyze,
    load_result,
)
from muffle.workbench import slide_export, slide_search, tile_map  # noqa: E402
from muffle.workbench.grammar import chip  # noqa: E402
from muffle.workbench.slides import queue as slide_queue  # noqa: E402
from muffle.workspace import MARKS, PLANNED, PatientFile, finding_key  # noqa: E402
from workbenches import slide_viewer  # noqa: E402
from workbenches._page import Page, land, queue_items  # noqa: E402

EXAMPLE = APP / "workbenches" / "slides_example"
RESULTS = APP / "workbenches" / "slides_results"
NO_MARK = "no mark"
MAX_MARKERS = 15
PICTURES = ["Map", "Slide viewer"]
MAP_CAPTION = (
    "The section's own scan with the analysis on top. The buttons in the map switch the view "
    "(tissue class, zones with the front and growth arrows, risk, flags, certainty, quality "
    "control, lymphocyte-like nuclei); the slider sets how see-through the colours are. Hover a "
    "square for its scores, click it for its full story in the Spot panel, scroll to zoom, drag "
    "to move, double-click or Whole section to see it all again. Each square is one score for "
    "112 µm of tissue; classes are model inferences smoothed over 3×3 squares.")
# What each class looks like on H&E, so a reader knows what to check by eye (general histology,
# not model output; the analyzer's LOOKS_LIKE, written for breast)
LOOKS_LIKE = {
    "tumor": "nests, cords or sheets of crowded cells with large, irregular, dark nuclei",
    "stroma": "pink collagen fibres with few thin, elongated nuclei",
    "lymphocytes": "sheets or clusters of small round cells with dark round nuclei",
    "necrosis": "pink, structureless debris with nuclear fragments, often inside a tumor nest",
    "fat": "large, empty-looking round cells with thin walls",
    "normal_breast": "ducts and lobules lined by two cell layers",
    "dcis": "atypical cells filling ducts, inside an intact basement membrane",
}


CHIP_COLORS = {"example slide": "violet",  # statuses, evidence, placeholders: the shared grammar
               "patient's own slide": "green", "hypothesis": "orange",
               "not reviewed by a pathologist": "red", "weak until validated": "orange"}


def chips(*labels: str) -> None:
    st.caption(" ".join(chip(label, CHIP_COLORS.get(label)) for label in labels))


def own_slides(index) -> list[str]:
    """The scored slide folders of a cohort index (``slides_results/cases.json``)."""
    path = RESULTS / "cases.json"
    if not path.exists():
        return []
    names = json.loads(path.read_text(encoding="utf-8")).get(str(index), [])
    return [n for n in names if (RESULTS / n / "tiles.json").exists()]


# --- review marks (the workspace's store, kind "slide") --------------------------------------

def slide_key(pf: PatientFile, slide: str, tile: str) -> str:
    return finding_key(pf, "slide", slide, tile)


def mark_box(pf: PatientFile, key: str, what: str) -> None:
    """Agree / disagree / second look and a pin for one finding."""
    reviews = st.session_state.setdefault("reviews", {})
    pins = st.session_state.setdefault("pins", {})
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    done = reviews.get(key)
    choice = st.segmented_control("Your mark", [NO_MARK, *MARKS], key=f"smark-{h}",
                                  default=done["mark"] if done else NO_MARK)
    if choice in (None, NO_MARK):
        reviews.pop(key, None)
    elif not done or done["mark"] != choice:
        reviews[key] = {"what": what, "mark": choice,
                        "by": (st.session_state.get("reviewer") or "").strip(),
                        "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    if st.checkbox("Pin", key=f"spin-{h}", value=key in pins):
        pins[key] = what
    else:
        pins.pop(key, None)
    if key in reviews:
        r = reviews[key]
        st.caption(f"{r['mark']} · {r['by'] or 'no initials'} · {r['at']}")


# --- the viewer and the Spot panel follow each other --------------------------------------

def go_to(k: str, slide: str, tile: str) -> None:
    """Point the viewer and the Spot panel at a tile ("r12c34"); a callback, so it runs before
    the page is drawn again."""
    try:
        rr, cc = (int(v) for v in tile.strip()[1:].split("c"))
    except ValueError:
        return
    st.session_state[f"{k}-spot"] = tile.strip()
    st.session_state[f"{k}-goto"] = {"slide": slide, "row": rr, "col": cc, "nonce": time.time()}


def spot_options(res: dict, meta: dict) -> list[str]:
    """The Spot panel's choices: every pointer, then the stored crops that are not one."""
    return [f"{p['pointer']} · r{p['row']}c{p['col']}" for p in res["queue"]] + [
        f"{c['why']} · r{c['row']}c{c['col']}" for c in meta.get("crops", [])
        if not any((c["row"], c["col"]) == (p["row"], p["col"]) for p in res["queue"])]


def spot_tile(k: str, res: dict, meta: dict) -> str:
    """The tile the Spot panel shows ("r12c34"): the one typed or clicked, else the one picked,
    else the first choice (pointer T1). The viewer starts its n / p from it."""
    ss = st.session_state
    pick = ss.get(f"{k}-pick") or next(iter(spot_options(res, meta)), "")
    return (ss.get(f"{k}-spot") or "").strip() or pick.split("· ")[-1]


def viewer_event(pid: str, key: str) -> None:
    """A click, n / p or "jump to" in a viewer opens its tile in that section's Spot panel; a
    browser that cannot load the tiles switches the page to its tile map."""
    ev = st.session_state.get(key) or {}
    if ev.get("failed"):
        st.session_state[f"{pid}|{ev['slide']}-viewer-failed"] = ev["failed"]
        st.session_state[f"{pid}|{ev['slide']}-pic"] = PICTURES[0]  # back to the map
    elif ev.get("tile"):
        st.session_state[f"{pid}-section"] = ev["slide"]
        st.session_state[f"{pid}|{ev['slide']}-spot"] = ev["tile"]


def viewer_unavailable(k: str, slide: str) -> str:
    """'' when the slide viewer can open this section here (its pyramid unpacked, or fetched on
    first use), else why not, in words that read as part of the page's sentence; never
    downloads."""
    why = (st.session_state.get(f"{k}-viewer-failed") or slide_viewer.unavailable(slide))
    why = why.rstrip(".")  # the browser's reason is a sentence of its own
    return why[:1].lower() + why[1:]


def show_viewer(pf: PatientFile, k: str, slide: str, res: dict, meta: dict) -> None:
    """The slide viewer (OpenSeadragon) on the section's own pyramid, fetched on first use."""
    src = slide_viewer.source(slide)
    if not isinstance(src, dict):
        st.info(f"The slide viewer is not available here: {src.rstrip('.')}. The map shows the "
                "same analysis on the section's overview image.", icon="🔬")
        return
    st.caption(
        f"The patient's own section (H&E) at {src['mpp']:.2f} µm per pixel, the scan's own level "
        "nearest 1 µm. Scroll or double-click to zoom from the whole section down to single "
        "nuclei, drag to pan; the minimap (top right) shows where you are. Colour the tiles by "
        "tissue class, certainty, quality control, zones, lymphocyte-like nuclei or risk level, "
        "and draw the front line, the arcs with their arrows, breakaway candidates with the "
        "counting field, islands, risk regions, the pointers and, zoomed in, every nucleus "
        "StarDist found on the counted tiles. Hover a tile for its scores; click it to open it "
        "in the Spot panel; n and p step through the pointers."
        + (" Only the tumor-centred window (dashed) was scored: the rest of the section is "
           "shown, not analysed." if src["window"] else ""))
    slide_viewer.show([src], key=f"{k}-viewer", goto=st.session_state.get(f"{k}-goto"),
                      on_change=lambda: viewer_event(pf.id, f"{k}-viewer"),
                      spot={"slide": slide, "tile": spot_tile(k, res, meta)})
    st.caption(f"Tiles: a Deep Zoom pyramid of {slide} (GDC open access; JPEG, cut with "
               "OpenSlide); viewer: OpenSeadragon 6.1.1. Each coloured tile is one score for "
               f"{TILE_UM:.0f} µm of tissue; classes are model inferences smoothed over 3×3 "
               "tiles, so their edges are a tile's width, not a cell's.")


# --- the patient's own slide -------------------------------------------------------------

def load_slide(folder: Path) -> dict | None:
    if not (folder / "tiles.json").exists():
        return None
    tiles = pd.read_json(folder / "tiles.json", orient="split")
    meta = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    nuc = json.loads((folder / "nuclei.json").read_text(encoding="utf-8")) \
        if (folder / "nuclei.json").exists() else {"tiles": [], "points": {}}
    if nuc.get("tiles") and nuc["tiles"].get("data"):
        summ = pd.DataFrame(nuc["tiles"]["data"], columns=nuc["tiles"]["columns"])
        tiles = tiles.merge(summ, on=["row", "col"], how="left")
    til = None
    if (folder / "til.json").exists():  # the second lymphocyte model, where it scored
        til = json.loads((folder / "til.json").read_text(encoding="utf-8"))
        scores = til.pop("tiles", {})
        if scores:
            tiles["tile_id"] = "r" + tiles["row"].astype(str) + "c" + tiles["col"].astype(str)
            tiles["p_til"] = tiles["tile_id"].map(scores)
            tiles = tiles.drop(columns="tile_id")
    return {"tiles": tiles, "meta": meta, "points": nuc.get("points", {}), "nuclei": nuc,
            "til": til,
            "thumbnail": folder / "thumbnail.jpg" if (folder / "thumbnail.jpg").exists()
            else None, "crops": folder / "crops", "folder": folder}


def frame(res: dict, classes: list[str]) -> pd.DataFrame:
    """The per-tile frame the charts and tables use, with readable columns."""
    df = res["tiles"].copy()
    df["tile"] = "r" + df["row"].astype(str) + "c" + df["col"].astype(str)
    df["class"] = df["label"].map(LABELS).fillna("")
    df["certainty"] = df["unsure"].map({True: "unsure here", False: "confident"})
    bad = df["qc"] != QC_OK
    df.loc[bad, "class"] = "excluded: " + df.loc[bad, "qc"]
    df.loc[bad, "certainty"] = "excluded"
    df["top"] = df[[f"p_{k}" for k in classes]].max(axis=1).map(lambda v: f"{v:.0%}")
    df["scores"] = df.apply(lambda r: " ".join(
        f"{LABELS[k].split()[0].lower()} {r[f'p_{k}']:.0%}" for k in classes), axis=1)
    df["zone_shown"] = df["zone"].where(~df["front"], "front line")
    df.loc[df["zone_shown"] == "", "zone_shown"] = "no tissue zone"
    df["risk"] = df["risk_level"].map({0: "none", 1: "level 1", 2: "level 2", 3: "level 3"})
    if "n_nuclei" in df:
        df["nuclei"] = df.apply(lambda r: "not counted" if pd.isna(r["n_nuclei"]) else
                                f"{int(r['n_nuclei'])} nuclei, {int(r['n_lymph'])} lymphocyte-"
                                f"like, {int(r['buds'])} breakaway cluster(s)", axis=1)
        df["immune"] = np.where(df["n_nuclei"].isna(), "not counted",
                                np.where(df["n_lymph"].fillna(0) >= 20, "many lymphocytes",
                                         np.where(df["n_lymph"].fillna(0) >= 5, "some", "few")))
    else:
        df["nuclei"], df["immune"] = "not counted", "not counted"
    if "til_lymph" in df:
        df["second model"] = np.where(df["til_lymph"].isna(), "not scored",
                                      np.where(df["til_lymph"] == 1, "lymphocytes",
                                               "not lymphocytes"))
        df.loc[df["disagree"].fillna(False).astype(bool), "second model"] += " (disagrees)"
    else:
        df["second model"] = "not scored"
    df["dist"] = df["dist_to_front_um"].map(lambda v: f"{v + 0.0:+.0f} µm from the front"
                                            if pd.notna(v) else "no front") \
        if "dist_to_front_um" in df else "no front"
    df["where"] = df["tile"] + " · " + df["zone"].replace("", "no zone") + " · " + df["dist"]
    return df


# --- the slide map (adapted from the analyzer's app/page_slide.py: map_area, handle_click,
# focus_on, reset_view, search_results) -------------------------------------------------------

def memory(k: str) -> dict:
    """What a section's map remembers between clicks."""
    store = st.session_state.setdefault("slide_map_memory", {})
    return store.setdefault(k, {"selected": None, "outline": None, "zoom": None, "zoom_rev": 0,
                                "last_click": None, "search": None, "match_on": True,
                                "goto_nonce": None})


def focus_on(k: str, loc: tuple[int, int], data: tile_map.MapData, select: bool = True) -> None:
    """Zoom the map around tile loc = (r, c) and outline it."""
    mem = memory(k)
    r, c = loc
    mem["zoom"] = tile_map.zoom_box(r, c, data)
    mem["zoom_rev"] += 1
    g = data.geom
    i = int(data.index_grid[r, c]) if 0 <= r < g["rows"] and 0 <= c < g["cols"] else -1
    if select and i >= 0:
        mem["selected"] = mem["outline"] = i


def reset_view(k: str) -> None:
    """The whole section, nothing selected."""
    mem = memory(k)
    mem["zoom"], mem["selected"], mem["outline"] = None, None, None
    mem["zoom_rev"] += 1


def files_stamp(folder: Path) -> str:
    return "-".join(str((folder / f).stat().st_mtime_ns) for f in
                    ("tiles.json", "nuclei.json", "summary.json", "til.json", "thumbnail.jpg")
                    if (folder / f).exists())


@st.cache_resource(max_entries=2, show_spinner=False)
def example_map(stamp: str):
    """The public example region's map data and scan (shared, read-only)."""
    from PIL import Image

    result = load_result(EXAMPLE)
    meta = result["meta"]
    classes = meta["head"]["classes"]
    res = analyze(result["tiles"], classes)
    thumb = Image.open(result["thumbnail"]).convert("RGB") if result["thumbnail"] else None
    data = tile_map.build(res["tiles"], classes, res["grid_shape"],
                          thumb.size if thumb else None, meta, key=f"example-{stamp}")
    return data, thumb


@st.cache_resource(max_entries=8, show_spinner=False)
def section_map(slide: str, stamp: str):
    """A scored section's map data and its scan (shared, read-only), once per version of its
    result files."""
    from PIL import Image

    got = scored(slide)
    if got is None:
        return None
    result, res, _ = got
    meta = result["meta"]
    thumb = Image.open(result["thumbnail"]).convert("RGB") if result["thumbnail"] else None
    data = tile_map.build(res["tiles"], meta["head"]["classes"], res["grid_shape"],
                          thumb.size if thumb else None, meta, key=f"{slide}-{stamp}")
    return data, thumb


def run_search(k: str, data: tile_map.MapData, res: dict | None) -> dict | None:
    """The search box's query, matched once per change: the map shows the whole section with
    every match coloured."""
    mem = memory(k)
    query = (st.session_state.get(f"{k}-search") or "").strip()
    if query != (mem.get("search") or {}).get("query", ""):
        mem["search"] = slide_search.search(data, query, res) if query else None
        mem["match_on"] = True
        mem["zoom"], mem["outline"] = None, None
        mem["zoom_rev"] += 1
    return mem.get("search")


def search_answer(found: dict | None) -> None:
    """What the search matched, under the search box."""
    if not found:
        return
    used = ", ".join(found.get("used") or []) or "nothing"
    zone = slide_search.ZONE_NAMES.get(found.get("zone"), "")
    text = (f"“{found['query']}” · matched {used}" + (f" · limited to the {zone}" if zone else "")
            + (f" · {found['message'].strip()}" if found.get("message") else ""))
    (st.caption if found.get("understood") else st.warning)(
        text + (f" The map below colours every square that matches {slide_search.MIN_SCORE:.0%} "
                "or more (model inference); Q1… mark the best spots." if found.get("values")
                is not None else ""))


def map_markers(k: str, res: dict | None, found: dict | None) -> list[dict]:
    """The pointers on the map: the search's best spots while a search is on, else the
    look-here pointers T1…Tn (the scheme the text and the Spot panel use)."""
    if found and found.get("spots"):
        color = tile_map.POINTER_COLORS["search"]
        return [{"r": s["r"], "c": s["c"], "label": s["label"], "color": color,
                 "hover": f"{s['label']}: match {s['score']:.0%}"} for s in found["spots"]]
    return [{"r": q["row"], "c": q["col"], "label": q["pointer"],
             "color": tile_map.POINTER_COLORS.get(q.get("kind"), tile_map.POINTER_COLORS["other"]),
             "hover": f"{q['pointer']} · {q['what']}"} for q in (res or {}).get("queue", [])]


def map_area(k: str, slide: str, data: tile_map.MapData, thumb, res: dict | None,
             found: dict | None, spot: bool = True) -> None:
    """The map: the class highlight and Whole section above it, the chart, a line saying what a
    square is and what was clicked, and the search's spots under it. The view buttons and the
    opacity slider are INSIDE the chart (plotly handles them in the browser, no rerun, so the
    zoom is kept). A click on a square opens it in the Spot panel below."""
    mem, ss = memory(k), st.session_state
    goto = ss.get(f"{k}-goto")  # a pointer picked elsewhere (queue, Spot panel, viewer) moves it
    if goto and goto.get("nonce") != mem["goto_nonce"] and goto.get("slide", slide) == slide:
        mem["goto_nonce"] = goto.get("nonce")
        focus_on(k, (int(goto["row"]), int(goto["col"])), data)
    row = st.container(horizontal=True, vertical_alignment="center", gap="small")
    names = {LABELS.get(c, c): c for c in data.classes}
    focus = row.pills("Highlight a class", list(names), key=f"{k}-focus",
                      help="Picks one tissue class to stand out in the Tissue view; the other "
                           "classes fade (the analyzer's clickable key).")
    if row.button("Whole section", key=f"{k}-fit", icon=":material/fit_screen:",
                  help="Shows the whole section again and clears the selected square"):
        reset_view(k)
    matching = found is not None and found.get("values") is not None and mem.get("match_on")
    if matching:   # a search is on: one view, coloured by how well each square matches it
        overlays = {"match": tile_map.overlay_png(data, "match", None, found["values"],
                                                  found["query"])}
    else:
        focus_key = names.get(focus) if focus else None
        overlays = {m: tile_map.overlay_png(data, m, focus_key if m == "tissue" else None)
                    for m in tile_map.modes(data, res)}
    markers = map_markers(k, res, found)[:MAX_MARKERS]
    shape = (data.key, tuple(overlays), focus, mem["outline"], tuple(mem["zoom"] or ()),
             mem["zoom_rev"], k, found["query"] if matching else None,
             tuple((m["r"], m["c"], m["label"]) for m in markers))

    def build():
        legends = {m: tile_map.legend_items(data, m, res) for m in overlays}
        return tile_map.figure(
            data, tile_map.scan_jpeg(thumb, data), overlays, legends,
            opacity=tile_map.MATCH_OPACITY if matching else tile_map.OPACITY,
            selected=mem["outline"], markers=markers, zoom=mem["zoom"],
            uirevision=f"{k}-{mem['zoom_rev']}", height=tile_map.height_for(data),
            res=None if matching else res)
    fig, first_hover = figure_once(shape, build)
    event = st.plotly_chart(fig, key=f"{k}-map", on_select="rerun", selection_mode="points",
                            width="stretch", config={"displayModeBar": False,
                                                     "scrollZoom": True, "doubleClick": "reset"})
    handle_click(event, k, data, first_hover)
    g = data.geom
    picked = mem.get("selected")
    where = ": its full story is in the Spot panel below" if spot else ""
    st.caption(f"One square = {g['tile_um']:.0f} µm, {round(1000 / g['tile_um'])} squares ≈ 1 mm"
               + (f" · selected {selected_line(data, picked)}{where}" if picked is not None
                  else " · click a square for its full story in the Spot panel below" if spot
                  else ""))
    if found and found.get("spots"):
        search_spots(k, data, found)


_figures: dict = {}
_fig_lock = threading.Lock()


def figure_once(shape: tuple, build):
    """The map's figure for one state of the map (section, views, highlight, selection, zoom,
    pointers): a click elsewhere on the page reruns it without rebuilding the figure (0.2–0.5 s).
    A few figures only: each holds its section's arrays."""
    with _fig_lock:
        if shape not in _figures:
            if len(_figures) >= 6:
                _figures.pop(next(iter(_figures)))
            _figures[shape] = build()
        return _figures[shape]


def selected_line(data: tile_map.MapData, i: int) -> str:
    names = [LABELS.get(c, c) for c in data.classes] + ["no class"]
    cls = (f"excluded ({data.reason[i]})" if not data.ok[i] else
           f"{names[data.label[i]].lower()} {data.score[i]:.0%} (3×3 mean)")
    zone = tile_map.ZONE_SHORT.get(data.zone[i], data.zone[i]).lower()
    return f"r{int(data.rows[i])}c{int(data.cols[i])}, {cls}, {zone}"


def handle_click(event, k: str, data: tile_map.MapData, first_hover: int) -> None:
    """A click on the map opens that square in the Spot panel (drawn later in this run)."""
    mem = memory(k)
    try:
        points = event["selection"]["points"]
    except (TypeError, KeyError):
        return
    if not points:
        return
    p = points[0]
    sig = (p.get("curve_number"), p.get("point_index"), p.get("x"), p.get("y"))
    if sig == mem["last_click"]:
        return
    mem["last_click"] = sig
    idx = tile_map.clicked_tile(data, p.get("curve_number"),
                                p.get("point_index", p.get("point_number")),
                                p.get("customdata"), first_hover)
    if idx is not None:
        mem["selected"] = int(idx)  # plotly marks the square itself; the chart isn't rebuilt
        st.session_state[f"{k}-spot"] = f"r{int(data.rows[idx])}c{int(data.cols[idx])}"


def clear_search(k: str) -> None:
    st.session_state[f"{k}-search"] = ""
    mem = memory(k)
    mem["search"], mem["zoom"], mem["outline"] = None, None, None
    mem["zoom_rev"] += 1


def search_spots(k: str, data: tile_map.MapData, found: dict) -> None:
    """One strip under the map: the best spots (click one to zoom there), the match colouring
    switch and Clear."""
    mem = memory(k)
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        for spot in found["spots"]:
            if st.button(f"{spot['label']} · {spot['score']:.0%}", key=f"{k}-q-{spot['label']}",
                         type="tertiary", help="Zooms the map to this spot and opens it in "
                                               "the Spot panel"):
                focus_on(k, (spot["r"], spot["c"]), data)
                st.session_state[f"{k}-spot"] = f"r{spot['r']}c{spot['c']}"
                st.rerun()
        if found.get("values") is not None:
            on = st.toggle("Colour by match", value=mem.get("match_on", True),
                           key=f"{k}-match", help="Off: the usual views come back, the spots "
                                                  "stay")
            if on != mem.get("match_on", True):
                mem["match_on"] = on
                st.rerun()
        st.button("Clear the search", key=f"{k}-clear", icon=":material/close:",
                  on_click=clear_search, args=(k,), help="Empties the search box")


def rose_chart(rose: list[dict]) -> alt.Chart:
    r = pd.DataFrame(rose)
    r["t1"] = np.radians((90 - r["to_deg"]) % 360)
    r["t2"] = r["t1"] + np.radians(r["to_deg"] - r["from_deg"])
    r["label"] = r.apply(lambda b: f"{int(b.from_deg)}–{int(b.to_deg)}° "
                         f"({inv.compass((b.from_deg + b.to_deg) / 2)})", axis=1)
    return (alt.Chart(r).mark_arc(innerRadius=4, stroke="white")
            .encode(theta=alt.Theta("t1:Q", scale=alt.Scale(domain=[0, 2 * math.pi])),
                    theta2="t2:Q",
                    radius=alt.Radius("push_sum:Q", scale=alt.Scale(type="sqrt", zero=True)),
                    color=alt.Color("push_mean:Q", scale=alt.Scale(scheme="reds"),
                                    title="mean push"),
                    tooltip=["label:N", "tiles:Q", "push_sum:Q", "push_mean:Q"])
            .properties(width=220, height=220))


def crop_image(result: dict, row: int, col: int):
    """The 224 px crop with nuclei dots (lymphocyte-like blue, others red), or None."""
    from PIL import Image, ImageDraw

    path = result["crops"] / f"{row}_{col}.jpg"
    if not path.exists():
        return None
    img = Image.open(path).convert("RGB")
    pts = result["points"].get(f"{row}_{col}")
    if pts:
        d = ImageDraw.Draw(img)
        k = img.width / TILE_UM  # px per µm
        for x, y, lymph in pts:
            d.ellipse([x * k - 3, y * k - 3, x * k + 3, y * k + 3],
                      outline="#2e86de" if lymph else "#c0392b", width=2)
    return img


def mixup(meta: dict, a: str, b: str) -> str | None:
    """How often the head confused two classes on its held-out tiles (its confusion matrix):
    a measured mix-up, where the analyzer named colon's by hand."""
    conf = meta.get("head", {}).get("confusion")
    if not conf or a not in conf["labels"] or b not in conf["labels"]:
        return None
    m, i, j = conf["rows_true_cols_pred"], conf["labels"].index(a), conf["labels"].index(b)
    parts = [f"{LABELS.get(x, x).lower()} read as {LABELS.get(y, y).lower()} on {m[p][q]} of "
             f"{sum(m[p])}" for x, y, p, q in ((a, b, i, j), (b, a, j, i)) if sum(m[p])]
    return ("On the head's held-out tiles: " + "; ".join(parts) + ".") if parts else None


def tile_story(t, classes: list[str], meta: dict, data: tile_map.MapData | None) -> dict:
    """Why the map gave this class, how sure it is and why, and what to check by eye (the
    analyzer's per-square explanation, adapted: muffle's smoothed class and measured mix-ups)."""
    probs = {k: float(t[f"p_{k}"]) for k in classes}
    order = sorted(probs, key=probs.get, reverse=True)
    top, second = order[0], order[1]
    shown = t["label"] if t["label"] in classes else top
    why = [f"Closest match: {LABELS[top]} ({probs[top]:.0%}); next: {LABELS[second]} "
           f"({probs[second]:.0%})."]
    if shown != top:
        why.append(f"The map shows {LABELS[shown].lower()}: the class with the highest "
                   "probability averaged over the 3×3 squares around it.")
    how = [("high" if probs[top] >= 0.9 else "low" if probs[top] < 0.5 else "moderate")
           + f" top score ({probs[top]:.0%})"]
    i = int(data.index_grid[int(t["row"]), int(t["col"])]) if data is not None else -1
    if i >= 0:
        share = float(data.share[i])
        why.append(f"{share:.0%} of the squares around it are also {LABELS[shown].lower()}.")
        how.append("neighbours match" if share >= 0.5 else
                   "neighbours differ (it may sit on a border)")
    looks = LOOKS_LIKE.get(shown)
    advice = (f"Check by eye: {LABELS[top].lower()} ({LOOKS_LIKE.get(top, '')}) or "
              f"{LABELS[second].lower()} ({LOOKS_LIKE.get(second, '')})?"
              if t["unsure"] else None)
    return {"why": why, "how": how, "looks": looks, "advice": advice, "shown": shown,
            "mixup": mixup(meta, top, second) if t["unsure"] or shown != top else None}


SPOT_PICTURES = 260  # px: the Spot panel's crop and neighbourhood pictures
SPOT_WORDS = 520  # px: beside the pictures at 1280 px (as wide as the old 2/3 column), under
# them at 800 px (QA R3-11)


def zoom_to_cells(k: str, slide: str, r: int, c: int) -> None:
    """Switch the picture to the slide viewer at this tile (a callback)."""
    st.session_state[f"{k}-pic"] = PICTURES[1]
    st.session_state[f"{k}-goto"] = {"slide": slide, "row": r, "col": c, "nonce": time.time()}


def spot_panel(pf: PatientFile, slide: str, result: dict, df: pd.DataFrame, res: dict,
               classes: list[str], r: int, c: int, meta: dict,
               data: tile_map.MapData | None = None, thumb=None, k: str = "",
               can_zoom: bool = False) -> None:
    rows = df[(df["row"] == r) & (df["col"] == c)]
    if rows.empty:
        st.warning("No tile at that position.")
        return
    t = rows.iloc[0]
    # a row that wraps: at 800 px the pictures and "Zoom to the cells" go above the words, never
    # a third-width column that cut the label and let the pictures cover the words (QA R3-11)
    with st.container(horizontal=True, gap="medium", key=f"{k}-spot-row"):
        left = st.container(width=SPOT_PICTURES)
        right = st.container(width=SPOT_WORDS)
    i = int(data.index_grid[r, c]) if data is not None else -1
    with left:
        img = crop_image(result, r, c)
        if img is not None:
            st.image(img, caption=f"{t['tile']}: 112 µm, the patient's own section", width=260,
                     alt=f"H&E crop of tile {t['tile']}, 112 µm across, with the nuclei found "
                         "marked: lymphocyte-like in blue, others in red")
        else:
            st.caption("No crop stored for this tile (crops are kept for the queue, the "
                       "counting field, the cards and the roughest front tiles).")
        near = tile_map.neighborhood(thumb, data, i) if i >= 0 else None
        if near is not None:
            st.image(near, caption="Where it sits: the scan around it, the square outlined",
                     width=260, alt=f"The scan around tile {t['tile']}, the tile outlined in "
                                    "blue")
        if can_zoom:
            st.button("Zoom to the cells", key=f"{k}-zoom-{r}-{c}", icon=":material/zoom_in:",
                      on_click=zoom_to_cells, args=(k, slide, r, c), width="stretch",
                      help="Opens the slide viewer at this tile, down to single nuclei")
    with right:
        step, mpp = meta.get("step_base_px", 448), meta.get("base_mpp", 0.25)
        r0, c0 = meta.get("scored", {}).get("origin_tile", [0, 0])
        st.markdown(f"**{t['tile']}** · {(c0 + c) * step * mpp / 1000:.1f} mm from the left, "
                    f"{(r0 + r) * step * mpp / 1000:.1f} mm from the top of the slide · "
                    f"{t['zone'] or 'no zone'} · {t['dist']}"
                    + (" · on the front" if t["front"] else "")
                    + (" · finger" if t.get("finger") else "")
                    + (" · in the main tumor" if t.get("main_tumor") else ""))
        st.markdown(f"**Class** {t['class']} ({t['top']}) · **certainty** {t['certainty']}"
                    + (f": top probability below {CUTOFFS['unsure_below'][0]} (placeholder "
                       "cutoff)" if t["unsure"] else "")
                    + f" · {INFERENCE}")
        if t["qc"] == QC_OK:
            story = tile_story(t, classes, meta, data)
            st.markdown(f"**Why** {' '.join(story['why'])} **How sure:** "
                        + "; ".join(story["how"]) + "."
                        + (f" {LABELS[story['shown']]} typically looks like {story['looks']} "
                           "(general histology)." if story["looks"] else ""))
            if story["advice"]:
                st.warning(story["advice"] + (f" {story['mixup']}" if story["mixup"] else ""))
            elif story["mixup"]:
                st.caption(story["mixup"])
        if pd.notna(t.get("p_til")):
            head_l = t["label"] == "lymphocytes"
            til_l = bool(t.get("til_lymph") == 1)
            st.markdown(f"**Second model** (lymphocytes, {INFERENCE}): {t['p_til']:.0%} · "
                        + ("agrees with the head" if head_l == til_l else
                           "disagrees with the head: a queue item, never a verdict"))
        scores = pd.DataFrame({"class": [LABELS[k] for k in classes],
                               "score": [100 * float(t[f"p_{k}"]) for k in classes]})
        st.dataframe(scores.sort_values("score", ascending=False), hide_index=True,
                     width="stretch", column_config={"score": st.column_config.ProgressColumn(
                         "Score", min_value=0, max_value=100, format="%.0f%%",
                         help="The head's probability for each class on this tile (raw, not "
                              "smoothed)")})
        counted = "n_nuclei" in t and pd.notna(t.get("n_nuclei"))
        cv_txt = ("n/a" if not counted or pd.isna(t.get("nuc_area_cv"))
                  else f"{t['nuc_area_cv']:.2f}")
        st.markdown(f"**Nuclei** {t['nuclei']}"
                    + (f"; {int(t['n_lymph_near_tumor'])} lymphocyte-like within 50 µm of a "
                       f"tumor candidate; nuclear-area variation {cv_txt} (a proxy, never a "
                       "grade)" if counted else "")
                    + f" · **risk points** {t['risk_points']:.0f} ({t['risk']}, placeholder)")
        checks = []
        if t["front"]:
            checks.append("the edge at 20×: single cells or small nests beyond the line")
        if t.get("buds", 0) and t["buds"] > 0:
            checks.append("each breakaway cluster: tumor cells, or stromal / inflammatory nuclei "
                          "cut by the tile border?")
        if t["unsure"]:
            checks.append("what tissue this is: the head could not decide")
        if t["label"] == "necrosis":
            checks.append("necrosis against a tumor nest, or debris / secretion?")
        if t["label"] == "lymphocytes":
            checks.append("stromal versus intratumoral lymphocytes (TILs Working Group)")
        if t["qc"] != QC_OK:
            checks.append(f"excluded for {t['qc']}: judge the tissue by eye")
        st.markdown("**What to check by eye:** " + ("; ".join(checks) if checks else
                                                     "nothing specific flagged here"))
        hs = res["hotspot"]
        if hs and (r, c) == (hs["row"], hs["col"]):  # one mark per finding on the page
            st.caption("This tile is the counting field's centre: your mark for it is with the "
                       "breakaway candidates above.")
        else:
            mark_box(pf, slide_key(pf, slide, t["tile"]),
                     f"Slide {slide}, tile {t['tile']}: {t['class']} ({t['zone'] or 'no zone'})")


def coverage_line(zones: dict) -> str:
    """How much of each zone the nuclei and the second lymphocyte model actually cover: counts
    and the TIL comparison hold only for those tiles."""
    def part(key: str) -> str:
        return "; ".join(f"{z} {v.get(key, 0)} of {v['tiles']} usable tiles"
                         + (f" ({v.get(key, 0) / v['tiles']:.0%})" if v["tiles"] else "")
                         for z, v in zones.items() if z != "core")
    return (f"Coverage: nuclei counted on {part('nuclei_tiles')}; the second model scored "
            f"{part('til_scored_tiles')}.")


def head_card(meta: dict, classes: list[str]) -> None:
    head, enc = meta.get("head", {}), meta.get("encoder", {})
    st.markdown(
        f"**Tissue head.** {inv.MODEL_CARD['tissue head']}. **Training data:** "
        f"{head.get('training_data', '?')}, labels from BCSS (Amgad et al. 2019, CC0). "
        f"**Held out:** {head.get('held_out', '?')}. **Accuracy:** "
        f"{head.get('accuracy', float('nan')):.1%} (balanced "
        f"{head.get('balanced_accuracy', float('nan')):.1%}); below the unsure cutoff the head "
        f"was right on {head.get('accuracy_below_cutoff', float('nan')):.0%} of tiles, at or "
        f"above it {head.get('accuracy_at_or_above_cutoff', float('nan')):.0%}."
        + (" **This patient's slide was among the head's training or held-out slides.**"
           if head.get("this_patient_in_training") else
           " This patient is not among the head's training or held-out slides."))
    per = head.get("per_class", {})
    if per:
        st.dataframe(pd.DataFrame([{"class": LABELS.get(k, k), "training tiles": v["n_train"],
                                    "held-out tiles": v["n_test"],
                                    "recall": f"{v['recall']:.0%}" if v["recall"] is not None
                                    else "no held-out tiles"} for k, v in per.items()]),
                     hide_index=True, width="stretch")
    not_learned = head.get("not_learned", {})
    if not_learned:
        st.markdown("**Not in the head:** " + "; ".join(
            f"{LABELS.get(k, k).lower()} ({why})" for k, why in not_learned.items())
            + ". Tiles of these tissues get one of the classes above: a known failure.")
    conf = head.get("confusion")
    if conf:
        with st.expander("Confusion matrix on the held-out tiles (rows true, columns predicted)"):
            labels = [LABELS.get(k, k) for k in conf["labels"]]
            st.dataframe(pd.DataFrame(conf["rows_true_cols_pred"], index=labels, columns=labels),
                         width="stretch")
    st.caption(f"Encoder: {enc.get('name', '?')}, {enc.get('license', '?')}, "
               f"{enc.get('access', '?')}; {enc.get('tiles_per_s_cpu', '?')} tiles/s on the "
               f"computer that scored the sections ({enc.get('threads', '?')} processor threads, "
               "shared with other work). The "
               "encoder's own benchmarks are not evidence for this task.")


def cannot_see(page: Page, cutoffs: dict | None = None) -> None:
    with page.cannot_see():
        st.dataframe(pd.DataFrame([{"not visible here": what, "why": why, "what can": how}
                                   for what, why, how in inv.CANNOT_SEE]), hide_index=True,
                     width="stretch")
        both = {**CUTOFFS, **(cutoffs or {})}
        n = sum(1 for v in both.values() if v[1] == PLACEHOLDER)
        with st.expander(f"Every cutoff and its source ({n} of {len(both)} placeholders)"):
            st.dataframe(pd.DataFrame([{"cutoff": k, "value": v, "source": tag, "note": note}
                                       for k, (v, tag, note) in both.items()]),
                         hide_index=True, width="stretch")
            st.caption(f"{n} of {len(both)} cutoffs are placeholders. Evidence types: tile "
                       f"positions, crops and the thumbnail are {OBSERVED}; every class, "
                       f"nucleus, region, front, zone and point is {INFERENCE}; the direction of "
                       "invasion is a hypothesis about this section.")


@st.cache_data(max_entries=16, show_spinner=False)
def section_numbers(slide: str) -> dict | None:
    """A scored section's stored numbers (its summary.json), for the comparison of sections:
    the other sections are read, not analysed again."""
    path = RESULTS / slide / "summary.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("numbers", {})


@st.cache_data(max_entries=8, show_spinner="Reading the scored section…")
def scored(slide: str) -> tuple[dict, dict, pd.DataFrame] | None:
    """A scored section, its analysis and its tile frame: they depend on the slide only, so
    they are computed once per process, not on every click in the workbench."""
    result = load_slide(RESULTS / slide)
    if result is None:
        return None
    classes = result["meta"]["head"]["classes"]
    til = result.get("til")
    res = inv.analyze_slide(result["tiles"], classes, til_cutoff=til["cutoff"] if til else None,
                            til_calibrated=bool(til and "calibrated" in til.get(
                                "cutoff_source", "")))
    return result, res, frame(res, classes)


def look_items(pf: PatientFile, slide: str, version: int | None, res: dict) -> list[dict]:
    """The section's look-here items: the ones the report's attention queue carries
    (``muffle.workbench.slides.queue``), or, for a section scored before those were stored,
    the page's own pointers in the same shape."""
    items = [x for x in queue_items("slides", pf, version, lambda: slide_queue(pf, version))
             if x["focus"]["slide"] == slide]
    if items:
        return items
    return [{"pointer": q["pointer"], "what": q["what"], "why": f"{q['why']}; check by eye: "
             f"{q['check']}", "evidence": q["evidence"], "trust": "weak", "consequence": 1,
             "month": None, "key": slide_key(pf, slide, f"r{q['row']}c{q['col']}"),
             "focus": {"slide": slide, "pointer": q["pointer"],
                       "tile": f"r{q['row']}c{q['col']}"}} for q in res["queue"]]


def render_slide(page: Page, pf: PatientFile, slide: str, version: int | None,
                 compare=None) -> None:
    """One scored section in the page skeleton; ``compare`` draws the details that compare it
    with the file's other sections."""
    if (got := scored(slide)) is None:
        return
    result, res, df = got
    meta = result["meta"]
    classes = meta["head"]["classes"]
    s, n = res["summary"], res["numbers"]
    sc, nuc, til = meta.get("scored", {}), meta.get("nuclei", {}), result.get("til")
    k = f"{pf.id}|{slide}"
    data, thumb = section_map(slide, files_stamp(RESULTS / slide))
    st.caption(
        f"Source: {meta.get('source', '')} · slide {slide} · scored: {sc.get('mode', '?')}, "
        f"{sc.get('scored_tiles', '?')} of {sc.get('tissue_tiles_total', '?')} tissue tiles of "
        f"{TILE_UM:.0f} µm ({sc.get('why', '')}) · encoder {meta.get('encoder', {}).get('name')} "
        f"· head: {meta.get('head', {}).get('kind')} · nuclei: {nuc.get('model') or 'not run'} on "
        f"{nuc.get('tiles', 0)} tiles · method version {meta.get('method_version', '0.2')} · "
        f"status: {meta.get('status', 'implemented')}.")
    for note in meta.get("known_failures", []):  # a reviewer's note on this section's map
        st.warning(f"Known failure on this section: {note}")
    if sc.get("skipped_tiles"):
        st.warning(f"{sc['skipped_tiles']} tissue tiles outside the scored window were not "
                   "scored (the time for scoring was limited): tumor outside the window is not "
                   "in this map. The whole slide is in the pathology report.")
    reviews = st.session_state.setdefault("reviews", {})

    # --- overview, look here, search ---------------------------------------------------------
    frac = s["tissue_fractions"]
    top3 = sorted(frac.items(), key=lambda kv: -kv[1])[:3]
    infil = [a for a in res["arcs"] if a["pattern"] == "infiltrative"]
    main_dir = inv.compass(inv._circular_mean(
        np.array([a["direction_deg"] for a in infil]), np.array([a["push"] for a in infil]))) \
        if infil else None
    hs = res["hotspot"]
    text = (
        f"**{INFERENCE}.** Of {s['usable_tiles']} usable tiles the map reads "
        + ", ".join(f"{LABELS[k].lower()} {v:.0%}" for k, v in top3)
        + f". The main tumor covers {s['main_tumor_mm2']} mm² with a {s['front_length_mm']} mm "
        f"front cut into {n['arcs']} arcs, {n['infiltrative_arcs']} of them infiltrative"
        + (f", invading mostly {main_dir}" if main_dir else "")
        + f"; the front mostly faces {LABELS.get(n['faces_top'], n['faces_top']).lower()}. "
        f"{n['islands']} satellite island(s). Immune pattern: {n['immune_pattern']} "
        f"(placeholder cutoffs); tumor–stroma ratio {n['tsr']}. "
        + (f"Breakaway candidates: {hs['buds_in_field']} cluster(s) in the 0.785 mm² counting "
           f"field (weak until validated; {hs['coverage']:.0%} of the field counted). "
           if hs else "No breakaway candidate found in the counted tiles. ")
        + f"{s['unsure_share']:.0%} of the tissue is unsure. "
        + ("Excluded by quality control: " + ", ".join(f"{v} {k}" for k, v in
                                                       s["excluded"].items()) + "."
           if s["excluded"] else "No tile was excluded by quality control.")
    )
    with page.overview():
        st.markdown(text)
        st.markdown("**Hypothesis.** The arrows show where the tumor is invading in this "
                    "section: a 2D snapshot, not a forecast of where it will go.")
        row = st.container(horizontal=True)  # wraps on a narrow screen instead of cutting values
        row.metric("Tumor area (map)", f"{s['tumor_mm2']} mm²", width="content",
                   help="Tiles whose smoothed class is invasive carcinoma, at 112 µm per tile "
                        "(model inference).")
        row.metric("Front length", f"{s['front_length_mm']} mm", width="content",
                   help="The tumor's border on the tile grid, in mm of tissue (model inference).")
        row.metric("Infiltrative arcs", f"{n['infiltrative_arcs']} / {n['arcs']}",
                   width="content", help="Arcs of the front whose roughness passes the "
                                         "infiltrative cutoff (a placeholder).")
        row.metric("Breakaway in field", "—" if not hs else str(hs["buds_in_field"]),
                   help="clusters of up to 4 tumor-candidate nuclei in the 0.785 mm² field; "
                        "weak until validated", width="content")
        row.metric("Unsure share", f"{s['unsure_share']:.0%}", width="content",
                   help=f"Share of tiles whose top class probability is under "
                        f"{CUTOFFS['unsure_below'][0]} (a placeholder cutoff).")
        page.look_here(look_items(pf, slide, version, res),
                       land=lambda focus: land(pf, page.version, focus),
                       more="Details › Every look-here pointer")
        st.text_input("Search inside the slide, in plain words", key=f"{k}-search",
                      placeholder="lymphocytes at the border · budding · necrosis in the core · "
                                  "unsure · satellite · direction · T2",
                      help="Known words: a tissue class, a flag, a place (border, core, "
                           "around), the direction of invasion or a pointer. The map colours "
                           "every match; Q1… mark the best spots.")
        found = run_search(k, data, res)
        search_answer(found)

    # --- the picture: the slide map, or the slide viewer down to single cells ----------------
    why_not = viewer_unavailable(k, slide)
    with page.picture("Slide map", caption=MAP_CAPTION):
        shown = PICTURES[0]
        if not why_not:
            # seeded, not a default=: "Zoom to the cells" sets it from a callback, and a widget
            # with a default whose state is set that way prints Streamlit's duplicate warning
            st.session_state.setdefault(f"{k}-pic", PICTURES[0])
            shown = st.segmented_control(
                "Picture", PICTURES, key=f"{k}-pic", required=True,
                label_visibility="collapsed",
                help="Map: the whole section with the analysis on top. Slide viewer: the "
                     "section's own pyramid, from the whole section down to single nuclei "
                     "(the first opening fetches its tiles).") or PICTURES[0]
        if shown == PICTURES[1]:
            show_viewer(pf, k, slide, res, meta)
        else:
            map_area(k, slide, data, thumb, res, found)
            if why_not:
                st.caption(f"Zooming to single cells needs the slide viewer, which is not "
                           f"available here: {why_not}.")
    if meta.get("scored", {}).get("window_side_tiles"):
        st.caption("Only the tumor-centred window was scored: the map shows that window; the "
                   "slide viewer shows the whole section with the window dashed.")

    # --- details ----------------------------------------------------------------------------
    with page.details("Direction of invasion: arcs of the front", len(res["arcs"])):
        chips("hypothesis", "placeholder cutoffs")
        if bool(res["rose"]) and res["normals"] is not None and len(res["normals"]) > 0:
            st.altair_chart(rose_chart(res["rose"]), width="content")
            st.caption("Rose of the front normals, push-weighted: the direction the front "
                       "points and how much tumor probability lies beyond it. A hypothesis "
                       "about this section; the map's Zones view draws the arcs as arrows.")
        st.caption(f"The front is cut into {CUTOFFS_INV['sectors'][0]} arcs around the tumor's "
                   "centroid. Direction = push-weighted mean outward normal; push = mean "
                   "P(invasive) over 3 tiles beyond the front (0 sharp, near 0.5 fading into the "
                   "tissue); roughness = share of the arc's tiles in fingers (opening of radius 2 "
                   f"tiles); infiltrative at {CUTOFFS_INV['infiltrative_arc'][0]:.0%} "
                   "(placeholder). Faces = classes of the tissue touching the arc.")
        if res["arcs"]:
            a = pd.DataFrame(res["arcs"])
            a["direction"] = a["direction_deg"].map(lambda d: f"{inv.compass(d)} ({d:.0f}°)")
            a["faces"] = a["faces"].map(lambda f: ", ".join(
                f"{LABELS.get(c, c).lower()} {v:.0%}" for c, v in list(f.items())[:3]))
            st.dataframe(a[["arc", "from_deg", "to_deg", "length_mm", "direction", "push",
                            "roughness", "pattern", "faces"]], hide_index=True, width="stretch")
            st.caption(f"Fingers found: {res['fingers']['n']}"
                       + ("" if res["fingers"]["judged"] else " (tumor too small to judge)")
                       + ".")
        else:
            st.caption("No tumor front in the map.")

    cells = (f"{hs['buds_in_field']} breakaway in the field" if hs else
             f"nuclei on {nuc.get('tiles', 0)} tiles")
    with page.details("Cells: breakaway candidates, lymphocytes, stroma and necrosis", cells):
        chips("weak until validated", "placeholder cutoffs")
        st.caption(f"{inv.MODEL_CARD['nuclei'][0].upper() + inv.MODEL_CARD['nuclei'][1:]}. "
                   f"Counted on {nuc.get('tiles', 0)} tiles ({nuc.get('nuclei', 0)} nuclei; "
                   f"{nuc.get('s_per_tile', '?')} s per tile), front tiles first, then the band "
                   "outside, then the rest of the front band and the peritumoral zone, as far as "
                   "the time for counting allowed. Every flag below is weak until validated.")
        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**Breakaway (budding) candidates**")
            if hs:
                st.markdown(f"Counting field at tile r{hs['row']}c{hs['col']} (0.785 mm², the "
                            f"ITBCC 20× field): **{hs['buds_in_field']}** cluster(s) of ≤ 4 "
                            f"tumor-candidate nuclei outside the main tumor; {hs['coverage']:.0%} "
                            "of the field was counted. Budding grades (Bd1–3) are defined for "
                            "colorectal cancer and are not applied here. A cluster is a "
                            "tumor-nucleus candidate by its tile's class, not by cell "
                            "morphology.")
                st.number_input("Buds you count in this field at 20× (your count, kept with the "
                                "export)", min_value=0, max_value=200, step=1,
                                key=f"{k}-budcount")
                mark_box(pf, slide_key(pf, slide, f"r{hs['row']}c{hs['col']}"),
                         f"Slide {slide}: counting field, {hs['buds_in_field']} breakaway "
                         "candidate(s)")
            else:
                st.markdown("No breakaway candidate in the counted tiles" + (
                    "" if nuc.get("tiles") else " (nuclei were not counted)") + ".")
        with g2:
            st.markdown("**Stromal lymphocytes by zone** (International TILs Working Group "
                        "zones; a count proxy, not the WG's area percentage)")
            im = res["immune"]
            # numeric columns with NaN where a zone has nothing, so no mixed dtype reaches Arrow
            rows = [{"zone": z, "tiles": v["tiles"],
                     "lymphocyte-class tiles": v["lymph_tile_share"],
                     "lymphocyte tiles (second model)": v.get("til_lymph_share"),
                     "counted stroma tiles": v.get("counted_tiles", 0),
                     "lymphocyte-like nuclei / mm²": v.get("lymph_nuclei_per_mm2"),
                     "within 50 µm of tumor": v.get("tumor_contacting_share")}
                    for z, v in im["zones"].items()]
            zones = pd.DataFrame(rows)
            for col in ("lymphocyte-class tiles", "lymphocyte tiles (second model)",
                        "lymphocyte-like nuclei / mm²", "within 50 µm of tumor"):
                zones[col] = pd.to_numeric(zones[col], errors="coerce")
            st.dataframe(zones, hide_index=True, width="stretch", column_config={
                "lymphocyte-class tiles": st.column_config.NumberColumn(format="percent"),
                "lymphocyte tiles (second model)": st.column_config.NumberColumn(
                    format="percent"),
                "lymphocyte-like nuclei / mm²": st.column_config.NumberColumn(format="%d"),
                "within 50 µm of tumor": st.column_config.NumberColumn(format="percent")})
            st.caption("An empty cell means the zone has no tiles, no counted stroma tiles or no "
                       "tile scored by the second model. " + coverage_line(im["zones"]))
            d = res["til"]
            if til and d["scored"]:
                ho = til.get("held_out", {})
                at = ho.get("at_cutoff", {})
                st.markdown(f"**Second opinion ({INFERENCE}).** {inv.TIL_SECOND}: scored "
                            f"{d['scored']} front-band and peritumoral tiles; the head and it "
                            f"disagree on {d['disagree']} ({d['share']:.0%}; kappa {d['kappa']}; "
                            f"{d['head_only']} head only, {d['til_only']} second model only). "
                            f"Cutoff {d['cutoff']}: {til.get('cutoff_source', 'placeholder')}. "
                            f"Held out on the head's {len(ho.get('slides', []))} test slides "
                            f"({ho.get('tiles', '?')} tiles): AUROC "
                            f"{ho.get('auroc', float('nan'))}, recall "
                            f"{at.get('recall_lymphocytes', float('nan')):.0%}, specificity "
                            f"{at.get('specificity', float('nan')):.0%}. The map's Flags view "
                            "marks the tiles where they disagree (orange diamonds); the "
                            "densest one is in the queue.")
            elif til is None:
                st.caption("No second lymphocyte model has scored this section.")
            else:
                st.caption("The second lymphocyte model scored no tile here: the map has no "
                           "front band or peritumoral zone to score.")
            st.markdown(f"Pattern: **{im['pattern']}** ({im['status']}).")
        row = st.container(horizontal=True)  # wraps on a narrow screen instead of cutting values
        tsr, nec = res["tsr"], res["necrosis"]
        row.metric("Tumor–stroma ratio", tsr["verdict"], width="content",
                   help=f"stroma {tsr['stroma_share']:.0%} of tumor-plus-stroma tiles in the "
                        f"tumor and its front band; stroma-high above 50% (literature, "
                        "colorectal)" if tsr["stroma_share"] is not None else "not assessed")
        n_nec = nec["touching_tumor_tiles"]
        row.metric("Necrosis touching tumor", f"{n_nec} tile{'' if n_nec == 1 else 's'}",
                   width="content",
                   help=f"{nec['necrosis_mm2']} mm² of necrosis-class tiles, "
                        f"{nec['share_touching'] or 0:.0%} touching tumor")
        cv = df["nuc_area_cv"].dropna() if "nuc_area_cv" in df else pd.Series(dtype=float)
        row.metric("Nuclear-area variation", f"{cv.median():.2f}" if len(cv) else "—",
                   width="content",
                   help="median coefficient of variation of non-lymphocyte nuclear area per "
                        "counted tile: a proxy only, never a grade")

    with page.details("Satellite islands", len(res["islands"])):
        if res["islands"]:
            isl = pd.DataFrame(res["islands"])
            isl["tissue between"] = isl["between_shares"].map(lambda f: ", ".join(
                f"{LABELS.get(c, c).lower()} {v:.0%}" for c, v in f.items()) or "touching")
            st.dataframe(isl[["island", "area_mm2", "distance_um", "tissue between"]],
                         hide_index=True, width="stretch")
            st.caption("Geometry on the tile classes. An island may be a satellite, a "
                       "tangential cut of the same tumor, or in-situ disease (DCIS is not a "
                       "class of the head).")
        else:
            st.caption("No separate tumor piece in the map.")

    cards = res["risk"]["cards"]
    with page.details("Risk map: points within 1 mm", f"{len(cards)} at level 2 or more"):
        chips("placeholder cutoffs")
        r1, r2 = st.columns([1, 2])
        with r1:
            st.dataframe(pd.DataFrame(res["risk"]["table"]), hide_index=True, width="stretch")
            st.caption(f"Level 2 at {CUTOFFS_INV['risk_level_2'][0]} points, level 3 at "
                       f"{CUTOFFS_INV['risk_level_3'][0]}; every value a placeholder, not an "
                       "outcome model. The map's Risk view colours the levels.")
        with r2:
            if cards:
                cols = st.columns(min(len(cards), 3))
                for i, c in enumerate(cards[:6]):
                    with cols[i % len(cols)]:
                        st.markdown(f"**{c['card']} · level {c['level']}** ({c['points']} "
                                    f"points, {c['mm2']} mm²)  \n" + ", ".join(c["features"]))
                        st.button(f"Open {c['card']} in the Spot panel", key=f"{k}-card-{i}",
                                  on_click=go_to, args=(k, slide, f"r{c['row']}c{c['col']}"))
            else:
                st.caption("No region reaches level 2.")

    excluded = df[df["qc"] != QC_OK]
    with page.details("Quality control", f"{len(excluded)} of {s['tiles']} tiles excluded"):
        chips("placeholder cutoffs")
        st.caption("Glass, pen ink and blur are checked per tile from texture and colour "
                   "measures; the cutoffs were set by eye on colon slides and not re-checked on "
                   "breast: placeholders. Blood, folds and stain variation are not checked "
                   "(planned). The map's Quality view shows where.")
        nov = meta.get("novelty")
        if nov:
            st.caption(f"Unlike training tissue, not scored: the tile's embedding is farther "
                       f"than {nov['cutoff']} (mean cosine distance to its {nov['k']} nearest) "
                       f"from all {nov['reference_tiles']} tiles the head was trained on; "
                       f"{nov['cutoff_source']}; it flags {nov['held_out_flagged']:.1%} of the "
                       f"{nov['held_out_tiles']} held-out tiles. Tissue outside the head's five "
                       "classes (muscle, crushed margins) would otherwise get one of them.")
        st.markdown(f"{len(excluded)} of {s['tiles']} tiles excluded"
                    + (": " + ", ".join(f"{v} {k}" for k, v in s["excluded"].items())
                       if s["excluded"] else "") + ".")

    with page.details("Every look-here pointer", len(res["queue"])):
        st.caption("Pointers T1…Tn, shared by the text, the map and the Spot panel, with why "
                   "each is there and what to check by eye.")
        if res["queue"]:
            q = pd.DataFrame(res["queue"])
            q["review"] = [reviews.get(slide_key(pf, slide, f"r{p['row']}c{p['col']}"), {})
                           .get("mark", "") for p in res["queue"]]
            st.dataframe(q[["pointer", "review", "what", "why", "check", "evidence", "status"]],
                         hide_index=True, width="stretch")
        else:
            st.caption("Nothing in the queue: no tumor front, island or counted candidate.")
    notes = (st.session_state.get(f"{k}-notes") or "").strip()
    with page.details("Your notes on this section",
                      f"{len(notes.split())} words" if notes else "empty"):
        st.text_area("Your notes on this section", key=f"{k}-notes", height=150,
                     placeholder="Observations, questions for the sign-out, what to look at under "
                                 "the microscope…",
                     help="Kept for this session with your marks and added to the slide report "
                          "(Export, below); not sent anywhere.")
    if compare is not None:
        compare(page)

    # --- Spot panel -------------------------------------------------------------------------
    with page.spot("The full story of one tile: pick a pointer or a stored crop, type a tile, or "
                   "click one in the map or the viewer."):
        options = spot_options(res, meta)
        s1, s2 = st.columns([2, 1])
        pick = s1.selectbox("A pointer or a stored crop", options, key=f"{k}-pick",
                            on_change=lambda: go_to(k, slide, (st.session_state[f"{k}-pick"]
                                                               or "").split("· ")[-1]))
        typed = s2.text_input("or a tile (r12c34), or click one in the map", key=f"{k}-spot",
                              placeholder="r12c34",
                              on_change=lambda: go_to(k, slide, st.session_state[f"{k}-spot"])
                              ).strip()
        target = typed or (pick.split("· ")[-1] if pick else "")
        try:
            rr, cc = target[1:].split("c")
            rr, cc = int(rr), int(cc)
        except (ValueError, IndexError):
            st.caption("Pick a pointer or type a tile such as r12c34.")
        else:
            spot_panel(pf, slide, result, df, res, classes, rr, cc, meta, data, thumb, k,
                       can_zoom=not why_not)

    # --- model and validation card, limits, export -------------------------------------------
    with page.card():
        chips("not reviewed by a pathologist")
        head_card(meta, classes)
        st.markdown(f"**Nuclei.** {inv.MODEL_CARD['nuclei']}. **Geometry.** "
                    f"{inv.MODEL_CARD['geometry']}. **Review.** {inv.MODEL_CARD['review']}.")
        if til:
            st.markdown(f"**Second lymphocyte model.** {inv.TIL_SECOND}; normalization "
                        f"{til.get('model', {}).get('normalization', '?')}; "
                        f"{til.get('s_per_tile', '?')} s per tile on {til.get('threads', '?')} "
                        f"processor threads ({til.get('uptime', '')}). "
                        "Its disagreement with the head is a queue item, never a verdict.")
        tm = meta.get("timings", {})
        st.caption("Timings on the computer that scored this section, shared with other work: "
                   + ", ".join(f"{k.replace('_s', '')} {v} s" for k, v in tm.items()
                               if k.endswith("_s"))
                   + f"; {tm.get('uptime_at_start', '')} at the start, "
                   f"{tm.get('uptime_at_end', '')} at the end.")
        st.markdown("**Known failures:**\n" + "\n".join(f"- {f}" for f in inv.KNOWN_FAILURES))
    cannot_see(page, CUTOFFS_INV)

    with page.export():
        mine = {kk: v for kk, v in reviews.items() if kk.startswith(f"{pf.id}|slide|{slide}|")}
        export = {"patient": pf.id, "slide": slide,
                  "summary": {kk: v for kk, v in meta.items() if kk != "crops"},
                  "second_lymphocyte_model": {**(til or {}), "disagreement": {
                      kk: v for kk, v in res["til"].items() if kk != "rows"}} if til else None,
                  "your_bud_count": st.session_state.get(f"{k}-budcount"),
                  "your_notes": notes or None,
                  "review_marks": mine, "pins": {kk: v for kk, v in
                                                 st.session_state.get("pins", {}).items()
                                                 if kk.startswith(f"{pf.id}|slide|{slide}|")}}
        marks = {}
        for kk, v in mine.items():  # finding keys end with the tile: "...|slide|<slide>|r3c4"
            try:
                rr, cc = (int(x) for x in kk.rsplit("|", 1)[-1][1:].split("c"))
            except ValueError:
                continue
            marks[(rr, cc)] = v

        def report() -> str:
            return slide_export.report_markdown(
                pf.id, slide, meta, res, marks=marks, notes=notes,
                bud_count=st.session_state.get(f"{k}-budcount"), cutoffs=CUTOFFS_INV,
                known_failures=inv.KNOWN_FAILURES, overview=text)

        e = st.container(horizontal=True, gap="small")  # labels whole, wraps
        e.download_button("Download the slide report (Markdown)", report,
                          file_name=f"{slide}_report.md", mime="text/markdown", key=f"{k}-md",
                          on_click="ignore", icon=":material/description:",
                          help="The section's report, built when you click: what was scored, "
                               "the tissue mix, the look-here pointers with your marks, your "
                               "notes, the findings with their evidence labels, every cutoff "
                               "and its source, the known failures")
        e.download_button("Download the findings (JSON)", json.dumps(export, indent=1,
                                                                      default=str),
                          file_name=f"{slide}_slide.json", mime="application/json",
                          key=f"{k}-json", help="Everything the section's summary holds, with "
                                                "your marks, pins, notes and bud count")
        cols = ["tile", "row", "col", "class", "top", "certainty", "qc", "zone", "dist", "front",
                "finger", "risk_points", "risk_level", "nuclei"]
        e.download_button("Download the tiles (CSV)", df[cols].to_csv(index=False),
                          file_name=f"{slide}_tiles.csv", mime="text/csv", key=f"{k}-csv",
                          help="One row per 112 µm square: class, certainty, quality, zone, "
                               "risk points, nuclei")
        map_export(e, k, slide, data, thumb, res, meta)


def map_export(row, k: str, slide: str, data: tile_map.MapData, thumb, res: dict | None,
               meta: dict) -> None:
    """The map picture of one view (title, map, colour key), made when clicked (the analyzer's
    "Map picture")."""
    views = tile_map.modes(data, res)
    with row.popover("Download the map (PNG)", icon=":material/image:",
                     help="A labelled picture of the map in one view, for a report or a "
                          "tumor board"):
        mode = st.selectbox("View", views, format_func=tile_map.MODES.get, key=f"{k}-pngview")
        enc = meta.get("encoder", {}).get("name", "?")
        st.download_button(
            "Download the map (PNG)",
            lambda: slide_export.map_png(
                thumb, data, mode, 0.55, title=slide,
                subtitle=f"{int(data.ok.sum()):,} squares of {TILE_UM:.0f} µm · tissue head on "
                         f"{enc} · model inferences",
                legend=tile_map.legend_items(data, mode, res)),
            file_name=f"{slide}_{mode}_map.png", mime="image/png", key=f"{k}-png",
            on_click="ignore", width="stretch")


CUTOFFS_INV = inv.CUTOFFS


def render_own(page: Page, pf: PatientFile, slides: list[str], version: int | None) -> None:
    page.title("patient's own slide", "placeholder cutoffs", "not reviewed by a pathologist",
               "implemented, validated on held-out BCSS slides", colors=CHIP_COLORS)
    st.markdown(f"**{len(slides)} diagnostic section(s) of this patient's tumor** scored by the "
                "slide pipeline: " + ", ".join(slides) + ". Each section is one cut through the "
                "block: a 2D sample of the tumor, not the whole tumor.")
    chosen = st.radio("Section", slides, horizontal=True, key=f"{pf.id}-section") \
        if len(slides) > 1 else slides[0]

    def compare(page: Page) -> None:
        numbers = {}  # the open section's own analysis; the others' stored numbers, unanalysed
        for name in slides:
            if name == chosen and (got := scored(name)):
                numbers[name] = {**got[1]["numbers"], "slide": name}
            elif name != chosen and (stored := section_numbers(name)) is not None:
                numbers[name] = {**stored, "slide": name}
        pairs = [(a, b) for i, a in enumerate(slides) for b in slides[i + 1:]
                 if numbers.get(a) and numbers.get(b)]
        with page.details("The sections compared", len(slides)):
            for a, b in pairs:  # a column mixes numbers and words ("no front"), so show text
                st.dataframe(pd.DataFrame(inv.compare(numbers[a], numbers[b])).map(
                    lambda v: "—" if v is None else f"{v:.3g}" if isinstance(v, float)
                    else str(v)), hide_index=True, width="stretch")
            st.caption("Why sections differ: each is one plane through the block, so a front "
                       "that is infiltrative in one cut can be pushing in another, a satellite "
                       "in one section can be the same tumor cut tangentially, and the counted "
                       "tiles differ. Differences between sections are not change over time: "
                       "both were cut from the same specimen. Numbers differ by more than 20% "
                       "are marked.")
            st.caption("Differences in the immune pattern, the tumor–stroma ratio and the "
                       "breakaway count are between placeholder-rule outputs, not validated "
                       "measurements.")
        with page.details("The sections side by side", len(slides), key=f"{pf.id}-side-open",
                          lazy=True) as box:
            if box.open:
                side_by_side(pf, slides)
            else:
                st.caption("Opens two or three sections in viewers next to each other.")

    render_slide(page, pf, chosen, version, compare if len(slides) > 1 else None)


def side_by_side(pf: PatientFile, slides: list[str]) -> None:
    """Two or three sections in viewers next to each other, pan and zoom linked in µm."""
    srcs = {n: slide_viewer.source(n) for n in slides
            if not st.session_state.get(f"{pf.id}|{n}-viewer-failed")}
    ok = [n for n, s in srcs.items() if isinstance(s, dict)]
    if len(ok) < 2:
        st.caption("Side by side needs the slide viewer for two sections, and it is not "
                   "available here: " + "; ".join(f"{n}: {s}" for n, s in srcs.items()
                                                  if isinstance(s, str)) + ".")
        return
    show = st.multiselect("Sections", ok, default=ok[:3], max_selections=3, key=f"{pf.id}-side")
    if len(show) < 2:
        st.caption("Pick two or three sections.")
        return
    mpp = ", ".join(f"{n} {srcs[n]['mpp']:.3f}" for n in show)
    ratio = max(srcs[n]["mpp"] for n in show) / min(srcs[n]["mpp"] for n in show)
    st.caption((f"The sections' scales match ({mpp} µm per pixel)" if ratio <= 1.01 else
                f"The sections' scales differ by {ratio - 1:.1%} ({mpp} µm per pixel)")
               + ": zoom is linked by physical size, one screen pixel showing the same µm in "
               "each, and pan moves every section by the same distance. The sections are not "
               "registered to each other: linked pan does not line up their anatomy, and each "
               "is one plane through the block. Untick \"link pan and zoom\" to move them "
               "apart; click a tile to open it in that section's Spot panel above.")
    slide_viewer.show([srcs[n] for n in show], key=f"{pf.id}-compare", height=520,
                      on_change=lambda: viewer_event(pf.id, f"{pf.id}-compare"))


def render_example(page: Page, pf: PatientFile, result: dict | None) -> None:
    slide_tests = [t for t in pf.tests if t.workbench == "slides"]
    if result is None:
        page.title(PLANNED)
        with page.overview():
            st.warning("The public example region is not installed on this server, so there "
                       "is nothing to show here. A scanned H&E section of this tumor would open "
                       "the patient's own map.")
        with page.card():
            st.caption("The tissue head's card appears with a scored section.")
        cannot_see(page)
        with page.export(empty="Nothing to export: no section of this patient's tumor is "
                               "scored here."):
            pass
        return
    page.title("example slide", "placeholder cutoffs",
               "implemented, validated on held-out BCSS slides", colors=CHIP_COLORS)
    if slide_tests:
        st.markdown("**In this file:** " + "; ".join(
            f"{t.name} (month {t.month}): {t.result}" for t in slide_tests))
        st.info("The record holds the pathology report's text, not the slide image. Below, the "
                "slide workbench is shown on a public example region so that what it would do "
                "with this patient's slide is visible; nothing below is this patient's tissue. "
                "A scanned H&E section of this tumor would open the patient's own map.",
                icon="🔬")
    else:
        st.info("This file holds no slide image. Below, the slide workbench on a public example "
                "region; nothing below is this patient's tissue. A scanned H&E section of this "
                "tumor would open the patient's own map.", icon="🔬")

    meta, tiles = result["meta"], result["tiles"]
    head = meta.get("head", {})
    classes = head.get("classes", [])
    res = analyze(tiles, classes)
    df, s = res["tiles"], res["summary"]
    data, thumb = example_map(files_stamp(EXAMPLE))
    k = f"{pf.id}|example"
    enc = meta.get("encoder", {})
    st.caption(f"Source: {meta.get('source', 'public TCGA-BRCA slide region')} · slide "
               f"{meta.get('slide', '')}, region {s['tiles']} tiles of {TILE_UM:.0f} µm · encoder "
               f"{enc.get('name', '?')} ({enc.get('license', '?')}, {enc.get('access', '?')}) · "
               f"head: {head.get('kind', '?')} · method version 0.1 (spike) · "
               f"status: {meta.get('status', 'implemented')}.")

    with page.overview():
        frac = s["tissue_fractions"]
        top3 = sorted(frac.items(), key=lambda kv: -kv[1])[:3]
        st.markdown(
            f"**Model inference.** Of {s['usable_tiles']} usable tiles, the map reads "
            + ", ".join(f"{LABELS[k].lower()} {v:.0%}" for k, v in top3)
            + f". The main tumor region covers {s['main_tumor_mm2']} mm² with a front of "
            f"{s['front_length_mm']} mm; {s['satellite_pieces']} separate tumor piece(s). "
            f"{s['unsure_share']:.0%} of the tissue is marked unsure (top probability below "
            f"{CUTOFFS['unsure_below'][0]}, a placeholder cutoff). "
            + ("Excluded by quality control: "
               + ", ".join(f"{v} {k}" for k, v in s["excluded"].items()) + "."
               if s["excluded"] else "No tile was excluded by quality control.")
        )
        if s["facing"]:
            faces = ", ".join(f"{LABELS.get(k, k).lower()} {v:.0%}"
                              for k, v in s["facing"].items())
            st.markdown(f"**What the front faces** (tiles touching the front, outside the "
                        f"tumor): {faces}. A 2D snapshot of this section: where the tumor is, "
                        "not where it is going.")
        row = st.container(horizontal=True)  # wraps on a narrow screen instead of cutting values
        row.metric("Tumor area (map)", f"{s['tumor_mm2']} mm²", width="content")
        row.metric("Front length", f"{s['front_length_mm']} mm", width="content")
        row.metric("Unsure share", f"{s['unsure_share']:.0%}", width="content")
        row.metric("Head accuracy (held out)", f"{head.get('accuracy', float('nan')):.0%}",
                   width="content")
        page.look_here([], empty="Nothing to look at: this is a public example region, not "
                                 "this patient's tissue.")
        st.text_input("Search inside the slide, in plain words", key=f"{k}-search",
                      placeholder="carcinoma at the border · necrosis in the core · unsure",
                      help="Known words: a tissue class, a flag, a place (border, core, "
                           "around). The map colours every match; Q1… mark the best spots.")
        found = run_search(k, data, None)
        search_answer(found)

    with page.picture("Slide map", caption=(
            "The example region's scan with the analysis on top. The buttons in the map switch "
            "the view (tissue class, zones with the front, certainty, quality control); the "
            "slider sets how see-through the colours are. Hover a square for its scores, scroll "
            "to zoom, drag to move. Each square is one score for 112 µm of tissue; classes are "
            "model inferences smoothed over 3×3 squares. The region is public TCGA-BRCA data, "
            "not this patient's tissue.")):
        map_area(k, "example", data, thumb, None, found, spot=False)

    with page.details("Certainty", f"{int(df['unsure'].sum())} unsure tiles"):
        chips("placeholder cutoffs")
        nan = float("nan")
        st.caption(f"Unsure here = top probability below {CUTOFFS['unsure_below'][0]} "
                   f"({CUTOFFS['unsure_below'][2]}). On the held-out BCSS tiles the head was "
                   f"right on {head.get('accuracy_below_cutoff', nan):.0%} of tiles below the "
                   f"cutoff and {head.get('accuracy_at_or_above_cutoff', nan):.0%} at or above "
                   f"it ({head.get('share_below_cutoff', nan):.0%} of tiles below). The map's "
                   "Certainty view shows where.")
    with page.details("Tumor region, front and zones", f"{s['front_length_mm']} mm of front"):
        st.caption("Tumor = smoothed P(invasive carcinoma) ≥ 0.5 (design); zones by distance to "
                   "the front: core (> 500 µm inside), front band (± 500 µm), peritumoral "
                   "(0.5–2 mm outside). Geometry on model inferences; the map's Zones view "
                   "draws them with the front in black.")
    excluded = df[df["qc"] != QC_OK]
    with page.details("Quality control", f"{len(excluded)} of {s['tiles']} tiles excluded"):
        chips("placeholder cutoffs")
        st.caption("Glass, pen ink and blur are checked per tile from texture and colour "
                   "measures (edge density, structure coverage, ink colour shares, Laplacian "
                   "variance). The cutoffs were set by eye on the team's colon slides and have "
                   "not been re-checked on breast tissue: placeholders. Blood, folds and stain "
                   "variation are not checked yet (planned).")
        if excluded.empty:
            st.markdown(f"No tile excluded ({s['tiles']} tiles, all passed).")
        else:
            cols = ["row", "col", "qc", "edges", "structure_cov", "ink_bluegreen", "ink_black",
                    "ink_red", "blur"]
            st.dataframe(excluded[cols], hide_index=True, width="stretch")

    with page.card():
        head_card(meta, classes)
        st.caption("On a patient's own scored section this workbench adds the direction of "
                   "invasion, breakaway candidates with the counting field, the immune pattern, "
                   "satellite islands, the risk map, a Spot panel per tile, search, review marks "
                   "and export (see a TCGA case with a scored slide).")
    cannot_see(page)
    with page.export(empty="Nothing to export: no section of this patient's tumor is scored; "
                           "the example region is public data, not this patient's."):
        pass


def render(file: PatientFile, version: int | None = None, test=None) -> None:
    page = Page("slides", file, test, version)
    slides = own_slides(file.id.split()[-1]) if file.kind == "TCGA-BRCA" else []
    if slides:
        render_own(page, file, slides, version)
    else:
        render_example(page, file, load_result(EXAMPLE))

if __name__ == "__main__":
    from muffle.workspace import synthetic_file

    st.set_page_config(page_title="Pathology slide workbench", layout="wide")
    st.text_input("Reviewer initials", key="reviewer", max_chars=5)  # the shell's field
    cases = json.loads((RESULTS / "cases.json").read_text()) if (RESULTS / "cases.json").exists() \
        else {}
    which = st.selectbox("File", ["SYNTHETIC-001 (example region)"]
                         + [f"Case {i} (own slides)" for i in cases])
    if which.startswith("Case"):
        from types import SimpleNamespace

        from muffle.workspace import case_file

        idx = int(which.split()[1])
        pf = case_file(SimpleNamespace(index=idx, site="site-0", percentile=50.0, group="medium",
                                       age=50.0, stage="II", layers=["clinical"], missing=[],
                                       mutations=None), slides=cases[str(idx)])
        render(pf)
    else:
        tl = json.loads((APP / "timeline_synthetic.json").read_text(encoding="utf-8"))
        render(synthetic_file(tl))

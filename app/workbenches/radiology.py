"""Radiology workbench for a patient file (docs/WORKSPACE.md, "Radiology"; docs/WORKBENCHES.md
§6; method and limits in docs/radiology.md).

streamlit run app/workbenches/radiology.py        # standalone: every file with imaging

The workspace pages call ``render(pf, version=None, test=None)`` with a
``muffle.workspace.PatientFile``; it draws inside the current container only, in the shared page
skeleton (``workbenches._page``: overview with the look-here queue and search, the picture,
counted details, the Spot panel, the card, what the test cannot see, export). Two pages in one:

* **Scan map**, for a file whose imaging tests carry a TCIA barcode (a TCGA patient with a
  processed public study, ``radiology_results/``): the slice underneath with see-through layers
  (``muffle.workbench.radiology_map``: Lesion, Kinetics, Enhancement, Change; the slide map's
  in-chart views and opacity slider), series, slice, window and level, pointers for the
  look-here queue, a fixed-size hover box per square and a click that opens the square in the
  Spot panel (its crop, curve, why, how sure, what to check, the mark), a Spot panel per
  candidate lesion (size, volume, the kinetics curve, how its box was chosen, the model and its
  published validation), search inside the scan with Q1… spots, prior comparison where two
  study dates exist, what the images cannot show, the model and validation card, review marks
  and exports (the map picture, the study report in Markdown). Mammograms: one view at a time
  on the same map with the Density view.
* **Report-driven page**, for a file whose imaging is report text only (SYNTHETIC-001): each read
  as the report words it, the lesion vocabulary, a lesion table that tracks every named site
  across the reads ("no measurements recorded"), lead and lag against CA 15-3, the reports'
  limits, search, marks and exports.

Images, contours and numbers are precomputed offline (``scripts/radiology_pipeline.py``); the
hosted app runs no model. Every candidate, contour and measurement is a model inference; the
structured report's BI-RADS category, pathology and receptors, and every report read, are
observed. Nothing here is a diagnosis or a recommendation.
"""

from __future__ import annotations

import hashlib
import io
import json
import math
import sys
import threading
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))
if str(APP) not in sys.path:  # standalone: streamlit run app/workbenches/radiology.py
    sys.path.insert(0, str(APP))

import altair as alt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from muffle.report.case_tools import INFERENCE, OBSERVED  # noqa: E402
from muffle.workbench import radiology as rad  # noqa: E402
from muffle.workbench import radiology_export as rx  # noqa: E402
from muffle.workbench import radiology_map as rm  # noqa: E402
from muffle.workbench import radiology_search as rs  # noqa: E402
from muffle.workbench import tile_map  # noqa: E402
from muffle.workbench.grammar import chip  # noqa: E402
from muffle.workspace import IMPLEMENTED, MARKS, PatientFile, finding_key  # noqa: E402
from workbenches._page import Page, land, queue_items  # noqa: E402

RESULTS = APP / "workbenches" / "radiology_results"
COLORS = {"C1": (230, 73, 72), "C2": (235, 160, 52), "C3": (64, 160, 230)}
HEX = {k: "#%02x%02x%02x" % v for k, v in COLORS.items()}
ZOOM = 2  # shipped slices are at most 256 px; drawn at up to twice that,
VIEW_PX = 460  # and at most this wide: the page column is 468 px at 800 px with the sidebar open
NO_MARK = "no mark"
PHASE_NAMES = {"pre": "Pre-contrast", "early": "Early post-contrast", "late": "Delayed",
               "sub": "Subtraction (early − pre)"}
KUHL_NUMBERS = ("in Kuhl et al. 1999 (266 lesions), type III curves were seen in 57% of cancers "
                "and 6% of benign lesions, type I in 9% and 83%: evidence about curve types, not "
                "a diagnosis of this lesion")


EXAMPLE_CHIP = "public example pair, not this patient"


def chips(*labels: str) -> None:
    """The shared badges (``muffle.workbench.grammar``); a placeholder is always orange."""
    st.caption(" ".join(chip(label, "orange" if label in ("synthetic patient", EXAMPLE_CHIP)
                             else None) for label in labels))


# --- review marks and pins (the workspace's shared stores) ----------------------------------------
def _store_mark(key: str, what: str, widget: str) -> None:
    choice = st.session_state.get(widget, NO_MARK)
    reviews = st.session_state.setdefault("reviews", {})
    if choice in (None, NO_MARK):
        reviews.pop(key, None)
    else:
        reviews[key] = {"what": what, "mark": choice,
                        "by": st.session_state.get("reviewer") or "",
                        "at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _toggle_pin(key: str, what: str) -> None:
    pins = st.session_state.setdefault("pins", {})
    if pins.pop(key, None) is None:
        pins[key] = what


def review(key: str, what: str) -> None:
    """Agree / disagree / second look (and reviewed) plus a pin, for one finding."""
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    done = st.session_state.get("reviews", {}).get(key)
    c1 = c2 = st.container(horizontal=True, gap="medium", vertical_alignment="bottom")
    widget = f"rad-mark-{h}"
    if widget not in st.session_state:
        st.session_state[widget] = done["mark"] if done else NO_MARK
    c1.segmented_control("Your mark", [NO_MARK, *MARKS], key=widget,
                         on_change=_store_mark, args=(key, what, widget),
                         help="Marks and pins go into the report export")
    c2.checkbox("Pin", key=f"rad-pin-{h}", value=key in st.session_state.get("pins", {}),
                on_change=_toggle_pin, args=(key, what))
    if done:
        st.caption(f"{done['mark']} · {done['by'] or 'no initials'} · {done['at']}")


# --- images ---------------------------------------------------------------------------------------
# Read-only arrays: no copy per rerun. An MRI study's phases are 17-27 MB decoded and its masks
# about 10 MB, so the least recently used go (a screen needs at most two studies at once).
@st.cache_resource(show_spinner=False, max_entries=16)
def _strip(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"))


def slices(study: dict, key: str) -> np.ndarray:
    """[slice, row, col] uint8 from a phase's JPEG strip."""
    d = study["display"]
    return _strip(str(Path(study["folder"]) / f"{key}.jpg")).reshape(d["slices"], d["rows"],
                                                                     d["cols"])


def window(img: np.ndarray, level: int, width: int) -> np.ndarray:
    lo = level - width / 2
    return (np.clip((img.astype(float) - lo) / max(width, 1), 0, 1) * 255).astype(np.uint8)


def view_of(study: dict, c: dict | None, i: int, zoom: bool) -> tuple:
    """The whole shown slice at ``ZOOM`` (narrower when that would pass ``VIEW_PX``), or a
    square around candidate ``c`` (its box on this slice, else on its longest-diameter slice)
    drawn four times larger (the cine's frame)."""
    d = study["display"]
    w, h = d["cols"], d["rows"]
    k = min(ZOOM, VIEW_PX / w)
    if not zoom or c is None or not c["per_slice"]:
        return 0, 0, w, h, k
    s = c["per_slice"].get(str(i)) or c["per_slice"][str(_ld_index(study, c))]
    side = min(64, w, h)
    cx, cy = (s["box"][0] + s["box"][2]) / 2, (s["box"][1] + s["box"][3]) / 2
    x0 = int(min(max(cx - side / 2, 0), w - side))
    y0 = int(min(max(cy - side / 2, 0), h - side))
    return x0, y0, side, side, w * k / side  # the same drawn width as the whole slice


def load(uptime: str | None) -> str:
    """A run's machine load from its recorded ``uptime`` line ("load average 18.77, 18.38,
    15.07"), not the raw line with its clock and users (QA R3-19)."""
    if not uptime:
        return "load not recorded"
    return f"load average {uptime.split('load average:')[-1].strip()}"


def kinetics_chart(c: dict) -> alt.Chart:
    k = c["kinetics"]
    df = pd.DataFrame({"phase": k["labels"], "order": range(len(k["labels"])),
                       "enhancement (% over pre-contrast)": k["relative"]})
    line = alt.Chart(df).mark_line(point=True, color=HEX.get(c["id"], "#888")).encode(
        # labels on the slant and a short title: upright labels and the column's name as title
        # left the plot a few px tall and the title cut (QA R3-10)
        x=alt.X("phase:N", sort=list(df["phase"]), title=None, axis=alt.Axis(labelAngle=-35)),
        y=alt.Y("enhancement (% over pre-contrast):Q", title="% over pre-contrast"),
        tooltip=["phase:N", "enhancement (% over pre-contrast):Q"])
    rules = alt.Chart(pd.DataFrame({"y": [rad.CUTOFFS["initial_slow_below"][0],
                                          rad.CUTOFFS["initial_fast_above"][0]],
                                    "cutoff": ["slow below (placeholder)",
                                               "fast above (placeholder)"]})).mark_rule(
        strokeDash=[4, 4], color="#eb6834").encode(y="y:Q", tooltip=["cutoff:N", "y:Q"])
    return (rules + line).properties(height=220)


@st.cache_resource(show_spinner=False, max_entries=16)
def _mask(folder: str, cid: str, shape: tuple) -> np.ndarray:
    """A candidate's mask packed eight voxels to a byte: 0.4-0.6 MB kept instead of the bool
    volume's 3-4.5 MB (docs/qa.md, "Memory pass")."""
    study = rad.load_study(folder)
    return np.packbits(rad.candidate_mask(next(c for c in study["candidates"]
                                               if c["id"] == cid), shape), axis=None)


def masks(study: dict) -> dict[str, np.ndarray]:
    """Each candidate's contour as a mask on the shipped grid, for the views other than axial
    (unpacked for this run: a few ms each)."""
    d = study["display"]
    shape = (d["slices"], d["rows"], d["cols"])
    return {c["id"]: np.unpackbits(_mask(study["folder"], c["id"], shape),
                                   count=math.prod(shape)).reshape(shape).view(bool)
            for c in study["candidates"]}


def series_keys(study: dict) -> list[str]:
    """The shipped series: pre, early, the phases between (round 2), delayed and subtraction."""
    return ["pre", "early", *study.get("shipped", {}).get("between", {}), "late", "sub"]


def series_label(study: dict, key: str) -> str:
    between = study.get("shipped", {}).get("between", {})
    if key in between:
        return f"Phase {between[key] + 1}: {study['phases'][between[key]]['label']}"
    return {"pre": PHASE_NAMES["pre"], "early": f"{PHASE_NAMES['early']}: "
                                                 f"{study['phases'][1]['label']}",
            "late": f"{PHASE_NAMES['late']}: {study['phases'][-1]['label']}",
            "sub": PHASE_NAMES["sub"]}[key]


def edges(m: np.ndarray) -> np.ndarray:
    p = np.pad(m, 1)
    return m & ~(p[2:, 1:-1] & p[:-2, 1:-1] & p[1:-1, 2:] & p[1:-1, :-2])


K = 2  # the smaller panes are drawn at twice the shipped size


def pane(img: np.ndarray, layers: list[tuple], lines: list[tuple],
         marks: list[tuple]) -> Image.Image:
    """A grey view drawn at ``K``: mask outlines (mask, colour), crosshair lines (("h" | "v",
    position, colour)) and labelled measurement marks ((x0, y0, x1, y1, colour, text))."""
    rgb = np.stack([img] * 3, -1)
    for m, col in layers:
        rgb[edges(m)] = col
    out = Image.fromarray(rgb).resize((img.shape[1] * K, img.shape[0] * K), Image.NEAREST)
    draw = ImageDraw.Draw(out)
    for kind, at, col in lines:
        a = at * K
        draw.line([(0, a), (out.width, a)] if kind == "h" else [(a, 0), (a, out.height)],
                  fill=col, width=1)
    for x0, y0, x1, y1, col, text in marks:
        draw.line([(x0 * K, y0 * K), (x1 * K, y1 * K)], fill=col, width=2)
        if text:
            draw.text((x1 * K + 4, (y0 + y1) / 2 * K - 6), text, fill=col)
    return out


def three_planes(study: dict, key0: str, vol: np.ndarray, i: int, picked: dict | None) -> None:
    """Axial, coronal and sagittal views of the shipped volume with linked positions: the axial
    slice (the viewer's slider) and a row and a column, each drawn as a line on the other two
    views; the contours resliced from the candidates' masks; the craniocaudal extent and the
    longest-diameter slice carried over as marks."""
    d = study["display"]
    box = (picked or {}).get("per_slice", {}).get(str(i), {}).get("box")
    at = ((box[1] + box[3]) / 2, (box[0] + box[2]) / 2) if box else (d["rows"] / 2, d["cols"] / 2)
    for k, default in ((f"{key0}-row", at[0]), (f"{key0}-col", at[1])):
        if k not in st.session_state:
            st.session_state[k] = int(default) + 1
    c1, c2 = st.columns(2)
    r = c1.slider("Coronal plane (row, front to back)", 1, d["rows"], key=f"{key0}-row") - 1
    c = c2.slider("Sagittal plane (column, patient's right to left)", 1, d["cols"],
                  key=f"{key0}-col") - 1
    ms = masks(study)
    row_i = rad.reslice_row(i, d)
    views = {}
    for plane, index, lines in (
            ("axial", i, [("h", r + 0.5, (80, 200, 120)), ("v", c + 0.5, (80, 160, 255))]),
            ("coronal", r, [("h", row_i, (255, 220, 80)), ("v", c + 0.5, (80, 160, 255))]),
            ("sagittal", c, [("h", row_i, (255, 220, 80)), ("v", r + 0.5, (80, 200, 120))])):
        img = rad.reslice(vol, plane, index, d)
        layers, marks = [], []
        for cand in study["candidates"]:
            m = rad.reslice(ms[cand["id"]], plane, index, d, order=0)
            if not m.any():
                continue
            col = COLORS.get(cand["id"], (255, 255, 0))
            layers.append((m, col))
            ys, xs = np.where(m)
            if plane == "axial":
                s = cand["per_slice"].get(str(i))
                if s and len(s["ld_line"]) == 2:
                    (x0, y0), (x1, y1) = s["ld_line"]
                    marks.append((x0, y0, x1, y1, (255, 255, 102), f"{s['ld_mm']:g} mm"))
            else:  # the craniocaudal extent beside the contour, and the LD slice
                x = xs.max() + 3
                marks.append((x, ys.min(), x, ys.max() + 1, col,
                              f"{cand['cc_extent_mm']:g} mm head-feet"))
                y = rad.reslice_row(_ld_index(study, cand), d)
                marks.append((xs.min(), y, xs.max() + 1, y, (255, 255, 102), "LD slice"))
        views[plane] = pane(img, layers, lines, marks)
    a, b, s_ = st.columns([2.2, 2.2, 1.3])
    a.image(views["axial"], caption=f"Axial, slice {i + 1}", width="stretch")
    b.image(views["coronal"], caption=f"Coronal, row {r + 1}", width="stretch")
    s_.image(views["sagittal"], caption=f"Sagittal, column {c + 1}", width="stretch")
    st.caption("Lines: yellow = the axial slice, green = the coronal plane, blue = the sagittal "
               "plane. " + rad.anisotropy(d) + ". Contours are the axial contours stacked and "
               "resliced (model inference); the marks carry the craniocaudal extent and the "
               "longest-diameter slice over from the measurements"
               + (f"; {picked['id']} is the chosen candidate" if picked else "") + ".")


def cine(study: dict, c: dict | None, i: int, level: int, width: int) -> bytes:
    """An animated GIF through every shipped phase at slice ``i``, zoomed on candidate ``c``
    (its contour outlined) or the whole slice."""
    keys = [k for k in series_keys(study) if k != "sub"]
    x0, y0, vw, vh, _ = view_of(study, c, i, c is not None)
    side = 256
    frames = []
    for key in keys:
        img = window(slices(study, key)[i], level, width)[y0:y0 + vh, x0:x0 + vw]
        rgb = Image.fromarray(img).resize((side, round(side * vh / vw)), Image.BILINEAR)
        rgb = rgb.convert("RGB")
        draw = ImageDraw.Draw(rgb)
        k = side / vw
        for poly in (c["per_slice"].get(str(i), {}).get("contours", []) if c else []):
            if len(poly) > 2:
                pts = [((x - x0) * k, (y - y0) * k) for x, y in poly]
                draw.line(pts + [pts[0]], fill=COLORS.get(c["id"], (255, 255, 0)), width=1)
        label = series_label(study, key).split(": ")[-1]
        draw.rectangle([0, 0, side, 14], fill=(0, 0, 0))
        draw.text((4, 1), f"{label} · slice {i + 1}", fill=(255, 255, 255))
        frames.append(rgb)
    buf = io.BytesIO()
    frames[0].save(buf, format="GIF", save_all=True, append_images=frames[1:], duration=800,
                   loop=0)
    return buf.getvalue()


# --- the scan map (muffle.workbench.radiology_map: the slide map's approach, for a scan) ---------
MAP_CAPTION = ("The study's own images with the models' results on top. Switch views, fade the "
               "colour layer and step through the nearby slices with the controls inside the map "
               "(the zoom stays), scroll to zoom, drag to move, hover a square for its numbers "
               "and click one for its full story in the Spot panel below. Every colour is a "
               "model inference or a rule on one.")
MAP_CAPTION_MG = ("The study's own mammogram, one view at a time, with the models' results on top. "
                  "Fade the colour layer with the slider inside the map (the zoom stays), scroll "
                  "to zoom, drag to move, hover a square for its numbers and click one for its "
                  "full story in the Spot panel below. Every colour is a model inference or a "
                  "rule on one.")
MAX_MARKERS = 8
MAP_WINDOW = 7  # slices on each side of the chosen one that the map carries (about 0.9 MB)
SEARCH_COLOR = "#2468c0"


def map_memory(key0: str) -> dict:
    """What a study's map remembers between clicks."""
    store = st.session_state.setdefault("rad_map_memory", {})
    return store.setdefault(key0, {"zoom": None, "zoom_rev": 0, "outline": None,
                                   "last_click": None, "search": None, "match_on": True,
                                   "spot": None, "cand_seen": None, "pending": {}})


def stamp(study: dict) -> str:
    """The study's files' version, for the shared caches."""
    p = Path(study["folder"]) / "study.json"
    return str(p.stat().st_mtime_ns) if p.exists() else "0"


@st.cache_resource(show_spinner=False, max_entries=8)
def geometry(folder: str, stamp_: str) -> tuple[np.ndarray, dict]:
    """An MRI study's skin surface per slice and column (``rad.skin_rows``) and its nipples
    (``rm.nipples``), from the pre-contrast copy, decoded once here and not kept."""
    study = rad.load_study(folder)
    d = study["display"]
    pre = np.asarray(Image.open(Path(folder) / "pre.jpg").convert("L")).reshape(
        d["slices"], d["rows"], d["cols"])
    skin = rad.skin_rows(pre).astype(np.int16)
    return skin, rm.nipples(skin, d)


def later_pair_folder(study: dict, changes: dict | None) -> str | None:
    """The folder of the pair this study is the later date of (its map gets the Change view)."""
    if changes and Path(changes["later"]["folder"]).name == Path(study["folder"]).name:
        return str(Path(study["folder"]).parent)
    return None


def _change_layer(pair_folder: str, i: int) -> dict:
    """The later study's slice ``i`` of a pair (``rm.change_layer``): its contours against the
    earlier ones moved by the rigid alignment, and the unreliable blocks."""
    pair, earlier, later = rad.load_pair(pair_folder)
    ch = rad.pair_change(pair, earlier, later)
    d = later["display"]
    now = {c["id"]: rm.fill_polygons(c["per_slice"][str(i)]["contours"], d["rows"], d["cols"])
           for c in later["candidates"] if str(i) in c["per_slice"]}
    before = {cid: rad.aligned_view(m.astype(np.uint8) * 255, earlier["display"], d,
                                    ch["registration"], "axial", i) > 127
              for cid, m in masks(earlier).items()}
    return rm.change_layer(later, earlier, ch, i, now, before)


@st.cache_resource(show_spinner=False, max_entries=12)
def change_slice(pair_folder: str, i: int) -> dict:
    """``_change_layer``, shared and read-only."""
    return _change_layer(pair_folder, i)


@st.cache_resource(show_spinner=False, max_entries=2)
def change_volume(pair_folder: str) -> dict[int, np.ndarray]:
    """Every slice's change classes of a pair (for the search), the slices that hold one."""
    _, _, later = rad.load_pair(pair_folder)
    out = {}
    for i in range(later["display"]["slices"]):
        classes = _change_layer(pair_folder, i)["classes"]
        if classes.any():
            out[i] = classes
    return out


@st.cache_resource(show_spinner=False, max_entries=16)  # a window and one more
def slice_map(folder: str, stamp_: str, i: int, pair_folder: str | None) -> rm.ScanMap:
    """One MRI slice's map data (shared, read-only; never changed in place)."""
    study = rad.load_study(folder)
    skin, nips = geometry(folder, stamp_)
    change = change_slice(pair_folder, i) if pair_folder else None
    return rm.mri_slice(study, i, slices(study, "sub"), skin, nips, change, stamp_)


@st.cache_resource(show_spinner=False, max_entries=8)
def view_map(folder: str, stamp_: str, view_key: str) -> rm.ScanMap:
    """One mammography view's map data (shared, read-only)."""
    study = rad.load_study(folder)
    position, v = next((n, v) for n, v in enumerate(study["views"]) if v["key"] == view_key)
    return rm.mammo_view(study, v, _mammo(str(Path(folder) / v["image"])), position, stamp_)


_figures: dict = {}
_fig_lock = threading.Lock()


def figure_once(shape: tuple, build):
    """The map's figure for one state of the map (study, slice or view, series, window,
    views, search, outline, zoom, pointers): a click elsewhere on the page reruns it without
    rebuilding the figure. A few figures only, each kept as its plain dict
    (``tile_map.frozen``)."""
    with _fig_lock:
        if shape not in _figures:
            if len(_figures) >= 3:
                _figures.pop(next(iter(_figures)))
            fig, first = build()
            _figures[shape] = tile_map.frozen(fig), first
        return _figures[shape]


def reset_view(key0: str) -> None:
    """The whole image, nothing outlined."""
    mem = map_memory(key0)
    mem["zoom"], mem["outline"] = None, None
    mem["zoom_rev"] += 1


def focus_square(key0: str, display: dict, at, row: float, col: float, square: int) -> None:
    """Zoom the map around a square (top-left pixel row, col) on slice or view ``at``, outline
    it and open it in the Spot panel."""
    mem = map_memory(key0)
    mem["zoom"] = rm.zoom_box_for(display["rows"], display["cols"], display["pixel_mm"],
                                  row + square / 2, col + square / 2)
    mem["zoom_rev"] += 1
    mem["outline"] = (at, int(row), int(col))
    mem["spot"] = {"kind": "square", "at": at, "row": int(row), "col": int(col)}


def focus_candidate(key0: str, study: dict, cid: str, set_slice: bool = True) -> None:
    """The candidate's slice (its longest diameter's), the map zoomed around its box there and
    its story in the Spot panel. Only before the slice slider is drawn (a callback, or the top
    of the map)."""
    c = next((c for c in study["candidates"] if c["id"] == cid), None)
    if c is None:
        return
    mem = map_memory(key0)
    j = rm.ld_index(study, c)
    if set_slice:
        st.session_state[f"{key0}-slice"] = j + 1
    s = c["per_slice"].get(str(j))
    d = study["display"]
    if s:
        box = s["box"]
        mem["zoom"] = rm.zoom_box_for(d["rows"], d["cols"], d["pixel_mm"],
                                      (box[1] + box[3]) / 2 + 0.5, (box[0] + box[2]) / 2 + 0.5)
        mem["zoom_rev"] += 1
        st.session_state[f"{key0}-row"] = int((box[1] + box[3]) / 2) + 1
        st.session_state[f"{key0}-col"] = int((box[0] + box[2]) / 2) + 1
    mem["outline"] = None
    mem["spot"] = {"kind": "cand", "id": cid}
    mem["cand_seen"] = cid


def search_placeholder(study: dict | None) -> str:
    """What the search box suggests: what this page can answer (QA R3-2)."""
    if study is None:
        return "liver · progression · month 12 · lesion size"
    return ("enhancing lesion · washout · spiculated · C2 · receptor status"
            if study["modality"] == "MR" else "dense · calcification · lymph node · mass")


def scan_search(pf: PatientFile, study: dict, key0: str, changes: dict | None) -> dict | None:
    """The search box inside the scan: known words, the answer under it; the map colours the
    matches and Q1… mark the best spots."""
    st.text_input("Search this scan in plain words", key=f"{key0}-search",
                  placeholder=search_placeholder(study),
                  help="Known words: a candidate (enhancing lesion, C2, largest), a curve "
                       "(washout, plateau, persistent, fast), the margin (spiculated), the chest "
                       "wall, unsure, change, dense. What a map cannot see (calcifications at "
                       "this size, lymph nodes, histology, receptor status, grade) gets an honest "
                       "answer naming the test that can. The map colours every match; Q1… mark "
                       "the best spots.")
    found = run_scan_search(key0, study, changes)
    search_answer(found)
    return found


def run_scan_search(key0: str, study: dict, changes: dict | None) -> dict | None:
    """The search box's query, matched once per change; the map shows the whole image again."""
    mem = map_memory(key0)
    query = (st.session_state.get(f"{key0}-search") or "").strip()
    if query != (mem.get("search") or {}).get("query", ""):
        if not query:
            mem["search"] = None
        elif study["modality"] == "MR":
            pair = later_pair_folder(study, changes)
            mem["search"] = rs.search(
                study, query, sub=slices(study, "sub"),
                skin=geometry(study["folder"], stamp(study))[0],
                change=change_volume(pair) if pair and "change" in rs.understand(query) else None)
        else:
            mem["search"] = rs.search(study, query, views={
                v["key"]: view_map(study["folder"], stamp(study), v["key"])
                for v in study["views"]})
        mem["match_on"] = True
        mem["zoom"], mem["outline"] = None, None
        mem["zoom_rev"] += 1
    return mem.get("search")


def search_answer(found: dict | None) -> None:
    """What the search matched, under the search box."""
    if not found:
        return
    used = ", ".join(found.get("used") or []) or "nothing"
    text = f"“{found['query']}” · matched {used}" + (
        f" · {found['message'].strip()}" if found.get("message") else "")
    (st.caption if found.get("understood") else st.warning)(
        text + (f" The map colours every square that matches {rs.MIN_SCORE:.0%} or more "
                "(model inference); Q1… mark the best spots, each with its slice or view."
                if found.get("volume") is not None else ""))


def clear_search(key0: str) -> None:
    st.session_state[f"{key0}-search"] = ""
    mem = map_memory(key0)
    mem["search"], mem["zoom"], mem["outline"] = None, None, None
    mem["zoom_rev"] += 1


def go_spot(key0: str, study: dict, s: dict) -> None:
    """A search spot's button (a callback): its slice or view, zoomed, in the Spot panel."""
    if "slice" in s:
        st.session_state[f"{key0}-slice"] = s["slice"] + 1
        at, display = s["slice"], study["display"]
    else:
        st.session_state[f"{key0}-view"] = s["view"]
        at = s["view"]
        m = view_map(study["folder"], stamp(study), s["view"])
        display = {"rows": m.rows, "cols": m.cols, "pixel_mm": m.pixel_mm}
    sq = rm.square_px(display["pixel_mm"])
    focus_square(key0, display, at, s["r"] * sq, s["c"] * sq, sq)


def search_spots(key0: str, study: dict, found: dict) -> None:
    """One strip under the map: the best spots (a click zooms there), the match colouring switch
    and Clear."""
    mem = map_memory(key0)
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        for s in found["spots"]:
            where = f"slice {s['slice'] + 1}" if "slice" in s else s["view"]
            st.button(f"{s['label']} · {where}" + (f" · {s['cand']}" if s.get("cand") else "")
                      + f" · {s['score']:.0%}", key=f"{key0}-q-{s['label']}", type="tertiary",
                      on_click=go_spot, args=(key0, study, s),
                      help="Zooms the map to this spot (its slice or view) and opens it in the "
                           "Spot panel")
        if found.get("volume") is not None:
            on = st.toggle("Colour by match", value=mem.get("match_on", True),
                           key=f"{key0}-match", help="Off: the usual views come back, the spots "
                                                     "stay")
            if on != mem.get("match_on", True):
                mem["match_on"] = on
                st.rerun()
        st.button("Clear the search", key=f"{key0}-clear", icon=":material/close:",
                  on_click=clear_search, args=(key0,), help="Empties the search box")


def map_markers(study: dict, m: rm.ScanMap, found: dict | None, items: list[dict]) -> list[dict]:
    """The pointers on the map: the search's spots on this slice or view while a search is on,
    else the candidates (the look-here queue's pointers), each with its look-here reasons."""
    if found and found.get("spots"):
        return [{"r": s["r"] * m.square + m.square / 2, "c": s["c"] * m.square + m.square / 2,
                 "label": s["label"], "color": SEARCH_COLOR, "id": None,
                 "hover": f"{s['label']}: match {s['score']:.0%}"}
                for s in found["spots"] if s.get("slice", s.get("view")) == where_key(m)]
    if m.kind != "MR":
        return []
    why = {}
    for x in items:
        if x["pointer"]:
            why.setdefault(x["pointer"], []).append(x["what"].split("): ", 1)[-1])
    return rm.candidate_pointers(study, m.index, why)


def handle_map_click(event, key0: str, m: rm.ScanMap, first_hover: int, study: dict) -> None:
    """A click on the map: a square opens in the Spot panel (drawn later in this run); a
    candidate's pointer opens that candidate, on its own slice (one more run for the slider)."""
    mem = map_memory(key0)
    try:
        points = event["selection"]["points"]
    except (TypeError, KeyError):
        return
    if not points:
        return
    p = points[0]
    sig = (p.get("curve_number"), p.get("point_index"), p.get("x"), p.get("y"),
           str(p.get("customdata")))
    if sig == mem["last_click"]:  # a selection persists across reruns: act on a new one only
        return
    mem["last_click"] = sig
    hit = rm.clicked(p.get("customdata"), p.get("x"), p.get("y"))
    if hit is None:
        return
    if hit[0] == "square":  # its own slice: any slice of the map's window, not only this one
        mem["spot"] = {"kind": "square", "at": hit[1] if m.kind == "MR" else m.where,
                       "row": hit[2], "col": hit[3]}
        return
    if any(c["id"] == hit[1] for c in study.get("candidates", [])):
        mem["pending"] = {"cand": hit[1]}  # applied above the map, before its widgets
        st.rerun()


def where_key(m: rm.ScanMap):
    """How the map's memory names this slice (its index) or view (its key)."""
    return m.index if m.kind == "MR" else m.where


def outline_index(mem: dict, m: rm.ScanMap) -> int | None:
    """The outlined square on this slice or view, if any."""
    o = mem.get("outline")
    if not o or o[0] != where_key(m):
        return None
    return rm.square_at(m, o[1], o[2])


def map_line(m: rm.ScanMap, where: str) -> None:
    """Under the map: what a square is, what the map holds, what a click does."""
    st.caption(f"One square ≈ {m.square * m.pixel_mm:.1f} mm ({m.square} shown pixels of "
               f"{m.pixel_mm:g} mm) · {where} · click a square for its full story in the Spot "
               "panel below.")


def mri_map(pf: PatientFile, study: dict, key0: str, found: dict | None, changes: dict | None,
            items: list[dict]) -> tuple:
    """The MRI scan map with its controls above (series, candidate, Whole image, window and
    level, slice) and its line and search spots under it. Returns (slice, series, level,
    window, the picked candidate, the slice's map)."""
    ss, mem = st.session_state, map_memory(key0)
    d, cands = study["display"], study["candidates"]
    ids = [c["id"] for c in cands]
    pend, mem["pending"] = mem.get("pending") or {}, {}  # asked for by a click in the last run
    if pend.get("cand") in ids:  # a pointer: its candidate, slice, zoom and story
        ss[f"{key0}-cand"] = pend["cand"]
        focus_candidate(key0, study, pend["cand"])
    if cands and ss.get(f"{key0}-cand") not in ids:
        ss[f"{key0}-cand"] = ids[0]
    cur = ss.get(f"{key0}-cand")
    if mem["cand_seen"] is None:
        mem["cand_seen"] = cur
    elif cur != mem["cand_seen"]:  # landed from the look-here queue or the report's "Open"
        focus_candidate(key0, study, cur)
    if f"{key0}-slice" not in ss:
        first = next((c for c in cands if c["id"] == cur), None)
        ss[f"{key0}-slice"] = (rm.ld_index(study, first) if first else d["slices"] // 2) + 1
    keys = series_keys(study)
    row = st.container(horizontal=True, vertical_alignment="bottom", gap="small")
    pick = row.selectbox("Series", keys, index=keys.index("early"), key=f"{key0}-phase",
                         format_func=lambda k: series_label(study, k), width=300,
                         help="The image under the colour layer: any shipped phase or the "
                              "subtraction") or "early"
    focus = row.segmented_control("Candidate", ids, key=f"{key0}-cand", on_change=_jump,
                                  args=(study, key0),
                                  help="Goes to the candidate's longest-diameter slice, zooms "
                                       "there and opens its story in the Spot panel") \
        if cands else None
    row.button("Whole image", key=f"{key0}-fit", icon=":material/fit_screen:",
               on_click=reset_view, args=(key0,),
               help="Shows the whole slice again and clears the outline")
    with row.popover("Window and level", icon=":material/contrast:",
                     help="Brightness and contrast of the image under the colours"):
        level = st.slider("Level", 0, 255, 128, key=f"{key0}-level")
        width = st.slider("Window", 1, 255, 255, key=f"{key0}-width")
        st.caption("Window and level act on the shipped 8-bit copy: " + d["window"] + ".")
    i = st.slider("Go to slice", 1, d["slices"], key=f"{key0}-slice",
                  help=f"Jumps to a slice: the map then holds it and the {MAP_WINDOW} on each "
                       "side, and the Slice slider inside the map steps through them keeping "
                       "the zoom. A jump keeps the view the page set (whole, or a candidate's), "
                       "not a wheel zoom.") - 1
    pair = later_pair_folder(study, changes)
    m = slice_map(study["folder"], stamp(study), i, pair)
    picked = next((c for c in cands if c["id"] == focus), None)
    matching = bool(found and found.get("volume") is not None and mem.get("match_on"))
    view_modes = ("match",) if matching else tuple(rm.modes(m))
    lo = max(0, min(i - MAP_WINDOW, d["slices"] - 2 * MAP_WINDOW - 1))
    shown = list(range(lo, min(d["slices"], lo + 2 * MAP_WINDOW + 1)))
    o = mem.get("outline")
    shape = (m.key, pick, level, width, view_modes, tuple(o) if o else None,
             tuple(mem["zoom"] or ()), mem["zoom_rev"], key0,
             found["query"] if found else None, tuple(x["key"] for x in items))

    def build():
        vol = slices(study, pick)
        frames = []
        for k in shown:  # the slice and its neighbours: the slider inside the map walks them
            mk = m if k == i else slice_map(study["folder"], stamp(study), k, pair)
            values = rs.values_for(found, mk) if matching else None
            frames.append(rm.frame_of(
                mk, rm.scan_jpeg(window(vol[k], level, width)),
                {md: rm.overlay_png(mk, md, values) for md in view_modes},
                map_markers(study, mk, found, items)[:MAX_MARKERS], outline_index(mem, mk)))
        legends = {md: rm.legend_items(m, md, study) for md in view_modes}
        return rm.figure(frames, legends, active_frame=shown.index(i), study=study,
                         opacity=rm.MATCH_OPACITY if matching else rm.OPACITY,
                         zoom=mem["zoom"], uirevision=f"{key0}-{mem['zoom_rev']}",
                         height=rm.height_for(m), total=d["slices"])
    fig, first = figure_once(shape, build)
    event = st.plotly_chart(fig, key=f"{key0}-map", on_select="rerun", selection_mode="points",
                            width="stretch", config={"displayModeBar": False, "scrollZoom": True,
                                                     "doubleClick": "reset"})
    handle_map_click(event, key0, m, first, study)
    here = [c["id"] for c in cands if str(i) in c["per_slice"]]
    map_line(m, f"the map holds slices {shown[0] + 1}–{shown[-1] + 1} around slice {i + 1} "
                f"(position {d['z_mm'][i]:g} mm; on it: {', '.join(here) or 'no candidate'}); "
                "its Slice slider walks them and keeps the zoom, Go to slice jumps further")
    st.caption(f"{series_label(study, pick)}; slice {i + 1} of {d['slices']} (every "
               f"{d['slice_step']} of {d['native_slices']} native slices); {d['pixel_mm']:g} mm "
               f"per shown pixel (native {d['native_pixel_mm'][0]:g} mm, slices "
               f"{d['slice_mm']:g} mm apart). {d['orientation'].capitalize()}. "
               + (f"Acquired {acq['plane']}: {acq['slices']} slices {acq['slice_mm']:g} mm "
                  f"apart, {acq['pixel_mm'][0]:g} mm pixels; the axial view is resampled from "
                  "them. " if (acq := d.get("acquisition", {})).get("plane", "axial") != "axial"
                  else "") + d.get("crop", "") + ". The dashed line is the seed rule's search "
               "limit (the intermammary cleft plus a margin, a placeholder): lesions behind it "
               "are never proposed. Kinetics are measured inside the contours only (the "
               "contour mean on the original data): the shipped 8-bit copies clip the brightest "
               "early-phase pixels, so no per-pixel curve map is drawn. Re-segmenting needs the "
               "local pipeline; the hosted app runs no model.")
    if found and found.get("spots"):
        search_spots(key0, study, found)
    return i, pick, level, width, picked, m


# --- the image viewer -----------------------------------------------------------------------------
def studies_of(pf: PatientFile) -> list[tuple]:
    return [(t, rad.load_study(rad.study_folder(t))) for t in pf.tests
            if t.workbench == "imaging" and "folder" in t.details]


def receptors(rep: dict) -> str:
    """The structured report's receptor results; a field it lacks says so."""
    return ", ".join(f"{name} {rep.get(key, 'not stated')}"
                     for key, name in (("er", "ER"), ("pr", "PR"), ("her2", "HER2")))


def provenance(study: dict) -> str:
    s, src = study["study"], study["source"]
    return (f"Data: {src['collection']}, patient {study['barcode']}, study of {s['date']} "
            f"(de-identified date), {s['scanner']}; {src['license']}, doi:{src['doi']}; 8-bit "
            f"downsampled copies, not the diagnostic originals. Method: "
            f"{rad.pipeline_name(study['pipeline'])} ({study['pipeline']['run_at']})" + (
                f"; contours by MedSAM ViT-B ({study['medsam']['model']}, revision "
                f"{study['medsam']['revision'][:7]})" if "medsam" in study else "")
            + ". Status: implemented, not validated here.")


def look_items(pf: PatientFile, version: int | None, prefix: str) -> list[dict]:
    """The workbench's look-here items (``muffle.workbench.radiology.queue``) for this page:
    one study's (``prefix`` "<barcode>|") or the reports' ("report|")."""
    return [x for x in queue_items("radiology", pf, version, lambda: rad.queue(pf, version))
            if x["key"].startswith(f"{pf.id}|imaging|{prefix}")]


def mri_page(page: Page, pf: PatientFile, study: dict) -> None:
    cands = study["candidates"]
    rep = study.get("report", {})
    key0 = f"rad-{pf.id}-{study['barcode']}"
    st.markdown(f"**{study['kind']} · {study['study']['date']}**")
    st.caption(provenance(study))

    # overview: observed, inferred, the look-here queue, search
    seed = study["seed"]
    c1 = cands[0] if cands else None
    obs = (f"**Observed** (the study's structured report): BI-RADS "
           f"{rep.get('birads', 'not stated')}; pathology {rep.get('pathology', 'not stated')}; "
           f"{receptors(rep)}; {rep.get('laterality', '')}. "
           f"{len(study['phases'])} phases: " + ", ".join(p["label"] for p in study["phases"])
           + f" ({study['phases'][1]['time_source']}).")
    inf = (f"**Model inference**: the seed rule proposed {seed['proposed']} candidate groups in "
           f"the breast region ({', '.join(f'{v} {k}' for k, v in seed['left_out'].items() if v)}"
           " left out); the top three were contoured by MedSAM. " + (
               f"C1 ({c1['side']}): longest diameter {c1['longest_diameter_mm']:g} mm, volume "
               f"{c1['volume_ml']:g} mL (range {c1['volume_range_ml'][0]:g}–"
               f"{c1['volume_range_ml'][1]:g}), {c1['kinetics'].get('initial')} initial and "
               f"{c1['kinetics'].get('delayed')} delayed enhancement (curve type "
               f"{c1['kinetics'].get('curve_type')})." if c1 else "No candidate was proposed."))
    changes = pair_for(pf, study)
    items = look_items(pf, page.version, f"{study['barcode']}|")
    with page.overview():
        st.markdown(obs + "  \n" + inf)
        st.caption("The candidates are where the subtraction is brightest, not a reading of the "
                   "study: compare them with the structured report and the images.")
        page.look_here(items, land=lambda focus: land(pf, page.version, focus))
        found = scan_search(pf, study, key0, changes)

    # the picture: the scan map
    with page.picture("Scan map", caption=MAP_CAPTION):
        chips(IMPLEMENTED, INFERENCE, "literature, placeholder until calibrated")
        i, pick, level, width, picked, m = mri_map(pf, study, key0, found, changes, items)

    # details: collapsed, each with its count
    with page.details("Three planes", "axial, coronal, sagittal"):
        chips(IMPLEMENTED, INFERENCE)
        three_planes(study, key0, window(slices(study, pick), level, width), i, picked)
    with page.details(f"Cine through the {len(study['phases'])} phases at this slice"
                      + (f", zoomed on {picked['id']}" if picked else ""), len(study["phases"]),
                      key=f"{key0}-cine-open", lazy=True) as box:
        if box.open:
            st.image(cine(study, picked, i, level, width), width=320,
                     alt=f"Every phase of the study at slice {i + 1}, in order")
            st.caption("Every shipped phase at the same slice, in order (" + "; ".join(
                p["label"] for p in study["phases"]) + f"); "
                f"{study['phases'][1]['time_source']}. The same window and level as the map; "
                "the contour is the early phase's.")
        else:
            st.caption("Opens the phases one after another at the map's slice.")
    table = lesion_rows(study)
    with page.details("Candidates", len(cands)):
        chips(IMPLEMENTED, INFERENCE, "placeholder")
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
        st.caption(f"Seed rule ({rad.CUTOFFS['seed_percentile'][1]}): {seed['rule']}. "
                   f"{seed['groups']} seed groups, {seed['proposed']} kept after the size and "
                   "shape rules; the top three are shown. The breast region: "
                   + study["region"]["rule"] + f" (posterior limit at row "
                   f"{study['region']['limit_row_display']:g} of the shown slice, the map's "
                   "dashed line). Lesions behind it, at the chest wall or in the axilla, are not "
                   "proposed.")
    since_last(page, pf, study, changes)

    # Spot panel: the clicked square, or the chosen candidate, in full
    with page.spot("The full story of one square or one candidate: click a square in the map, "
                   "or pick a candidate with Candidate above the map or Spot in the look-here "
                   "queue."):
        mri_spot(pf, study, key0, m, picked, changes)

    model_card(page, study)
    _cannot_see(page, rad.CANNOT_SEE)
    ch = changes["change"] if changes else None
    img = window(slices(study, pick)[i], level, width)

    def more(row) -> None:
        report_button(row, pf, study, key0, items, obs + "\n\n" + inf, changes)
        map_png_button(row, key0, study, m, img, map_markers(study, m, None, items),
                       title=f"{study['barcode']} · {study['study']['date']} · {m.where}",
                       subtitle=f"{series_label(study, pick)} · MedSAM contours, seed rule and "
                                "kinetics: model inferences")
    _export(page, pf, study, table, {"change": {k: ch[k] for k in (
        "rows", "sum", "protocol", "registration", "what_changed", "dates", "label")}} if ch else
        None, change_rows(ch) if ch else None, more=more)


_ld_index = rm.ld_index  # the slice a candidate opens on (the cine, the three planes, the change)


def _jump(study: dict, key0: str) -> None:
    """The Candidate control (a callback): the candidate's slice, the map zoomed there, its
    story in the Spot panel, and the three planes through its box's centre."""
    cid = st.session_state.get(f"{key0}-cand")
    if cid:
        focus_candidate(key0, study, cid)


def mri_spot(pf: PatientFile, study: dict, key0: str, m: rm.ScanMap, picked: dict | None,
             changes: dict | None) -> None:
    """The Spot panel of an MRI study: the clicked square (and, inside a contour, its
    candidate's story), else the chosen candidate."""
    sp = map_memory(key0).get("spot") or {}
    by_id = {c["id"]: c for c in study["candidates"]}
    if sp.get("kind") == "square":
        sm = m if sp["at"] == m.index else slice_map(
            study["folder"], stamp(study), int(sp["at"]), later_pair_folder(study, changes))
        j = rm.square_at(sm, sp["row"], sp["col"])
        if j is not None:
            square_panel(pf, study, sm, j)
            if sm.cand[j] in by_id:
                st.markdown(f"##### Its candidate: {sm.cand[j]}")
                spot(pf, study, by_id[sm.cand[j]], changes)
            return
    c = by_id.get(sp.get("id")) if sp.get("kind") == "cand" else picked
    if c is not None:
        spot(pf, study, c, changes)
    else:
        st.caption("No candidate was proposed in this study: click a square in the map to open "
                   "it here.")


def square_panel(pf: PatientFile, study: dict, m: rm.ScanMap, j: int) -> None:
    """One square of the map in full: the crops at the copy's own resolution, where it is, why
    it has its colour, how sure, what to check by eye, its curve on the copy and the mark."""
    story = rm.square_story(m, j, study)
    n = story["numbers"]
    r0, c0 = int(m.sq_r[j] * m.square), int(m.sq_c[j] * m.square)  # its top-left pixel
    name = rm.square_name(m, j)  # its centre, as the hover box names it
    st.markdown(f"**Square {name}** · {m.where} · {story['region']}")
    chips(IMPLEMENTED, INFERENCE)
    radius = max(4, int(round(12 / m.pixel_mm)))
    pics = st.container(horizontal=True, gap="small")
    if m.kind == "MR":
        for key, what in (("pre", "pre-contrast"), ("early", "early post-contrast"),
                          ("sub", "subtraction")):
            pics.image(rm.crop(slices(study, key)[m.index], r0, c0, m.square, radius),
                       caption=what, width=150,
                       alt=f"The {what} copy around square {name}, the square outlined")
    else:
        v = m.info["view"]
        pics.image(rm.crop(_mammo(str(Path(study["folder"]) / v["image"])), r0, c0, m.square,
                           radius, scale=4), caption=f"{v['key']}, the square outlined",
                   width=200, alt=f"The {v['key']} view around square {name}")
    st.caption(f"The shipped copy at its own resolution ({m.pixel_mm:g} mm per pixel, enlarged "
               f"without smoothing), {radius * m.pixel_mm:.0f} mm around the square; the "
               "diagnostic originals stay at TCIA.")
    if m.kind == "MR":
        lim = n["limit"]
        where = (f"{rm.side_name(c0 + m.square / 2, m.cols)} · "
                 + (f"about {n['nipple']} mm from the nipple (3D, approximate: the breast's "
                    "most anterior skin point) · " if n["nipple"] >= 0 else "")
                 + (f"{n['skin']} mm from the nearest skin (in-plane) · " if n["skin"] >= 0
                    else "")
                 + (f"{lim} mm in front of the search limit" if lim >= 0 else
                    f"{-lim} mm behind the search limit")
                 + f" · subtraction {n['sub']}% of the study's brightest (its 99.9th "
                   "percentile in the breast region)")
    else:
        where = ((f"about {n['nipple']} mm from the nipple along the view · "
                  if n["nipple"] >= 0 else "") + f"{n['chest']} mm from the chest-wall edge · "
                 f"{n['dense']}% of its breast pixels dense (placeholder rule)")
    st.markdown(f"**Where** · {where}. Geometry on the shipped copy.")
    st.markdown("**Why this colour:** " + "; ".join(story["why"]) + ".")
    st.markdown("**How sure:** " + "; ".join(story["how"]) + ".")
    st.markdown("**What to check by eye:** " + "; ".join(story["check"]) + ".")
    if m.kind == "MR" and "inside" not in story["region"]:
        keys = [k for k in series_keys(study) if k != "sub"]
        vols = [slices(study, k) for k in keys]
        vals = rm.square_curve(vols, m.index, r0, c0, m.square)
        clipped = rm.clipped_share(vols, m.index, r0, c0, m.square)
        df = pd.DataFrame({"phase": [series_label(study, k).split(": ")[-1] for k in keys],
                           "brightness on the 8-bit copy": vals})
        with st.container(width=VIEW_PX):
            st.altair_chart(alt.Chart(df).mark_line(point=True, color="#5C5F6A").encode(
                x=alt.X("phase:N", sort=list(df["phase"]), title=None,
                        axis=alt.Axis(labelAngle=-35)),
                y=alt.Y("brightness on the 8-bit copy:Q", title="brightness (0–255)",
                        scale=alt.Scale(domain=[0, 255])),
                tooltip=["phase:N", alt.Tooltip("brightness on the 8-bit copy:Q", format=".0f")])
                .properties(height=200), width="stretch")
        st.caption("The square's mean brightness on each phase's copy: the curve's shape only, "
                   "not a percentage (every phase shares one window whose lower end is not "
                   f"stored); {clipped:.0%} of its pixels reach 250 on some phase (clipped "
                   "there). Measured kinetics exist inside the contours only.")
    if story["candidate"] in {c["id"] for c in study.get("candidates", [])}:
        st.caption(f"Your mark for this place goes with {story['candidate']}: in its story "
                   "below.")
        return
    at = m.where.split(" of ")[0]
    review(finding_key(pf, "imaging", study["barcode"], study["study"]["date"], f"{at} {name}"),
           f"{study['barcode']} {study['study']['date']} {at}, square {name}: "
           f"{story['region'].lower()} (model inference)")


def report_button(row, pf: PatientFile, study: dict, key0: str, items: list[dict],
                  overview: str, changes: dict | None) -> None:
    """The study's report in Markdown, built when clicked (``rx.report_markdown``)."""
    prefix = f"{pf.id}|imaging|{study['barcode']}|"
    marks = {k: v for k, v in st.session_state.get("reviews", {}).items() if k.startswith(prefix)}
    looked = {x["key"] for x in items}
    squares = [v for k, v in marks.items() if k not in looked and " r" in k.rsplit("|", 1)[-1]]
    mr = study["modality"] == "MR"
    failures = [f for f in rad.KNOWN_FAILURES if ("ammograph" in f) != mr]
    name = f"{pf.id}_{study['barcode']}_{study['study']['date']}_report.md".replace(" ", "_")
    row.download_button(
        "Download the study report (Markdown)",
        lambda: rx.report_markdown(pf.id, study, look=items, marks=marks, overview=overview,
                                   change=changes["change"] if changes else None,
                                   square_marks=squares, known_failures=failures),
        file_name=name, mime="text/markdown", key=f"{key0}-md", on_click="ignore",
        icon=":material/description:",
        help="The study's report, built when you click: what was imaged, the measurements with "
             "their evidence labels, the look-here pointers with your marks, the change over "
             "time, every cutoff and its source, the known failures")


def map_png_button(row, key0: str, study: dict, m: rm.ScanMap, img: np.ndarray,
                   markers: list[dict], title: str, subtitle: str) -> None:
    """The map picture of one view at the shown slice or view, made when clicked."""
    views = rm.modes(m)
    with row.popover("Download the map (PNG)", icon=":material/image:",
                     help="A labelled picture of the map in one view at this slice or view, for "
                          "a report or a tumor board"):
        mode = st.selectbox("View", views, format_func=rm.MODES.get, key=f"{key0}-pngview")
        st.download_button(
            "Download the map (PNG)",
            lambda: rx.map_png(img, m, mode, 0.55, study=study if m.kind == "MR" else None,
                               markers=markers, title=title, subtitle=subtitle,
                               legend=rm.legend_items(m, mode, study)),
            file_name=f"{key0.replace(' ', '_')}_{m.where.split(' of ')[0].replace(' ', '')}_"
                      f"{mode}_map.png", mime="image/png", key=f"{key0}-png",
            on_click="ignore", width="stretch")


def lesion_rows(study: dict) -> list[dict]:
    rows = []
    for c in study["candidates"]:
        k = c["kinetics"]
        rows.append({
            "candidate": c["id"], "side": c["side"],
            "slices (native)": f"{c['slices'][0] + 1}–{c['slices'][1] + 1}",
            "longest diameter (mm)": c["longest_diameter_mm"],
            "craniocaudal extent (mm)": c["cc_extent_mm"], "volume (mL)": c["volume_ml"],
            "volume range (mL)": f"{c['volume_range_ml'][0]:g}–{c['volume_range_ml'][1]:g}",
            "initial": f"{k.get('initial', '?')} ({k.get('initial_pct', '?')}%)",
            "delayed": f"{k.get('delayed', '?')} ({k.get('delayed_pct', '?')}%)",
            "curve type": k.get("curve_type", "?"),
            "contour unsure on": len(c["unsure_slices"]), "evidence": c["evidence"]})
    return rows


def spot(pf: PatientFile, study: dict, c: dict, changes: dict | None = None) -> None:
    st.markdown(f"**{c['id']}** · {c['side']}")
    chips(IMPLEMENTED, INFERENCE, "literature, placeholder until calibrated")
    k, d, seed = c["kinetics"], study["display"], c["seed"]
    plane = c.get("ld_plane", "axial")
    # the words, then the curve and the mark: in a 2-of-5 column the curve's axis and the mark's
    # options were cut at 800 px (QA R3-10)
    a, b = st.container(), st.container()
    with a:
        st.markdown(
            f"**Size** (model inference, from MedSAM's contour): longest diameter "
            f"**{c['longest_diameter_mm']:g} mm** on native {plane} slice {c['ld_slice'] + 1} "
            f"(in the acquisition plane, between pixel centres, ± {c['ld_uncertainty_mm']:g} mm; "
            f"measured on {c.get('ld_from', 'every slice')}); craniocaudal extent "
            f"{c['cc_extent_mm']:g} mm (along the body axis, from the contour); volume "
            f"**{c['volume_ml']:g} mL**, {c['volume_range_ml'][0]:g}–{c['volume_range_ml'][1]:g} "
            "mL with the contour one pixel in or out"
            + (f", {c['volume_sure_ml']:g} mL without the {len(c['unsure_slices'])} unsure "
               "slice(s)" if c["unsure_slices"] and "volume_sure_ml" in c else "")
            + f" (voxels × {d['native_pixel_mm'][0]:g} × {d['native_pixel_mm'][1]:g} × "
            f"{d['slice_mm']:g} mm; the slice thickness is {d['slice_thickness_mm']:g} mm). "
            f"Side: {c['side']}.")
        st.markdown(
            f"**Kinetics** (mean signal inside the contour, per phase): initial "
            f"**{k.get('initial')}** ({k.get('initial_pct')}% over pre-contrast at "
            f"{k['labels'][k['peak_phase']]}), delayed **{k.get('delayed')}** "
            f"({k.get('delayed_pct')}% from that peak to {k['labels'][-1]}): curve type "
            f"{k.get('curve_type')} ({rad.BIRADS}; {rad.KUHL}). Cutoffs: slow below "
            f"{rad.CUTOFFS['initial_slow_below'][0]}%, fast above "
            f"{rad.CUTOFFS['initial_fast_above'][0]}%, plateau within ±"
            f"{rad.CUTOFFS['delayed_band_pct'][0]}%: the literature's usual values, placeholders "
            "until calibrated here. For context, " + KUHL_NUMBERS + ".")
        st.markdown(
            f"**How its box was chosen**: rank {c['rank']} of the seed groups by summed "
            f"subtraction (score {seed['score']:.3g}; {seed['seed_mm3']:g} mm³ of seed voxels, "
            f"mean {seed['mean_sub']:.3g}, peak {seed['peak_sub']:.3g}, elongation "
            f"{seed['elongation']:g}). On every slice where the seed has voxels, its extent plus "
            f"{rad.CUTOFFS['box_pad'][0]:.0%} became MedSAM's box prompt. "
            + ("Contour unsure on native slices "
               + ", ".join(str(z + 1) for z in c["unsure_slices"]) + "."
               if c["unsure_slices"] else "MedSAM returned a contour inside its box on every "
                                          "slice."))
        st.markdown("**Change over time**: " + change_text(study, c, changes))
        m = study.get("medsam", {})
        st.markdown(
            f"**The model**: {rad.MEDSAM}. The paper reports a model developed on 1,570,263 "
            "image-mask pairs from 10 imaging modalities and over 30 cancer types, evaluated on "
            "86 internal and 60 external validation tasks with better accuracy and robustness "
            "than modality-wise specialist models. **Not validated on breast MRI here**; this "
            "checkpoint (uploaded May 2023) may predate the paper's final model. "
            f"{m.get('seconds_per_slice', '?')} CPU seconds per slice here ({m.get('threads')} "
            f"threads; {load(m.get('uptime'))}).")
    with b:
        with st.container(width=VIEW_PX):
            st.altair_chart(kinetics_chart(c), width="stretch")
            st.caption(f"Phase times: {study['phases'][1]['time_source']}.")
        key = finding_key(pf, "imaging", study["barcode"], study["study"]["date"], c["id"])
        review(key, f"{study['barcode']} {study['study']['date']} {c['id']}: "
                    f"{c['longest_diameter_mm']:g} mm, {k.get('delayed')} (model inference)")


def pair_for(pf: PatientFile, study: dict) -> dict | None:
    """The study pair this study belongs to in this file (two dates, aligned), else None."""
    found = [(t, s) for t, s in studies_of(pf) if s]
    for t0, t1, ch, later in rad.pairs_of(found):
        if Path(study["folder"]).name in (t0.details["folder"], t1.details["folder"]):
            return {"change": ch, "earlier": rad.load_study(rad.study_folder(t0)),
                    "later": later}
    return None


def example_pair() -> dict | None:
    """The public example study pair (``radiology_example/``), not any patient's file."""
    loaded = rad.load_pair(rad.EXAMPLE)
    if not loaded:
        return None
    pair, earlier, later = loaded
    return {"change": rad.pair_change(pair, earlier, later), "earlier": earlier, "later": later}


def change_text(study: dict, c: dict, changes: dict | None) -> str:
    """One candidate's change over time for its Spot panel."""
    if not changes:
        return ("one study date on file: no prior, so no change (a second study, aligned, "
                "would show it).")
    later = Path(study["folder"]).name == Path(changes["later"]["folder"]).name
    row = next((r for r in changes["change"]["rows"]
                if r["later" if later else "earlier"] == c["id"]), None)
    if row is None:
        return "not in the pairing of the two dates."
    ch, (d0, d1) = row["change"], changes["change"]["dates"]
    if not ch.get("ld_mm"):
        return (f"{row['lesion']} ({d0} → {d1}): {ch['status']}; the seed rule's top three on "
                "each date need not hold the same lesions.")
    res = row["residual"] or {}
    return (f"{row['lesion']} ({d0} → {d1}): longest diameter {ch['ld_mm'][0]:g} → "
            f"{ch['ld_mm'][1]:g} mm ({ch['ld_change_mm']:+g} mm, {ch['ld_change_pct']:+.0f}%), "
            f"volume {ch['volume_ml'][0]:g} → {ch['volume_ml'][1]:g} mL; **{ch['status']}** "
            f"(model inference; the rules are placeholders). The two contours lie "
            f"{row['distance_mm']:g} mm apart after alignment; "
            + (f"the alignment is unreliable here ({res.get('why')})." if row["reliable"] is False
               else f"the local check finds {res.get('residual_mm', '?')} mm left over here."))


def _blocks(ch: dict, display: dict, plane: str, index: int) -> list[tuple]:
    """The unreliable blocks the view cuts, as rectangles in its pixels."""
    dz, px, _ = rad.shown_spacing(display)
    at = {"axial": index * dz, "coronal": index * px, "sagittal": index * px}[plane]
    axis = {"axial": 0, "coronal": 1, "sagittal": 2}[plane]
    out = []
    for b in ch["blocks"]:
        if b["reliable"] or abs(b["at_mm"][axis] - at) > b["half_mm"]:
            continue
        z, y, x = b["at_mm"]
        h = b["half_mm"]
        if plane == "axial":
            out.append(((x - h) / px, (y - h) / px, (x + h) / px, (y + h) / px))
        else:
            u = y if plane == "sagittal" else x
            top = rad.reslice_row((z + h) / dz, display)
            bottom = rad.reslice_row((z - h) / dz, display)
            out.append(((u - h) / px, top, (u + h) / px, bottom))
    return out


def change_view(pf: PatientFile, changes: dict, key0: str, marks: bool = True) -> None:
    """Two dates side by side at the same position: the later study and the earlier one moved
    onto it by the rigid alignment, the unreliable blocks tinted red, the lesions paired across
    dates with both sizes and the change, the computed sum and the 'what changed' paragraph."""
    ch, earlier, later = changes["change"], changes["earlier"], changes["later"]
    d = later["display"]
    chips(*([EXAMPLE_CHIP] if ch["label"] else []), IMPLEMENTED, INFERENCE, "placeholder")
    if ch["label"]:
        st.info(ch["label"], icon="🧭")
    if ch["protocol"]:
        st.warning("Before any 'larger' or 'smaller', the two studies differ: "
                   + "; ".join(ch["protocol"]) + ".")
    reg = ch["registration"]
    st.markdown(f"**What changed** (model inference): {ch['what_changed']}")
    if not marks:  # the example pair: its later study on the map, the Change view first
        pair_map(changes, key0)
    n_bad = sum(not b["reliable"] for b in ch["blocks"])
    st.caption(f"Method: {reg['method']}. Normalised mutual information {reg['nmi_start']:g} at "
               f"the start, {reg['nmi_after']:g} aligned; {reg['evaluations']} evaluations, "
               f"{reg['seconds']:g} CPU seconds. Local check: "
               f"shifts up to {rad.CUTOFFS['residual_search_mm'][0]} mm (4 mm, then 2 mm "
               "steps); "
               f"{n_bad} of {len(ch['blocks'])} 30 mm blocks of the breasts unreliable "
               f"(more than {rad.CUTOFFS['residual_unreliable_mm'][0]} mm left over, or a best "
               f"correlation under {rad.CUTOFFS['residual_min_ncc'][0]}; placeholders), tinted "
               "red on the views (a toggle hides them). Registration is rigid: it cannot follow "
               "the breast's own deformation between exams.")
    c1, c2, c3 = st.columns([2, 2, 3])
    plane = c1.segmented_control("Plane", ["axial", "coronal", "sagittal"], default="axial",
                                 key=f"{key0}-cmp-plane") or "axial"
    series = c2.segmented_control("Series", ["sub", "early", "pre"],
                                  format_func=lambda k: series_label(later, k).split(":")[0],
                                  default="sub", key=f"{key0}-cmp-series") or "sub"
    cands = later["candidates"]
    focus = c3.segmented_control("Lesion (later date)", [c["id"] for c in cands],
                                 default=cands[0]["id"] if cands else None,
                                 key=f"{key0}-cmp-cand")
    picked = next((c for c in cands if c["id"] == focus), None)
    n = {"axial": d["slices"], "coronal": d["rows"], "sagittal": d["cols"]}[plane]
    start = n // 2
    if picked and picked["centroid_mm"]:
        _, px, _ = rad.shown_spacing(d)
        start = {"axial": _ld_index(later, picked), "coronal": int(picked["centroid_mm"][1] / px),
                 "sagittal": int(picked["centroid_mm"][2] / px)}[plane]
    idx = st.slider(f"{plane.capitalize()} position", 1, n, min(n, start + 1),
                    key=f"{key0}-cmp-{plane}-{focus}") - 1
    img_b = rad.reslice(slices(later, series), plane, idx, d)
    img_a = rad.aligned_view(slices(earlier, series), earlier["display"], d, reg, plane, idx)
    ms_b, ms_a = masks(later), masks(earlier)
    layers_b = [(rad.reslice(ms_b[c["id"]], plane, idx, d, order=0),
                 COLORS.get(c["id"], (255, 255, 0))) for c in cands]
    layers_a = [(rad.aligned_view(ms_a[c["id"]].astype(np.uint8) * 255, earlier["display"], d,
                                  reg, plane, idx) > 127, COLORS.get(c["id"], (255, 255, 0)))
                for c in earlier["candidates"]]
    hatch = _blocks(ch, d, plane, idx) if st.toggle(
        "Show where the alignment is unreliable", True, key=f"{key0}-cmp-blocks") else []
    shown = []
    for img, layers in ((img_b, layers_b), (img_a, layers_a)):
        out = pane(img, [x for x in layers if x[0].any()], [], []).convert("RGBA")
        tint = Image.new("RGBA", out.size, (0, 0, 0, 0))
        draw = ImageDraw.Draw(tint)
        for x0, y0, x1, y1 in hatch:  # a light red tint and a thin edge: the anatomy stays seen
            draw.rectangle([x0 * K, y0 * K, x1 * K, y1 * K], fill=(255, 60, 60, 38),
                           outline=(255, 90, 90, 150), width=1)
        shown.append(Image.alpha_composite(out, tint).convert("RGB"))
    left, right = st.columns(2)
    left.image(shown[0], caption=f"{later['study']['date']} (later), {plane} {idx + 1}: its "
                                 "own candidates", width="stretch")
    right.image(shown[1], caption=f"{earlier['study']['date']} (earlier), moved onto the later "
                                  "study by the rigid alignment: its own candidates",
                width="stretch")
    st.caption("Both views show the same place after alignment; black where the earlier study "
               "has no data. " + rad.anisotropy(d) + ".")
    rows = change_rows(ch)
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    total = ch["sum"]
    st.markdown("**Sum of longest diameters (computed, not a response call)**: " + (
        f"{', '.join(total['targets'])}: {total['sum_mm'][0]:g} → {total['sum_mm'][1]:g} mm "
        f"({total['change_mm']:+g} mm, {total['change_pct']:+.0f}%)"
        + (f"; left out, not proposed on the later date: {', '.join(total['left_out'])}"
           if total.get("left_out") else "") + f". {total['note'].capitalize()}."
        if total.get("sum_mm") else total["note"].capitalize() + "."))
    st.caption(f"Rules (placeholders, borrowed from RECIST 1.1 per candidate): grew when the "
               f"longest diameter rose ≥ {rad.CUTOFFS['grew_pct'][0]}% and ≥ "
               f"{rad.CUTOFFS['grew_mm'][0]} mm, shrank when it fell ≥ "
               f"{rad.CUTOFFS['shrank_pct'][0]}%, both by more than twice the pixel; paired "
               f"within {rad.CUTOFFS['match_mm'][0]} mm after alignment. The sum takes paired "
               f"candidates of ≥ {rad.CUTOFFS['measurable_mm'][0]} mm on the earlier date, at "
               f"most {rad.CUTOFFS['targets_per_organ'][0]} (RECIST 1.1's measurable size and "
               "per-organ limit).")
    if not marks:  # the example pair is not this file's: no mark goes into its export
        st.caption("Review marks: none on the example pair; it is not this patient's data.")
        return
    barcode, span = later["barcode"], f"{ch['dates'][0]} to {ch['dates'][1]}"
    pick = st.selectbox("Mark a lesion's change", [r["lesion"] for r in rows],
                        key=f"{key0}-cmp-mark")
    row = next(r for r in rows if r["lesion"] == pick)
    review(finding_key(pf, "imaging", barcode, span, pick),
           f"{barcode} {span} {pick}: {row['status']} (model inference)")


def pair_map(changes: dict, key0: str) -> None:
    """A pair's later study on the scan map, opened on the Change view around its first
    candidate: its contours against the earlier ones moved by the rigid alignment, where the
    alignment is unreliable tinted; the Slice slider inside walks the slices around. Hover only:
    the pair is not this file's, so no Spot panel and no mark."""
    later = changes["later"]
    d = later["display"]
    folder, stamp_ = later["folder"], stamp(later)
    pair = str(Path(folder).parent)
    first = later["candidates"][0] if later["candidates"] else None
    i = rm.ld_index(later, first) if first else d["slices"] // 2
    lo = max(0, min(i - MAP_WINDOW, d["slices"] - 2 * MAP_WINDOW - 1))
    shown = list(range(lo, min(d["slices"], lo + 2 * MAP_WINDOW + 1)))

    def build():
        vol = slices(later, "early")
        frames = []
        for k in shown:
            mk = slice_map(folder, stamp_, k, pair)
            frames.append(rm.frame_of(mk, rm.scan_jpeg(vol[k]),
                                      {md: rm.overlay_png(mk, md) for md in rm.modes(mk)},
                                      rm.candidate_pointers(later, k)))
        m = frames[shown.index(i)]["m"]
        return rm.figure(frames, {md: rm.legend_items(m, md, later) for md in rm.modes(m)},
                         active_frame=shown.index(i), study=later, active="change",
                         uirevision=f"{key0}-pair", height=rm.height_for(m),
                         total=d["slices"])
    fig, _ = figure_once(("pair", folder, stamp_, i), build)
    st.plotly_chart(fig, key=f"{key0}-pairmap", width="stretch",
                    config={"displayModeBar": False, "scrollZoom": True, "doubleClick": "reset"})
    st.caption(f"The later study ({later['study']['date']}) on the scan map, slices "
               f"{shown[0] + 1}–{shown[-1] + 1}: the Change view colours both dates' model "
               "contours after the rigid alignment (larger now, smaller now, on one date only: "
               "not new, not gone) and tints where the alignment is unreliable. A comparison of "
               "two dates, not a forecast. Hover for the numbers; this pair is another patient's "
               "public data, so it opens no Spot panel and takes no mark.")


def change_rows(ch: dict) -> list[dict]:
    out = []
    for r in ch["rows"]:
        c = r["change"]
        ld, vol = c.get("ld_mm"), c.get("volume_ml")
        res = r["residual"] or {}
        out.append({
            "lesion": r["lesion"], "side": r["side"],
            "longest diameter (mm)": f"{ld[0]:g} → {ld[1]:g}" if ld else "—",
            "change": f"{c['ld_change_mm']:+g} mm ({c['ld_change_pct']:+.0f}%)" if ld else "—",
            "volume (mL)": f"{vol[0]:g} → {vol[1]:g}" if vol else "—",
            "volume ranges overlap": ("yes" if c["volume_overlap"] else "no") if vol else "—",
            "status": c["status"],
            "alignment here": ("unreliable: " + res.get("why", "") if r["reliable"] is False else
                               f"{res['residual_mm']:g} mm left over" if res.get("residual_mm")
                               is not None else "—"),
            "evidence": r["evidence"]})
    return out


def since_last(page: Page, pf: PatientFile, study: dict, changes: dict | None) -> None:
    """Change over time: this patient's two studies aligned, or, with one study date, why
    there is none (and, for an MRI, the change view on a public example pair, loaded only when
    opened)."""
    if changes:
        dates = changes["change"]["dates"]
        with page.details("Since the last study", f"{dates[0]} to {dates[1]}"):
            change_view(pf, changes, f"rad-{pf.id}-{study['barcode']}")
        return
    with page.details("Since the last study", "one study date"):
        chips(IMPLEMENTED)
        st.caption(f"One {study['modality']} study date on file for this patient "
                   f"({study['study']['date']}): no prior to compare with, so no change is "
                   "shown. With a second study the two are aligned, protocol and scanner "
                   "differences are flagged first, and each lesion's change is shown with where "
                   "the alignment is unreliable.")
    example = example_pair()
    if example and study["modality"] == "MR":
        with page.details("Change over time on a public example pair (another TCGA-BRCA "
                          "patient, not this patient)", "2 dates", key=f"rad-{pf.id}-ex-open",
                          lazy=True) as box:
            if box.open:
                change_view(pf, example, f"rad-{pf.id}-example", marks=False)
            else:
                st.caption("Opens the change view on a public pair of studies of another "
                           "patient: what this page shows when a prior exists.")


def _cannot_see(page: Page, rows: list[tuple], note: str | None = None) -> None:
    with page.cannot_see():
        st.dataframe(pd.DataFrame([{"not shown here": w, "why": why, "what can": how}
                                   for w, why, how, _ in rows]), hide_index=True,
                     width="stretch")
        if note:
            st.caption(note)


def model_card(page: Page, study: dict) -> None:
    with page.card():
        m = study.get("medsam")
        rows = [("Training data", "MedSAM: the paper's dataset (1,570,263 image-mask pairs, 10 "
                 "modalities, over 30 cancer types); this study is not in it as far as known"),
                ("Design", f"{rad.MEDSAM}; box prompt; the authors' preprocessing (0.5–99.5 "
                 "percentile window, 1024² cubic resize, [0, 1] scaling), sigmoid > 0.5; input "
                 f"here: {m['input'] if m else 'n/a'} slices" if m else "no model on this study"),
                ("Performance", "as the paper reports, on its own validation tasks; nothing "
                 "measured on breast MRI here"),
                ("External validity", "not checked on this collection, scanner or protocol"),
                ("Calibration", "not applicable (a contour, not a probability)"),
                ("Robustness", "depends on the box: the seed rule's placeholders decide where "
                 "MedSAM looks"),
                ("Uncertainty", "three candidates shown; contours flagged unsure when empty or "
                 "larger than their box; volume shown as a one-pixel range"),
                ("Known failures", " ".join(f for f in rad.KNOWN_FAILURES
                                            if "ammograph" not in f)),
                ("Reproducibility", (f"{rad.pipeline_name(study['pipeline'])}, run "
                                     f"{study['pipeline']['run_at']}; model revision "
                                     f"{m['revision'] if m else 'n/a'}")),
                ("Change over time", f"{rad.REGISTRATION}; a local check by normalised "
                 "cross-correlation (shifts up to 10 mm in a 40 mm cube) marks where the aligned "
                 "studies still differ (unreliable here, placeholder cutoffs); candidates paired "
                 "by position within 15 mm (placeholder); growth and shrinkage by rules borrowed "
                 "from RECIST 1.1 per candidate (placeholders); a sum of diameters computed, never "
                 "a response call. No rule, no model: nothing to validate it against here"),
                ("Multiplanar views", "coronal and sagittal resliced from the shipped axial copy "
                 "(linear, nearest for the contours) at square pixels; " + rad.anisotropy(
                     study["display"])),
                ("Acquisition", f"{study['display'].get('acquisition', {}).get('plane', 'axial')} "
                 "acquisition; MedSAM and the longest diameter run on the acquisition plane, the "
                 "viewer shows the axial frame")]
        st.dataframe(pd.DataFrame(rows, columns=["field", "what it records"]), hide_index=True,
                     width="stretch")
        _cutoffs()


def _cutoffs() -> None:
    n_ph = sum(1 for v in rad.CUTOFFS.values() if v[1] == rad.PLACEHOLDER)
    with st.expander(f"Every radiology cutoff and its source ({n_ph} of {len(rad.CUTOFFS)} "
                     "placeholders)"):
        st.dataframe(pd.DataFrame([{"cutoff": k, "value": str(v), "source": tag, "what": note}
                                   for k, (v, tag, note) in rad.CUTOFFS.items()]),
                     hide_index=True, width="stretch")
        st.caption(f"{n_ph} of {len(rad.CUTOFFS)} cutoffs are placeholders; the kinetics "
                   "cutoffs are literature values used as placeholders until calibrated here.")


DENSITY = {"A": "almost entirely fatty", "B": "scattered fibroglandular density",
           "C": "heterogeneously dense", "D": "extremely dense"}  # the BI-RADS categories


def screening_text(score: dict) -> str:
    """mammoscreen's per-breast score and density, with what they are and are not."""
    if score.get("status") != "implemented":
        return f"**Screening score**: planned ({score.get('why', '')})."
    card = score["card"]
    per = "; ".join(
        f"{'right' if side == 'R' else 'left'} breast {b['cancer']:.2g} (density "
        f"{b['density_class']}, {DENSITY[b['density_class']]}, "
        f"{b['density'][b['density_class']]:.0%})" for side, b in score["breasts"].items())
    return (f"**Screening score** (model inference: mammoscreen, {score['license']}, revision "
            f"{score['revision'][:7]}; CC and MLO per breast): {per}. An uncalibrated model "
            "output, not a probability for this population; on its own held-out data the card "
            "puts 98%, 94% and 91% sensitivity at "
            + ", ".join(f"{v:g}" for v in card["thresholds"].values())
            + f" and reports AUROC {card['auroc']}. The structured report records a biopsy-proven "
            "cancer (BI-RADS 6) without its side, so the score cannot be checked against the "
            "record here and adds nothing to a known diagnosis. Not validated here; "
            f"{score['how']}; {score['seconds_inference']:.0f} CPU seconds ({score['threads']} "
            f"threads; {load(score.get('uptime'))}).")


def view_density(study: dict, view: dict) -> str:
    """MONAI's density class for one view, for its tooltip and the CSV."""
    d = study.get("density_monai", {}).get("views", {}).get(view["key"])
    return (f"{d['density_class']} ({DENSITY[d['density_class']]}; model inference, not "
            "validated here)" if d else "planned")


def monai_text(d: dict, score: dict) -> str:
    """MONAI's per-view density, whether it agrees with mammoscreen's per breast, and what the
    model is and is not."""
    if d.get("status") != "implemented":
        return f"**Second density opinion**: planned ({d.get('why', 'not run')})."
    views = d["views"]
    per = "; ".join(f"{k} {v['density_class']}" for k, v in sorted(views.items()))
    sides = []
    for side, b in score.get("breasts", {}).items():
        theirs = {v["density_class"] for k, v in views.items() if k.startswith(f"{side}-")}
        sides.append(f"{'right' if side == 'R' else 'left'} breast: "
                     + ("both say " + b["density_class"] if theirs == {b["density_class"]} else
                        f"mammoscreen {b['density_class']}, MONAI {', '.join(sorted(theirs))}"))
    return (f"**Second density opinion** (model inference: MONAI breast density "
            f"classification, {d['license']}, revision {d['revision'][:7]}; "
            f"{d['card']['training']}): {per}. Against mammoscreen: "
            + ("; ".join(sides) or "no mammoscreen result to compare")
            + f". Its metadata states accuracy {d['card']['accuracy']} and calls it "
            f"{d['card']['intended_use']}. Not validated here; {d['how']}; "
            f"{d['seconds']:.0f} CPU seconds. Two models agreeing is not a validation.")


def breast_score(study: dict, view: dict) -> str:
    """The screening score of the breast a view shows, for its tooltip."""
    b = study["screening_score"].get("breasts", {}).get(view["laterality"])
    return (f"{b['cancer']:.2g} for this breast, density {b['density_class']} (model inference, "
            "not validated here)" if b else "planned")


NO_DETECTOR = ("Lesion candidates on mammograms: none shown. No open, permissively licensed "
               "mammography lesion detector with published weights that runs on the CPU was found "
               "(the registry's mammography models give a score per breast (mammoscreen), a "
               "density (MONAI) or a risk (Mirai); detectors trained on VinDr-Mammo carry its "
               "restricted licence, and the open detectors found on 2026-10-21 publish code "
               "without licensed weights). The density opinions stay.")


@st.cache_resource(show_spinner=False, max_entries=16)
def _mammo(path: str) -> np.ndarray:
    return np.asarray(Image.open(path).convert("L"))


def mammo_geometry(page: Page, pf: PatientFile, study: dict, views: list[dict], key0: str,
                   level: int, width: int) -> list[dict]:
    """Left-right asymmetry (the dense-pixel share per view and a map, placeholder rule) and
    the CC and MLO views of one breast zoomed on the same band behind the nipple, as two
    details sections."""
    imgs = {(v["laterality"], v["view"]): _mammo(str(Path(study["folder"]) / v["image"]))
            for v in views}
    asym = rad.asymmetry(views)
    with page.details("Left and right", f"{sum(a['asymmetric'] for a in asym)} of "
                                        f"{len(asym)} view pairs asymmetric"):
        chips(IMPLEMENTED, INFERENCE, "placeholder")
        st.markdown("**Left-right difference in dense-pixel share** (model inference, "
                    "placeholder rule): " + ("; ".join(
                        f"{a['view']}: right {a['right']:.0%}, left {a['left']:.0%}, "
                        f"{a['difference_points']:+g} points"
                        + (" (asymmetric by the placeholder rule)" if a["asymmetric"] else "")
                        for a in asym) or "needs both breasts' views")
                    + (f". Rule: {asym[0]['rule']}; a pixel share, not a BI-RADS asymmetry "
                       "finding." if asym else "."))
        pairs = [v for v in ("CC", "MLO") if ("R", v) in imgs and ("L", v) in imgs]
        if pairs:
            view = st.segmented_control("Map of", pairs, default=pairs[0],
                                        key=f"{key0}-asym") or pairs[0]
            m = rad.asymmetry_map(imgs[("R", view)], imgs[("L", view)])
            rgb = np.full((*m["map"].shape, 3), 40, np.uint8)
            rgb[m["map"] > 0] = (230, 73, 72)
            rgb[m["map"] < 0] = (64, 160, 230)
            st.image(Image.fromarray(rgb).resize((m["map"].shape[1] * 2,
                                                  m["map"].shape[0] * 2), Image.NEAREST),
                     width=240, alt=f"Map of the {view} views: red where only the right "
                                    f"breast is dense ({m['right_only']:.0%}), blue where only "
                                    f"the left is ({m['left_only']:.0%})")
            st.caption(f"{view} views, each breast cropped to its outline with the chest wall on "
                       "the left, mirrored onto one grid: red = dense on the right breast only "
                       f"({m['right_only']:.0%} of the grid), blue = dense on the left only "
                       f"({m['left_only']:.0%}). {m['rule'].capitalize()}; it ignores "
                       "compression, positioning and breast size.")
    sides = [s for s in ("R", "L") if (s, "CC") in imgs and (s, "MLO") in imgs]
    with page.details("CC and MLO, linked", f"{len(sides)} breast"
                                            f"{'' if len(sides) == 1 else 's'}"):
        chips(IMPLEMENTED, "placeholder")
        _cc_mlo(imgs, views, sides, key0, level, width)
    return asym


def _cc_mlo(imgs: dict, views: list[dict], sides: list[str], key0: str, level: int,
            width: int) -> None:
    if not sides:
        st.caption("Needs a breast's CC and MLO views.")
        return
    c1, c2 = st.columns([1, 3])
    side = c1.segmented_control("Breast", sides, default=sides[0], key=f"{key0}-zoom-side",
                                format_func={"R": "right", "L": "left"}.get) or sides[0]
    px = next(v["pixel_mm"] for v in views if v["laterality"] == side)
    outs = {v: rad.breast_outline(imgs[(side, v)]) for v in ("CC", "MLO")}
    if any(o["nipple"] is None for o in outs.values()):
        st.caption("No breast outline found on one of the views: nothing to link.")
        return
    reach = min(abs(o["nipple"][0] - (0 if o["chest"] == "left" else o["mask"].shape[1]))
                for o in outs.values()) * px
    depth = c2.slider("Distance behind the nipple (mm)", 0, max(10, int(reach)),
                      min(40, int(reach) // 2), key=f"{key0}-zoom-depth")
    half = 10
    cols = st.columns(2)
    for col, v in zip(cols, ("CC", "MLO"), strict=True):
        o, img = outs[v], window(imgs[(side, v)], level, width)
        x0, x1 = rad.nipple_band(o, depth, half, px)
        x0, x1 = max(0, x0), min(img.shape[1], x1)
        full = Image.fromarray(img).convert("RGB")
        draw = ImageDraw.Draw(full)
        draw.rectangle([x0, 0, x1, img.shape[0] - 1], outline=(235, 160, 52), width=2)
        nx, ny = o["nipple"]
        draw.ellipse([nx - 4, ny - 4, nx + 4, ny + 4], outline=(80, 200, 120), width=2)
        band = Image.fromarray(img[:, x0:max(x1, x0 + 1)]).resize(
            ((max(x1, x0 + 1) - x0) * 3, img.shape[0] * 3 // 2), Image.BILINEAR)
        with col:
            st.image(full, caption=f"{side}-{v}: the band {depth - half}–{depth + half} mm "
                                   "behind the nipple (green)", width=260,
                     alt=f"The {side}-{v} mammogram with a band {depth - half} to "
                         f"{depth + half} mm behind the nipple outlined")
            st.image(band, caption=f"{side}-{v}, the band enlarged", width=140,
                     alt=f"The band of the {side}-{v} view, enlarged")
    st.caption("A lesion's distance from the nipple is about the same on the CC and the MLO "
               "view, so the same band is shown on both: a finding on one view is looked for "
               "in that band on the other. The nipple is the breast's point farthest from the "
               "chest-wall edge and the distance is measured along the image rows (on the MLO "
               "view it runs at an angle to the pectoral muscle): geometry for looking, not a "
               "registration of the two views.")


def mammo_map(pf: PatientFile, study: dict, key0: str, views: list[dict],
              found: dict | None) -> tuple:
    """The mammography map: one view at a time (View, Whole image, window and level above it),
    the Density view, its line and the search spots under it. Returns (view key, level,
    window, the view's map)."""
    ss, mem = st.session_state, map_memory(key0)
    keys = [v["key"] for v in views]
    if ss.get(f"{key0}-view") not in keys:
        ss[f"{key0}-view"] = keys[0]
    row = st.container(horizontal=True, vertical_alignment="bottom", gap="small")
    vk = row.segmented_control("View", keys, key=f"{key0}-view", required=True,
                               help="Right and left, CC and MLO: one view under the map at a "
                                    "time; the four side by side are in Details") or keys[0]
    row.button("Whole image", key=f"{key0}-fit", icon=":material/fit_screen:",
               on_click=reset_view, args=(key0,),
               help="Shows the whole view again and clears the outline")
    with row.popover("Window and level", icon=":material/contrast:",
                     help="Brightness and contrast of the image under the colours"):
        level = st.slider("Level", 0, 255, 128, key=f"{key0}-level")
        width = st.slider("Window", 1, 255, 255, key=f"{key0}-width")
        st.caption("Window and level act on the shipped 8-bit copy.")
    m = view_map(study["folder"], stamp(study), vk)
    v = m.info["view"]
    img = window(_mammo(str(Path(study["folder"]) / v["image"])), level, width)
    values = rs.values_for(found, m) if found and mem.get("match_on") else None
    markers = map_markers(study, m, found, [])[:MAX_MARKERS]
    view_modes = ("match",) if values is not None else tuple(rm.modes(m))
    sel = outline_index(mem, m)
    shape = (m.key, level, width, view_modes, sel, tuple(mem["zoom"] or ()), mem["zoom_rev"],
             key0, found["query"] if found else None,
             tuple((p["r"], p["c"], p["label"]) for p in markers))

    def build():
        overlays = {md: rm.overlay_png(m, md, values) for md in view_modes}
        legends = {md: rm.legend_items(m, md, study) for md in overlays}
        return rm.figure([rm.frame_of(m, rm.scan_jpeg(img), overlays, markers, sel)], legends,
                         opacity=rm.MATCH_OPACITY if values is not None else rm.OPACITY,
                         zoom=mem["zoom"], uirevision=f"{key0}-{mem['zoom_rev']}",
                         height=rm.height_for(m))
    fig, first = figure_once(shape, build)
    event = st.plotly_chart(fig, key=f"{key0}-map", on_select="rerun", selection_mode="points",
                            width="stretch", config={"displayModeBar": False, "scrollZoom": True,
                                                     "doubleClick": "reset"})
    handle_map_click(event, key0, m, first, study)
    map_line(m, f"{v['key']} ({'right' if v['laterality'] == 'R' else 'left'} breast, "
                f"{v['view']} view)")
    st.caption(f"Shown at {v['pixel_mm']:g} mm per pixel, downsampled from the "
               f"{v['native_pixel_mm'][0]:g} mm original: microcalcifications are not visible at "
               f"this size. Density view: the dense pixels (an Otsu threshold inside the breast on "
               f"the shipped copy: {m.info['dense_share']:.0%} here, "
               f"{v['dense']['dense_fraction']:.0%} on the original; a placeholder rule, not a "
               "BI-RADS density category), coloured by MONAI's density class for this view "
               f"({view_density(study, v)}). " + NO_DETECTOR)
    if found and found.get("spots"):
        search_spots(key0, study, found)
    return vk, level, width, m


def mammo_spot(pf: PatientFile, study: dict, key0: str, m: rm.ScanMap) -> None:
    """The Spot panel of a mammography study: the clicked square, else the shown view with its
    dense-pixel share, density opinions and the view's mark."""
    sp = map_memory(key0).get("spot") or {}
    if sp.get("kind") == "square":
        sm = m if sp["at"] == m.where else view_map(study["folder"], stamp(study), sp["at"])
        j = rm.square_at(sm, sp["row"], sp["col"])
        if j is not None:
            square_panel(pf, study, sm, j)
            return
    v = m.info["view"]
    st.markdown(f"**{v['key']}** · dense-pixel share {v['dense']['dense_fraction']:.0%} "
                "(placeholder rule; on MLO views the pectoral muscle counts as dense) · MONAI "
                f"density {view_density(study, v)} · screening score {breast_score(study, v)}")
    review(finding_key(pf, "imaging", study["barcode"], study["study"]["date"], v["key"]),
           f"{study['barcode']} {v['key']}: dense-pixel share "
           f"{v['dense']['dense_fraction']:.0%} (placeholder rule)")
    st.caption("Click a square in the map to open it here.")


def mammo_page(page: Page, pf: PatientFile, study: dict) -> None:
    rep = study.get("report", {})
    key0 = f"rad-{pf.id}-{study['barcode']}"
    st.markdown(f"**{study['kind']} · {study['study']['date']}**")
    st.caption(provenance(study))
    items = look_items(pf, page.version, f"{study['barcode']}|")
    overview = (
        f"**Observed** (the study's structured report): {rep.get('procedure', '')}; BI-RADS "
        f"{rep.get('birads', 'not stated')}; pathology {rep.get('pathology', 'not stated')}; "
        f"{receptors(rep)}.  \n"
        f"**Model inference** (placeholder rule): dense-pixel share "
        f"{study['dense_cc_mean']:.0%} on the CC views; a pixel share above an Otsu "
        "threshold inside the breast, not a BI-RADS density category and not validated.  \n"
        + screening_text(study["screening_score"]) + "  \n"
        + monai_text(study.get("density_monai", {}), study["screening_score"])
        + " " + NO_DETECTOR)
    with page.overview():
        st.markdown(overview)
        page.look_here(items, empty="Nothing flagged: no lesion detector runs on the mammograms "
                                    "here.")
        found = scan_search(pf, study, key0, None)
    order = {"R-CC": 0, "L-CC": 1, "R-MLO": 2, "L-MLO": 3}
    views = sorted(study["views"], key=lambda v: order.get(v["key"], 9))
    with page.picture("Scan map", caption=MAP_CAPTION_MG):
        chips(IMPLEMENTED, INFERENCE, "placeholder")
        vk, level, width, m = mammo_map(pf, study, key0, views, found)
    with page.details("The four views side by side", len(views)):
        line = st.container(horizontal=True, gap="small")  # left and right; wraps when narrow
        for v in views:
            line.image(window(_mammo(str(Path(study["folder"]) / v["image"])), level, width),
                       caption=f"{v['key']} · dense-pixel share "
                               f"{v['dense']['dense_fraction']:.0%} (placeholder rule)",
                       width=170, alt=f"The {v['laterality']} {v['view']} mammogram")
        st.caption("The same window and level as the map; pick a view in the map to work on it. "
                   "On MLO views the pectoral muscle counts as dense.")
    asym = mammo_geometry(page, pf, study, views, key0, level, width)
    with page.spot("The full story of one square or one view: click a square in the map."):
        mammo_spot(pf, study, key0, m)
    with page.card():
        score = study["screening_score"]
        if score.get("status") == "implemented":
            card = score["card"]
            st.markdown("**mammoscreen** (screening score and density per breast)")
            st.dataframe(pd.DataFrame([
                ("Training data", card["training"]),
                ("Design", "an ensemble of three EfficientNetV2-S nets (2048×1024, 1920×1280, "
                           "1536×1536), CC and MLO averaged per breast; outputs a cancer score "
                           "and BI-RADS density A–D"),
                ("Performance", f"the card's: AUROC {card['auroc']}; nothing measured here"),
                ("External validity", "not checked on this collection or this vendor"),
                ("Calibration", "none: the score is not a probability for this population"),
                ("Robustness", score["how"]),
                ("Uncertainty", "per-net cancer scores: " + "; ".join(
                    f"{s} {', '.join(f'{c:.2g}' for c in b['cancer_per_net'])}"
                    for s, b in score["breasts"].items())),
                ("Known failures", "one study only, a known cancer (BI-RADS 6) without its side "
                                   "in the record: nothing to check the score against"),
                ("Reproducibility", f"{score['model']} revision {score['revision']}; "
                                    f"{score['seconds_inference']:.0f} CPU seconds, "
                                    f"{score['threads']} threads; {load(score.get('uptime'))}"),
            ], columns=["field", "what it records"]), hide_index=True, width="stretch")
        else:
            st.markdown(screening_text(score))
        st.caption("The dense-pixel share is a placeholder rule (an Otsu threshold inside the "
                   "breast), not a model: nothing to validate it against here.")
        _cutoffs()
    _cannot_see(page, rad.CANNOT_SEE)
    v = m.info["view"]
    img = window(_mammo(str(Path(study["folder"]) / v["image"])), level, width)

    def more(row) -> None:
        report_button(row, pf, study, key0, items, overview.replace("  \n", "\n\n"), None)
        map_png_button(row, key0, study, m, img, [],
                       title=f"{study['barcode']} · {study['study']['date']} · {vk}",
                       subtitle="Dense pixels (placeholder rule) and MONAI's density class: "
                                "model inferences")
    _export(page, pf, study, [{"view": v["key"], "dense-pixel share": v["dense"]["dense_fraction"],
                               "dense rule": "placeholder", "screening score (breast)":
                               breast_score(study, v), "MONAI density (view)":
                               view_density(study, v), "evidence": INFERENCE} for v in views],
            {"left_right": asym, "lesion_detector": NO_DETECTOR}, more=more)


def _search(pf: PatientFile, reads: list[dict], cannot: list[tuple]) -> None:
    """The report page's search: reads, sites and months in the reports' words (a study page
    searches inside its scan instead, ``scan_search``)."""
    q = st.text_input("Search this test in plain words", key=f"rad-search-{pf.id}-reports",
                      placeholder=search_placeholder(None))
    if q:
        hit = rad.search(q, reads, [], cannot)
        (st.markdown if hit["understood"] else st.warning)(hit["answer"])
        if hit["reads"]:
            st.dataframe(pd.DataFrame(read_rows(hit["reads"])), hide_index=True, width="stretch")


def _export(page: Page, pf: PatientFile, study: dict | None, table: list[dict],
            extra: dict | None = None, change: list[dict] | None = None, more=None):
    """The page's downloads; ``more(row)`` adds the study's report and the map picture."""
    with page.export():
        marks = {k: v for k, v in st.session_state.get("reviews", {}).items()
                 if k.startswith(f"{pf.id}|imaging|")}
        body = {"file": pf.id, "exported": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "evidence": "candidates, contours and measurements: model inference; report "
                            "facts and reads: observed",
                "placeholders": [k for k, v in rad.CUTOFFS.items() if v[1] != rad.DESIGN],
                "review_marks": marks, **(extra or {})}
        if study:
            body["study"] = {k: v for k, v in study.items() if k != "folder"}
        name = (f"{pf.id}_{study['barcode']}_{study['study']['date']}" if study else
                f"{pf.id}_imaging_reports").replace(" ", "_")
        e = st.container(horizontal=True, gap="small")  # labels whole, wraps
        if more is not None:
            more(e)
        e.download_button("Download the study (JSON)" if study else "Download the reads (JSON)",
                          json.dumps(body, indent=1, default=str),
                          file_name=f"{name}.json", mime="application/json",
                          key=f"rad-json-{name}")
        e.download_button("Download the lesion table (CSV)",
                          pd.DataFrame(table).to_csv(index=False),
                          file_name=f"{name}_lesions.csv", mime="text/csv",
                          key=f"rad-csv-{name}")
        if change:
            e.download_button("Download the change table (CSV)",
                              pd.DataFrame(change).to_csv(index=False),
                              file_name=f"{name}_change.csv", mime="text/csv",
                              key=f"rad-chg-{name}")


# --- the report-driven page -----------------------------------------------------------------------
def read_rows(reads: list[dict]) -> list[dict]:
    return [{"month": r["month"], "source": r["source"], "read": r["read"],
             "the words": r["words"], "new sites": ", ".join(r["new_sites"]) or "none named",
             "measurements": r["measurements"], "evidence": r["evidence"], "report": r["text"]}
            for r in reads]


def report_card(page: Page) -> None:
    """The report-reading rule's card: what it reads, how it was checked, where it fails."""
    with page.card():
        st.markdown(f"**Imaging report reading** · rules, no model  \n**Method:** "
                    f"{rad.REPORT_METHOD}.  \n**Measurements:** {rad.NO_MEASUREMENTS}.  \n"
                    "**Validation:** tested on sample sentences by the platform's automated "
                    "tests, not validated on a set of real reports: the report itself is the "
                    "record, and every read shows its own words.  \n**Known failures:** a site "
                    "named in a sentence the rule does not parse is missed; the words win over "
                    "the record's sites field, and a disagreement between them is flagged, "
                    "never resolved.")
        _cutoffs()


def imported_read(pf: PatientFile, r: dict) -> None:
    """For a read an import brought in: what the intake rule read, and what it set aside."""
    t = next((t for t in pf.tests if t.kind == "Imaging" and t.month == r["month"]
              and "read" in t.details), None)
    if t is not None:
        from workbenches import imports  # the import's own reading of the report

        imports.read_details(t.details)


def report_page(page: Page, pf: PatientFile, version: int | None) -> None:
    """The file's imaging reports as text: the synthetic record's and any imported ones, never
    another file's (``muffle.workbench.radiology.file_events``), in the page skeleton."""
    events = rad.file_events(pf, version)
    hidden = len(rad.file_events(pf)) - len(events)
    reads = rad.imaging_reads(events)
    synthetic = pf.kind == "synthetic"
    page.title(IMPLEMENTED, OBSERVED, *(["synthetic patient"] if synthetic else []),
               colors={"synthetic patient": "orange"})
    if synthetic:
        st.warning("Synthetic patient: this record was written by hand and is not a real person. "
                   "Its imaging reports exist to show how the workbench reads them.")
    st.caption("Data: this file's imaging reports (text, observed; an imported report as its "
               f"import read it); no images are on file. Method: {rad.REPORT_METHOD}. "
               f"Measurements: {rad.NO_MEASUREMENTS}. Status: implemented.")
    if hidden:
        st.caption(f"As of month {pf.versions[version].month} ({pf.versions[version].label}): "
                   f"{hidden} later events hidden.")
    picked = st.session_state.get(f"picked-{pf.id}")
    if not reads:
        with page.overview():
            st.info("No imaging read in the record up to this version. An imaging report (text "
                    "or PDF, through Import tests) would be read here.", icon="🩻")
        report_card(page)
        _cannot_see(page, rad.REPORT_CANNOT_SEE)
        with page.export(empty="Nothing to export: no imaging read up to this version."):
            pass
        return
    lag = rad.lead_lag(events, reads)
    prog = [r for r in reads if r["read"] == rad.PROGRESSION]
    new = [(s, r["month"]) for r in reads for s in r["new_sites"]]
    rise = next((x for x in lag if x["progression"] and "rising" in x["flag"]), None)
    table = rad.lesion_table(reads)
    months = [r["month"] for r in reads]
    rows = [{"site": t["site"], "first named": f"month {t['first_named']}",
             **{f"month {m}": t["cells"][m] for m in months},
             "measurements": t["measurements"]} for t in table]
    progressed = ", ".join(str(r["month"]) for r in prog) or "none"
    named_new = ", ".join(f"{s.lower()} (month {m})" for s, m in new) or "none"
    with page.overview():
        st.markdown(
            f"**Observed.** {len(reads)} imaging reads from month {reads[0]['month']} to "
            f"{reads[-1]['month']}; read as progression at month"
            f"{'s' if len(prog) != 1 else ''} {progressed}; new sites named: {named_new}. "
            f"Latest: {reads[-1]['read']} at month {reads[-1]['month']} ({reads[-1]['source']}). "
            f"The reports record no lesion size: {rad.NO_MEASUREMENTS}."
            + (f" {rise['what'][0].upper() + rise['what'][1:]} (an observed order of events in "
               "this record, not a validated lead time)." if rise else ""))
        page.look_here(look_items(pf, page.version, "report|"),
                       land=lambda focus: land(pf, page.version, focus))
        _search(pf, reads, rad.REPORT_CANNOT_SEE)

    with page.picture("Imaging reports", caption="Each read in the report's own words, newest "
                      "first; the one opened from the tests table or an alert is open."):
        chips(IMPLEMENTED, OBSERVED)
        for r in reversed(reads):
            title = (f"Imaging report, month {r['month']}" if r["kind"] == "Imaging" else
                     f"{r['kind']} note, month {r['month']}")
            opened = bool(picked) and picked[0] == "Imaging" and picked[1] == r["month"]
            with st.expander(f"{title}: {r['read']}", expanded=opened):
                st.markdown(f"**{title}** · read: **{r['read']}** (\"{r['words']}\") · new "
                            f"sites: {', '.join(r['new_sites']) or 'none named'} · "
                            f"measurements: {r['measurements']} · evidence: {r['evidence']}  \n"
                            f"> {r['text']}")
                if not r["agrees"]:
                    st.warning("The report's words and the record's sites field disagree: "
                               f"words {r['new_sites']}, field {r['recorded_sites']}.")
                imported_read(pf, r)
                review(finding_key(pf, "imaging", "report", r["month"], "read"),
                       f"{title}: read {r['read']}")

    with page.details("Lesion table", f"{len(table)} site{'' if len(table) == 1 else 's'}"):
        chips(IMPLEMENTED, OBSERVED)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
        st.caption("One row per site a report names; a cell says what that read says about the "
                   "site. A read that does not name a site is not a statement about it: "
                   "\"not named; overall read: stable\" is never \"stable\" for that site. Pick a "
                   "site in the Spot panel below.")
    with page.details("Change between reads", f"{len(months)} reads"):
        chips(IMPLEMENTED, OBSERVED)
        if len(months) > 1:
            c1, c2 = st.columns(2)
            m0 = c1.selectbox("Earlier read", months[:-1], index=len(months) - 2,
                              format_func=lambda m: f"month {m}", key=f"rad-chg0-{pf.id}")
            later = [m for m in months if m > m0]
            m1 = c2.selectbox("Later read", later, index=len(later) - 1,
                              format_func=lambda m: f"month {m}", key=f"rad-chg1-{pf.id}")
            change = rad.report_change(reads, m0, m1)
            st.markdown(f"**What changed** (observed: the reports' own words): "
                        f"{change['what_changed']}")
            if change["rows"]:
                st.dataframe(pd.DataFrame([{k: r[k] for k in ("lesion", "earlier", "later",
                                                              "change", "measurements")}
                                           for r in change["rows"]]), hide_index=True,
                             width="stretch")
            st.caption("The image workbench's change view where only text exists: each named "
                       "site on the two reads, no size and so no change in size and no sum of "
                       f"diameters ({change['sum']['note']}).")
        else:
            st.caption("One imaging read in the record up to this version: nothing to compare.")
    example = example_pair()
    if example:
        with page.details("What the change view shows with images: a public example pair "
                          "(a TCGA-BRCA patient, not this patient)", "2 dates",
                          key=f"rad-{pf.id}-ex-open", lazy=True) as box:
            if box.open:
                change_view(pf, example, f"rad-{pf.id}-example", marks=False)
            else:
                st.caption("Opens the change view on a public pair of studies of another "
                           "patient: what this page shows when images exist.")
    with page.details("Against the tumor marker", len(lag)):
        chips(IMPLEMENTED, OBSERVED)
        st.caption("Each read against the last CA 15-3 result before it (the labs workbench's "
                   "rule): the observed order of events in this record, not a validated lead "
                   "time.")
        st.markdown("\n".join(f"- {x['pointer'] + ': ' if x['pointer'] else ''}{x['what']}"
                              for x in lag) or "No marker result before a read.")

    with page.spot("The full story of one named site: where it was first named, what each later "
                   "read says about it, its alert and your mark."):
        if table:
            if st.session_state.get(f"rad-site-{pf.id}") not in [t["site"] for t in table]:
                st.session_state[f"rad-site-{pf.id}"] = table[-1]["site"]
            site = st.segmented_control("Site", [t["site"] for t in table],
                                        key=f"rad-site-{pf.id}")
            t = next((t for t in table if t["site"] == site), None)
            if t:
                named = [r for r in reads if r["month"] in t["named_in"]]
                alerts = [a.what for v in pf.versions for a in v.alerts
                          if a.what.lower().endswith(t["site"].lower())]
                st.markdown(
                    f"**{t['site']}**: first named at month {t['first_named']} ("
                    + "; ".join(f"\"{r['text']}\"" for r in named) + "). Later reads: "
                    + "; ".join(f"month {m}: {c}" for m, c in t["cells"].items()
                                if m > t["first_named"]) + ". "
                    + (f"The report's SOS alert: {'; '.join(alerts)}. " if alerts else "")
                    + f"Size and count: {rad.NO_MEASUREMENTS}; measuring them needs the images.")
                review(finding_key(pf, "imaging", "report", t["first_named"], t["site"]),
                       f"{t['site']} first named at month {t['first_named']}")
        else:
            st.caption("No site is named in the reads up to this version.")

    report_card(page)
    _cannot_see(page, rad.REPORT_CANNOT_SEE, "No images are in this file, so no contour, size or "
                "kinetics exists for these lesions. The image viewer runs on public TCGA-BRCA "
                "studies: open a TCGA case file with an imaging test.")
    _export(page, pf, None, rows, {"reads": read_rows(reads), "lead_lag": lag})


# --- the Methods and validation page's cards ---------------------------------------------------
def methods_card() -> None:
    """The radiology workbench's models and rules for the Methods and validation page
    (app/methods_page.py): MedSAM, mammoscreen, and the report-reading, seed and kinetics rules
    with every cutoff and its source."""
    def head(title: str, what: str) -> None:
        st.subheader(title)
        st.markdown(f"{chip(IMPLEMENTED)} · {what}")

    head("Lesion contours (MedSAM, breast MRI)", "promptable contours from a seed rule's boxes, "
         "precomputed offline · the radiology workbench")
    st.markdown(
        f"- **Design:** {rad.MEDSAM}; a box prompt per slice from the seed rule, the authors' "
        "preprocessing, sigmoid above 0.5; longest diameter, volume and DCE kinetics are "
        "measured on its contours.\n"
        "- **Published validation:** the paper's own tasks (1,570,263 image-mask pairs, 10 "
        "modalities, 86 internal and 60 external validation tasks). **Not validated on breast "
        "MRI here**: no reader contour exists for these studies.\n"
        "- **Data:** the held-out TCGA cases with a public TCIA study (CC BY 3.0) and a public "
        "example pair of two dates; the hosted app reads 8-bit copies and derived numbers and "
        "runs no model. Axial, sagittal or coronal acquisitions: MedSAM runs on the "
        "acquisition plane.")
    head("Change over time (rigid alignment, breast MRI)", "two dates side by side at the same "
         "position, lesions paired, precomputed offline · the radiology workbench")
    st.markdown(
        f"- **Design:** {rad.REGISTRATION}. A local check (normalised cross-correlation, shifts "
        f"up to {rad.CUTOFFS['residual_search_mm'][0]} mm in a 40 mm cube) at each candidate and "
        "on 30 mm blocks says where the aligned studies still differ: unreliable here above "
        f"{rad.CUTOFFS['residual_unreliable_mm'][0]} mm (placeholder). Candidates pair by "
        f"position within {rad.CUTOFFS['match_mm'][0]} mm (placeholder); growth and shrinkage "
        "use RECIST 1.1's sum rules borrowed per candidate (placeholders); a sum of longest "
        "diameters is computed, never a response call. Protocol differences are listed first.\n"
        "- **Published validation:** none for this use; tested on synthetic shifted and rotated "
        "volumes (the project's automated tests). Shown on one public example pair, which "
        "is not a patient file here.")
    head("Multiplanar views and cine (breast MRI)", "axial, coronal and sagittal with linked "
         "positions; every phase at a slice · the radiology workbench")
    st.markdown(
        "- **Design:** coronal and sagittal resliced from the shipped axial copy at square pixels "
        "(linear; nearest for the contours, which are the axial contours stacked), with the voxel "
        "shape said under the views; the craniocaudal extent and the longest-diameter slice "
        "carried over as marks; a cine through every shipped phase.\n"
        "- **Limits:** detail along the slice direction is interpolated, not seen.")
    head("Mammography geometry (left-right, CC and MLO)", "a dense-pixel difference and a "
         "linked band behind the nipple · the radiology workbench")
    st.markdown(
        "- **Design:** the left-right difference in dense-pixel share per view (placeholder: "
        f"more than {rad.CUTOFFS['asymmetry_points'][0]} points) and a map of outline-normalised, "
        "mirrored breasts; the CC and MLO views of a breast zoomed on the same distance behind "
        "the nipple. Geometry, not a reading; not a BI-RADS asymmetry finding.\n"
        f"- **Lesion detector:** none. {NO_DETECTOR}")
    head("Breast density, second opinion (MONAI, mammography)", "BI-RADS density A–D per "
         "view, precomputed offline · the radiology workbench")
    st.markdown(
        "- **Design:** InceptionV3 fine-tuned on Mayo Clinic mammograms (Gupta et al., "
        "arXiv:2202.08238, preprint); MONAI's bundle network re-built from torchvision with the "
        "pinned weights (Apache-2.0); the whole view at 299×299, a sigmoid per class.\n"
        "- **Published validation:** the bundle's metadata states accuracy 0.96 without "
        "describing its test set and calls the model an example, not for diagnostic use. Not "
        "validated here; shown next to mammoscreen's density, which is not a validation either.")
    head("Screening score (mammoscreen, mammography)", "cancer score and BI-RADS density per "
         "breast, precomputed offline · the radiology workbench")
    st.markdown(
        "- **Design:** three EfficientNetV2-S nets on the CC and MLO views of a breast "
        "(Apache-2.0), re-built from the published code with the pinned weights, so no remote "
        "code runs; crops from a threshold mask, not the authors' crop model.\n"
        "- **Published validation:** the model card's AUROC 0.945 on held-out splits of the "
        "RSNA 2023 screening data; uncalibrated, not validated here, and the one study is a "
        "known cancer whose report does not record the side.")
    c = rad.CUTOFFS
    n = sum(1 for _, tag, _ in c.values() if tag == rad.PLACEHOLDER)
    head("Radiology: report reading, seed and kinetics rules", "reads in the report's words, "
         "where to look, curve types · the radiology workbench")
    st.markdown(
        f"Imaging reports are read in their own words ({chip(OBSERVED)}): the read, the sites "
        "named new, a lesion table across reads, and no measurement where none is recorded. On "
        "images, the seed rule proposes boxes from the subtraction inside the breast region and "
        "kinetics follow the BI-RADS MRI lexicon's curve types (Kuhl et al. 1999). "
        f"**{n} of {len(c)} cutoffs are placeholders**; the kinetics cutoffs are literature "
        "values used as placeholders until calibrated. Known failures: "
        + " ".join(rad.KNOWN_FAILURES) + " Method: docs/radiology.md.")
    with st.expander("Every radiology cutoff and its source"):
        st.dataframe(pd.DataFrame([{"cutoff": k, "value": str(v), "source": tag, "note": note}
                                   for k, (v, tag, note) in c.items()]),
                     hide_index=True, width="stretch")


# --- entry point ----------------------------------------------------------------------------------
def render(pf: PatientFile, version: int | None = None, test=None) -> None:
    """The radiology workbench for one patient file, in the current container (no page config,
    no sidebar), in the shared page skeleton (``workbenches._page``). ``version``: an index
    into ``pf.versions``; the report-driven page shows the reads up to that version's month.
    ``test`` is the test it was opened from, for the title."""
    page = Page("radiology", pf, test, version)
    found = studies_of(pf)
    if not found:
        if any(t.workbench == "imaging" for t in pf.tests):
            report_page(page, pf, version)
        else:
            page.title(IMPLEMENTED)
            with page.overview():
                st.info("No imaging in this file. An imaging report (text or PDF, brought in "
                        "through Import tests) or a processed scan series would open this "
                        "workbench.", icon="🩻")
            report_card(page)
            _cannot_see(page, rad.REPORT_CANNOT_SEE)
            with page.export(empty="Nothing to export: this file holds no imaging."):
                pass
        return
    kept = [(t, s) for t, s in found if s is not None]
    mr = any(s["modality"] == "MR" for _, s in kept)
    page.title(IMPLEMENTED, OBSERVED, INFERENCE, "placeholder",
               *(["literature, placeholder until calibrated"] if mr else []))
    for t, _ in [(t, s) for t, s in found if s is None]:
        st.warning(f"{t.name}: the processed study is not installed on this server, so its "
                   "images and measurements can't be shown.")
    if not kept:
        with page.overview():
            st.info("The file's imaging studies are not installed on this server: nothing to "
                    "show. The study's processed images and contours would open this "
                    "workbench.", icon="🩻")
        report_card(page)
        _cannot_see(page, rad.CANNOT_SEE)
        with page.export(empty="Nothing to export: no study is installed."):
            pass
        return
    names = [t.name for t, _ in kept]
    pick = st.segmented_control("Study", names, default=names[0], key=f"rad-study-{pf.id}") \
        if len(names) > 1 else names[0]
    study = kept[names.index(pick or names[0])][1]
    (mri_page if study["modality"] == "MR" else mammo_page)(page, pf, study)
    st.caption("Research and decision support for clinicians; not a diagnosis or a "
               "prescription. Treatment questions belong to the clinician; nothing here is a "
               "recommendation.")


if __name__ == "__main__":
    from types import SimpleNamespace

    from muffle.workspace import case_file, synthetic_file

    st.set_page_config(page_title="Radiology workbench", layout="wide")
    st.text_input("Reviewer initials", key="reviewer", max_chars=5)  # the shell's field
    tl = json.loads((APP / "timeline_synthetic.json").read_text(encoding="utf-8"))
    files = {"SYNTHETIC-001": synthetic_file(tl)}
    for index, studies in rad.load_index(RESULTS).items():  # stand-ins for the bundle's cases
        case = SimpleNamespace(index=index, mutations=None, layers=["clinical"], missing=[],
                               stage=None, age=None, percentile=50.0, group="intermediate",
                               site="(not loaded on this page)")
        files[f"Case {index}"] = case_file(case, None, imaging=studies)
    if rad.example_studies():  # the public example pair as a file of its own, here only
        case = SimpleNamespace(index=0, mutations=None, layers=["clinical"], missing=[],
                               stage=None, age=None, percentile=50.0, group="intermediate",
                               site="(public example pair)")
        pf = case_file(case, None, imaging=rad.example_studies())
        for t in pf.tests:
            if t.workbench == "imaging":
                t.details["root"] = "example"
        files["Public example pair (not a patient file)"] = pf
    render(files[st.selectbox("File", list(files))])

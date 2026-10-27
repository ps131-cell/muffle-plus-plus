"""Radiology workbench for a patient file (docs/WORKSPACE.md, "Radiology"; docs/WORKBENCHES.md
§6; method and limits in docs/radiology.md).

streamlit run app/workbenches/radiology.py        # standalone: every file with imaging

The workspace pages call ``render(pf, version=None, test=None)`` with a
``muffle.workspace.PatientFile``; it draws inside the current container only, in the shared page
skeleton (``workbenches._page``: overview with the look-here queue and search, the picture,
counted details, the Spot panel, the card, what the test cannot see, export). Two pages in one:

* **Image viewer**, for a file whose imaging tests carry a TCIA barcode (a TCGA patient with a
  processed public study, ``radiology_results/``): series and slice, window and level, the model's
  contours, boxes and measurements as overlays with hover stats per region, a Spot panel per
  candidate lesion (size, volume, the kinetics curve, how its box was chosen, the model and its
  published validation), prior comparison where two study dates exist, what the images cannot
  show, the model and validation card, search, review marks and exports. Mammograms: the four
  views with a dense-pixel share (placeholder rule).
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

import base64
import hashlib
import io
import json
import sys
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


def uri(img: Image.Image) -> str:
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()


def overlay(img: np.ndarray, cands: list[dict], i: int, mask: bool, view: tuple) -> Image.Image:
    """The view (x0, y0, width, height in shown pixels, and the drawing scale) of the slice,
    enlarged, with each candidate's contour filled and outlined when ``mask`` is on."""
    x0, y0, vw, vh, k = view
    base = Image.fromarray(img[y0:y0 + vh, x0:x0 + vw]).resize(
        (int(vw * k), int(vh * k)), Image.BILINEAR).convert("RGBA")
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    for c in cands if mask else []:
        s = c["per_slice"].get(str(i))
        if not s:
            continue
        col = COLORS.get(c["id"], (255, 255, 0))
        for poly in s["contours"]:
            pts = [((x - x0) * k, (y - y0) * k) for x, y in poly]
            if len(pts) > 2:
                draw.polygon(pts, fill=(*col, 90))
                draw.line(pts + [pts[0]], fill=(*col, 255), width=2)
    return Image.alpha_composite(base, layer).convert("RGB")


def view_of(study: dict, c: dict | None, i: int, zoom: bool) -> tuple:
    """The whole shown slice at ``ZOOM`` (narrower when that would pass ``VIEW_PX``), or a
    square around candidate ``c`` (its box on this slice, else on its longest-diameter slice)
    drawn four times larger. The image and its outlines share one scale, so they stay aligned."""
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


def viewer_chart(img: Image.Image, cands: list[dict], i: int, show_box: bool, show_ld: bool,
                 view: tuple) -> alt.Chart:
    """The view as an image mark, with a hover rectangle per candidate (its stats) and the
    longest-diameter line on this slice."""
    x0, y0, vw, vh, k = view
    x = alt.X("x:Q", scale=alt.Scale(domain=[x0, x0 + vw], nice=False), axis=None)
    y = alt.Y("y:Q", scale=alt.Scale(domain=[y0, y0 + vh], nice=False, reverse=True), axis=None)
    layers = [alt.Chart(pd.DataFrame([{"x": x0, "y": y0, "url": uri(img)}])).mark_image(
        width=vw * k, height=vh * k, align="left", baseline="top", tooltip=None).encode(
        x=x, y=y, url="url:N")]
    boxes, lines = [], []
    for c in cands:
        s = c["per_slice"].get(str(i))
        if not s:
            continue
        kin = c["kinetics"]
        boxes.append({"x": s["box"][0], "y": s["box"][1], "x2": s["box"][2], "y2": s["box"][3],
                      "candidate": c["id"], "side": c["side"] or "",
                      "this slice": f"longest diameter {s['ld_mm']:g} mm, area "
                                    f"{s['area_mm2']:g} mm²"
                                    + (" · contour unsure here" if s["unsure"] else ""),
                      "lesion": f"{c['longest_diameter_mm']:g} mm longest, {c['volume_ml']:g} mL "
                                f"({c['volume_range_ml'][0]:g}–{c['volume_range_ml'][1]:g})",
                      "kinetics": f"{kin.get('initial', '?')} initial "
                                  f"({kin.get('initial_pct', '?')}%), {kin.get('delayed', '?')} "
                                  f"delayed ({kin.get('delayed_pct', '?')}%)",
                      "evidence": INFERENCE, "color": HEX.get(c["id"], "#ffff00")})
        if show_ld and len(s["ld_line"]) == 2:
            (x0, y0), (x1, y1) = s["ld_line"]
            lines.append({"x": x0, "y": y0, "x2": x1, "y2": y1, "candidate": c["id"],
                          "longest diameter": f"{s['ld_mm']:g} mm on this slice (between pixel "
                                              "centres; ± one pixel)"})
    tip = ["candidate:N", "side:N", "this slice:N", "lesion:N", "kinetics:N", "evidence:N"]
    if boxes:
        df = pd.DataFrame(boxes)
        layers.append(alt.Chart(df).mark_rect(
            fillOpacity=0.01, fill="white", strokeWidth=1.5 if show_box else 0,
            strokeOpacity=1 if show_box else 0, strokeDash=[4, 3], clip=True).encode(
            x=x, y=y, x2="x2:Q", y2="y2:Q", stroke=alt.Stroke("color:N", scale=None),
            tooltip=tip))
    if lines:
        layers.append(alt.Chart(pd.DataFrame(lines)).mark_rule(
            color="#ffff66", strokeWidth=2, clip=True).encode(
            x=x, y=y, x2="x2:Q", y2="y2:Q", tooltip=["candidate:N", "longest diameter:N"]))
    # autosize "pad", no padding: the plot is exactly the image, so the boxes and the measure
    # line sit on the contours (Streamlit's default "fit" shrank the plot under the image)
    return alt.layer(*layers).properties(width=vw * k, height=vh * k, padding=0,
                                        autosize=alt.AutoSizeParams(type="pad")).configure_view(
        strokeWidth=0)


def kinetics_chart(c: dict) -> alt.Chart:
    k = c["kinetics"]
    df = pd.DataFrame({"phase": k["labels"], "order": range(len(k["labels"])),
                       "enhancement (% over pre-contrast)": k["relative"]})
    line = alt.Chart(df).mark_line(point=True, color=HEX.get(c["id"], "#888")).encode(
        x=alt.X("phase:N", sort=list(df["phase"]), title=None),
        y=alt.Y("enhancement (% over pre-contrast):Q"),
        tooltip=["phase:N", "enhancement (% over pre-contrast):Q"])
    rules = alt.Chart(pd.DataFrame({"y": [rad.CUTOFFS["initial_slow_below"][0],
                                          rad.CUTOFFS["initial_fast_above"][0]],
                                    "cutoff": ["slow below (placeholder)",
                                               "fast above (placeholder)"]})).mark_rule(
        strokeDash=[4, 4], color="#eb6834").encode(y="y:Q", tooltip=["cutoff:N", "y:Q"])
    return (rules + line).properties(height=220)


@st.cache_resource(show_spinner=False, max_entries=16)  # 3-4.5 MB each (see _strip)
def _mask(folder: str, cid: str, shape: tuple) -> np.ndarray:
    study = rad.load_study(folder)
    return rad.candidate_mask(next(c for c in study["candidates"] if c["id"] == cid), shape)


def masks(study: dict) -> dict[str, np.ndarray]:
    """Each candidate's contour as a mask on the shipped grid, for the views other than axial."""
    d = study["display"]
    return {c["id"]: _mask(study["folder"], c["id"], (d["slices"], d["rows"], d["cols"]))
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
    d, cands = study["display"], study["candidates"]
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
    with page.overview():
        st.markdown(obs + "  \n" + inf)
        st.caption("The candidates are where the subtraction is brightest, not a reading of the "
                   "study: compare them with the structured report and the images.")
        page.look_here(look_items(pf, page.version, f"{study['barcode']}|"),
                       land=lambda focus: land(pf, page.version, focus))
        _search(pf, study, [], cands, rad.CANNOT_SEE)

    # the picture: the viewer
    with page.picture("Viewer"):
        chips(IMPLEMENTED, INFERENCE)
        pick = st.segmented_control("Series", series_keys(study),
                                    format_func=lambda k: series_label(study, k), default="sub",
                                    key=f"{key0}-phase") or "sub"
        if cands and st.session_state.get(f"{key0}-cand") not in [c["id"] for c in cands]:
            st.session_state[f"{key0}-cand"] = cands[0]["id"]  # a landed pointer keeps its own
        focus = st.segmented_control("Candidate", [c["id"] for c in cands], key=f"{key0}-cand",
                                     on_change=_jump, args=(study, key0)) if cands else None
        picked = next((c for c in cands if c["id"] == focus), None)
        if f"{key0}-slice" not in st.session_state:
            st.session_state[f"{key0}-slice"] = _ld_index(study, picked) + 1 if picked else \
                d["slices"] // 2 + 1
        # the image keeps its drawn size; the controls sit beside it where they fit, else under
        # it (fixed columns let a 460 px image cover the controls at 1280 px with the sidebar)
        row = st.container(horizontal=True, gap="small")
        left, right = row.container(width="content"), row.container(width=260)
        with right:
            i = st.slider("Slice", 1, d["slices"], key=f"{key0}-slice") - 1
            st.caption(f"Slice {i + 1} of {d['slices']} (every {d['slice_step']} of "
                       f"{d['native_slices']} native slices), position {d['z_mm'][i]:g} mm; "
                       f"{d['pixel_mm']:g} mm per shown pixel (native "
                       f"{d['native_pixel_mm'][0]:g} mm, slices {d['slice_mm']:g} mm apart). "
                       f"{d['orientation'].capitalize()}."
                       + (f" Acquired {acq['plane']}: {acq['slices']} slices "
                          f"{acq['slice_mm']:g} mm apart, {acq['pixel_mm'][0]:g} mm pixels; the "
                          "axial view is resampled from them."
                          if (acq := d.get("acquisition", {})).get("plane", "axial") != "axial"
                          else ""))
            level = st.slider("Level", 0, 255, 128, key=f"{key0}-level")
            width = st.slider("Window", 1, 255, 255, key=f"{key0}-width")
            t1 = t2 = t3 = t4 = st.container(horizontal=True, gap="small")  # labels whole
            show_mask = t1.toggle("Mask", True, key=f"{key0}-mask")
            show_box = t2.toggle("Box", True, key=f"{key0}-box")
            show_ld = t3.toggle("Measure", True, key=f"{key0}-ld")
            zoom = t4.toggle("Zoom", False, key=f"{key0}-zoom",
                             help="A square around the chosen candidate, four times larger")
            st.caption("Window and level act on the shipped 8-bit copy: " + d["window"] + ". "
                       + d.get("crop", "") + ". Hover a box for its region's stats. "
                       "Re-segmenting with a moved box needs the local pipeline; the hosted app "
                       "runs no model.")
            here = [c["id"] for c in cands if str(i) in c["per_slice"]]
            st.markdown("**On this slice:** " + (", ".join(here) if here else "no candidate"))
        with left:
            img = window(slices(study, pick)[i], level, width)
            view = view_of(study, picked, i, zoom)
            st.altair_chart(viewer_chart(overlay(img, cands, i, show_mask, view), cands, i,
                                         show_box, show_ld, view), width="content",
                            alt=f"{series_label(study, pick)}, slice {i + 1} of {d['slices']}"
                                + (f", candidates {', '.join(here)} outlined" if here else ""))

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
                f"{study['phases'][1]['time_source']}. The same window and level as the viewer; "
                "the contour is the early phase's.")
        else:
            st.caption("Opens the phases one after another at the viewer's slice.")
    table = lesion_rows(study)
    with page.details("Candidates", len(cands)):
        chips(IMPLEMENTED, INFERENCE, "placeholder")
        st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
        st.caption(f"Seed rule ({rad.CUTOFFS['seed_percentile'][1]}): {seed['rule']}. "
                   f"{seed['groups']} seed groups, {seed['proposed']} kept after the size and "
                   "shape rules; the top three are shown. The breast region: "
                   + study["region"]["rule"] + f" (posterior limit at row "
                   f"{study['region']['limit_row_display']:g} of the shown slice). Lesions "
                   "behind it, at the chest wall or in the axilla, are not proposed.")
    since_last(page, pf, study, changes)

    # Spot panel: the chosen candidate in full
    with page.spot("The full story of one candidate: its size, volume, kinetics curve, how its "
                   "box was chosen and the model; pick it with Candidate in the viewer."):
        if picked:
            spot(pf, study, picked, changes)
        else:
            st.caption("No candidate was proposed in this study: nothing to open.")

    model_card(page, study)
    _cannot_see(page, rad.CANNOT_SEE)
    ch = changes["change"] if changes else None
    _export(page, pf, study, table, {"change": {k: ch[k] for k in (
        "rows", "sum", "protocol", "registration", "what_changed", "dates", "label")}} if ch else
        None, change_rows(ch) if ch else None)


def _ld_index(study: dict, c: dict) -> int:
    """The shown slice closest to the candidate's longest-diameter slice (an axial
    acquisition), else the shown slice where its contour is largest."""
    step = study["display"]["slice_step"]
    shown = [int(k) for k in c["per_slice"]]
    if not shown:
        return study["display"]["slices"] // 2
    if c.get("ld_plane", "axial") != "axial":
        return max(shown, key=lambda k: c["per_slice"][str(k)]["area_mm2"])
    return min(shown, key=lambda k: abs(k * step - (c["ld_slice"] or 0)))


def _jump(study: dict, key0: str) -> None:
    c = next((c for c in study["candidates"] if c["id"] == st.session_state.get(f"{key0}-cand")),
             None)
    if c:  # all three planes go to the candidate: its slice, and its box's centre
        i = _ld_index(study, c)
        st.session_state[f"{key0}-slice"] = i + 1
        box = c["per_slice"].get(str(i), {}).get("box")
        if box:
            st.session_state[f"{key0}-row"] = int((box[1] + box[3]) / 2) + 1
            st.session_state[f"{key0}-col"] = int((box[0] + box[2]) / 2) + 1


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
    a, b = st.columns([3, 2])
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
            f"threads; {m.get('uptime', '')}).")
    with b:
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
            f"threads; {score['uptime'].split('load average:')[-1].strip()} load).")


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


def mammo_page(page: Page, pf: PatientFile, study: dict) -> None:
    rep = study.get("report", {})
    key0 = f"rad-{pf.id}-{study['barcode']}"
    st.markdown(f"**{study['kind']} · {study['study']['date']}**")
    st.caption(provenance(study))
    with page.overview():
        st.markdown(
            f"**Observed** (the study's structured report): {rep.get('procedure', '')}; BI-RADS "
            f"{rep.get('birads', 'not stated')}; pathology {rep.get('pathology', 'not stated')}; "
            f"{receptors(rep)}.  \n"
            f"**Model inference** (placeholder rule): dense-pixel share "
            f"{study['dense_cc_mean']:.0%} on the CC views; a pixel share above an Otsu "
            "threshold inside the breast, not a BI-RADS density category and not validated.  \n"
            + screening_text(study["screening_score"]) + "  \n"
            + monai_text(study.get("density_monai", {}), study["screening_score"])
            + " " + NO_DETECTOR)
        page.look_here(look_items(pf, page.version, f"{study['barcode']}|"),
                       empty="Nothing flagged: no lesion detector runs on the mammograms here.")
        _search(pf, study, [], [], rad.CANNOT_SEE)
    order = {"R-CC": 0, "L-CC": 1, "R-MLO": 2, "L-MLO": 3}
    views = sorted(study["views"], key=lambda v: order.get(v["key"], 9))
    with page.picture("Mammograms", caption="Shown at 0.46 mm per pixel, downsampled from the "
                      "0.07 mm original: microcalcifications are not visible at this size. Hover "
                      "a view for its dense-pixel share, screening score and density."):
        level = st.slider("Level", 0, 255, 128, key=f"{key0}-level")
        width = st.slider("Window", 1, 255, 255, key=f"{key0}-width")
        for row in (views[:2], views[2:]):
            line = st.container(horizontal=True, gap="medium")  # left and right; wraps when narrow
            for v in row:
                col = line.container(width="content")
                img = np.asarray(Image.open(Path(study["folder"]) / v["image"]).convert("L"))
                h, w = img.shape
                dense = v["dense"]
                chart = alt.layer(
                    alt.Chart(pd.DataFrame([{"x": 0, "y": 0, "url": uri(Image.fromarray(
                        window(img, level, width)))}])).mark_image(
                        width=w * 0.75, height=h * 0.75, align="left", baseline="top",
                        tooltip=None).encode(
                        x=alt.X("x:Q", scale=alt.Scale(domain=[0, w], nice=False), axis=None),
                        y=alt.Y("y:Q", scale=alt.Scale(domain=[0, h], nice=False,
                                                       reverse=True), axis=None),
                        url="url:N"),
                    alt.Chart(pd.DataFrame([{
                        "x": 0, "y": 0, "x2": w, "y2": h, "view": v["key"],
                        "dense-pixel share": f"{dense['dense_fraction']:.0%} (placeholder rule)",
                        "screening score": breast_score(study, v),
                        "MONAI density": view_density(study, v),
                        "pixel": f"{v['pixel_mm']:g} mm shown, native "
                                 f"{v['native_pixel_mm'][0]:g} mm"}])).mark_rect(
                        fillOpacity=0.01, fill="white").encode(
                        x="x:Q", y="y:Q", x2="x2:Q", y2="y2:Q",
                        tooltip=["view:N", "dense-pixel share:N", "screening score:N",
                                 "MONAI density:N", "pixel:N"])
                ).properties(width=w * 0.75, height=h * 0.75).configure_view(strokeWidth=0)
                with col:
                    st.altair_chart(chart, width="content",
                                    alt=f"The {v['laterality']} {v['view']} mammogram")
                    st.caption(f"{v['laterality']} {v['view']} · dense-pixel share "
                               f"{dense['dense_fraction']:.0%} (placeholder rule; on MLO views "
                               "the pectoral muscle counts as dense)")
                    review(finding_key(pf, "imaging", study["barcode"],
                                       study["study"]["date"], v["key"]),
                           f"{study['barcode']} {v['key']}: dense-pixel share "
                           f"{dense['dense_fraction']:.0%} (placeholder rule)")
    asym = mammo_geometry(page, pf, study, views, key0, level, width)
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
                                    f"{score['threads']} threads; {score['uptime']}"),
            ], columns=["field", "what it records"]), hide_index=True, width="stretch")
        else:
            st.markdown(screening_text(score))
        st.caption("The dense-pixel share is a placeholder rule (an Otsu threshold inside the "
                   "breast), not a model: nothing to validate it against here.")
        _cutoffs()
    _cannot_see(page, rad.CANNOT_SEE)
    _export(page, pf, study, [{"view": v["key"], "dense-pixel share": v["dense"]["dense_fraction"],
                               "dense rule": "placeholder", "screening score (breast)":
                               breast_score(study, v), "MONAI density (view)":
                               view_density(study, v), "evidence": INFERENCE} for v in views],
            {"left_right": asym, "lesion_detector": NO_DETECTOR})


def _search(pf: PatientFile, study: dict | None, reads: list[dict], cands: list[dict],
            cannot: list[tuple]) -> None:
    q = st.text_input("Search this test in plain words",
                      key=f"rad-search-{pf.id}-{study['barcode'] if study else 'reports'}",
                      placeholder="washout · largest · C2 · mutation" if study else
                                  "liver · progression · month 12 · lesion size")
    if q:
        hit = rad.search(q, reads, cands, cannot)
        (st.markdown if hit["understood"] else st.warning)(hit["answer"])
        if hit["lesions"]:
            st.dataframe(pd.DataFrame([r for r in lesion_rows(study)
                                       if r["candidate"] in {c["id"] for c in hit["lesions"]}]),
                         hide_index=True, width="stretch")
        if hit["reads"]:
            st.dataframe(pd.DataFrame(read_rows(hit["reads"])), hide_index=True, width="stretch")


def _export(page: Page, pf: PatientFile, study: dict | None, table: list[dict],
            extra: dict | None = None, change: list[dict] | None = None):
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
        _search(pf, None, reads, [], rad.REPORT_CANNOT_SEE)

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

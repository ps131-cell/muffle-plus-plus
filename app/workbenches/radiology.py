"""Radiology workbench for a patient file (docs/WORKSPACE.md, "Radiology"; docs/WORKBENCHES.md
§6; method and limits in docs/radiology.md).

streamlit run app/workbenches/radiology.py        # standalone: every file with imaging

The workspace pages call ``render(pf, version=None)`` with a ``muffle.workspace.PatientFile``; it
draws inside the current container only. Two pages in one:

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

import altair as alt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

from muffle.report.case_tools import INFERENCE, OBSERVED  # noqa: E402
from muffle.timeline import EVENTS  # noqa: E402
from muffle.workbench import radiology as rad  # noqa: E402
from muffle.workbench.grammar import CANNOT_SEE, CARD, EXPORT, chip  # noqa: E402
from muffle.workspace import IMPLEMENTED, MARKS, PLANNED, PatientFile, finding_key  # noqa: E402

RESULTS = APP / "workbenches" / "radiology_results"
COLORS = {"C1": (230, 73, 72), "C2": (235, 160, 52), "C3": (64, 160, 230)}
HEX = {k: "#%02x%02x%02x" % v for k, v in COLORS.items()}
ZOOM = 2  # shipped slices are at most 256 px; drawn at twice that
NO_MARK = "no mark"
PHASE_NAMES = {"pre": "Pre-contrast", "early": "Early post-contrast", "late": "Delayed",
               "sub": "Subtraction (early − pre)"}
KUHL_NUMBERS = ("in Kuhl et al. 1999 (266 lesions), type III curves were seen in 57% of cancers "
                "and 6% of benign lesions, type I in 9% and 83%: evidence about curve types, not "
                "a diagnosis of this lesion")


def chips(*labels: str) -> None:
    """The shared badges (``muffle.workbench.grammar``); a placeholder is always orange."""
    st.caption(" ".join(chip(label, "orange" if label == "synthetic patient" else None)
                        for label in labels))


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
    c1, c2 = st.columns([3, 1])
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
@st.cache_resource(show_spinner=False)  # read-only arrays: no copy per rerun
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
    """The whole shown slice at ``ZOOM``, or a square around candidate ``c`` (its box on this
    slice, else on its longest-diameter slice) drawn four times larger."""
    d = study["display"]
    w, h = d["cols"], d["rows"]
    if not zoom or c is None or not c["per_slice"]:
        return 0, 0, w, h, ZOOM
    s = c["per_slice"].get(str(i)) or c["per_slice"][str(_ld_index(study, c))]
    side = min(64, w, h)
    cx, cy = (s["box"][0] + s["box"][2]) / 2, (s["box"][1] + s["box"][3]) / 2
    x0 = int(min(max(cx - side / 2, 0), w - side))
    y0 = int(min(max(cy - side / 2, 0), h - side))
    return x0, y0, side, side, w * ZOOM / side  # the same drawn width as the whole slice


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
    return alt.layer(*layers).properties(width=vw * k, height=vh * k).configure_view(
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


# --- the image viewer -----------------------------------------------------------------------------
def studies_of(pf: PatientFile) -> list[tuple]:
    return [(t, rad.load_study(RESULTS / t.details["folder"])) for t in pf.tests
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
            f"{study['pipeline']['script']} version {study['pipeline']['version']} "
            f"({study['pipeline']['run_at']})" + (
                f"; contours by MedSAM ViT-B ({study['medsam']['model']}, revision "
                f"{study['medsam']['revision'][:7]})" if "medsam" in study else "")
            + ". Status: implemented, not validated here.")


def mri_page(pf: PatientFile, study: dict) -> None:
    d, cands = study["display"], study["candidates"]
    rep = study.get("report", {})
    key0 = f"rad-{pf.id}-{study['barcode']}"
    st.markdown(f"#### {study['kind']} · {study['study']['date']}")
    chips(IMPLEMENTED, OBSERVED, INFERENCE, "placeholder",
          "literature, placeholder until calibrated")
    st.caption(provenance(study))

    # overview: observed, inferred, what to check
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
    look = look_here(study)
    st.markdown(obs + "  \n" + inf + "  \n**Check by eye**: " + (
        "; ".join(f"{q['candidate']}: {q['why']}" for q in look) or "nothing flagged") + ".")
    st.caption("The candidates are where the subtraction is brightest, not a reading of the "
               "study: compare them with the structured report and the images.")

    # viewer
    st.markdown("#### Viewer")
    chips(IMPLEMENTED, INFERENCE)
    phases = ["pre", "early", "late", "sub"]
    labels = {"pre": PHASE_NAMES["pre"], "early": f"{PHASE_NAMES['early']}: "
                                                  f"{study['phases'][1]['label']}",
              "late": f"{PHASE_NAMES['late']}: {study['phases'][-1]['label']}",
              "sub": PHASE_NAMES["sub"]}
    pick = st.segmented_control("Series", phases, format_func=labels.get, default="sub",
                                key=f"{key0}-phase") or "sub"
    focus = st.segmented_control("Candidate", [c["id"] for c in cands], default=cands[0]["id"]
                                 if cands else None, key=f"{key0}-cand",
                                 on_change=_jump, args=(study, key0)) if cands else None
    picked = next((c for c in cands if c["id"] == focus), None)
    if f"{key0}-slice" not in st.session_state:
        st.session_state[f"{key0}-slice"] = _ld_index(study, picked) + 1 if picked else \
            d["slices"] // 2 + 1
    left, right = st.columns([3, 2])
    with right:
        i = st.slider("Slice", 1, d["slices"], key=f"{key0}-slice") - 1
        st.caption(f"Slice {i + 1} of {d['slices']} (every {d['slice_step']} of "
                   f"{d['native_slices']} native slices), position {d['z_mm'][i]:g} mm; "
                   f"{d['pixel_mm']:g} mm per shown pixel (native {d['native_pixel_mm'][0]:g} mm, "
                   f"slices {d['slice_mm']:g} mm apart). {d['orientation'].capitalize()}.")
        level = st.slider("Level", 0, 255, 128, key=f"{key0}-level")
        width = st.slider("Window", 1, 255, 255, key=f"{key0}-width")
        t1, t2, t3, t4 = st.columns(4)
        show_mask = t1.toggle("Mask", True, key=f"{key0}-mask")
        show_box = t2.toggle("Box", True, key=f"{key0}-box")
        show_ld = t3.toggle("Measure", True, key=f"{key0}-ld")
        zoom = t4.toggle("Zoom", False, key=f"{key0}-zoom",
                         help="A square around the chosen candidate, four times larger")
        st.caption("Window and level act on the shipped 8-bit copy: " + d["window"] + ". "
                   + d.get("crop", "") + ". Hover a box for its region's stats. Re-segmenting "
                   "with a moved box needs the local pipeline (scripts/radiology_pipeline.py); "
                   "the hosted app runs no model.")
        here = [c["id"] for c in cands if str(i) in c["per_slice"]]
        st.markdown("**On this slice:** " + (", ".join(here) if here else "no candidate"))
    with left:
        img = window(slices(study, pick)[i], level, width)
        view = view_of(study, picked, i, zoom)
        st.altair_chart(viewer_chart(overlay(img, cands, i, show_mask, view), cands, i, show_box,
                                     show_ld, view), width="content")

    # spot panel
    for c in cands:
        if c["id"] == focus:
            spot(pf, study, c)

    # all candidates
    st.markdown("#### Candidates")
    chips(IMPLEMENTED, INFERENCE, "placeholder")
    table = lesion_rows(study)
    st.dataframe(pd.DataFrame(table), hide_index=True, width="stretch")
    st.caption(f"Seed rule ({rad.CUTOFFS['seed_percentile'][1]}): {seed['rule']}. "
               f"{seed['groups']} seed groups, {seed['proposed']} kept after the size and shape "
               "rules; the top three are shown. The breast region: " + study["region"]["rule"]
               + f" (posterior limit at row {study['region']['limit_row_display']:g} of the "
               "shown slice). Lesions behind it, at the chest wall or in the axilla, are not "
               "proposed.")

    prior(study, pf)
    _cannot_see(rad.CANNOT_SEE)
    model_card(study)
    _search(pf, study, [], cands, rad.CANNOT_SEE)
    _export(pf, study, table)


def _ld_index(study: dict, c: dict) -> int:
    """The shown slice closest to the candidate's longest-diameter slice."""
    step = study["display"]["slice_step"]
    shown = [int(k) for k in c["per_slice"]]
    if not shown:
        return study["display"]["slices"] // 2
    return min(shown, key=lambda k: abs(k * step - (c["ld_slice"] or 0)))


def _jump(study: dict, key0: str) -> None:
    c = next((c for c in study["candidates"] if c["id"] == st.session_state.get(f"{key0}-cand")),
             None)
    if c:
        st.session_state[f"{key0}-slice"] = _ld_index(study, c) + 1


def look_here(study: dict) -> list[dict]:
    """What to check by eye, per candidate, with the reason."""
    out = []
    for c in study["candidates"]:
        if c["unsure_slices"]:
            out.append({"candidate": c["id"], "why": f"contour unsure on {len(c['unsure_slices'])}"
                        " slice(s) (empty, or larger than its box)"})
        if c["longest_diameter_mm"] < 5:
            out.append({"candidate": c["id"], "why": "under 5 mm: partial volume dominates"})
        if c["kinetics"].get("delayed") == "washout":
            out.append({"candidate": c["id"], "why": "washout curve (type III)"})
        gap = (study["region"]["limit_row"] - c["seed"]["bbox"][3]) * \
            study["display"]["native_pixel_mm"][0]
        if gap < rad.CUTOFFS["near_wall_mm"][0]:
            out.append({"candidate": c["id"], "why": f"{gap:.0f} mm from the search region's "
                        "posterior limit: chest-wall muscle and internal mammary vessels enhance "
                        "there too"})
        if c["rank"] > 1 and c["seed"]["mean_sub"] > study["candidates"][0]["seed"]["mean_sub"]:
            out.append({"candidate": c["id"], "why": "brighter on average than C1, ranked lower "
                        "only because it is smaller"})
    return out


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


def spot(pf: PatientFile, study: dict, c: dict) -> None:
    st.markdown(f"#### Spot panel · {c['id']}")
    chips(IMPLEMENTED, INFERENCE, "literature, placeholder until calibrated")
    k, d, seed = c["kinetics"], study["display"], c["seed"]
    a, b = st.columns([3, 2])
    with a:
        st.markdown(
            f"**Size** (model inference, from MedSAM's contour): longest diameter "
            f"**{c['longest_diameter_mm']:g} mm** on native slice {c['ld_slice'] + 1} (in-plane, "
            f"between pixel centres, ± {c['ld_uncertainty_mm']:g} mm; measured on "
            f"{c.get('ld_from', 'every slice')}); craniocaudal extent {c['cc_extent_mm']:g} mm "
            f"({c['medsam_slices']} slices × {d['slice_mm']:g} mm); volume "
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


def prior(study: dict, pf: PatientFile) -> None:
    st.markdown("#### Since the last study")
    chips(PLANNED)
    dates = sorted({s["study"]["date"] for _, s in studies_of(pf) if s and
                    s["modality"] == study["modality"]})
    if len(dates) < 2:
        st.caption(f"One {study['modality']} study date on file for this patient "
                   f"({study['study']['date']}): no prior to compare with. A comparison would "
                   "align two studies by slice index only, with registration not done, and say "
                   "so before any 'larger' or 'smaller'; protocol and scanner differences are "
                   "flagged first.")
    else:
        st.caption(f"Studies on {', '.join(dates)}: aligned by slice index only; registration "
                   "not done, so any change in size is not reliable here.")


def _cannot_see(rows: list[tuple]) -> None:
    st.markdown(f"#### {CANNOT_SEE}")
    st.dataframe(pd.DataFrame([{"not shown here": w, "why": why, "what can": how}
                               for w, why, how, _ in rows]), hide_index=True, width="stretch")


def model_card(study: dict) -> None:
    with st.expander(CARD):
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
                ("Known failures", " ".join(rad.KNOWN_FAILURES[:4])),
                ("Reproducibility", (f"{study['pipeline']['script']} v"
                                     f"{study['pipeline']['version']}, run "
                                     f"{study['pipeline']['run_at']}; model revision "
                                     f"{m['revision'] if m else 'n/a'}"))]
        st.dataframe(pd.DataFrame(rows, columns=["field", "what it records"]), hide_index=True,
                     width="stretch")
        st.dataframe(pd.DataFrame([{"cutoff": k, "value": str(v), "source": tag, "what": note}
                                   for k, (v, tag, note) in rad.CUTOFFS.items()]),
                     hide_index=True, width="stretch")
        n_ph = sum(1 for v in rad.CUTOFFS.values() if v[1] == rad.PLACEHOLDER)
        st.caption(f"{n_ph} of {len(rad.CUTOFFS)} cutoffs are placeholders; the kinetics cutoffs "
                   "are literature values used as placeholders until calibrated here.")


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


def breast_score(study: dict, view: dict) -> str:
    """The screening score of the breast a view shows, for its tooltip."""
    b = study["screening_score"].get("breasts", {}).get(view["laterality"])
    return (f"{b['cancer']:.2g} for this breast, density {b['density_class']} (model inference, "
            "not validated here)" if b else "planned")


def mammo_page(pf: PatientFile, study: dict) -> None:
    rep = study.get("report", {})
    key0 = f"rad-{pf.id}-{study['barcode']}"
    st.markdown(f"#### {study['kind']} · {study['study']['date']}")
    chips(IMPLEMENTED, OBSERVED, INFERENCE, "placeholder")
    st.caption(provenance(study))
    st.markdown(
        f"**Observed** (the study's structured report): {rep.get('procedure', '')}; BI-RADS "
        f"{rep.get('birads', 'not stated')}; pathology {rep.get('pathology', 'not stated')}; "
        f"{receptors(rep)}.  \n"
        f"**Model inference** (placeholder rule): dense-pixel share "
        f"{study['dense_cc_mean']:.0%} on the CC views; a pixel share above an Otsu threshold "
        "inside the breast, not a BI-RADS density category and not validated.  \n"
        + screening_text(study["screening_score"])
        + " Lesion contours on mammograms: planned (no seed rule for mammograms here).")
    level = st.slider("Level", 0, 255, 128, key=f"{key0}-level")
    width = st.slider("Window", 1, 255, 255, key=f"{key0}-width")
    order = {"R-CC": 0, "L-CC": 1, "R-MLO": 2, "L-MLO": 3}
    views = sorted(study["views"], key=lambda v: order.get(v["key"], 9))
    for row in (views[:2], views[2:]):
        for col, v in zip(st.columns(2), row, strict=False):
            img = np.asarray(Image.open(Path(study["folder"]) / v["image"]).convert("L"))
            h, w = img.shape
            dense = v["dense"]
            chart = alt.layer(
                alt.Chart(pd.DataFrame([{"x": 0, "y": 0, "url": uri(Image.fromarray(
                    window(img, level, width)))}])).mark_image(
                    width=w * 0.75, height=h * 0.75, align="left", baseline="top",
                    tooltip=None).encode(
                    x=alt.X("x:Q", scale=alt.Scale(domain=[0, w], nice=False), axis=None),
                    y=alt.Y("y:Q", scale=alt.Scale(domain=[0, h], nice=False, reverse=True),
                            axis=None), url="url:N"),
                alt.Chart(pd.DataFrame([{"x": 0, "y": 0, "x2": w, "y2": h, "view": v["key"],
                                         "dense-pixel share": f"{dense['dense_fraction']:.0%} "
                                                              "(placeholder rule)",
                                         "screening score": breast_score(study, v),
                                         "pixel": f"{v['pixel_mm']:g} mm shown, native "
                                                  f"{v['native_pixel_mm'][0]:g} mm"}])).mark_rect(
                    fillOpacity=0.01, fill="white").encode(
                    x="x:Q", y="y:Q", x2="x2:Q", y2="y2:Q",
                    tooltip=["view:N", "dense-pixel share:N", "screening score:N", "pixel:N"])
            ).properties(width=w * 0.75, height=h * 0.75).configure_view(strokeWidth=0)
            with col:
                st.altair_chart(chart, width="content")
                st.caption(f"{v['laterality']} {v['view']} · dense-pixel share "
                           f"{dense['dense_fraction']:.0%} (placeholder rule; on MLO views the "
                           "pectoral muscle counts as dense)")
                review(finding_key(pf, "imaging", study["barcode"], study["study"]["date"],
                                   v["key"]),
                       f"{study['barcode']} {v['key']}: dense-pixel share "
                       f"{dense['dense_fraction']:.0%} (placeholder rule)")
    st.caption("Shown at 0.46 mm per pixel, downsampled from the 0.07 mm original: "
               "microcalcifications are not visible at this size.")
    _cannot_see(rad.CANNOT_SEE)
    score = study["screening_score"]
    if score.get("status") == "implemented":
        with st.expander(f"{CARD}: mammoscreen"):
            card = score["card"]
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
    _search(pf, study, [], [], rad.CANNOT_SEE)
    _export(pf, study, [{"view": v["key"], "dense-pixel share": v["dense"]["dense_fraction"],
                         "dense rule": "placeholder", "screening score (breast)":
                         breast_score(study, v), "evidence": INFERENCE} for v in views])


def _search(pf: PatientFile, study: dict | None, reads: list[dict], cands: list[dict],
            cannot: list[tuple]) -> None:
    st.markdown("#### Search")
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


def _export(pf: PatientFile, study: dict | None, table: list[dict], extra: dict | None = None):
    st.markdown(f"#### {EXPORT}")
    marks = {k: v for k, v in st.session_state.get("reviews", {}).items()
             if k.startswith(f"{pf.id}|imaging|")}
    body = {"file": pf.id, "exported": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "evidence": "candidates, contours and measurements: model inference; report "
                        "facts and reads: observed",
            "placeholders": [k for k, v in rad.CUTOFFS.items() if v[1] != rad.DESIGN],
            "review_marks": marks, **(extra or {})}
    if study:
        body["study"] = {k: v for k, v in study.items() if k != "folder"}
    name = f"{pf.id}_{study['barcode'] if study else 'imaging_reports'}".replace(" ", "_")
    e1, e2 = st.columns(2)
    e1.download_button("Download the study (JSON)" if study else "Download the reads (JSON)",
                       json.dumps(body, indent=1, default=str),
                       file_name=f"{name}.json", mime="application/json",
                       key=f"rad-json-{name}")
    e2.download_button("Download the lesion table (CSV)", pd.DataFrame(table).to_csv(index=False),
                       file_name=f"{name}_lesions.csv", mime="text/csv", key=f"rad-csv-{name}")


# --- the report-driven page -----------------------------------------------------------------------
def read_rows(reads: list[dict]) -> list[dict]:
    return [{"month": r["month"], "source": r["source"], "read": r["read"],
             "the words": r["words"], "new sites": ", ".join(r["new_sites"]) or "none named",
             "measurements": r["measurements"], "evidence": r["evidence"], "report": r["text"]}
            for r in reads]


def report_page(pf: PatientFile, version: int | None) -> None:
    events = EVENTS
    if version is not None and pf.versions[version].month is not None:
        cutoff = pf.versions[version].month
        hidden = sum(e["month"] > cutoff for e in events)
        events = [e for e in events if e["month"] <= cutoff]
        st.caption(f"As of month {cutoff} ({pf.versions[version].label}): {hidden} later events "
                   "hidden.")
    reads = rad.imaging_reads(events)
    chips(IMPLEMENTED, OBSERVED, "synthetic patient")
    st.warning("Synthetic patient: this record was written by hand and is not a real person. Its "
               "imaging reports exist to show how the workbench reads them.")
    st.caption("Data: the record's imaging reports (text, observed); no images are on file. "
               "Method: report reading rules version 1 (word patterns for the read and for new "
               "sites, cross-checked against the record's own sites field), no model. "
               f"Measurements: {rad.NO_MEASUREMENTS}. Status: implemented.")
    picked = st.session_state.get(f"picked-{pf.id}")
    if picked and picked[0] == "Imaging":
        st.info(f"Opened: {picked[2]}, month {picked[1]}.", icon="📍")
    if not reads:
        st.caption("No imaging read in the record up to this version.")
        return
    lag = rad.lead_lag(events, reads)
    prog = [r for r in reads if r["read"] == rad.PROGRESSION]
    new = [(s, r["month"]) for r in reads for s in r["new_sites"]]
    rise = next((x for x in lag if x["progression"] and "rising" in x["flag"]), None)
    st.markdown(
        f"**Observed.** {len(reads)} imaging reads from month {reads[0]['month']} to "
        f"{reads[-1]['month']}; read as progression at month"
        f"{'s' if len(prog) != 1 else ''} {', '.join(str(r['month']) for r in prog) or 'none'}; "
        f"new sites named: {', '.join(f'{s.lower()} (month {m})' for s, m in new) or 'none'}. "
        f"Latest: {reads[-1]['read']} at month {reads[-1]['month']} ({reads[-1]['source']}). "
        f"The reports record no lesion size: {rad.NO_MEASUREMENTS}."
        + (f" {rise['what'][0].upper() + rise['what'][1:]} (an observed order of events in this "
           "record, not a validated lead time)." if rise else ""))

    st.markdown("#### Imaging reports")
    chips(IMPLEMENTED, OBSERVED)
    for r in reversed(reads):
        title = (f"Imaging report, month {r['month']}" if r["kind"] == "Imaging" else
                 f"{r['kind']} note, month {r['month']}")
        opened = bool(picked) and picked[0] == "Imaging" and picked[1] == r["month"]
        with st.expander(f"{title}: {r['read']}", expanded=opened):
            st.markdown(f"**{title}** · read: **{r['read']}** (\"{r['words']}\") · new sites: "
                        f"{', '.join(r['new_sites']) or 'none named'} · measurements: "
                        f"{r['measurements']} · evidence: {r['evidence']}  \n> {r['text']}")
            if not r["agrees"]:
                st.warning("The report's words and the record's sites field disagree: "
                           f"words {r['new_sites']}, field {r['recorded_sites']}.")
            review(finding_key(pf, "imaging", "report", r["month"], "read"),
                   f"{title}: read {r['read']}")

    st.markdown("#### Lesion table")
    chips(IMPLEMENTED, OBSERVED)
    table = rad.lesion_table(reads)
    months = [r["month"] for r in reads]
    rows = [{"site": t["site"], "first named": f"month {t['first_named']}",
             **{f"month {m}": t["cells"][m] for m in months},
             "measurements": t["measurements"]} for t in table]
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("One row per site a report names; a cell says what that read says about the "
               "site. A read that does not name a site is not a statement about it: "
               "\"not named; overall read: stable\" is never \"stable\" for that site.")
    if table:
        site = st.segmented_control("Spot panel: site", [t["site"] for t in table],
                                    default=table[-1]["site"], key=f"rad-site-{pf.id}")
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

    st.markdown("#### Against the tumor marker")
    chips(IMPLEMENTED, OBSERVED)
    st.caption("Each read against the last CA 15-3 result before it (the labs workbench's rule): "
               "the observed order of events in this record, not a validated lead time.")
    st.markdown("\n".join(f"- {x['pointer'] + ': ' if x['pointer'] else ''}{x['what']}"
                          for x in lag) or "No marker result before a read.")

    _cannot_see(rad.REPORT_CANNOT_SEE)
    st.info("No images are in this file, so no contour, size or kinetics exists for these "
            "lesions. The image viewer runs on public TCGA-BRCA studies: open a TCGA case "
            "file with an imaging test.", icon="🩻")
    _search(pf, None, reads, [], rad.REPORT_CANNOT_SEE)
    _export(pf, None, rows, {"reads": read_rows(reads), "lead_lag": lag})


# --- entry point ----------------------------------------------------------------------------------
def render(pf: PatientFile, version: int | None = None) -> None:
    """The radiology workbench for one patient file, in the current container (no page config,
    no sidebar). ``version``: an index into ``pf.versions``; the report-driven page shows the
    reads up to that version's month."""
    st.subheader("Radiology workbench")
    st.caption(f"{pf.id} · {pf.title}")
    found = studies_of(pf)
    if not found:
        if any(t.workbench == "imaging" for t in pf.tests):
            report_page(pf, version)
        else:
            st.info("This file holds no imaging.", icon="🩻")
        return
    missing = [t for t, s in found if s is None]
    for t in missing:
        st.warning(f"{t.name}: the processed study is not in this checkout "
                   f"(app/workbenches/radiology_results/{t.details['folder']}).")
    found = [(t, s) for t, s in found if s is not None]
    if not found:
        return
    names = [t.name for t, _ in found]
    pick = st.segmented_control("Study", names, default=names[0], key=f"rad-study-{pf.id}") \
        if len(names) > 1 else names[0]
    study = found[names.index(pick or names[0])][1]
    (mri_page if study["modality"] == "MR" else mammo_page)(pf, study)
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
    render(files[st.selectbox("File", list(files))])

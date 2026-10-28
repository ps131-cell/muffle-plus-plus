# Built on muffle.workbench.tile_map (adapted from the team's Colon Tumor Front Analyzer, app/tile_map.py): its in-chart controls, hover grouping and click rules, for a scan  # noqa: E501
"""The scan map of one radiology study (docs/radiology.md §8): the image underneath (an MRI
phase at one slice, or one mammography view), see-through colour layers on top with an opacity
slider, view buttons inside the chart, a fixed-size hover box per square, clickable squares,
pointers and a legend. The slide workbench's map (``muffle.workbench.tile_map``) is the model:
the same in-chart controls (plotly restyles in the browser, so a view change keeps the zoom),
the same hover grouping and click rules, its colours and sizes where they fit.

Views. MRI: **Lesion** (MedSAM's contours filled, their margin band, the seed box and the
longest diameter), **Kinetics** (each contour filled by its delayed curve type, measured by the
pipeline as the contour mean on the original data), **Enhancement** (the subtraction copy as a
heat layer), **Change** (a study pair: the later contours against the earlier ones moved by the
rigid alignment, where the alignment is unreliable tinted). Mammography: **Density** (the dense
pixels and the breast tinted by MONAI's class for the view). A search colours the squares that
match (**Search**).

Why no per-pixel kinetics: the shipped copies are 8-bit with one window shared by every phase
whose lower end is not stored, and the brightest 0.2% of the early phase are clipped at 255,
which is where a lesion is (55% of case 563 C1's pixels): a curve read per pixel from them would
look like a finding and be noise. Kinetics stay the pipeline's contour means.

Coordinates are shown pixels of the shipped copy: pixel (row, col) covers x = col..col+1,
y = row..row+1; the contours, boxes and lines in study.json put pixel centres at integers, so
they are drawn half a pixel on. A square is about ``rad.CUTOFFS["map_square_mm"]`` across.
Evidence: the image and the structured report are observed; every colour on top is a model
inference or a rule on one (placeholders say so). Nothing here runs a model; plotly is imported
only to draw.
"""

from __future__ import annotations

import base64
import io
import math
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageDraw

from muffle.report.case_tools import INFERENCE
from muffle.workbench import radiology as rad
from muffle.workbench.tile_map import (
    MATCH_MIN,
    MATCH_OPACITY,  # noqa: F401  (the page reads the slider's start while searching from here)
    MATCH_RAMP,
    NB,
    OPACITY,
    OPACITY_STEPS,
    THEME,
    TOP_HEIGHT,
    hex_rgb,
)

MODES = {"lesion": "Lesion", "kinetics": "Kinetics", "enhancement": "Enhancement",
         "change": "Change", "density": "Density", "match": "Search"}
CANDIDATE_COLORS = {"C1": "#E64948", "C2": "#EBA034", "C3": "#40A0E6"}  # the page's colours
OTHER_CANDIDATE = "#B8860B"
OFF_SLICE = "#5C5F6A"                  # a pointer to a candidate on another slice
# Delayed curve types (BI-RADS MRI lexicon terms; Kuhl et al. 1999): blue, amber, red
CURVE_COLORS = {"persistent": "#2166AC", "plateau": "#E0A526", "washout": "#B2182B"}
CURVE_TYPES = {"persistent": "I", "plateau": "II", "washout": "III"}
# Enhancement display bins (not cutoffs): share of the study's brightest subtraction
HEAT = [(0.25, "#FED976"), (0.50, "#FD8D3C"), (0.75, "#BD0026")]
# Change between two dates (model contours after a rigid alignment)
CHANGE = {1: ("Both dates", "#7B3294"), 2: ("Larger now (paired)", "#E66101"),
          3: ("Smaller now (paired)", "#1B9E77"), 4: ("Later date only", "#FDB863"),
          5: ("Earlier date only", "#80CDC1")}
UNRELIABLE = "#FF3C3C"
# MONAI / mammoscreen density classes (BI-RADS density categories as the models name them),
# light to dark in a ramp that stays visible on a dark mammogram
DENSITY_COLORS = {"A": "#FFFFB2", "B": "#FECC5C", "C": "#FD8D3C", "D": "#E31A1C"}
OUTLINE_COLOR = "#2468c0"
LIMIT_COLOR = "#C9CED6"                # the seed rule's search limit, dashed, on a dark image
LD_COLOR = "#FFD400"
RULE = "─" * 40                        # fixed-width line: keeps every hover box the same size
LEGEND_HEIGHT = 74                     # three rows of the key below the image
CONTROLS_HEIGHT = TOP_HEIGHT + LEGEND_HEIGHT
ENTRY_PX = 210                         # one key entry's width


def label(text: str) -> str:
    """A hover line's label, padded to a fixed width (non-breaking spaces)."""
    return (text + NB * 11)[:11]


def square_px(pixel_mm: float) -> int:
    """Shown pixels per square side: about ``map_square_mm`` (design: about the smallest
    candidate the seed rule keeps, 30 mm³, a 4 mm sphere)."""
    return max(2, int(round(rad.CUTOFFS["map_square_mm"][0] / pixel_mm)))


def side_name(col: float, cols: int) -> str:
    """The patient's side of a shown column (the patient's right is on the image's left)."""
    return "patient's right" if col < cols / 2 else "patient's left"


# ---------------------------------------------------------------- one slice or view, ready

@dataclass
class ScanMap:
    """One MRI slice or one mammography view: the shown image's size, the squares that hold
    tissue, what each one's hover box says, and the per-pixel layers the views colour."""
    key: str                  # study folder, its files' stamp and the slice or view (caches)
    kind: str                 # "MR" or "MG"
    where: str                # "slice 42 of 90" or "R-CC"
    index: int                # the slice (MR) or the view's position (MG)
    rows: int
    cols: int
    pixel_mm: float
    square: int
    sq_r: np.ndarray          # each square's row and column, in squares
    sq_c: np.ndarray
    wordings: list            # what a hover box says in words, each wording once
    word: np.ndarray          # [n] int16: each square's wording (an index into wordings)
    numbers: np.ndarray       # [n, k] the per-square numbers (-1: not measured)
    cand: np.ndarray          # the candidate a square is inside or beside ("" for none)
    pix: dict                 # per-pixel layers: "cand", "band", "sub", "change", "dense", ...
    info: dict = field(default_factory=dict)

    @property
    def centers(self) -> tuple[np.ndarray, np.ndarray]:
        """Each square's centre in shown pixels (row, col)."""
        h = self.square / 2
        return (np.minimum(self.sq_r * self.square + h, self.rows),
                np.minimum(self.sq_c * self.square + h, self.cols))


def fill_polygons(polys: list, h: int, w: int) -> np.ndarray:
    """Polygons (x, y in shown pixels) filled even-odd, so a hole stays a hole."""
    out = np.zeros((h, w), bool)
    for poly in polys:
        if len(poly) > 2:
            img = Image.new("1", (w, h), 0)
            ImageDraw.Draw(img).polygon([tuple(p) for p in poly], fill=1)
            out ^= np.asarray(img, bool)
    return out


def square_shares(mask: np.ndarray, sq: int) -> np.ndarray:
    """Per square: the share of its pixels where ``mask`` holds (the image padded to whole
    squares)."""
    h, w = mask.shape
    H, W = math.ceil(h / sq) * sq, math.ceil(w / sq) * sq
    pad = np.zeros((H, W), float)
    pad[:h, :w] = mask
    return pad.reshape(H // sq, sq, W // sq, sq).mean(axis=(1, 3))


def nipples(skin: np.ndarray, display: dict) -> dict:
    """The most anterior skin point of each breast (each half of the image) over every shown
    slice, as (z, row, col) in mm and in shown pixels: the nipple in a prone breast MRI with
    anterior at the top. Geometry on the shipped copy, approximate."""
    dz, px, _ = rad.shown_spacing(display)
    out = {}
    skin = np.asarray(skin, np.int64)
    half = skin.shape[1] // 2
    for side, sl in (("patient's right", slice(0, half)), ("patient's left", slice(half, None))):
        part = np.where(skin[:, sl] >= 0, skin[:, sl], 10 ** 6)
        if (part >= 10 ** 6).all():
            continue
        z, x = np.unravel_index(int(np.argmin(part)), part.shape)
        x += sl.start or 0
        out[side] = {"z": int(z), "row": int(skin[z, x]), "col": int(x),
                     "mm": (z * dz, skin[z, x] * px, x * px)}
    return out


def mri_slice(study: dict, i: int, sub: np.ndarray, skin: np.ndarray, nips: dict,
              change: dict | None = None, stamp: str = "") -> ScanMap:
    """MRI slice ``i`` of a study: the candidates' contours on it, their margin band, the
    subtraction brightness, the distances, and (with ``change``, ``change_layer``'s result for
    this slice) the change between two dates. ``sub`` is the shipped subtraction volume
    (uint8), ``skin`` ``rad.skin_rows`` of the pre-contrast copy, ``nips`` ``nipples``."""
    from scipy import ndimage

    d = study["display"]
    h, w, px = d["rows"], d["cols"], d["pixel_mm"]
    sq = square_px(px)
    cands = study["candidates"]
    cand = np.zeros((h, w), np.int8)       # 1-based candidate index inside its contour
    band = np.zeros((h, w), np.int8)       # ... in its margin band
    edge = np.zeros((h, w), np.int8)       # ... on the band's outer edge
    margin = rad.CUTOFFS["margin_band_mm"][0]
    for n, c in reversed(list(enumerate(cands, start=1))):  # C1 drawn last: it wins
        s = c["per_slice"].get(str(i))
        if not s:
            continue
        m = fill_polygons(s["contours"], h, w)
        if not m.any():
            continue
        dist = ndimage.distance_transform_edt(~m) * px
        ring = (dist > 0) & (dist <= margin)
        band[ring & (cand == 0)] = n
        edge[(dist > margin - px) & (dist <= margin) & (cand == 0)] = n
        cand[m] = n
    band[cand > 0] = 0
    v = sub[i].astype(np.float32) / 255.0
    rows = np.arange(h)[:, None]
    under = (skin[i][None, :] >= 0) & (rows >= skin[i][None, :])   # inside the body
    depth = ndimage.distance_transform_edt(under) * px             # to the nearest skin, in-plane
    body = under | (cand > 0)
    # the squares: those that hold tissue (under the skin) or a contour
    share_body = square_shares(body, sq)
    ids = [c["id"] for c in cands]
    share_in = np.stack([square_shares(cand == n, sq) for n in range(1, len(cands) + 1)]) \
        if cands else np.zeros((0, *share_body.shape))
    share_band = np.stack([square_shares(band == n, sq) for n in range(1, len(cands) + 1)]) \
        if cands else np.zeros((0, *share_body.shape))
    sub_sq = square_shares(v, sq) * 100
    keep = share_body > 0
    if cands:
        keep |= share_in.sum(0) > 0
    sq_r, sq_c = np.nonzero(keep)
    n = len(sq_r)
    cy = np.minimum(sq_r * sq + sq / 2, h)
    cx = np.minimum(sq_c * sq + sq / 2, w)
    limit = study["region"]["limit_row_display"]
    d_limit = (limit - cy) * px
    py, px_ = np.minimum(cy.astype(int), h - 1), np.minimum(cx.astype(int), w - 1)
    d_skin = np.where(under[py, px_], depth[py, px_], np.nan)
    dz, _, _ = rad.shown_spacing(d)
    d_nip = np.full(n, np.nan)
    for j in range(n):
        nip = nips.get(side_name(cx[j], w))
        if nip:
            z0, y0, x0 = nip["mm"]
            d_nip[j] = math.dist((i * dz, cy[j] * px, cx[j] * px), (z0, y0, x0))
    wordings: dict = {}                    # each wording once; the squares keep an index
    word = np.zeros(n, np.int16)
    cand_of = np.full(n, "", object)
    inside = np.zeros(n)
    for j in range(n):
        r, c_ = sq_r[j], sq_c[j]
        k_in = int(np.argmax(share_in[:, r, c_])) if cands and share_in[:, r, c_].max() > 0 \
            else None
        k_band = int(np.argmax(share_band[:, r, c_])) if cands and \
            share_band[:, r, c_].max() > 0 else None
        if k_in is not None:
            c = cands[k_in]
            s = c["per_slice"].get(str(i), {})
            region = f"{c['id']} · inside the contour" + (" · unsure" if s.get("unsure")
                                                         else "")
            cand_of[j], inside[j] = c["id"], share_in[k_in, r, c_]
        elif k_band is not None:
            c = cands[k_band]
            region = f"{c['id']} · margin band (≤ {margin:g} mm)"
            cand_of[j] = c["id"]
        else:
            c = None
            region = "Breast tissue" if d_limit[j] >= 0 else "Behind the search limit"
        # how the box writes the distances: in front of or behind the limit, unknown ones
        flags = ("front" if d_limit[j] >= 0 else "behind") + \
            ("" if np.isnan(d_skin[j]) else "|skin") + ("" if np.isnan(d_nip[j]) else "|nip")
        if c is not None:
            k = c["kinetics"]
            words = (region, f"{c['id']} {c['longest_diameter_mm']:g} mm · {c['volume_ml']:g} mL",
                     f"{k.get('initial', '?')} {k.get('initial_pct', '?')}% · contour mean",
                     f"{k.get('delayed', '?')} {k.get('delayed_pct', 0):+g}% · type "
                     f"{k.get('curve_type', '?')}", flags)
        else:
            words = (region, "— (no candidate here)", "— (inside contours only)", "—", flags)
        word[j] = wordings.setdefault(words, len(wordings))
    numbers = np.stack([np.round(sub_sq[sq_r, sq_c]), np.round(d_limit),
                        np.round(np.nan_to_num(d_skin, nan=-1)),
                        np.round(np.nan_to_num(d_nip, nan=-1)),
                        sq_r * sq, sq_c * sq, np.round(inside * 100)], 1)
    pix = {"cand": cand, "band": band, "edge": edge, "sub": sub[i]}
    if change is not None:
        pix["change"] = change["classes"]
        pix["unreliable"] = change["unreliable"]
    here = [c["id"] for c in cands if str(i) in c["per_slice"]]
    return ScanMap(key=f"{study['barcode']}-{study['study']['date']}-{stamp}-s{i}", kind="MR",
                   where=f"slice {i + 1} of {d['slices']}", index=i, rows=h, cols=w,
                   pixel_mm=px, square=sq, sq_r=sq_r, sq_c=sq_c, wordings=list(wordings), word=word,
                   numbers=numbers.astype(np.int32), cand=cand_of, pix=pix,
                   info={"ids": ids, "here": here, "limit_row": limit, "nipples": nips,
                         "candidates": {c["id"]: c for c in cands}})


def mammo_view(study: dict, view: dict, img: np.ndarray, position: int = 0,
               stamp: str = "") -> ScanMap:
    """One mammography view: the breast's outline, the nipple and the chest-wall edge
    (``rad.breast_outline``), the dense pixels by the placeholder rule (Otsu inside the breast,
    on the shipped copy), MONAI's class for the view and mammoscreen's score for the breast."""
    from scipy import ndimage

    h, w = img.shape
    px = view["pixel_mm"]
    sq = square_px(px)
    out = rad.breast_outline(img)
    breast = out["mask"]
    edge = breast & ~ndimage.binary_erosion(breast, iterations=1)  # the outline, one pixel
    thr = rad.dense_fraction(np.where(breast, img, 0), background=0.5).get("threshold")
    dense = breast & (img > thr) if thr is not None else np.zeros_like(breast)
    share_breast = square_shares(breast, sq)
    share_dense = square_shares(dense, sq)
    sq_r, sq_c = np.nonzero(share_breast > 0)
    n = len(sq_r)
    cy = np.minimum(sq_r * sq + sq / 2, h)
    cx = np.minimum(sq_c * sq + sq / 2, w)
    nip = out["nipple"]
    d_nip = np.hypot(cx - nip[0], cy - nip[1]) * px if nip else np.full(n, np.nan)
    d_chest = (cx if out["chest"] == "left" else w - cx) * px
    monai = study.get("density_monai", {}).get("views", {}).get(view["key"])
    score = study.get("screening_score", {}).get("breasts", {}).get(view["laterality"])
    m_txt = (f"{monai['density_class']} · MONAI, this view" if monai else "not run")
    s_txt = (f"{score['cancer']:.2g} · mammoscreen, breast" if score else "not run")
    d_txt = (f"{score['density_class']} · mammoscreen, breast" if score else "not run")
    wordings = [("Breast tissue", m_txt, d_txt, s_txt, "nip" if nip else "")]
    numbers = np.stack([np.round(share_dense[sq_r, sq_c] / np.maximum(share_breast[sq_r, sq_c],
                                                                      1e-9) * 100),
                        np.round(np.nan_to_num(d_nip, nan=-1)), np.round(d_chest),
                        sq_r * sq, sq_c * sq], 1)
    share = float(dense.sum() / max(breast.sum(), 1))
    return ScanMap(key=f"{study['barcode']}-{view['key']}-{stamp}", kind="MG", where=view["key"],
                   index=position, rows=h, cols=w, pixel_mm=px, square=sq, sq_r=sq_r,
                   sq_c=sq_c, wordings=wordings, word=np.zeros(n, np.int16),
                   numbers=numbers.astype(np.int32), cand=np.full(n, "", object),
                   pix={"breast": breast, "dense": dense, "outline": edge},
                   info={"outline": out, "dense_share": share, "threshold": thr,
                         "monai": monai, "score": score, "view": view})


# ---------------------------------------------------------------- change between two dates

def change_layer(later: dict, earlier: dict, ch: dict, i: int, later_masks: dict,
                 earlier_aligned: dict) -> dict:
    """Per pixel of the later study's slice ``i``: 1 both dates (a paired candidate's contours
    overlap), 2 larger now (the later contour only, paired), 3 smaller now (the aligned
    earlier contour only, paired), 4 proposed on the later date only (unpaired), 5 on the
    earlier date only (unpaired); 0 none. ``later_masks`` / ``earlier_aligned``: each
    candidate's mask on this slice of the later study's grid (the earlier one moved by the
    rigid alignment). Unpaired is not new or gone: the seed rule's top three on each date need
    not hold the same lesions. Also the alignment's unreliable blocks on this slice."""
    d = later["display"]
    out = np.zeros((d["rows"], d["cols"]), np.int8)
    for r in ch["rows"]:
        a = earlier_aligned.get(r["earlier"]) if r["earlier"] else None
        b = later_masks.get(r["later"]) if r["later"] else None
        if a is not None and b is not None:
            out[(b & ~a) & (out == 0)] = 2
            out[(a & ~b) & (out == 0)] = 3
            out[a & b] = 1
        elif b is not None:
            out[b & (out == 0)] = 4
        elif a is not None:
            out[a & (out == 0)] = 5
    return {"classes": out, "unreliable": unreliable_blocks(ch, d, i)}


def unreliable_blocks(ch: dict, display: dict, i: int) -> list[tuple]:
    """The alignment's unreliable blocks that axial slice ``i`` cuts, as (x0, y0, x1, y1) in
    shown pixels (``rad.local_residual``'s 30 mm blocks; placeholder cutoffs)."""
    dz, px, _ = rad.shown_spacing(display)
    at = i * dz
    out = []
    for b in ch.get("blocks", []):
        if b["reliable"] or abs(b["at_mm"][0] - at) > b["half_mm"]:
            continue
        _, y, x = b["at_mm"]
        hh = b["half_mm"]
        out.append(((x - hh) / px, (y - hh) / px, (x + hh) / px, (y + hh) / px))
    return out


# ---------------------------------------------------------------- overlay pictures

def modes(m: ScanMap) -> list[str]:
    """The views this slice or view has: Change only with a study pair."""
    if m.kind == "MG":
        return ["density"]
    return ["lesion", "kinetics", "enhancement"] + (["change"] if "change" in m.pix else [])


def overlay_rgba(m: ScanMap, mode: str, values=None) -> np.ndarray:
    """[rows, cols, 4] colours for one view, one pixel per shown pixel (full alpha where
    coloured; the chart's slider sets the opacity). ``values``: per-square 0-1 match scores for
    the search view."""
    out = np.zeros((m.rows, m.cols, 4), np.uint8)
    ids = m.info.get("ids", [])
    if mode == "lesion":
        for n, cid in enumerate(ids, start=1):
            rgb = hex_rgb(CANDIDATE_COLORS.get(cid, OTHER_CANDIDATE))
            out[m.pix["cand"] == n] = rgb + (230,)
            out[m.pix["band"] == n] = rgb + (90,)
            out[m.pix["edge"] == n] = rgb + (255,)
    elif mode == "kinetics":
        cands = m.info.get("candidates", {})
        for n, cid in enumerate(ids, start=1):
            curve = cands[cid]["kinetics"].get("delayed")
            if curve in CURVE_COLORS:
                out[m.pix["cand"] == n] = hex_rgb(CURVE_COLORS[curve]) + (235,)
    elif mode == "enhancement":
        v = m.pix["sub"].astype(np.float32) / 255.0
        for (lo, color), alpha in zip(HEAT, (150, 200, 245), strict=True):  # brighter on top
            out[v >= lo] = hex_rgb(color) + (alpha,)  # one alpha per bin: a small PNG
    elif mode == "change":
        for k, (_, color) in CHANGE.items():
            out[m.pix["change"] == k] = hex_rgb(color) + (240,)
        tint = np.zeros((m.rows, m.cols), bool)
        for x0, y0, x1, y1 in m.pix.get("unreliable", []):
            tint[max(0, int(y0)):max(0, int(math.ceil(y1))),
                 max(0, int(x0)):max(0, int(math.ceil(x1)))] = True
        empty = tint & (out[..., 3] == 0)
        out[empty] = hex_rgb(UNRELIABLE) + (70,)
    elif mode == "density":
        cls = (m.info.get("monai") or {}).get("density_class", "C")
        rgb = hex_rgb(DENSITY_COLORS.get(cls, DENSITY_COLORS["C"]))
        out[m.pix["breast"]] = rgb + (50,)
        out[m.pix["dense"]] = rgb + (235,)
        out[m.pix["outline"]] = hex_rgb(OUTLINE_COLOR) + (255,)
    elif mode == "match" and values is not None:
        ramp = np.array([hex_rgb(c) for c in MATCH_RAMP], float)
        v = np.nan_to_num(np.clip(np.asarray(values, float), 0, 1))
        for j in np.flatnonzero(v >= MATCH_MIN):
            step = min(int(v[j] * len(MATCH_RAMP)), len(MATCH_RAMP) - 1)
            r0, c0 = m.sq_r[j] * m.square, m.sq_c[j] * m.square
            out[r0:r0 + m.square, c0:c0 + m.square, :3] = ramp[step].astype(np.uint8)
            out[r0:r0 + m.square, c0:c0 + m.square, 3] = int(150 + 105 * v[j])
        if "outline" in m.pix:
            out[m.pix["outline"]] = hex_rgb(OUTLINE_COLOR) + (255,)
    return out


def overlay_png(m: ScanMap, mode: str, values=None) -> bytes:
    """One view as PNG bytes, one pixel per shown pixel: the chart draws it unsmoothed."""
    buf = io.BytesIO()
    Image.fromarray(overlay_rgba(m, mode, values), "RGBA").save(buf, "PNG")
    return buf.getvalue()


def scan_jpeg(img: np.ndarray) -> bytes:
    """The shown image (already windowed, uint8) as JPEG bytes for the chart (quality 85:
    the shipped copy is itself a quality-80 JPEG)."""
    buf = io.BytesIO()
    Image.fromarray(img).convert("L").save(buf, "JPEG", quality=85)
    return buf.getvalue()


def legend_items(m: ScanMap, mode: str, study: dict | None = None) -> list[tuple[str, str]]:
    """[(label, hex colour)] explaining one view's colours (at most six entries)."""
    cands = m.info.get("candidates", {})
    if mode == "lesion":  # the same key on every slice of the map's window
        items = [(f"{cid} contour (MedSAM)", CANDIDATE_COLORS.get(cid, OTHER_CANDIDATE))
                 for cid in m.info.get("ids", [])] or [("No candidate proposed", "#FFFFFF")]
        items += [(f"Margin band ≤ {rad.CUTOFFS['margin_band_mm'][0]:g} mm (lighter)",
                   "#E8D3D3"), ("Longest diameter", LD_COLOR),
                  ("Search limit (cleft + 10 mm)", LIMIT_COLOR)]
    elif mode == "kinetics":
        band = rad.CUTOFFS["delayed_band_pct"][0]
        items = [(f"Persistent (I): above +{band:g}%", CURVE_COLORS["persistent"]),
                 (f"Plateau (II): within ±{band:g}%", CURVE_COLORS["plateau"]),
                 (f"Washout (III): below −{band:g}%", CURVE_COLORS["washout"]),
                 ("Cutoffs: literature, placeholder", "#FFFFFF")]
        if not cands:
            items.insert(0, ("No candidate proposed", "#FFFFFF"))
    elif mode == "enhancement":
        items = [("25–50% of the brightest", HEAT[0][1]), ("50–75%", HEAT[1][1]),
                 ("75–100% (display bins)", HEAT[2][1])]
    elif mode == "change":
        items = [(name, color) for name, color in CHANGE.values()]
        items.append(("Alignment unreliable here", UNRELIABLE))
        items = items[:6]
    elif mode == "density":
        monai = m.info.get("monai")
        cls = monai["density_class"] if monai else "?"
        color = DENSITY_COLORS.get(cls, "#2171B5")
        items = [(f"Dense pixels · {m.info['dense_share']:.0%} (placeholder)", color),
                 (f"Breast · MONAI density {cls}", color + "55"),
                 ("Breast outline and nipple", OUTLINE_COLOR)]
    elif mode == "match":
        items = [(f"Match {MATCH_MIN:.0%}–50%", MATCH_RAMP[1]),
                 ("Match over 50%", MATCH_RAMP[-1])]
    else:
        items = []
    return items


# ---------------------------------------------------------------- hover box (grouped = fast)

def hover_groups(m: ScanMap) -> list[tuple[tuple, np.ndarray]]:
    """Squares grouped by everything their hover box says in words; per square only the
    numbers go to the browser. Returns [(texts, square indices)] in drawing order."""
    out = [(words, np.flatnonzero(m.word == k)) for k, words in enumerate(m.wordings)]
    return [(words, idx) for words, idx in out if len(idx)]


def hover_data(m: ScanMap, idx: np.ndarray) -> np.ndarray:
    """The numbers a group's squares send to the browser (int16, so plotly sends them as
    typed arrays; the square itself is its point's x and y, its centre): MRI [subtraction %,
    mm to the search limit, mm to the skin, mm to the nipple, slice + 1]; mammography [dense
    %, mm to the nipple, mm to the chest-wall edge, the view's position + 1]. The slice is in
    the data, not the template, so one template serves every slice of the window."""
    if m.kind == "MG":
        cols = [m.numbers[idx, 0], m.numbers[idx, 1], m.numbers[idx, 2],
                np.full(len(idx), m.index + 1)]
    else:
        cols = [m.numbers[idx, 0], np.abs(m.numbers[idx, 1]), m.numbers[idx, 2],
                m.numbers[idx, 3], np.full(len(idx), m.index + 1)]
    return np.stack(cols, 1).astype(np.int16)


def square_name(m: ScanMap, j: int) -> str:
    """How the page names a square: its centre pixel, as the hover box writes it."""
    cy, cx = m.centers
    return f"r{int(round(float(cy[j])))}c{int(round(float(cx[j])))}"


def group_template(m: ScanMap, texts: tuple) -> str:
    """One group's hover box: the same lines in every box (a fixed-width rule keeps every box
    the same size), the numbers from customdata (``hover_data``)."""
    rule = f"<span style='color:{THEME['rule']}'>{RULE}</span><br>"
    foot = (rule + f"<span style='color:{THEME['muted']}'>Model inference · click to open it"
            "</span><extra></extra>")
    flags = texts[-1].split("|")
    if m.kind == "MG":
        region, monai, mdens, score, _ = texts
        return (f"<b>{region}</b><br>{rule}"
                + label("Dense px") + "%{customdata[0]}% of the square (rule)<br>"
                + label("Density") + f"{monai}<br>" + label("") + f"{mdens}<br>"
                + label("Screening") + f"{score}<br>"
                + label("Nipple") + ("%{customdata[1]} mm (along the view)<br>" if "nip" in flags
                                     else "— (no outline)<br>")
                + label("Chest wall") + "%{customdata[2]} mm to its edge<br>"
                + label("Square") + f"r%{{y:.0f}}c%{{x:.0f}} · {m.where}<br>"
                + foot)
    region, size, wash, curve, _ = texts
    return (f"<b>{region}</b><br>{rule}"
            + label("Size") + f"{size}<br>" + label("Wash-in") + f"{wash}<br>"
            + label("Curve") + f"{curve}<br>"
            + label("Enhanced") + "%{customdata[0]}% of the brightest<br>"
            + label("Nipple") + ("%{customdata[3]} mm (3D, approx.)<br>" if "nip" in flags
                                 else "— (not found)<br>")
            + label("Skin") + ("%{customdata[2]} mm (nearest, in-plane)<br>" if "skin" in flags
                               else "— (outside the body)<br>")
            + label("Limit") + ("%{customdata[1]} mm in front (cleft+10)<br>" if "front" in flags
                                else "behind it by %{customdata[1]} mm<br>")
            + label("Square") + "r%{y:.0f}c%{x:.0f} · slice %{customdata[4]}<br>"
            + foot)


def clicked(customdata, x=None, y=None):
    """What a click hit: ("square", slice or view position, row, col of its centre) for a
    hover square (its customdata ends with the slice or view, ``hover_data``, so a click on
    any slice of the map's window names its own slice; x and y are the point's), ("cand", id)
    for a pointer, else None."""
    if isinstance(customdata, dict):  # a typed array reaches Streamlit as {"0": …, "1": …}
        try:
            customdata = [customdata[k] for k in sorted(customdata, key=int)]
        except (TypeError, ValueError):
            return None
    while isinstance(customdata, (list, tuple)) and len(customdata) == 1:
        customdata = customdata[0]
    if isinstance(customdata, str):
        return ("cand", customdata[5:]) if customdata.startswith("cand:") else None
    if isinstance(customdata, (list, tuple)) and len(customdata) in (4, 5) and \
            x is not None and y is not None:
        try:
            return "square", int(customdata[-1]) - 1, int(round(float(y))), int(round(float(x)))
        except (TypeError, ValueError):
            return None
    return None


def square_at(m: ScanMap, row: float, col: float) -> int | None:
    """The square holding shown pixel (row, col), if it is one of the map's squares."""
    hit = np.flatnonzero((m.sq_r == int(row) // m.square) & (m.sq_c == int(col) // m.square))
    return int(hit[0]) if len(hit) else None


# ---------------------------------------------------------------- what is drawn on top

def contour_lines(study: dict, i: int) -> list[dict]:
    """Each candidate's contour, seed box and longest diameter on slice ``i``, as line traces'
    coordinates (half a pixel on: study.json puts pixel centres at integers)."""
    out = []
    for c in study["candidates"]:
        s = c["per_slice"].get(str(i))
        if not s:
            continue
        xs, ys = [], []
        for poly in s["contours"]:
            if len(poly) > 2:
                xs += [p[0] + 0.5 for p in poly] + [poly[0][0] + 0.5, None]
                ys += [p[1] + 0.5 for p in poly] + [poly[0][1] + 0.5, None]
        x0, y0, x1, y1 = s["box"]
        ld = s["ld_line"] if len(s.get("ld_line", [])) == 2 else None
        out.append({"id": c["id"], "x": xs, "y": ys, "unsure": s.get("unsure", False),
                    "box": (x0 + 0.5, y0 + 0.5, x1 + 0.5, y1 + 0.5), "ld_mm": s.get("ld_mm"),
                    "ld": ([ld[0][0] + 0.5, ld[1][0] + 0.5], [ld[0][1] + 0.5, ld[1][1] + 0.5])
                    if ld else None, "curve": c["kinetics"].get("delayed")})
    return out


def ld_index(study: dict, c: dict) -> int:
    """The shown slice closest to a candidate's longest-diameter slice (an axial acquisition),
    else the shown slice where its contour is largest."""
    step = study["display"]["slice_step"]
    shown = [int(k) for k in c["per_slice"]]
    if not shown:
        return study["display"]["slices"] // 2
    if c.get("ld_plane", "axial") != "axial":
        return max(shown, key=lambda k: c["per_slice"][str(k)]["area_mm2"])
    return min(shown, key=lambda k: abs(k * step - (c["ld_slice"] or 0)))


def candidate_pointers(study: dict, i: int, why: dict | None = None) -> list[dict]:
    """The look-here pointers on slice ``i``: each candidate at its box centre here (its own
    colour), or, when it is not on this slice, at its box centre on its own slice (grey,
    labelled with that slice). ``why``: {candidate: the look-here reasons}."""
    out = []
    for c in study["candidates"]:
        s = c["per_slice"].get(str(i))
        on = s is not None
        j = i if on else ld_index(study, c)
        s = s or c["per_slice"].get(str(j))
        if not s:
            continue
        x0, y0, x1, y1 = s["box"]
        k = c["kinetics"]
        reasons = "; ".join((why or {}).get(c["id"], [])) or "a candidate of the seed rule"
        out.append({"r": (y0 + y1) / 2 + 0.5, "c": (x0 + x1) / 2 + 0.5, "id": c["id"],
                    "label": c["id"] if on else f"{c['id']} · slice {j + 1}",
                    "color": CANDIDATE_COLORS.get(c["id"], OTHER_CANDIDATE) if on else OFF_SLICE,
                    "slice": j, "on": on,
                    "hover": f"{c['id']} ({c['side']}): {c['longest_diameter_mm']:g} mm, "
                             f"{k.get('initial')} wash-in, {k.get('delayed')} delayed · "
                             f"{reasons}" + ("" if on else f" · on slice {j + 1}")})
    return out


# ---------------------------------------------------------------- the figure

def _uri(kind: str, data_bytes: bytes) -> str:
    return f"data:image/{kind};base64," + base64.b64encode(data_bytes).decode()


def full_ranges(m: ScanMap):
    """The whole image in shown pixels: (x range, y range); y runs downward."""
    return [0.0, float(m.cols)], [float(m.rows), 0.0]


def aspect(m: ScanMap) -> float:
    return m.cols / max(m.rows, 1)


def zoom_box_for(rows: int, cols: int, pixel_mm: float, row: float, col: float,
                 half_mm: float = 25.0) -> list[float]:
    """A view of about 2 × ``half_mm`` around shown pixel (row, col) of a rows × cols image,
    with the image's own shape so the drawn size does not change; shifted (not shrunk) to stay
    inside the image. [top, left, bottom, right] in shown pixels."""
    h = min(2 * half_mm / pixel_mm, rows)
    w = min(h * cols / max(rows, 1), cols)
    top = min(max(row - h / 2, 0), rows - h)
    left = min(max(col - w / 2, 0), cols - w)
    return [top, left, top + h, left + w]


def zoom_box(m: ScanMap, row: float, col: float, half_mm: float = 25.0) -> list[float]:
    """``zoom_box_for`` on a map's image."""
    return zoom_box_for(m.rows, m.cols, m.pixel_mm, row, col, half_mm)


def height_for(m: ScanMap, width_px: int = 650, lo: int = 300, hi: int = 520) -> int:
    """The chart's height: the drawing area takes the image's shape at about the page's width,
    within limits, plus the controls above and the key below."""
    return int(min(hi, max(lo, width_px / aspect(m)))) + CONTROLS_HEIGHT


def frame_of(m: ScanMap, scan: bytes, overlays: dict, markers=(), selected=None) -> dict:
    """One slice (or view) of the map's window, as ``figure`` takes it."""
    at = m.where.split(" of ")[0]
    return {"name": at, "label": at.replace("slice ", ""), "m": m, "scan": scan,
            "overlays": overlays, "markers": list(markers), "selected": selected}


def _annotations(m: ScanMap, markers) -> list[dict]:
    top_rows = 0.1 * m.rows
    return [dict(x=p["c"], y=p["r"], text=f"<b>{p['label']}</b>", showarrow=True, arrowhead=0,
                 arrowwidth=1.5, arrowcolor=p["color"], ax=24, ay=28 if p["r"] < top_rows else -28,
                 bgcolor="#FFFFFF", bordercolor=p["color"], borderwidth=1.5, borderpad=3,
                 font=dict(color=p["color"], size=12)) for p in markers]


def _outline(m: ScanMap, selected) -> list[dict]:
    if selected is None or not 0 <= selected < len(m.sq_r):
        return []
    r0, c0 = m.sq_r[selected] * m.square, m.sq_c[selected] * m.square
    return [dict(type="rect", x0=c0 - pad, y0=r0 - pad, x1=c0 + m.square + pad,
                 y1=r0 + m.square + pad, line=dict(color=color, width=width))
            for color, pad, width in (("#FFFFFF", 0.6, 3), (THEME["button"], 0, 2))]


def figure(frames: list[dict], legends: dict, *, active_frame: int = 0,
           study: dict | None = None, opacity: float = OPACITY, active: str | None = None,
           zoom=None, uirevision: str = "map", height: int = 600, total: int | None = None):
    """The interactive map (plotly).
      frames: ``frame_of`` per slice of the window around the chosen slice (MRI), or one (a
      mammography view): the map, the shown image (JPEG), its views' overlays ({mode: PNG}),
      its pointers ([{"r", "c", "label", "color", "hover", "id"}]) and an outlined square;
      active_frame: the one shown first. legends: {mode: [(label, colour)]}. study: the MRI
      study (contours, boxes, the search limit), or None. zoom: [top, left, bottom, right] in
      shown pixels (None = the whole image). total: the study's slice count, for the slider.
    Every trace that changes with the slice is updated by a plotly frame, so the slice slider
    inside the chart (method animate), the view buttons (restyle visible) and the opacity
    slider (restyle opacity) all act in the browser with no rerun, and none undoes the others
    or the zoom. Returns (figure, index of the first hover trace)."""
    import plotly.graph_objects as go

    base = frames[active_frame]
    m0 = base["m"]
    modes_ = list(base["overlays"])
    active = active if active in modes_ else modes_[0]
    mri = study is not None and m0.kind == "MR"
    cands = study["candidates"] if mri else []
    groups = [dict(hover_groups(f["m"])) for f in frames]
    # one hover trace per distinct hover text over the window: its template is written once,
    # on the trace; a frame sends only its squares' positions and numbers
    keys = list(dict.fromkeys(texts for g in groups for texts in g)) or [None]
    img_kw = dict(x0=0.5, y0=0.5, dx=1, dy=1, hoverinfo="skip")
    nothing = dict(x=[None], y=[None])

    def slots(f: dict, grp: dict) -> list[tuple[str, dict]]:
        """The changing data of every per-slice trace, in trace order."""
        m = f["m"]
        out = [("scan", dict(type="image", source=_uri("jpeg", f["scan"])))]
        out += [(f"overlay:{md}", dict(type="image", source=_uri("png", f["overlays"][md])))
                for md in modes_]
        r_c, c_c = m.centers
        for j, texts in enumerate(keys):
            idx = grp.get(texts)
            out.append((f"hover:{j}", dict(type="scattergl", x=[], y=[], customdata=[])
                        if idx is None else dict(
                            type="scattergl", x=c_c[idx].astype(np.float32),
                            y=r_c[idx].astype(np.float32), customdata=hover_data(m, idx))))
        lines = {ln["id"]: ln for ln in contour_lines(study, m.index)} if mri else {}
        for c in cands:
            ln, cid = lines.get(c["id"]), c["id"]
            color = CANDIDATE_COLORS.get(cid, OTHER_CANDIDATE)
            if ln is None:
                out += [(f"contour:{cid}", dict(type="scatter", **nothing,
                                                line=dict(color=color, width=2))),
                        (f"box:{cid}", dict(type="scatter", **nothing)),
                        (f"ld:{cid}", dict(type="scatter", **nothing,
                                           hovertemplate="<extra></extra>")),
                        (f"kin:{cid}", dict(type="scatter", **nothing))]
                continue
            x0, y0, x1, y1 = ln["box"]
            ld = ln["ld"] or ([None], [None])
            out += [(f"contour:{cid}", dict(type="scatter", x=ln["x"], y=ln["y"], line=dict(
                        color=color, width=2, dash="dot" if ln["unsure"] else "solid"))),
                    (f"box:{cid}", dict(type="scatter", x=[x0, x1, x1, x0, x0],
                                        y=[y0, y0, y1, y1, y0])),
                    (f"ld:{cid}", dict(type="scatter", x=ld[0], y=ld[1], hovertemplate=(
                        f"{cid}: longest diameter {ln['ld_mm']:g} mm on this slice (between "
                        "pixel centres, ± one pixel)<extra></extra>" if ln["ld"] else
                        "<extra></extra>"))),
                    (f"kin:{cid}", dict(type="scatter", x=ln["x"], y=ln["y"]))]
        mk = f.get("markers") or []
        clear = "rgba(0,0,0,0)"
        out.append(("markers", dict(
            type="scatter", x=[p["c"] for p in mk] or [None], y=[p["r"] for p in mk] or [None],
            customdata=[[f"cand:{p['id']}"] if p.get("id") else [""] for p in mk] or [[""]],
            text=[p.get("hover", "") for p in mk] or [""],
            marker=dict(symbol="circle-open", size=24, color=[p["color"] for p in mk] or [clear],
                        line=dict(width=2.5, color=[p["color"] for p in mk] or [clear])))))
        return out

    per_mode = {md: [] for md in modes_}
    fades, traces, framed = [], [], []

    def add(trace, modes=(), fade=False, frame=True):
        for md in modes:
            if md in per_mode:
                per_mode[md].append(len(traces))
        if fade:
            fades.append(len(traces))
        if frame:
            framed.append(len(traces))
        traces.append(trace)

    def bare(d: dict) -> dict:
        return {k: v for k, v in d.items() if k != "type"}

    size = max(6.0, 560 / max(m0.cols / m0.square, m0.rows / m0.square))
    first_hover = None
    for role, d in slots(base, groups[active_frame]):
        kind, _, rest = role.partition(":")
        if kind == "scan":
            add(go.Image(**bare(d), **img_kw))
        elif kind == "overlay":
            add(go.Image(**bare(d), opacity=opacity, visible=rest == active, **img_kw), [rest],
                fade=True)
        elif kind == "hover":
            first_hover = len(traces) if first_hover is None else first_hover
            texts = keys[int(rest)]
            add(go.Scattergl(**bare(d), mode="markers", showlegend=False, name="",
                             hovertemplate=group_template(m0, texts) if texts else None,
                             marker=dict(size=size, symbol="square-open", opacity=0,
                                         line=dict(width=2.5, color=THEME["button"])),
                             selected=dict(marker=dict(opacity=1, size=16)),
                             unselected=dict(marker=dict(opacity=0))))
        elif kind == "contour":
            add(go.Scatter(**bare(d), mode="lines", hoverinfo="skip", showlegend=False, name="",
                           visible=active == "lesion"), ["lesion"], fade=True)
        elif kind == "box":
            add(go.Scatter(**bare(d), mode="lines", hoverinfo="skip", showlegend=False, name="",
                           line=dict(color=CANDIDATE_COLORS.get(rest, OTHER_CANDIDATE), width=1,
                                     dash="dash"), visible=active == "lesion"),
                ["lesion"], fade=True)
        elif kind == "ld":
            add(go.Scatter(**bare(d), mode="lines+markers", showlegend=False, name="",
                           line=dict(color=LD_COLOR, width=2), marker=dict(size=5),
                           visible=active == "lesion"), ["lesion"], fade=True)
        elif kind == "kin":
            curve = next(c for c in cands if c["id"] == rest)["kinetics"].get("delayed")
            add(go.Scatter(**bare(d), mode="lines", hoverinfo="skip", showlegend=False, name="",
                           line=dict(color=CURVE_COLORS.get(curve, "#FFFFFF"), width=2),
                           visible=active == "kinetics"), ["kinetics"], fade=True)
        elif kind == "markers":
            add(go.Scatter(**bare(d), mode="markers", hovertemplate="%{text}<extra></extra>",
                           showlegend=False, name="", selected=dict(marker=dict(opacity=1)),
                           unselected=dict(marker=dict(opacity=1))))
    if mri:
        limit = study["region"]["limit_row_display"]
        if 0 < limit < m0.rows:  # every MRI view: lesions behind it are never proposed
            add(go.Scatter(x=[0, m0.cols], y=[limit, limit], mode="lines", hoverinfo="skip",
                           line=dict(color=LIMIT_COLOR, width=1.2, dash="dash"),
                           showlegend=False, name=""), frame=False)
    if m0.kind == "MG":  # the outline is in the overlay (its edge pixels); the nipple on top
        out = m0.info["outline"]
        if out["nipple"]:
            nx, ny = out["nipple"]
            add(go.Scatter(x=[nx + 0.5], y=[ny + 0.5], mode="markers",
                           marker=dict(symbol="circle-open", size=14, color=THEME["button"],
                                       line=dict(width=2)),
                           hovertemplate="Nipple (the breast's point farthest from the "
                                         "chest-wall edge; geometry)<extra></extra>",
                           showlegend=False, name=""), list(per_mode), fade=True, frame=False)
    for md in modes_:                           # legend entries: points that only carry a name
        for text, color in legends.get(md, []):
            add(go.Scatter(x=[None], y=[None], mode="markers", name=text, visible=md == active,
                           hoverinfo="skip", marker=dict(symbol="square", size=11, color=color,
                                                         line=dict(width=1,
                                                                   color="rgba(0,0,0,.25)"))),
                [md], frame=False)

    fig = go.Figure(traces)
    fig.update_layout(annotations=_annotations(m0, base["markers"]),
                      shapes=_outline(m0, base.get("selected")))
    if len(frames) > 1:
        fig.frames = [go.Frame(name=f["name"], traces=framed,
                               data=[d for _, d in slots(f, groups[k])],
                               layout=dict(annotations=_annotations(f["m"], f["markers"]),
                                           shapes=_outline(f["m"], f.get("selected"))))
                      for k, f in enumerate(frames)]

    n = len(traces)

    def visibility(mode):
        visible = [True] * n
        for other in modes_:
            for i in [1 + modes_.index(other)] + per_mode[other]:
                visible[i] = False
        for i in [1 + modes_.index(mode)] + per_mode[mode]:
            visible[i] = True
        return visible

    style = dict(bgcolor="#FFFFFF", bordercolor=THEME["border"], borderwidth=1,
                 font=dict(size=12, color=THEME["text"]))
    menus = []
    if len(modes_) > 1:
        menus.append(dict(type="buttons", direction="right", x=0, y=1.0, xanchor="left",
                          yanchor="bottom", pad=dict(b=50), showactive=True,
                          active=modes_.index(active), **style,
                          buttons=[dict(label=MODES.get(md, md), method="restyle",
                                        args=[{"visible": visibility(md)}]) for md in modes_]))
    look = dict(y=1.0, yanchor="bottom", xanchor="left", pad=dict(t=0, b=6), ticklen=0,
                minorticklen=0, bgcolor=THEME["border"], bordercolor=THEME["border"],
                borderwidth=0, font=dict(size=1))
    sliders = [dict(active=min(range(len(OPACITY_STEPS)),
                               key=lambda i: abs(OPACITY_STEPS[i] - opacity)),
                    steps=[dict(method="restyle", args=[{"opacity": v}, fades],
                                label=f"{v:.0%}") for v in OPACITY_STEPS],
                    x=0, len=0.44 if len(frames) > 1 else 0.55, **look,
                    currentvalue=dict(visible=True, prefix="Colour layer ", xanchor="left",
                                      offset=0, font=dict(size=12, color=THEME["muted"])))]
    if len(frames) > 1:
        sliders.append(dict(
            active=active_frame, x=0.52, len=0.48, **look,
            steps=[dict(method="animate", label=f["label"],
                        args=[[f["name"]], {"mode": "immediate", "transition": {"duration": 0},
                                            "frame": {"duration": 0, "redraw": True}}])
                   for f in frames],
            currentvalue=dict(visible=True, prefix="Slice ",
                              suffix=f" of {total}" if total else "", xanchor="left", offset=0,
                              font=dict(size=12, color=THEME["muted"]))))
    full_x, full_y = full_ranges(m0)
    if zoom:
        top, left, bottom, right = zoom
        xr, yr = [left, right], [bottom, top]
    else:
        xr, yr = full_x, full_y
    pad_x, pad_y = (full_x[1] - full_x[0]) * 0.02, (full_y[0] - full_y[1]) * 0.02
    fig.update_xaxes(visible=False, range=xr, constrain="domain", minallowed=full_x[0] - pad_x,
                     maxallowed=full_x[1] + pad_x)
    fig.update_yaxes(visible=False, range=yr, scaleanchor="x", constrain="domain",
                     minallowed=full_y[1] - pad_y, maxallowed=full_y[0] + pad_y)
    fig.update_layout(
        margin=dict(l=0, r=0, t=TOP_HEIGHT, b=LEGEND_HEIGHT), height=height, dragmode="pan",
        hovermode="closest", hoverdistance=-1, clickmode="event+select", uirevision=uirevision,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#11151A", updatemenus=menus, sliders=sliders,
        legend=dict(orientation="h", x=0, y=-0.02, xanchor="left", yanchor="top",
                    font=dict(size=11, color=THEME["text"]), itemclick=False,
                    itemdoubleclick=False, bgcolor="rgba(0,0,0,0)", entrywidthmode="pixels",
                    entrywidth=ENTRY_PX),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#9AA1AA", align="left",
                        font=dict(family=THEME["mono"], size=12, color=THEME["text"])))
    return fig, first_hover


# ---------------------------------------------------------------- the Spot panel's pictures

def crop(img: np.ndarray, r0: int, c0: int, size: int, radius_px: int,
         scale: int = 6) -> Image.Image:
    """The shown image around a square (top-left pixel r0, c0; ``size`` pixels across),
    ``radius_px`` pixels on each side, enlarged ``scale`` times without smoothing (each shown
    pixel stays a pixel), the square outlined: the copy at its own resolution."""
    h, w = img.shape[:2]
    top, left = max(0, r0 - radius_px), max(0, c0 - radius_px)
    bottom, right = min(h, r0 + size + radius_px), min(w, c0 + size + radius_px)
    part = Image.fromarray(img[top:bottom, left:right]).convert("RGB")
    part = part.resize((part.width * scale, part.height * scale), Image.NEAREST)
    d = ImageDraw.Draw(part)
    x0, y0 = (c0 - left) * scale, (r0 - top) * scale
    x1, y1 = x0 + size * scale, y0 + size * scale
    d.rectangle([x0 - 2, y0 - 2, x1 + 2, y1 + 2], outline=(255, 255, 255), width=3)
    d.rectangle([x0, y0, x1, y1], outline=hex_rgb(THEME["button"]), width=2)
    return part


def square_curve(vols: list[np.ndarray], i: int, r0: int, c0: int, size: int) -> list[float]:
    """A square's mean brightness on each phase's 8-bit copy at slice ``i`` (0-255): the
    curve's shape only, not a percentage (one shared window whose lower end is not stored)."""
    return [float(v[i, r0:r0 + size, c0:c0 + size].mean()) for v in vols]


def clipped_share(vols: list[np.ndarray], i: int, r0: int, c0: int, size: int) -> float:
    """Share of the square's pixels at 250 or more on any phase's copy: clipped there."""
    stack = np.stack([v[i, r0:r0 + size, c0:c0 + size] for v in vols])
    return float((stack >= 250).any(0).mean())


def square_story(m: ScanMap, j: int, study: dict | None = None) -> dict:
    """What a square's Spot panel says: where it is, why it has this colour, how sure, what to
    check by eye. Words only; the page draws them."""
    nums = dict(zip(("sub", "limit", "skin", "nipple", "row", "col", "inside")
                    if m.kind == "MR" else ("dense", "nipple", "chest", "row", "col"),
                    (int(v) for v in m.numbers[j]), strict=False))
    region = m.wordings[m.word[j]][0]
    out = {"region": region, "numbers": nums, "why": [], "how": [], "check": [],
           "candidate": m.cand[j] or None}
    if m.kind == "MG":
        monai, score = m.info.get("monai"), m.info.get("score")
        out["why"].append(f"{nums['dense']}% of this square's breast pixels are above the "
                          "view's Otsu threshold (the dense-pixel rule, a placeholder; a pixel "
                          "share, not a BI-RADS density category)")
        if monai:
            out["why"].append(f"MONAI calls the whole view density {monai['density_class']} "
                              "(model inference; one class per view, not per square)")
        if score:
            out["why"].append(f"mammoscreen's score for this breast is {score['cancer']:.2g} "
                              "(uncalibrated, one score per breast)")
        out["how"].append("no model reads this square on its own: the density opinions are per "
                          "view or breast, the dense pixels a threshold")
        out["check"] += ["a mass, architectural distortion or asymmetry here, by eye",
                         "calcifications on the original images: microcalcifications are not "
                         "visible at the shipped 0.46 mm per pixel"]
        return out
    c = (study or {}).get("candidates") and next(
        (x for x in study["candidates"] if x["id"] == m.cand[j]), None)
    if c is not None and "inside" in region:
        k = c["kinetics"]
        s = c["per_slice"].get(str(m.index), {})
        out["why"] += [
            f"inside MedSAM's contour of {c['id']} (rank {c['rank']} of the seed rule's groups "
            "by summed subtraction): model inference",
            f"its curve: wash-in {k.get('initial')} ({k.get('initial_pct')}%; slow below "
            f"{rad.CUTOFFS['initial_slow_below'][0]}%, fast above "
            f"{rad.CUTOFFS['initial_fast_above'][0]}%), delayed {k.get('delayed')} "
            f"({k.get('delayed_pct'):+g}%; plateau within ±{rad.CUTOFFS['delayed_band_pct'][0]}%)"
            ": the contour's mean on the original data; cutoffs literature, placeholder until "
            "calibrated"]
        edge = abs(abs(k.get("delayed_pct", 0)) - rad.CUTOFFS["delayed_band_pct"][0])
        out["how"] += [("the contour is unsure on this slice (empty, or larger than 1.5 times "
                        "its box)") if s.get("unsure") else "the contour stayed inside its box "
                       "on this slice",
                       f"the delayed change is {edge:.1f} points from the nearest curve-type "
                       "cutoff", f"volume {c['volume_ml']:g} mL, "
                       f"{c['volume_range_ml'][0]:g}–{c['volume_range_ml'][1]:g} mL with the "
                       "contour one pixel in or out"]
        out["check"] += ["the margin in the band around the contour: smooth, irregular or "
                         "spiculated (the map cannot judge a shape)",
                         "the internal enhancement: homogeneous, heterogeneous or rim",
                         "the curve on the original series at a workstation (the mean inside a "
                         "contour mixes enhancing and non-enhancing parts)"]
    elif c is not None:
        out["why"].append(f"in the margin band of {c['id']}: up to "
                          f"{rad.CUTOFFS['margin_band_mm'][0]:g} mm outside its contour "
                          "(placeholder width), where a margin's shape is judged")
        out["how"].append("the band is geometry around a model contour, not a finding")
        out["check"].append("spiculation, an irregular edge or enhancement running out of the "
                            "contour (the contour may stop short of the lesion)")
    else:
        behind = nums["limit"] < 0
        out["why"].append("no candidate here: " + (
            "behind the search limit (the intermammary cleft plus "
            f"{rad.CUTOFFS['chest_margin_mm'][0]} mm, a placeholder), where the seed rule never "
            "looks" if behind else "the subtraction here stays under the seed rule's 99.5th "
            "percentile, or its group was left out by the size or shape rules"))
        out["how"].append("nothing was measured here: the subtraction brightness is the copy's "
                          f"({nums['sub']}% of the study's brightest), not a percentage over "
                          "pre-contrast")
        out["check"].append("a mass or non-mass enhancement the seed rule left out (deep, at the "
                            "chest wall, vessel-like or plate-like shapes are never proposed)")
    return out


INFERENCE_NOTE = (f"Every colour is a {INFERENCE} or a rule on one; the image and the study's "
                  "structured report are observed.")

# Adapted from the team's Colon Tumor Front Analyzer (Ashby Prize Hackathon, Oct 2026): app/tile_map.py  # noqa: E501
"""The slide map of one scored section (docs/pathology.md §8): the section's own scan underneath,
a see-through coloured layer on top with an opacity slider, the hover box, clickable squares,
pointers and the legend. Seven views: the tissue head's classes; the zones around the invasive
front with the front line, growth arrows on the infiltrative arcs, rings on the satellite islands
and the main direction of invasion; the risk levels; the look-here flags; the certainty; the
quality-control exclusions; the lymphocyte-like nuclei. Colours follow the team's analysis figure,
adapted to the head's breast classes (BCSS) and a light page.

Why the view buttons and the opacity slider live INSIDE the chart: Streamlit draws a chart again
when anything in it changes, which resets the zoom; plotly's own buttons and slider act in the
browser with no rerun, so switching views or changing the opacity keeps the view. The chart gets
the scan plus one image per view; the buttons pick which image is visible.

Map coordinates are in TILES: tile (row, col) covers x = col..col+1, y = row..row+1, and the
section's thumbnail (the scored region, ``scripts/slide_pipeline.py``) is stretched to match.
Evidence: the scan and the tile positions are observed; every colour on top is a model inference
or a rule on inferences (the risk levels and several cutoffs are placeholders). Nothing here runs
a model; plotly is imported only to draw.
"""

from __future__ import annotations

import base64
import io
import math
import threading
from dataclasses import dataclass, field

import numpy as np
import pandas as pd
from PIL import Image, ImageFilter

from muffle.workbench.slides import COLORS, LABELS, QC_OK, TILE_UM

MODES = {"tissue": "Tissue", "zones": "Zones", "risk": "Risk", "flags": "Flags",
         "certainty": "Certainty", "qc": "Quality", "immune": "Immune"}
FAINT = 0.12          # how much of a class's colour stays when another class is highlighted
RULE = "─" * 26       # fixed-width line: keeps every hover box the same size
NB = " "         # non-breaking space (normal spaces would be squeezed together)
GLASS_TINT = (233, 236, 239)
OPACITY = 0.45        # the slider's starting value
OPACITY_STEPS = [round(v * 0.05, 2) for v in range(21)]
TOP_HEIGHT = 92       # the view buttons and the opacity slider, above the drawing area
LEGEND_HEIGHT = 66    # bottom margin that holds the key (two rows of entries)
CONTROLS_HEIGHT = TOP_HEIGHT + LEGEND_HEIGHT

# The page's own colours (.streamlit/config.toml), for the parts drawn here
THEME = {"text": "#0e1117", "muted": "#5c5f6a", "border": "#D0D5DB", "button": "#2468c0",
         "rule": "#9AA1AA", "mono": "Cascadia Mono, SFMono-Regular, Consolas, Menlo, monospace"}
# Zones around the invasive front (the figure: core dark red, front band orange, peritumoral
# peach, other tissue light grey, the front itself black); keys are muffle's zone names
ZONES = {"core": ("Tumor core", "#8C0000"),
         "front band": ("Front band (±0.5 mm)", "#FF734D"),
         "peritumoral": ("Peritumoral (0.5–2 mm)", "#FFD9B3"),
         "outside": ("Other tissue", "#D9D9D9")}
ZONE_SHORT = {"core": "Tumor core", "front band": "Front band", "peritumoral": "Peritumoral",
              "outside": "Other tissue", "": "—"}
FRONT_COLOR = "#000000"
GROWTH_COLOR = "#1F5BFF"         # the figure's blue arrows and rings
# Risk levels in matplotlib "Reds" (white -> dark red), as the figure draws risk points
RISK_COLORS = {1: "#FCBBA1", 2: "#EF3B2C", 3: "#A50F15"}
# Search match: one blue scale (more = darker), so it never looks like risk
MATCH_RAMP = ["#C6DBEF", "#9ECAE1", "#6BAED6", "#4292C6", "#2171B5", "#084594"]
UNSURE_COLOR = "#E8A33D"         # only the doubtful tiles get a colour, so they stand out
NOT_ANALYZED = "#9AA1AA"
QC_COLORS = {"glass": "#74B9FF", "pen ink": "#6C3483", "blur": "#16A085",
             "unlike training tissue": "#E67E22"}
# Lymphocyte-like nuclei per counted tile: display bins (not cutoffs), darker = more
IMMUNE_BINS = [(20, "Many lymphocyte-like nuclei (20 or more)", "#08306B"),
               (5, "Some (5–19)", "#4292C6"), (0, "Few (under 5)", "#C6DBEF")]
# Flag markers: (plotly symbol, colour, legend name); the figure's shapes for its flags
FLAG_MARKERS = {"breakaway": ("star", "#B15928", "Breakaway candidates"),
                "disagree": ("diamond", "#FF7F00", "Models disagree on lymphocytes"),
                "island": ("circle-open", GROWTH_COLOR, "Satellite island"),
                "unsure": ("circle-open", "#5C5F6A", "Unsure area"),
                "field": ("circle-open", "#B15928", "Counting field (0.785 mm²)")}
RISK_MARKER = ("square-open", "#7A1C1C")
# Pointer colours per look-here kind (muffle.workbench.invasion.look_here) and for search
POINTER_COLORS = {"risk": "#7A1C1C", "hotspot": "#B15928", "arc": "#1F5BFF",
                  "island": "#1F5BFF", "unsure": "#B54708", "disagree": "#B42318",
                  "search": "#2468c0", "other": "#2468c0"}


def hex_rgb(color: str) -> tuple[int, int, int]:
    color = color.lstrip("#")
    return tuple(int(color[i:i + 2], 16) for i in (0, 2, 4))


def risk_levels() -> dict[int, tuple[str, str]]:
    """{level: (legend name, colour)} with the placeholder point cutoffs in the names."""
    from muffle.workbench.invasion import CUTOFFS
    two, three = CUTOFFS["risk_level_2"][0], CUTOFFS["risk_level_3"][0]
    return {1: (f"Level 1 · 1–{two - 1} points", RISK_COLORS[1]),
            2: (f"Level 2 · {two}–{three - 1} points", RISK_COLORS[2]),
            3: (f"Level 3 · {three} or more", RISK_COLORS[3])}


# ---------------------------------------------------------------- the section, loaded once

@dataclass
class MapData:
    """Everything the map needs for one scored section, as arrays in tile order."""
    key: str                 # names the section and its result files' version (picture cache)
    classes: list
    rows: np.ndarray
    cols: np.ndarray
    ok: np.ndarray           # passed quality control
    reason: np.ndarray       # the quality-control reason, "" when the tile passed
    probs: np.ndarray        # [n, C] the head's raw probabilities
    label: np.ndarray        # [n] index of the map's class (smoothed over 3×3), -1 for none
    score: np.ndarray        # [n] that class's probability averaged over the 3×3 squares
    unsure: np.ndarray
    certainty: np.ndarray    # "Confident" / "Unsure here" / "Excluded"
    risk_points: np.ndarray
    risk_level: np.ndarray
    zone: np.ndarray         # "core" / "front band" / "peritumoral" / "outside" / ""
    on_front: np.ndarray
    dist_um: np.ndarray
    in_main_tumor: np.ndarray
    in_tumor: np.ndarray
    share: np.ndarray        # share of the 8 neighbours with the same class
    index_grid: np.ndarray   # [R, C] -> tile index, -1 for no tile
    geom: dict
    extra: dict = field(default_factory=dict)   # n_lymph, n_nuclei, buds, p_til, disagree


def build(tiles: pd.DataFrame, classes: list[str], grid_shape, thumb_size=None,
          meta: dict | None = None, key: str = "") -> MapData:
    """A section's map data from the page's analysis frame (``invasion.analyze_slide``'s
    ``tiles``: label, unsure, zone, front, risk points, quality, nuclei and second-model columns
    where present); ``thumb_size`` (width, height) of the scored region's thumbnail."""
    from scipy import ndimage

    t = tiles.reset_index(drop=True)
    n = len(t)
    rows, cols = t["row"].to_numpy(int), t["col"].to_numpy(int)
    probs = t[[f"p_{c}" for c in classes]].to_numpy(float)
    qc = t["qc"].astype(str).to_numpy() if "qc" in t else np.full(n, QC_OK, object)
    ok = qc == QC_OK
    reason = np.where(ok, "", qc).astype(object)
    index = {c: i for i, c in enumerate(classes)}
    if "label" in t:
        label = np.array([index.get(v, -1) for v in t["label"].fillna("").astype(str)], int)
    else:
        label = np.where(ok, probs.argmax(1), -1)
    # the score that decides the colour: the class's probability averaged over the 3×3 usable
    # squares around (the map's class is the largest of these averages)
    from muffle.workbench.slides import smooth, tissue_grid

    grid = tissue_grid(t, classes)
    sm = smooth(grid["probs"], grid["usable"])[rows, cols]
    score = np.where(label >= 0, sm[np.arange(n), np.maximum(label, 0)], np.nan)

    def column(name, default, kind=float):
        if name not in t:
            return np.full(n, default, dtype=kind if kind is not str else object)
        col = t[name]
        if kind is bool:
            return col.fillna(False).astype(bool).to_numpy()
        if kind is str:
            return col.fillna("").astype(str).to_numpy(dtype=object)
        return pd.to_numeric(col, errors="coerce").to_numpy(float)

    unsure = column("unsure", False, bool) & ok
    certainty = np.where(~ok, "Excluded", np.where(unsure, "Unsure here", "Confident"))
    R, C = (int(v) for v in grid_shape)
    index_grid = np.full((R, C), -1)
    index_grid[rows, cols] = np.arange(n)
    label_grid = np.full((R, C), -1)
    label_grid[rows[ok], cols[ok]] = label[ok]
    kernel = np.ones((3, 3))
    kernel[1, 1] = 0
    n_nb = ndimage.convolve((label_grid >= 0).astype(float), kernel, mode="constant")
    same = np.zeros((R, C))
    for k in range(len(classes)):
        m = label_grid == k
        same[m] = ndimage.convolve(m.astype(float), kernel, mode="constant")[m]
    share = np.where(n_nb > 0, same / np.maximum(n_nb, 1), 0)[rows, cols]

    w, h = thumb_size or (C * 8, R * 8)
    geom = {"rows": R, "cols": C, "step_x": w / C, "step_y": h / R, "x0": 0.0, "y0": 0.0,
            "width": int(w), "height": int(h), "tile_um": TILE_UM,
            "slide_box": slide_box(meta or {}, R, C)}
    extra = {c: column(c, np.nan) for c in ("n_lymph", "n_nuclei", "buds", "p_til", "til_lymph")
             if c in t}
    if "disagree" in t:
        extra["disagree"] = column("disagree", False, bool)
    return MapData(key=key, classes=list(classes), rows=rows, cols=cols, ok=ok, reason=reason,
                   probs=probs, label=label, score=score, unsure=unsure, certainty=certainty,
                   risk_points=np.nan_to_num(column("risk_points", 0.0)).round().astype(int),
                   risk_level=np.nan_to_num(column("risk_level", 0.0)).astype(int),
                   zone=column("zone", "", str), on_front=column("front", False, bool),
                   dist_um=column("dist_to_front_um", np.nan),
                   in_main_tumor=column("main_tumor", False, bool),
                   in_tumor=column("tumor", False, bool), share=share, index_grid=index_grid,
                   geom=geom, extra=extra)


def slide_box(meta: dict, rows: int, cols: int) -> tuple[int, int, int, int]:
    """The part of the scored grid that lies on the slide, (r0, c0, r1, c1) in tiles: a
    tumor-centred window can reach past the slide's edge (its origin is negative there)."""
    step, dims = meta.get("step_base_px"), meta.get("slide_dimensions")
    r0, c0 = (meta.get("scored") or {}).get("origin_tile", [0, 0])
    if not step or not dims:
        return 0, 0, rows, cols
    return (max(0, -r0), max(0, -c0), min(rows, math.ceil(dims[1] / step) - r0),
            min(cols, math.ceil(dims[0] / step) - c0))


# ---------------------------------------------------------------- overlay pictures

def tile_rgba(data: MapData, mode: str, focus: str | None = None, values=None) -> np.ndarray:
    """[rows, cols, 4] overlay colours for one view. focus = a class to highlight; values =
    per-tile 0-1 match scores for the "match" view (search)."""
    g = data.geom
    out = np.zeros((g["rows"], g["cols"], 4), np.uint8)
    colors = np.zeros((len(data.rows), 4), np.uint8)
    table = np.array([hex_rgb(COLORS.get(c, "#888888")) + (255,) for c in data.classes], np.uint8)
    has = data.label >= 0
    if mode in ("tissue", "flags"):
        colors[has] = table[data.label[has]]
        if mode == "flags":  # the figure's flags panel: the tissue at half strength, markers on top
            colors[has, :3] = 127 + colors[has, :3] // 2
        elif focus in data.classes:
            colors[has & (data.label != data.classes.index(focus)), 3] = int(255 * FAINT)
    elif mode == "certainty":
        colors[data.unsure] = hex_rgb(UNSURE_COLOR) + (255,)
    elif mode == "risk":
        for level, color in RISK_COLORS.items():
            colors[data.risk_level == level] = hex_rgb(color) + (255,)
    elif mode == "match" and values is not None:
        ramp = np.array([hex_rgb(c) for c in MATCH_RAMP], float)
        v = np.clip(np.asarray(values, float), 0, 1)
        shown = v > 0
        step = np.minimum((v * len(MATCH_RAMP)).astype(int), len(MATCH_RAMP) - 1)
        colors[shown, :3] = ramp[step[shown]].astype(np.uint8)
        colors[shown, 3] = (90 + 165 * v[shown]).astype(np.uint8)
    elif mode == "zones":
        for z, (_, color) in ZONES.items():
            colors[data.zone == z] = hex_rgb(color) + (255,)
        colors[data.zone == ""] = hex_rgb(ZONES["outside"][1]) + (255,)
        colors[data.on_front] = hex_rgb(FRONT_COLOR) + (255,)
    elif mode == "qc":
        for why, color in QC_COLORS.items():
            colors[data.reason == why] = hex_rgb(color) + (255,)
        colors[~data.ok & (colors[:, 3] == 0)] = hex_rgb(NOT_ANALYZED) + (255,)
    elif mode == "immune" and "n_lymph" in data.extra:
        lymph = data.extra["n_lymph"]
        counted = ~np.isnan(lymph)
        for low, _, color in IMMUNE_BINS:  # most first: a tile takes the first bin it reaches
            pick = counted & (lymph >= low) & (colors[:, 3] == 0)
            colors[pick] = hex_rgb(color) + (255,)
    if mode != "qc":
        colors[~data.ok] = hex_rgb(NOT_ANALYZED) + (255,)
    out[data.rows, data.cols] = colors
    return out


_pictures: dict = {}
_pic_lock = threading.Lock()


def _remember(key, make):
    with _pic_lock:
        if key not in _pictures:
            if len(_pictures) > 64:          # keep memory in check: forget the oldest pictures
                _pictures.pop(next(iter(_pictures)))
            _pictures[key] = make()
        return _pictures[key]


def _scan(thumb: Image.Image | None, data: MapData, tint_glass: bool) -> Image.Image:
    """The section's scan as RGBA; the grid's part beyond the slide's edge painted as glass,
    and optionally the empty glass around the tissue tinted grey."""
    g = data.geom
    size = (g["width"], g["height"])
    base = (thumb.resize(size) if thumb is not None and thumb.size != size else thumb)
    base = (base if base is not None else Image.new("RGB", size, (236, 236, 240))).convert("RGBA")
    r0, c0, r1, c1 = g["slide_box"]
    if (r0, c0, r1, c1) != (0, 0, g["rows"], g["cols"]):
        on = Image.new("L", size, 0)
        on.paste(255, (round(c0 * g["step_x"]), round(r0 * g["step_y"]),
                       round(c1 * g["step_x"]), round(r1 * g["step_y"])))
        base = Image.composite(base, Image.new("RGBA", size, GLASS_TINT + (255,)), on)
    if tint_glass:
        # tint the empty glass around the tissue (no tiles there) a soft grey, so the tissue
        # outline stands out on the white page; tissue pixels are untouched (fat looks white too)
        grid = ((data.index_grid >= 0) * 255).astype(np.uint8)
        tissue = Image.fromarray(grid).resize(size, Image.NEAREST)
        tissue = tissue.filter(ImageFilter.MaxFilter(5)).filter(ImageFilter.GaussianBlur(3))
        grey = Image.new("RGBA", size, GLASS_TINT + (255,))
        base = Image.composite(base, Image.blend(base, grey, 0.75), tissue)
    return base


def _layer(data: MapData, mode: str, focus=None, values=None, size=None) -> Image.Image:
    """One overlay as a transparent RGBA image: one pixel per tile, or ``size`` (the scan's)
    with the tiles' edges kept crisp."""
    img = Image.fromarray(tile_rgba(data, mode, focus, values), "RGBA")
    return img if size is None else img.resize(size, Image.NEAREST)


def map_image(thumb: Image.Image | None, data: MapData, mode: str, opacity: float,
              show_overlay: bool = True, focus=None, values=None) -> Image.Image:
    """The scan with one view blended on top (PIL image, white glass), for exports."""
    base = _scan(thumb, data, tint_glass=False)
    if show_overlay:
        layer = _layer(data, mode, focus, values, base.size)
        layer.putalpha(layer.getchannel("A").point(lambda a: int(a * opacity)))
        base = Image.alpha_composite(base, layer)
    return base.convert("RGB")


def scan_jpeg(thumb: Image.Image | None, data: MapData) -> bytes:
    """The scan alone (grey glass) as JPEG bytes, for the interactive map."""
    def make():
        buf = io.BytesIO()
        _scan(thumb, data, tint_glass=True).convert("RGB").save(buf, "JPEG", quality=85)
        return buf.getvalue()
    return _remember(("scan", data.key), make)


def overlay_png(data: MapData, mode: str, focus=None, values=None, values_key=None) -> bytes:
    """One view (full alpha; the chart applies the opacity) as PNG bytes, one pixel per tile:
    the chart draws it unsmoothed, so every tile stays a crisp square."""
    def make():
        buf = io.BytesIO()
        _layer(data, mode, focus, values).save(buf, "PNG", optimize=True)
        return buf.getvalue()
    return _remember(("overlay", data.key, mode, focus, values_key), make)


def modes(data: MapData, res: dict | None = None) -> list[str]:
    """The views this section has: Immune only where nuclei were counted; Risk and Flags only
    with the invasion analysis."""
    out = ["tissue", "zones"]
    if res is not None:
        out += ["risk", "flags"]
    out += ["certainty", "qc"]
    if "n_lymph" in data.extra and (~np.isnan(data.extra["n_lymph"])).any():
        out.append("immune")
    return out


def legend_items(data: MapData, mode: str, res: dict | None = None) -> list[tuple[str, str]]:
    """[(label, hex colour)] explaining the colours of one view."""
    ok = data.ok
    n_ok = max(int(ok.sum()), 1)
    if mode == "tissue":
        items = [(f"{LABELS.get(c, c)} {np.mean(data.label[ok] == i) * 100:.0f}%",
                  COLORS.get(c, "#888888")) for i, c in enumerate(data.classes)]
    elif mode == "certainty":
        items = [(f"Unsure here · {int(data.unsure.sum()) / n_ok:.0%} of tissue", UNSURE_COLOR)]
    elif mode == "risk":
        items = [(name, color) for name, color in risk_levels().values()]
        if res is not None and res["risk"]["cards"]:
            items.append(("Risk regions R1… (level 2 or 3)", RISK_MARKER[1]))
    elif mode == "flags":
        present = {f["key"] for f in flag_layer(res, data)} if res is not None else set()
        items = [(name, color) for key, (_, color, name) in FLAG_MARKERS.items()
                 if key in present]
        items = items or [("No flag on this section", "#FFFFFF")]
    elif mode == "match":
        items = [("Weaker match", MATCH_RAMP[1]), ("Stronger match", MATCH_RAMP[-1])]
    elif mode == "qc":
        counts = {why: int((data.reason == why).sum()) for why in QC_COLORS}
        items = [(f"{why.capitalize()} · {n}", QC_COLORS[why]) for why, n in counts.items() if n]
        items = items or [("Every square passed", "#FFFFFF")]
    elif mode == "immune":
        items = [(name, color) for _, name, color in IMMUNE_BINS]
        items.append(("Not counted: no colour", "#FFFFFF"))
    else:
        items = [(name, color) for name, color in ZONES.values()] + [
            ("Invasive front", FRONT_COLOR), ("Growth arrows, island rings", GROWTH_COLOR)]
    if (~ok).any() and mode != "qc":
        items.append((f"Excluded · {int((~ok).sum())} squares", NOT_ANALYZED))
    return items


# ---------------------------------------------------------------- hover box (grouped = fast)

_groups: dict = {}


def label(text: str) -> str:
    return (text + NB * 11)[:11]


def hover_groups(data: MapData) -> list[tuple[tuple[str, str, str], np.ndarray]]:
    """Squares grouped by everything their hover box SAYS (class, certainty, zone). Each group
    becomes one map layer whose words are written once; per square only four small numbers go to
    the browser (score %, risk points, row, column). Returns [(texts, tile indices)], in drawing
    order."""
    if data.key not in _groups:
        if len(_groups) > 16:
            _groups.pop(next(iter(_groups)))
        names = np.array([LABELS.get(c, c) for c in data.classes] + ["No class"], dtype=object)
        cls = names[data.label]  # -1 picks "No class"
        cert = data.certainty.astype(object)
        zone = np.array([ZONE_SHORT.get(z, z) for z in data.zone], dtype=object)
        zone[data.on_front] = "Invasive front"
        bad = ~data.ok
        cls[bad] = np.array([f"Excluded: {r}" for r in data.reason[bad]], dtype=object)
        cert[bad] = "Not scored"
        keys = np.array([f"{a}\x1f{b}\x1f{c}" for a, b, c in zip(cls, cert, zone, strict=True)])
        uniq, inverse = np.unique(keys, return_inverse=True)
        _groups[data.key] = [(tuple(k.split("\x1f")), np.flatnonzero(inverse == i))
                             for i, k in enumerate(uniq)]
    return _groups[data.key]


def group_template(texts: tuple[str, str, str]) -> str:
    cls, cert, zone = texts
    score = "" if cls.startswith("Excluded") else NB * 2 + "%{customdata[0]}% (3×3)"
    rule = f"<span style='color:{THEME['rule']}'>{RULE}</span><br>"
    return (f"<b>{cls}</b>{score}<br>{rule}"
            + label("Certainty") + f"{cert}<br>" + label("Zone") + f"{zone}<br>"
            + label("Risk pts") + "%{customdata[1]} (placeholder)<br>"
            + label("Tile") + "r%{customdata[2]}c%{customdata[3]}<br>" + rule
            + f"<span style='color:{THEME['muted']}'>Model inference · click to select it"
              "</span><extra></extra>")


def clicked_tile(data: MapData, curve, point_index, customdata, first_hover_curve: int):
    """Which tile a click hit: the hover groups carry the index by position; other curves carry
    the tile index in customdata."""
    groups = hover_groups(data)
    i = (curve if curve is not None else -1) - first_hover_curve
    if 0 <= i < len(groups) and point_index is not None:
        return int(groups[i][1][int(point_index)])
    while isinstance(customdata, (list, tuple)):
        customdata = customdata[0] if customdata else None
    try:
        return int(customdata) if customdata is not None and int(customdata) >= 0 else None
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------- what is drawn on top

def _normal(direction_deg: float) -> tuple[float, float]:
    """A compass angle (0 = right, 90 = up) as a step in (rows, cols): rows run downward."""
    rad = math.radians(direction_deg)
    return -math.sin(rad), math.cos(rad)


def growth_layer(res: dict) -> tuple[list[dict], list[dict]]:
    """Where the tumor is pushing out: arrows on the infiltrative arcs of the front and rings on
    the satellite islands (``invasion.analyze_slide``'s arcs and islands)."""
    arcs = [{"center_rc": (a["row"], a["col"]), "normal_rc": _normal(a["direction_deg"]),
             "hover": f"Arc {a['arc']}: infiltrative, push {a['push']:.2f}, "
                      f"roughness {a['roughness']:.0%} (hypothesis)"}
            for a in res.get("arcs", []) if a["pattern"] == "infiltrative"]
    sats = [{"row": s["row"], "col": s["col"],
             "hover": f"Island {s['island']} · {s['area_mm2']} mm² · {s['distance_um']} µm from "
                      f"the main tumor · {LABELS.get(s['between'], s['between']).lower()} "
                      "between"} for s in res.get("islands", [])]
    return arcs, sats


def main_arrow(res: dict):
    """The main direction of invasion: from the main tumor's centre along the push-weighted
    circular mean of the infiltrative arcs' directions, or None."""
    from muffle.workbench.invasion import _circular_mean

    infil = [a for a in res.get("arcs", []) if a["pattern"] == "infiltrative"]
    t = res["tiles"]
    main = t[t["main_tumor"]] if "main_tumor" in t else t.iloc[0:0]
    if not infil or main.empty:
        return None
    deg = _circular_mean(np.array([a["direction_deg"] for a in infil], float),
                         np.array([a["push"] for a in infil], float))
    return (float(main["row"].mean()), float(main["col"].mean())), _normal(deg)


def unsure_regions(data: MapData, top: int = 3) -> list[dict]:
    """The largest unsure areas (8-connected unsure tiles), each with the tile nearest its
    centre."""
    from scipy import ndimage

    g = data.geom
    grid = np.zeros((g["rows"], g["cols"]), bool)
    grid[data.rows[data.unsure], data.cols[data.unsure]] = True
    lab, n = ndimage.label(grid, structure=np.ones((3, 3)))
    if n == 0:
        return []
    sizes = ndimage.sum(grid, lab, range(1, n + 1))
    out = []
    for i in np.argsort(-sizes)[:top]:
        rr, cc = np.nonzero(lab == i + 1)
        j = int(np.argmin((rr - rr.mean()) ** 2 + (cc - cc.mean()) ** 2))
        out.append({"row": int(rr[j]), "col": int(cc[j]), "n_tiles": int(sizes[i])})
    return out


def flag_layer(res: dict | None, data: MapData) -> list[dict]:
    """The look-here flags as map markers: {key, row, col, hover}."""
    out = []
    buds = data.extra.get("buds")
    if buds is not None:
        for i in np.flatnonzero(np.nan_to_num(buds) > 0):
            out.append({"key": "breakaway", "row": int(data.rows[i]), "col": int(data.cols[i]),
                        "hover": f"Breakaway candidates: {int(buds[i])} cluster(s) of up to 4 "
                                 "tumor-candidate nuclei · weak until validated"})
    dis = data.extra.get("disagree")
    if dis is not None:
        names = [LABELS.get(c, c).lower() for c in data.classes] + ["no class"]
        for i in np.flatnonzero(dis):
            p = data.extra.get("p_til", np.full(len(data.rows), np.nan))[i]
            out.append({"key": "disagree", "row": int(data.rows[i]), "col": int(data.cols[i]),
                        "hover": f"Models disagree: the head reads {names[data.label[i]]}, the "
                                 f"second model {p:.0%} lymphocytes"})
    for s in growth_layer(res)[1] if res is not None else []:
        out.append({"key": "island", "row": s["row"], "col": s["col"], "hover": s["hover"]})
    for u in unsure_regions(data):
        out.append({"key": "unsure", "row": u["row"], "col": u["col"],
                    "hover": f"Unsure area · {u['n_tiles']} squares · decide by eye what this "
                             "tissue is"})
    hs = (res or {}).get("hotspot")
    if hs:
        out.append({"key": "field", "row": hs["row"], "col": hs["col"],
                    "radius": hs["radius_tiles"],
                    "hover": f"Counting field: {hs['buds_in_field']} breakaway candidate "
                             f"cluster(s) in 0.785 mm²; {hs['coverage']:.0%} of it counted"})
    return out


# ---------------------------------------------------------------- the figure

def _uri(kind: str, data_bytes: bytes) -> str:
    return f"data:image/{kind};base64," + base64.b64encode(data_bytes).decode()


def figure(data: MapData, scan: bytes, overlays: dict, legends: dict, opacity: float = OPACITY,
           active=None, selected=None, markers=(), zoom=None, uirevision="map", height=600,
           res: dict | None = None):
    """The interactive map (plotly).
      scan: JPEG bytes of the section; overlays: {mode: PNG bytes} (one image per view; the
      in-chart buttons pick one when there are several); legends: {mode: [(label, colour)]}.
      opacity: the slider's starting value; active: the view shown first. markers: [{"r", "c",
      "label", "color", "hover"}] pointers. zoom: [r0, c0, r1, c1] tiles to show (None = whole
      section). res: the invasion analysis (arrows, rings, flags, risk regions), or None.
    Returns (figure, index of the first hover curve) for clicked_tile()."""
    import plotly.graph_objects as go

    g = data.geom
    modes_ = list(overlays)
    active = active if active in modes_ else modes_[0]
    scan_kw = dict(x0=0.5 / g["step_x"], y0=0.5 / g["step_y"], dx=1 / g["step_x"],
                   dy=1 / g["step_y"], hoverinfo="skip")
    tile_kw = dict(x0=0.5, y0=0.5, dx=1, dy=1, hoverinfo="skip")
    traces = [go.Image(source=_uri("jpeg", scan), **scan_kw)]
    for m in modes_:
        traces.append(go.Image(source=_uri("png", overlays[m]), opacity=opacity,
                               visible=m == active, **tile_kw))
    overlay_idx = list(range(1, 1 + len(modes_)))
    first_hover = len(traces)

    size = max(6.0, 600 / max(g["cols"], g["rows"]))
    numbers = np.stack([np.nan_to_num(np.round(data.score * 100)), data.risk_points,
                        data.rows, data.cols], axis=1).astype(np.int16)
    for texts, idx in hover_groups(data):
        traces.append(go.Scattergl(
            x=(data.cols[idx] + 0.5).astype(np.float32),
            y=(data.rows[idx] + 0.5).astype(np.float32),
            customdata=numbers[idx], hovertemplate=group_template(texts), mode="markers",
            showlegend=False, name="",
            # invisible markers to hover; the clicked one is shown by plotly itself (no rebuild
            # of the chart) as an open blue square
            marker=dict(size=size, symbol="square-open", opacity=0,
                        line=dict(width=2.5, color=THEME["button"])),
            selected=dict(marker=dict(opacity=1, size=16)),
            unselected=dict(marker=dict(opacity=0))))
    per_mode = {m: [] for m in modes_}           # trace indices that belong to one view only
    layer_traces = []                            # traces that fade with the opacity slider

    def add(trace, mode):
        per_mode[mode].append(len(traces))
        layer_traces.append(len(traces))
        traces.append(trace)

    def tile_index(r, c):
        r, c = int(round(r)), int(round(c))
        ok = 0 <= r < g["rows"] and 0 <= c < g["cols"]
        return [int(data.index_grid[r, c])] if ok else [-1]

    arcs, sats = growth_layer(res) if res is not None else ([], [])
    arrow = main_arrow(res) if res is not None else None
    if "zones" in modes_ and (arcs or arrow):
        # growth arrows (and the main direction of invasion) as traces, so the slider and the
        # view buttons control them like everything else on the view
        reach = max(g["rows"], g["cols"]) * 0.07
        segments = [(a["center_rc"], a["normal_rc"], reach) for a in arcs]
        if arrow:
            segments.append((arrow[0], arrow[1], max(g["rows"], g["cols"]) * 0.16))
        xs, ys, hx, hy, angles, sizes = [], [], [], [], [], []
        for (r, c), (dr, dc), length in segments:
            x0, y0, x1, y1 = c + 0.5, r + 0.5, c + 0.5 + dc * length, r + 0.5 + dr * length
            xs += [x0, x1, None]
            ys += [y0, y1, None]
            hx.append(x1)
            hy.append(y1)
            angles.append(math.degrees(math.atan2(dc, -dr)))  # clockwise from "up" on screen
            sizes.append(16 if length > reach else 11)
        add(go.Scatter(x=xs, y=ys, mode="lines", line=dict(color=GROWTH_COLOR, width=2.4),
                       opacity=opacity, hoverinfo="skip", showlegend=False, name="",
                       visible=active == "zones"), "zones")
        add(go.Scatter(x=hx, y=hy, mode="markers", opacity=opacity, showlegend=False, name="",
                       visible=active == "zones",
                       text=[a["hover"] for a in arcs] + (
                           ["Main direction of invasion in this section (hypothesis: a 2D "
                            "snapshot, not a forecast)"] if arrow else []),
                       hovertemplate="%{text}<extra></extra>",
                       marker=dict(symbol="triangle-up", size=sizes, angle=angles,
                                   color=GROWTH_COLOR)), "zones")
    if sats and "zones" in modes_:
        add(go.Scatter(
            x=[s["col"] + 0.5 for s in sats], y=[s["row"] + 0.5 for s in sats], mode="markers",
            marker=dict(symbol="circle-open", size=18, color=GROWTH_COLOR, line=dict(width=2)),
            opacity=opacity, hovertemplate="%{text}<extra></extra>", showlegend=False, name="",
            visible=active == "zones", text=[s["hover"] for s in sats],
            customdata=[tile_index(s["row"], s["col"]) for s in sats]), "zones")
    if "flags" in modes_:
        flags = flag_layer(res, data)
        for key in dict.fromkeys(f["key"] for f in flags):
            symbol, color, _ = FLAG_MARKERS[key]
            mine = [f for f in flags if f["key"] == key]
            if key == "field":  # the counting field: a circle of its radius around its centre
                f = mine[0]
                t = np.linspace(0, 2 * math.pi, 73)
                add(go.Scatter(x=f["col"] + 0.5 + f["radius"] * np.cos(t),
                               y=f["row"] + 0.5 + f["radius"] * np.sin(t), mode="lines",
                               line=dict(color=color, width=2, dash="dash"), opacity=opacity,
                               hoverinfo="skip", showlegend=False, name="",
                               visible=active == "flags"), "flags")
                continue
            ring = symbol.endswith("open")
            add(go.Scatter(
                x=[f["col"] + 0.5 for f in mine], y=[f["row"] + 0.5 for f in mine],
                mode="markers", opacity=opacity, showlegend=False, name="",
                visible=active == "flags", hovertemplate="%{text}<extra></extra>",
                text=[f["hover"] for f in mine],
                customdata=[tile_index(f["row"], f["col"]) for f in mine],
                marker=dict(symbol=symbol, size=18 if ring else 11, color=color,
                            line=dict(width=2 if ring else 1,
                                      color=color if ring else "#FFFFFF"))), "flags")
    if "risk" in modes_ and res is not None and res["risk"]["cards"]:
        cards = res["risk"]["cards"]
        add(go.Scatter(
            x=[c["col"] + 0.5 for c in cards], y=[c["row"] + 0.5 for c in cards],
            mode="markers+text", text=[c["card"] for c in cards], textposition="top right",
            textfont=dict(color=RISK_MARKER[1], size=11), opacity=opacity, showlegend=False,
            name="", visible=active == "risk",
            hovertext=[f"{c['card']} · level {c['level']} · {c['points']} points "
                       f"(placeholder) · {', '.join(c['features']) or 'points'}" for c in cards],
            hovertemplate="%{hovertext}<extra></extra>",
            customdata=[tile_index(c["row"], c["col"]) for c in cards],
            marker=dict(symbol=RISK_MARKER[0], size=16, color=RISK_MARKER[1],
                        line=dict(width=2, color=RISK_MARKER[1]))), "risk")

    if markers:
        traces.append(go.Scatter(
            x=[m["c"] + 0.5 for m in markers], y=[m["r"] + 0.5 for m in markers],
            mode="markers", customdata=[tile_index(m["r"], m["c"]) for m in markers],
            hovertemplate="%{text}<extra></extra>", text=[m.get("hover", "") for m in markers],
            showlegend=False, name="",
            marker=dict(symbol="circle-open", size=22, color=[m["color"] for m in markers],
                        line=dict(width=2.5, color=[m["color"] for m in markers])),
            selected=dict(marker=dict(opacity=1)), unselected=dict(marker=dict(opacity=1))))

    for m in modes_:                             # legend entries: points that only carry a name
        for text, color in legends.get(m, []):
            per_mode[m].append(len(traces))
            traces.append(go.Scatter(
                x=[None], y=[None], mode="markers", name=text, visible=m == active,
                hoverinfo="skip", marker=dict(symbol="square", size=11, color=color,
                                              line=dict(width=1, color="rgba(0,0,0,.25)"))))

    fig = go.Figure(traces)
    top_rows = 0.08 * g["rows"]  # a label near the top edge goes below its ring, not over the
    fig.update_layout(annotations=[dict(  # slider
        x=m["c"] + 0.5, y=m["r"] + 0.5, text=f"<b>{m['label']}</b>", showarrow=True,
        arrowhead=0, arrowwidth=1.5, arrowcolor=m["color"], ax=22,
        ay=26 if m["r"] < top_rows else -26, bgcolor="#FFFFFF", bordercolor=m["color"],
        borderwidth=1.5, borderpad=3, font=dict(color=m["color"], size=12)) for m in markers])

    if selected is not None:
        r, c = int(data.rows[selected]), int(data.cols[selected])
        for color, pad, width in (("#FFFFFF", 0.15, 3), (THEME["button"], 0, 2)):
            fig.add_shape(type="rect", x0=c - pad, y0=r - pad, x1=c + 1 + pad, y1=r + 1 + pad,
                          line=dict(color=color, width=width))

    # in-chart controls: view buttons and the opacity slider (no rerun, so the view is kept)
    n = len(traces)
    menus = []

    def visibility(mode):
        visible = [True] * n
        for other in modes_:
            for i in [1 + modes_.index(other)] + per_mode[other]:
                visible[i] = other == mode
        return visible

    style = dict(bgcolor="#FFFFFF", bordercolor=THEME["border"], borderwidth=1,
                 font=dict(size=12, color=THEME["text"]))
    if len(modes_) > 1:
        menus.append(dict(type="buttons", direction="right", x=0, y=1.0, xanchor="left",
                          yanchor="bottom", pad=dict(b=50), showactive=True,
                          active=modes_.index(active), **style,
                          buttons=[dict(label=MODES.get(m, m), method="restyle",
                                        args=[{"visible": visibility(m)}]) for m in modes_]))
    steps = [dict(method="restyle", args=[{"opacity": v}, overlay_idx + layer_traces],
                  label="", value=f"{v:.0%}") for v in OPACITY_STEPS]
    slider = dict(active=min(range(len(OPACITY_STEPS)),
                             key=lambda i: abs(OPACITY_STEPS[i] - opacity)),
                  steps=steps, x=0, len=0.55, xanchor="left", y=1.0, yanchor="bottom",
                  pad=dict(t=0, b=6), ticklen=0, minorticklen=0, bgcolor=THEME["border"],
                  bordercolor=THEME["border"], borderwidth=0, font=dict(size=1),
                  currentvalue=dict(visible=True, prefix="Colour layer ", suffix="",
                                    xanchor="left", offset=0,
                                    font=dict(size=12, color=THEME["muted"])))

    full_x, full_y = full_ranges(data)
    if zoom:
        r0, c0, r1, c1 = zoom
        xr, yr = [c0, c1 + 1], [r1 + 1, r0]
    else:
        xr, yr = full_x, full_y
    # The drawing area keeps the section's shape (constrain="domain"); every view the app sets
    # has that same shape (zoom_box), so the drawn size never changes. minallowed / maxallowed
    # stop panning and zooming out at the section's edges.
    pad_x, pad_y = (full_x[1] - full_x[0]) * 0.02, (full_y[0] - full_y[1]) * 0.02
    fig.update_xaxes(visible=False, range=xr, constrain="domain", minallowed=full_x[0] - pad_x,
                     maxallowed=full_x[1] + pad_x)
    fig.update_yaxes(visible=False, range=yr, scaleanchor="x", constrain="domain",
                     minallowed=full_y[1] - pad_y, maxallowed=full_y[0] + pad_y)
    fig.update_layout(
        margin=dict(l=0, r=0, t=TOP_HEIGHT, b=LEGEND_HEIGHT), height=height, dragmode="pan",
        hovermode="closest",
        hoverdistance=-1,  # always hover (and so select) the nearest square, however far zoomed
        clickmode="event+select", uirevision=uirevision, paper_bgcolor="#FFFFFF",
        plot_bgcolor="#F4F6F8", updatemenus=menus, sliders=[slider],
        legend=dict(orientation="h", x=0, y=-0.02, xanchor="left", yanchor="top",
                    font=dict(size=11, color=THEME["text"]), itemclick=False,
                    itemdoubleclick=False, bgcolor="rgba(0,0,0,0)", entrywidthmode="pixels",
                    entrywidth=150),
        hoverlabel=dict(bgcolor="#FFFFFF", bordercolor="#9AA1AA", align="left",
                        font=dict(family=THEME["mono"], size=12, color=THEME["text"])))
    return fig, first_hover


def full_ranges(data: MapData):
    """The whole-section view in tile units: (x range, y range); y runs downward like the
    image."""
    g = data.geom
    return [0.0, float(g["cols"])], [float(g["rows"]), 0.0]


def aspect(data: MapData) -> float:
    """Width / height of the whole section (the drawing area has the same shape)."""
    (x0, x1), (y0, y1) = full_ranges(data)
    return (x1 - x0) / max(y0 - y1, 1e-9)


def zoom_box(r: int, c: int, data: MapData, half: int = 12) -> list[float]:
    """A view of about (2 x half) rows around tile (r, c), with the section's own shape so the
    drawn size doesn't change; shifted (not shrunk) to stay inside the section."""
    (x0, x1), (y0, y1) = full_ranges(data)
    h = min(2 * half, y0 - y1)
    w = min(h * aspect(data), x1 - x0)
    top, left = r + 0.5 - h / 2, c + 0.5 - w / 2
    top = min(max(top, y1), y0 - h)
    left = min(max(left, x0), x1 - w)
    return [top, left, top + h - 1, left + w - 1]


def height_for(data: MapData, width_px: int = 760, lo: int = 320, hi: int = 640) -> int:
    """The chart's height in pixels: the drawing area takes the section's shape at about the
    page's width, within limits, plus the controls above and the key below."""
    return int(min(hi, max(lo, width_px / aspect(data)))) + CONTROLS_HEIGHT


def neighborhood(thumb: Image.Image | None, data: MapData, i: int, radius: int = 6,
                 scale: int = 4) -> Image.Image | None:
    """A zoomed crop of the scan around tile i, with that tile outlined ("where it sits")."""
    from PIL import ImageDraw

    if thumb is None:
        return None
    g = data.geom
    sx, sy = g["step_x"], g["step_y"]
    x, y = data.cols[i] * sx, data.rows[i] * sy
    box = [max(0, x - radius * sx), max(0, y - radius * sy),
           min(thumb.width, x + sx * (radius + 1)), min(thumb.height, y + sy * (radius + 1))]
    crop = thumb.crop(tuple(round(v) for v in box))
    crop = crop.resize((max(1, crop.width * scale), max(1, crop.height * scale)), Image.BICUBIC)
    d = ImageDraw.Draw(crop)
    left, top = (x - box[0]) * scale, (y - box[1]) * scale
    right, bottom = left + sx * scale, top + sy * scale
    d.rectangle([left - 2, top - 2, right + 2, bottom + 2], outline=(255, 255, 255), width=3)
    d.rectangle([left, top, right, bottom], outline=hex_rgb(THEME["button"]), width=2)
    return crop

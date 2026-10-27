"""The slide viewer's geometry: Deep Zoom pyramids of a diagnostic section and where the scored
tile grid, its overlays and its nuclei sit on them (docs/pathology.md §7).

Pure functions, no model and no Streamlit: ``scripts/slide_pyramid.py`` uses the pyramid math
to write the tiles, the page uses the mapping and ``overlay`` to draw the analysis on the
tissue. Evidence types carry over unchanged from ``slides`` and ``invasion``: classes and
nuclei are model inferences, the front and zones are rules on them, the direction of invasion
is a hypothesis about this section.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd
from scipy import ndimage

from muffle.workbench import invasion as inv
from muffle.workbench.slides import COLORS, LABELS, QC_OK, QC_UNLIKE

TILE, OVERLAP = 254, 1   # Deep Zoom tiles of 254 px plus a 1 px overlap: 256 px JPEGs
ZONES = ["", "core", "front band", "peritumoral", "outside"]
QCS = [QC_OK, "glass", "pen ink", "blur", QC_UNLIKE]
CELL_KINDS = ["other", "lymphocyte-like", "tumor candidate", "breakaway cluster"]


# --- the pyramid -------------------------------------------------------------------------------

def dz_levels(width: int, height: int) -> list[tuple[int, int]]:
    """Deep Zoom level sizes from level 0 (1×1) to the full image; each level is the next one
    halved, rounding up (the DZI convention OpenSeadragon and OpenSlide share)."""
    sizes = [(int(width), int(height))]
    while sizes[-1] != (1, 1):
        w, h = sizes[-1]
        sizes.append((max(1, -(-w // 2)), max(1, -(-h // 2))))
    return sizes[::-1]


def dz_tiles(width: int, height: int, tile: int = TILE) -> list[tuple[int, int]]:
    """Tile columns and rows per Deep Zoom level."""
    return [(-(-w // tile), -(-h // tile)) for w, h in dz_levels(width, height)]


def level_drop(base_mpp: float, target_mpp: float = 1.0) -> int:
    """How many halvings below the scan's full resolution the pyramid's top level sits: the
    power of two nearest to ``target_mpp / base_mpp`` (2 for a 40× scan at 1 µm/px)."""
    return max(0, int(round(math.log2(target_mpp / base_mpp))))


def tile_frame(meta: dict, pyramid: dict) -> dict:
    """Where the scored grid sits in the pyramid's top-level pixels: tile (row, col) covers
    x0 + col·t to x0 + (col + 1)·t, and the same for rows. ``meta`` is the result's
    summary.json (grid step in base pixels, the scored window's origin tile), ``pyramid`` its
    pyramid entry (``downsample``: base pixels per pyramid pixel)."""
    step, ds = float(meta["step_base_px"]), float(pyramid["downsample"])
    r0, c0 = meta.get("scored", {}).get("origin_tile", [0, 0])
    return {"x0": c0 * step / ds, "y0": r0 * step / ds, "t": step / ds}


def to_pyramid(row: float, col: float, frame: dict) -> tuple[float, float]:
    """The pyramid pixel (x, y) of a point in grid units (a tile's top-left corner is integer)."""
    return frame["x0"] + col * frame["t"], frame["y0"] + row * frame["t"]


# --- overlay geometry --------------------------------------------------------------------------

def _runs(edges: set[tuple[int, int]]) -> list[tuple[int, int, int]]:
    """Unit edges (line, position) merged into runs (line, start, end)."""
    out: list[tuple[int, int, int]] = []
    for line, pos in sorted(edges):
        if out and out[-1][0] == line and out[-1][2] == pos:
            out[-1] = (line, out[-1][1], pos + 1)
        else:
            out.append((line, pos, pos + 1))
    return out


def outline(mask: np.ndarray, against: np.ndarray | None = None) -> list[list[int]]:
    """The boundary of a [rows, cols] mask as segments [x0, y0, x1, y1] in grid units; with
    ``against``, only the sides that face a cell of that mask (the front faces non-tumor
    tissue, not glass)."""
    out = np.pad(~mask if against is None else against & ~mask, 1,
                 constant_values=against is None)
    horiz, vert = set(), set()
    for r, c in zip(*np.nonzero(mask), strict=True):
        if out[r, c + 1]:
            horiz.add((r, c))          # top side, y = row
        if out[r + 2, c + 1]:
            horiz.add((r + 1, c))      # bottom side, y = row + 1
        if out[r + 1, c]:
            vert.add((c, r))           # left side, x = col
        if out[r + 1, c + 2]:
            vert.add((c + 1, r))       # right side, x = col + 1
    return ([[int(x0), int(y), int(x1), int(y)] for y, x0, x1 in _runs(horiz)]
            + [[int(x), int(y0), int(x), int(y1)] for x, y0, y1 in _runs(vert)])


# --- nuclei ------------------------------------------------------------------------------------

def cells_json(nuclei: pd.DataFrame) -> dict:
    """The pipeline's nucleus table (row, col, x_um, y_um, area_um2, solidity) packed per tile
    for nuclei.json, at the table's own precision."""
    tiles = {}
    for (r, c), g in nuclei.groupby(["row", "col"]):
        a = np.column_stack([g.x_um * 10, g.y_um * 10, g.area_um2 * 10, g.solidity * 1000])
        tiles[f"{int(r)}_{int(c)}"] = np.rint(a).astype(int).ravel().tolist()
    return {"units": "per tile: x, y (0.1 µm from the tile's top-left corner), area (0.1 µm²), "
                     "solidity (thousandths)", "tiles": tiles}


def cells_frame(nuc: dict) -> pd.DataFrame:
    """``cells_json`` read back: one row per nucleus. Empty when the result holds no
    per-nucleus table (nuclei not run on this section)."""
    frames = []
    for key, flat in (nuc.get("cells") or {}).get("tiles", {}).items():
        r, c = (int(v) for v in key.split("_"))
        a = np.asarray(flat, float).reshape(-1, 4)
        frames.append(pd.DataFrame({"row": r, "col": c, "x_um": a[:, 0] / 10,
                                    "y_um": a[:, 1] / 10, "area_um2": a[:, 2] / 10,
                                    "solidity": a[:, 3] / 1000}))
    if not frames:
        return pd.DataFrame(columns=["row", "col", "x_um", "y_um", "area_um2", "solidity"])
    return pd.concat(frames, ignore_index=True)


def cell_kinds(cells: pd.DataFrame, tiles: pd.DataFrame) -> np.ndarray:
    """Each nucleus's kind by the rules ``invasion.nuclei_summary`` counts with (all
    placeholders): 1 lymphocyte-like, 2 tumor candidate, 3 member of a breakaway cluster
    (≤ 4 candidate nuclei in a front-band tile outside the main tumor), 0 other. ``tiles`` is
    ``invasion.analyze_slide``'s frame."""
    kinds = np.zeros(len(cells), int)
    if not len(cells):
        return kinds
    cut = inv.CUTOFFS
    t = tiles.set_index(["row", "col"])
    lymph = inv.lymphocyte_like(cells)
    big = (cells["area_um2"] >= cut["tumor_nucleus_area_um2"][0]).to_numpy()
    kinds[lymph] = 1
    for (r, c), idx in cells.groupby(["row", "col"]).indices.items():
        if (r, c) not in t.index:
            continue
        tile = t.loc[(r, c)]
        p = float(tile["p_tumor"])
        cand = ~lymph[idx] & big[idx]
        if p >= cut["tumor_nucleus_p"][0]:
            kinds[idx[cand]] = 2
        if (not tile["main_tumor"] and tile["zone"] == "front band"
                and p >= cut["bud_tile_p"][0] and cand.any()):
            members = idx[cand]
            lab = inv.clusters(cells.iloc[members][["x_um", "y_um"]].to_numpy(float))
            kinds[members[np.bincount(lab)[lab] <= cut["bud_max_nuclei"][0]]] = 3
    return kinds


# --- the payload the viewer draws --------------------------------------------------------------

def _region_outlines(res: dict) -> list[dict]:
    """Each risk card with the outline of its level-2-or-more region (matched by centre and
    size, as ``invasion.risk_map`` made them)."""
    lab, n = ndimage.label(res["risk"]["level"] >= 2)
    pieces = {}
    for i in range(1, n + 1):
        rr, cc = np.nonzero(lab == i)
        pieces[(int(round(rr.mean())), int(round(cc.mean())), len(rr))] = lab == i
    return [{**{k: card[k] for k in ("card", "level", "points", "features", "mm2", "row", "col")},
             "outline": outline(pieces[(card["row"], card["col"], card["tiles"])])}
            for card in res["risk"]["cards"]]


def til_codes(t: pd.DataFrame) -> list[int]:
    """The second lymphocyte model per tile: -1 not scored, 0 not lymphocytes, 1 lymphocytes;
    2 and 3 the same where the head disagrees."""
    if "til_lymph" not in t:
        return [-1] * len(t)
    code = t["til_lymph"].fillna(-1).astype(int)
    dis = t["disagree"].fillna(False).astype(bool) if "disagree" in t else False
    return code.where(~(dis & (code >= 0)), code + 2).tolist()


def overlay(res: dict, classes: list[str], cells: pd.DataFrame | None = None) -> dict:
    """Everything the viewer draws on the section, in grid units (the browser maps them with
    ``tile_frame``): per-tile class, certainty, quality, zone, front, risk and nuclei counts as
    columns; the front line, island and risk-region outlines as segments; arcs with direction
    and push; the counting field; pointers; and each counted nucleus with its radius (µm, from
    its area) and kind."""
    t = res["tiles"]
    h, w = res["grid_shape"]
    counted = t["n_nuclei"].notna() if "n_nuclei" in t else pd.Series(False, index=t.index)

    def ints(name, fill=-1):
        return (t[name].where(counted, fill).fillna(fill).astype(int).tolist() if name in t
                else [fill] * len(t))

    tissue = inv.grid(t.assign(one=True), "one", False, bool)
    main = inv.grid(t, "main_tumor", False, bool)
    lab_s, _ = ndimage.label(inv.grid(t, "tumor", False, bool) & ~main)  # as satellite_islands
    cls = t["label"].map({k: i for i, k in enumerate(classes)}).fillna(-1).astype(int)
    payload = {
        "grid": {"rows": int(h), "cols": int(w)},
        "classes": [{"key": k, "label": LABELS[k], "color": COLORS[k]} for k in classes],
        "zones": ZONES, "qcs": QCS, "cell_kinds": CELL_KINDS,
        "tiles": {
            "r": t["row"].astype(int).tolist(), "c": t["col"].astype(int).tolist(),
            "cls": cls.where(t["qc"] == QC_OK, -1).tolist(),
            "top": (t[[f"p_{k}" for k in classes]].max(axis=1) * 100).round().astype(int)
            .tolist(),
            "unsure": t["unsure"].astype(int).tolist(),
            "qc": t["qc"].map({q: i for i, q in enumerate(QCS)}).fillna(0).astype(int).tolist(),
            "zone": t["zone"].map({z: i for i, z in enumerate(ZONES)}).fillna(0).astype(int)
            .tolist(),
            "front": t["front"].astype(int).tolist(),
            "dist": ([None if pd.isna(v) else int(v) for v in t["dist_to_front_um"]]
                     if "dist_to_front_um" in t else [None] * len(t)),
            "risk": t["risk_level"].astype(int).tolist(),
            "pts": t["risk_points"].round().astype(int).tolist(),
            "n": ints("n_nuclei"), "ly": ints("n_lymph"), "bud": ints("buds"),
            "til": til_codes(t),
        },
        "front": outline(main, against=tissue & ~main),
        "arcs": [{"arc": a["arc"], "row": a["row"] + 0.5, "col": a["col"] + 0.5,
                  "dir": a["direction_deg"], "push": a["push"], "pattern": a["pattern"],
                  "rough": a["roughness"], "length_mm": a["length_mm"],
                  "faces": LABELS.get(a["faces_top"], a["faces_top"])} for a in res["arcs"]],
        "hotspot": res["hotspot"],
        "islands": [{"island": s["island"], "row": s["row"], "col": s["col"],
                     "area_mm2": s["area_mm2"], "distance_um": s["distance_um"],
                     "between": LABELS.get(s["between"], s["between"]),
                     "outline": outline(lab_s == int(s["island"][1:]))} for s in res["islands"]],
        "regions": _region_outlines(res),
        "queue": [{k: p[k] for k in ("pointer", "row", "col", "what", "check", "evidence",
                                     "status", "kind")} for p in res["queue"]],
        "cells": {},
    }
    if cells is not None and len(cells):
        kinds = cell_kinds(cells, t)
        x, y = cells["x_um"].to_numpy(float), cells["y_um"].to_numpy(float)
        radius = np.sqrt(cells["area_um2"].to_numpy(float) / math.pi)
        for (r, c), idx in cells.groupby(["row", "col"]).indices.items():
            payload["cells"][f"{r}_{c}"] = [v for i in idx for v in (
                round(float(x[i]), 1), round(float(y[i]), 1), round(float(radius[i]), 1),
                int(kinds[i]))]
    return payload

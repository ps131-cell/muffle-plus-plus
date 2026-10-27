"""Pathology slide workbench: pure functions over one slide's tile table (docs/WORKBENCHES.md §5).

A slide region is a grid of 224 px tiles at 0.5 µm/px (112 µm a side, 0.0125 mm²). Each tile
row carries the tissue head's class probabilities (``p_<class>``), its quality measures and its
position. Everything here is numpy and scipy arithmetic on those columns: no model runs.

Evidence types: a tile's class is a **model inference** (the head's probabilities, with their
measured accuracy in ``HEAD_CARD``); the tumor region, its front and the zones are geometry on
those inferences; the quality exclusions are rules. Every cutoff in ``CUTOFFS`` names its source;
the ones tagged placeholder were carried over from the team's colon analyzer or chosen by hand and
have not been checked on breast slides, so the page must never show them as validated.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from muffle.memo import per_file
from muffle.report.case_tools import HYPOTHESIS, INFERENCE
from muffle.workspace import card, finding_key, look

TILE_PX, MPP = 224, 0.5
TILE_UM = TILE_PX * MPP                      # 112 µm a side
TILE_MM2 = (TILE_UM / 1000) ** 2             # 0.0125 mm²

# Head classes, from BCSS region codes (meta/gtruth_codes.tsv, CC0): the three immune codes are
# one class; blood, vessels, secretions, mucoid material and "other" are left out of training.
CLASSES = ["tumor", "stroma", "lymphocytes", "necrosis", "fat", "normal_breast", "dcis"]
BCSS_TO_CLASS = {1: "tumor", 2: "stroma", 3: "lymphocytes", 10: "lymphocytes", 11: "lymphocytes",
                 4: "necrosis", 9: "fat", 13: "normal_breast", 20: "dcis"}
LABELS = {"tumor": "Invasive carcinoma", "stroma": "Stroma", "lymphocytes": "Lymphocytes",
          "necrosis": "Necrosis or debris", "fat": "Fat", "normal_breast": "Normal breast",
          "dcis": "In-situ carcinoma (DCIS)"}
COLORS = {"tumor": "#c0392b", "stroma": "#f1c27d", "lymphocytes": "#2e86de", "necrosis": "#2d2d2d",
          "fat": "#fff4b8", "normal_breast": "#7fc97f", "dcis": "#b452cd"}

PLACEHOLDER, LITERATURE, MEASURED, DOC = "placeholder", "literature", "measured", "design"
# name: (value, source tag, where it comes from)
CUTOFFS = {
    "unsure_below": (0.8, PLACEHOLDER, "top probability below this = unsure here; the colon "
                     "analyzer calibrated 0.9 by eye on colon tiles, not transferable"),
    "smooth_size": (3, DOC, "probabilities averaged over a 3×3 tile neighbourhood"),
    "tumor_prob": (0.5, DOC, "tumor = smoothed P(invasive carcinoma) at or above this"),
    "small_hole_tiles": (4, PLACEHOLDER, "holes in the tumor mask up to this many tiles are "
                         "filled"),
    "core_um": (500, DOC, "core = more than 500 µm inside the front"),
    "front_band_um": (500, DOC, "front band = within 500 µm on either side of the front"),
    "peritumoral_um": (2000, DOC, "peritumoral = 0.5 to 2 mm outside the front"),
    "label_purity": (0.5, PLACEHOLDER, "a training tile's BCSS class must cover at least this "
                     "share of its labeled pixels"),
    "glass_edges_max": (0.02, PLACEHOLDER, "glass = fewer than 2% of pixels on a sharp edge; set "
                        "by eye on 980 colon tiles (team's colon analyzer), not re-checked on "
                        "breast"),
    "glass_structure_min": (0.4, PLACEHOLDER, "glass = structure in fewer than 40% of the 4×4 "
                            "sub-blocks; same origin"),
    "ink_bluegreen_min": (0.2, PLACEHOLDER, "pen ink = more than 20% blue/green pixels; same "
                          "origin"),
    "ink_black_min": (0.3, PLACEHOLDER, "pen ink = more than 30% near-black pixels; same origin"),
    "ink_red_min": (0.5, PLACEHOLDER, "pen ink = more than 50% flat saturated red pixels; same "
                    "origin"),
    "blur_rel": (0.1, PLACEHOLDER, "blurry = Laplacian variance below 10% of the region's median; "
                 "same origin"),
}
QC_GLASS, QC_INK, QC_BLUR, QC_OK = "glass", "pen ink", "blur", "ok"

CANNOT_SEE = [
    ("Single cells and tumor budding", "a 112 µm tile is one score; cells are not resolved",
     "a cell-level model at higher resolution, or the pathologist at 40×"),
    ("Nottingham grade", "mitoses and nuclear pleomorphism need more resolution than a tile map",
     "the pathologist's grading on the slide"),
    ("Receptor status (ER, PR, HER2)", "H&E shows no receptor expression",
     "immunohistochemistry on the block"),
    ("Mutations", "a tile map does not read DNA", "tumor sequencing (the genomics workbench)"),
    ("Margins and specimen type", "one region of one section; the specimen edges are not in view",
     "the full slide set and the gross description"),
    ("What happens next", "one section is a 2D snapshot: where the tumor is, not where it is going",
     "follow-up imaging and repeat sampling"),
]


def tissue_grid(tiles: pd.DataFrame, classes: list[str] = CLASSES) -> dict:
    """Arrays indexed [row, col] from a tile table: ``probs`` [H, W, C] (NaN where no tile),
    ``tissue`` (a tile exists), ``usable`` (tissue that passed quality control)."""
    h, w = int(tiles["row"].max()) + 1, int(tiles["col"].max()) + 1
    probs = np.full((h, w, len(classes)), np.nan)
    tissue = np.zeros((h, w), bool)
    usable = np.zeros((h, w), bool)
    r, c = tiles["row"].to_numpy(int), tiles["col"].to_numpy(int)
    probs[r, c] = tiles[[f"p_{k}" for k in classes]].to_numpy(float)
    tissue[r, c] = True
    usable[r, c] = (tiles["qc"] == QC_OK).to_numpy() if "qc" in tiles else True
    return {"probs": probs, "tissue": tissue, "usable": usable, "classes": classes}


def smooth(probs: np.ndarray, usable: np.ndarray, size: int = CUTOFFS["smooth_size"][0]):
    """Mean probability over a size×size neighbourhood of usable tiles (NaN elsewhere)."""
    from scipy import ndimage  # here: opening the app needs none of scipy
    filled = np.where(usable[..., None], probs, 0.0)
    num = ndimage.uniform_filter(filled, size=(size, size, 1), mode="constant")
    den = ndimage.uniform_filter(usable.astype(float), size=size, mode="constant")[..., None]
    out = np.where(den > 0, num / np.maximum(den, 1e-9), np.nan)
    return np.where(usable[..., None], out, np.nan)


def unsure(probs: np.ndarray, usable: np.ndarray,
           cutoff: float = CUTOFFS["unsure_below"][0]) -> np.ndarray:
    """Usable tiles whose top probability is below the cutoff: "unsure here"."""
    top = np.nanmax(np.where(usable[..., None], probs, -1), axis=-1)
    return usable & (top < cutoff)


def tumor_regions(smoothed: np.ndarray, usable: np.ndarray, classes: list[str] = CLASSES) -> dict:
    """Tumor mask from the smoothed invasive-carcinoma probability, small holes filled; the
    largest connected piece is the main tumor, the others satellites."""
    from scipy import ndimage
    p = np.nan_to_num(smoothed[..., classes.index("tumor")], nan=0.0)
    mask = usable & (p >= CUTOFFS["tumor_prob"][0])
    filled = ndimage.binary_fill_holes(mask)
    holes, n = ndimage.label(filled & ~mask)
    if n:
        sizes = ndimage.sum(np.ones_like(mask, int), holes, range(1, n + 1))
        small = np.isin(holes, [i + 1 for i, s in enumerate(sizes)
                                if s <= CUTOFFS["small_hole_tiles"][0]])
        mask = mask | small
    lab, n = ndimage.label(mask)
    if n == 0:
        return {"mask": mask, "main": mask, "satellites": mask, "n_pieces": 0}
    sizes = ndimage.sum(np.ones_like(mask, int), lab, range(1, n + 1))
    main = lab == (int(np.argmax(sizes)) + 1)
    return {"mask": mask, "main": main, "satellites": mask & ~main, "n_pieces": int(n)}


def front_and_zones(main: np.ndarray, tissue: np.ndarray) -> dict:
    """The invasive front (main-tumor tiles with a non-tumor tissue neighbour) and the zones by
    distance to it, in tiles of 112 µm: core, front band (both sides), peritumoral, outside."""
    from scipy import ndimage
    if not main.any():
        empty = np.zeros_like(main)
        return {"front": empty, "zone": np.full(main.shape, "", object), "dist_um": None,
                "front_length_mm": 0.0}
    neighbours = ndimage.binary_dilation(~main & tissue, structure=np.array(
        [[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool))
    front = main & neighbours
    # distance (tiles) to the nearest front tile, signed: negative inside the tumor
    d_out = ndimage.distance_transform_edt(~front)
    dist_um = np.where(main, -d_out, d_out) * TILE_UM
    zone = np.full(main.shape, "", object)
    core, band, peri = (CUTOFFS[k][0] for k in ("core_um", "front_band_um", "peritumoral_um"))
    zone[tissue & main & (dist_um < -core)] = "core"
    zone[tissue & (np.abs(dist_um) <= band)] = "front band"
    zone[tissue & ~main & (dist_um > band) & (dist_um <= peri)] = "peritumoral"
    zone[tissue & ~main & (dist_um > peri)] = "outside"
    zone[~tissue] = ""
    return {"front": front, "zone": zone, "dist_um": dist_um,
            "front_length_mm": round(float(front.sum()) * TILE_UM / 1000, 2)}


def facing(front: np.ndarray, labels: np.ndarray, main: np.ndarray, tissue: np.ndarray) -> dict:
    """What the front faces: the class shares of the non-tumor tiles touching the front."""
    from scipy import ndimage
    ring = ndimage.binary_dilation(front) & ~main & tissue
    vals = labels[ring]
    vals = vals[(vals != "") & (vals != "tumor")]  # tumor-labeled tiles below the mask cutoff
    if vals.size == 0:
        return {}
    names, counts = np.unique(vals, return_counts=True)
    return {str(n): round(float(c) / vals.size, 3) for n, c in
            sorted(zip(names, counts, strict=True), key=lambda t: -t[1])}


def quality(tiles: pd.DataFrame) -> pd.Series:
    """Quality reason per tile from its measures (glass checked before ink, ink before blur, as
    in the colon analyzer's order): ``glass``, ``pen ink``, ``blur`` or ``ok``."""
    c = {k: CUTOFFS[k][0] for k in CUTOFFS}
    glass = ((tiles["edges"] < c["glass_edges_max"])
             | (tiles["structure_cov"] < c["glass_structure_min"]))
    ink = ((tiles["ink_bluegreen"] > c["ink_bluegreen_min"])
           | (tiles["ink_black"] > c["ink_black_min"]) | (tiles["ink_red"] > c["ink_red_min"]))
    stained = tiles.loc[~glass & ~ink, "blur"]
    typical = float(stained.median()) if len(stained) else float(tiles["blur"].median())
    blur = tiles["blur"] < c["blur_rel"] * typical
    out = pd.Series(QC_OK, index=tiles.index, dtype=object)
    out[blur] = QC_BLUR
    out[ink] = QC_INK
    out[glass] = QC_GLASS
    return out


def analyze(tiles: pd.DataFrame, classes: list[str] = CLASSES) -> dict:
    """Everything the page draws, from one tile table: the per-tile frame (label, top probability,
    unsure, zone, on the front, quality) and the summary numbers with their evidence types."""
    tiles = tiles.copy()
    if "qc" not in tiles and {"edges", "structure_cov", "blur"} <= set(tiles.columns):
        tiles["qc"] = quality(tiles)
    g = tissue_grid(tiles, classes)
    sm = smooth(g["probs"], g["usable"])
    top = np.where(g["usable"], np.nanargmax(np.nan_to_num(sm, nan=-1), axis=-1), -1)
    labels = np.where(top >= 0, np.array(classes, object)[np.maximum(top, 0)], "")
    uns = unsure(g["probs"], g["usable"])
    tumor = tumor_regions(sm, g["usable"], classes)
    fz = front_and_zones(tumor["main"], g["tissue"])
    r, c = tiles["row"].to_numpy(int), tiles["col"].to_numpy(int)
    raw_top = tiles[[f"p_{k}" for k in classes]].to_numpy(float)
    tiles["label"] = labels[r, c]
    tiles["top_p"] = raw_top.max(axis=1)
    tiles["unsure"] = uns[r, c]
    tiles["tumor"] = tumor["mask"][r, c]
    tiles["main_tumor"] = tumor["main"][r, c]
    tiles["front"] = fz["front"][r, c]
    tiles["zone"] = fz["zone"][r, c]
    if fz["dist_um"] is not None:
        tiles["dist_to_front_um"] = np.round(fz["dist_um"][r, c], 0)
    usable_n = int(g["usable"].sum())
    fractions = {k: round(float((labels[g["usable"]] == k).mean()), 3) if usable_n else 0.0
                 for k in classes}
    qc_counts = tiles["qc"].value_counts().to_dict() if "qc" in tiles else {}
    summary = {
        "tiles": int(len(tiles)), "usable_tiles": usable_n,
        "excluded": {str(k): int(v) for k, v in qc_counts.items() if k != QC_OK},
        "tissue_fractions": fractions,
        "unsure_share": round(float(uns.sum()) / usable_n, 3) if usable_n else None,
        "tumor_mm2": round(float(tumor["mask"].sum()) * TILE_MM2, 2),
        "main_tumor_mm2": round(float(tumor["main"].sum()) * TILE_MM2, 2),
        "satellite_pieces": max(tumor["n_pieces"] - 1, 0),
        "front_length_mm": fz["front_length_mm"],
        "zone_tiles": {z: int((fz["zone"] == z).sum()) for z in
                       ("core", "front band", "peritumoral", "outside")},
        "facing": facing(fz["front"], labels, tumor["main"], g["tissue"]),
    }
    return {"tiles": tiles, "summary": summary, "grid_shape": list(g["tissue"].shape)}


# --- the workbench contract (docs/WORKBENCHES.md §1): the patient file's overview ----------------
# Read from each scored section's summary.json (scripts/slide_pipeline.py): its numbers and its
# queue are the ones the page recomputes from the tiles (same pointers), without the tiles.

RESULTS = Path(__file__).resolve().parents[3] / "app" / "workbenches" / "slides_results"


@lru_cache(maxsize=32)
def _meta(folder: Path) -> dict | None:
    path = folder / "summary.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def sections(pf, version: int | None = None, results: Path = RESULTS) -> list[dict]:
    """The patient's own scored sections as of report version ``version`` (the latest when
    None): each {"slide", "meta" (its summary.json), "opens" (the slide test, the shape of
    ``Alert.opens``)}. [] when the file has none (its slide test shows a public example)."""
    vs = pf.versions[: len(pf.versions) if version is None else version + 1]
    out = []
    for t in (t for v in vs for t in v.tests if t.workbench == "slides"):
        for name in t.details.get("slides", ()):
            meta = _meta(results / name)
            if meta is not None:
                out.append({"slide": name, "meta": meta,
                            "opens": ("Tests", t.kind, t.month, t.name)})
    return out


def _head(meta: dict) -> str:
    head, nuc = meta.get("head", {}), meta.get("nuclei", {})
    encoder = meta.get("encoder", {}).get("name")
    return (f"{len(head.get('classes', []))}-class BCSS head on {encoder} embeddings (held-out "
            f"accuracy {head.get('accuracy', 0):.1%} on "
            f"{head.get('held_out', 'held-out slides')}); {nuc.get('model') or 'no'} nuclei on "
            f"the front band; method version {meta.get('method_version', '?')}")


@per_file
def summary(pf, version: int | None = None) -> dict:
    """The slide picture of the section with the largest main tumor: its area, infiltrative arcs,
    breakaway candidates and immune pattern."""
    secs = sections(pf, version)
    if not secs:
        example = any(t.workbench == "slides" for t in pf.tests)
        return {"workbench": "slides", "title": "Pathology slide", "cards": [], "note": (
            "no scored section of this tumor: the slide workbench shows a public example region"
            if example else "no slide in this file")}
    s = max(secs, key=lambda s: s["meta"].get("analysis", {}).get("main_tumor_mm2", 0))
    m, n = s["meta"], s["meta"].get("numbers", {})
    where = (f"section {s['slide']}" + (f", the largest tumor of {len(secs)} sections"
                                         if len(secs) > 1 else ""))
    if not n.get("arcs"):
        text = f"no tumor front found in {where}: nothing to measure at a front"
    else:
        buds = n.get("buds_in_field")
        text = (f"main tumor {m['analysis']['main_tumor_mm2']} mm² ({where}); "
                f"{n['infiltrative_arcs']} of {n['arcs']} front arcs infiltrative; "
                + (f"{buds} breakaway candidate cluster(s) in the 0.785 mm² counting field"
                   if buds is not None else "no breakaway count") +
                f"; immune pattern: {n.get('immune_pattern')}")
    return {"workbench": "slides", "title": "Pathology slide", "note": None, "cards": [card(
        "Slide picture", text, f"{INFERENCE} (tile classes, nuclei), {HYPOTHESIS} (front "
        "pattern)", f"Pathology slide {s['slide']} (the patient's own section)", _head(m),
        "placeholder cutoffs (front pattern, immune pattern); the counting field from the ITBCC "
        "(literature)", "weak", s["opens"], {"slide": s["slide"]})]}


@per_file
def queue(pf, version: int | None = None) -> list[dict]:
    """Each section's look-here pointers T1…Tn (risk regions, the counting field, the roughest
    arc, islands, the most unsure spot). The map is not validated on breast nuclei nor reviewed
    by a pathologist: trust weak, consequence 1 (worth a look)."""
    secs, out = sections(pf, version), []
    for s in secs:
        for q in s["meta"].get("queue", []):
            tile = f"r{q['row']}c{q['col']}"
            out.append(look(
                q["pointer"], q["what"] + (f" · {s['slide']}" if len(secs) > 1 else ""),
                f"{q['why']}; check by eye: {q['check']}", q["evidence"], "weak", 1, s["opens"],
                source=f"Pathology slide {s['slide']}", key=finding_key(pf, "slide", s["slide"],
                                                                        tile),
                focus={"slide": s["slide"], "pointer": q["pointer"], "tile": tile},
                threshold=q["status"]))
    return out


def load_result(folder: str | Path) -> dict | None:
    """A precomputed slide result folder: ``tiles.json`` (records), ``summary.json`` (slide,
    region, head card) and ``thumbnail.jpg``; None if it isn't there."""
    folder = Path(folder)
    if not (folder / "tiles.json").exists():
        return None
    meta_path = folder / "summary.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
    return {"tiles": pd.read_json(folder / "tiles.json", orient="records"), "meta": meta,
            "thumbnail": folder / "thumbnail.jpg" if (folder / "thumbnail.jpg").exists() else None}

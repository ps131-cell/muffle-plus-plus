"""Pathology slide workbench, round 2: the invasion picture on one slide's tile table
(docs/WORKBENCHES.md §5, docs/pathology.md).

Everything here is numpy and scipy arithmetic on the columns ``muffle.workbench.slides.analyze``
produces (tile class probabilities, the tumor mask, its front and zones) plus, where the
pipeline ran StarDist, per-tile nuclei counts. No model runs in the app.

Evidence types: tiles and nuclei are **model inferences** (the tissue head; StarDist); the front
normals, arcs, fingers, islands, counting field and risk points are geometry and rules on those
inferences; the direction of invasion is a **hypothesis** about this section: a 2D snapshot of
where the tumor is invading in this section, not a forecast. Every cutoff in ``CUTOFFS`` names
its source and the placeholders are tagged; the page must never show one as validated.
"""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from muffle.lazy import module
from muffle.workbench.slides import (
    CLASSES,
    DOC,
    LABELS,
    LITERATURE,
    PLACEHOLDER,
    QC_OK,
    TILE_MM2,
    TILE_UM,
    analyze,
)

# scipy loads on first use: the report reads only CUTOFFS and the compass from this module
ndimage = module("scipy.ndimage")


def cKDTree(*args, **kwargs):  # noqa: N802 (scipy's name)
    from scipy.spatial import cKDTree as tree

    return tree(*args, **kwargs)


INFERENCE, HYPOTHESIS, OBSERVED = "model inference", "hypothesis", "observed"

# name: (value, source tag, where it comes from)
CUTOFFS = {
    "normal_sigma_tiles": (2, DOC, "the outward normal of the front is the gradient of the main "
                           "tumor mask blurred by 2 tiles (224 µm)"),
    "push_depth_tiles": (3, DOC, "push = mean smoothed P(invasive carcinoma) over the 3 tiles "
                         "outward along the normal; 0 = sharp edge, near 0.5 = tumor fading "
                         "into the tissue"),
    "sectors": (12, DOC, "the front is cut into 12 arcs of 30° around the main tumor's centroid"),
    "finger_radius_tiles": (2, PLACEHOLDER, "fingers = main-tumor tiles that a morphological "
                            "opening of radius 2 tiles (224 µm) removes; the radius was chosen "
                            "by eye, not calibrated"),
    "infiltrative_arc": (0.3, PLACEHOLDER, "an arc is infiltrative when at least 30% of its "
                         "front tiles lie in fingers; pushing otherwise"),
    "tumor_nucleus_p": (0.5, PLACEHOLDER, "a nucleus that is not lymphocyte-like is a tumor "
                        "candidate when its tile's raw P(invasive carcinoma) is at least 0.5"),
    "bud_tile_p": (0.3, PLACEHOLDER, "a front-band tile outside the main tumor mask is searched "
                   "for breakaway clusters when its raw P(invasive carcinoma) is at least 0.3"),
    "tumor_nucleus_area_um2": (40, PLACEHOLDER, "a tumor-candidate nucleus has an area of at "
                               "least 40 µm²; smaller non-round nuclei (fibroblasts, "
                               "endothelium) are left out of the clusters"),
    "lymph_area_um2": (45, PLACEHOLDER, "lymphocyte-like = nuclear area at most 45 µm² and "
                       "solidity at least 0.9; a small round dark nucleus, not a cell type"),
    "lymph_solidity": (0.9, PLACEHOLDER, "see lymph_area_um2"),
    "bud_link_um": (20, PLACEHOLDER, "tumor-candidate nuclei within 20 µm of each other form "
                    "one cluster (single linkage)"),
    "bud_max_nuclei": (4, LITERATURE, "a bud is a cluster of up to 4 tumor cells (ITBCC 2016, "
                       "Lugli et al., Mod Pathol 2017; defined for colorectal cancer)"),
    "field_mm2": (0.785, LITERATURE, "the ITBCC counting field: one 20× objective field, "
                  "0.785 mm² (Lugli et al. 2017)"),
    "til_proximity_um": (50, PLACEHOLDER, "a lymphocyte-like nucleus within 50 µm of a tumor "
                         "candidate counts as tumor-contacting"),
    "tsr_stroma_high": (0.5, LITERATURE, "stroma-high = stroma over 50% of tumor-plus-stroma "
                        "tiles (tumor–stroma ratio; van Pelt et al., Histopathology 2018, "
                        "colorectal; Mesker et al. 2007); a tile count, not their visual method"),
    "immune_desert": (0.05, PLACEHOLDER, "immune desert = lymphocyte-class tiles under 5% of "
                      "the core and the front band"),
    "immune_excluded": (2.0, PLACEHOLDER, "immune excluded = the front band's lymphocyte share "
                        "at least twice the core's, with the core under 5%"),
    "risk_radius_um": (1000, DOC, "a tile collects a feature's points when the feature lies "
                       "within 1 mm"),
    "risk_level_2": (3, PLACEHOLDER, "level 2 at 3 points"),
    "risk_level_3": (5, PLACEHOLDER, "level 3 at 5 points"),
    "nuclei_cv_min": (5, DOC, "nuclear-area variation needs at least 5 non-lymphocyte nuclei"),
    "til_cutoff_fallback": (0.5, PLACEHOLDER, "the second lymphocyte model's cutoff when its "
                            "result file carries none (the pipeline writes the calibrated one)"),
    "disagree_min_tiles": (3, DOC, "the queue points at the densest disagreement only when at "
                           "least 3 scored tiles disagree"),
}
RISK_POINTS = {  # feature -> points; all placeholders (docs/pathology.md)
    "infiltrative arc": 2, "breakaway candidates": 2, "faces fat": 1, "satellite island": 1,
    "necrosis contact": 1, "immune-poor front": 1,
}
FIELD_RADIUS_TILES = math.sqrt(CUTOFFS["field_mm2"][0] / math.pi) * 1000 / TILE_UM  # 4.46

CANNOT_SEE = [
    ("Nottingham grade", "mitoses and tubule formation are not scored; nuclear-area variation "
     "is a proxy, never a grade", "the pathologist's grading on the slide"),
    ("Receptor status (ER, PR, HER2)", "H&E shows no receptor expression",
     "immunohistochemistry on the block"),
    ("Mutations", "a tile map does not read DNA", "tumor sequencing (the genomics workbench)"),
    ("Margins and specimen type", "one diagnostic section; the specimen edges and the gross "
     "description are not in view", "the full slide set and the pathology report"),
    ("Lymphovascular invasion", "vessels are not a class of the head and nuclei alone cannot "
     "tell a vessel from a cleft", "the pathologist at 20× and 40×; an endothelial stain"),
    ("What happens next", "arrows show where the tumor is invading in this section, a 2D "
     "snapshot, not where it will go", "follow-up imaging and repeat sampling"),
]

TIL_SECOND = ("WSInfer TIL InceptionV4 (kaczmarj/pancancer-lymphocytes-inceptionv4.tcga; "
              "Abousamra et al., Front Oncol 2022; CC BY 4.0), the centre 50 µm of a tile, trained "
              "on TCGA slides so the held-out BCSS slides may overlap its training set")

KNOWN_FAILURES = [
    "Normal breast and in-situ carcinoma are not in the head: their tiles get one of the five "
    "classes, usually invasive carcinoma or stroma, so a benign duct can be read as tumor.",
    "A tile border can cut a tumor nest in two: nuclei at the edge of a nest can be counted as "
    "a breakaway cluster in the neighbouring tile.",
    "StarDist 2D_versatile_he is pretrained on other organs and scanners and not validated on "
    "breast here: dense lymphocyte sheets and dark pyknotic nuclei are over-segmented, pale "
    "nuclei missed.",
    "The lymphocyte-like rule is size and shape only: small stromal, endothelial and apoptotic "
    "nuclei count as lymphocytes.",
    "Where the pipeline scored a tumor-centred window rather than the whole slide, tumor "
    "outside the window is not in the map; the summary says how much tissue was not scored.",
    "Pen ink, folds and out-of-focus tiles are excluded by placeholder rules set on colon slides; "
    "an excluded tile inside the tumor leaves a hole in the mask (small holes are filled).",
    "The front normals come from a blurred mask: on a front thinner than two tiles the arrow "
    "direction is unstable.",
    "Tissue the head was not trained on (muscle, cautery-crushed margins, nerve, vessels) is "
    "read as one of its five classes, often invasive carcinoma. Tiles unlike every training tile "
    "are not scored (a calibrated rule), but the rule misses some: on TCGA-EW-A1J2-DX1 small "
    "fragments on crushed margin tissue still read as carcinoma. Check small tumor pieces by "
    "eye.",
    "On a section with little carcinoma, collagen and loose stroma can be read as invasive "
    "carcinoma: on TCGA-PL-A8LZ-DX1 several hundred such tiles form small false tumor pieces, "
    "flagged by a high unsure share.",
]

MODEL_CARD = {
    "tissue head": "logistic regression on frozen GigaPath-Flash (Prov-GigaPath's tile encoder "
                   "distilled to a ViT-S/16, Apache-2.0) tile embeddings; trained on BCSS (CC0) "
                   "tiles of 8 TCGA-BRCA slides, held out on 3 patient-disjoint slides; the "
                   "numbers on this page are those held-out numbers; tiles unlike every "
                   "training tile (cosine distance to the 5 nearest of its 1,052 training tiles "
                   "above a calibrated cutoff) are not scored",
    "nuclei": "StarDist 2D_versatile_he (Schmidt et al., MICCAI 2018; Weigert et al., WACV "
              "2020; BSD-3-Clause), pretrained, run on the tile at the slide's own resolution; "
              "not validated on breast here: counts are model inferences without a measured "
              "error",
    "geometry": "front, zones, normals, arcs, fingers, islands, counting field and risk points "
                "are deterministic rules on the tiles (this module, version 0.2)",
    "review": "not reviewed by a pathologist",
}


# --- grids ---------------------------------------------------------------------------------

def grid(tiles: pd.DataFrame, col: str, fill=0.0, dtype=float) -> np.ndarray:
    """A [rows, cols] array of one tile column (``fill`` where no tile)."""
    h, w = int(tiles["row"].max()) + 1, int(tiles["col"].max()) + 1
    g = np.full((h, w), fill, dtype)
    g[tiles["row"].to_numpy(int), tiles["col"].to_numpy(int)] = tiles[col].to_numpy()
    return g


def disk(radius: float) -> np.ndarray:
    r = int(math.ceil(radius))
    y, x = np.ogrid[-r:r + 1, -r:r + 1]
    return (y ** 2 + x ** 2) <= radius ** 2


def within(feature: np.ndarray, radius_tiles: float) -> np.ndarray:
    """True where the feature occurs within the radius (a disk dilation)."""
    if not feature.any():
        return np.zeros_like(feature, bool)
    return ndimage.binary_dilation(feature, structure=disk(radius_tiles))


# --- direction of invasion -----------------------------------------------------------------

def front_normals(main: np.ndarray, front: np.ndarray, p_tumor: np.ndarray, tissue: np.ndarray,
                  sigma: float = CUTOFFS["normal_sigma_tiles"][0],
                  depth: int = CUTOFFS["push_depth_tiles"][0]) -> pd.DataFrame:
    """Per front tile: the outward unit normal (``ny``, ``nx`` in grid steps, y down), its
    compass angle (degrees, 0 = right, 90 = up) and the push: mean smoothed P(invasive) over
    ``depth`` tiles outward along the normal (tissue outside the main mask only)."""
    rows, cols = np.nonzero(front)
    if len(rows) == 0:
        return pd.DataFrame(columns=["row", "col", "ny", "nx", "angle", "push"])
    blurred = ndimage.gaussian_filter(main.astype(float), sigma)
    gy, gx = np.gradient(blurred)
    ny, nx = -gy, -gx  # the mask rises inward, so minus the gradient points outward
    norm = np.hypot(ny, nx)
    norm[norm == 0] = 1.0
    ny, nx = ny / norm, nx / norm
    p = np.nan_to_num(p_tumor, nan=0.0)
    push = np.zeros(len(rows))
    for i, (r, c) in enumerate(zip(rows, cols, strict=True)):
        vals = []
        for k in range(1, depth + 1):
            rr, cc = int(round(r + k * ny[r, c])), int(round(c + k * nx[r, c]))
            if (0 <= rr < main.shape[0] and 0 <= cc < main.shape[1] and tissue[rr, cc]
                    and not main[rr, cc]):
                vals.append(p[rr, cc])
        push[i] = float(np.mean(vals)) if vals else 0.0
    angle = np.degrees(np.arctan2(-ny[rows, cols], nx[rows, cols])) % 360
    return pd.DataFrame({"row": rows, "col": cols, "ny": ny[rows, cols], "nx": nx[rows, cols],
                         "angle": np.round(angle, 1), "push": np.round(push, 3)})


def fingers(main: np.ndarray, radius: int = CUTOFFS["finger_radius_tiles"][0]) -> dict:
    """Main-tumor tiles that a morphological opening removes: thin protrusions ("fingers").
    A tumor the opening removes entirely is too small to judge (no fingers, ``judged`` False)."""
    opened = ndimage.binary_opening(main, structure=disk(radius))
    if not opened.any():
        return {"mask": np.zeros_like(main), "n": 0, "judged": False}
    f = main & ~opened
    _, n = ndimage.label(f)
    return {"mask": f, "n": int(n), "judged": True}


def _circular_mean(angles_deg: np.ndarray, weights: np.ndarray | None = None) -> float:
    w = np.ones_like(angles_deg, float) if weights is None else np.asarray(weights, float)
    if w.sum() <= 0:
        w = np.ones_like(angles_deg, float)
    a = np.radians(angles_deg)
    return float(np.degrees(np.arctan2((w * np.sin(a)).sum(), (w * np.cos(a)).sum())) % 360)


def arcs(normals: pd.DataFrame, main: np.ndarray, labels: np.ndarray, tissue: np.ndarray,
         finger_mask: np.ndarray, n_sectors: int = CUTOFFS["sectors"][0]) -> list[dict]:
    """The front cut into arcs by angle around the main tumor's centroid. Per arc: its length,
    mean direction of invasion (push-weighted circular mean of the normals), mean push, the
    share of its tiles in fingers (roughness) and the pattern that follows, and what it faces
    (class shares of the non-tumor tissue tiles touching its front tiles)."""
    if normals.empty:
        return []
    cy, cx = ndimage.center_of_mass(main)
    pos = np.degrees(np.arctan2(-(normals["row"] - cy), normals["col"] - cx)) % 360
    width = 360 / n_sectors
    sector = np.minimum((pos // width).astype(int), n_sectors - 1)
    cross = np.array([[0, 1, 0], [1, 1, 1], [0, 1, 0]], bool)
    out = []
    for s in range(n_sectors):
        sel = normals[sector == s]
        if sel.empty:
            continue
        here = np.zeros_like(main)
        here[sel["row"].to_numpy(int), sel["col"].to_numpy(int)] = True
        ring = ndimage.binary_dilation(here, structure=cross) & ~main & tissue
        vals = labels[ring]
        vals = vals[(vals != "") & (vals != "tumor")]
        faces = {}
        if vals.size:
            names, counts = np.unique(vals, return_counts=True)
            faces = {str(n): round(float(c) / vals.size, 3) for n, c in
                     sorted(zip(names, counts, strict=True), key=lambda t: -t[1])}
        rough = float(finger_mask[sel["row"].to_numpy(int), sel["col"].to_numpy(int)].mean())
        out.append({
            "arc": f"A{len(out) + 1}", "from_deg": int(s * width), "to_deg": int((s + 1) * width),
            "tiles": int(len(sel)), "length_mm": round(len(sel) * TILE_UM / 1000, 2),
            "direction_deg": round(_circular_mean(sel["angle"].to_numpy(),
                                                  sel["push"].to_numpy()), 0),
            "push": round(float(sel["push"].mean()), 3), "roughness": round(rough, 3),
            "pattern": "infiltrative" if rough >= CUTOFFS["infiltrative_arc"][0] else "pushing",
            "faces": faces, "faces_top": next(iter(faces), "nothing"),
            "row": round(float(sel["row"].mean()), 1), "col": round(float(sel["col"].mean()), 1),
        })
    return out


def rose(normals: pd.DataFrame, n_bins: int = CUTOFFS["sectors"][0]) -> list[dict]:
    """Direction histogram of the front normals, push-weighted: where this section's front is
    pointing and how much tumor probability lies beyond it."""
    width = 360 / n_bins
    out = []
    for b in range(n_bins):
        sel = normals[(normals["angle"] >= b * width) & (normals["angle"] < (b + 1) * width)]
        out.append({"from_deg": b * width, "to_deg": (b + 1) * width, "tiles": int(len(sel)),
                    "push_sum": round(float(sel["push"].sum()), 2),
                    "push_mean": round(float(sel["push"].mean()), 3) if len(sel) else 0.0})
    return out


def compass(deg: float) -> str:
    names = ["right", "upper right", "up", "upper left", "left", "lower left", "down",
             "lower right"]
    return names[int(((deg + 22.5) % 360) // 45)]


# --- satellite islands ---------------------------------------------------------------------

def satellite_islands(mask: np.ndarray, main: np.ndarray, labels: np.ndarray) -> list[dict]:
    """Every tumor piece other than the main one: size, distance to the main tumor (nearest
    tiles, µm) and the tissue on the straight line between them."""
    sat = mask & ~main
    lab, n = ndimage.label(sat)
    if n == 0 or not main.any():
        return []
    d_main, idx = ndimage.distance_transform_edt(~main, return_indices=True)
    out = []
    for i in range(1, n + 1):
        isl = lab == i
        rr, cc = np.nonzero(isl)
        j = int(np.argmin(d_main[isl]))
        r0, c0 = int(rr[j]), int(cc[j])
        r1, c1 = int(idx[0][r0, c0]), int(idx[1][r0, c0])
        steps = int(max(abs(r1 - r0), abs(c1 - c0)))
        between = [str(labels[int(round(r0 + (r1 - r0) * t / steps)),
                              int(round(c0 + (c1 - c0) * t / steps))])
                   for t in range(1, steps)] if steps > 1 else []
        between = [b for b in between if b]
        shares = {}
        if between:
            names, counts = np.unique(between, return_counts=True)
            shares = {str(k): round(float(v) / len(between), 2) for k, v in
                      sorted(zip(names, counts, strict=True), key=lambda t: -t[1])}
        out.append({"island": f"S{i}", "tiles": int(isl.sum()),
                    "area_mm2": round(float(isl.sum()) * TILE_MM2, 3),
                    "distance_um": int(round(float(d_main[r0, c0]) * TILE_UM)),
                    "row": round(float(rr.mean()), 1), "col": round(float(cc.mean()), 1),
                    "between": next(iter(shares), "touching"), "between_shares": shares})
    return sorted(out, key=lambda d: -d["distance_um"])


# --- cells: nuclei summaries (pipeline side) and the counting field (both sides) -----------

def lymphocyte_like(nuclei: pd.DataFrame) -> np.ndarray:
    """Small round nuclei (placeholder rule on area and solidity)."""
    return ((nuclei["area_um2"] <= CUTOFFS["lymph_area_um2"][0])
            & (nuclei["solidity"] >= CUTOFFS["lymph_solidity"][0])).to_numpy()


def clusters(xy: np.ndarray, link_um: float = CUTOFFS["bud_link_um"][0]) -> np.ndarray:
    """Single-linkage cluster labels of points (µm): points within ``link_um`` join."""
    n = len(xy)
    if n == 0:
        return np.zeros(0, int)
    pairs = cKDTree(xy).query_pairs(link_um, output_type="ndarray")
    parent = np.arange(n)

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    roots = np.array([find(i) for i in range(n)])
    _, lab = np.unique(roots, return_inverse=True)
    return lab


def nuclei_summary(nuclei: pd.DataFrame, tiles: pd.DataFrame, ran: pd.DataFrame) -> pd.DataFrame:
    """Per-tile nuclei counts from a nucleus table (one row per nucleus: ``row``, ``col`` of its
    tile, ``x_um``, ``y_um`` inside the tile, ``area_um2``, ``solidity``) for the tiles StarDist
    ran on (``ran``: rows with ``row``, ``col``). ``tiles`` is ``analyze``'s frame (``p_tumor``,
    ``main_tumor``, ``zone``). Columns: n_nuclei, n_lymph, n_tumor_nuc, n_lymph_near_tumor,
    buds (front-band tiles outside the main tumor only), nuc_area_cv; zero or NaN where nothing
    was found."""
    t = tiles.set_index(["row", "col"])
    rows = []
    groups = {k: g for k, g in nuclei.groupby(["row", "col"])} if len(nuclei) else {}
    for r, c in ran[["row", "col"]].itertuples(index=False):
        g = groups.get((r, c))
        p = float(t.loc[(r, c), "p_tumor"])
        inside = bool(t.loc[(r, c), "main_tumor"])
        rec = {"row": int(r), "col": int(c), "n_nuclei": 0, "n_lymph": 0, "n_tumor_nuc": 0,
               "n_lymph_near_tumor": 0, "buds": 0, "nuc_area_cv": np.nan}
        if g is not None and len(g):
            lymph = lymphocyte_like(g)
            big = (g["area_um2"] >= CUTOFFS["tumor_nucleus_area_um2"][0]).to_numpy()
            tumor_cand = ~lymph & big & (p >= CUTOFFS["tumor_nucleus_p"][0])
            xy = g[["x_um", "y_um"]].to_numpy(float)
            rec.update(n_nuclei=int(len(g)), n_lymph=int(lymph.sum()),
                       n_tumor_nuc=int(tumor_cand.sum()))
            if lymph.any() and tumor_cand.any():
                d, _ = cKDTree(xy[tumor_cand]).query(xy[lymph])
                rec["n_lymph_near_tumor"] = int((d <= CUTOFFS["til_proximity_um"][0]).sum())
            band = str(t.loc[(r, c), "zone"]) == "front band" if "zone" in t else True
            if not inside and band and p >= CUTOFFS["bud_tile_p"][0] and (~lymph & big).sum():
                lab = clusters(xy[~lymph & big])
                sizes = np.bincount(lab)
                rec["buds"] = int((sizes <= CUTOFFS["bud_max_nuclei"][0]).sum())
            areas = g.loc[~lymph, "area_um2"].to_numpy(float)
            if len(areas) >= CUTOFFS["nuclei_cv_min"][0] and areas.mean() > 0:
                rec["nuc_area_cv"] = round(float(areas.std() / areas.mean()), 3)
        rows.append(rec)
    return pd.DataFrame(rows, columns=["row", "col", "n_nuclei", "n_lymph", "n_tumor_nuc",
                                       "n_lymph_near_tumor", "buds", "nuc_area_cv"])


def hotspot_field(tiles: pd.DataFrame) -> dict | None:
    """The ITBCC-style counting field (0.785 mm², radius 0.5 mm) placed where the breakaway
    candidates within it are most numerous; None when no tile was counted or none has a
    candidate. Reports how much of the field was actually counted."""
    if "buds" not in tiles or tiles["buds"].notna().sum() == 0:
        return None
    buds = grid(tiles.fillna({"buds": 0}), "buds")
    counted = grid(tiles.assign(c=tiles["buds"].notna().astype(float)), "c") > 0
    k = disk(FIELD_RADIUS_TILES).astype(float)
    in_field = ndimage.convolve(buds, k, mode="constant")
    if in_field.max() <= 0:
        return None
    # the field must be centred on a counted tile
    in_field[~counted] = -1
    r, c = np.unravel_index(int(np.argmax(in_field)), in_field.shape)
    cov = ndimage.convolve(counted.astype(float), k, mode="constant")[r, c] / k.sum()
    return {"row": int(r), "col": int(c), "buds_in_field": int(round(in_field[r, c])),
            "field_mm2": CUTOFFS["field_mm2"][0], "coverage": round(float(cov), 2),
            "radius_tiles": round(FIELD_RADIUS_TILES, 2)}


# --- the second opinion on lymphocytes ------------------------------------------------------

def til_disagreement(tiles: pd.DataFrame, cutoff: float | None = None) -> dict:
    """Where the tissue head and the second lymphocyte model disagree, on the tiles the second
    model scored (``p_til``): the head says lymphocytes when its label is lymphocytes; the
    second model when its probability reaches the cutoff. Returns the counts, the share of
    scored tiles that disagree, Cohen's kappa, and the disagreeing rows."""
    if "p_til" not in tiles or tiles["p_til"].notna().sum() == 0:
        return {"scored": 0, "agree": 0, "disagree": 0, "share": None, "kappa": None,
                "head_only": 0, "til_only": 0, "cutoff": cutoff, "rows": tiles.iloc[0:0]}
    cutoff = CUTOFFS["til_cutoff_fallback"][0] if cutoff is None else float(cutoff)
    t = tiles[tiles["p_til"].notna()]
    if "qc" in t:
        t = t[t["qc"] == QC_OK]
    head = (t["label"] == "lymphocytes").to_numpy()
    til = (t["p_til"] >= cutoff).to_numpy()
    n = len(t)
    agree = int((head == til).sum())
    po = agree / n if n else 0.0
    pe = (head.mean() * til.mean() + (1 - head.mean()) * (1 - til.mean())) if n else 0.0
    kappa = round(float((po - pe) / (1 - pe)), 3) if n and pe < 1 else None
    return {"scored": n, "agree": agree, "disagree": n - agree,
            "share": round(float((n - agree) / n), 3) if n else None, "kappa": kappa,
            "head_only": int((head & ~til).sum()), "til_only": int((~head & til).sum()),
            "cutoff": cutoff, "rows": t[head != til]}


# --- immune pattern, tumor-stroma ratio, necrosis -------------------------------------------

def immune_by_zone(tiles: pd.DataFrame, til_cutoff: float | None = None) -> dict:
    """Stromal lymphocytes by zone, two ways: the head's lymphocyte-class share of the usable
    tiles (every tile), and where nuclei were counted, lymphocyte-like nuclei per mm² of
    stroma-or-lymphocyte tiles and the share of them within 50 µm of a tumor candidate. The
    pattern (desert, excluded, inflamed) follows placeholder cutoffs on the tile shares. A proxy
    in the International TILs Working Group's zones, not its area-percentage method."""
    usable = tiles[tiles["qc"] == QC_OK] if "qc" in tiles else tiles
    zones = {}
    for z in ("core", "front band", "peritumoral"):
        tz = usable[usable["zone"] == z]
        rec = {"tiles": int(len(tz)),
               "lymph_tile_share": round(float((tz["label"] == "lymphocytes").mean()), 3)
               if len(tz) else None}
        if "n_lymph" in tz:
            rec["nuclei_tiles"] = int(tz["n_nuclei"].notna().sum())  # coverage, any class
            counted = tz[tz["n_nuclei"].notna() & tz["label"].isin(["stroma", "lymphocytes"])]
            rec["counted_tiles"] = int(len(counted))
            if len(counted):
                rec["lymph_nuclei_per_mm2"] = int(round(counted["n_lymph"].sum()
                                                        / (len(counted) * TILE_MM2)))
                total = counted["n_lymph"].sum()
                rec["tumor_contacting_share"] = (
                    round(float(counted["n_lymph_near_tumor"].sum() / total), 2) if total else None)
        if "p_til" in tz:  # the second model, where it scored
            scored = tz[tz["p_til"].notna()]
            rec["til_scored_tiles"] = int(len(scored))
            if len(scored):
                c = CUTOFFS["til_cutoff_fallback"][0] if til_cutoff is None else til_cutoff
                rec["til_lymph_share"] = round(float((scored["p_til"] >= c).mean()), 3)
        zones[z] = rec
    core, band = zones["core"]["lymph_tile_share"], zones["front band"]["lymph_tile_share"]
    desert, excl = CUTOFFS["immune_desert"][0], CUTOFFS["immune_excluded"][0]
    if band is None:
        pattern = "no front: not assessed"
    elif core is None:
        pattern = ("desert (no core: front band only)" if band < desert
                   else "inflamed (no core: front band only)")
    elif core < desert and band < desert:
        pattern = "desert"
    elif core < desert and band >= excl * max(core, 1e-9):
        pattern = "excluded"
    else:
        pattern = "inflamed"
    return {"zones": zones, "pattern": pattern, "evidence": INFERENCE,
            "status": "placeholder cutoffs on tile shares; nuclei counts are StarDist "
                      "inferences, not validated on breast"}


ZONES = ("core", "front band", "peritumoral")
ZONE_CLASSES = ("tumor", "stroma", "lymphocytes", "necrosis", "fat")  # the head's other classes
# (normal breast, DCIS) count as "other"
ZONE_PRECEDENT = ("tissue compartments read separately on H&E, as in Mittal et al. 2019 (Front "
                  "Bioeng Biotechnol 7:246, doi:10.3389/fbioe.2019.00246); their clustering "
                  "measure is not used here")


TSR_ECM3_HYPOTHESIS = (
    "In one 42-tumor, single-centre infrared study the collagen at tumor borders carried the "
    "ECM3 stromal signature, and ECM3 grade III tumors fared worst (Tiwari et al. 2020, Sci Rep "
    "10:5442, doi:10.1038/s41598-020-62403-2; AUC 0.87, not validated externally). Here only "
    "the H&E stroma share is measured, not the collagen's chemistry; the omics workbench shows "
    "the ECM3 genes where RNA was sequenced.")


def tissue_by_zone(tiles: pd.DataFrame) -> dict:
    """Each zone's class shares of its usable tiles (the head's labels): {zone: {"tiles",
    "shares": {class: share}, "other"}}; a zone without tiles has shares None. Model inference
    on tile labels, a description, never a cutoff."""
    usable = tiles[tiles["qc"] == QC_OK] if "qc" in tiles else tiles
    out = {}
    for z in ZONES:
        tz = usable[usable["zone"] == z]
        n = int(len(tz))
        shares = ({c: round(float((tz["label"] == c).mean()), 3) for c in ZONE_CLASSES}
                  if n else None)
        out[z] = {"tiles": n, "shares": shares,
                  "other": round(1 - sum(shares.values()), 3) if shares else None}
    return out


def tumor_stroma(tiles: pd.DataFrame) -> dict:
    """Stroma share of tumor-plus-stroma tiles inside the main tumor and its front band."""
    region = tiles[(tiles["main_tumor"]) | (tiles["zone"] == "front band")]
    region = region[region["qc"] == QC_OK] if "qc" in region else region
    t, s = int((region["label"] == "tumor").sum()), int((region["label"] == "stroma").sum())
    if t + s == 0:
        return {"stroma_share": None, "verdict": "not assessed", "tumor_tiles": t,
                "stroma_tiles": s}
    share = s / (t + s)
    return {"stroma_share": round(share, 3), "tumor_tiles": t, "stroma_tiles": s,
            "verdict": "stroma-high" if share > CUTOFFS["tsr_stroma_high"][0] else "stroma-low"}


def necrosis_contact(tiles: pd.DataFrame, tumor: np.ndarray, labels: np.ndarray) -> dict:
    nec = labels == "necrosis"
    touching = nec & ndimage.binary_dilation(tumor)
    return {"necrosis_tiles": int(nec.sum()), "necrosis_mm2": round(float(nec.sum()) * TILE_MM2, 3),
            "touching_tumor_tiles": int(touching.sum()),
            "share_touching": round(float(touching.sum() / nec.sum()), 2) if nec.any() else None,
            "mask": touching}


# --- risk map, cards, queue -----------------------------------------------------------------

def risk_map(tiles: pd.DataFrame, arc_list: list[dict], normals: pd.DataFrame, front: np.ndarray,
             main: np.ndarray, mask: np.ndarray, labels: np.ndarray, tissue: np.ndarray,
             necrosis_mask: np.ndarray) -> dict:
    """Points per feature within 1 mm of a tile (``RISK_POINTS``), the level per tile and one
    card per region at level 2 or more. Every point value is a placeholder."""
    h, w = main.shape
    feats = {k: np.zeros((h, w), bool) for k in RISK_POINTS}
    if not normals.empty:
        cy, cx = ndimage.center_of_mass(main)
        pos = np.degrees(np.arctan2(-(normals["row"] - cy), normals["col"] - cx)) % 360
        for a in arc_list:
            sel = normals[(pos >= a["from_deg"]) & (pos < a["to_deg"])]
            rr, cc = sel["row"].to_numpy(int), sel["col"].to_numpy(int)
            if a["pattern"] == "infiltrative":
                feats["infiltrative arc"][rr, cc] = True
            if a["faces_top"] == "fat":
                feats["faces fat"][rr, cc] = True
            if a["faces"].get("lymphocytes", 0.0) < CUTOFFS["immune_desert"][0]:
                feats["immune-poor front"][rr, cc] = True
    if "buds" in tiles:
        feats["breakaway candidates"] = grid(tiles.fillna({"buds": 0}), "buds") > 0
    feats["satellite island"] = mask & ~main
    feats["necrosis contact"] = necrosis_mask
    radius = CUTOFFS["risk_radius_um"][0] / TILE_UM
    points = np.zeros((h, w), float)
    for k, pts in RISK_POINTS.items():
        points += pts * within(feats[k], radius)
    points[~tissue] = 0
    level = np.zeros((h, w), int)
    level[points >= 1] = 1
    level[points >= CUTOFFS["risk_level_2"][0]] = 2
    level[points >= CUTOFFS["risk_level_3"][0]] = 3
    lab, n = ndimage.label(level >= 2)
    cards = []
    for i in range(1, n + 1):
        reg = lab == i
        rr, cc = np.nonzero(reg)
        near = within(reg, radius)
        present = [k for k in RISK_POINTS if (feats[k] & near).any()]
        cards.append({"card": f"R{len(cards) + 1}", "level": int(level[reg].max()),
                      "points": int(points[reg].max()), "features": present,
                      "tiles": int(reg.sum()), "mm2": round(float(reg.sum()) * TILE_MM2, 2),
                      "row": int(round(rr.mean())), "col": int(round(cc.mean()))})
    cards.sort(key=lambda c: (-c["level"], -c["points"], -c["tiles"]))
    for i, c in enumerate(cards):
        c["card"] = f"R{i + 1}"
    return {"points": points, "level": level, "features": feats, "cards": cards,
            "table": [{"feature": k, "points": v, "source": PLACEHOLDER} for k, v in
                      RISK_POINTS.items()]}


def look_here(res: dict) -> list[dict]:
    """The queue: pointers T1…Tn shared by the text, the queue and the map. Risk cards first,
    then the counting field, the roughest arc, the farthest islands and the most unsure spot."""
    q = []

    def add(what, why, row, col, evidence, status, check, kind):
        q.append({"pointer": f"T{len(q) + 1}", "what": what, "why": why, "row": int(round(row)),
                  "col": int(round(col)), "evidence": evidence, "status": status, "check": check,
                  "kind": kind})

    for c in res["risk"]["cards"][:4]:
        add(f"Risk level {c['level']} region ({c['card']})", ", ".join(c["features"]) or "points",
            c["row"], c["col"], INFERENCE, "placeholder points",
            "the front here at 10× and 20×: infiltration, buds, the tissue it faces", "risk")
    hs = res["hotspot"]
    if hs:
        add(f"Breakaway counting field: {hs['buds_in_field']} candidate cluster(s) in 0.785 mm²",
            f"{hs['coverage']:.0%} of the field was counted", hs["row"], hs["col"], INFERENCE,
            "weak until validated", "count buds at 20× in this field; fill in the counter",
            "hotspot")
    infil = [a for a in res["arcs"] if a["pattern"] == "infiltrative"]
    if infil:
        a = max(infil, key=lambda a: a["roughness"])
        add(f"Roughest arc {a['arc']}: infiltrative, invading {compass(a['direction_deg'])}, "
            f"faces {LABELS.get(a['faces_top'], a['faces_top']).lower()}",
            f"{a['roughness']:.0%} of its front tiles are fingers; push {a['push']:.2f}",
            a["row"], a["col"], HYPOTHESIS, "placeholder cutoff",
            "single cells and small nests beyond the front at 20×", "arc")
    for s in res["islands"][:2]:
        add(f"Island {s['island']}: {s['area_mm2']} mm², {s['distance_um']} µm from the main "
            f"tumor, {LABELS.get(s['between'], s['between']).lower()} between",
            "a separate tumor piece in the map", s["row"], s["col"], INFERENCE,
            "geometry on the tile classes", "is it a satellite, a tangential cut of the same "
            "tumor, or in-situ disease? (DCIS is not a class of the head)", "island")
    t = res["tiles"]
    uns = t[t["unsure"]] if "unsure" in t else t.iloc[0:0]
    if len(uns) >= 3:
        g = grid(uns.assign(u=1.0), "u") if len(uns) else None
        dens = ndimage.uniform_filter(g, 5) if g is not None else None
        if dens is not None and dens.max() > 0:
            r, c = np.unravel_index(int(np.argmax(dens)), dens.shape)
            add("Most unsure spot", f"{len(uns)} unsure tiles in the map, densest here", r, c,
                INFERENCE, "placeholder cutoff", "what is this tissue? the head is unsure here",
                "unsure")
    d = res.get("til") or {}
    if d.get("disagree", 0) >= CUTOFFS["disagree_min_tiles"][0]:
        mask = np.zeros(tuple(res["grid_shape"]), bool)
        mask[d["rows"]["row"].to_numpy(int), d["rows"]["col"].to_numpy(int)] = True
        dense = ndimage.uniform_filter(mask.astype(float), 5)
        dense[~mask] = -1  # the pointer sits on a disagreeing tile, the densest one
        r, c = np.unravel_index(int(np.argmax(dense)), dense.shape)
        add(f"Models disagree on lymphocytes: {d['disagree']} of {d['scored']} scored tiles "
            f"({d['head_only']} head only, {d['til_only']} second model only)",
            f"kappa {d['kappa']}; the second model is {TIL_SECOND}", r, c, INFERENCE,
            "second model: held-out AUROC in its card; cutoff " + (
                "calibrated on the head's training slides" if d.get("cutoff_calibrated")
                else "placeholder"),
            "are these lymphocytes, plasma cells, stromal nuclei or tumor cells? the two models "
            "read this tissue differently", "disagree")
    return q


# --- search --------------------------------------------------------------------------------

CANT = {"grade": "Nottingham grade", "mitos": "mitoses", "receptor": "receptor status",
        " er ": "ER status", "her2": "HER2 status", "pr status": "PR status",
        "mutation": "mutations", "margin": "margins", "vessel": "lymphovascular invasion",
        "lymphovascular": "lymphovascular invasion", "lvi": "lymphovascular invasion"}


def search(query: str, res: dict) -> dict:
    """Plain-word search inside the slide: a class, a zone, 'budding', 'lymphocytes at the
    border', 'unsure', 'satellite', a pointer (T2), or something this map cannot see."""
    q = f" {query.lower().strip()} "
    t = res["tiles"]
    for key, what in CANT.items():
        if key in q:
            can = next((how for w, _, how in CANNOT_SEE if what.split()[0].lower()
                        in w.lower()), "another test")
            return {"understood": False, "rows": t.iloc[0:0], "pointer": None,
                    "answer": f"This map can't see {what}. {can[0].upper() + can[1:]} can."}
    for p in res["queue"]:
        if f" {p['pointer'].lower()} " in q:
            return {"understood": True, "rows": t[(t.row == p["row"]) & (t.col == p["col"])],
                    "pointer": p["pointer"], "answer": f"{p['pointer']}: {p['what']}."}
    rows, parts = t, []
    border = any(w in q for w in (" border", " front", " edge", " margin of"))
    if any(w in q for w in ("bud", "breakaway", "single cell", "cluster")):
        rows = rows[rows["buds"] > 0] if "buds" in rows else rows.iloc[0:0]
        parts.append("tiles with breakaway candidates (clusters of up to 4 tumor-candidate "
                     "nuclei outside the main tumor; weak until validated)")
    for key, cls in (("lymph", "lymphocytes"), ("immune", "lymphocytes"), ("til", "lymphocytes"),
                     ("fat", "fat"), ("necro", "necrosis"), ("strom", "stroma"),
                     ("tumor", "tumor"), ("tumour", "tumor"), ("carcinoma", "tumor")):
        if key in q:
            rows = rows[rows["label"] == cls]
            parts.append(f"{LABELS[cls].lower()} tiles")
            break
    if border:
        rows = rows[rows["zone"] == "front band"]
        parts.append("in the front band (± 500 µm of the front)")
    if "unsure" in q or "uncertain" in q:
        rows = rows[rows["unsure"]]
        parts.append("marked unsure")
    if "satellite" in q or "island" in q:
        rows = rows[rows["tumor"] & ~rows["main_tumor"]]
        parts.append("in satellite islands")
    if "disagree" in q or "second model" in q or "second opinion" in q:
        d = res.get("til") or {}
        if not d.get("scored"):
            return {"understood": False, "rows": t.iloc[0:0], "pointer": None,
                    "answer": "The second lymphocyte model has not scored this section."}
        rows = rows.merge(d["rows"][["row", "col"]], on=["row", "col"])
        parts.append(f"where the head and the second model disagree on lymphocytes (of "
                     f"{d['scored']} scored tiles)")
    if "arrow" in q or "direction" in q or "invad" in q:
        infil = [a for a in res["arcs"] if a["pattern"] == "infiltrative"]
        dirs = ", ".join(f"{a['arc']} {compass(a['direction_deg'])} (faces "
                         f"{LABELS.get(a['faces_top'], a['faces_top']).lower()})" for a in infil)
        return {"understood": True, "rows": rows[rows["front"]], "pointer": None,
                "answer": f"{len(infil)} of {len(res['arcs'])} arcs read infiltrative: "
                          f"{dirs or 'none'}. A 2D snapshot of this section, not a forecast."}
    if not parts:
        return {"understood": False, "rows": t.iloc[0:0], "pointer": None,
                "answer": "Not understood. Try a tissue class, 'budding', 'lymphocytes at the "
                          "border', 'unsure', 'satellite', 'direction', or a pointer such as T1."}
    return {"understood": True, "rows": rows, "pointer": None,
            "answer": f"{len(rows)} {' '.join(parts)}."}


# --- comparison of two sections ------------------------------------------------------------

COMPARE = [("tumor_mm2", "Tumor area in the map (mm²)"), ("front_length_mm", "Front length (mm)"),
           ("infiltrative_arcs", "Infiltrative arcs of 12"), ("buds_in_field", "Breakaway "
            "candidates in the counting field"), ("islands", "Satellite islands"),
           ("immune_pattern", "Immune pattern"), ("tsr", "Tumor–stroma ratio"),
           ("til_disagree_share", "Models disagree on lymphocytes (share of scored tiles)"),
           ("faces_top", "The front mostly faces"), ("unsure_share", "Unsure share")]


def compare(a: dict, b: dict) -> list[dict]:
    """Two slides of one patient side by side: the same numbers, and whether they differ."""
    rows = []
    for key, name in COMPARE:
        va, vb = a.get(key), b.get(key)
        if isinstance(va, float) and isinstance(vb, float):
            differs = abs(va - vb) > 0.2 * max(abs(va), abs(vb), 1e-9)
        else:
            differs = va != vb
        rows.append({"measure": name, a["slide"]: va, b["slide"]: vb,
                     "differs": "yes" if differs else "no"})
    return rows


# --- everything (the map as a picture: muffle.workbench.slide_export.map_png) ----------

def analyze_slide(tiles: pd.DataFrame, classes: list[str] = CLASSES,
                  til_cutoff: float | None = None, til_calibrated: bool = False) -> dict:
    """``slides.analyze`` plus the invasion picture: normals and push per front tile, arcs with
    their pattern and what they face, the rose, fingers, satellite islands, the counting field,
    immune pattern by zone, tumor–stroma ratio, necrosis contact, the risk map with its cards,
    the look-here queue, and a flat ``numbers`` dict for the comparison of two slides. A
    ``p_til`` column (the second lymphocyte model, where it scored) adds the disagreement with
    the head at ``til_cutoff`` (``til_calibrated`` says whether that cutoff was measured)."""
    base = analyze(tiles, classes)
    t, s = base["tiles"], base["summary"]
    h, w = base["grid_shape"]
    main = grid(t, "main_tumor", False, bool)
    mask = grid(t, "tumor", False, bool)
    front = grid(t, "front", False, bool)
    tissue = np.zeros((h, w), bool)
    tissue[t["row"].to_numpy(int), t["col"].to_numpy(int)] = True
    labels = grid(t, "label", "", object)
    p_sm = grid(t, "p_tumor")  # raw; the push uses smoothed probability outside the mask
    p_sm = ndimage.uniform_filter(np.nan_to_num(p_sm), 3)
    normals = front_normals(main, front, p_sm, tissue)
    fing = fingers(main)
    arc_list = arcs(normals, main, labels, tissue, fing["mask"])
    islands = satellite_islands(mask, main, labels)
    hotspot = hotspot_field(t)
    immune = immune_by_zone(t, til_cutoff)
    til = til_disagreement(t, til_cutoff)
    til["cutoff_calibrated"] = til_calibrated
    if til["scored"]:
        t["til_lymph"] = (t["p_til"] >= til["cutoff"]).astype(float).where(t["p_til"].notna())
        disagree_idx = t.set_index(["row", "col"]).index.get_indexer(
            pd.MultiIndex.from_frame(til["rows"][["row", "col"]]))
        t["disagree"] = False
        t.loc[t.index[disagree_idx], "disagree"] = True
    tsr = tumor_stroma(t)
    nec = necrosis_contact(t, mask, labels)
    risk = risk_map(t, arc_list, normals, front, main, mask, labels, tissue, nec["mask"])
    r, c = t["row"].to_numpy(int), t["col"].to_numpy(int)
    t["finger"] = fing["mask"][r, c]
    t["risk_points"] = risk["points"][r, c]
    t["risk_level"] = risk["level"][r, c]
    t["necrosis_contact"] = nec["mask"][r, c]
    t["push"] = np.nan
    t["angle"] = np.nan
    if not normals.empty:
        idx = t.set_index(["row", "col"]).index
        pos = idx.get_indexer(pd.MultiIndex.from_frame(normals[["row", "col"]]))
        t.loc[t.index[pos], "push"] = normals["push"].to_numpy()
        t.loc[t.index[pos], "angle"] = normals["angle"].to_numpy()
    res = {"tiles": t, "summary": s, "grid_shape": base["grid_shape"], "normals": normals,
           "arcs": arc_list, "rose": rose(normals), "fingers": {"n": fing["n"],
                                                               "judged": fing["judged"]},
           "islands": islands, "hotspot": hotspot, "immune": immune, "tsr": tsr,
           "necrosis": {k: v for k, v in nec.items() if k != "mask"}, "risk": risk,
           "til": til}
    res["queue"] = look_here(res)
    infil = sum(a["pattern"] == "infiltrative" for a in arc_list)
    res["numbers"] = {
        "tumor_mm2": s["tumor_mm2"], "front_length_mm": s["front_length_mm"],
        "infiltrative_arcs": infil, "arcs": len(arc_list),
        "buds_in_field": hotspot["buds_in_field"] if hotspot else None,
        "islands": len(islands), "immune_pattern": immune["pattern"],
        "tsr": tsr["verdict"], "faces_top": next(iter(s["facing"]), "nothing"),
        "unsure_share": s["unsure_share"],
        "counted_tiles": int(t["n_nuclei"].notna().sum()) if "n_nuclei" in t else 0,
        "til_disagree_share": til["share"],
    }
    return res

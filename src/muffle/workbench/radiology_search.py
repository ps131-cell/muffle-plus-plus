# Built on muffle.workbench.slide_search (adapted from the team's Colon Tumor Front Analyzer, app/search.py): known words to per-square scores, Q1… spots, for a scan  # noqa: E501
"""Search inside one radiology study, in plain words (docs/radiology.md §8).

Known words only (no text model runs here): the query's words are matched to what the scan map
holds: the candidates (lesion, mass, enhancing lesion), their curve types (washout, plateau,
persistent, fast), the subtraction (enhancing), the margin band (spiculated, margin), the search
limit (chest wall, deep), unsure contours, the change between two dates (change, grew, smaller)
and, on mammograms, the dense pixels (dense). A pointer (C2) or "largest" get their own answer.
Every score is per square of the map (about 4.5 mm) across the whole study, so the best spots
come back as Q1…Q5 with their slice or view. Things a map cannot see (calcifications at this
size, lymph nodes, histology, receptor status, grade) get an honest "this map can't see that"
naming the test that can. Every score is a model inference or a rule on one.
"""

from __future__ import annotations

import math
import re

import numpy as np

from muffle.workbench import radiology as rad
from muffle.workbench.radiology_map import fill_polygons, square_px, square_shares

MIN_SCORE = 0.15          # weaker squares are not results (nor coloured on the map)
SPACING_MM = 15.0         # between results, so they point at different places

WORDS = {
    "lesion": {"lesion", "lesions", "mass", "masses", "candidate", "candidates", "tumor",
               "tumour", "contour", "contours", "nodule"},
    "enhancing": {"enhancing", "enhancement", "enhances", "enhanced", "bright", "brightest",
                  "subtraction"},
    "washout": {"washout", "wash", "iii"},
    "plateau": {"plateau", "ii"},
    "persistent": {"persistent", "persisting", "progressive"},
    "fast": {"fast", "rapid", "quick"},
    "margin": {"spiculated", "spiculation", "spiculations", "margin", "margins", "irregular",
               "border", "edge", "rim"},
    "wall": {"chest", "wall", "deep", "pectoral", "posterior"},
    "unsure": {"unsure", "uncertain", "doubtful", "unclear"},
    "change": {"change", "changed", "changes", "grow", "grows", "grew", "grown", "growth",
               "growing", "larger", "bigger", "smaller", "shrink", "shrinks", "shrank", "shrunk",
               "new", "gone", "compare", "prior"},
    "dense": {"dense", "density", "fibroglandular", "glandular", "parenchyma"},
}
NAMES = {"lesion": "the candidates' contours (MedSAM, model inference)",
         "enhancing": "the subtraction's brightness (the shipped copy)",
         "washout": "contours with a washout delayed phase (type III)",
         "plateau": "contours with a plateau delayed phase (type II)",
         "persistent": "contours with a persistent delayed phase (type I)",
         "fast": "contours with a fast wash-in (above 100%)",
         "margin": "the margin bands (up to 3 mm outside each contour; the shape is judged by "
                   "eye, the map cannot read spiculation)",
         "wall": "tissue within 5 mm in front of the search limit (placeholder), about the "
                 "chest wall",
         "unsure": "contours flagged unsure on their slice",
         "change": "where the two dates' contours differ after the rigid alignment",
         "dense": "the dense pixels (Otsu inside the breast, a placeholder rule)"}
# What a scan map can't see, by word: (what, which test can)
CANT = {
    "calcification": ("calcifications", "the original mammograms at full resolution (0.07 mm; "
                                        "the shipped copy is 0.46 mm), or magnification views"),
    "calcifications": None, "microcalcification": None, "microcalcifications": None,
    "calc": None, "calcs": None,
    "node": ("lymph nodes", "axillary ultrasound and sentinel node biopsy: the seed rule looks "
                            "in the breasts only, never the axilla"),
    "nodes": None, "lymph": None, "axilla": None, "axillary": None, "nodal": None,
    "histology": ("histology", "the pathologist on a biopsy (the slide workbench)"),
    "histologic": None, "pathology": None, "biopsy": None,
    "receptor": ("receptor status", "immunohistochemistry on the biopsy; the structured report "
                                    "records it as observed"),
    "receptors": None, "er": None, "pr": None, "her2": None, "hormone": None,
    "grade": ("grade", "the pathologist (Nottingham grade)"), "nottingham": None, "ki67": None,
    "mutation": ("mutations", "tumor sequencing (the genomics workbench)"), "mutations": None,
    "gene": None, "genes": None,
    "metastasis": ("distant metastases", "staging CT, bone scan or PET-CT: a breast MRI or "
                                         "mammogram covers the breasts and axillae only"),
    "metastases": None, "metastatic": None,
    "benign": ("whether an area is cancer", "image-guided biopsy and pathology"),
    "malignant": None, "malignancy": None, "diagnosis": None, "cancer": None,
    "birads": ("a BI-RADS assessment", "the radiologist; the study's own structured report "
                                       "records BI-RADS 6 (observed)"),
}
_last = None
for _k in list(CANT):  # a None entry shares the answer above it
    if CANT[_k] is None:
        CANT[_k] = _last
    else:
        _last = CANT[_k]


def words(query: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", query.lower().replace("bi-rads", "birads")
                          .replace("wash-out", "washout").replace("ki-67", "ki67")))


def understand(query: str) -> list[str]:
    """Which of the map's things the words point to, in ``WORDS``' order."""
    w = words(query)
    if "type" in w:  # "type III" names a curve, "type II" another
        w |= {"washout"} if "iii" in w else {"plateau"} if "ii" in w else \
            {"persistent"} if {"i", "1"} & w else set()
    found = [k for k, ws in WORDS.items() if w & ws]
    if "lesion" in found and ({"washout", "plateau", "persistent", "fast", "margin", "unsure",
                               "change"} & set(found)):
        found.remove("lesion")  # "washout lesion": the curve already says it's a candidate
    if "wash" in w and "in" in w:  # "wash-in" names the speed, not a washout
        found = [k for k in found if k != "washout"] + (["fast"] if "fast" not in found else [])
    if "border" in w and "chest" in w:
        found = [k for k in found if k != "margin"]
    return found


def cannot(query: str) -> tuple[str, str] | None:
    w = words(query)
    hit = next((CANT[x] for x in sorted(w) if x in CANT), None)
    return hit


# ---------------------------------------------------------------- per-square scores, a volume

def _grid(study: dict) -> tuple[int, int, int, int]:
    d = study["display"]
    sq = square_px(d["pixel_mm"])
    return d["slices"], math.ceil(d["rows"] / sq), math.ceil(d["cols"] / sq), sq


def candidate_scores(study: dict, ids: list[str], band: bool = False,
                     unsure_only: bool = False) -> np.ndarray:
    """[slice, square row, square col]: the share of each square inside the named candidates'
    contours (with ``band``, in their margin bands; with ``unsure_only``, only on the slices
    where the contour is flagged unsure)."""
    from scipy import ndimage

    d = study["display"]
    z, gr, gc, sq = _grid(study)
    out = np.zeros((z, gr, gc), np.float32)
    margin = rad.CUTOFFS["margin_band_mm"][0]
    for c in study["candidates"]:
        if c["id"] not in ids:
            continue
        for k, s in c["per_slice"].items():
            if unsure_only and not s.get("unsure"):
                continue
            m = fill_polygons(s["contours"], d["rows"], d["cols"])
            if band:
                dist = ndimage.distance_transform_edt(~m) * d["pixel_mm"]
                m = (dist > 0) & (dist <= margin)
            out[int(k)] = np.maximum(out[int(k)], square_shares(m, sq)[:gr, :gc])
    return out


def enhancing_scores(sub: np.ndarray, study: dict) -> np.ndarray:
    """[slice, square row, square col]: the subtraction copy's mean brightness per square, 0-1
    of the study's brightest (its 99.9th percentile in the breast region)."""
    z, gr, gc, sq = _grid(study)
    h, w = sub.shape[1:]
    pad = np.zeros((z, gr * sq, gc * sq), np.float32)
    pad[:, :h, :w] = sub / 255.0
    return pad.reshape(z, gr, sq, gc, sq).mean(axis=(2, 4))


def wall_scores(study: dict, skin: np.ndarray) -> np.ndarray:
    """[slice, square row, square col]: 1 for tissue squares within ``near_wall_mm`` in front of
    the search limit (about the chest wall)."""
    d = study["display"]
    z, gr, gc, sq = _grid(study)
    px = d["pixel_mm"]
    limit = study["region"]["limit_row_display"]
    rows = np.arange(gr) * sq + sq / 2
    near = ((limit - rows) * px >= 0) & ((limit - rows) * px <= rad.CUTOFFS["near_wall_mm"][0])
    cols = np.minimum(np.arange(gc) * sq + sq // 2, d["cols"] - 1)
    body = skin[:, cols] >= 0                                   # [slice, square col]
    return (near[None, :, None] & body[:, None, :]).astype(np.float32)


def change_scores(study: dict, layers: dict[int, np.ndarray]) -> np.ndarray:
    """[slice, square row, square col]: the share of each square where the two dates' contours
    differ (``radiology_map.change_layer``'s classes 2-5), from per-slice class layers."""
    z, gr, gc, sq = _grid(study)
    out = np.zeros((z, gr, gc), np.float32)
    for k, classes in layers.items():
        out[k] = square_shares(classes >= 2, sq)[:gr, :gc]
    return out


# ---------------------------------------------------------------- the search

def search(study: dict, query: str, *, sub: np.ndarray | None = None,
           skin: np.ndarray | None = None, change: dict[int, np.ndarray] | None = None,
           views: dict | None = None, top: int = 5) -> dict:
    """{"query", "used", "volume" ([slice, square row, square col] 0-1 for an MRI; {view:
    [square row, square col]} for mammograms), "spots" [{"slice" | "view", "r", "c", "score",
    "label", "cand"}], "message", "understood"}. ``views`` (mammograms): {view key:
    ``radiology_map.mammo_view``'s map}."""
    query = query.strip()
    out = {"query": query, "used": [], "volume": None, "spots": [], "message": "",
           "understood": False}
    if not query:
        return out
    w = words(query)
    cant = cannot(query)
    if cant:
        what, how = cant
        out["message"] = (f"This map can't see {what}: it shows the shipped images and the "
                          f"models' contours, one answer per square of about "
                          f"{rad.CUTOFFS['map_square_mm'][0]:g} mm. {how[0].upper() + how[1:]} "
                          "can. ")
        if not (set().union(*WORDS.values()) & w):
            return out
    mri = study["modality"] == "MR"
    cands = study.get("candidates", [])
    pointer = next((c for c in cands if c["id"].lower() in w), None)
    if pointer is not None and mri:  # a pointer by name: C2
        from muffle.workbench.radiology_map import ld_index

        i = ld_index(study, pointer)
        s = pointer["per_slice"].get(str(i))
        sq = square_px(study["display"]["pixel_mm"])
        r = int(((s["box"][1] + s["box"][3]) / 2) // sq) if s else 0
        c = int(((s["box"][0] + s["box"][2]) / 2) // sq) if s else 0
        out.update(understood=True, used=[f"pointer {pointer['id']}: its longest-diameter slice"],
                   spots=[{"slice": i, "r": r, "c": c, "score": 1.0, "label": pointer["id"],
                           "cand": pointer["id"]}])
        out["volume"] = candidate_scores(study, [pointer["id"]])
        return out
    if mri and w & {"largest", "biggest", "large"} and cands:
        big = max(cands, key=lambda c: c.get("volume_ml", 0))
        hit = search(study, big["id"], sub=sub, skin=skin, change=change)
        hit["used"] = [f"the largest candidate by volume, {big['id']} ({big['volume_ml']:g} mL)"]
        hit["query"] = query
        return hit
    found = understand(query)
    if not found:
        if not out["message"]:
            out["message"] = ("No known words found. Try " + (
                "a candidate (enhancing lesion, C2, largest), a curve (washout, plateau, "
                "persistent, fast), the margin (spiculated), the chest wall, unsure, or "
                "change." if mri else "dense or density; no lesion detector runs on the "
                                      "mammograms here."))
        return out
    cols, used = [], []
    if mri:
        for k in found:
            if k == "lesion":
                cols.append(candidate_scores(study, [c["id"] for c in cands]))
            elif k in ("washout", "plateau", "persistent"):
                cols.append(candidate_scores(study, [c["id"] for c in cands if
                                                     c["kinetics"].get("delayed") == k]))
            elif k == "fast":
                cols.append(candidate_scores(study, [c["id"] for c in cands if
                                                     c["kinetics"].get("initial") == "fast"]))
            elif k == "margin":
                cols.append(candidate_scores(study, [c["id"] for c in cands], band=True))
            elif k == "unsure":
                cols.append(candidate_scores(study, [c["id"] for c in cands], unsure_only=True))
            elif k == "enhancing" and sub is not None:
                cols.append(enhancing_scores(sub, study))
            elif k == "wall" and skin is not None:
                cols.append(wall_scores(study, skin))
            elif k == "change":
                if not change:
                    out["message"] += ("One study date on this file: no change to show (a "
                                       "second study, aligned, would show it; the public "
                                       "example pair shows how). ")
                    continue
                cols.append(change_scores(study, change))
            elif k == "dense":
                out["message"] += ("Mammographic density is read on mammograms; on this MRI "
                                   "the fibroglandular tissue is judged by eye. ")
                continue
            else:
                continue
            used.append(NAMES[k])
    else:
        for k in found:
            if k == "dense" and views:
                cols.append({v: _dense(mv) for v, mv in views.items()})
                used.append(NAMES["dense"])
            elif k in ("lesion", "washout", "plateau", "persistent", "fast", "margin",
                       "unsure", "enhancing"):
                out["message"] += ("No lesion detector runs on the mammograms here (none open, "
                                   "permissive and CPU-ready was found), so there is nothing "
                                   "to search for that. ")
            elif k == "change":
                out["message"] += "One mammography date on this file: no change to show. "
    if not cols:
        if out["message"]:
            out["understood"] = bool(found)
        return out
    out["understood"] = True
    out["used"] = used
    if mri:
        vol = np.mean(cols, axis=0) if len(cols) > 1 else cols[0]
        if len(cols) > 1 and "enhancing" in found and len(found) == 2 and "lesion" in found:
            vol = np.minimum(cols[0], 1) * 0.5 + cols[1] * 0.5  # "enhancing lesion"
        out["volume"] = np.clip(vol, 0, 1)
        out["spots"] = _spots_mri(study, out["volume"], top)
    else:
        merged = {v: np.mean([c[v] for c in cols], axis=0) for v in cols[0]}
        out["volume"] = merged
        out["spots"] = _spots_views(merged, top)
    if not out["spots"]:
        out["message"] += f"Nothing reaches {MIN_SCORE:.0%} for this search in this study."
    return out


def _dense(mv) -> np.ndarray:
    """A mammography view's dense-pixel share per square, as a [square row, square col] grid."""
    gr = math.ceil(mv.rows / mv.square)
    gc = math.ceil(mv.cols / mv.square)
    out = np.zeros((gr, gc), np.float32)
    out[mv.sq_r, mv.sq_c] = mv.numbers[:, 0] / 100.0
    return out


def _spots_mri(study: dict, vol: np.ndarray, top: int) -> list[dict]:
    """The best squares, at least ``SPACING_MM`` apart in 3D: Q1…Q5 with their slice and the
    candidate they fall in."""
    d = study["display"]
    dz, px, _ = rad.shown_spacing(d)
    sq = square_px(px)
    flat = vol.reshape(-1).astype(float).copy()
    zz, rr, cc = np.unravel_index(np.arange(flat.size), vol.shape)
    pos = np.stack([zz * dz, rr * sq * px, cc * sq * px], 1)
    out = []
    for n in range(1, top + 1):
        j = int(np.argmax(flat))
        if flat[j] < MIN_SCORE:
            break
        z, r, c = int(zz[j]), int(rr[j]), int(cc[j])
        cand = next((x["id"] for x in study.get("candidates", []) if str(z) in x["per_slice"]
                     and _inside_box(x["per_slice"][str(z)]["box"], r, c, sq)), None)
        out.append({"slice": z, "r": r, "c": c, "score": float(flat[j]), "label": f"Q{n}",
                    "cand": cand})
        far = np.linalg.norm(pos - pos[j], axis=1) < SPACING_MM
        flat[far] = -1
    return out


def _inside_box(box, r: int, c: int, sq: int) -> bool:
    x0, y0, x1, y1 = box
    y, x = r * sq + sq / 2, c * sq + sq / 2
    return x0 - sq <= x <= x1 + sq and y0 - sq <= y <= y1 + sq


def _spots_views(grids: dict, top: int) -> list[dict]:
    """The best squares over the mammography views, five squares apart within a view."""
    cand = sorted(((float(v), view, int(r), int(c)) for view, g in grids.items()
                   for (r, c), v in np.ndenumerate(g) if v >= MIN_SCORE), reverse=True)
    out = []
    for v, view, r, c in cand:
        if any(s["view"] == view and abs(s["r"] - r) < 5 and abs(s["c"] - c) < 5 for s in out):
            continue
        out.append({"view": view, "r": r, "c": c, "score": v, "label": f"Q{len(out) + 1}",
                    "cand": None})
        if len(out) == top:
            break
    return out


def values_for(found: dict | None, m) -> np.ndarray | None:
    """A search's per-square scores on one slice or view of the map (``ScanMap``)."""
    if not found or found.get("volume") is None:
        return None
    vol = found["volume"]
    if isinstance(vol, dict):
        g = vol.get(m.where)
        return None if g is None else g[m.sq_r, m.sq_c]
    return vol[m.index][m.sq_r, m.sq_c]

# Adapted from the team's Colon Tumor Front Analyzer (Ashby Prize Hackathon, Oct 2026): app/search.py  # noqa: E501
"""Search inside one scored section, in plain words (docs/pathology.md §8).

Known words only (no text model runs here): the query's words are matched to the tissue head's
classes, to the section's flags (breakaway candidates, unsure tiles, satellite islands, the
models' disagreement on lymphocytes, quality-control exclusions) and to a place ("border",
"core", "around" limit it to that zone); a pointer (T2) or the direction of invasion get their own
answer. Each tile's score is averaged with its 3×3 neighbours (regions, not single noisy tiles),
and the best spots come back spaced apart as Q1…Q5 (S1… already names the satellite islands
here). The answer always says what was matched; things a tile map cannot see get an honest "this
map can't see that". Every score is a model inference or a rule on inferences.
"""

from __future__ import annotations

import re

import numpy as np

from muffle.workbench.invasion import CANNOT_SEE, compass
from muffle.workbench.slides import LABELS
from muffle.workbench.tile_map import MapData

CLASS_WORDS = {
    "tumor": ["tumor", "tumour", "cancer", "carcinoma", "malignant", "invasive", "idc"],
    "stroma": ["stroma", "stromal", "desmoplastic", "desmoplasia", "fibrous", "collagen",
               "connective", "fibroblasts"],
    "lymphocytes": ["lymphocytes", "lymphocyte", "immune", "inflammation", "inflammatory",
                    "tils", "til", "lymphoid"],
    "necrosis": ["necrosis", "necrotic", "dead", "debris", "comedo"],
    "fat": ["fat", "adipose", "adipocytes", "fatty"],
}
FLAG_WORDS = {
    "breakaway": ["budding", "buds", "bud", "breakaway", "cluster", "clusters"],
    "unsure": ["unsure", "uncertain", "doubtful", "unclear"],
    "island": ["satellite", "satellites", "island", "islands"],
    "disagree": ["disagree", "disagreement", "disagrees", "second"],
    "excluded": ["excluded", "glass", "ink", "pen", "blur", "blurry", "unlike", "artifact",
                 "artefact", "quality", "crushed"],
}
FLAG_NAMES = {"breakaway": "breakaway candidates (weak until validated)",
              "unsure": "unsure tiles (top probability under the placeholder cutoff)",
              "island": "satellite islands (separate tumor pieces)",
              "disagree": "tiles where the head and the second lymphocyte model disagree",
              "excluded": "tiles excluded by quality control"}
QC_WORDS = {"glass": "glass", "ink": "pen ink", "pen": "pen ink", "blur": "blur",
            "blurry": "blur", "unlike": "unlike training tissue",
            "crushed": "unlike training tissue"}
ZONE_WORDS = {
    "front band": ["border", "front", "edge", "periphery", "boundary", "invasive"],
    "core": ["core", "center", "centre", "inside", "interior", "middle"],
    "peritumoral": ["around", "surrounding", "peritumoral", "outside", "near"],
}
ZONE_NAMES = {"front band": "invasive front band (±0.5 mm)", "core": "tumor core",
              "peritumoral": "peritumoral zone (0.5–2 mm outside)"}
# Things a 112 µm tile map can't see: the analyzer's single-cell words, plus breast's own
SINGLE_CELL = {"mitosis", "mitoses", "mitotic", "cd8", "cd4", "foxp3", "treg", "tregs",
               "macrophage", "macrophages", "neutrophil", "neutrophils", "eosinophil",
               "eosinophils", "nucleus", "nuclei", "signet", "grade", "nottingham"}
CANT = {"receptor": "receptor status", "er": "ER status", "pr": "PR status",
        "her2": "HER2 status", "mutation": "mutations", "mutations": "mutations",
        "margin": "margins", "margins": "margins", "vessel": "lymphovascular invasion",
        "vessels": "lymphovascular invasion", "lymphovascular": "lymphovascular invasion",
        "lvi": "lymphovascular invasion", "dcis": "in-situ carcinoma (not a class of the head)"}
MIN_SCORE = 0.15          # weaker spots aren't shown as results
SPACING = 5               # tiles between results, so they point at different places


def words(query: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", query.lower()))


def understand(query: str) -> tuple[list[str], list[str], str | None]:
    """Which classes, flags and zone the words point to."""
    w = words(query)
    classes = [c for c, ws in CLASS_WORDS.items() if w & set(ws)]
    flags = [k for k, ws in FLAG_WORDS.items() if w & set(ws)]
    zone = next((z for z, ws in ZONE_WORDS.items() if w & set(ws)), None)
    if "tumor" in classes and (flags or (zone and len(classes) > 1)):
        classes.remove("tumor")           # "satellite tumor", "lymphocytes at the tumor border":
                                          # the flag or the place already says it's about tumor
    if zone == "front band" and "invasive" in w and not (w & set(ZONE_WORDS["front band"]) -
                                                         {"invasive"}):
        zone = None                       # "invasive carcinoma" names the class, not the front
    return classes, flags, zone


def known_words_scores(data: MapData, classes: list[str], flags: list[str], query: str):
    """Per-tile 0-1 score from the matched classes and flags, and what was used (for the
    page)."""
    cols, used = [], []
    for c in classes:
        if c not in data.classes:
            continue
        cols.append(data.probs[:, data.classes.index(c)] * data.ok)
        used.append(f"{LABELS.get(c, c)} (the head's probability)")
    n = len(data.rows)
    for f in flags:
        if f == "breakaway" and "buds" in data.extra:
            cols.append(np.clip(np.nan_to_num(data.extra["buds"]) / 3, 0, 1))
        elif f == "unsure":
            cols.append(data.unsure.astype(float))
        elif f == "island":
            cols.append((data.in_tumor & ~data.in_main_tumor & data.ok).astype(float))
        elif f == "disagree" and "disagree" in data.extra:
            cols.append(data.extra["disagree"].astype(float))
        elif f == "excluded":
            named = {QC_WORDS[w] for w in words(query) if w in QC_WORDS}
            cols.append(np.isin(data.reason, list(named)).astype(float) if named
                        else (~data.ok).astype(float))
            if named:
                used.append("tiles excluded for " + " or ".join(sorted(named)))
                continue
        else:
            continue
        used.append(FLAG_NAMES[f])
    if not cols:
        return None, used
    return np.mean([np.asarray(c, float)[:n] for c in cols], axis=0), used


def smooth(data: MapData, values: np.ndarray, usable: np.ndarray) -> np.ndarray:
    """Average each tile with its 3x3 neighbours (``usable`` tiles only)."""
    from scipy import ndimage

    g = data.geom
    grid = np.zeros((g["rows"], g["cols"]))
    has = np.zeros_like(grid)
    grid[data.rows, data.cols] = values * usable
    has[data.rows, data.cols] = usable
    num = ndimage.uniform_filter(grid, 3, mode="constant")
    den = ndimage.uniform_filter(has, 3, mode="constant")
    return np.where(den > 0, num / np.maximum(den, 1e-9), 0)[data.rows, data.cols]


def search(data: MapData, query: str, res: dict | None = None, top: int = 5) -> dict:
    """{"query", "used", "zone", "values" (0-1 per tile, for the map), "spots" [{"r", "c",
    "score", "label"}], "message", "understood"}."""
    query = query.strip()
    out = {"query": query, "used": [], "zone": None, "values": None, "spots": [],
           "message": "", "understood": False}
    if not query:
        return out
    w = words(query)
    cant = next((CANT[x] for x in w if x in CANT), None)
    if cant or w & SINGLE_CELL:
        what = cant or "single cells (mitoses, grade, cell types)"
        how = next((h for name, _, h in CANNOT_SEE if what.split()[0].lower() in name.lower()),
                   "the pathologist at high power")
        out["message"] = (f"This map can't see {what}: it gives one answer per 112 µm square "
                          f"(10–15 cells). {how[0].upper() + how[1:]} can. ")
        if cant:
            return out
    queue = (res or {}).get("queue") or []
    for p in queue:   # a pointer by name: T2
        if p["pointer"].lower() in w:
            out.update(understood=True, used=[f"pointer {p['pointer']}: {p['what']}"],
                       spots=[{"r": p["row"], "c": p["col"], "score": 1.0,
                               "label": p["pointer"]}])
            return out
    if res is not None and w & {"direction", "arrow", "arrows", "invading", "invades",
                                "invasion"}:
        infil = [a for a in res.get("arcs", []) if a["pattern"] == "infiltrative"]
        dirs = ", ".join(f"{a['arc']} {compass(a['direction_deg'])}" for a in infil)
        out["message"] += (f"{len(infil)} of {len(res.get('arcs', []))} arcs of the front read "
                           f"infiltrative: {dirs or 'none'}; the Zones view draws them as blue "
                           "arrows. A hypothesis about this section, not a forecast. ")
        out["understood"] = True
        if not (set().union(*CLASS_WORDS.values(), *FLAG_WORDS.values()) & w):
            values = (data.on_front & data.ok).astype(float)
            out.update(used=["the invasive front"], values=values)
            out["spots"] = _spots(data, values, top)
            return out
    classes, flags, zone = understand(query)
    values, out["used"] = known_words_scores(data, classes, flags, query)
    if values is None:
        if not out["understood"]:
            out["message"] += ("No known words found. Try a tissue (carcinoma, stroma, "
                               "lymphocytes, necrosis, fat), a flag (budding, unsure, "
                               "satellite, disagree, excluded, glass), a place (border, core, "
                               "around), the direction of invasion, or a pointer such as T1.")
        return out
    out["understood"] = True
    usable = data.ok if "excluded" not in flags else np.ones(len(data.rows), bool)
    values = smooth(data, values, usable) if "excluded" not in flags else values
    if zone:
        values = values * (data.zone == zone)
        out["zone"] = zone
    out["values"] = values / max(float(values.max()), 1e-9)
    out["spots"] = _spots(data, values, top)
    if not out["spots"]:
        out["message"] += "Nothing stands out for this search on this section."
    return out


def _spots(data: MapData, values: np.ndarray, top: int) -> list[dict]:
    """The best spots, spaced apart: Q1…Q5."""
    g = data.geom
    grid = np.full((g["rows"], g["cols"]), -1.0)
    grid[data.rows, data.cols] = values / max(float(np.max(values, initial=0)), 1e-9)
    out = []
    for n in range(1, top + 1):
        r, c = np.unravel_index(int(np.argmax(grid)), grid.shape)
        if grid[r, c] < MIN_SCORE:
            break
        out.append({"r": int(r), "c": int(c), "score": float(grid[r, c]), "label": f"Q{n}"})
        grid[max(0, r - SPACING):r + SPACING + 1, max(0, c - SPACING):c + SPACING + 1] = -1
    return out

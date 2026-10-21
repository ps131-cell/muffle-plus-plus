"""Radiology workbench: pure functions (docs/WORKBENCHES.md §6, docs/radiology.md).

Two kinds of input:

* **Imaging reports as text** (the synthetic record, ``muffle.timeline.EVENTS``): the lesion
  vocabulary of each read (progression / stable, the sites named new) and a lesion table that
  tracks every named site across the reads. All **observed**: the report's own words. The record
  holds no measurement, so none is invented: "no measurements recorded".
* **Public images** (TCGA-BRCA radiology on TCIA, CC BY 3.0): the offline pipeline
  (``scripts/radiology_pipeline.py``) proposes lesion candidates from the subtraction volume, has
  MedSAM draw their contours and measures them with the functions below. Every candidate,
  contour and measurement is a **model inference**; the structured report's BI-RADS category,
  pathology and receptors are **observed**.

Every cutoff in ``CUTOFFS`` names its source; the kinetics cutoffs are the literature's usual
values and stay "literature, placeholder until calibrated" until they are checked on data here.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

from muffle.report.case_tools import INFERENCE, OBSERVED
from muffle.workbench.labs import lead_lag as _lab_lead_lag
from muffle.workbench.labs import results_table

PROGRESSION, STABLE, RESPONSE, NOT_STATED = "progression", "stable", "response", "not stated"
NO_MEASUREMENTS = "no measurements recorded"
PLACEHOLDER, DESIGN = "placeholder", "design"
LITERATURE = "literature, placeholder until calibrated"
KUHL = ("Kuhl et al., Radiology 1999, doi:10.1148/radiology.211.1.r99ap38101 (curve types I "
        "persistent, II plateau, III washout)")
BIRADS = "ACR BI-RADS Atlas, MRI lexicon (5th edition, 2013): kinetic curve assessment"
MEDSAM = ("MedSAM (Ma et al., Nat Commun 2024, doi:10.1038/s41467-024-44824-z), ViT-B, "
          "Hugging Face wanglab/medsam-vit-base")
TCIA = ("TCGA-BRCA radiology collection, The Cancer Imaging Archive, "
        "doi:10.7937/K9/TCIA.2016.AB2NAZRP, CC BY 3.0")

# name: (value, source tag, what it means and where it comes from)
CUTOFFS = {
    "initial_window_s": (120, LITERATURE, "the initial phase: the strongest post-contrast phase "
                         f"within the first 2 minutes ({BIRADS})"),
    "initial_slow_below": (50, LITERATURE, "initial enhancement below 50% over pre-contrast = "
                           "slow (the usual value; not checked in the lexicon's full text here)"),
    "initial_fast_above": (100, LITERATURE, "initial enhancement above 100% = fast; 50-100% = "
                           "medium (the usual value; same caveat)"),
    "delayed_band_pct": (10, LITERATURE, "delayed phase within ±10% of the initial peak = "
                         f"plateau; above = persistent, below = washout ({KUHL})"),
    "seed_percentile": (99.5, PLACEHOLDER, "seed voxels: the subtraction above this percentile "
                        "of the breast region's subtraction values"),
    "seed_min_mm3": (30, PLACEHOLDER, "a candidate is at least this many mm³ of seed voxels"),
    "seed_open_mm": (1.5, PLACEHOLDER, "the seed voxels are opened with a 1.5 mm ellipsoid, which "
                     "detaches vessels thinner than about 3 mm from a mass"),
    "seed_max_elongation": (3.0, PLACEHOLDER, "longest over second axis of a candidate's voxel "
                            "spread; above this it is vessel-like and not proposed"),
    "seed_max_flatness": (3.0, PLACEHOLDER, "second over shortest axis; above this it is "
                          "plate-like (chest wall, skin) and not proposed"),
    "chest_margin_mm": (10, PLACEHOLDER, "candidates are searched anterior to the intermammary "
                        "cleft plus this margin, so the heart and chest wall are left out"),
    "skin_mm": (3, PLACEHOLDER, "the first 3 mm under the skin surface are left out"),
    "box_pad": (0.15, DESIGN, "a candidate's box on each slice is its seed extent plus 15% "
                "(at least 2 pixels) on every side"),
    "mask_threshold": (0.5, DESIGN, "MedSAM's mask = sigmoid output above 0.5, as in the "
                       "authors' inference code"),
    "dense_threshold": ("Otsu", PLACEHOLDER, "mammography dense pixels: above an Otsu threshold "
                        "inside the breast; a pixel share, not a BI-RADS density category"),
}

SITE_WORDS = {"bone": "Bone", "liver": "Liver", "lung": "Lung", "brain": "Brain",
              "lymph node": "Lymph node", "nodal": "Lymph node", "pleural": "Pleura",
              "adrenal": "Adrenal", "peritoneal": "Peritoneum", "skin": "Skin",
              "chest wall": "Chest wall", "breast": "Breast"}
READ_WORDS = [  # the first match wins, in this order
    (PROGRESSION, r"read as progression|progressi(?:on|ve disease)"),
    (RESPONSE, r"partial response|complete response|\bresponse\b|decreas"),
    (STABLE, r"stable disease|imaging stable|\bstable\b"),
]

# (what, why not, which test can, words that ask for it): what breast images cannot show
CANNOT_SEE = [
    ("Whether an enhancing area is cancer", "enhancement and curve shape are suggestive, not "
     "proof: benign lesions can wash out and cancers can enhance slowly",
     "image-guided biopsy and pathology", ("cancer?", "malignan", "benign", "diagnos")),
    ("Mutations, receptors, grade", "an image does not read DNA, receptor expression or "
     "nuclear grade", "sequencing (the genomics workbench), immunohistochemistry, the "
     "pathologist", ("mutation", "gene", "pik3ca", "esr1", "receptor", "her2", "grade", "ki")),
    ("Microscopic lymph-node spread", "nodes can look normal and hold tumor cells",
     "sentinel node biopsy", ("node", "nodal", "axilla")),
    ("Distant metastases", "a breast MRI or mammogram covers the breasts and axillae only",
     "staging CT, bone scan or PET-CT", ("metasta", "bone", "liver", "lung", "brain")),
    ("Change over time from one study", "growth or shrinkage needs a prior study of the same "
     "breast, aligned", "a second study, with registration", ("grow", "shrink", "change",
                                                                 "prior", "compare")),
    ("Exact size", "partial volume, slice thickness and the contour's own error; MRI and "
     "pathology sizes differ", "the pathologist's measurement on the specimen",
     ("exact", "true size", "pathology size")),
]
REPORT_CANNOT_SEE = [
    ("Lesion size and count", f"the reports in this record name sites only: {NO_MEASUREMENTS}",
     "the images themselves, or the radiologist's measurements",
     ("size", "count", "how many", "measure", "mm", "diameter", "volume")),
    ("Whether a 'stable' read covers every site", "a stable read is an overall statement; the "
     "report does not name the sites it compared", "the images, compared side by side",
     ("every site", "each site", "all sites")),
    ("A response category (RECIST)", "RECIST needs measured target lesions and their sums",
     "measurements on the images", ("recist", "response category", "target lesion")),
    ("What the lesions are", "a report's words carry no tissue diagnosis",
     "biopsy of a lesion (the record's month-0 sequencing came from a bone biopsy)",
     ("what are", "malignan", "benign", "mutation", "receptor", "grade")),
]


# --- imaging reports as text --------------------------------------------------------------
def read_of(text: str) -> tuple[str, str]:
    """The overall read a report's words state, and the words it rests on."""
    low = text.lower()
    for read, pattern in READ_WORDS:
        m = re.search(pattern, low)
        if m:
            return read, text[m.start(): m.end()]
    return NOT_STATED, ""


def sites_named_new(text: str) -> list[str]:
    """Sites a report names as new ("new liver lesions" -> Liver), in the order named."""
    out = []
    for m in re.finditer(r"new ([a-z ]+?) (?:lesions?|metastas[ie]s|nodules?|masses|mass)",
                         text.lower()):
        site = SITE_WORDS.get(m.group(1).strip())
        if site and site not in out:
            out.append(site)
    return out


def imaging_reads(events: list[dict]) -> list[dict]:
    """Every imaging read in the record: the imaging reports, and any other note that states an
    imaging read (a clinic visit's "Imaging stable"). Observed: the report's own words, the
    record's own sites field, and no measurement, because the record holds none."""
    out = []
    for e in events:
        if e["kind"] != "Imaging" and "imaging" not in e["text"].lower():
            continue
        read, words = read_of(e["text"])
        if e.get("progression") and read != PROGRESSION:  # the record's flag wins; say so
            read, words = PROGRESSION, "the record's progression flag"
        named = sites_named_new(e["text"])
        recorded = list(e.get("sites", []))
        out.append({
            "month": e["month"], "kind": e["kind"], "text": e["text"], "read": read,
            "words": words, "new_sites": named or recorded, "recorded_sites": recorded,
            "agrees": set(named) == set(recorded) or not named,
            "source": "imaging report" if e["kind"] == "Imaging"
                      else f"{e['kind'].lower()} note stating an imaging read",
            "measurements": NO_MEASUREMENTS, "evidence": OBSERVED})
    return out


def lesion_table(reads: list[dict]) -> list[dict]:
    """One row per named site: when it was first named, every read's status for it, the
    reports that name it, and the measurements (none recorded). A site a read does not name is
    "not named", with that read's overall words: never "stable" for the site itself."""
    rows = {}
    for r in reads:
        for site in r["new_sites"]:
            rows.setdefault(site, {"site": site, "first_named": r["month"], "named_in": [],
                                   "cells": {}, "measurements": NO_MEASUREMENTS,
                                   "evidence": OBSERVED})
            rows[site]["named_in"].append(r["month"])
    for row in rows.values():
        for r in reads:
            if r["month"] < row["first_named"]:
                row["cells"][r["month"]] = "not yet named"
            elif r["month"] in row["named_in"]:
                row["cells"][r["month"]] = "new" if r["month"] == row["first_named"] else "named"
            else:
                row["cells"][r["month"]] = f"not named; overall read: {r['read']}"
    return list(rows.values())


def lead_lag(events: list[dict], reads: list[dict] | None = None) -> list[dict]:
    """Each imaging read against the last tumor-marker result before it (the labs workbench's
    rule, ``muffle.workbench.labs.lead_lag``, on this page's reads): an observed order of events
    in this record, not a validated lead time."""
    reads = imaging_reads(events) if reads is None else reads
    as_events = [{"kind": "Imaging", "month": r["month"], "text": r["text"],
                  "progression": r["read"] == PROGRESSION} for r in reads]
    return _lab_lead_lag(results_table(events), as_events)


# --- measurements on a contour ---------------------------------------------------------------
def longest_diameter_mm(mask: np.ndarray, spacing: tuple[float, float]) -> tuple[float, tuple]:
    """The longest in-plane distance across a 2D mask, in mm, between pixel centres (so it is up
    to one pixel short of the outer edges), and its two end points as (row, col)."""
    from scipy import ndimage

    edge = mask & ~ndimage.binary_erosion(mask)
    pts = np.argwhere(edge)
    if len(pts) < 2:
        return 0.0, ()
    mm = pts * np.asarray(spacing, float)
    d = np.sqrt(((mm[:, None, :] - mm[None, :, :]) ** 2).sum(-1))  # ponytail: O(n²) on edge pixels
    i, j = np.unravel_index(int(np.argmax(d)), d.shape)
    return float(d[i, j]), (tuple(int(v) for v in pts[i]), tuple(int(v) for v in pts[j]))


def volume_ml(mask: np.ndarray, spacing: tuple[float, float, float]) -> float:
    """Voxels × voxel volume (slice spacing × pixel spacing²), in mL."""
    return float(mask.sum()) * float(np.prod(spacing)) / 1000.0


def volume_range_ml(mask: np.ndarray, spacing: tuple[float, float, float]) -> tuple[float, float]:
    """The volume with the contour moved one pixel in and one pixel out on every slice: a range
    for the contour's own uncertainty, not a confidence interval."""
    from scipy import ndimage

    st = np.zeros((1, 3, 3), bool)
    st[0] = ndimage.generate_binary_structure(2, 1)
    return (volume_ml(ndimage.binary_erosion(mask, st), spacing),
            volume_ml(ndimage.binary_dilation(mask, st), spacing))


def kinetics(signal: list[float], times_s: list[float | None] | None = None,
             labels: list[str] | None = None) -> dict:
    """Signal versus phase at a lesion, in the BI-RADS MRI lexicon's terms: the initial phase
    (the strongest post-contrast phase within ``initial_window_s``, or the first post-contrast
    phase when times are unknown) as % over pre-contrast, slow / medium / fast; the delayed
    phase (the last) as % change from that peak, persistent / plateau / washout. The cutoffs are
    the literature's usual values, placeholders until calibrated here."""
    s = [float(v) for v in signal]
    if len(s) < 3 or s[0] <= 0:
        return {"note": "needs a pre-contrast and at least two post-contrast phases",
                "evidence": INFERENCE}
    times = list(times_s) if times_s else [None] * len(s)
    window = CUTOFFS["initial_window_s"][0]
    early = [i for i in range(1, len(s) - 1) if times[i] is not None and times[i] <= window]
    peak = max(early or [1], key=lambda i: s[i])
    initial = 100 * (s[peak] - s[0]) / s[0]
    delayed = 100 * (s[-1] - s[peak]) / s[peak]
    slow, fast = CUTOFFS["initial_slow_below"][0], CUTOFFS["initial_fast_above"][0]
    band = CUTOFFS["delayed_band_pct"][0]
    speed = "slow" if initial < slow else "fast" if initial > fast else "medium"
    curve = ("persistent" if delayed > band else "washout" if delayed < -band else "plateau")
    return {"initial_pct": round(initial, 1), "initial": speed, "peak_phase": peak,
            "delayed_pct": round(delayed, 1), "delayed": curve,
            "curve_type": {"persistent": "I", "plateau": "II", "washout": "III"}[curve],
            "relative": [round(100 * (v - s[0]) / s[0], 1) for v in s],
            "labels": labels or [f"phase {i}" for i in range(len(s))], "times_s": times,
            "evidence": INFERENCE, "sources": [BIRADS, KUHL],
            "status": "implemented; cutoffs literature, placeholder until calibrated",
            "caveat": "mean signal inside the model's contour; the curve shape is suggestive, "
                      "not a diagnosis"}


# --- where to look: the seed rule ------------------------------------------------------------
def skin_rows(pre: np.ndarray, frac: float = 0.2) -> np.ndarray:
    """Per slice and column, the first row (from the anterior edge) above ``frac`` of the
    volume's 99th percentile after light smoothing: the skin surface; -1 where there is none."""
    from scipy import ndimage

    sm = ndimage.gaussian_filter(pre.astype(float), (0, 1.5, 1.5))
    above = sm > frac * np.percentile(sm, 99)
    first = np.argmax(above, axis=1)  # [z, x]
    return np.where(above.any(axis=1), first, -1)


def cleft_row(skin: np.ndarray) -> int | None:
    """The intermammary cleft: per slice, the deepest skin row between the two breasts'
    anterior-most points (one in each half of the image); the median over slices that have
    both. None if no slice shows two breasts."""
    from scipy import ndimage

    deep = []
    for row in skin:
        w = row.size
        left, right = row[: w // 2], row[w // 2:]
        if (left < 0).all() or (right < 0).all():
            continue
        a = int(np.argmin(np.where(left >= 0, left, 10 ** 6)))
        b = w // 2 + int(np.argmin(np.where(right >= 0, right, 10 ** 6)))
        between = row[a: b + 1]
        between = between[between >= 0]
        if between.size:
            deep.append(int(ndimage.median_filter(between, 5).max()))
    return int(np.median(deep)) if deep else None


def breast_region(pre: np.ndarray, spacing: tuple[float, float, float]) -> tuple[np.ndarray, dict]:
    """Where candidates are searched, on a [z, row, col] volume with anterior at row 0: inside
    the body, at least ``skin_mm`` under the skin surface and anterior to the intermammary cleft
    plus ``chest_margin_mm`` (placeholders), which leaves the heart and chest wall out."""
    skin = skin_rows(pre)
    cleft = cleft_row(skin)
    z, h, w = pre.shape
    rows = np.arange(h)[None, :, None]
    under = rows >= (skin[:, None, :] + CUTOFFS["skin_mm"][0] / spacing[1])
    region = (skin[:, None, :] >= 0) & under
    limit = h if cleft is None else min(h, cleft + int(round(CUTOFFS["chest_margin_mm"][0]
                                                           / spacing[1])))
    region &= rows < limit
    return region, {"cleft_row": cleft, "limit_row": int(limit),
                    "rule": "inside the body, under the skin and anterior to the intermammary "
                            "cleft plus a margin (placeholders)"}


def candidates(sub: np.ndarray, region: np.ndarray, spacing: tuple[float, float, float],
               k: int = 3, limit_row: int | None = None) -> tuple[list[dict], dict]:
    """Lesion candidates in a subtraction volume (early post-contrast minus pre-contrast,
    [z, row, col]): voxels above ``seed_percentile`` of the region's values, lightly smoothed,
    opened with a ``seed_open_mm`` ellipsoid (so thin vessels come off a mass) and grouped in
    3D. Left out: groups smaller than ``seed_min_mm3``, vessel-like (more elongated
    than ``seed_max_elongation``), plate-like (flatter than ``seed_max_flatness``) and, with
    ``limit_row``, groups that reach the region's posterior limit (cut by the chest-wall line).
    The rest are ranked by summed enhancement (brighter and larger first). Returns the top ``k``
    and the counts left out, by reason."""
    from scipy import ndimage

    sm = ndimage.gaussian_filter(sub.astype(float), (0.5, 1.0, 1.0))
    thr = float(np.percentile(sm[region], CUTOFFS["seed_percentile"][0])) if region.any() else 0
    r = [max(1, int(round(CUTOFFS["seed_open_mm"][0] / s))) for s in spacing]
    zz, yy, xx = np.ogrid[-r[0]:r[0] + 1, -r[1]:r[1] + 1, -r[2]:r[2] + 1]
    ball = (zz / r[0]) ** 2 + (yy / r[1]) ** 2 + (xx / r[2]) ** 2 <= 1
    lab, n = ndimage.label(ndimage.binary_opening((sm > thr) & region, structure=ball))
    voxel = float(np.prod(spacing))
    found = []
    left_out = {"too small": 0, "vessel-like": 0, "plate-like": 0, "at the chest-wall line": 0}
    for i, sl in enumerate(ndimage.find_objects(lab), start=1):
        comp = lab[sl] == i
        mm3 = float(comp.sum()) * voxel
        if mm3 < CUTOFFS["seed_min_mm3"][0]:
            left_out["too small"] += 1
            continue
        if limit_row is not None and sl[1].stop >= limit_row:
            left_out["at the chest-wall line"] += 1
            continue
        pts = np.argwhere(comp) * np.asarray(spacing, float)
        ev = np.sort(np.linalg.eigvalsh(np.cov(pts.T) + 1e-6 * np.eye(3)))[::-1]
        elong = float(np.sqrt(ev[0] / max(ev[1], 1e-6)))
        flat = float(np.sqrt(ev[1] / max(ev[2], 1e-6)))
        if elong > CUTOFFS["seed_max_elongation"][0]:
            left_out["vessel-like"] += 1
            continue
        if flat > CUTOFFS["seed_max_flatness"][0]:
            left_out["plate-like"] += 1
            continue
        vals = sm[sl][comp]
        found.append({"label": i, "voxels": int(comp.sum()), "seed_mm3": round(mm3, 1),
                      "bbox": [int(v) for s in sl for v in (s.start, s.stop)],
                      "score": float(vals.sum()), "mean_sub": float(vals.mean()),
                      "peak_sub": float(vals.max()), "elongation": round(elong, 2),
                      "flatness": round(flat, 2)})
    found.sort(key=lambda c: -c["score"])
    for rank, c in enumerate(found[:k], start=1):
        c["id"], c["rank"] = f"C{rank}", rank
    return found[:k], {"threshold": thr, "groups": int(n), "proposed": len(found),
                       "left_out": left_out, "labels": lab}


def slice_box(comp2d: np.ndarray) -> list[int] | None:
    """A seed's box on one slice, [col0, row0, col1, row1] in pixels, padded by ``box_pad``."""
    pts = np.argwhere(comp2d)
    if not len(pts):
        return None
    (r0, c0), (r1, c1) = pts.min(0), pts.max(0)
    pad_r = max(2, int(round(CUTOFFS["box_pad"][0] * (r1 - r0 + 1))))
    pad_c = max(2, int(round(CUTOFFS["box_pad"][0] * (c1 - c0 + 1))))
    h, w = comp2d.shape
    return [max(0, c0 - pad_c), max(0, r0 - pad_r), min(w - 1, c1 + pad_c), min(h - 1, r1 + pad_r)]


def dense_fraction(image: np.ndarray, background: float) -> dict:
    """Mammography: the share of breast pixels (above ``background``) above an Otsu threshold
    computed inside the breast. A pixel share with a placeholder rule, not a BI-RADS density
    category and not validated."""
    breast = image > background
    vals = image[breast].astype(float)
    if vals.size < 100:
        return {"note": "no breast found", "evidence": INFERENCE}
    hist, edges = np.histogram(vals, 256)
    p = hist / hist.sum()
    centers = (edges[:-1] + edges[1:]) / 2
    w0 = np.cumsum(p)
    m = np.cumsum(p * centers)
    between = (m[-1] * w0 - m) ** 2 / np.maximum(w0 * (1 - w0), 1e-12)
    thr = float(centers[int(np.argmax(between))])
    return {"dense_fraction": round(float((vals > thr).mean()), 3), "threshold": thr,
            "breast_pixels": int(vals.size), "evidence": INFERENCE,
            "status": "implemented, placeholder rule", "source": CUTOFFS["dense_threshold"][2]}


# --- reading the precomputed results -----------------------------------------------------------
def load_index(folder: str | Path) -> dict[int, list[dict]]:
    """``radiology_results/index.json``: cohort index -> the processed public studies of that
    TCGA patient ({"barcode", "study", "name", "result", "folder", ...}); {} if absent."""
    path = Path(folder) / "index.json"
    if not path.exists():
        return {}
    return {int(k): v for k, v in json.loads(path.read_text(encoding="utf-8"))["cases"].items()}


def load_study(folder: str | Path) -> dict | None:
    """One processed study's ``study.json``, with its folder; None if it isn't there."""
    path = Path(folder) / "study.json"
    if not path.exists():
        return None
    study = json.loads(path.read_text(encoding="utf-8"))
    study["folder"] = str(Path(folder))
    return study


def search(query: str, reads: list[dict], lesions: list[dict] | None = None,
           cannot_see: list[tuple] = CANNOT_SEE) -> dict:
    """Plain-word search: a read ("progression", "stable"), a site ("liver"), a month
    ("month 12"), a candidate ("C2"), a curve ("washout"), "largest". What the test cannot
    show (``cannot_see``: the images' limits or the reports') gets an honest answer naming the
    test that can. Reads come before the limits, so "liver" finds the report naming it."""
    q = query.strip().lower()
    lesions = lesions or []
    if not q:
        return {"understood": False, "answer": "type a read, a site, a month, a candidate or a "
                                               "curve type", "reads": [], "lesions": []}
    if reads:
        for word, site in SITE_WORDS.items():
            if word in q:
                hits = [r for r in reads if site in r["new_sites"]]
                return {"understood": True, "reads": hits, "lesions": [],
                        "answer": f"{len(hits)} read(s) naming {site.lower()} "
                                  + (f"({NO_MEASUREMENTS})" if hits else
                                     "(no read in this record names it)")}
    for what, why, test, words in cannot_see:
        if any(w in q for w in words):
            return {"understood": False, "reads": [], "lesions": [],
                    "answer": f"This test can't see that: {what.lower()} ({why}). "
                              f"{test[0].upper() + test[1:]} could."}
    m = re.search(r"\bmonth\s*(-?\d+)", q)
    if m:
        hits = [r for r in reads if r["month"] == int(m.group(1))]
        return {"understood": True, "reads": hits, "lesions": [],
                "answer": f"{len(hits)} read(s) at month {m.group(1)}"}
    for read in (PROGRESSION, STABLE, RESPONSE):
        if reads and read[:5] in q:
            hits = [r for r in reads if r["read"] == read]
            return {"understood": True, "reads": hits, "lesions": [],
                    "answer": f"{len(hits)} read(s) stating {read}"}
    m = re.fullmatch(r"c(\d)", q)
    if m:
        hits = [c for c in lesions if c["id"].lower() == q]
        return {"understood": True, "reads": [], "lesions": hits,
                "answer": f"candidate {q.upper()}" + ("" if hits else ": not in this study")}
    for curve in ("persistent", "plateau", "washout"):
        if curve in q:
            hits = [c for c in lesions if c.get("kinetics", {}).get("delayed") == curve]
            return {"understood": True, "reads": [], "lesions": hits,
                    "answer": f"{len(hits)} candidate(s) with a {curve} delayed phase"}
    if "largest" in q or "biggest" in q:
        hits = sorted(lesions, key=lambda c: -c.get("volume_ml", 0))[:1]
        return {"understood": True, "reads": [], "lesions": hits,
                "answer": "the largest candidate by volume" if hits else "no candidates here"}
    return {"understood": False, "reads": [], "lesions": [],
            "answer": "this workbench can't answer that. It searches reads (progression, "
                      "stable), sites (liver, bone), months (month 12), candidates (C1), "
                      "curve types (washout) and 'largest'."}

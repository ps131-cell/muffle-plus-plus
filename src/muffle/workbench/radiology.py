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

from muffle.imports import (CLAUSE, NOT_STATED, PROGRESSION, READS, RESPONSE, STABLE,
                            imaging_read, stated)
from muffle.imports import SITE_WORDS as DISTANT_SITES
from muffle.report.case_tools import INFERENCE, OBSERVED
from muffle.workspace import card, finding_key, look
from muffle.workbench.labs import lead_lag as _lab_lead_lag
from muffle.workbench.labs import results_table
from muffle.workspace import record_events

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
    "near_wall_mm": (5, PLACEHOLDER, "a candidate this close to the search region's posterior "
                     "limit is flagged: chest-wall muscle and internal mammary vessels enhance "
                     "there too"),
    "box_pad": (0.15, DESIGN, "a candidate's box on each slice is its seed extent plus 15% "
                "(at least 2 pixels) on every side"),
    "mask_threshold": (0.5, DESIGN, "MedSAM's mask = sigmoid output above 0.5, as in the "
                       "authors' inference code"),
    "dense_threshold": ("Otsu", PLACEHOLDER, "mammography dense pixels: above an Otsu threshold "
                        "inside the breast; a pixel share, not a BI-RADS density category"),
    # change over time (round 2)
    "register_grid_mm": ("4 then 2", DESIGN, "the rigid alignment runs on 4 mm, then 2 mm voxels "
                         "of the two pre-contrast volumes"),
    "residual_search_mm": (10, DESIGN, "the local check searches shifts up to 10 mm (4 mm "
                           "steps, then 2 mm around the best) for a 40 mm cube (30 mm on the "
                           "block grid); a best shift at the search's edge counts as unreliable"),
    "residual_unreliable_mm": (5, PLACEHOLDER, "where the local check finds the aligned studies "
                               "still more than 5 mm apart, the comparison says unreliable here"),
    "residual_min_ncc": (0.5, PLACEHOLDER, "where the best local correlation of the two aligned "
                         "studies stays below 0.5 (no shared structure), unreliable here too"),
    "match_mm": (15, PLACEHOLDER, "a candidate on one date is the same lesion as the nearest "
                 "candidate on the other within 15 mm, after alignment"),
    "grew_pct": (20, PLACEHOLDER, "a candidate grew when its longest diameter rose at least 20% "
                 "and 5 mm (RECIST 1.1's rule for a sum of diameters, Eisenhauer et al., Eur J "
                 "Cancer 2009, doi:10.1016/j.ejca.2008.10.026, borrowed per candidate)"),
    "grew_mm": (5, PLACEHOLDER, "the absolute part of the growth rule (same source)"),
    "shrank_pct": (30, PLACEHOLDER, "a candidate shrank when its longest diameter fell at least "
                   "30% (RECIST 1.1's rule for a sum, borrowed per candidate)"),
    "measurable_mm": (10, "guideline", "RECIST 1.1: a measurable lesion is at least 10 mm; the "
                      "computed sum takes candidates this size on the earlier date"),
    "targets_per_organ": (2, "guideline", "RECIST 1.1: at most two target lesions per organ; the "
                          "breasts counted as one organ here"),
    "asymmetry_points": (10, PLACEHOLDER, "mammography: a left-right difference in dense-pixel "
                         "share above 10 points is shown as asymmetric"),
}

# every value nobody has validated yet, as (what, value) for the Methods page's one table
PLACEHOLDERS = [(k, f"{v} ({note})") for k, (v, tag, note) in CUTOFFS.items() if tag != DESIGN]

# what the workbench gets wrong, as far as it has been seen (docs/radiology.md §6)
KNOWN_FAILURES = [
    "Lesions behind the cleft-plus-margin line (deep, at the chest wall, in the axilla) are never "
    "proposed; non-mass enhancement and vessel-like or plate-like shapes are left out by the "
    "shape rules; foci under about 4 mm vanish in the opening.",
    "The seed rule ranks brightness × size: background enhancement can outrank a small cancer, "
    "and a chest-wall strip (case 563, C2) and a vessel segment (case 937, C3) made the top three.",
    "MedSAM is not validated on breast MRI here; its contour runs past a narrow box (flagged "
    "unsure on the page): case 537's C1 and C2 on 12 of 13 slices, so their sizes rest on unsure "
    "contours.",
    "Kinetics are a mean inside a contour that mixes enhancing and non-enhancing parts; GE phase "
    "times count from the first phase, not the injection, and Siemens times are nominal.",
    "The mammography screening score moves with the crop (right breast 0.42 or 0.37 for two "
    "crops of the same views) and nothing in the record can check it.",
    "Change over time: the alignment is rigid, so it cannot follow the breast's own deformation "
    "between exams (positioning in the coil, compression, weight); where the local check finds "
    "the studies still apart the comparison says unreliable here, but a wrong pairing can stay "
    "within the 15 mm match distance.",
    "Candidates are paired across dates from each date's own top three: a lesion outside one "
    "date's top three is unpaired, which is not the same as gone or new.",
    "The sagittal and coronal views, and the axial view of a sagittal acquisition, are "
    "resampled from slices 1.7–3 mm apart: detail along the slice direction is interpolated.",
    "Phase timing differs between studies and scanners (the example pair's phases start 168–210 s "
    "apart and take minutes each), so kinetics are not compared across dates.",
    "Mammography: no lesion detector (none open, permissive and CPU-ready was found); the "
    "left-right map compares outline-normalised breasts and ignores compression and "
    "positioning.",
]

# The import's distant sites, and the local and regional ones the lesion table tracks too: a new
# chest-wall nodule is a site the report names, though the import's "new metastatic site" alert
# counts distant sites only
SITE_WORDS = DISTANT_SITES | {"lymph node": "Lymph node", "nodal": "Lymph node", "skin": "Skin",
                              "chest wall": "Chest wall", "breast": "Breast"}
# The import's read words (muffle.imports.READS), and the one-line reads of the record and of an
# imported report's event ("read as response"); the first stated read wins, in this order
READ_WORDS = [(read, rf"read as {read}|{words}") for read, words in READS]

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


def pipeline_name(pipeline: dict) -> str:
    """The offline pipeline that made a study, in words, with its version: "the offline
    radiology pipeline (MRI) version 2", not the script's path (study.json's "script")."""
    step = pipeline["script"].split()[-1]
    step = {"mri": "MRI", "mammo": "mammography", "pair": "change pair"}.get(step, step)
    return f"the offline radiology pipeline ({step}) version {pipeline['version']}"


# --- imaging reports as text --------------------------------------------------------------
def read_of(text: str) -> tuple[str, str]:
    """The overall read a report's words state, and the words it rests on, by the import's rule
    (``muffle.imports.imaging_read``): clause by clause, a negated ("No evidence of
    progression") or hedged ("possible progression") mention is set aside."""
    clauses = [c.strip() for c in CLAUSE.split(text) if c and c.strip()]
    for read, pattern in READ_WORDS:
        for clause in clauses:
            for m in re.finditer(pattern, clause.lower()):
                if not stated(clause.lower(), m):
                    return read, clause[m.start(): m.end()]
    return NOT_STATED, ""


def sites_named_new(text: str) -> list[str]:
    """Sites a report names as new ("new liver lesions" -> Liver), in the order named: the
    import's rule with this page's wider site list ("No new liver lesions" names none)."""
    return imaging_read(text, SITE_WORDS)["new_sites"]


def file_events(pf, version: int | None = None) -> list[dict]:
    """The record the report page reads for a patient file: the synthetic record's events and
    each imported test's event (``workspace.record_events``), up to report version
    ``version``'s month. A TCGA file has only its imports: never the synthetic record."""
    events = record_events(pf)
    month = None if version is None else pf.versions[version].month
    return events if month is None else [e for e in events if e["month"] <= month]


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
            "imported": bool(e.get("imported")),  # read by the import's text rule
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
                                   "evidence": OBSERVED, "imported": r.get("imported", False)})
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


# --- change over time: rigid alignment of two studies ----------------------------------------
REGISTRATION = ("rigid alignment (three rotations and three shifts) of the earlier study's "
                "pre-contrast volume onto the later one's, maximising normalised mutual "
                "information (Studholme et al., Pattern Recognit 1999, "
                "doi:10.1016/S0031-3203(98)00091-0) with Powell's method on 4 mm, then 2 mm "
                "voxels (scipy); started from the two bodies' centres of mass")


def rigid_matrix(params) -> np.ndarray:
    """The rotation of ``params`` (degrees about the Z, Y and X axes, applied X first) as a 3×3
    matrix over (Z, Y, X) coordinates in mm."""
    out = np.eye(3)
    for axis, deg in zip((0, 1, 2), params[:3], strict=True):  # Z, then Y, then X
        a, b = [k for k in range(3) if k != axis]
        r = np.eye(3)
        c, s = np.cos(np.radians(deg)), np.sin(np.radians(deg))
        r[a, a], r[a, b], r[b, a], r[b, b] = c, -s, s, c
        out = out @ r
    return out


def map_points(points_mm, transform: dict, inverse: bool = False) -> np.ndarray:
    """Points (N×3, Z Y X mm) of the later study's frame into the earlier one's (q = R(p − c) +
    c + t), or back with ``inverse``."""
    p = np.atleast_2d(np.asarray(points_mm, float))
    r, c, t = (np.asarray(transform[k], float) for k in ("matrix", "center_mm", "shift_mm"))
    if inverse:
        return (p - c - t) @ r + c  # R⁻¹ = Rᵀ
    return (p - c) @ r.T + c + t


def _sample(vol: np.ndarray, spacing, points_mm: np.ndarray, order: int = 1) -> np.ndarray:
    """``vol`` at points in its own frame (index × spacing, mm); NaN outside the volume."""
    from scipy import ndimage

    idx = (points_mm / np.asarray(spacing, float)).T
    inside = np.all((idx >= 0) & (idx <= np.array(vol.shape)[:, None] - 1), axis=0)
    out = np.full(points_mm.shape[0], np.nan)
    out[inside] = ndimage.map_coordinates(vol, idx[:, inside], order=order, mode="nearest")
    return out


def _nmi(a: np.ndarray, b: np.ndarray, bins: int = 32) -> float:
    """Normalised mutual information (H(A) + H(B)) / H(A, B) of two samples."""
    def binned(x):
        edges = np.percentile(x, np.linspace(0, 100, bins + 1)[1:-1])
        return np.searchsorted(edges, x)

    joint = np.bincount(binned(a) * bins + binned(b), minlength=bins * bins) / a.size
    pa, pb = joint.reshape(bins, bins).sum(1), joint.reshape(bins, bins).sum(0)

    def h(p):
        p = p[p > 0]
        return float(-(p * np.log(p)).sum())

    return (h(pa) + h(pb)) / max(h(joint), 1e-12)


def _ncc(a: np.ndarray, b: np.ndarray) -> float:
    ok = ~(np.isnan(a) | np.isnan(b))
    if ok.sum() < 10:
        return float("nan")
    a, b = a[ok] - a[ok].mean(), b[ok] - b[ok].mean()
    return float((a * b).sum() / max(np.sqrt((a * a).sum() * (b * b).sum()), 1e-12))


def _tissue_centre(vol: np.ndarray, spacing) -> np.ndarray:
    from scipy import ndimage

    return np.array(ndimage.center_of_mass(vol > 0.2 * np.percentile(vol, 99))) * \
        np.asarray(spacing, float)


def register(fixed: np.ndarray, moving: np.ndarray, spacing_f, spacing_m,
             mask: np.ndarray | None = None) -> dict:
    """Rigid alignment of ``moving`` (the earlier study) onto ``fixed`` (the later one), both
    [Z, Y, X] with their own spacing in mm (``REGISTRATION``). ``mask`` (fixed's shape) limits
    the voxels that count, e.g. the breasts and the air in front of them. Returns the transform
    (``map_points``: later frame -> earlier frame) and the similarity before and after."""
    import time

    from scipy import ndimage, optimize

    start = time.time()
    rng = np.random.default_rng(0)
    center = _tissue_centre(fixed, spacing_f)
    x0 = x = np.r_[0.0, 0.0, 0.0, _tissue_centre(moving, spacing_m) - center]
    evaluations = 0
    for grid in (4.0, 2.0):
        extent = (np.array(fixed.shape) - 1) * np.asarray(spacing_f, float)
        pts = np.stack(np.meshgrid(*[np.arange(0, e + 1e-6, grid) for e in extent],
                                   indexing="ij"), -1).reshape(-1, 3)
        if mask is not None:
            pts = pts[_sample(mask.astype(np.float32), spacing_f, pts, order=0) > 0.5]
        if len(pts) > 200_000:  # a fixed random sample of the voxels, as Mattes et al. do
            pts = pts[rng.choice(len(pts), 200_000, replace=False)]

        def smooth(v, sp, grid=grid):
            return ndimage.gaussian_filter(v.astype(np.float32),
                                           [max(0.0, grid / (2 * s) - 0.5) for s in sp])

        vals, m = _sample(smooth(fixed, spacing_f), spacing_f, pts), smooth(moving, spacing_m)

        def cost(p, pts=pts, vals=vals, m=m):
            nonlocal evaluations
            evaluations += 1
            t = {"matrix": rigid_matrix(p), "center_mm": center, "shift_mm": p[3:]}
            got = _sample(m, spacing_m, map_points(pts, t))
            ok = ~np.isnan(got)
            if ok.mean() < 0.5:  # most of the fixed voxels fall outside the moving volume
                return 0.0
            return -_nmi(vals[ok], got[ok])

        x = optimize.minimize(cost, x, method="Powell",
                              options={"xtol": 1e-2, "ftol": 1e-5, "maxfev": 3000}).x
    return {"method": REGISTRATION, "angles_deg": [round(float(v), 2) for v in x[:3]],
            "shift_mm": [round(float(v), 2) for v in x[3:]],
            "matrix": rigid_matrix(x).round(6).tolist(),
            "center_mm": [round(float(v), 2) for v in center],
            "nmi_start": round(-cost(x0), 4), "nmi_after": round(-cost(x), 4),
            "evaluations": evaluations, "seconds": round(time.time() - start, 1)}


def local_residual(fixed: np.ndarray, moving: np.ndarray, spacing_f, spacing_m,
                   transform: dict, at_mm, half_mm: float = 20.0) -> dict:
    """How far off the rigid alignment still is at one place of the later study: the shift (4 mm
    steps, then 2 mm, up to ``residual_search_mm``) that best matches a ``half_mm`` cube of the
    later study to the aligned earlier one, by normalised cross-correlation. Above
    ``residual_unreliable_mm``, or with the best correlation under ``residual_min_ncc``, the
    comparison is unreliable here."""
    step, search = 2.0, CUTOFFS["residual_search_mm"][0]
    g = np.arange(-half_mm, half_mm + step / 2, step)
    cube = np.stack(np.meshgrid(g, g, g, indexing="ij"), -1).reshape(-1, 3) + \
        np.asarray(at_mm, float)
    a = _sample(fixed.astype(np.float32), spacing_f, cube)
    if np.nanstd(a) < 1e-6 or np.isnan(a).mean() > 0.5:
        return {"at_mm": [round(float(v), 1) for v in at_mm], "shift_mm": None,
                "residual_mm": None, "ncc_aligned": None, "ncc_best": None,
                "reliable": False, "why": "outside the later study or no structure to match"}
    m = moving.astype(np.float32)
    seen = {}

    def score(shift) -> float:
        key = tuple(float(v) for v in shift)
        if key not in seen:
            seen[key] = _ncc(a, _sample(m, spacing_m, map_points(cube + shift, transform)))
        return seen[key]

    # 4 mm steps over the search, then 2 mm steps around the best (about 150 shifts, not 1,331)
    coarse = np.arange(-2 * step * (search // (2 * step)), search + step / 2, 2 * step)
    grid = np.stack(np.meshgrid(coarse, coarse, coarse, indexing="ij"), -1).reshape(-1, 3)
    centre = max(grid, key=score)
    fine = np.stack(np.meshgrid(*[np.clip(c + np.array([-step, 0, step]), -search, search)
                                  for c in centre], indexing="ij"), -1).reshape(-1, 3)
    shift = np.array(max(fine, key=score), float)
    best, ncc0 = (score(shift), None), score(np.zeros(3))
    residual = float(np.linalg.norm(shift))
    edge = bool(np.abs(shift).max() >= search)  # the best shift is at the search's edge
    reliable = residual <= CUTOFFS["residual_unreliable_mm"][0] and \
        best[0] >= CUTOFFS["residual_min_ncc"][0] and not edge
    why = "" if reliable else (
        f"the studies are still {'at least ' if edge else ''}{residual:.0f} mm apart here"
        if residual > CUTOFFS["residual_unreliable_mm"][0] or edge else
        f"little shared structure here (best correlation {best[0]:.2f})")
    return {"at_mm": [round(float(v), 1) for v in at_mm], "shift_mm": shift.tolist(),
            "residual_mm": round(residual, 1), "at_search_edge": edge,
            "ncc_aligned": round(float(ncc0), 3), "ncc_best": round(float(best[0]), 3),
            "reliable": bool(reliable), "why": why}


# --- change over time: the same lesion on two dates -------------------------------------------
def match_candidates(earlier: list[dict], later: list[dict], transform: dict,
                     residuals: dict | None = None) -> list[dict]:
    """Pairs of candidates that are the same place on both dates: each later candidate's
    centroid mapped into the earlier frame (with its local residual's shift when there is one),
    paired with the nearest earlier candidate within ``match_mm``, nearest pairs first. Unpaired
    candidates come back with the other side None: not proposed on that date by the seed rule's
    top three, which is not the same as gone or new."""
    residuals = residuals or {}
    dist = []
    for b in later:
        if not b.get("centroid_mm"):
            continue
        shift = (residuals.get(b["id"]) or {}).get("shift_mm") or [0, 0, 0]
        q = map_points(np.asarray(b["centroid_mm"]) + shift, transform)[0]
        for a in earlier:
            if a.get("centroid_mm"):
                dist.append((float(np.linalg.norm(q - np.asarray(a["centroid_mm"]))), a["id"],
                             b["id"]))
    pairs, used_a, used_b = [], set(), set()
    for d, a, b in sorted(dist):
        if d <= CUTOFFS["match_mm"][0] and a not in used_a and b not in used_b:
            pairs.append({"earlier": a, "later": b, "distance_mm": round(d, 1)})
            used_a.add(a)
            used_b.add(b)
    pairs += [{"earlier": None, "later": b["id"], "distance_mm": None} for b in later
              if b["id"] not in used_b]
    pairs += [{"earlier": a["id"], "later": None, "distance_mm": None} for a in earlier
              if a["id"] not in used_a]
    return pairs


def lesion_change(a: dict | None, b: dict | None) -> dict:
    """One lesion's change from the earlier candidate ``a`` to the later ``b``: the longest
    diameter and volume on both dates, the change, and whether it grew or shrank beyond the
    placeholder rules (``grew_pct`` and ``grew_mm``, ``shrank_pct``) by more than twice the
    measurement's own pixel uncertainty. Model inference throughout."""
    if a is None or b is None:
        return {"status": "not proposed on the " + ("earlier" if a is None else "later")
                + " date", "ld_change_mm": None, "ld_change_pct": None, "evidence": INFERENCE}
    la, lb = a["longest_diameter_mm"], b["longest_diameter_mm"]
    d = lb - la
    pct = 100 * d / la if la else None
    noise = 2 * max(a.get("ld_uncertainty_mm", 0), b.get("ld_uncertainty_mm", 0))
    if pct is not None and d >= CUTOFFS["grew_mm"][0] and pct >= CUTOFFS["grew_pct"][0] \
            and d > noise:
        status = "grew beyond the placeholder rule"
    elif pct is not None and pct <= -CUTOFFS["shrank_pct"][0] and -d > noise:
        status = "shrank beyond the placeholder rule"
    else:
        status = "within the placeholder rules"
    va, vb = a["volume_ml"], b["volume_ml"]
    ra, rb = a["volume_range_ml"], b["volume_range_ml"]
    return {"status": status, "ld_mm": [la, lb], "ld_change_mm": round(d, 1),
            "ld_change_pct": round(pct, 0) if pct is not None else None,
            "volume_ml": [va, vb], "volume_change_ml": round(vb - va, 2),
            "volume_overlap": bool(ra[0] <= rb[1] and rb[0] <= ra[1]),
            "noise_mm": round(noise, 2), "evidence": INFERENCE}


def computed_sum(rows: list[dict]) -> dict:
    """A RECIST-style sum of longest diameters, computed and labeled so, never a response call:
    the paired candidates at least ``measurable_mm`` on the earlier date, the largest
    ``targets_per_organ`` (the breasts as one organ), on both dates. The candidates are a
    model's, not a reader's target lesions, and RECIST's response categories are not applied."""
    big = [r for r in rows if r["change"].get("ld_mm") and
           r["change"]["ld_mm"][0] >= CUTOFFS["measurable_mm"][0]]
    targets = sorted(big, key=lambda r: -r["change"]["ld_mm"][0])[:CUTOFFS["targets_per_organ"][0]]
    left = [r["earlier"] for r in rows if r["earlier"] and not r["later"]]
    note = ("computed on model candidates, not a RECIST response call: the candidates are not a "
            "reader's target lesions and no response category is applied")
    if not targets:
        return {"targets": [], "sum_mm": None, "note": "no paired candidate of "
                f"{CUTOFFS['measurable_mm'][0]} mm or more on the earlier date: nothing to sum; "
                + note, "evidence": INFERENCE}
    s0 = sum(r["change"]["ld_mm"][0] for r in targets)
    s1 = sum(r["change"]["ld_mm"][1] for r in targets)
    return {"targets": [f"{r['earlier']}→{r['later']}" for r in targets],
            "sum_mm": [round(s0, 1), round(s1, 1)], "change_mm": round(s1 - s0, 1),
            "change_pct": round(100 * (s1 - s0) / s0, 0),
            "left_out": left, "note": note, "evidence": INFERENCE}


def protocol_differences(earlier: dict, later: dict) -> list[str]:
    """What differs between two studies' acquisitions, said before any 'larger' or 'smaller'."""
    out = []
    a, b = earlier["study"], later["study"]
    for key, what in (("scanner", "scanner"), ("field_t", "field strength (T)"),
                      ("contrast", "contrast agent as recorded")):
        if a.get(key) != b.get(key):
            out.append(f"{what}: {a.get(key) or 'not recorded'} → {b.get(key) or 'not recorded'}")
    sa, sb = a.get("sequence", {}), b.get("sequence", {})
    for key, what in (("tr_ms", "repetition time (ms)"), ("te_ms", "echo time (ms)"),
                      ("flip_deg", "flip angle (°)")):
        if sa.get(key) and sb.get(key) and abs(sa[key] - sb[key]) > 0.05 * sa[key]:
            out.append(f"{what}: {sa[key]:g} → {sb[key]:g}")
    da, db = earlier["display"].get("acquisition", {}), later["display"].get("acquisition", {})
    def fmt(v):
        return " × ".join(f"{x:.2f}" for x in v) if isinstance(v, list) else v

    for key, what in (("plane", "acquisition plane"), ("slice_mm", "slice spacing (mm)"),
                      ("pixel_mm", "pixel size (mm)")):
        if da.get(key) != db.get(key):
            out.append(f"{what}: {fmt(da.get(key))} → {fmt(db.get(key))}")
    ta = [p["time_s"] for p in earlier["phases"]]
    tb = [p["time_s"] for p in later["phases"]]
    if ta != tb:
        out.append("phase times (s from the pre-contrast start): "
                   f"{', '.join(f'{t:g}' for t in ta if t is not None)} → "
                   f"{', '.join(f'{t:g}' for t in tb if t is not None)}; kinetics are not "
                   "directly comparable")
    return out


def pair_change(pair: dict, earlier: dict, later: dict) -> dict:
    """The change view's content for a study pair (``pair.json``): the protocol differences
    first, the alignment and where it is unreliable, one row per lesion (paired by
    ``match_candidates``) with both dates' sizes and the change, the computed sum, and a
    'what changed' paragraph in the shared grammar's words."""
    a_by = {c["id"]: c for c in earlier["candidates"]}
    b_by = {c["id"]: c for c in later["candidates"]}
    res = pair.get("residuals", {})
    rows = []
    for m in pair["matches"]:
        a, b = a_by.get(m["earlier"]), b_by.get(m["later"])
        r = res.get(m["later"]) if m["later"] else None
        ch = lesion_change(a, b)
        rows.append({"lesion": f"{m['earlier'] or '—'} → {m['later'] or '—'}",
                     "earlier": m["earlier"], "later": m["later"],
                     "side": (b or a)["side"], "distance_mm": m["distance_mm"],
                     "change": ch, "reliable": r["reliable"] if r else None,
                     "residual": r, "evidence": INFERENCE})
    total = computed_sum(rows)
    diffs = protocol_differences(earlier, later)
    reg = pair["registration"]
    d0, d1 = earlier["study"]["date"], later["study"]["date"]
    parts = [f"Two studies, {d0} and {d1}."]
    parts.append("Before any 'larger' or 'smaller': " + ("; ".join(diffs) if diffs else
                                                       "no protocol difference found in the "
                                                       "headers") + ".")
    unreliable = [x["lesion"] for x in rows if x["reliable"] is False]
    parts.append(f"Rigid alignment: rotations {', '.join(f'{v:g}°' for v in reg['angles_deg'])}, "
                 f"shifts {', '.join(f'{v:g} mm' for v in reg['shift_mm'])}; breast tissue "
                 "deforms between exams, which a rigid alignment cannot follow"
                 + (f"; unreliable here: {', '.join(unreliable)}" if unreliable else "") + ".")
    for x in rows:
        c = x["change"]
        if c.get("ld_mm"):
            parts.append(f"{x['lesion']} ({x['side']}): longest diameter {c['ld_mm'][0]:g} → "
                         f"{c['ld_mm'][1]:g} mm ({c['ld_change_mm']:+g} mm, "
                         f"{c['ld_change_pct']:+.0f}%), {c['status']}; volume "
                         f"{c['volume_ml'][0]:g} → {c['volume_ml'][1]:g} mL (the one-pixel ranges "
                         + ("overlap" if c["volume_overlap"] else "do not overlap") + ")"
                         + ("" if x["reliable"] is not False else "; alignment unreliable here")
                         + ".")
    alone_b = [x["later"] for x in rows if x["earlier"] is None]
    alone_a = [x["earlier"] for x in rows if x["later"] is None]
    if alone_a or alone_b:
        parts.append("Not paired: " + "; ".join(
            f"{', '.join(ids)} of the {when} date (not proposed on the {other})"
            for ids, when, other in ((alone_b, "later", "earlier"), (alone_a, "earlier", "later"))
            if ids) + "; the seed rule's top three on each date need not hold the same lesions, "
            "so unpaired is not gone or new.")
    if total["sum_mm"]:
        parts.append(f"Sum of longest diameters ({', '.join(total['targets'])}): "
                     f"{total['sum_mm'][0]:g} → {total['sum_mm'][1]:g} mm "
                     f"({total['change_pct']:+.0f}%), {total['note']}.")
    else:
        parts.append(total["note"][0].upper() + total["note"][1:] + ".")
    return {"rows": rows, "sum": total, "protocol": diffs, "registration": reg,
            "blocks": pair.get("blocks", []), "dates": [d0, d1],
            "what_changed": " ".join(parts), "evidence": INFERENCE,
            "label": earlier.get("example") or later.get("example")}


def report_change(reads: list[dict], earlier_month: int, later_month: int) -> dict:
    """The same change view where only report text exists: per named site, what the earlier and
    the later read say (``lesion_table``'s cells), no sizes (``NO_MEASUREMENTS``), no sum."""
    table = lesion_table(reads)
    rows = []
    for t in table:
        c0, c1 = t["cells"].get(earlier_month, ""), t["cells"].get(later_month, "")
        if t["first_named"] > later_month:
            continue
        change = ("first named on the later read" if c1 == "new" else
                  "named on both reads" if c0 in ("new", "named") and c1 == "named" else
                  "named earlier, not named on the later read" if c0 in ("new", "named") else
                  "named before the earlier read; neither read names it" if
                  t["first_named"] < earlier_month else "")
        rows.append({"lesion": t["site"], "earlier": c0, "later": c1, "change": change,
                     "measurements": NO_MEASUREMENTS, "evidence": OBSERVED})
    by_month = {r["month"]: r for r in reads}
    r0, r1 = by_month.get(earlier_month), by_month.get(later_month)
    text = (f"Reads of month {earlier_month} ({r0['read'] if r0 else 'none'}) and month "
            f"{later_month} ({r1['read'] if r1 else 'none'}). "
            + " ".join(f"{r['lesion']}: {r['change']}." for r in rows if r["change"])
            + f" No sizes: {NO_MEASUREMENTS}, so no sum of diameters can be computed; the "
              "reports' own words are the only change shown.")
    return {"rows": rows, "sum": {"sum_mm": None, "note": f"not computable: {NO_MEASUREMENTS}"},
            "what_changed": text, "evidence": OBSERVED}


# --- multiplanar views of the shipped volume ----------------------------------------------------
def shown_spacing(display: dict) -> tuple[float, float, float]:
    """The shipped volume's spacing (between shown slices, rows, columns) in mm."""
    return (display["slice_step"] * display["slice_mm"], display["pixel_mm"],
            display["pixel_mm"])


def anisotropy(display: dict) -> str:
    """The shipped volume's voxel shape in words, for the multiplanar views' captions."""
    dz, px, _ = shown_spacing(display)
    acq = display.get("acquisition", {})
    native = (f"; acquired {acq['plane']} with {acq['slice_mm']:g} mm between slices and "
              f"{acq['pixel_mm'][0]:g} mm pixels" if acq else "")
    return (f"{dz:g} mm between shown slices against {px:g} mm pixels: voxels {dz / px:.1f}× "
            f"longer along the body axis{native}; the sagittal and coronal views are "
            "resampled linearly to square pixels, so detail along the body axis is "
            "interpolated, not seen")


def candidate_mask(c: dict, shape: tuple[int, int, int]) -> np.ndarray:
    """A candidate's contour as a [shown slice, row, col] mask on the shipped grid, filled from
    its per-slice polygons (even-odd, so a hole stays a hole)."""
    from PIL import Image, ImageDraw

    n, h, w = shape
    out = np.zeros(shape, bool)
    for i, s in c["per_slice"].items():
        for poly in s["contours"]:
            if len(poly) > 2:
                img = Image.new("1", (w, h), 0)
                ImageDraw.Draw(img).polygon([tuple(p) for p in poly], fill=1)
                out[int(i)] ^= np.asarray(img, bool)
    return out


def reslice(vol: np.ndarray, plane: str, index: int, display: dict,
            order: int = 1) -> np.ndarray:
    """One plane of a shipped [shown slice, row, col] volume at square pixels: axial (slice
    ``index``), coronal (row ``index``) or sagittal (column ``index``). Coronal and sagittal have
    the head at the top, the patient's right on the left (coronal) and anterior on the left
    (sagittal); the body axis is resampled from the slice spacing to the pixel size (linear, or
    nearest for a mask with ``order=0``)."""
    if plane == "axial":
        return vol[index]
    pts, shape = frame_points(display, plane, index)
    got = _sample(vol.astype(np.float32), shown_spacing(display), pts, order=order)
    return np.nan_to_num(got).reshape(shape).astype(vol.dtype)


def _reslice_rows(display: dict) -> int:
    dz, px, _ = shown_spacing(display)
    return int(round((display["slices"] - 1) * dz / px)) + 1


def reslice_row(i: float, display: dict) -> float:
    """Where shown slice ``i`` falls on a resliced (coronal or sagittal) view's rows."""
    dz, px, _ = shown_spacing(display)
    return _reslice_rows(display) - 1 - i * dz / px


def frame_points(display: dict, plane: str, index: int) -> tuple[np.ndarray, tuple[int, int]]:
    """Every shown pixel of one axial, coronal or sagittal view, as (Z, Y, X) mm in the study's
    own frame (index × spacing from the first shown slice and the first row and column)."""
    dz, px, _ = shown_spacing(display)
    h, w = display["rows"], display["cols"]
    if plane == "axial":
        yy, xx = np.mgrid[:h, :w]
        pts = np.stack([np.full(yy.shape, index * dz), yy * px, xx * px], -1)
    else:
        rows = _reslice_rows(display)
        zz = (rows - 1 - np.arange(rows)) * px  # head at the top
        other = np.arange(w if plane == "coronal" else h) * px
        z2, o2 = np.meshgrid(zz, other, indexing="ij")
        fixed = np.full(z2.shape, index * px)
        pts = np.stack([z2, fixed, o2] if plane == "coronal" else [z2, o2, fixed], -1)
    return pts.reshape(-1, 3), pts.shape[:2]


def aligned_view(moving: np.ndarray, moving_display: dict, display: dict, transform: dict,
                 plane: str, index: int) -> np.ndarray:
    """The earlier study (``moving``, its shipped volume) at the later study's view: each shown
    pixel of the later view mapped through the rigid alignment (``map_points``) and sampled
    linearly; 0 where the earlier study has no data."""
    pts, shape = frame_points(display, plane, index)
    got = _sample(moving.astype(np.float32), shown_spacing(moving_display),
                  map_points(pts, transform))
    return np.nan_to_num(got, nan=0.0).reshape(shape).clip(0, 255).astype(np.uint8)


# --- mammography: geometry for the linked zoom and left-right asymmetry ---------------------------
def breast_outline(img: np.ndarray) -> dict:
    """On a shipped 8-bit mammogram: the breast (the largest region brighter than 8% of the
    image's 99th percentile), the chest-wall edge (the image side it touches most) and the
    nipple (its pixel farthest from that edge, the middle row of those). Geometry for the linked
    zoom, not a reading."""
    from scipy import ndimage

    sm = ndimage.uniform_filter(img.astype(float), 5)
    lab, n = ndimage.label(sm > 0.08 * np.percentile(sm, 99))
    if not n:
        return {"mask": np.zeros(img.shape, bool), "chest": "left", "nipple": None}
    sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1))
    mask = lab == int(np.argmax(sizes)) + 1
    chest = "left" if mask[:, 0].sum() >= mask[:, -1].sum() else "right"
    cols = np.where(mask.any(0))[0]
    far = cols.max() if chest == "left" else cols.min()
    rows = np.where(mask[:, far])[0]
    return {"mask": mask, "chest": chest, "nipple": (int(far), int(np.median(rows)))}


def nipple_band(outline: dict, depth_mm: float, half_mm: float, pixel_mm: float) -> tuple:
    """The columns (x0, x1) of a band ``depth_mm`` ± ``half_mm`` behind the nipple, toward the
    chest wall: the same band on the CC and the MLO view of a breast (a lesion's distance from
    the nipple is about the same on both views)."""
    x = outline["nipple"][0]
    toward = -1 if outline["chest"] == "left" else 1
    a = x + toward * (depth_mm - half_mm) / pixel_mm
    b = x + toward * (depth_mm + half_mm) / pixel_mm
    return int(round(min(a, b))), int(round(max(a, b)))


def asymmetry(views: list[dict]) -> list[dict]:
    """Left-right difference in dense-pixel share per view (CC, MLO), from the shipped study's
    per-view shares (``dense_fraction``): a placeholder rule (``asymmetry_points``), not a
    BI-RADS asymmetry finding."""
    by = {(v["laterality"], v["view"]): v["dense"].get("dense_fraction") for v in views}
    out = []
    for view in ("CC", "MLO"):
        r, left = by.get(("R", view)), by.get(("L", view))
        if r is None or left is None:
            continue
        d = 100 * (r - left)
        out.append({"view": view, "right": r, "left": left, "difference_points": round(d, 1),
                    "asymmetric": abs(d) > CUTOFFS["asymmetry_points"][0],
                    "rule": f"placeholder: more than {CUTOFFS['asymmetry_points'][0]} points "
                            "apart", "evidence": INFERENCE})
    return out


def asymmetry_map(right: np.ndarray, left: np.ndarray, size: tuple[int, int] = (160, 120)) -> dict:
    """A dense-pixel difference map of one view pair: each breast cropped to its outline, turned
    so the chest wall is on the left, resampled to ``size`` (rows, columns) and thresholded by
    one Otsu threshold over both breasts (``dense_fraction``); +1 dense on the right breast
    only, −1 on the left only. Placeholder: it ignores compression, positioning and breast
    size."""
    from scipy import ndimage

    crops = []
    for img in (right, left):
        o = breast_outline(img)
        rows, cols = np.where(o["mask"].any(1))[0], np.where(o["mask"].any(0))[0]
        if not len(rows):
            return {"map": np.zeros(size, int), "note": "no breast found"}
        crop = np.where(o["mask"], img, 0)[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
        if o["chest"] == "right":
            crop = crop[:, ::-1]
        crops.append(ndimage.zoom(crop.astype(float), (size[0] / crop.shape[0],
                                                       size[1] / crop.shape[1]),
                                  order=1)[:size[0], :size[1]])
    thr = dense_fraction(np.concatenate(crops), background=0.5).get("threshold", np.inf)
    diff = (crops[0] > thr).astype(int) - (crops[1] > thr).astype(int)
    return {"map": diff, "right_only": float((diff > 0).mean()),
            "left_only": float((diff < 0).mean()), "evidence": INFERENCE,
            "rule": "placeholder: Otsu dense pixels on outline-normalised breasts, mirrored"}


def example_studies() -> list[dict]:
    """The example pair's two studies in ``load_index``'s shape (a test built from one needs
    ``details["root"] = "example"``); [] when the pair is not in this checkout."""
    loaded = load_pair(EXAMPLE)
    return [{"barcode": s["barcode"], "study": s["study"]["date"], "modality": s["modality"],
             "name": f"{s['kind']}, public example pair ({s['study']['date']})",
             "result": f"{s['study']['scanner']} {s['study']['field_t']:g} T, "
                       f"{len(s['phases'])} phases (public example, not a patient file)",
             "folder": Path(s["folder"]).name} for s in loaded[1:]] if loaded else []


def load_pair(folder: str | Path) -> tuple[dict, dict, dict] | None:
    """The example study pair (``pair.json`` and its two studies, earlier first), or None."""
    path = Path(folder) / "pair.json"
    if not path.exists():
        return None
    pair = json.loads(path.read_text(encoding="utf-8"))
    studies = [load_study(Path(folder) / pair[k]) for k in ("earlier", "later")]
    return (pair, *studies) if all(studies) else None


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


def look_here(study: dict, change: dict | None = None) -> list[dict]:
    """What to check by eye in a processed study, per candidate, with the reason; with a study
    pair's ``change`` (``pair_change``) also where the alignment is unreliable and what grew or
    shrank beyond the placeholder rules."""
    out = []
    later = change is not None and study["study"]["date"] == change["dates"][1]
    for r in (change or {}).get("rows", []):
        cid = r["later"] if later else r["earlier"]
        if cid is None:
            continue
        if r["reliable"] is False:
            out.append({"candidate": cid, "why": f"alignment with the other date unreliable "
                        f"here ({r['residual']['why']})"})
        if r["change"]["status"].startswith(("grew", "shrank")):
            out.append({"candidate": cid, "why": f"{r['change']['status']} between "
                        f"{change['dates'][0]} and {change['dates'][1]} ({r['lesion']})"})
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
        if gap < CUTOFFS["near_wall_mm"][0]:
            out.append({"candidate": c["id"], "why": f"{gap:.0f} mm from the search region's "
                        "posterior limit: chest-wall muscle and internal mammary vessels enhance "
                        "there too"})
        if c["rank"] > 1 and c["seed"]["mean_sub"] > study["candidates"][0]["seed"]["mean_sub"]:
            out.append({"candidate": c["id"], "why": "brighter on average than C1, ranked lower "
                        "only because it is smaller"})
    return out


# --- the workbench contract (docs/WORKBENCHES.md §1): the patient file's overview ----------------

RESULTS = Path(__file__).resolve().parents[3] / "app" / "workbenches" / "radiology_results"
REPORT_METHOD = ("report reading rules version 2 (the import's imaging-report rule: word patterns "
                 "for the read and for new sites, negated and hedged clauses set aside, "
                 "cross-checked against the record's own sites field), no model")


def _tests(pf, version: int | None) -> list:
    vs = pf.versions[: len(pf.versions) if version is None else version + 1]
    return [t for v in vs for t in v.tests if t.workbench == "imaging"]


EXAMPLE = RESULTS.parent / "radiology_example"  # the public example study pair


def study_folder(t) -> Path:
    """Where an imaging test's processed study is: the bundle's results, or the example pair's
    folder for a test with ``details["root"] == "example"``."""
    return (EXAMPLE if t.details.get("root") == "example" else RESULTS) / t.details["folder"]


def _studies(pf, version: int | None) -> list[tuple]:
    return [(t, s) for t in _tests(pf, version) if "folder" in t.details
            for s in [load_study(study_folder(t))] if s is not None]


def pairs_of(studies: list[tuple]) -> list[tuple]:
    """(earlier test, later test, change, later study) for every two MR studies of one patient
    that a ``pair.json`` next to them aligns; the change is ``pair_change``'s."""
    out = []
    for folder in {Path(s["folder"]).parent for _, s in studies if s["modality"] == "MR"}:
        loaded = load_pair(folder)
        if not loaded:
            continue
        pair, earlier, later = loaded
        by = {Path(s["folder"]).name: t for t, s in studies}
        if pair["earlier"] in by and pair["later"] in by:
            out.append((by[pair["earlier"]], by[pair["later"]], pair_change(pair, earlier, later),
                        later))
    return out


def _reads(pf, version: int | None) -> list[dict]:
    """The file's imaging reads up to the version's month (the report page's own source)."""
    return imaging_reads(file_events(pf, version))


def _opens(t) -> tuple:
    return ("Tests", t.kind, t.month, t.name)


def summary(pf, version: int | None = None) -> dict:
    """A study pair's change (where two dates exist), a processed public study's headline (its
    contours, measurements or scores, and the structured report's BI-RADS), else the lesion
    table of the record's imaging reports."""
    tests = _tests(pf, version)
    if not tests:
        return {"workbench": "radiology", "title": "Radiology", "cards": [],
                "note": "no imaging in this file"}
    cards = []
    studies = _studies(pf, version)
    for t0, t1, ch, later in pairs_of(studies)[:1]:
        moved = [r for r in ch["rows"] if r["change"].get("ld_mm")]
        total = ch["sum"]
        cards.append(card(
            "Imaging change", f"{t0.details.get('study', '')} → {t1.details.get('study', '')}: "
            + "; ".join(f"{r['lesion']} {r['change']['ld_mm'][0]:g} → "
                        f"{r['change']['ld_mm'][1]:g} mm, {r['change']['status']}"
                        + (" (alignment unreliable here)" if r["reliable"] is False else "")
                        for r in moved)
            + (f"; computed sum {total['sum_mm'][0]:g} → {total['sum_mm'][1]:g} mm, not a "
               "response call" if total.get("sum_mm") else "")
            + ("; protocol differs: " + "; ".join(ch["protocol"]) if ch["protocol"] else ""),
            INFERENCE, f"{t0.name}; {t1.name}", f"{REGISTRATION}; MedSAM contours on each date",
            "growth and shrinkage rules borrowed from RECIST 1.1 per candidate (placeholders); "
            "the unreliable-here residual is a placeholder", "weak", _opens(t1)))
        studies = [(t1, later)]  # the headline study is the later one
    for t, s in studies[:1]:
        rep = s.get("report", {})
        cards.append(card(
            "Imaging", t.result + (f"; the study's report: BI-RADS {rep['birads']}"
                                   if rep.get("birads") else ""),
            f"{OBSERVED} (the study's structured report), {INFERENCE} (contours, sizes, scores)",
            t.name, f"{pipeline_name(s['pipeline'])}: "
            + ("MedSAM contours on the seed rule's candidates" if s["modality"] == "MR" else
               "a mammography screening model and a dense-pixel rule"),
            "the seed rule's and the density rule's cutoffs are placeholders; the kinetics "
            "cutoffs are literature values used as placeholders", "weak", _opens(t)))
    reads = _reads(pf, version)
    if not cards and reads:
        table = lesion_table(reads)
        last = reads[-1]
        named = [t for t in tests if t.kind == "Imaging"]
        cards.append(card(
            "Imaging lesions", "; ".join(f"{row['site']} named new at month "
                                         f"{row['first_named']}" for row in table)
            + ("; " if table else "") + f"latest read (month {last['month']}): {last['read']}; "
            f"{NO_MEASUREMENTS}", OBSERVED, "the record's imaging reports (text, no images)",
            REPORT_METHOD, "none: the reports' own words",
            "moderate" if any(r["imported"] for r in reads) else "strong",
            _opens(named[-1]) if named else (), {"site": table[-1]["site"]} if table else None))
    return {"workbench": "radiology", "title": "Radiology", "cards": cards,
            "note": None if cards else "the imaging reports state no read"}


def queue(pf, version: int | None = None) -> list[dict]:
    """Each site a report names as new (consequence 3, trust strong: the reader's words; trust
    moderate for an imported report, whose site the import's text rule read, as its alert in
    ``workspace.add_version``), a report whose words and the record's sites field disagree,
    where two dates of a study pair exist each candidate that grew (consequence 3) or shrank (2)
    beyond the placeholder rules or whose alignment is unreliable (1), and each processed
    study's candidates to check by eye (model contours: consequence 1, trust weak)."""
    out = []
    reads = _reads(pf, version)
    for row in lesion_table(reads):
        m, imported = row["first_named"], row["imported"]
        out.append(look(
            row["site"], f"{row['site']}: named new at month {m}",
            ("the imported report's words, read by the import's text rule" if imported else
             "the imaging report names it") + f"; size and count: {NO_MEASUREMENTS}", OBSERVED,
            "moderate" if imported else "strong", 3,
            ("Tests", "Imaging", m, "Imaging report"), source=f"Imaging report, month {m}",
            key=finding_key(pf, "imaging", "report", m, row["site"]),
            focus={"site": row["site"]}, month=m,
            threshold="muffle.imports.imaging_read" if imported
            else "none: the reader's own words"))
    for r in reads:
        if not r["agrees"]:
            out.append(look(
                None, f"Imaging, month {r['month']}: the report's words and the record's sites "
                "field disagree", f"words {r['new_sites']}, field {r['recorded_sites']}",
                OBSERVED, "moderate", 2, ("Tests", "Imaging", r["month"], "Imaging report"),
                source=f"Imaging report, month {r['month']}",
                key=finding_key(pf, "imaging", "report", r["month"], "read"), month=r["month"],
                threshold=REPORT_METHOD))
    studies = _studies(pf, version)
    for t0, t1, ch, later in pairs_of(studies):
        span = f"{t0.details.get('study', '')} to {t1.details.get('study', '')}"
        for r in ch["rows"]:
            c = r["change"]
            grew, shrank = c["status"].startswith("grew"), c["status"].startswith("shrank")
            if not (grew or shrank or r["reliable"] is False and c.get("ld_mm")):
                continue
            unreliable = r["reliable"] is False
            out.append(look(
                r["later"] or r["earlier"],
                f"{r['lesion']} ({later['barcode']}, {span}): "
                + (f"{c['ld_mm'][0]:g} → {c['ld_mm'][1]:g} mm, {c['status']}" if grew or shrank
                   else "alignment unreliable here"),
                f"longest diameter {c['ld_change_mm']:+g} mm ({c['ld_change_pct']:+.0f}%) on "
                "model contours of two rigidly aligned studies"
                + (f"; {r['residual']['why']}" if unreliable else "")
                + ("; protocol differs: " + "; ".join(ch["protocol"]) if ch["protocol"] else ""),
                INFERENCE, "weak", 3 if grew else 2 if shrank else 1, _opens(t1),
                source=f"{t0.name}; {t1.name}",
                key=finding_key(pf, "imaging", later["barcode"], span, r["lesion"]),
                threshold="placeholder: RECIST 1.1's 20% and 5 mm (grew) or 30% (shrank), "
                          "borrowed per candidate"))
    for t, s in studies:
        for q in look_here(s) if s["modality"] == "MR" else []:
            out.append(look(
                q["candidate"], f"{q['candidate']} ({t.name}): {q['why']}", "a model contour "
                "from the seed rule's candidates, not a reading of the study", INFERENCE,
                "weak", 1, _opens(t), source=t.name,
                key=finding_key(pf, "imaging", s["barcode"], s["study"]["date"],
                                q["candidate"]),
                focus={"study": s["barcode"], "candidate": q["candidate"]},
                threshold="the seed rule's cutoffs (placeholders)"))
    return out

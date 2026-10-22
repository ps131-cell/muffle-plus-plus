"""Radiology workbench, offline: public TCGA-BRCA studies on TCIA -> small derived files the app
shows (docs/radiology.md). Runs locally (WSL), never in the hosted app.

    python scripts/radiology_pipeline.py fetch TCGA-EW-A1P3:10,11,14,22   # into ~/muffle-radiology
    python scripts/radiology_pipeline.py mri --barcode TCGA-EW-A1P3 --index 937 --series 10,11,14,22
    python scripts/radiology_pipeline.py mri --barcode TCGA-BH-A0H5 --index 563 --series 4
    python scripts/radiology_pipeline.py mammo --barcode TCGA-EW-A1J2 --index 926 \\
        --series 1,2,3,4 --screen --density
    python scripts/radiology_pipeline.py index

Source: the TCGA-BRCA radiology collection on The Cancer Imaging Archive (CC BY 3.0,
doi:10.7937/K9/TCIA.2016.AB2NAZRP), read through the public NBIA REST API (no login). The
pixels of this collection may be redistributed with attribution, so the app ships small 8-bit
copies: per series, slices downsampled to at most 256 px (mammograms 512 px), one JPEG strip per
phase, at most 128 slices; each case stays under 5 MB in app/workbenches/radiology_results/.

MRI: the phases (one multiphase series split by TriggerTime, or one series per phase), turned to
the display orientation (anterior up, the patient's right on the image's left), the subtraction
(first post-contrast minus pre-contrast), the seed rule of ``muffle.workbench.radiology.
candidates`` inside ``breast_region``, MedSAM (ViT-B, wanglab/medsam-vit-base at a pinned
revision, the authors' preprocessing: per-slice 0.5-99.5 percentile window, 1024² cubic resize,
[0, 1] scaling, box prompt, sigmoid > 0.5) on every slice of the top three candidates, then
longest diameter, volume and kinetics from the contours. Mammography: the four views and a
dense-pixel share (placeholder rule). Data in ~/muffle-radiology (never in the repo).
"""

from __future__ import annotations

import argparse
import io
import json
import math
import os
import re
import subprocess
import time
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app" / "workbenches" / "radiology_results"
EXAMPLE = ROOT / "app" / "workbenches" / "radiology_example"  # the public study pair
API = "https://services.cancerimagingarchive.net/nbia-api/services/v1"
MEDSAM_ID, MEDSAM_REV = "wanglab/medsam-vit-base", "de8488bca37bb1d4fb190f612c516126d739ce3b"
DISPLAY_PX, MAMMO_PX, MAX_SLICES, JPEG_Q = 256, 512, 128, 80
BEHIND_MM = 30  # shipped MR slices end this far behind the search region's posterior limit
SOURCE = {"collection": "TCGA-BRCA radiology (The Cancer Imaging Archive)",
          "doi": "10.7937/K9/TCIA.2016.AB2NAZRP", "license": "CC BY 3.0",
          "attribution": "Lingle W, Erickson BJ, Zuley ML, et al. The Cancer Genome Atlas Breast "
                         "Invasive Carcinoma Collection (TCGA-BRCA), version 3. The Cancer "
                         "Imaging Archive, 2016. doi:10.7937/K9/TCIA.2016.AB2NAZRP. "
                         "Downsampled to 8-bit copies here; not the diagnostic originals."}
EXAMPLE_NOTE = ("A public example study pair: a TCGA-BRCA patient on TCIA with breast MRI on two "
                "dates, not a patient file in this app. Shown so that change over time on real "
                "images can be seen; nothing in it is any patient file's data.")
SR_KEEP = {"Procedure reported": "procedure", "Laterality": "laterality",
           "Assessment Category": "birads", "Pathology": "pathology",
           "Estrogen receptor": "er", "Progesterone receptor": "pr", "HER2": "her2"}


# --- fetch -------------------------------------------------------------------------------------
def get_json(url: str):
    return json.loads(urllib.request.urlopen(url, timeout=120).read())


def fetch(out: Path, specs: list[str]) -> None:
    """BARCODE:NUM,NUM -> out/BARCODE/NUM/*.dcm (plus the study's structured report in sr/).
    BARCODE@YYYY-MM-DD:NUM,NUM takes that date's study only (a patient with two studies reuses
    series numbers) -> out/BARCODE_YYYY-MM-DD/NUM/."""
    for spec in specs:
        who, nums = spec.split(":")
        barcode, _, date = who.partition("@")
        series = get_json(f"{API}/getSeries?Collection=TCGA-BRCA&PatientID={barcode}")
        if date:
            uids = {s["StudyInstanceUID"] for s in get_json(
                f"{API}/getPatientStudy?Collection=TCGA-BRCA&PatientID={barcode}")
                if s.get("StudyDate", "").startswith(date)}
            series = [s for s in series if s["StudyInstanceUID"] in uids]
        want = [*nums.split(","), "sr"]
        for s in series:
            num = "sr" if s["Modality"] == "SR" else str(s.get("SeriesNumber"))
            dest = out / (f"{barcode}_{date}" if date else barcode) / num
            if num not in want or (dest.exists() and any(dest.glob("**/*.dcm"))):
                continue
            t = time.time()
            data = urllib.request.urlopen(f"{API}/getImage?SeriesInstanceUID="
                                          f"{s['SeriesInstanceUID']}", timeout=600).read()
            dest.mkdir(parents=True, exist_ok=True)
            zipfile.ZipFile(io.BytesIO(data)).extractall(dest)
            (dest / "series.json").write_text(json.dumps(s))
            print(barcode, num, s.get("SeriesDescription"), f"{len(data) / 1e6:.0f} MB",
                  f"{time.time() - t:.0f} s", flush=True)


# --- shared helpers -------------------------------------------------------------------------
def dicoms(folder: Path) -> list:
    import pydicom

    return [pydicom.dcmread(p) for p in sorted(folder.rglob("*.dcm"))]


def report_facts(folder: Path) -> dict:
    """The structured report's assessment, pathology and receptors (observed); nothing else
    (the report also states race and health status, which the page does not need)."""
    if not folder.exists():
        return {}
    facts = {}

    def walk(items):
        for it in items:
            name = it.ConceptNameCodeSequence[0].CodeMeaning if "ConceptNameCodeSequence" in it \
                else ""
            key = SR_KEEP.get(name.strip())
            if key and key not in facts:
                if "ConceptCodeSequence" in it:
                    facts[key] = str(it.ConceptCodeSequence[0].CodeMeaning).strip()
                elif "TextValue" in it:
                    facts[key] = str(it.TextValue).strip()
            if "ContentSequence" in it:
                walk(it.ContentSequence)

    for ds in dicoms(folder):
        walk(ds.ContentSequence)
    return facts


def scanner(d) -> str:
    return f"{d.Manufacturer} {getattr(d, 'ManufacturerModelName', '')}".strip()


def uptime() -> str:
    try:
        return subprocess.run(["uptime"], capture_output=True, text=True).stdout.strip()
    except OSError:
        return "unknown"


def to8(a: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return (np.clip((a - lo) / max(hi - lo, 1e-6), 0, 1) * 255 + 0.5).astype(np.uint8)


def strip_jpeg(slices: np.ndarray, path: Path) -> None:
    """One JPEG with every slice stacked top to bottom (the page cuts it back into slices)."""
    from PIL import Image

    Image.fromarray(np.concatenate(list(slices), axis=0)).save(path, quality=JPEG_Q,
                                                                optimize=True)


def resize2d(a: np.ndarray, shape: tuple[int, int], order: int = 1) -> np.ndarray:
    from skimage.transform import resize

    return resize(a.astype(np.float32), shape, order=order, preserve_range=True,
                  anti_aliasing=order > 0 and (shape[0] < a.shape[0]))


# --- MRI -------------------------------------------------------------------------------------
def seconds(hhmmss: str) -> float:
    s = str(hhmmss)
    return int(s[:2]) * 3600 + int(s[2:4]) * 60 + float(s[4:] or 0)


def load_phases(base: Path, series: list[str], times: list[float] | None):
    """[phase, Z, Y, X] float32 in the display frame (``orient``), the per-phase info, the
    display frame's spacing (Z, Y, X) in mm, the pre-contrast phase's headers sorted along the
    slice normal, and how the acquisition maps to the display frame."""
    phases, info = [], []
    if len(series) == 1:  # one multiphase series: split it by TriggerTime, else by acquisition
        ds = dicoms(base / series[0])
        desc = str(ds[0].SeriesDescription)
        trig = sorted({int(float(d.get("TriggerTime", 0) or 0)) for d in ds})
        if len(trig) > 1:
            starts = [t / 1000 for t in trig]
            phases = [[d for d in ds if int(float(d.TriggerTime)) == t] for t in trig]
            source = "TriggerTime from the first phase's start; the injection time is not in " \
                     "the headers"
        else:  # the same positions acquired again and again, numbered in order (GE VIBRANT)
            n = len({round(float(np.dot(d.ImagePositionPatient, normal(d))), 1) for d in ds})
            ds = sorted(ds, key=lambda d: int(d.InstanceNumber))
            phases = [ds[i:i + n] for i in range(0, len(ds), n)]
            assert all(len(p) == n for p in phases), "phases of unequal size"
            t0 = min(seconds(d.AcquisitionTime) for d in phases[0])
            starts = [min(seconds(d.AcquisitionTime) for d in p) - t0 for p in phases]
            source = (f"AcquisitionTime, each phase's start from the pre-contrast phase's start "
                      f"(a phase takes about {starts[1]:.0f} s to acquire); the injection time is "
                      "not in the headers")
        for k, t in enumerate(starts):
            info.append({"series": int(series[0]), "description": desc, "time_s": round(t, 1),
                         "time_source": source,
                         "label": "pre-contrast" if k == 0 else f"post {k} ({t:.0f} s)"})
    else:
        for k, num in enumerate(series):
            ds = dicoms(base / num)
            phases.append(ds)
            desc = str(ds[0].SeriesDescription)
            m = re.search(r"(\d+)\s*_?min", desc)
            t = times[k] if times else (0.0 if k == 0 else (60.0 * int(m.group(1)) if m else None))
            info.append({"series": int(num), "description": desc, "time_s": t,
                         "time_source": "given on the command line" if times else
                                        "the series descriptions, nominal minutes after contrast",
                         "series_time": str(ds[0].SeriesTime),
                         "label": "pre-contrast" if k == 0 else
                                  (f"post {k} ({t / 60:g} min)" if t is not None else f"post {k}")})
    vols, first = [], None
    for ds in phases:
        ds = sorted(ds, key=lambda d: float(np.dot(d.ImagePositionPatient, normal(d))))
        vol = np.stack([d.pixel_array.astype(np.float32) * float(getattr(d, "RescaleSlope", 1))
                        + float(getattr(d, "RescaleIntercept", 0)) for d in ds])
        vols.append(vol)
        first = first or ds  # the pre-contrast phase's headers and positions
    pos = np.array([float(np.dot(d.ImagePositionPatient, normal(d))) for d in first])
    gap = float(np.median(np.diff(pos))) if len(pos) > 1 else float(first[0].SliceThickness)
    row_mm, col_mm = (float(v) for v in first[0].PixelSpacing)
    frame = Frame(first, (abs(gap), row_mm, col_mm), vols[0].shape)
    return (np.stack([frame.to_display(v) for v in vols]), info, frame.spacing, first, frame)


def axes(d) -> tuple[np.ndarray, np.ndarray]:
    iop = np.array(d.ImageOrientationPatient, float)
    return iop[:3], iop[3:]


def normal(d) -> np.ndarray:
    return np.cross(*axes(d))


class Frame:
    """The display frame [Z, Y, X] for any acquisition plane: axial slices from the feet to the
    head, anterior at the top (rows run to +Y, posterior, in DICOM's LPS frame) and the
    patient's right on the image's left (columns run to +X, the patient's left). An axial
    acquisition only flips; a sagittal or coronal one is turned, and its in-plane resolution
    becomes two of the display axes (the anisotropy is in ``spacing``)."""

    PLANES = {0: "sagittal", 1: "coronal", 2: "axial"}  # the LPS axis the slice normal runs along

    def __init__(self, ds: list, acq_spacing: tuple, shape: tuple):
        r, c = axes(ds[0])
        n = normal(ds[0])
        dirs = [n, c, r]  # acquisition axes (slice, row, col) in LPS
        lps = [int(np.argmax(np.abs(v))) for v in dirs]
        self.perm = [lps.index(k) for k in (2, 1, 0)]  # display Z, Y, X <- acquisition axis
        self.flips = [bool(dirs[p][k] < 0) for p, k in zip(self.perm, (2, 1, 0), strict=True)]
        self.plane = self.PLANES[lps[0]]
        self.acq_spacing = tuple(float(v) for v in acq_spacing)
        self.spacing = tuple(self.acq_spacing[p] for p in self.perm)
        # LPS z of every display slice (a corner of the volume is enough to find the lowest)
        ipp0, ipp1 = (np.array(d.ImagePositionPatient, float) for d in (ds[0], ds[-1]))
        corners = [p + i * c * acq_spacing[1] + j * r * acq_spacing[2] for p in (ipp0, ipp1)
                   for i in (0, shape[1] - 1) for j in (0, shape[2] - 1)]
        z0 = min(float(p[2]) for p in corners)
        self.z_mm = [round(z0 + k * self.spacing[0], 1) for k in range(shape[self.perm[0]])]

    def to_display(self, vol: np.ndarray) -> np.ndarray:
        out = np.transpose(vol, self.perm)
        for ax, f in enumerate(self.flips):
            if f:
                out = np.flip(out, ax)
        return np.ascontiguousarray(out)

    def to_plane(self, vol: np.ndarray) -> np.ndarray:
        """A display-frame volume as acquisition-plane slices [slice, row, col], kept in the
        display's directions (an axial acquisition: the display frame itself)."""
        return np.ascontiguousarray(np.transpose(vol, np.argsort(self.perm)))

    def from_plane(self, vol: np.ndarray) -> np.ndarray:
        return np.ascontiguousarray(np.transpose(vol, self.perm))


class MedSAM:
    """MedSAM ViT-B with the authors' inference recipe (MedSAM_Inference.py), on the CPU."""

    def __init__(self):
        import torch
        from transformers import SamModel

        self.torch = torch
        self.model = SamModel.from_pretrained(MEDSAM_ID, revision=MEDSAM_REV).eval()
        self.seconds = []

    def embed(self, img: np.ndarray):
        from skimage.transform import resize

        lo, hi = np.percentile(img, [0.5, 99.5])
        x = np.clip((img - lo) / max(hi - lo, 1e-6), 0, 1)
        x = resize(x, (1024, 1024), order=3, preserve_range=True, anti_aliasing=True)
        x = (x - x.min()) / max(x.max() - x.min(), 1e-8)
        t = self.torch.tensor(np.repeat(x[None], 3, 0)[None], dtype=self.torch.float32)
        start = time.time()
        with self.torch.inference_mode():
            emb = self.model.get_image_embeddings(t)
        self.seconds.append(time.time() - start)
        return emb

    def segment(self, emb, box: list[int], shape: tuple[int, int]) -> np.ndarray:
        h, w = shape
        b = self.torch.tensor([[[box[0] / w * 1024, box[1] / h * 1024, box[2] / w * 1024,
                                 box[3] / h * 1024]]], dtype=self.torch.float32)
        with self.torch.inference_mode():
            out = self.model(image_embeddings=emb, input_boxes=b, multimask_output=False)
            prob = self.torch.sigmoid(out.pred_masks[0, 0])[None]  # (1, 1, 256, 256)
            prob = self.torch.nn.functional.interpolate(prob, size=(h, w), mode="bilinear",
                                                        align_corners=False)
        return prob[0, 0].numpy() > 0.5


def keep_overlapping(mask: np.ndarray, seed: np.ndarray) -> np.ndarray:
    """MedSAM's mask on one slice, only the pieces that touch the seed."""
    from scipy import ndimage

    lab, n = ndimage.label(mask)
    keep = np.unique(lab[seed & mask])
    return np.isin(lab, keep[keep > 0]) if n else mask


def contours(mask2d: np.ndarray, scale: tuple[float, float]) -> list:
    from skimage.measure import approximate_polygon, find_contours

    out = []
    for c in find_contours(mask2d.astype(float), 0.5):
        c = approximate_polygon(c, 0.5)
        out.append([[round(float(x) / scale[1], 1), round(float(y) / scale[0], 1)] for y, x in c])
    return out


def mri(args) -> None:
    from scipy import ndimage

    from muffle.workbench import radiology as rad

    folder = f"{args.barcode}_{args.date}" if args.date else args.barcode
    base = Path(args.dicom).expanduser() / folder
    series = args.series.split(",")
    times = [float(t) for t in args.times.split(",")] if args.times else None
    vols, info, spacing, first, frame = load_phases(base, series, times)
    n_ph, nz, h, w = vols.shape
    pre, post = vols[0], vols[1]
    sub = post - pre
    region, region_info = rad.breast_region(pre, spacing)
    found, seed = rad.candidates(sub, region, spacing, limit_row=region_info["limit_row"])
    labels = seed.pop("labels")
    print(f"{folder}: {frame.plane} acquisition, display frame {nz}x{h}x{w}, {n_ph} phases, "
          f"spacing {spacing}, cleft row {region_info['cleft_row']}, {seed['groups']} seed "
          f"groups, {len(found)} proposed", flush=True)

    # MedSAM on the acquisition plane (the sharpest one), in display directions; the masks go
    # back to the display frame for the shipped slices
    medsam = MedSAM()
    feed = frame.to_plane({"sub": np.clip(sub, 0, None), "early": post}[args.medsam_input])
    plane_labels = frame.to_plane(labels)
    n_acq, ah, aw = feed.shape
    flipped = frame.flips[frame.perm.index(0)]  # plane slices run against the acquisition order

    def acq(k: int) -> int:  # a plane slice's number in the acquisition's own order
        return int(n_acq - 1 - k if flipped else k)

    embeddings, masks = {}, {}
    for c in found:
        m3 = np.zeros(feed.shape, bool)
        unsure_where = np.zeros(feed.shape, bool)
        boxes, unsure = {}, []
        for z in map(int, np.where((plane_labels == c["label"]).any((1, 2)))[0]):
            comp = plane_labels[z] == c["label"]
            box = rad.slice_box(comp)
            if z not in embeddings:
                embeddings[z] = medsam.embed(feed[z])
            m = keep_overlapping(medsam.segment(embeddings[z], box, (ah, aw)), comp)
            box_area = (box[2] - box[0] + 1) * (box[3] - box[1] + 1)
            if not m.any() or m.sum() > 1.5 * box_area:
                unsure.append(z)
                unsure_where[z, box[1]:box[3] + 1, box[0]:box[2] + 1] = True
            m3[z], boxes[z] = m, box
        masks[c["id"]] = (m3, frame.from_plane(m3), frame.from_plane(unsure_where))
        c["boxes"], c["unsure_slices"] = boxes, unsure
        print(f"  {c['id']}: {frame.plane} slices {acq(min(boxes))}-{acq(max(boxes))}, seed "
              f"{c['seed_mm3']} mm³, MedSAM on {len(boxes)} slices, unsure "
              f"{sorted(acq(z) for z in unsure)}", flush=True)

    # --- shipped display volume -------------------------------------------------------------
    sz, sy, sx = spacing
    step = max(1, math.ceil(nz / MAX_SLICES))
    shown = list(range(0, nz, step))
    rows = min(h, region_info["limit_row"] + int(round(BEHIND_MM / sy)))  # the crop
    pixel_mm = max(rows * sy, w * sx) / DISPLAY_PX  # square shown pixels
    dh, dw = int(round(rows * sy / pixel_mm)), int(round(w * sx / pixel_mm))
    scale = (pixel_mm / sy, pixel_mm / sx)  # display-frame pixels per shown pixel
    lo = float(np.percentile(pre[region], 0.5)) if region.any() else float(pre.min())
    hi = float(np.percentile(post[region], 99.8)) if region.any() else float(post.max())
    out = Path(args.out) / folder
    out.mkdir(parents=True, exist_ok=True)
    sub_hi = float(np.percentile(np.clip(sub, 0, None)[region], 99.9)) if region.any() else 1.0
    middle = {f"phase{k}": k for k in range(2, n_ph - 1)}  # the cine's phases in between
    for key, vol, (a, b) in (("pre", pre, (lo, hi)), ("early", post, (lo, hi)),
                             ("late", vols[-1], (lo, hi)),
                             *((k, vols[i], (lo, hi)) for k, i in middle.items()),
                             ("sub", np.clip(sub, 0, None), (0, sub_hi))):
        strip_jpeg(np.stack([to8(resize2d(vol[z, :rows], (dh, dw)), a, b) for z in shown]),
                   out / f"{key}.jpg")

    # --- measurements per candidate ----------------------------------------------------------
    acq_px = frame.acq_spacing[1:]  # the acquisition plane's pixel spacing (rows, cols)
    cands, keep = [], {}
    for c in found:
        m3, md, unsure_d = masks[c["id"]]
        keep[f"mask_{c['id']}"] = md
        lds = {z: rad.longest_diameter_mm(m3[z], acq_px) for z in c["boxes"]}
        sure_only = [z for z in lds if z not in c["unsure_slices"]]
        sure = sure_only or list(lds)
        z_ld = max(sure, key=lambda z: lds[z][0]) if sure else None
        m_sure = m3.copy()
        m_sure[c["unsure_slices"]] = False
        signal = [float(vols[k][md].mean()) if md.any() else float("nan") for k in range(n_ph)]
        kin = rad.kinetics(signal, [p["time_s"] for p in info], [p["label"] for p in info])
        per_slice = {}
        for i, z in enumerate(shown):
            seed_z = labels[z] == c["label"]
            if not (seed_z.any() or md[z].any()):
                continue
            ld, ends = rad.longest_diameter_mm(md[z], (sy, sx))
            x0, y0, x1, y1 = rad.slice_box(seed_z if seed_z.any() else md[z])
            per_slice[i] = {
                "z": z, "box": [round(x0 / scale[1], 1), round(y0 / scale[0], 1),
                                round(x1 / scale[1], 1), round(y1 / scale[0], 1)],
                "contours": contours(md[z], scale), "ld_mm": round(ld, 1),
                "ld_line": [[round(p[1] / scale[1], 1), round(p[0] / scale[0], 1)]
                            for p in ends],
                "area_mm2": round(float(md[z].sum()) * sy * sx, 1),
                "unsure": bool(unsure_d[z].any())}
        lo_ml, hi_ml = rad.volume_range_ml(m3, frame.acq_spacing)
        zs = sorted(c["boxes"])
        cands.append({
            "id": c["id"], "rank": c["rank"], "evidence": "model inference",
            "seed": {k: c[k] for k in ("seed_mm3", "mean_sub", "peak_sub", "elongation", "score",
                                       "bbox")},
            "slices": sorted([acq(zs[0]), acq(zs[-1])]), "medsam_slices": len(zs),
            "unsure_slices": sorted(acq(z) for z in c["unsure_slices"]),
            "longest_diameter_mm": round(lds[z_ld][0], 1) if z_ld is not None else 0.0,
            "ld_slice": acq(z_ld) if z_ld is not None else None,
            "ld_plane": frame.plane,
            "ld_uncertainty_mm": round(max(acq_px), 2),
            "cc_extent_mm": round(int(md.any((1, 2)).sum()) * sz, 1),
            "volume_ml": round(rad.volume_ml(m3, frame.acq_spacing), 2),
            "volume_range_ml": [round(lo_ml, 2), round(hi_ml, 2)],
            "volume_sure_ml": round(rad.volume_ml(m_sure, frame.acq_spacing), 2),
            "ld_from": f"{len(sure_only)} of {len(lds)} slices where the contour stayed inside "
                       "its box" if sure_only else "every slice (all were flagged unsure)",
            "centroid_mm": [round(float(v), 1) for v in
                            np.array(ndimage.center_of_mass(md)) * np.array(spacing)]
            if md.any() else None,
            "side": ("patient's right" if (np.argwhere(md)[:, 2].mean() < w / 2) else
                     "patient's left") if md.any() else None,
            "signal": [round(v, 1) for v in signal], "kinetics": kin, "per_slice": per_slice})

    sr = report_facts(base / "sr")
    d0 = first[0]
    plane_note = "" if frame.plane == "axial" else \
        f" (reconstructed from the {frame.plane} acquisition)"
    study = {
        "barcode": args.barcode, "cohort_index": args.index, "modality": "MR",
        "kind": "Breast MRI (dynamic contrast-enhanced)",
        "study": {"date": f"{d0.StudyDate[:4]}-{d0.StudyDate[4:6]}-{d0.StudyDate[6:]}",
                  "uid_suffix": str(d0.StudyInstanceUID)[-12:],
                  "description": str(getattr(d0, "StudyDescription", "")),
                  "scanner": scanner(d0),
                  "field_t": float(getattr(d0, "MagneticFieldStrength", 0) or 0),
                  "contrast": str(getattr(d0, "ContrastBolusAgent", "") or "").strip(),
                  "sequence": {"tr_ms": float(getattr(d0, "RepetitionTime", 0) or 0),
                               "te_ms": float(getattr(d0, "EchoTime", 0) or 0),
                               "flip_deg": float(getattr(d0, "FlipAngle", 0) or 0)}},
        "source": SOURCE, "report": sr,
        "display": {"rows": dh, "cols": dw, "pixel_mm": round(pixel_mm, 3),
                    "native": [int(h), int(w)], "native_pixel_mm": [round(sy, 4), round(sx, 4)],
                    "crop": f"rows 1-{rows} of {h}: up to {BEHIND_MM} mm behind the search "
                            "region's posterior limit (the heart and lungs are cut off)",
                    "slices": len(shown), "native_slices": int(nz), "slice_step": step,
                    "slice_mm": round(sz, 2),
                    "slice_thickness_mm": float(getattr(d0, "SliceThickness", 0) or 0),
                    "z_mm": [frame.z_mm[z] for z in shown],
                    "acquisition": {"plane": frame.plane, "slices": int(n_acq),
                                    "slice_mm": round(frame.acq_spacing[0], 2),
                                    "pixel_mm": [round(v, 4) for v in acq_px]},
                    "orientation": f"axial{plane_note}; anterior at the top, the patient's "
                                   "right on the image's left",
                    "window": "pre, early and late share one window (0.5th percentile of the "
                              "pre-contrast to the 99.8th of the early phase inside the breast "
                              "region); the subtraction has its own",
                    "jpeg_quality": JPEG_Q},
        "phases": info,
        "shipped": {"pre": 0, "early": 1, "late": n_ph - 1, "sub": "early minus pre",
                    "between": middle},
        "region": {**region_info, "margin_mm": rad.CUTOFFS["chest_margin_mm"][0],
                   "limit_row_display": round(region_info["limit_row"] / scale[0], 1)},
        "seed": {**seed, "rule": "subtraction above the breast region's 99.5th percentile, "
                                 "opened with a 1.5 mm ellipsoid and grouped in 3D; small, "
                                 "vessel-like, plate-like and chest-wall-line groups left out; "
                                 "ranked by summed enhancement"},
        "candidates": cands,
        "medsam": {"model": MEDSAM_ID, "revision": MEDSAM_REV, "input": args.medsam_input,
                   "plane": frame.plane, "slices": len(medsam.seconds),
                   "seconds_per_slice": round(float(np.median(medsam.seconds)), 1)
                   if medsam.seconds else None,
                   "seconds_total": round(float(np.sum(medsam.seconds)), 0),
                   "threads": int(medsam.torch.get_num_threads()), "uptime": uptime()},
        "pipeline": {"script": "scripts/radiology_pipeline.py mri", "version": "2",
                     "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")},
    }
    if args.example:
        study["example"] = EXAMPLE_NOTE
    (out / "study.json").write_text(json.dumps(study, indent=1, default=float), encoding="utf-8")
    if args.keep:  # full-resolution volumes for `pair`, outside the repository
        Path(args.keep).expanduser().mkdir(parents=True, exist_ok=True)
        np.savez_compressed(Path(args.keep).expanduser() / f"{folder}.npz", pre=pre, early=post,
                            spacing=np.array(spacing), limit_row=region_info["limit_row"],
                            crop_rows=rows, **keep)
    size = sum(p.stat().st_size for p in out.iterdir())
    print(f"-> {out} ({size / 1e6:.2f} MB)", flush=True)


def pair(args) -> None:
    """Two dates of one patient (processed with ``mri --keep``): the earlier study's
    pre-contrast volume aligned rigidly onto the later one's (``muffle.workbench.radiology.
    register``), the local residual at every later candidate and on a block grid over the breast
    region, and the candidates paired across dates; pair.json next to the two studies."""
    from muffle.workbench import radiology as rad

    work, out = Path(args.keep).expanduser(), Path(args.out)
    a, b = (np.load(work / f"{name}.npz") for name in (args.earlier, args.later))
    sa, sb = tuple(float(v) for v in a["spacing"]), tuple(float(v) for v in b["spacing"])
    fixed, moving = b["pre"].astype(np.float32), a["pre"].astype(np.float32)
    mask = np.zeros(fixed.shape, bool)
    mask[:, :int(b["crop_rows"])] = True  # the shipped crop: the breasts and the air before them
    print(f"registering {args.earlier} onto {args.later}", flush=True)
    reg = rad.register(fixed, moving, sb, sa, mask)
    print(json.dumps({k: v for k, v in reg.items() if k != "method"}), flush=True)
    earlier, later = rad.load_study(out / args.earlier), rad.load_study(out / args.later)
    t = time.time()
    residuals = {c["id"]: rad.local_residual(fixed, moving, sb, sa, reg, c["centroid_mm"])
                 for c in later["candidates"] if c.get("centroid_mm")}
    print("residuals", json.dumps(residuals), f"{time.time() - t:.0f} s", flush=True)
    # a block grid over the breasts (tissue in front of the search region's posterior limit)
    tissue = fixed > 0.2 * np.percentile(fixed, 99)
    tissue[:, int(b["limit_row"]):] = False
    step = 30.0
    extent = (np.array(fixed.shape) - 1) * np.array(sb)
    centres = np.stack(np.meshgrid(*[np.arange(step / 2, e, step) for e in extent],
                                   indexing="ij"), -1).reshape(-1, 3)
    blocks = []
    for at in centres:
        lo = np.maximum(((at - step / 2) / sb).astype(int), 0)
        hi = ((at + step / 2) / sb).astype(int) + 1
        if tissue[lo[0]:hi[0], lo[1]:hi[1], lo[2]:hi[2]].mean() < 0.3:
            continue
        r = rad.local_residual(fixed, moving, sb, sa, reg, at, half_mm=step / 2)
        blocks.append({**r, "half_mm": step / 2})
    print(f"{len(blocks)} blocks, {sum(not x['reliable'] for x in blocks)} unreliable, "
          f"{time.time() - t:.0f} s", flush=True)
    matches = rad.match_candidates(earlier["candidates"], later["candidates"], reg, residuals)
    result = {"earlier": args.earlier, "later": args.later, "registration": reg,
              "residuals": residuals, "blocks": blocks, "matches": matches,
              "frame": "the later study's frame: (Z, Y, X) mm from its first shown slice, row "
                       "and column", "example": EXAMPLE_NOTE, "source": SOURCE,
              "pipeline": {"script": "scripts/radiology_pipeline.py pair", "version": "1",
                           "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
                           "seconds": round(time.time() - t + reg["seconds"], 0),
                           "uptime": uptime()}}
    (out / "pair.json").write_text(json.dumps(result, indent=1, default=float), encoding="utf-8")
    print(json.dumps(matches), flush=True)


# --- mammography --------------------------------------------------------------------------------
MAMMO_ID, MAMMO_REV = "ianpan/mammoscreen", "b619a889a8214f3b3f9e7427c2603608a44e6d0a"
MAMMO_SIZES, MAMMO_PAD = [(2048, 1024), (1920, 1280), (1536, 1536)], [True, True, False]


def screen(images: dict[tuple[str, str], np.ndarray]) -> dict:
    """mammoscreen (Apache-2.0) per breast from its CC and MLO views. The three nets are
    re-built from the model's published code (timm tf_efficientnetv2_s, one channel, average
    pooling, a 5-way linear head: cancer, then density A-D) and the pinned weights loaded strictly,
    so no remote code runs. Images: uint8 after the VOI LUT, cropped to the breast's bounding box
    (the authors use a separate crop model). Padding is constant zero."""
    import torch
    import torch.nn.functional as F
    from huggingface_hub import hf_hub_download
    from safetensors.torch import load_file
    from timm import create_model

    class Net(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.backbone = create_model("tf_efficientnetv2_s", pretrained=False, num_classes=0,
                                         global_pool="", in_chans=1)
            self.pooling = torch.nn.AdaptiveAvgPool2d(1)
            self.dropout = torch.nn.Dropout(0.1)
            self.linear = torch.nn.Linear(1280, 5)

    def prep(img: np.ndarray, size: tuple[int, int], pad: bool):
        h, w = img.shape
        if pad and h / w > size[0] / size[1]:
            nw = round(h * size[1] / size[0])
            img = np.pad(img, ((0, 0), ((nw - w) // 2, nw - w - (nw - w) // 2)))
        t = torch.from_numpy(np.ascontiguousarray(img)).float()[None, None]
        if pad:
            t = F.interpolate(t, size=size, mode="bilinear", align_corners=False)
        else:
            s = size[0] / max(h, w)
            t = F.interpolate(t, size=(round(h * s), round(w * s)), mode="bilinear",
                              align_corners=False)
            ph, pw = size[0] - t.shape[2], size[1] - t.shape[3]
            t = F.pad(t, (pw // 2, pw - pw // 2, ph // 2, ph - ph // 2))
        return (t / 255.0 - 0.5) * 2.0

    start = time.time()
    sd = load_file(hf_hub_download(MAMMO_ID, "model.safetensors", revision=MAMMO_REV))
    nets = []
    for i in range(len(MAMMO_SIZES)):
        net = Net().eval()
        net.load_state_dict({k[len(f"net{i}."):]: v for k, v in sd.items()
                             if k.startswith(f"net{i}.")}, strict=True)
        nets.append(net)
    loaded, out = time.time() - start, {}
    with torch.inference_mode():
        for side in sorted({s for s, _ in images}):
            views = [v for v in ("CC", "MLO") if (side, v) in images]
            cancer, density = [], []
            for net, size, pad in zip(nets, MAMMO_SIZES, MAMMO_PAD, strict=True):
                x = torch.cat([prep(images[(side, v)], size, pad) for v in views])
                logits = net.linear(net.pooling(net.backbone(x)).flatten(1))
                cancer.append(float(logits[:, 0].sigmoid().mean()))
                density.append(logits[:, 1:].softmax(1).mean(0).numpy())
            dens = np.mean(density, 0)
            out[side] = {"views": views, "cancer": round(float(np.mean(cancer)), 4),
                         "cancer_per_net": [round(c, 4) for c in cancer],
                         "density": {k: round(float(p), 3) for k, p in zip("ABCD", dens,
                                                                            strict=True)},
                         "density_class": "ABCD"[int(np.argmax(dens))]}
    return {"status": "implemented", "model": MAMMO_ID, "revision": MAMMO_REV,
            "license": "Apache-2.0", "breasts": out,
            "card": {"auroc": "0.945 (mean of 3 splits, sd 0.002) on 10% held-out splits of the "
                              "RSNA 2023 screening challenge data, the model card's numbers",
                     "thresholds": {"98.1% sensitivity": 0.0072, "94.3% sensitivity": 0.0127,
                                    "90.5% sensitivity": 0.0184},
                     "training": "CBIS-DDSM, then RSNA 2023 (the RSNA data terms not retrieved)"},
            "how": "the published architecture re-built with timm and the pinned weights, no "
                   "remote code; crops from the breast mask instead of the authors' crop model; "
                   "constant-zero padding",
            "seconds_load": round(loaded, 0), "seconds_inference": round(time.time() - start
                                                                        - loaded, 0),
            "threads": int(torch.get_num_threads()), "uptime": uptime()}


MONAI_ID = "MONAI/breast_density_classification"
MONAI_REV = "eb746b7590d830bef92137ac632a4abe34a64f3d"


def monai_density(views: dict[tuple[str, str], np.ndarray]) -> dict:
    """MONAI's breast density bundle (Apache-2.0, Mayo Clinic) per view: BI-RADS density A-D.
    The network is re-built the way the bundle's TorchVisionFCModel builds it (torchvision
    InceptionV3 as constructed with pretrained weights: aux logits and the ImageNet input
    transform on; its fc replaced by identity, then a new 4-way linear layer) and the pinned
    weights loaded strictly, so MONAI itself is not needed. The bundle's preprocessing: the whole
    view scaled to [0, 1], resized to 299x299 (area), the grey channel repeated three times; a
    sigmoid per class."""
    import torch
    import torch.nn.functional as F
    from huggingface_hub import hf_hub_download
    from torchvision.models import inception_v3

    class Net(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.features = inception_v3(weights=None, aux_logits=True, transform_input=True,
                                         init_weights=False)
            self.features.fc = torch.nn.Identity()
            self.fc = torch.nn.Linear(2048, 4)

        def forward(self, x):
            return self.fc(torch.flatten(self.features(x), 1))

    start = time.time()
    ckpt = torch.load(hf_hub_download(MONAI_ID, "models/model.pt", revision=MONAI_REV),
                      map_location="cpu", weights_only=True)
    net = Net().eval()
    net.load_state_dict(ckpt.get("model", ckpt), strict=True)
    out = {}
    with torch.inference_mode():
        for (side, view), img in sorted(views.items()):
            x = torch.from_numpy(img.astype(np.float32))
            x = (x - x.min()) / max(float(x.max() - x.min()), 1e-6)
            x = F.interpolate(x[None, None], size=(299, 299), mode="area").expand(1, 3, 299, 299)
            p = torch.sigmoid(net(x))[0].numpy()
            out[f"{side}-{view}"] = {"density": {k: round(float(v), 3)
                                                 for k, v in zip("ABCD", p, strict=True)},
                                     "density_class": "ABCD"[int(np.argmax(p))]}
    return {"status": "implemented", "model": MONAI_ID, "revision": MONAI_REV,
            "license": "Apache-2.0", "views": out,
            "card": {"accuracy": "0.96 (the bundle's metadata; its test set is not described)",
                     "training": "InceptionV3 fine-tuned on Mayo Clinic mammograms (Gupta et "
                                 "al., arXiv:2202.08238, preprint)",
                     "intended_use": "an example, not to be used for diagnostic purposes (the "
                                     "bundle's metadata)"},
            "how": "the bundle's network re-built from torchvision with the pinned weights, "
                   "without MONAI; the whole view, as the bundle's preprocessing takes it; a "
                   "sigmoid per class, so the four values need not sum to 1",
            "seconds": round(time.time() - start, 0), "uptime": uptime()}


def mammo(args) -> None:
    from scipy import ndimage

    from muffle.workbench import radiology as rad

    base = Path(args.dicom).expanduser() / args.barcode
    out = OUT / args.barcode
    out.mkdir(parents=True, exist_ok=True)
    views, crops, whole = [], {}, {}
    for num in args.series.split(","):
        d = dicoms(base / num)[0]
        try:
            from pydicom.pixels import apply_voi_lut
            img = apply_voi_lut(d.pixel_array, d).astype(np.float32)
        except Exception:  # no VOI LUT: the stored values
            img = d.pixel_array.astype(np.float32)
        if str(d.PhotometricInterpretation) == "MONOCHROME1":
            img = img.max() - img
        sm = ndimage.uniform_filter(img, 9)
        lab, n = ndimage.label(sm > 0.05 * float(np.percentile(img, 99.5)))
        sizes = ndimage.sum(np.ones_like(lab), lab, range(1, n + 1)) if n else []
        breast = lab == (int(np.argmax(sizes)) + 1) if n else np.ones_like(img, bool)
        dense = rad.dense_fraction(np.where(breast, img, 0), background=0.5)
        rows, cols = np.where(breast.any(1))[0], np.where(breast.any(0))[0]
        u8 = ((img - img.min()) / max(float(img.max() - img.min()), 1e-6) * 255).astype(np.uint8)
        crops[(str(d.ImageLaterality), str(d.ViewPosition))] = \
            u8[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]
        whole[(str(d.ImageLaterality), str(d.ViewPosition))] = u8
        scale = max(img.shape) / MAMMO_PX
        small = resize2d(img, (round(img.shape[0] / scale), round(img.shape[1] / scale)))
        lo, hi = np.percentile(img[breast], [0.5, 99.8])
        key = f"{d.ImageLaterality}-{d.ViewPosition}"
        from PIL import Image

        Image.fromarray(to8(small, lo, hi)).save(out / f"{key}.jpg", quality=JPEG_Q,
                                                 optimize=True)
        views.append({"key": key, "laterality": str(d.ImageLaterality),
                      "view": str(d.ViewPosition), "series": int(num), "image": f"{key}.jpg",
                      "native": [int(v) for v in img.shape],
                      "native_pixel_mm": [float(v) for v in d.PixelSpacing],
                      "pixel_mm": round(float(d.PixelSpacing[0]) * scale, 3),
                      "dense": {k: v for k, v in dense.items() if k != "threshold"}})
    d0 = dicoms(base / args.series.split(",")[0])[0]
    cc = [v["dense"]["dense_fraction"] for v in views if v["view"] == "CC"]
    study = {
        "barcode": args.barcode, "cohort_index": args.index, "modality": "MG",
        "kind": "Mammography (four standard views)",
        "study": {"date": f"{d0.StudyDate[:4]}-{d0.StudyDate[4:6]}-{d0.StudyDate[6:]}",
                  "uid_suffix": str(d0.StudyInstanceUID)[-12:],
                  "description": str(getattr(d0, "StudyDescription", "")),
                  "scanner": scanner(d0),
                  "presentation": str(getattr(d0, "PresentationIntentType", ""))},
        "source": SOURCE, "report": report_facts(base / "sr"), "views": views,
        "dense_cc_mean": round(float(np.mean(cc)), 3) if cc else None,
        "density_monai": monai_density(whole) if args.density else {
            "status": "planned", "why": "run with --density (MONAI breast density, "
                                        "Apache-2.0)"},
        "screening_score": screen(crops) if args.screen else {
            "status": "planned", "why": "run with --screen (mammoscreen, Apache-2.0, minutes on "
                                        "the CPU); see docs/radiology.md"},
        "pipeline": {"script": "scripts/radiology_pipeline.py mammo", "version": "1",
                     "run_at": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")},
    }
    (out / "study.json").write_text(json.dumps(study, indent=1), encoding="utf-8")
    print(f"-> {out} ({sum(p.stat().st_size for p in out.iterdir()) / 1e6:.2f} MB)", flush=True)


def index() -> None:
    """index.json: cohort index -> its processed studies, for the patient files' tests."""
    cases = {}
    for path in sorted(OUT.glob("*/study.json")):
        s = json.loads(path.read_text(encoding="utf-8"))
        if s["modality"] == "MR":
            c1 = next(iter(s["candidates"]), None)
            result = (f"{s['study']['scanner']} {s['study']['field_t']:g} T, "
                      f"{len(s['phases'])} phases; " + (
                          f"model contour C1 {c1['longest_diameter_mm']:g} mm, "
                          f"{c1['kinetics'].get('delayed', '?')} delayed phase (model inference)"
                          if c1 else "no candidate proposed"))
        else:
            score = s["screening_score"]
            result = f"{len(s['views'])} views; " + (
                "screening score (model inference) " + ", ".join(
                    f"{side} {b['cancer']:.2g}" for side, b in score["breasts"].items()) + "; "
                if score["status"] == "implemented" else "") + (
                f"dense-pixel share {s['dense_cc_mean']:.0%} on the CC views (placeholder rule)"
                if s["dense_cc_mean"] is not None else "no dense-pixel share")
        cases.setdefault(str(s["cohort_index"]), []).append({
            "barcode": s["barcode"], "study": s["study"]["date"], "modality": s["modality"],
            "name": f"{s['kind']}, public TCIA study ({s['study']['date']})", "result": result,
            "folder": path.parent.name})
    (OUT / "index.json").write_text(json.dumps({
        "source": SOURCE, "cases": cases,
        "note": "TCGA-BRCA patients in the app's held-out set with a processed public study"},
        indent=1), encoding="utf-8")
    print(json.dumps(cases, indent=1))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("--out", default="~/muffle-radiology/dicom")
    f.add_argument("specs", nargs="+", help="BARCODE:SERIES,SERIES")
    for name in ("mri", "mammo"):
        s = sub.add_parser(name)
        s.add_argument("--dicom", default="~/muffle-radiology/dicom")
        s.add_argument("--barcode", required=True)
        s.add_argument("--index", type=int, default=None, help="the case's row in cohort.npz")
        s.add_argument("--series", required=True, help="series numbers, pre-contrast first")
        if name == "mri":
            s.add_argument("--date", default=None, help="the study date, for a patient with two")
            s.add_argument("--times", default=None, help="seconds per phase, if not in headers")
            s.add_argument("--medsam-input", choices=("sub", "early"), default="sub")
            s.add_argument("--out", default=str(OUT))
            s.add_argument("--example", action="store_true", help="label it the example pair")
            s.add_argument("--keep", default=None, help="folder for the full-resolution volumes")
        else:
            s.add_argument("--screen", action="store_true", help="add mammoscreen's score")
            s.add_argument("--density", action="store_true",
                           help="add MONAI's breast density per view")
    pr = sub.add_parser("pair")
    pr.add_argument("--earlier", required=True, help="the earlier study's folder name")
    pr.add_argument("--later", required=True)
    pr.add_argument("--out", default=str(EXAMPLE))
    pr.add_argument("--keep", default="~/muffle-radiology2/work")
    sub.add_parser("index")
    a = p.parse_args()
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    if a.cmd == "fetch":
        fetch(Path(a.out).expanduser(), a.specs)
    elif a.cmd == "mri":
        mri(a)
    elif a.cmd == "mammo":
        mammo(a)
    elif a.cmd == "pair":
        pair(a)
    else:
        index()

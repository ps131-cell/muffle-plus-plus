"""Whole-slide pipeline for a patient's own diagnostic slide -> the small result folder the
pathology workbench reads (docs/pathology.md).

Runs where openslide, torch, transformers, tensorflow and stardist are installed (WSL on the
Windows PC); the app only reads the derived numbers this writes. Reuses the spike's tiling,
texture measures, encoder loading and head (``scripts/slide_spike.py``,
``muffle.workbench.slides``) and the round-2 geometry (``muffle.workbench.invasion``).

  python scripts/slide_pipeline.py run --slide SLIDES/TCGA-AN-A0AS-DX1.svs --work WORK \
      --out app/workbenches/slides_results/TCGA-AN-A0AS-DX1 [--budget 9000] [--nuclei 500]
      1. tissue mask on the thumbnail -> the grid of 224 px tiles at 0.5 µm/px, tissue tiles
      2. if more tissue tiles than --budget: a coarse pass (every 3rd row and column) finds the
         largest tumor piece, and a square window around it holding at most --budget tissue
         tiles is scored in full; the rest of the slide is skipped and the summary says so
      3. QuiltNet-B-32 embeddings (CPU) -> the BCSS head's class probabilities -> quality rules
      4. ``invasion.analyze_slide``: front, zones, normals, arcs, islands, risk map
      5. StarDist 2D_versatile_he on up to --nuclei front-band and peritumoral tiles (front
         tiles first), at the slide's own resolution -> per-tile nuclei summaries
      6. writes tiles.json, nuclei.json, summary.json, thumbnail.jpg and up to 60 224 px crops
         (the queue, the counting field, the risk cards, the roughest front tiles): derived
         numbers and small public-slide crops only, never embeddings
  python scripts/slide_pipeline.py index --results app/workbenches/slides_results \
      --case 299=TCGA-AN-A0AS-DX1 --case 730=TCGA-D8-A1XF-DX1,TCGA-D8-A1XF-DX2 ...
      writes cases.json: cohort index -> its slide folders (the page's lookup)

Work files (WORK/<slide>/: grid.csv, embeddings.npy, tiles.csv, nuclei.csv, selection.json)
stay local. A re-run with another encoder (``--model``) only changes "encoder" in summary.json
and the probabilities; the grid, window and nuclei are reused.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
import slide_spike  # noqa: E402
from slide_spike import ENCODERS, embed_stack, texture  # noqa: E402

from muffle.workbench import invasion as inv  # noqa: E402
from muffle.workbench.slides import MPP, TILE_PX, analyze, quality  # noqa: E402

TISSUE_SAT = 12       # placeholder: the colon analyzer's saturation rule, as in slide_spike count
TISSUE_MIN_SHARE = 0.5  # design: a tile is tissue when half its pixels are
COARSE = 3            # coarse pass: every 3rd row and column
MAX_CROPS = 60
STARDIST_MODEL = "2D_versatile_he"


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def uptime() -> str:
    try:
        return "load average %.1f %.1f %.1f" % os.getloadavg()
    except OSError:
        return "load average unknown"


# --- 1. grid -----------------------------------------------------------------------------

def tissue_grid(slide, work: Path) -> tuple[pd.DataFrame, dict]:
    """Every tile position of the slide with its tissue share (from a saturation mask on the
    thumbnail); cached as grid.csv."""
    from skimage.color import rgb2hsv

    base_mpp = float(slide.properties.get("openslide.mpp-x", 0.25))
    step = int(round(TILE_PX * MPP / base_mpp))  # tile side in base px
    W, H = slide.dimensions
    region = {"base_mpp": base_mpp, "step": step, "slide_dimensions": [W, H],
              "grid_shape": [H // step, W // step]}
    if (work / "grid.csv").exists():
        return pd.read_csv(work / "grid.csv"), region
    thumb = np.array(slide.get_thumbnail((4096, 4096)).convert("RGB"))
    ds = W / thumb.shape[1]
    tissue = (rgb2hsv(thumb)[..., 1] * 255) > TISSUE_SAT
    rows = []
    for r in range(H // step):
        for c in range(W // step):
            y0, y1 = int(r * step / ds), int((r + 1) * step / ds)
            x0, x1 = int(c * step / ds), int((c + 1) * step / ds)
            block = tissue[y0:max(y1, y0 + 1), x0:max(x1, x0 + 1)]
            share = float(block.mean()) if block.size else 0.0
            if share >= TISSUE_MIN_SHARE:
                rows.append({"row": r, "col": c, "tissue_share": round(share, 2)})
    grid = pd.DataFrame(rows)
    work.mkdir(parents=True, exist_ok=True)
    grid.to_csv(work / "grid.csv", index=False)
    return grid, region


# --- 2. selection ------------------------------------------------------------------------

def read_tile(slide, step: int, r: int, c: int, size: int = TILE_PX) -> np.ndarray:
    from PIL import Image

    reg = slide.read_region((c * step, r * step), 0, (step, step)).convert("RGB")
    if size != step:
        reg = reg.resize((size, size), Image.LANCZOS)
    return np.array(reg)


def embed_tiles(slide, step: int, positions: pd.DataFrame, encoder, batch: int,
                with_texture: bool) -> tuple[np.ndarray, list[dict], float]:
    """Embeddings (and texture measures) for the given tile positions, streamed in batches so
    no tile stack sits in memory. Returns embeddings, measures, tiles/s of the encoder."""
    embs, measures, t_enc = [], [], 0.0
    pos = positions[["row", "col"]].to_numpy(int)
    for i in range(0, len(pos), batch):
        rgb = np.stack([read_tile(slide, step, r, c) for r, c in pos[i:i + batch]])
        if with_texture:
            measures += [texture(t) for t in rgb]
        t0 = time.time()
        e, _ = embed_stack(encoder, rgb, batch)
        t_enc += time.time() - t0
        embs.append(e)
        if (i // batch) % 20 == 0:
            log(f"  embedded {i + len(rgb)}/{len(pos)} tiles, {uptime()}")
    emb = np.concatenate(embs) if embs else np.zeros((0, 1), np.float32)
    return emb, measures, len(pos) / t_enc if t_enc else 0.0


def apply_head(head: dict, emb: np.ndarray) -> pd.DataFrame:
    z = (emb - np.array(head["scaler_mean"])) / np.array(head["scaler_scale"])
    logits = z @ np.array(head["coef"]).T + np.array(head["intercept"])
    logits -= logits.max(1, keepdims=True)
    proba = np.exp(logits) / np.exp(logits).sum(1, keepdims=True)
    return pd.DataFrame({f"p_{c}": np.round(proba[:, i], 4) for i, c in
                         enumerate(head["classes"])})


def choose_window(grid: pd.DataFrame, budget: int, centre: tuple[float, float]) -> dict:
    """The largest square window (in tiles) around ``centre`` holding at most ``budget`` tissue
    tiles."""
    best = None
    for side in range(20, 2000, 4):
        r0 = int(round(centre[0] - side / 2))
        c0 = int(round(centre[1] - side / 2))
        sel = grid[(grid.row >= r0) & (grid.row < r0 + side) & (grid.col >= c0)
                   & (grid.col < c0 + side)]
        if len(sel) > budget:
            break
        best = {"r0": r0, "c0": c0, "side": side, "tissue_tiles": int(len(sel))}
        if len(sel) == len(grid):
            break
    return best


def select_tiles(slide, grid: pd.DataFrame, region: dict, budget: int, work: Path, encoder,
                 head: dict, batch: int) -> tuple[pd.DataFrame, dict]:
    """All tissue tiles when they fit the budget; otherwise a coarse pass finds the largest
    tumor piece and a window around it is scored. Cached as selection.json."""
    sel_path = work / "selection.json"
    if sel_path.exists():
        sel = json.loads(sel_path.read_text())
    elif len(grid) <= budget:
        sel = {"mode": "whole slide", "r0": 0, "c0": 0, "side": None,
               "tissue_tiles_total": int(len(grid)), "scored": int(len(grid)), "coarse": None}
    else:
        coarse = grid[(grid.row % COARSE == 0) & (grid.col % COARSE == 0)]
        log(f"coarse pass on {len(coarse)} of {len(grid)} tissue tiles")
        emb, _, rate = embed_tiles(slide, region["step"], coarse, encoder, batch, False)
        probs = apply_head(head, emb)
        cg = coarse.reset_index(drop=True).assign(row=coarse.row.to_numpy() // COARSE,
                                                  col=coarse.col.to_numpy() // COARSE)
        cg = pd.concat([cg, probs], axis=1)
        res = analyze(cg, head["classes"])
        t = res["tiles"]
        if t["main_tumor"].any():
            m = t[t["main_tumor"]]
            centre = (float(m.row.mean()) * COARSE, float(m.col.mean()) * COARSE)
            why = "centred on the largest tumor piece of the coarse pass"
        else:
            centre = (float(grid.row.mean()), float(grid.col.mean()))
            why = "no tumor found in the coarse pass: centred on the tissue"
        win = choose_window(grid, budget, centre)
        sel = {"mode": "tumor-centred window", "r0": win["r0"], "c0": win["c0"],
               "side": win["side"], "tissue_tiles_total": int(len(grid)),
               "scored": win["tissue_tiles"], "why": why,
               "coarse": {"tiles": int(len(coarse)), "every": COARSE,
                          "tumor_tiles": int(t["tumor"].sum()), "tiles_per_s": round(rate, 2)}}
        log(f"window {win} ({why})")
    sel_path.write_text(json.dumps(sel, indent=1))
    g = grid
    if sel["side"]:
        g = grid[(grid.row >= sel["r0"]) & (grid.row < sel["r0"] + sel["side"])
                 & (grid.col >= sel["c0"]) & (grid.col < sel["c0"] + sel["side"])]
    g = g.assign(row=g.row - sel["r0"], col=g.col - sel["c0"]).reset_index(drop=True)
    return g, sel


# --- 5. nuclei --------------------------------------------------------------------------

def nuclei_tiles(tiles: pd.DataFrame, n: int) -> pd.DataFrame:
    """Which tiles StarDist runs on: the front, then the band just outside it by distance,
    then the rest of the front band, then the peritumoral zone, usable tiles only."""
    ok = tiles[tiles["qc"] == "ok"]
    front = ok[ok["front"]]
    outside = ok[(ok["zone"] == "front band") & ~ok["main_tumor"]].sort_values("dist_to_front_um")
    band = ok[(ok["zone"] == "front band") & ok["main_tumor"] & ~ok["front"]]
    peri = ok[ok["zone"] == "peritumoral"].sort_values("dist_to_front_um")
    chosen = pd.concat([front, outside, band, peri]).drop_duplicates(["row", "col"])
    return chosen[["row", "col"]].head(n).reset_index(drop=True)


def run_stardist(slide, region: dict, ran: pd.DataFrame, threads: int, work: Path
                 ) -> tuple[pd.DataFrame, dict]:
    """Nuclei on each chosen tile at the slide's own resolution: one row per nucleus with its
    tile, centroid (µm inside the tile), area (µm²) and solidity. Cached as nuclei.csv."""
    if (work / "nuclei.csv").exists():
        meta = json.loads((work / "nuclei_meta.json").read_text())
        return pd.read_csv(work / "nuclei.csv"), meta
    import tensorflow as tf
    from csbdeep.utils import normalize
    from PIL import Image
    from skimage.measure import regionprops
    from stardist.models import StarDist2D

    tf.config.threading.set_intra_op_parallelism_threads(threads)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    model = StarDist2D.from_pretrained(STARDIST_MODEL)
    step, mpp = region["step"], region["base_mpp"]
    up = 2 if mpp > 0.4 else 1  # a 20× slide is upsampled so nuclei are ~20 px across
    mpp_run = mpp / up
    rows, t0 = [], time.time()
    for i, (r, c) in enumerate(ran[["row", "col"]].itertuples(index=False)):
        img = read_tile(slide, step, int(r), int(c), size=step)
        if up > 1:
            img = np.array(Image.fromarray(img).resize((step * up, step * up), Image.BICUBIC))
        labels, _ = model.predict_instances(normalize(img, 1, 99.8, axis=(0, 1)),
                                            verbose=False, show_tile_progress=False)
        for p in regionprops(labels):
            rows.append({"row": int(r), "col": int(c), "x_um": round(p.centroid[1] * mpp_run, 1),
                         "y_um": round(p.centroid[0] * mpp_run, 1),
                         "area_um2": round(float(p.area) * mpp_run ** 2, 1),
                         "solidity": round(float(p.solidity), 3)})
        if i % 50 == 0:
            log(f"  nuclei on {i + 1}/{len(ran)} tiles, {len(rows)} nuclei, {uptime()}")
    dt = time.time() - t0
    nuclei = pd.DataFrame(rows, columns=["row", "col", "x_um", "y_um", "area_um2", "solidity"])
    nuclei.to_csv(work / "nuclei.csv", index=False)
    meta = {"model": f"StarDist {STARDIST_MODEL}", "tiles": int(len(ran)),
            "nuclei": int(len(nuclei)), "s_per_tile": round(dt / max(len(ran), 1), 2),
            "run_mpp": mpp_run, "threads": threads, "uptime": uptime()}
    (work / "nuclei_meta.json").write_text(json.dumps(meta, indent=1))
    return nuclei, meta


# --- 6. output -------------------------------------------------------------------------

def crop_tiles(res: dict) -> list[tuple[int, int, str]]:
    """Which tiles get a 224 px crop (≤ MAX_CROPS): the queue, the counting field, the risk
    cards, the roughest front tiles, the breakaway tiles, the most unsure tiles."""
    t = res["tiles"]
    picks: list[tuple[int, int, str]] = []
    seen = set()

    def add(r, c, why):
        if (int(r), int(c)) not in seen and len(picks) < MAX_CROPS:
            seen.add((int(r), int(c)))
            picks.append((int(r), int(c), why))

    for p in res["queue"]:
        add(p["row"], p["col"], p["pointer"])
    if res["hotspot"]:
        add(res["hotspot"]["row"], res["hotspot"]["col"], "counting field")
    for c in res["risk"]["cards"][:6]:
        add(c["row"], c["col"], c["card"])
    if "buds" in t:
        budding = t[t["buds"].fillna(0) > 0].sort_values("buds", ascending=False)
        for r in budding.head(12).itertuples():
            add(r.row, r.col, "breakaway candidates")
    for r in t[t["front"]].sort_values("push", ascending=False).head(15).itertuples():
        add(r.row, r.col, "front, highest push")
    for r in t[t["finger"]].head(8).itertuples():
        add(r.row, r.col, "finger")
    for r in t[t["unsure"]].sort_values("top_p").head(6).itertuples():
        add(r.row, r.col, "unsure")
    return picks


def write_result(slide, region: dict, sel: dict, tiles: pd.DataFrame, nuclei: pd.DataFrame | None,
                 nuc_meta: dict | None, res: dict, head_metrics: dict, encoder_info: dict,
                 timings: dict, out: Path, slide_name: str, work: Path) -> None:
    from PIL import Image

    out.mkdir(parents=True, exist_ok=True)
    classes = head_metrics["classes"]
    keep = ["row", "col", "qc"] + [f"p_{c}" for c in classes]
    tj = tiles[keep].copy()
    for c in classes:
        tj[f"p_{c}"] = tj[f"p_{c}"].round(3)
    tj.to_json(out / "tiles.json", orient="split", index=False)
    # nuclei summaries for the counted tiles, and nucleus centroids for the crop tiles only
    picks = crop_tiles(res)
    nuc_out = {"tiles": [], "points": {}}
    if nuclei is not None and "n_nuclei" in res["tiles"]:
        counted = res["tiles"][res["tiles"]["n_nuclei"].notna()]
        cols = ["row", "col", "n_nuclei", "n_lymph", "n_tumor_nuc", "n_lymph_near_tumor", "buds",
                "nuc_area_cv"]
        nuc_out["tiles"] = json.loads(counted[cols].to_json(orient="split", index=False))
        lymph = inv.lymphocyte_like(nuclei) if len(nuclei) else np.zeros(0, bool)
        for r, c, _ in picks:
            g = nuclei[(nuclei.row == r) & (nuclei.col == c)]
            if len(g):
                nuc_out["points"][f"{r}_{c}"] = [[float(x), float(y), int(lab)] for x, y, lab in
                                                 zip(g.x_um, g.y_um, lymph[g.index], strict=True)]
    (out / "nuclei.json").write_text(json.dumps(nuc_out))
    # crops
    crops = out / "crops"
    crops.mkdir(exist_ok=True)
    for old in crops.glob("*.jpg"):
        old.unlink()
    step = region["step"]
    for r, c, _why in picks:
        img = read_tile(slide, step, r + sel["r0"], c + sel["c0"])
        Image.fromarray(img).save(crops / f"{r}_{c}.jpg", quality=72)
    # thumbnail of the scored region
    h, w = res["grid_shape"]
    x0, y0 = sel["c0"] * step, sel["r0"] * step
    W, H = min(w * step, region["slide_dimensions"][0] - x0), min(h * step,
                                                                 region["slide_dimensions"][1] - y0)
    lvl = slide.get_best_level_for_downsample(16)
    ds = slide.level_downsamples[lvl]
    thumb = slide.read_region((x0, y0), lvl, (int(W / ds), int(H / ds))).convert("RGB")
    thumb.thumbnail((900, 900))
    thumb.save(out / "thumbnail.jpg", quality=80)
    s = res["summary"]
    summary = {
        "slide": slide_name, "patient": slide_name[:12],
        "source": "TCGA-BRCA diagnostic slide (GDC, open access); the patient's own section",
        "base_mpp": region["base_mpp"], "slide_dimensions": region["slide_dimensions"],
        "tile_px": TILE_PX, "mpp": MPP, "step_base_px": step,
        "scored": {"mode": sel["mode"], "origin_tile": [sel["r0"], sel["c0"]],
                   "window_side_tiles": sel["side"],
                   "tissue_tiles_total": sel["tissue_tiles_total"],
                   "scored_tiles": int(len(tiles)),
                   "skipped_tiles": int(sel["tissue_tiles_total"] - len(tiles)),
                   "why": sel.get("why", "the whole slide fits the budget"),
                   "coarse_pass": sel.get("coarse")},
        "grid_shape": res["grid_shape"],
        "encoder": encoder_info,
        "head": {"kind": "logistic regression on frozen embeddings", "classes": classes,
                 "training_data": f"BCSS tiles from {len(head_metrics['train_slides'])} "
                                  f"TCGA-BRCA slides ({head_metrics['n_train_tiles']} tiles)",
                 "held_out": f"{len(head_metrics['test_slides'])} slides, "
                             f"{head_metrics['n_test_tiles']} tiles, patient-disjoint",
                 "accuracy": head_metrics["accuracy"],
                 "balanced_accuracy": head_metrics["balanced_accuracy"],
                 "per_class": head_metrics["per_class"], "confusion": head_metrics["confusion"],
                 "accuracy_below_cutoff": head_metrics["accuracy_below_cutoff"],
                 "accuracy_at_or_above_cutoff": head_metrics["accuracy_at_or_above_cutoff"],
                 "share_below_cutoff": head_metrics["share_below_cutoff"],
                 "not_learned": {"normal_breast": "too few labeled tiles in BCSS at this tile "
                                                  "size",
                                 "dcis": "one BCSS slide only; cannot be held out"},
                 "this_patient_in_training": slide_name[:12] in
                 {s[:12] for s in head_metrics["train_slides"] + head_metrics["test_slides"]}},
        "nuclei": nuc_meta or {"model": None, "tiles": 0, "note": "not run"},
        "analysis": s, "numbers": res["numbers"],
        "arcs": res["arcs"], "rose": res["rose"], "islands": res["islands"],
        "hotspot": res["hotspot"], "immune": res["immune"], "tsr": res["tsr"],
        "necrosis": res["necrosis"], "risk_cards": res["risk"]["cards"],
        "risk_points": res["risk"]["table"], "queue": res["queue"],
        "crops": [{"row": r, "col": c, "why": why} for r, c, why in picks],
        "timings": timings, "method_version": "0.2",
        "status": "implemented; tissue head validated on held-out BCSS slides only; nuclei "
                  "model pretrained, not validated on breast here; not reviewed by a "
                  "pathologist",
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=1, default=_json))
    size = sum(p.stat().st_size for p in out.rglob("*") if p.is_file()) / 1e6
    log(f"wrote {out} ({size:.2f} MB, {len(picks)} crops)")


def _json(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return None if np.isnan(o) else float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    raise TypeError(type(o))


# --- run ---------------------------------------------------------------------------------

def cmd_run(a):
    import openslide

    slide_path = Path(a.slide)
    name = slide_path.stem
    work = Path(a.work) / name
    work.mkdir(parents=True, exist_ok=True)
    timings = {"uptime_at_start": uptime(), "threads": a.threads}
    slide = openslide.OpenSlide(str(slide_path))
    t0 = time.time()
    grid, region = tissue_grid(slide, work)
    timings["grid_s"] = round(time.time() - t0, 1)
    log(f"{name}: {len(grid)} tissue tiles of {region['grid_shape']} ({timings['grid_s']} s)")

    head = json.load(open(Path(a.work) / "head.json"))
    head_metrics = json.load(open(Path(a.work) / "head_metrics.json"))
    slide_spike.a_threads = a.threads
    encoder = slide_spike.load_encoder(a.model)
    t0 = time.time()
    positions, sel = select_tiles(slide, grid, region, a.budget, work, encoder, head, a.batch)
    timings["select_s"] = round(time.time() - t0, 1)

    emb_path, tiles_path = work / "embeddings.npy", work / "tiles.csv"
    if emb_path.exists() and tiles_path.exists():
        tiles, emb = pd.read_csv(tiles_path), np.load(emb_path)
        cached = json.loads((work / "embed_meta.json").read_text())
        rate, timings["embed_s"] = cached["tiles_per_s"], cached["s"]
        timings["embed_uptime"] = cached["uptime"]
    else:
        t0 = time.time()
        emb, measures, rate = embed_tiles(slide, region["step"], positions, encoder, a.batch,
                                          True)
        tiles = pd.concat([positions[["row", "col"]], pd.DataFrame(measures)], axis=1)
        tiles["qc"] = quality(tiles)
        tiles.to_csv(tiles_path, index=False)
        np.save(emb_path, emb)
        timings["embed_s"], timings["embed_uptime"] = round(time.time() - t0, 1), uptime()
        (work / "embed_meta.json").write_text(json.dumps(
            {"tiles_per_s": round(rate, 2), "uptime": uptime(), "s": timings["embed_s"]}))
        log(f"embedded {len(tiles)} tiles at {rate:.2f} tiles/s ({uptime()})")
    probs = apply_head(head, emb)
    for col in probs:
        tiles[col] = probs[col].to_numpy()
    classes = head["classes"]

    res = inv.analyze_slide(tiles, classes)
    nuclei, nuc_meta = None, None
    if not a.skip_nuclei and res["tiles"]["front"].any():
        ran = nuclei_tiles(res["tiles"], a.nuclei)
        log(f"nuclei on {len(ran)} tiles")
        t0 = time.time()
        nuclei, nuc_meta = run_stardist(slide, region, ran, a.threads, work)
        timings["nuclei_s"] = round(nuc_meta["s_per_tile"] * nuc_meta["tiles"], 1)
        timings["nuclei_uptime"] = nuc_meta["uptime"]
        summ = inv.nuclei_summary(nuclei, res["tiles"], ran)
        tiles = tiles.merge(summ, on=["row", "col"], how="left")
        res = inv.analyze_slide(tiles, classes)
    elif not a.skip_nuclei:
        log("no tumor front in the map: nuclei not counted")
    timing_path = Path(a.work) / "timing.json"
    timing = json.load(open(timing_path)) if timing_path.exists() else {}
    spec = ENCODERS[a.model]
    encoder_info = {"name": a.model, "license": spec.get("license", "?"),
                    "access": "open, ungated" if spec.get("gate", "none") == "none"
                    else f"gated: {spec['gate']}", "kind": spec.get("loader", "?"),
                    "dim": spec.get("dim"), "tiles_per_s_cpu": round(rate, 2),
                    "threads": a.threads, "peak_rss_gb": timing.get("peak_rss_gb")}
    timings["uptime_at_end"] = uptime()
    write_result(slide, region, sel, tiles, nuclei, nuc_meta, res, head_metrics, encoder_info,
                 timings, Path(a.out), name, work)
    print(json.dumps(res["numbers"], indent=1, default=_json))


def cmd_index(a):
    cases = {}
    for item in a.case:
        idx, slides = item.split("=")
        cases[idx] = slides.split(",")
    path = Path(a.results) / "cases.json"
    old = json.loads(path.read_text()) if path.exists() else {}
    old.update(cases)
    path.write_text(json.dumps(old, indent=1, sort_keys=True))
    print(old)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("--slide", required=True)
    r.add_argument("--work", required=True, help="holds head.json, head_metrics.json")
    r.add_argument("--out", required=True)
    r.add_argument("--model", default="wisdomik/QuiltNet-B-32")
    r.add_argument("--budget", type=int, default=9000)
    r.add_argument("--nuclei", type=int, default=500)
    r.add_argument("--threads", type=int, default=4)
    r.add_argument("--batch", type=int, default=32)
    r.add_argument("--skip-nuclei", action="store_true")
    i = sub.add_parser("index")
    i.add_argument("--results", required=True)
    i.add_argument("--case", action="append", required=True, help="INDEX=SLIDE[,SLIDE]")
    args = p.parse_args()
    {"run": cmd_run, "index": cmd_index}[args.cmd](args)

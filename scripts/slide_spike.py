"""Breast slide spike: BCSS tiles -> open encoder embeddings -> tissue head -> one slide result.

Runs where openslide, torch and transformers are installed (WSL on the Windows PC, or a Mac); the
app only reads the small result folder this writes. Subcommands, in order:

  python scripts/slide_spike.py tiles  --slides DIR --masks DIR --out WORK
      For every <slide>.svs with a <slide>.png BCSS mask (region at base resolution, bounds from
      meta/roiBounds.csv encoded in the file list --bounds): cut the labeled region into 224 px
      tiles at 0.5 µm/px, give each tile its majority BCSS class (purity >= 0.5, else "mixed"),
      measure texture (edges, structure, ink shares, blur) and save WORK/<slide>/tiles.csv,
      thumbnail.png and the 224 px tiles as a uint8 .npy stack (local only, never committed).
  python scripts/slide_spike.py embed  --work WORK [--model kaiko-ai/midnight]
      Embed every tile on CPU, report tiles/s and peak memory, save embeddings.npy per slide.
  python scripts/slide_spike.py train  --work WORK --test SLIDE [SLIDE ...]
      Logistic regression on the training slides' pure tiles; accuracy per class on the held-out
      slides (patient-disjoint: one slide per patient in BCSS). Writes WORK/head.json (weights)
      and WORK/head_metrics.json.
  python scripts/slide_spike.py result --work WORK --slide SLIDE \
      --out app/workbenches/slides_example
      Score one held-out slide with the head and write the folder the workbench reads: tiles.csv
      (positions, class probabilities, quality measures), thumbnail.png, summary.json. Only
      derived numbers on public TCGA tiles; no pixels beyond the thumbnail, no embeddings.
  python scripts/slide_spike.py requality --work WORK
      Recompute texture measures and quality verdicts from the saved tiles (after a rule change).
  python scripts/slide_spike.py count --slides DIR
      Tissue tiles per whole slide (saturation mask on the thumbnail), to extrapolate the timing.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from muffle.workbench.slides import (  # noqa: E402
    BCSS_TO_CLASS,
    CLASSES,
    CUTOFFS,
    MPP,
    TILE_PX,
    analyze,
    quality,
)

# Encoders this spike can run, by Hugging Face id: how to load them, how to normalize a tile
# and which vector is the tile's embedding. Both are MIT and ungated (docs/registry.md).
ENCODERS = {
    "kaiko-ai/midnight": {"kind": "dinov2", "mean": (0.5, 0.5, 0.5), "std": (0.5, 0.5, 0.5)},
    "wisdomik/QuiltNet-B-32": {"kind": "clip", "mean": (0.48145466, 0.4578275, 0.40821073),
                               "std": (0.26862954, 0.26130258, 0.27577711)},
}


# --- tiles -----------------------------------------------------------------------------------

def texture(tile: np.ndarray) -> dict:
    """The colon analyzer's quality measures, re-implemented: share of pixels on a sharp edge,
    share of 4×4 sub-blocks with structure, pen-ink colour shares, Laplacian variance (blur)."""
    from skimage.color import rgb2gray
    from skimage.filters import laplace, sobel

    g = rgb2gray(tile)
    edges = sobel(g) > 0.1
    blocks = edges.reshape(4, TILE_PX // 4, 4, TILE_PX // 4).mean(axis=(1, 3))
    r, gch, b = (tile[..., i].astype(int) for i in range(3))
    # Pen ink is cyan, green or true blue (green at least as strong as red); H&E's purple-blue
    # hematoxylin has green well below red, so it must not count. The first version counted
    # blue > red alone and excluded a whole nucleus-dense tumor region (TCGA-A8-A08R).
    bluegreen = ((gch > r + 20) | ((b > r + 30) & (gch >= r - 5))) & (tile.max(-1) > 60)
    black = tile.max(-1) < 60
    red = (r > 150) & (gch < 80) & (b < 80)
    return {"edges": round(float(edges.mean()), 4),
            "structure_cov": round(float((blocks > 0.01).mean()), 3),
            "ink_bluegreen": round(float(bluegreen.mean()), 3),
            "ink_black": round(float(black.mean()), 3),
            "ink_red": round(float(red.mean()), 3),
            "blur": round(float(laplace(g).var()), 6)}


def cut_tiles(slide_path: Path, mask_path: Path, bounds: tuple[int, int], out: Path) -> int:
    import openslide
    from PIL import Image

    Image.MAX_IMAGE_PIXELS = None
    slide = openslide.OpenSlide(str(slide_path))
    base_mpp = float(slide.properties.get("openslide.mpp-x", 0.25))
    scale = MPP / base_mpp                        # base px per output px (~2)
    mask = np.array(Image.open(mask_path))        # at base resolution, ROI only
    xmin, ymin = bounds
    h, w = mask.shape
    step = int(round(TILE_PX * scale))            # tile side in base px
    rows, stack = [], []
    for r, y in enumerate(range(0, h - step + 1, step)):
        for c, x in enumerate(range(0, w - step + 1, step)):
            region = slide.read_region((xmin + x, ymin + y), 0, (step, step)).convert("RGB")
            tile = np.array(region.resize((TILE_PX, TILE_PX), Image.LANCZOS))
            m = mask[y:y + step, x:x + step]
            labeled = m[(m != 0) & (m != 7)]
            if labeled.size < 0.5 * m.size:
                label, purity = "unlabeled", 0.0
            else:
                codes, counts = np.unique(labeled, return_counts=True)
                top = int(codes[np.argmax(counts)])
                purity = float(counts.max() / labeled.size)
                label = BCSS_TO_CLASS.get(top, "other")
                if purity < CUTOFFS["label_purity"][0]:
                    label = "mixed"
            rows.append({"row": r, "col": c, "x": xmin + x, "y": ymin + y, "bcss_label": label,
                         "purity": round(purity, 3), **texture(tile)})
            stack.append(tile)
    out.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df["qc"] = quality(df)
    df.to_csv(out / "tiles.csv", index=False)
    np.save(out / "tiles_rgb.npy", np.stack(stack).astype(np.uint8))
    thumb = slide.read_region((xmin, ymin), 0, (w, h)) if w * h < 4e7 else None
    if thumb is None:  # read from a lower level for big regions
        lvl = slide.get_best_level_for_downsample(8)
        ds = slide.level_downsamples[lvl]
        thumb = slide.read_region((xmin, ymin), lvl, (int(w / ds), int(h / ds)))
    thumb = thumb.convert("RGB")
    thumb.thumbnail((1024, 1024))
    thumb.save(out / "thumbnail.png")
    whole = slide.get_thumbnail((1024, 1024))
    whole.save(out / "slide_thumbnail.png")
    json.dump({"slide": slide_path.stem, "base_mpp": base_mpp, "region": [xmin, ymin, w, h],
               "grid_shape": [int(df["row"].max()) + 1, int(df["col"].max()) + 1],
               "slide_dimensions": list(slide.dimensions)},
              open(out / "region.json", "w"), indent=1)
    return len(df)


def cmd_requality(a):
    """Recompute the texture measures and the quality verdicts from the saved tiles."""
    for folder in sorted(Path(a.work).iterdir()):
        if not (folder / "tiles_rgb.npy").exists():
            continue
        df = pd.read_csv(folder / "tiles.csv")
        rgb = np.load(folder / "tiles_rgb.npy")
        measures = pd.DataFrame([texture(t) for t in rgb])
        for col in measures:
            df[col] = measures[col].to_numpy()
        df["qc"] = quality(df)
        df.to_csv(folder / "tiles.csv", index=False)
        print(folder.name, df["qc"].value_counts().to_dict(), flush=True)


def cmd_tiles(a):
    bounds = {r[""]: (int(r["xmin"]), int(r["ymin"])) for r in
              pd.read_csv(a.bounds, dtype=str).rename(columns={"Unnamed: 0": ""})
              .to_dict("records")}
    for mask in sorted(Path(a.masks).glob("*.png")):
        key = mask.stem
        slide = Path(a.slides) / f"{key}.svs"
        if not slide.exists() or (Path(a.out) / key / "tiles.csv").exists():
            continue
        t = time.time()
        n = cut_tiles(slide, mask, bounds[key], Path(a.out) / key)
        print(f"{key}: {n} tiles in {time.time() - t:.0f} s", flush=True)


# --- embed -----------------------------------------------------------------------------------

def load_encoder(name: str):
    import torch
    from transformers import AutoModel, CLIPModel

    torch.set_num_threads(a_threads)
    spec = ENCODERS[name]
    model = (CLIPModel if spec["kind"] == "clip" else AutoModel).from_pretrained(name).eval()
    return model, spec


def embed_stack(encoder, rgb: np.ndarray, batch: int = 8) -> tuple[np.ndarray, float]:
    """Tile embeddings: for a DINOv2 model the CLS token and the mean patch token concatenated
    (Midnight's model card); for a CLIP model the projected image features. Returns the
    embeddings and tiles per second."""
    import torch

    model, spec = encoder
    mean = torch.tensor(spec["mean"]).view(1, 3, 1, 1)
    std = torch.tensor(spec["std"]).view(1, 3, 1, 1)
    out, t = [], time.time()
    with torch.inference_mode():
        for i in range(0, len(rgb), batch):
            x = torch.from_numpy(rgb[i:i + batch]).permute(0, 3, 1, 2).float() / 255
            x = (x - mean) / std
            if spec["kind"] == "clip":
                f = model.visual_projection(model.vision_model(pixel_values=x).pooler_output)
            else:
                h = model(pixel_values=x).last_hidden_state
                f = torch.cat([h[:, 0], h[:, 1:].mean(1)], -1)
            out.append(f.numpy())
    return np.concatenate(out).astype(np.float32), len(rgb) / (time.time() - t)


def cmd_embed(a):
    import resource

    encoder = load_encoder(a.model)
    rates = []
    for folder in sorted(Path(a.work).iterdir()):
        rgb_path = folder / "tiles_rgb.npy"
        if not rgb_path.exists() or ((folder / "embeddings.npy").exists() and not a.limit):
            continue
        rgb = np.load(rgb_path)
        if a.limit:
            rgb = rgb[:a.limit]
        emb, rate = embed_stack(encoder, rgb, a.batch)
        if not a.limit:
            np.save(folder / "embeddings.npy", emb)
        rates.append(rate)
        print(f"{folder.name}: {len(rgb)} tiles, {rate:.2f} tiles/s, dim {emb.shape[1]}",
              flush=True)
        if a.limit and len(rates) >= 2:  # a timing run: two slides are enough
            break
    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1e6
    timing = {"model": a.model, "threads": a_threads, "batch": a.batch,
              "tiles_per_s_median": round(float(np.median(rates)), 3) if rates else None,
              "peak_rss_gb": round(peak, 2)}
    name = "timing.json" if not a.limit else f"timing_{a.model.split('/')[-1]}_{a.limit}.json"
    json.dump(timing, open(Path(a.work) / name, "w"), indent=1)
    print(timing)


# --- train -----------------------------------------------------------------------------------

def load_sets(work: Path):
    sets = {}
    for folder in sorted(work.iterdir()):
        if (folder / "embeddings.npy").exists():
            df = pd.read_csv(folder / "tiles.csv")
            sets[folder.name] = (df, np.load(folder / "embeddings.npy"))
    return sets


def cmd_train(a):
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import confusion_matrix
    from sklearn.preprocessing import StandardScaler

    sets = load_sets(Path(a.work))
    test = set(a.test)
    train = [k for k in sets if k not in test]
    classes = [c for c in CLASSES if c in a.classes]

    def pure(keys):
        xs, ys, slides = [], [], []
        for k in keys:
            df, emb = sets[k]
            keep = df["bcss_label"].isin(classes) & (df["qc"] == "ok")
            xs.append(emb[keep.to_numpy()])
            ys += df.loc[keep, "bcss_label"].tolist()
            slides += [k] * int(keep.sum())
        return np.concatenate(xs), np.array(ys), np.array(slides)

    xtr, ytr, _ = pure(train)
    xte, yte, ste = pure(sorted(test))
    scaler = StandardScaler().fit(xtr)
    clf = LogisticRegression(C=a.C, max_iter=3000, class_weight="balanced")
    clf.fit(scaler.transform(xtr), ytr)
    pred = clf.predict(scaler.transform(xte))
    proba = clf.predict_proba(scaler.transform(xte))
    present = [c for c in classes if c in set(ytr)]
    cm = confusion_matrix(yte, pred, labels=present)
    per_class = {c: {"n_test": int((yte == c).sum()),
                     "recall": round(float((pred[yte == c] == c).mean()), 3)
                     if (yte == c).any() else None,
                     "n_train": int((ytr == c).sum())} for c in present}
    top = proba.max(1)
    cutoff = CUTOFFS["unsure_below"][0]
    metrics = {
        "classes": present, "train_slides": train, "test_slides": sorted(test),
        "n_train_tiles": int(len(ytr)), "n_test_tiles": int(len(yte)),
        "accuracy": round(float((pred == yte).mean()), 3),
        "balanced_accuracy": round(float(np.mean([v["recall"] for v in per_class.values()
                                                  if v["recall"] is not None])), 3),
        "per_class": per_class,
        "confusion": {"labels": present, "rows_true_cols_pred": cm.tolist()},
        "per_test_slide": {s: round(float((pred[ste == s] == yte[ste == s]).mean()), 3)
                           for s in sorted(test) if (ste == s).any()},
        "unsure_cutoff": cutoff,
        "accuracy_below_cutoff": round(float((pred[top < cutoff] == yte[top < cutoff]).mean()), 3)
        if (top < cutoff).any() else None,
        "accuracy_at_or_above_cutoff":
        round(float((pred[top >= cutoff] == yte[top >= cutoff]).mean()), 3)
        if (top >= cutoff).any() else None,
        "share_below_cutoff": round(float((top < cutoff).mean()), 3),
        "C": a.C, "encoder": json.load(open(Path(a.work) / "timing.json"))["model"],
    }
    json.dump(metrics, open(Path(a.work) / "head_metrics.json", "w"), indent=1)
    head = {"classes": list(clf.classes_), "coef": clf.coef_.tolist(),
            "intercept": clf.intercept_.tolist(), "scaler_mean": scaler.mean_.tolist(),
            "scaler_scale": scaler.scale_.tolist()}
    json.dump(head, open(Path(a.work) / "head.json", "w"))
    print(json.dumps({k: v for k, v in metrics.items() if k != "confusion"}, indent=1))
    print("confusion (rows true, cols predicted):", present)
    print(cm)


# --- result ----------------------------------------------------------------------------------

def cmd_result(a):
    work = Path(a.work)
    head = json.load(open(work / "head.json"))
    metrics = json.load(open(work / "head_metrics.json"))
    timing = json.load(open(work / "timing.json"))
    df = pd.read_csv(work / a.slide / "tiles.csv")
    emb = np.load(work / a.slide / "embeddings.npy")
    z = (emb - np.array(head["scaler_mean"])) / np.array(head["scaler_scale"])
    logits = z @ np.array(head["coef"]).T + np.array(head["intercept"])
    logits -= logits.max(1, keepdims=True)
    proba = np.exp(logits) / np.exp(logits).sum(1, keepdims=True)
    for i, c in enumerate(head["classes"]):
        df[f"p_{c}"] = np.round(proba[:, i], 4)
    classes = list(head["classes"])
    cols = ["row", "col", "x", "y", "qc", "edges", "structure_cov", "ink_bluegreen", "ink_black",
            "ink_red", "blur"] + [f"p_{c}" for c in classes]
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    tiles = df[cols].copy()
    res = analyze(tiles, classes)
    tiles.to_csv(out / "tiles.csv", index=False)
    region = json.load(open(work / a.slide / "region.json"))
    from PIL import Image

    thumb = Image.open(work / a.slide / "thumbnail.png").convert("RGB")
    thumb.thumbnail((900, 900))
    thumb.save(out / "thumbnail.jpg", quality=80)  # a few hundred KB, not a PNG of 2 MB
    summary = {
        "slide": a.slide, "source": "TCGA-BRCA diagnostic slide (GDC, open access), region "
        "annotated by BCSS (CC0); this patient is not in the head's training slides",
        "region_base_px": region["region"], "base_mpp": region["base_mpp"],
        "slide_dimensions": region["slide_dimensions"],
        "tile_px": TILE_PX, "mpp": MPP, "grid_shape": res["grid_shape"],
        "encoder": {"name": timing["model"], "license": "MIT", "access": "open, ungated",
                    "kind": ENCODERS[timing["model"]]["kind"],
                    "tiles_per_s_cpu": timing["tiles_per_s_median"],
                    "peak_rss_gb": timing["peak_rss_gb"]},
        "head": {"kind": "logistic regression on frozen embeddings", "classes": classes,
                 "training_data": f"BCSS tiles from {len(metrics['train_slides'])} TCGA-BRCA "
                                  f"slides ({metrics['n_train_tiles']} tiles)",
                 "held_out": f"{len(metrics['test_slides'])} slides, {metrics['n_test_tiles']} "
                             "tiles, patient-disjoint",
                 "accuracy": metrics["accuracy"], "balanced_accuracy": metrics["balanced_accuracy"],
                 "per_class": metrics["per_class"], "confusion": metrics["confusion"],
                 "accuracy_below_cutoff": metrics["accuracy_below_cutoff"],
                 "accuracy_at_or_above_cutoff": metrics["accuracy_at_or_above_cutoff"],
                 "share_below_cutoff": metrics["share_below_cutoff"],
                 "not_learned": {"normal_breast": "too few labeled tiles in BCSS at this tile size",
                                 "dcis": "one BCSS slide only; cannot be held out"}},
        "analysis": res["summary"],
        "status": "implemented, experimentally validated on held-out BCSS slides only; not "
                  "reviewed by a pathologist",
    }
    json.dump(summary, open(out / "summary.json", "w"), indent=1)
    print(json.dumps(summary["analysis"], indent=1))


# --- count -----------------------------------------------------------------------------------

def cmd_count(a):
    import openslide
    from skimage.color import rgb2hsv

    rows = []
    for path in sorted(Path(a.slides).glob("*.svs")):
        s = openslide.OpenSlide(str(path))
        mpp = float(s.properties.get("openslide.mpp-x", 0.25))
        thumb = np.array(s.get_thumbnail((2048, 2048)).convert("RGB"))
        ds = s.dimensions[0] / thumb.shape[1]                   # base px per thumb px
        sat = rgb2hsv(thumb)[..., 1] * 255
        tissue = sat > 12  # the colon analyzer's measured saturation rule, placeholder here
        tile_base = TILE_PX * MPP / mpp
        tiles = tissue.sum() * ds ** 2 / tile_base ** 2
        rows.append({"slide": path.stem, "tissue_tiles_224px_0.5um": int(tiles),
                     "tissue_mm2": round(float(tissue.sum() * (ds * mpp / 1000) ** 2), 1)})
        print(rows[-1], flush=True)
    pd.DataFrame(rows).to_csv(Path(a.slides).parent / "tissue_tile_counts.csv", index=False)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tiles")
    t.add_argument("--slides", required=True)
    t.add_argument("--masks", required=True)
    t.add_argument("--bounds", required=True, help="BCSS meta/roiBounds.csv")
    t.add_argument("--out", required=True)
    e = sub.add_parser("embed")
    e.add_argument("--work", required=True)
    e.add_argument("--model", default="kaiko-ai/midnight")
    e.add_argument("--batch", type=int, default=8)
    e.add_argument("--threads", type=int, default=8)
    e.add_argument("--limit", type=int, default=0,
                   help="time this many tiles per slide, save nothing")
    tr = sub.add_parser("train")
    tr.add_argument("--work", required=True)
    tr.add_argument("--test", nargs="+", required=True)
    tr.add_argument("--classes", nargs="+", default=CLASSES)
    tr.add_argument("--C", type=float, default=0.1)
    r = sub.add_parser("result")
    r.add_argument("--work", required=True)
    r.add_argument("--slide", required=True)
    r.add_argument("--out", required=True)
    rq = sub.add_parser("requality")
    rq.add_argument("--work", required=True)
    c = sub.add_parser("count")
    c.add_argument("--slides", required=True)
    args = p.parse_args()
    a_threads = getattr(args, "threads", 8)
    {"tiles": cmd_tiles, "embed": cmd_embed, "train": cmd_train, "result": cmd_result,
     "count": cmd_count, "requality": cmd_requality}[args.cmd](args)

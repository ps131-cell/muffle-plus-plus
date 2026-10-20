"""Breast slide spike: BCSS tiles -> open encoder embeddings -> tissue head -> one slide result.

Runs where openslide, torch and transformers are installed (WSL on the Windows PC, or a Mac); the
app only reads the small result folder this writes. Subcommands, in order:

  python scripts/slide_spike.py tiles  --slides DIR --masks DIR --out WORK
      For every <slide>.svs with a <slide>.png BCSS mask (region at base resolution, bounds from
      meta/roiBounds.csv encoded in the file list --bounds): cut the labeled region into 224 px
      tiles at 0.5 µm/px, give each tile its majority BCSS class (purity >= 0.5, else "mixed"),
      measure texture (edges, structure, ink shares, blur) and save WORK/<slide>/tiles.csv,
      thumbnail.png and the 224 px tiles as a uint8 .npy stack (local only, never committed).
  python scripts/slide_spike.py embed  --work WORK [--model ID] [--tiles TILES] [--device auto]
      Embed every tile with one ENCODERS entry (--device auto: CUDA, then XPU, then CPU), report
      tiles/s, load and peak memory, save embeddings.npy per slide. --tiles TILES links the tiles
      of TILES/<slide>/ into WORK/<slide>/, so each encoder gets its own run folder. Gated models
      read HF_TOKEN from the environment or .env (never printed) and stop with a one-line message
      naming the click-through URL when it is missing.
  python scripts/slide_spike.py train  --work WORK --test SLIDE [SLIDE ...]
      Logistic regression on the training slides' pure tiles; accuracy per class on the held-out
      slides (patient-disjoint: one slide per patient in BCSS). Writes WORK/head.json (weights)
      and WORK/head_metrics.json.
  python scripts/slide_spike.py result --work WORK --slide SLIDE \
      --out app/workbenches/slides_example
      Score one held-out slide with the head and write the folder the workbench reads: tiles.json
      (positions, class probabilities, quality measures), thumbnail.jpg, summary.json. Only
      derived numbers on public TCGA tiles; no pixels beyond the thumbnail, no embeddings.
  python scripts/slide_spike.py requality --work WORK
      Recompute texture measures and quality verdicts from the saved tiles (after a rule change).
  python scripts/slide_spike.py compare --runs RUNS
      Markdown table of every encoder (license, gate, measured speed, held-out accuracy per class)
      from RUNS/<short name>/, with the commands for the rows still pending (docs/encoders.md).
  python scripts/slide_spike.py count --slides DIR
      Tissue tiles per whole slide (saturation mask on the thumbnail), to extrapolate the timing.
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

ROOT = Path(__file__).resolve().parents[1]
IMAGENET = {"mean": (0.485, 0.456, 0.406), "std": (0.229, 0.224, 0.225)}
OPENAI_CLIP = {"mean": (0.48145466, 0.4578275, 0.40821073),
               "std": (0.26862954, 0.26130258, 0.27577711)}

# Tile encoders by Hugging Face id (docs/encoders.md, docs/model_access.md; every one has a row in
# docs/registry.md). Tiles are already 224 px at 0.5 µm/px, so preprocessing is: resize to
# `size` if it is not 224, scale to [0, 1], normalize with `mean` / `std`. `loader` says how the
# weights load, `pool` which vector is the tile's embedding (cards read 2026-10-20). `gate` is the
# Hugging Face access step; `local_only` marks CC BY-NC-ND models: their embeddings, heads and
# results never leave this machine (`embed` and `result` refuse a path inside the repository).
ENCODERS = {
    # MIT, ungated. Pretrained on TCGA only (12k slides): TCGA-BRCA test slides were seen
    # without labels. ViT-g: ~0.19 tiles/s on this CPU, a GPU job for whole slides.
    "kaiko-ai/midnight": {
        "loader": "hf_auto", "pool": "cls+mean", "size": 224, "mean": (0.5, 0.5, 0.5),
        "std": (0.5, 0.5, 0.5), "params_m": 1137, "dim": 3072,
        "license": "MIT", "gate": "none", "local_only": False},
    # MIT, ungated. Card: research output, "any deployed use case ... is out of scope": the
    # hosted app shows precomputed results only and runs no encoder.
    "wisdomik/QuiltNet-B-32": {
        "loader": "hf_clip", "pool": "clip_proj", "size": 224, **OPENAI_CLIP, "params_m": 88,
        "dim": 512, "license": "MIT", "gate": "none", "local_only": False},
    # Health AI Developer Foundations terms (HAI-DEF): click-through, instant. Use restrictions
    # pass on to anyone given fine-tuned weights; "Clinical Use" includes research studies on
    # patients (ours are public TCGA slides). The HF release is a TensorFlow SavedModel (tf-keras,
    # saved_model.pb + variables/), loaded with tf.saved_model.load; input is [0, 1] RGB, no
    # normalization; output_0 is the 384-d embedding. Trained on TCGA only.
    "google/path-foundation": {
        "loader": "tf_savedmodel", "pool": "output_0", "size": 224, "mean": (0.0, 0.0, 0.0),
        "std": (1.0, 1.0, 1.0), "params_m": 22, "dim": 384, "needs": "tensorflow-cpu",
        "license": "HAI-DEF terms", "gate": "click-through (instant)", "local_only": False},
    # Apache-2.0; gate: share contact information (instant). Card: research use only, "not
    # intended to be used in clinical care", "any deployed use case ... is out of scope". The
    # tile encoder is a DINOv2-small ViT-S/16 (SwiGLU, LayerScale) whose architecture lives in the
    # prov-gigapath package; the arguments below copy its gigapath/tile_encoder.py so plain timm
    # loads pytorch_model.bin. The card resizes to 256 and centre-crops 224 for arbitrary images;
    # our tiles are already 224 px at 0.5 µm/px, so they go in as they are.
    "prov-gigapath/prov-gigapath-flash": {
        "loader": "timm_file", "arch": "vit_small_patch16_224", "pool": "pooled", "size": 224,
        **IMAGENET, "params_m": 22, "dim": 384,
        "timm_kwargs": {"img_size": 224, "patch_size": 16, "embed_dim": 384, "depth": 12,
                        "num_heads": 6, "mlp_ratio": 2048 / 384, "mlp_layer": "SwiGLUPacked",
                        "act_layer": "SiLU", "init_values": 1e-5, "num_classes": 0,
                        "global_pool": "token", "class_token": True, "reg_tokens": 0},
        "license": "Apache-2.0", "gate": "contact info (instant)", "local_only": False},
    # Apache-2.0; gate: contact information (instant). DINOv2 with registers in the repo's own
    # modeling code (trust_remote_code), pinned to the revision read on 2026-10-20. Preprocessing
    # from HistAI/hibou example.ipynb; embedding is pooler_output as in that notebook.
    "histai/hibou-b": {
        "loader": "hf_auto", "remote_code": True,
        "revision": "7fdc8cce365ebfd9e7e60ee6ee9a8d4d59388f3c", "pool": "pooler", "size": 224,
        "mean": (0.7068, 0.5755, 0.7220), "std": (0.1950, 0.2316, 0.1816), "params_m": 86,
        "dim": 768, "license": "Apache-2.0", "gate": "contact info (instant)",
        "local_only": False},
    "histai/hibou-L": {
        "loader": "hf_auto", "remote_code": True,
        "revision": "31a3b9fee16554c8552cb643d311733bce8faf7c", "pool": "pooler", "size": 224,
        "mean": (0.7068, 0.5755, 0.7220), "std": (0.1950, 0.2316, 0.1816), "params_m": 304,
        "dim": 1024, "license": "Apache-2.0", "gate": "contact info (instant)",
        "local_only": False},
    # Apache-2.0; gate: contact information (instant). Card: 224 px at 0.5 µm/px, its own
    # mean/std, 1536-d output from the timm model; no published validation (software citation).
    "bioptimus/H-optimus-0": {
        "loader": "timm", "pool": "pooled", "size": 224, "mean": (0.707223, 0.578729, 0.703617),
        "std": (0.211883, 0.230117, 0.177517), "params_m": 1100, "dim": 1536,
        "timm_kwargs": {"init_values": 1e-5, "dynamic_img_size": False},
        "license": "Apache-2.0", "gate": "contact info (instant)", "local_only": False},
    # Apache-2.0 plus "additional terms": the HF primary email must match an institutional email;
    # "not intended for use in medical diagnosis, treatment, or prevention of disease of real
    # patients". Embedding: class token and mean patch token concatenated (card), 2560-d.
    "paige-ai/Virchow": {
        "loader": "timm", "pool": "cls+mean", "size": 224, **IMAGENET, "params_m": 632,
        "dim": 2560, "timm_kwargs": {"mlp_layer": "SwiGLUPacked", "act_layer": "SiLU"},
        "license": "Apache-2.0 (+ card terms)", "gate": "institutional email (approval)",
        "local_only": False},
    # CC BY-NC-ND 4.0: "non-commercial, academic research purposes"; derivatives "include models
    # trained on outputs from the UNI 2 model or datasets created from" it; no distribution. Gate:
    # HF primary email must be institutional (@gmail etc. denied). LOCAL ONLY.
    "MahmoodLab/UNI2-h": {
        "loader": "timm", "pool": "pooled", "size": 224, **IMAGENET, "params_m": 681,
        "dim": 1536,
        "timm_kwargs": {"img_size": 224, "patch_size": 14, "depth": 24, "num_heads": 24,
                        "init_values": 1e-5, "embed_dim": 1536, "mlp_ratio": 2.66667 * 2,
                        "num_classes": 0, "no_embed_class": True, "mlp_layer": "SwiGLUPacked",
                        "act_layer": "SiLU", "reg_tokens": 8, "dynamic_img_size": True},
        "license": "CC BY-NC-ND 4.0", "gate": "institutional email (approval)",
        "local_only": True},
    # CC BY-NC-ND 4.0, same terms and gate as UNI2-h. Loads through the CONCH package (open_clip
    # fork): 448 px input, OpenAI CLIP mean/std (conch_ViT-B-16 config); embedding before the
    # projection head, as the card recommends for linear probes. LOCAL ONLY.
    "MahmoodLab/CONCH": {
        "loader": "conch", "pool": "conch_image", "size": 448, **OPENAI_CLIP, "params_m": 90,
        "dim": 512, "needs": "git+https://github.com/Mahmoodlab/CONCH.git",
        "license": "CC BY-NC-ND 4.0", "gate": "institutional email (approval)",
        "local_only": True},
}
LOCAL_ONLY = {name for name, spec in ENCODERS.items() if spec["local_only"]}


def require_access(name: str, env_file: Path = ROOT / ".env") -> None:
    """Exit with one line naming the click-through URL and HF_TOKEN when a gated model has no
    token. The token is read from the environment or `.env` (never printed); huggingface_hub
    picks HF_TOKEN up from the environment by itself."""
    if name not in ENCODERS:
        raise SystemExit(f"Unknown encoder {name}; known: {', '.join(ENCODERS)}")
    spec = ENCODERS[name]
    if spec["gate"] == "none":
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=False)
    except ImportError:
        pass
    if not os.environ.get("HF_TOKEN"):
        raise SystemExit(f"{name} is gated ({spec['gate']}): accept its terms at "
                         f"https://huggingface.co/{name}, then set HF_TOKEN=<read token from "
                         "https://huggingface.co/settings/tokens> in .env or the environment.")


def guard_local(name: str, path: Path) -> None:
    """A CC BY-NC-ND encoder's embeddings and results stay outside the (public) repository."""
    path = Path(path).resolve()
    if name in LOCAL_ONLY and (path == ROOT or ROOT in path.parents):
        raise SystemExit(f"{name} is {ENCODERS[name]['license']}: local only; its embeddings and "
                         f"results never go into the repository (refused: {path}; app/ never).")


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

def pick_device(want: str) -> str:
    """`auto`: CUDA, then Intel XPU (the Arc iGPU), then CPU."""
    import torch

    if want != "auto":
        return want
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch, "xpu") and torch.xpu.is_available():
        return "xpu"
    return "cpu"


def _timm_kwargs(spec: dict) -> dict:
    import timm
    import torch

    named = {"SwiGLUPacked": timm.layers.SwiGLUPacked, "SiLU": torch.nn.SiLU}
    return {k: named.get(v, v) if isinstance(v, str) else v
            for k, v in spec.get("timm_kwargs", {}).items()}


def load_encoder(name: str, device: str = "cpu"):
    """Load one ENCODERS entry. A gated model without access, or a missing extra package, ends
    with a one-line message instead of a traceback."""
    require_access(name)
    spec = ENCODERS[name]
    try:
        if spec["loader"] == "tf_savedmodel":
            import tensorflow as tf
            from huggingface_hub import snapshot_download

            return tf.saved_model.load(snapshot_download(name)), spec, "tf"
        import torch

        torch.set_num_threads(a_threads)
        if spec["loader"] == "hf_clip":
            from transformers import CLIPModel
            model = CLIPModel.from_pretrained(name)
        elif spec["loader"] == "hf_auto":
            from transformers import AutoModel
            model = AutoModel.from_pretrained(name, revision=spec.get("revision"),
                                              trust_remote_code=spec.get("remote_code", False))
        elif spec["loader"] == "timm":
            import timm
            model = timm.create_model(f"hf-hub:{name}", pretrained=True, **_timm_kwargs(spec))
        elif spec["loader"] == "timm_file":
            import timm
            from huggingface_hub import hf_hub_download
            model = timm.create_model(spec["arch"], pretrained=False, **_timm_kwargs(spec))
            state = torch.load(hf_hub_download(name, "pytorch_model.bin"), map_location="cpu")
            missing, _ = model.load_state_dict(state.get("model", state), strict=False)
            if missing:
                raise SystemExit(f"{name}: weights do not fit {spec['arch']} "
                                 f"(missing {missing[:3]})")
        elif spec["loader"] == "conch":
            from conch.open_clip_custom import create_model_from_pretrained
            model, _ = create_model_from_pretrained("conch_ViT-B-16", f"hf_hub:{name}",
                                                    hf_auth_token=os.environ.get("HF_TOKEN"))
        else:
            raise SystemExit(f"{name}: unknown loader {spec['loader']}")
    except ImportError as e:
        raise SystemExit(f"{name} needs an extra package ({e.name}): "
                         f"pip install {spec.get('needs', e.name)}") from None
    except OSError as e:  # transformers / huggingface_hub wrap 401, 403 and gated-repo errors
        if spec["gate"] != "none" and any(s in str(e) for s in ("gated", "401", "403", "access")):
            raise SystemExit(f"{name}: Hugging Face refused the download; open "
                             f"https://huggingface.co/{name} and check it says access is granted "
                             "to the account whose token is in HF_TOKEN.") from None
        raise
    return model.eval().to(device), spec, device


def embed_batch(encoder, rgb: np.ndarray) -> np.ndarray:
    """Embed a uint8 (n, 224, 224, 3) batch with the entry's preprocessing and pooling."""
    model, spec, device = encoder
    x = rgb.astype(np.float32) / 255
    x = (x - np.array(spec["mean"], np.float32)) / np.array(spec["std"], np.float32)
    if device == "tf":
        import tensorflow as tf

        return model.signatures["serving_default"](tf.constant(x))["output_0"].numpy()
    import torch
    import torch.nn.functional as F

    x = torch.from_numpy(x).permute(0, 3, 1, 2).to(device)
    if spec["size"] != x.shape[-1]:
        x = F.interpolate(x, size=spec["size"], mode="bicubic", align_corners=False)
    with torch.inference_mode(), torch.autocast(device_type="cuda", dtype=torch.float16,
                                                enabled=device == "cuda"):
        pool = spec["pool"]
        if pool == "clip_proj":
            f = model.visual_projection(model.vision_model(pixel_values=x).pooler_output)
        elif pool == "pooler":
            f = model(pixel_values=x).pooler_output
        elif pool == "conch_image":
            f = model.encode_image(x, proj_contrast=False, normalize=False)
        elif pool == "pooled":  # timm with num_classes=0: the pooled class token
            f = model(x)
        elif pool == "cls+mean" and spec["loader"] == "hf_auto":
            h = model(pixel_values=x).last_hidden_state
            f = torch.cat([h[:, 0], h[:, 1:].mean(1)], -1)
        elif pool == "cls+mean":  # timm: tokens after the prefix (class and register) tokens
            h = model.forward_features(x)
            f = torch.cat([h[:, 0], h[:, model.num_prefix_tokens:].mean(1)], -1)
        else:
            raise ValueError(f"unknown pool {pool}")
    return f.float().cpu().numpy()


def embed_stack(encoder, rgb: np.ndarray, batch: int = 8) -> tuple[np.ndarray, float]:
    """Tile embeddings for a stack and tiles per second."""
    t = time.time()
    out = [embed_batch(encoder, rgb[i:i + batch]) for i in range(0, len(rgb), batch)]
    return np.concatenate(out).astype(np.float32), len(rgb) / (time.time() - t)


def link_tiles(src: Path, work: Path) -> None:
    """Point WORK/<slide>/ at the tiles in SRC/<slide>/ (symlinks), so each encoder gets its own
    run folder and embeddings.npy without copying the tiles."""
    for folder in sorted(src.iterdir()):
        if not (folder / "tiles_rgb.npy").exists():
            continue
        dst = work / folder.name
        dst.mkdir(parents=True, exist_ok=True)
        for f in folder.iterdir():
            if f.name != "embeddings.npy" and not (dst / f.name).exists():
                (dst / f.name).symlink_to(f.resolve())


def cmd_embed(a):
    import resource

    guard_local(a.model, Path(a.work))
    if a.tiles:
        link_tiles(Path(a.tiles), Path(a.work))
    encoder = load_encoder(a.model, pick_device(a.device))
    load_start = os.getloadavg()[0]
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
    timing = {"model": a.model, "device": encoder[2], "threads": a_threads, "batch": a.batch,
              "nice": os.nice(0), "load_1min_start": round(load_start, 2),
              "load_1min_end": round(os.getloadavg()[0], 2),
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
    timing = json.load(open(work / "timing.json"))
    guard_local(timing["model"], Path(a.out))
    spec = ENCODERS[timing["model"]]
    head = json.load(open(work / "head.json"))
    metrics = json.load(open(work / "head_metrics.json"))
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
    tiles.to_json(out / "tiles.json", orient="records")  # .csv is git-ignored by repo rule
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
        "encoder": {"name": timing["model"], "license": spec["license"],
                    "access": "open, ungated" if spec["gate"] == "none"
                    else f"Hugging Face, gated: {spec['gate']}",
                    "kind": spec["loader"],
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


# --- compare ---------------------------------------------------------------------------------

HEAD_CLASSES = CLASSES[:5]  # normal breast and DCIS have too few BCSS tiles for the head


def run_dir(name: str) -> str:
    return name.split("/")[-1]


def compare_table(runs: Path, tiles: str = "TILES", test: str = "SLIDE ...") -> str:
    """Markdown table of every ENCODERS entry, filled from RUNS/<short name>/timing.json and
    head_metrics.json; entries without a head get the commands that make one."""
    cols = ["Encoder", "License", "Gate", "Params (M)", "Tiles/s measured (device, threads, "
            "1-min load)", "Min per 15k-tile slide", "Held-out accuracy (balanced)",
            *HEAD_CLASSES]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    todo = []
    for name, spec in ENCODERS.items():
        run = runs / run_dir(name)
        timing = json.load(open(run / "timing.json")) if (run / "timing.json").exists() else {}
        metrics = (json.load(open(run / "head_metrics.json"))
                   if (run / "head_metrics.json").exists() else {})
        rate = timing.get("tiles_per_s_median")
        load = timing.get("load_1min_start", "not recorded")
        if "load_1min_end" in timing:
            load = f"{load} → {timing['load_1min_end']}"
        speed = (f"{rate:g} ({timing.get('device', 'cpu')}, {timing['threads']} threads, load "
                 f"{load})" if rate else "pending access")
        minutes = f"{15000 / rate / 60:,.0f}" if rate else "–"
        acc = (f"{metrics['accuracy']:.3f} ({metrics['balanced_accuracy']:.3f})" if metrics
               else "pending access" if spec["gate"] != "none" else "not run (CPU too slow)")
        per = [f"{metrics['per_class'][c]['recall']:.2f}" if metrics
               and metrics["per_class"].get(c, {}).get("recall") is not None else "–"
               for c in HEAD_CLASSES]
        lic = spec["license"] + (", **local only**" if spec["local_only"] else "")
        lines.append(f"| `{name}` | {lic} | {spec['gate']} | {spec['params_m']:,} | {speed} | "
                     f"{minutes} | {acc} | " + " | ".join(per) + " |")
        if not metrics:
            env = "HF_TOKEN=… " if spec["gate"] != "none" else ""
            work = f"~/muffle-encoders/runs/{run_dir(name)}"
            todo.append(f"- `{name}`:\n  `{env}python scripts/slide_spike.py embed --tiles "
                        f"{tiles} --work {work} --model {name} && python scripts/slide_spike.py "
                        f"train --work {work} --test {test}`")
    return "\n".join(lines) + "\n\nTo fill a pending row (from the clone, venv active):\n\n" + \
        "\n".join(todo)


def cmd_compare(a):
    print(compare_table(Path(a.runs), a.tiles, " ".join(a.test)))


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
    e.add_argument("--model", default="kaiko-ai/midnight", choices=list(ENCODERS))
    e.add_argument("--tiles", help="read tiles from TILES/<slide>/ (linked into WORK/<slide>/)")
    e.add_argument("--device", default="auto", help="auto (cuda, then xpu, then cpu), or name one")
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
    cp = sub.add_parser("compare")
    cp.add_argument("--runs", required=True, help="one folder per encoder: RUNS/<short name>/")
    cp.add_argument("--tiles", default="~/muffle-encoders/work", help="shown in the commands")
    cp.add_argument("--test", nargs="+", default=["TCGA-C8-A26X-DX1", "TCGA-C8-A26Y-DX1",
                                                  "TCGA-EW-A1OV-DX1"])
    args = p.parse_args()
    a_threads = getattr(args, "threads", 8)
    {"tiles": cmd_tiles, "embed": cmd_embed, "train": cmd_train, "result": cmd_result,
     "count": cmd_count, "requality": cmd_requality, "compare": cmd_compare}[args.cmd](args)

"""Deep Zoom (DZI) pyramids of the patient's own diagnostic sections for the slide viewer
(docs/pathology.md §7).

Runs where openslide is installed (WSL on the Windows PC). The pyramids are JPEG tiles of
open-access TCGA sections at about 1 µm/px; they are published as one zip per section on the
release ``slide-tiles-v1`` and never committed to this repository. The app downloads a
section's zip the first time its viewer opens (``app/workbenches/slide_viewer.py``).

  python scripts/slide_pyramid.py build --slide SLIDES/TCGA-AN-A0AS-DX1.svs --out OUT \
      [--mpp 1.0] [--quality 80] [--workers 3]
      OUT/<slide>/<slide>.dzi and <slide>_files/<level>/<col>_<row>.jpeg: the scanner's own
      level nearest --mpp (the 4× level of a 40× scan: 0.99–1.01 µm/px) and every halving
      below it, 254 px tiles with a 1 px overlap (256 px JPEGs; bare glass written flat),
      OUT/<slide>/pyramid.json
      (size, µm per pixel, levels, tiles, bytes, time) and OUT/<slide>.zip (stored: JPEGs
      don't shrink)
  python scripts/slide_pyramid.py manifest --out OUT \
      --into app/workbenches/slides_results/pyramids.json
      collects every pyramid.json with its zip's size and SHA-256 (the app checks downloads
      against it)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
from muffle.workbench.viewer import OVERLAP, TILE, dz_levels, level_drop  # noqa: E402

RELEASE = "slide-tiles-v1"
GLASS_STD = 2.5  # design: a tile this flat is bare glass (tissue, fat included, is far above)
DZI = ('<?xml version="1.0" encoding="UTF-8"?>\n<Image xmlns="http://schemas.microsoft.com/'
       'deepzoom/2008" Format="jpeg" Overlap="{o}" TileSize="{t}"><Size Width="{w}" '
       'Height="{h}"/></Image>\n')


def uptime() -> str:
    try:
        return "load average %.1f %.1f %.1f" % os.getloadavg()
    except OSError:
        return "load average unknown"


_dz = None


def _open(slide_path: str) -> None:
    global _dz
    import openslide
    from openslide.deepzoom import DeepZoomGenerator

    _dz = DeepZoomGenerator(openslide.OpenSlide(slide_path), tile_size=TILE, overlap=OVERLAP,
                            limit_bounds=False)


def _row(job: tuple[int, int, str, int]) -> tuple[int, int, int]:
    """One row of tiles of one level; a featureless tile (bare glass: grey-level standard
    deviation under GLASS_STD) is written flat in its mean colour, which keeps the look at a
    tenth of the bytes. Returns (level, bytes, glass tiles)."""
    import numpy as np
    from PIL import Image

    level, row, folder, quality = job
    size = glass = 0
    for col in range(_dz.level_tiles[level][0]):
        tile = _dz.get_tile(level, (col, row))
        a = np.asarray(tile)
        if a.mean(axis=2).std() < GLASS_STD:
            tile = Image.new("RGB", tile.size, tuple(int(v) for v in a.reshape(-1, 3).mean(0)))
            glass += 1
        path = Path(folder) / str(level) / f"{col}_{row}.jpeg"
        tile.save(path, quality=quality)
        size += path.stat().st_size
    return level, size, glass


def build(slide_path: Path, out: Path, mpp: float, quality: int, workers: int) -> dict:
    from multiprocessing import Pool

    import openslide

    name = slide_path.stem
    base_mpp = float(openslide.OpenSlide(str(slide_path)).properties["openslide.mpp-x"])
    drop = level_drop(base_mpp, mpp)
    _open(str(slide_path))
    top = _dz.level_count - 1 - drop
    width, height = _dz.level_dimensions[top]
    assert dz_levels(width, height) == list(_dz.level_dimensions[:top + 1])
    folder = out / name
    files = folder / f"{name}_files"
    jobs = []
    for level in range(top + 1):
        (files / str(level)).mkdir(parents=True, exist_ok=True)
        jobs += [(level, row, str(files), quality) for row in range(_dz.level_tiles[level][1])]
    t0, start = time.time(), uptime()
    by_level = {lv: {"tiles": c * r, "bytes": 0, "glass": 0}
                for lv, (c, r) in enumerate(_dz.level_tiles[:top + 1])}
    with Pool(workers, initializer=_open, initargs=(str(slide_path),)) as pool:
        for level, size, glass in pool.imap_unordered(_row, jobs[::-1], chunksize=4):
            by_level[level]["bytes"] += size
            by_level[level]["glass"] += glass
    (folder / f"{name}.dzi").write_text(DZI.format(o=OVERLAP, t=TILE, w=width, h=height))
    info = {"slide": name, "width": width, "height": height, "mpp": round(base_mpp * 2 ** drop, 4),
            "base_mpp": base_mpp, "downsample": 2 ** drop, "levels": top + 1, "tile_size": TILE,
            "overlap": OVERLAP, "format": "jpeg", "quality": quality,
            "tiles": sum(v["tiles"] for v in by_level.values()),
            "glass_tiles": sum(v["glass"] for v in by_level.values()),
            "bytes": sum(v["bytes"] for v in by_level.values()), "by_level": by_level,
            "seconds": round(time.time() - t0, 1), "uptime_at_start": start,
            "uptime_at_end": uptime()}
    (folder / "pyramid.json").write_text(json.dumps(info, indent=1))
    with zipfile.ZipFile(out / f"{name}.zip", "w", zipfile.ZIP_STORED) as z:
        for p in sorted(folder.rglob("*")):
            if p.is_file():
                z.write(p, p.relative_to(folder).as_posix())
    return info


def manifest(out: Path) -> dict:
    slides = {}
    for info_path in sorted(out.glob("*/pyramid.json")):
        info = json.loads(info_path.read_text())
        zpath = out / f"{info['slide']}.zip"
        digest = hashlib.sha256(zpath.read_bytes()).hexdigest()
        slides[info["slide"]] = {k: info[k] for k in (
            "width", "height", "mpp", "downsample", "levels", "tile_size", "overlap", "format",
            "quality", "tiles", "glass_tiles", "bytes", "seconds", "uptime_at_start")} | {
            "zip": zpath.name, "zip_bytes": zpath.stat().st_size, "sha256": digest}
    return {"release": RELEASE, "source": "TCGA-BRCA diagnostic slides (GDC open access); "
            "JPEG Deep Zoom pyramids at about 1 µm/px", "slides": slides}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--slide", required=True)
    b.add_argument("--out", required=True)
    b.add_argument("--mpp", type=float, default=1.0)
    b.add_argument("--quality", type=int, default=80)
    b.add_argument("--workers", type=int, default=3)
    m = sub.add_parser("manifest")
    m.add_argument("--out", required=True)
    m.add_argument("--into", required=True)
    a = p.parse_args()
    if a.cmd == "build":
        print(json.dumps(build(Path(a.slide), Path(a.out), a.mpp, a.quality,
                                a.workers), indent=1))
    else:
        Path(a.into).write_text(json.dumps(manifest(Path(a.out)), indent=1) + "\n")

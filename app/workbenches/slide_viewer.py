"""The slide viewer: pan and zoom over the patient's own diagnostic section with the analysis
drawn on the tissue, from overview to region to tile to cells (docs/pathology.md §7).

A Streamlit component (``slide_viewer_frontend/``: OpenSeadragon 6.1.1, BSD-3-Clause, and plain
JavaScript speaking the component protocol; no build step). Each section's Deep Zoom pyramid
(``scripts/slide_pyramid.py``: JPEG tiles of the open-access TCGA section at about 1 µm/px) is a
zip on the release named in ``slides_results/pyramids.json``. The first time a section's viewer
opens, the app downloads that zip, checks its SHA-256 and unzips it into
``app/static/slides/<slide>/``, which Streamlit serves (``enableStaticServing`` in
``.streamlit/config.toml``); the analysis layers (``muffle.workbench.viewer.overlay``) are
written next to the tiles as one JSON file. ``MUFFLE_SLIDE_TILES`` points at another folder of
zips (a URL, or ``file://`` for local work) or switches downloads off (``off``). When a
pyramid can't be had, ``source`` says why and the page shows its tile map instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from muffle.workbench import viewer

APP = Path(__file__).resolve().parents[1]
STATIC = APP / "static" / "slides"
RESULTS = APP / "workbenches" / "slides_results"
RELEASES = "https://github.com/ps131-cell/muffle-plus-plus/releases/download"
OFF = {"off", "0", "no", "false"}
_component = components.declare_component(
    "slide_viewer", path=str(Path(__file__).with_name("slide_viewer_frontend")))
_lock = threading.Lock()


def manifest() -> dict:
    path = RESULTS / "pyramids.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"slides": {}}


def ensure(slide: str) -> str:
    """'' when the section's pyramid is served from app/static/slides/<slide>/ (downloading it
    on first use), otherwise the reason it isn't."""
    m = manifest()
    entry = m["slides"].get(slide)
    if not entry:
        return "no tile pyramid has been built for this section"
    if (STATIC / slide / f"{slide}.dzi").exists():
        return ""
    if not st.get_option("server.enableStaticServing"):
        return "static file serving is switched off on this server"
    base = os.getenv("MUFFLE_SLIDE_TILES") or f"{RELEASES}/{m['release']}"
    if base.strip().lower() in OFF:
        return "tile downloads are switched off on this server"
    with st.spinner(f"Fetching the section's tiles once ({entry['zip_bytes'] / 1e6:.0f} MB)…"):
        return _download(slide, base.rstrip("/"), entry["sha256"])


@st.cache_resource(show_spinner=False, ttl=600)  # a failure is retried after 10 minutes
def _download(slide: str, base: str, sha256: str) -> str:
    with _lock:
        if (STATIC / slide / f"{slide}.dzi").exists():
            return ""
        STATIC.mkdir(parents=True, exist_ok=True)
        zpath, tmp = STATIC / f".{slide}.zip", STATIC / f".{slide}.unzip"
        try:
            with urllib.request.urlopen(f"{base}/{slide}.zip", timeout=60) as r, \
                    open(zpath, "wb") as f:
                shutil.copyfileobj(r, f, 1 << 20)  # streamed: a big section never sits in memory
            digest = hashlib.sha256()
            with open(zpath, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    digest.update(block)
            if digest.hexdigest() != sha256:
                return "the downloaded tiles do not match their checksum"
            shutil.rmtree(tmp, ignore_errors=True)
            with zipfile.ZipFile(zpath) as z:
                z.extractall(tmp)
            shutil.rmtree(STATIC / slide, ignore_errors=True)
            tmp.replace(STATIC / slide)
            return ""
        except Exception as e:  # offline, release missing, disk full: the page falls back
            return f"the section's tiles could not be fetched ({type(e).__name__})"
        finally:
            zpath.unlink(missing_ok=True)
            shutil.rmtree(tmp, ignore_errors=True)


@st.cache_data(show_spinner=False, max_entries=32)
def _overlay(slide: str, stamp: str) -> str:
    """Writes a section's analysis layers next to its tiles; returns the file name (its content
    hash, so a browser never draws an old version)."""
    from workbenches.slides import scored  # the page module (imported by now) and its cache

    result, res, _ = scored(slide)
    classes = result["meta"]["head"]["classes"]
    text = json.dumps(viewer.overlay(res, classes, viewer.cells_frame(result["nuclei"])),
                      separators=(",", ":"))
    name = f"overlay-{hashlib.sha1(text.encode()).hexdigest()[:12]}.json"
    (STATIC / slide / name).write_text(text, encoding="utf-8")
    return name


def source(slide: str, label: str | None = None) -> dict | str:
    """What the viewer needs to show a section, or the reason it can't (a string)."""
    problem = ensure(slide)
    if problem:
        return problem
    entry = manifest()["slides"][slide]
    folder = RESULTS / slide
    meta = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    stamp = "-".join(str((folder / f).stat().st_mtime_ns) for f in
                     ("tiles.json", "nuclei.json", "summary.json") if (folder / f).exists())
    name = _overlay(slide, stamp)
    if not (STATIC / slide / name).exists():  # the folder was replaced since
        _overlay.clear()
        name = _overlay(slide, stamp)
    scored = meta.get("scored", {})
    return {"slide": slide, "label": label or slide,
            "tiles": f"app/static/slides/{slide}/{slide}_files/",
            "overlay": f"app/static/slides/{slide}/{name}",
            **{k: entry[k] for k in ("width", "height", "tile_size", "overlap", "format", "mpp")},
            "frame": viewer.tile_frame(meta, entry),
            "window": scored.get("mode") if scored.get("window_side_tiles") else None}


def show(sources: list[dict], key: str, goto: dict | None = None, height: int = 620,
         on_change=None) -> dict | None:
    """The viewer for one section, or several side by side with pan and zoom linked in µm.
    Returns its last event: a click ``{slide, tile, nonce}`` (also n / p and "jump to"), or
    ``{slide, failed, nonce}`` when the browser could not load the tiles; None before any."""
    return _component(sources=sources, goto=goto, height=height, key=key, default=None,
                      on_change=on_change)

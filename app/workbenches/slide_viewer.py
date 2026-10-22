"""The slide viewer: pan and zoom over the patient's own diagnostic section with the analysis
drawn on the tissue, from overview to region to tile to cells (docs/pathology.md §7).

A Streamlit component (``slide_viewer_frontend/``: OpenSeadragon 6.1.1, BSD-3-Clause, and plain
JavaScript speaking the component protocol; no build step). Each section's Deep Zoom pyramid
(``scripts/slide_pyramid.py``: JPEG tiles of the open-access TCGA section at about 1 µm/px) is a
zip on the release named in ``slides_results/pyramids.json``. The first time a section's viewer
opens, the app downloads that zip (a progress bar counts the megabytes), checks its SHA-256
and unzips it into ``app/static/slides/<slide>/``, which Streamlit serves
(``enableStaticServing`` in ``.streamlit/config.toml``); the analysis layers
(``muffle.workbench.viewer.overlay``) are
written next to the tiles as one JSON file. Streamlit reads that setting when the server
starts, so a server that has not restarted since (a hot-updated deployment) or was started
without the config unzips into the component's own folder instead, which Streamlit serves
with the component. ``MUFFLE_SLIDE_TILES`` points at another folder of zips (a URL, or
``file://`` for local work) or switches downloads off (``off``). When a pyramid can't be had,
``source`` says why and the page shows its tile map instead.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import threading
import time
import urllib.request
import zipfile
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from muffle.workbench import viewer

APP = Path(__file__).resolve().parents[1]
FRONTEND = Path(__file__).with_name("slide_viewer_frontend")
STATIC = APP / "static" / "slides"          # served at /app/static/slides/
FALLBACK = FRONTEND / "static" / "slides"   # served with the component
RESULTS = APP / "workbenches" / "slides_results"
RELEASES = "https://github.com/ps131-cell/muffle-plus-plus/releases/download"
OFF = {"off", "0", "no", "false"}
_component = components.declare_component("slide_viewer", path=str(FRONTEND))
_lock = threading.Lock()


def manifest() -> dict:
    path = RESULTS / "pyramids.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"slides": {}}


def served() -> tuple[Path, str]:
    """Where sections are unpacked, and that folder's URL from the viewer's page."""
    if st.get_option("server.enableStaticServing"):
        return STATIC, "../../app/static/slides"
    return FALLBACK, "static/slides"


def ensure(slide: str) -> str:
    """'' when the section's pyramid is unpacked where the server serves it (downloading it on
    first use, with a progress bar in megabytes), otherwise the reason it isn't. A failed
    download is retried after ``RETRY_S`` seconds."""
    m = manifest()
    entry = m["slides"].get(slide)
    if not entry:
        return "no tile pyramid has been built for this section"
    root, _ = served()
    if (root / slide / f"{slide}.dzi").exists():
        return ""
    base = os.getenv("MUFFLE_SLIDE_TILES") or f"{RELEASES}/{m['release']}"
    if base.strip().lower() in OFF:
        return "tile downloads are switched off on this server"
    when, why = _failed.get(slide, (0.0, ""))
    if why and time.time() - when < RETRY_S:
        return why
    total = entry["zip_bytes"]
    bar = st.progress(0.0, text=f"Fetching this section's tiles, once for this server: 0 of "
                                f"{total / 1e6:.0f} MB")

    def progress(done: int, text: str | None = None) -> None:
        bar.progress(min(done / total, 1.0), text=text or (
            f"Fetching this section's tiles, once for this server: {done / 1e6:.0f} of "
            f"{total / 1e6:.0f} MB"))

    why = _download(slide, base.rstrip("/"), entry["sha256"], str(root), progress)
    bar.empty()
    if why:
        _failed[slide] = (time.time(), why)
    return why


RETRY_S = 600  # a failed download is tried again after 10 minutes
_failed: dict[str, tuple[float, str]] = {}  # slide -> (when, why) of its last failed download


def _download(slide: str, base: str, sha256: str, root: str, progress=None) -> str:
    """Download, check and unpack one section's pyramid; '' or the reason it failed.
    ``progress(bytes done, text=None)`` follows the transfer."""
    root = Path(root)
    with _lock:
        if (root / slide / f"{slide}.dzi").exists():  # another session fetched it meanwhile
            return ""
        root.mkdir(parents=True, exist_ok=True)
        zpath, tmp = root / f".{slide}.zip", root / f".{slide}.unzip"
        try:
            with urllib.request.urlopen(f"{base}/{slide}.zip", timeout=60) as r, \
                    open(zpath, "wb") as f:
                done = 0
                while block := r.read(1 << 20):  # streamed: a big section never sits in memory
                    f.write(block)
                    done += len(block)
                    if progress:
                        progress(done)
            if progress:
                progress(done, "Checking and unpacking the tiles…")
            digest = hashlib.sha256()
            with open(zpath, "rb") as f:
                for block in iter(lambda: f.read(1 << 20), b""):
                    digest.update(block)
            if digest.hexdigest() != sha256:
                return "the downloaded tiles do not match their checksum"
            shutil.rmtree(tmp, ignore_errors=True)
            with zipfile.ZipFile(zpath) as z:
                z.extractall(tmp)
            shutil.rmtree(root / slide, ignore_errors=True)
            tmp.replace(root / slide)
            return ""
        except Exception as e:  # offline, release missing, disk full: the page falls back
            return f"the section's tiles could not be fetched ({type(e).__name__})"
        finally:
            zpath.unlink(missing_ok=True)
            shutil.rmtree(tmp, ignore_errors=True)


@st.cache_data(show_spinner=False, max_entries=32)
def _overlay(slide: str, stamp: str, root: str) -> str:
    """Writes a section's analysis layers next to its tiles; returns the file name (its content
    hash, so a browser never draws an old version)."""
    from workbenches.slides import scored  # the page module (imported by now) and its cache

    result, res, _ = scored(slide)
    classes = result["meta"]["head"]["classes"]
    text = json.dumps(viewer.overlay(res, classes, viewer.cells_frame(result["nuclei"])),
                      separators=(",", ":"))
    name = f"overlay-{hashlib.sha1(text.encode()).hexdigest()[:12]}.json"
    (Path(root) / slide / name).write_text(text, encoding="utf-8")
    return name


def source(slide: str, label: str | None = None) -> dict | str:
    """What the viewer needs to show a section, or the reason it can't (a string)."""
    problem = ensure(slide)
    if problem:
        return problem
    entry = manifest()["slides"][slide]
    root, url = served()
    folder = RESULTS / slide
    meta = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    stamp = "-".join(str((folder / f).stat().st_mtime_ns) for f in
                     ("tiles.json", "nuclei.json", "summary.json") if (folder / f).exists())
    name = _overlay(slide, stamp, str(root))
    if not (root / slide / name).exists():  # the folder was replaced since
        _overlay.clear()
        name = _overlay(slide, stamp, str(root))
    scored = meta.get("scored", {})
    return {"slide": slide, "label": label or slide,
            "tiles": f"{url}/{slide}/{slide}_files/", "overlay": f"{url}/{slide}/{name}",
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

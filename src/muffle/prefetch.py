"""Downloads started early, for a faster first screen in the hosted setup: a fresh container has
neither the release bundle nor CIViC's table, and the app used to fetch them one after the other
before the patient list. ``start`` fetches each in a background thread while the app's libraries
import; the loader (``muffle.demo.fetch_bundle``, ``muffle.report.civic.load_table``) calls
``wait`` first and finds the file there. If a download fails, the loader fetches it again as
before and reports what goes wrong. Nothing here imports torch or pandas.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import threading
import urllib.request
from pathlib import Path

_RUNNING: dict[str, threading.Thread] = {}


def bundle_path(url: str) -> Path:
    """Where a downloaded bundle is kept: one file per URL, so a new release isn't masked by the
    previous release's file."""
    name = f"muffle_bundle_{hashlib.sha1(url.encode()).hexdigest()[:12]}.pt"
    return Path(tempfile.gettempdir()) / name


def _key(dest) -> str:
    return os.path.abspath(dest)


def _get(url: str, dest: Path) -> None:
    part = dest.with_name(f"{dest.name}.{os.getpid()}-{threading.get_ident()}.part")  # its own
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(url, timeout=120) as r, open(part, "wb") as f:
            shutil.copyfileobj(r, f)
        part.replace(dest)
    except Exception:  # noqa: BLE001 (the loader downloads it again and says what failed)
        part.unlink(missing_ok=True)


def start(url: str, dest: str | Path) -> None:
    """Fetch ``url`` to ``dest`` in the background, unless it is there or on its way."""
    dest = Path(dest)
    if dest.exists() or _key(dest) in _RUNNING:
        return
    t = threading.Thread(target=_get, args=(url, dest), daemon=True, name=f"fetch {dest.name}")
    _RUNNING[_key(dest)] = t
    t.start()


def wait(dest: str | Path) -> None:
    """Return once a download of ``dest`` started here has ended (at once if none was)."""
    t = _RUNNING.get(_key(dest))
    if t is not None:
        t.join()

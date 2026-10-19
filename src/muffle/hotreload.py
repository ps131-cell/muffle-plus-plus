"""Keep a hot-updated Streamlit process in step with the code on disk.

Streamlit Community Cloud pulls a new commit and re-runs the entry file, but the modules the
process already imported (app/charts.py, src/muffle) stay as they were, so an entry file that
uses a name added in the same commit fails until the app is rebooted (twice on 2026-10-19: an
AttributeError on ``charts.risk_timeline``, then an ImportError on ``muffle.demo.evidence_lookup``).
The app hashes the project's source files on every run and, when the hash differs from the one
this process last ran, drops those modules (the next import statement re-executes them) and
clears Streamlit's caches, whose objects were built by the old code.
"""

from __future__ import annotations

import hashlib
import sys
from collections.abc import Iterable
from pathlib import Path


def source_digest(roots: Iterable[Path], patterns: tuple[str, ...] = ("*.py", "*.json")) -> str:
    """A hash of every matching file's path, size and modification time under ``roots``."""
    h = hashlib.sha1()
    for root in roots:
        if not root.is_dir():
            continue
        for pattern in patterns:
            for p in sorted(root.rglob(pattern)):
                s = p.stat()
                h.update(f"{p.relative_to(root).as_posix()}:{s.st_size}:{s.st_mtime_ns}\n".encode())
    return h.hexdigest()


def purge_modules(prefixes: tuple[str, ...]) -> list[str]:
    """Remove the modules named by ``prefixes``, and their submodules, from ``sys.modules`` so
    the next import re-executes them from disk. Returns the names removed."""
    names = [m for m in sys.modules if any(m == p or m.startswith(p + ".") for p in prefixes)]
    for m in names:
        del sys.modules[m]
    return names

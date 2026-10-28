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
import os
import sys
from collections.abc import Iterable
from fnmatch import fnmatch
from pathlib import Path


def source_digest(roots: Iterable[Path], patterns: tuple[str, ...] = ("*.py", "*.json"),
                  skip: tuple[str, ...] = ("static", "__pycache__")) -> str:
    """A hash of every matching file's path, size and modification time under ``roots``.
    Folders named in ``skip`` are not entered: ``app/static`` holds the slide viewer's tiles and
    overlay files, written while the app runs; walking them on every run would be slow, and a
    new file there would clear every cache as if the code had changed. It runs on every rerun,
    so it reads directory entries (``os.scandir``) and stats only the matching files, as
    ``os.walk`` would without following links to folders."""
    plain = all(p.startswith("*.") and not any(c in p[2:] for c in "*?[") for p in patterns)
    suffixes = tuple(p[1:] for p in patterns)
    h = hashlib.sha1()
    for root in roots:
        if not os.path.isdir(root):
            continue
        found = []
        folders = [("", os.fspath(root))]
        while folders:
            rel, folder = folders.pop()
            with os.scandir(folder) as entries:
                for e in entries:
                    if e.is_dir():
                        if e.name not in skip and not e.is_symlink():
                            folders.append((rel + e.name + "/", e.path))
                    elif e.name.endswith(suffixes) if plain else any(
                            fnmatch(e.name, pat) for pat in patterns):
                        s = e.stat()
                        found.append(f"{rel}{e.name}:{s.st_size}:{s.st_mtime_ns}\n")
        h.update("".join(sorted(found)).encode())
    return h.hexdigest()


def purge_modules(prefixes: tuple[str, ...]) -> list[str]:
    """Remove the modules named by ``prefixes``, and their submodules, from ``sys.modules`` so
    the next import re-executes them from disk. Returns the names removed. Another session's
    run may be importing meanwhile (readers who open a fresh server together), so it reads a
    copy of ``sys.modules``: iterating the live dict raised "dictionary changed size during
    iteration" there (docs/qa.md, "Memory pass")."""
    names = [m for m in list(sys.modules)
             if any(m == p or m.startswith(p + ".") for p in prefixes)]
    for m in names:
        sys.modules.pop(m, None)
    return names

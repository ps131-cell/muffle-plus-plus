"""Computed once, handed out as copies: the workbenches' pure summaries and queues.

A patient file (``muffle.workspace.PatientFile``) is not changed once built: an import makes a
new file (``workspace.add_version``). So what a pure function computes from a file and its
arguments can stay with that file object (``per_file``): the app builds the bundle's files once
per process, and the report, the timeline and each workbench page then share one computation of
each workbench's ``summary`` and ``queue`` across reruns and browser sessions. ``calls`` keeps a
function's results by its arguments (one CIViC lookup per variant). Each call gets its own deep
copy, so a caller that changes its result changes nothing for the next one. Nothing here outlives
the code that computed it: the hot-update guard (``muffle.hotreload``) drops this module with the
rest of ``muffle``.
"""

from __future__ import annotations

import copy
import functools
import threading
import weakref

_files: dict[int, tuple[weakref.ref, dict]] = {}  # id(file) -> (the file, its results)
_lock = threading.RLock()  # re-entrant: a collected file's callback can run inside it


def _forget(key: int, ref: weakref.ref) -> None:
    with _lock:
        if _files.get(key, (None,))[0] is ref:
            _files.pop(key, None)


def _results(pf) -> dict | None:
    """The results kept with ``pf``; None for an object that can't be weakly referenced (a
    stand-in), which is then computed every time."""
    with _lock:
        slot = _files.get(id(pf))
        if slot is not None and slot[0]() is pf:
            return slot[1]
        try:
            ref = weakref.ref(pf, functools.partial(_forget, id(pf)))
        except TypeError:
            return None
        _files[id(pf)] = (ref, {})
        return _files[id(pf)][1]


def _plain(value) -> bool:
    """An argument a result can be kept by: a number, a string, None, a tuple of those, or a
    named function (never a lambda or a function made per call, which would pile up)."""
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, tuple):
        return all(_plain(v) for v in value)
    name = getattr(value, "__qualname__", "")
    return callable(value) and bool(name) and "<" not in name


def per_file(fn):
    """``fn(pf, *args, **kwargs)`` computed once per file object and arguments (``_plain``
    ones: a version, a named lookup function; other calls are computed as before)."""
    @functools.wraps(fn)
    def wrapper(pf, *args, **kwargs):
        if not all(_plain(v) for v in (*args, *kwargs.values())):
            return fn(pf, *args, **kwargs)
        key = (fn.__module__, fn.__qualname__, args, tuple(sorted(kwargs.items())))
        kept = _results(pf)
        if kept is None:
            return fn(pf, *args, **kwargs)
        if key not in kept:
            kept[key] = fn(pf, *args, **kwargs)
        return copy.deepcopy(kept[key])

    return wrapper


def calls(fn):
    """``fn`` with its results kept by argument (``_plain`` ones; others computed each time)."""
    kept: dict = {}

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        if not all(_plain(v) for v in (*args, *kwargs.values())):
            return fn(*args, **kwargs)
        key = (args, tuple(sorted(kwargs.items())))
        if key not in kept:
            kept[key] = fn(*args, **kwargs)
        return copy.deepcopy(kept[key])

    return wrapper

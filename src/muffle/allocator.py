"""How the server process gives freed memory back: glibc's malloc set once, before the big
imports (``app/streamlit_app.py``'s first lines). docs/qa.md, "Memory pass (2026-10-28)".

The hosted app runs on Linux (glibc), where Streamlit Community Cloud guarantees 690 MB.
Two glibc defaults keep memory the app has already freed:

- **The mmap threshold moves up.** A block of 128 KiB or more (an image, a figure's JSON, a
  pickled cache entry, a numpy temporary of the slide or MRI pages) is mmapped and returned to
  the system when freed, but each such free raises the threshold to that block's size (up to
  32 MiB). After the first map page, later blocks of that size come from the heap and stay there
  as free space between live blocks. A fixed threshold keeps them mmapped.
- **An arena per thread.** Streamlit runs every rerun of every session in a thread, and glibc
  gives threads that run at the same time their own heaps (up to eight per core), each keeping
  its own free space. Two arenas, shared by every thread.

Elsewhere (macOS, Windows, a libc without ``mallopt``) nothing changes. Settings given to the
process (``MALLOC_MMAP_THRESHOLD_``, ``MALLOC_ARENA_MAX``) win.
"""

from __future__ import annotations

import ctypes
import os
import sys

M_MMAP_THRESHOLD = -3   # glibc's mallopt parameters (malloc.h)
M_ARENA_MAX = -8
MMAP_THRESHOLD = 128 * 1024   # glibc's own starting value, kept fixed
ARENA_MAX = 2
SETTINGS = ((M_MMAP_THRESHOLD, MMAP_THRESHOLD, "MALLOC_MMAP_THRESHOLD_"),
            (M_ARENA_MAX, ARENA_MAX, "MALLOC_ARENA_MAX"))


def tune() -> dict[str, int]:
    """Set what the environment leaves unset; returns {environment name: value} for each
    setting glibc took (empty off glibc). Calling it again changes nothing."""
    if not sys.platform.startswith("linux"):
        return {}
    try:
        mallopt = ctypes.CDLL("libc.so.6").mallopt
    except (OSError, AttributeError):  # musl, or no libc.so.6
        return {}
    mallopt.argtypes, mallopt.restype = (ctypes.c_int, ctypes.c_int), ctypes.c_int
    return {name: value for param, value, name in SETTINGS
            if name not in os.environ and mallopt(param, value) == 1}

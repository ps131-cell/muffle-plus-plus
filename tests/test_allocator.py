"""glibc's malloc set once per process (muffle.allocator; docs/qa.md, "Memory pass")."""

import subprocess
import sys

import pytest

from muffle import allocator

LINUX = sys.platform.startswith("linux")

# After a 4 MB block is freed, glibc raises its mmap threshold to 4 MB, so a later 1 MB block
# comes from the heap (and stays there once freed); with the fixed threshold it is mmapped and
# goes back to the system when freed. mallinfo2's hblkhd counts the mmapped bytes.
PROBE = """
import ctypes, sys
import numpy as np
from muffle import allocator
if sys.argv[1] == "tuned":
    assert allocator.tune() == {"MALLOC_MMAP_THRESHOLD_": 131072, "MALLOC_ARENA_MAX": 2}
class Info(ctypes.Structure):
    _fields_ = [(n, ctypes.c_size_t) for n in ("arena", "ordblks", "smblks", "hblks", "hblkhd",
                "usmblks", "fsmblks", "uordblks", "fordblks", "keepcost")]
libc = ctypes.CDLL("libc.so.6")
libc.mallinfo2.restype = Info
big = np.ones(4_000_000, np.uint8)
del big
before = libc.mallinfo2().hblkhd
block = np.ones(1_000_000, np.uint8)
print(int(libc.mallinfo2().hblkhd - before >= 1_000_000))
"""


@pytest.mark.skipif(not LINUX, reason="glibc only")
def test_a_freed_large_block_does_not_move_the_mmap_threshold():
    def mmapped(mode: str) -> bool:
        out = subprocess.run([sys.executable, "-c", PROBE, mode], capture_output=True,
                             text=True, env={"PATH": "/usr/bin:/bin", "PYTHONPATH":
                                             ":".join(sys.path)})
        if "mallinfo2" in out.stderr:
            pytest.skip("glibc without mallinfo2")
        assert out.returncode == 0, out.stderr
        return out.stdout.strip() == "1"

    assert mmapped("tuned")          # mmapped: returned to the system when freed
    assert not mmapped("default")    # glibc's moving threshold: from the heap


def test_settings_given_to_the_process_win(monkeypatch):
    monkeypatch.setenv("MALLOC_ARENA_MAX", "4")
    took = allocator.tune()
    assert "MALLOC_ARENA_MAX" not in took
    assert took == ({"MALLOC_MMAP_THRESHOLD_": allocator.MMAP_THRESHOLD} if LINUX else {})


def test_nothing_happens_off_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    assert allocator.tune() == {}

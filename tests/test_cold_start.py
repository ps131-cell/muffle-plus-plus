"""The first screen's shortcuts (docs/qa.md, "Cold-start pass (2026-10-28)"): modules loaded on
first use (muffle.lazy), the hosted setup's downloads started early (muffle.prefetch), and the
slide maths importing scipy only when it runs."""

import subprocess
import sys

from muffle import lazy, prefetch


def test_a_lazy_module_imports_on_first_use_and_follows_a_purge(tmp_path, monkeypatch):
    (tmp_path / "zzlazy.py").write_text("LOADS = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    m = lazy.module("zzlazy")
    assert "zzlazy" not in sys.modules  # nothing imported yet
    assert m.LOADS == 1 and "zzlazy" in sys.modules
    # the hot-update guard drops a module; the next read imports the new source
    (tmp_path / "zzlazy.py").write_text("LOADS = 2\n")
    del sys.modules["zzlazy"]
    sys.path_importer_cache.clear()
    assert m.LOADS == 22
    del sys.modules["zzlazy"]


def test_a_prefetched_file_is_there_once_the_loader_waits(tmp_path):
    src = tmp_path / "remote.bin"
    src.write_bytes(b"bundle bytes")
    dest = tmp_path / "cache" / "bundle.pt"
    prefetch.start(src.as_uri(), dest)
    prefetch.wait(dest)
    assert dest.read_bytes() == b"bundle bytes"
    assert not list(dest.parent.glob("*.part"))  # written under its own name, then renamed
    prefetch.start("file:///no/such/file", dest)  # already there: nothing to do
    assert dest.read_bytes() == b"bundle bytes"


def test_a_failed_prefetch_leaves_nothing_for_the_loader_to_trip_on(tmp_path):
    dest = tmp_path / "civic.tsv"
    prefetch.start((tmp_path / "missing.tsv").as_uri(), dest)
    prefetch.wait(dest)
    assert not dest.exists() and not list(tmp_path.glob("*.part"))
    prefetch.wait(tmp_path / "never-started")  # returns at once


def test_the_bundle_path_is_one_file_per_url():
    a, b = (prefetch.bundle_path(f"https://example.org/{t}/demo_bundle.pt") for t in ("v1", "v2"))
    assert a != b and a.name.startswith("muffle_bundle_") and a.suffix == ".pt"


def test_the_slide_maths_imports_scipy_only_when_it_runs():
    """The report reads the slide cutoffs from muffle.workbench.invasion; that must not load
    scipy (about 1.7 s at load 3), which the slide page loads when it draws a section."""
    code = ("import sys; from muffle.workbench import invasion; "
            "assert 'scipy' not in sys.modules, 'scipy at import'; "
            "import numpy as np; m = np.zeros((9, 9), bool); m[3:6, 3:6] = True; "
            "invasion.ndimage.binary_dilation(m); "
            "d, _ = invasion.cKDTree(np.array([[0.0, 0.0], [3.0, 4.0]])).query([[0.0, 0.0]]); "
            "assert 'scipy.ndimage' in sys.modules and d[0] == 0")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr

"""The first screen's shortcuts (docs/qa.md, "Cold-start pass (2026-10-28)"): modules loaded on
first use (muffle.lazy), the hosted setup's downloads started early (muffle.prefetch), and the
slide maths importing scipy only when it runs."""

import json
import subprocess
import sys
import types
from pathlib import Path

from muffle import lazy, prefetch

ROOT = Path(__file__).resolve().parents[1]


def test_a_lazy_module_imports_on_first_use_and_follows_a_purge(tmp_path, monkeypatch):
    (tmp_path / "zzlazy.py").write_text("LOADS = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    m = lazy.module("zzlazy")
    assert "zzlazy" not in sys.modules  # nothing imported yet
    assert m.LOADS == 1 and "zzlazy" in sys.modules
    # the hot-update guard drops a module; the next read imports the new source
    (tmp_path / "zzlazy.py").write_text("LOADS = 22\n")  # another size: no stale bytecode
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


def test_the_patient_list_draws_without_altair(app, monkeypatch):
    """The list's first screen needs no chart library: its one chart, the cohort strip's risk
    groups, is a plain Vega-Lite dict (app/chart_theme.py). With Altair and the chart module
    unimportable, the list still draws, the histogram included (the first worklist built it with
    Altair, which brought jsonschema and the schema check into a fresh start, docs/qa.md)."""
    for name in ("altair", "charts"):
        monkeypatch.setitem(sys.modules, name, None)  # importing either now fails
    # the app's last lines preload Altair in a thread unless scipy.spatial is loaded: not here
    monkeypatch.setitem(sys.modules, "scipy.spatial",
                        sys.modules.get("scipy.spatial") or types.ModuleType("scipy.spatial"))
    at = app.new().run()
    assert not at.exception and len(at.dataframe[0].value) > 1
    assert any('"risk group"' in c.proto.spec for c in at.get("vega_lite_chart"))


def test_the_strip_chart_is_the_altair_chart_key_for_key(monkeypatch):
    """The dict is what Altair writes for the chart the worklist drew (#162): the app's theme,
    the dataset's name, every key in its order, so the screen is the same. A list that keeps no
    file of a group shows no dark bar there (an empty selection read as "all" in #162)."""
    monkeypatch.syspath_prepend(str(ROOT / "app"))
    import altair as alt
    import chart_theme
    import charts
    import pandas as pd

    def drawn(counts, shown):  # #162's charts.risk_bands, with the empty selection fixed
        order = [g for g in ("low", "medium", "high") if g in counts]
        df = pd.DataFrame({"group": order, "files": [int(counts[g]) for g in order],
                           "shown": [int(shown.get(g, 0)) for g in order]})
        x = alt.X("group:N", sort=order, title=None, axis=alt.Axis(
            labelAngle=0, labelFontSize=11, ticks=False, domainOpacity=0.4))
        y = alt.Y("files:Q", title=None, axis=None,
                  scale=alt.Scale(domainMax=max(df["files"]) * 1.3))
        tip = [alt.Tooltip("group:N", title="risk group"), alt.Tooltip("files:Q", title="files"),
               alt.Tooltip("shown:Q", title="in the list now")]
        base = alt.Chart(df).encode(x=x, tooltip=tip)
        bars = base.mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2, opacity=0.35).encode(
            y=y, color=alt.Color("group:N", legend=None, scale=alt.Scale(
                domain=order, range=[charts.RAMP[g] for g in order])))
        kept = base.mark_bar(cornerRadiusTopLeft=2, cornerRadiusTopRight=2).encode(
            y=alt.Y("shown:Q", title=None, axis=None), color=alt.Color("group:N", legend=None))
        labels = base.mark_text(dy=-6, baseline="bottom", fontSize=11).encode(
            y="files:Q", text=alt.Text("files:Q"))
        return (bars + kept + labels).properties(
            height=52, padding={"top": 14, "bottom": 0, "left": 2, "right": 2},
            autosize=alt.AutoSizeParams(type="fit-x", contains="padding")).configure_view(
            strokeWidth=0)

    for counts, shown in (({"low": 14, "medium": 16, "high": 10}, {"low": 3, "high": 4}),
                          ({"low": 5, "high": 2}, {}), ({"medium": 7}, {"medium": 7})):
        ref, light = drawn(counts, shown).to_dict(), chart_theme.risk_bands(counts, shown)
        assert ref.pop("$schema").startswith("https://vega.github.io/schema/vega-lite/v")
        light.pop("$schema")
        assert json.dumps(light) == json.dumps(ref), counts
    empty = chart_theme.risk_bands({"low": 5, "high": 2}, {})
    assert [r["shown"] for r in next(iter(empty["datasets"].values()))] == [0, 0]


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

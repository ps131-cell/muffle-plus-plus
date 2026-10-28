import sys
import types

from muffle.hotreload import purge_modules, source_digest


def test_source_digest_changes_when_a_source_file_changes(tmp_path):
    (tmp_path / "a.py").write_text("x = 1\n")
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.py").write_text("y = 2\n")
    (tmp_path / "data.json").write_text("{}")
    (tmp_path / "notes.txt").write_text("ignored")
    first = source_digest([tmp_path])
    assert first == source_digest([tmp_path])  # stable while nothing changes
    (tmp_path / "sub" / "b.py").write_text("y = 3000\n")
    second = source_digest([tmp_path])
    assert second != first
    (tmp_path / "data.json").write_text('{"k": 1}')
    assert source_digest([tmp_path]) != second
    (tmp_path / "notes.txt").write_text("still ignored, longer")
    assert source_digest([tmp_path]) == source_digest([tmp_path])
    assert source_digest([tmp_path / "missing"]) == source_digest([])  # a missing root is skipped
    before = source_digest([tmp_path])
    (tmp_path / "static" / "slides").mkdir(parents=True)  # the slide viewer's tiles: not code
    (tmp_path / "static" / "slides" / "overlay-1.json").write_text("{}")
    assert source_digest([tmp_path]) == before


def test_source_digest_sees_new_and_removed_files_at_any_depth(tmp_path):
    deep = tmp_path / "workbenches" / "slides_results" / "S1"
    deep.mkdir(parents=True)
    (deep / "summary.json").write_text("{}")
    (tmp_path / "__pycache__").mkdir()
    first = source_digest([tmp_path])
    (tmp_path / "__pycache__" / "x.cpython-312.pyc").write_text("")  # bytecode: not a source
    (tmp_path / "__pycache__" / "y.py").write_text("")
    assert source_digest([tmp_path]) == first
    (deep / "tiles.json").write_text("[]")  # a new result file, three folders down
    second = source_digest([tmp_path])
    assert second != first
    (deep / "tiles.json").unlink()
    assert source_digest([tmp_path]) == first
    (deep / "summary.json").write_text('{"n": 1}')
    assert source_digest([tmp_path]) not in (first, second)


def test_purge_modules_drops_only_the_named_prefixes():
    names = ("zzpkg", "zzpkg.sub", "zzpkgother", "zzcharts")
    for name in names:
        sys.modules[name] = types.ModuleType(name)
    try:
        gone = purge_modules(("zzpkg", "zzcharts"))
        assert sorted(gone) == ["zzcharts", "zzpkg", "zzpkg.sub"]
        assert "zzpkgother" in sys.modules and "os" in sys.modules
        assert "zzpkg" not in sys.modules and "zzpkg.sub" not in sys.modules
    finally:
        for name in names:
            sys.modules.pop(name, None)


def test_purge_modules_survives_an_import_in_another_session():
    """Readers who open a fresh server together: one run purges while another imports. The
    prefix below imports a module each time it is read, as that other thread would; reading the
    live sys.modules raised "dictionary changed size during iteration"."""
    added = []

    class Importing(str):
        def __add__(self, other):
            name = f"zzlate{len(added)}"
            sys.modules[name] = types.ModuleType(name)
            added.append(name)
            return str.__add__(self, other)

    sys.modules["zzgone"] = types.ModuleType("zzgone")
    try:
        assert purge_modules((Importing("zzgone"),)) == ["zzgone"]
        assert added and all(name in sys.modules for name in added)
    finally:
        for name in ("zzgone", *added):
            sys.modules.pop(name, None)

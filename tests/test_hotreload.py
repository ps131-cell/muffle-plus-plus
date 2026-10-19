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

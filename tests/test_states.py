"""Error states, the patient list's order and SOS badge, the sidebar's session block and the
report's cards (docs/ux.md §4): a part that fails says which part and where its method is
described, never a traceback; the list sorts by last update, risk or open SOS alerts."""

import ast
import sys

import pytest

from muffle import overview
from tests.appfixture import APP, popovers, shown

pytestmark = pytest.mark.filterwarnings("error")  # a warning from a page fails the test
SYN = "SYNTHETIC-001"


def test_sorting_the_list():
    rows = [{"id": "a", "alerts": ["x"], "updated": None, "imported": False, "percentile": 40.0},
            {"id": "b", "alerts": ["y", "z"], "updated": 24, "imported": False,
             "percentile": None},
            {"id": "c", "alerts": [], "updated": None, "imported": True, "percentile": 90.0},
            {"id": "d", "alerts": ["w"], "updated": 3, "imported": False, "percentile": 70.0}]
    ids = lambda by, reviews=None: [r["id"] for r in overview.sort_rows(rows, by, reviews)]  # noqa: E731
    assert ids("Last update") == ["c", "b", "d", "a"]  # an import first, then the latest month
    assert ids("Risk") == ["c", "d", "a", "b"]  # no cohort percentile: last
    assert ids("Open SOS") == ["b", "a", "d", "c"]
    assert ids("Open SOS", {"y": {}, "z": {}}) == ["a", "d", "b", "c"]  # marked: no longer open


def test_a_part_that_fails_says_so_without_a_traceback(app, monkeypatch):
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    at.segmented_control(key="view").set_value("Tests").run()

    def boom(*a, **k):
        raise KeyError("a field the page expected")

    monkeypatch.setenv("MUFFLE_STRICT_PAGES", "0")  # as in front of a clinician
    monkeypatch.setattr(sys.modules["workbenches.labs"], "render", boom)
    at.session_state[f"picked-{SYN}"] = ("Lab", 24, "CA 15-3")
    at.run()
    assert not at.exception  # no traceback on the page
    assert at.error[0].value.startswith("The blood and lab workbench could not be drawn.")
    assert "Methods and validation page" in at.error[0].value
    assert [p.label for p in at.get("page_link")][-1] == "Methods and validation"
    assert "Logged for the team: KeyError." in shown(at)
    assert at.dataframe[0].value["Test"].tolist()  # the tests table still works
    at.segmented_control(key="view").set_value("Report").run()  # and so do the other views
    assert not at.error and not at.exception


def test_the_list_sorts_and_the_sidebar_holds_the_session(app):
    at = app.new().run()
    table = at.dataframe[0].value
    assert table["Open SOS"].tolist()[0] == "🔴 7 open" and table["Patient"][0] == SYN
    assert "**Your patient files.**" in shown(at)
    at.segmented_control(key="list-sort").set_value("Risk").run()
    cases = [c for c in app.demo.cases if f"Case {c.index}" in table["Patient"].tolist()]
    top = max(cases, key=lambda c: c.percentile)
    assert at.dataframe[0].value["Patient"].tolist()[:1] == [f"Case {top.index}"]
    assert at.dataframe[0].value["Patient"].tolist()[-1] == SYN  # another measure: last
    # the sidebar: provenance in "About this system", this session's marks with their export
    assert "About this system" in [e.label for e in at.sidebar.expander]
    assert "0 review marks and 0 pins in this session" in " ".join(
        c.value for c in at.sidebar.caption)
    at.selectbox(key="patient").select(SYN).run()
    queue = f"queue-{SYN}-{len(at.select_slider(key=f'version-{SYN}').options) - 1}"
    at.button(key=f"reviewed-{queue}").click().run()
    assert "1 review mark and 0 pins" in " ".join(c.value for c in at.sidebar.caption)
    assert "Download this session's marks (CSV)" in [b.label for b in
                                                     at.sidebar.get("download_button")]


def test_report_cards_are_short_with_their_full_text_one_click_away(app):
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    cards = [m.value for m in at.markdown if m.value.endswith(" …")]  # shortened cards
    assert cards and "**:red[SOS]** · 7 open" in shown(at) and not at.exception
    full = popovers(at)["more"]  # the full text, one click away
    assert cards[-1][:-2].split("*")[-1].strip()[:20] in full


def test_metric_tiles_wrap_instead_of_cutting_their_values():
    """Every metric tile takes its content's width in a row that wraps on a narrow screen
    (st.container(horizontal=True)), never a fixed column that cuts "75th percentile" to "75th
    perc…"; its unit goes in the label ("…, cohort percentile"), not the value (docs/ux.md §4)."""
    calls = [(p.name, n) for p in sorted(APP.parent.rglob("*.py"))
             for n in ast.walk(ast.parse(p.read_text(encoding="utf-8")))
             if isinstance(n, ast.Call) and getattr(n.func, "attr", None) == "metric"]
    assert len(calls) > 30
    for name, n in calls:
        width = {k.arg: k.value for k in n.keywords}.get("width")
        assert isinstance(width, ast.Constant) and width.value == "content", f"{name}:{n.lineno}"
        words = [c.value for c in ast.walk(n.args[1]) if isinstance(c, ast.Constant)
                 and isinstance(c.value, str)] if len(n.args) > 1 else []  # the value's text
        assert not any("percentile" in w for w in words), f"{name}:{n.lineno}: unit in the label"


def in_columns(at) -> list[str]:
    """The labels of the buttons, downloads and popovers whose nearest row is a set of fixed
    columns (st.columns) giving them under 40% of the width (a third, a sixth, [10, 1]), not a
    row that wraps (st.container(horizontal=True))."""
    out: list[str] = []

    def walk(node, inside: bool) -> None:
        kind = getattr(node, "type", None)
        if inside and kind in ("button", "download_button"):
            out.append(node.label)
        if inside and kind == "popover":
            out.append(node.proto.popover.label)
        children = [node.children[k] for k in sorted(getattr(node, "children", {}) or {})]
        cols = [c for c in children if getattr(c, "type", None) == "column"]
        if kind == "flex_container" and node.proto.flex_container.direction == 2:
            if not cols:
                inside = False  # a horizontal container: its items take their own width, wrap
            total = sum(c.weight for c in cols)
            for c in cols:
                walk(c, c.weight / total < 0.4)
            children = [c for c in children if c not in cols]
        for child in children:
            walk(child, inside)

    walk(at._tree, False)
    return out


def test_buttons_keep_their_labels_whole(app):
    """Buttons sit in rows that wrap (st.container(horizontal=True)), never in fixed columns,
    which cut "Mark reviewed" to "M…", "Open" to "(" and the export's downloads at 800 px (QA
    round 2, docs/qa.md): the report, its attention queue and the workbenches' look-here lists,
    review marks and exports."""
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    assert not in_columns(at), in_columns(at)
    at.segmented_control(key="view").set_value("Tests").run()
    for test in (("Lab", 24, "CA 15-3"), ("Sequencing", 0, "Tumor sequencing"),
                 ("Imaging", 12, "Imaging report"), ("ctDNA (liquid biopsy)", 24,
                                                     "ctDNA panel (synthetic series)")):
        at.session_state[f"picked-{SYN}"] = test
        at.run()
        assert not at.exception and not in_columns(at), (test, in_columns(at))
    at.segmented_control(key="view").set_value("Timeline").run()
    assert not in_columns(at), in_columns(at)
    at.selectbox(key="patient").select(app.case).run()
    assert not in_columns(at), in_columns(at)


def test_the_theme_passes_wcag_aa_contrast():
    """Badge text on Streamlit 1.66's light badge tints (measured in headless Chrome by the QA
    walk, docs/qa.md round 2), white on the primary color and captions (the text color at 60%
    opacity, as Streamlit draws them) all reach 4.5:1."""
    import tomllib

    theme = tomllib.loads((APP.parents[1] / ".streamlit" / "config.toml").read_text())["theme"]

    def rgb(h: str) -> tuple:
        return tuple(int(h[i:i + 2], 16) for i in (1, 3, 5))

    def lum(c) -> float:
        c = [v / 255 for v in c]
        c = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    def ratio(a, b) -> float:
        return (max(lum(a), lum(b)) + 0.05) / (min(lum(a), lum(b)) + 0.05)

    tints = {"orange": (255, 246, 233), "gray": (234, 235, 236), "green": (233, 249, 238)}
    for color, tint in tints.items():
        assert ratio(rgb(theme[f"{color}TextColor"]), tint) >= 4.5, color
    assert ratio((255, 255, 255), rgb(theme["primaryColor"])) >= 4.5  # primary buttons, chips
    caption = tuple(255 - 0.6 * (255 - v) for v in rgb(theme["textColor"]))
    assert ratio(caption, (255, 255, 255)) >= 4.5


def test_the_methods_page_lists_every_card_in_its_contents(app):
    at = app.new().run()
    pages = {i.get("url_pathname"): h for h, i in at._registered_pages.items()}
    at._page_hash = pages["methods"]
    at.run()
    assert not at.exception
    sys.path.insert(0, str(APP.parent))
    from methods_page import CONTENTS, anchor

    assert list(CONTENTS) == [h.value for h in at.header]
    cards = [t for titles in CONTENTS.values() for t in titles]
    assert cards == [s.value for s in at.subheader], "a new card joins methods_page.CONTENTS"
    toc = " ".join(m.value for m in at.markdown if "](#" in m.value)
    assert all(f"[{t}](#{anchor(t)})" in toc for t in [*CONTENTS, *cards])
    assert anchor("Lesion contours (MedSAM, breast MRI)") == "lesion-contours-medsam-breast-mri"

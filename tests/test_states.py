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
    rows = [{"id": "a", "alerts": ["x"], "updated": None, "imported": False, "percentile": 40.0,
             "stage": "II", "versions": 1},
            {"id": "b", "alerts": ["y", "z"], "updated": 24, "imported": False,
             "percentile": None, "stage": "not recorded", "versions": 16},
            {"id": "c", "alerts": [], "updated": None, "imported": True, "percentile": 90.0,
             "stage": "IV", "versions": 2},
            {"id": "d", "alerts": ["w"], "updated": 3, "imported": False, "percentile": 70.0,
             "stage": "I", "versions": 1}]

    def ids(by, reviews=None, reverse=False):
        return [r["id"] for r in overview.sort_rows(rows, by, reviews, reverse)]

    assert ids("Last update") == ["c", "b", "d", "a"]  # an import first, then the latest month
    assert ids("Risk") == ["c", "d", "a", "b"]  # no cohort percentile: last
    assert ids("Open SOS") == ["b", "a", "d", "c"]
    assert ids("Open SOS", {"y": {}, "z": {}}) == ["a", "d", "b", "c"]  # marked: no longer open
    assert ids("Stage") == ["c", "a", "d", "b"]  # IV first; not recorded last
    assert ids("Versions") == ["b", "c", "a", "d"] and ids("ID") == ["a", "b", "c", "d"]
    # reversed: the other way round, the rows without a value still last
    assert ids("Risk", reverse=True) == ["a", "d", "c", "b"]
    assert ids("Stage", reverse=True) == ["d", "a", "c", "b"]
    assert ids("Last update", reverse=True) == ["d", "b", "c", "a"]
    assert ids("ID", reverse=True) == ["d", "c", "b", "a"]


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


def test_cards_open_their_evidence_and_empty_ones_say_what_would_fill_them(app):
    """Each finding card ends in a full-width Open that names where it lands; a workbench with
    nothing to show is a card too, saying why and what would fill it, with Import a test where
    Import tests takes that test."""
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    last = len(at.select_slider(key=f"version-{SYN}").options) - 1
    opens = {b.key: b.label for b in at.button if (b.key or "").startswith(f"card-{SYN}-")}
    assert opens and all(label.startswith("Open · ") for label in opens.values())
    assert opens[f"card-{SYN}-{last}-12-month risk"] == "Open · Timeline"
    assert opens[f"card-{SYN}-{last}-Key drivers"] == "Open · Sequencing, month 0"
    assert "**Expression** · nothing to show" in shown(at)
    assert "What would fill it: expression, methylation or protein profiling" in shown(at)
    assert f"fill-{SYN}-omics" not in [b.key for b in at.button]  # Import tests can't take it
    at.button(key=f"fill-{SYN}-slides").click().run()
    assert at.segmented_control(key="view").value == "Import tests" and not at.exception
    at.segmented_control(key="view").set_value("Report").run()
    at.button(key=f"card-{SYN}-{last}-Key drivers").click().run()
    assert at.segmented_control(key="view").value == "Tests" and not at.exception
    assert "Genomics workbench" in shown(at)


def test_metric_tiles_and_number_strips_wrap_instead_of_cutting_their_values():
    """Every metric tile takes its content's width in a row that wraps on a narrow screen
    (st.container(horizontal=True)), never a fixed column that cuts "75th percentile" to "75th
    perc…"; a number strip (``workbenches._page.strip``) wraps by itself (app/theme.css). Either
    way the unit goes in the label ("…, cohort percentile") or the note, not the value
    (docs/ux.md §4, §8.1)."""
    calls, stats = [], []
    for p in sorted(APP.parent.rglob("*.py")):
        for n in ast.walk(ast.parse(p.read_text(encoding="utf-8"))):
            name = getattr(getattr(n, "func", None), "attr", None) or getattr(
                getattr(n, "func", None), "id", None)
            if isinstance(n, ast.Call) and name == "metric":
                calls.append((p.name, n))
            elif isinstance(n, ast.Call) and name in ("strip", "stat_strip"):
                stats += [(p.name, t) for t in n.args if isinstance(t, ast.Tuple)]
    assert len(calls) + len(stats) > 30 and stats
    for name, n in calls:
        width = {k.arg: k.value for k in n.keywords}.get("width")
        assert isinstance(width, ast.Constant) and width.value == "content", f"{name}:{n.lineno}"
        words = [c.value for c in ast.walk(n.args[1]) if isinstance(c, ast.Constant)
                 and isinstance(c.value, str)] if len(n.args) > 1 else []  # the value's text
        assert not any("percentile" in w for w in words), f"{name}:{n.lineno}: unit in the label"
    for name, t in stats:  # (label, value, note, help): the value's text
        words = [c.value for c in ast.walk(t.elts[1]) if isinstance(c, ast.Constant)
                 and isinstance(c.value, str)]
        assert not any("percentile" in w for w in words), f"{name}:{t.lineno}: unit in the label"


CONTROLS = {"button", "download_button", "popover", "selectbox", "multiselect", "pills",
            "segmented_control", "toggle", "checkbox", "text_input", "select_slider", "radio",
            "number_input", "text_area", "file_uploader", "slider", "page_link"}
FORMATS = ("Markdown", "CSV", "JSON", "PNG", "PDF", "MAF", "VCF", "text", "DICOM")


def test_every_control_of_the_shell_says_what_it_does():
    """Every button, popover, picker and toggle of the shell (the patient list, the file, the
    report, the guide, the timeline, the page helper) has a tooltip (docs/ux.md §2); every
    download in the app whose label is written out names its format, "(Markdown)", "CSV"
    (docs/ux.md §1); a label held in a variable is not read here."""
    missing, downloads = [], []
    for path in sorted(APP.parent.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        shell = path.name in ("streamlit_app.py", "guide.py", "navigation.py",
                              "timeline_page.py", "_page.py")
        for n in ast.walk(tree):
            if not (isinstance(n, ast.Call) and getattr(n.func, "attr", None) in CONTROLS):
                continue
            help_ = {k.arg: k.value for k in n.keywords}.get("help")
            if shell and (help_ is None or (isinstance(help_, ast.Constant)
                                            and help_.value is None)):
                missing.append(f"{path.name}:{n.lineno}")
            if n.func.attr == "download_button" and n.args:
                label = n.args[0]
                for branch in (label.body, label.orelse) if isinstance(label, ast.IfExp) \
                        else (label,):  # each side of "a if b else c" names it
                    text = " ".join(str(c.value) for c in ast.walk(branch)
                                    if isinstance(c, ast.Constant) and isinstance(c.value, str))
                    if text and not any(f in text for f in FORMATS):
                        downloads.append(f"{path.name}:{n.lineno}")
    assert not missing, missing
    assert not downloads, downloads


def test_the_shells_expanders_say_what_they_hold(app):
    """The report's expanders start with a verb and carry a count; the Methods and validation
    page is a link in the file's action row and in the open workbench's model card."""
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    labels = [e.label for e in at.expander]
    assert any(e.startswith("Show the caveats, data sources and model versions (") for e in labels)
    at.segmented_control(key="view").set_value("Tests").run()
    links = [p.proto.page for p in at.get("page_link") if p.label == "Methods and validation"]
    assert links == ["methods", "methods"] and not at.exception  # the file's row, the card


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


def charts_in_columns(at) -> list[str]:
    """The charts whose nearest row is a set of fixed columns giving them half the width or
    less: at 800 px with the sidebar open that is about 230 px, too narrow for an axis title."""
    out: list[str] = []

    def walk(node, inside: bool) -> None:
        kind = getattr(node, "type", None) or ""
        if inside and "vega" in kind:
            out.append(kind)
        children = [node.children[k] for k in sorted(getattr(node, "children", {}) or {})]
        cols = [c for c in children if getattr(c, "type", None) == "column"]
        if kind == "flex_container" and node.proto.flex_container.direction == 2:
            if not cols:
                inside = False
            total = sum(c.weight for c in cols)
            for c in cols:
                walk(c, c.weight / total <= 0.5)
            children = [c for c in children if c not in cols]
        for child in children:
            walk(child, inside)

    walk(at._tree, False)
    return out


def test_the_reports_charts_keep_room_for_their_axes(app):
    """QA R3-7: a TCGA file's risk histogram and layer contributions sat in two fixed columns,
    so at 800 px the histogram's plot was about 30 px wide and both axis titles were cut; they
    now share a row that wraps, a fixed width each. R3-10: the MRI Spot panel's curve sat in a
    2-of-5 column (its axis and the mark's options cut); it sits under the panel's words."""
    at = app.new().run()
    for pid in (app.case, SYN):
        at.selectbox(key="patient").select(pid).run()
        assert not at.exception and not charts_in_columns(at), (pid, charts_in_columns(at))
    at.selectbox(key="patient").select(app.case).run()  # R3-5: one "Where this patient sits"
    assert "risk among all" in shown(at) and "sits among all patients" not in shown(at)
    if app.shipped:  # the test case borrows a processed public MRI
        at.selectbox(key="patient").select(app.case).run()
        at.session_state[f"picked-{app.case}"] = ("Imaging", None, app.shipped[0]["name"])
        at.segmented_control(key="view").set_value("Tests").run()
        assert "Spot panel" in shown(at) and not at.exception
        assert not charts_in_columns(at), charts_in_columns(at)


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
    assert ratio(caption, (255, 255, 255)) >= 4.5  # a caption as Streamlit fades it (no sheet)
    # QA R4-1: the sheet draws captions at full opacity in the muted ink, so the chips and links
    # inside a caption keep their own contrast (the badge checks above), and the text 7.6:1
    import re

    sheet = (APP.parent / "theme.css").read_text(encoding="utf-8")
    rule = re.search(r'\[data-testid="stCaptionContainer"\]\s*\{([^}]*)\}', sheet).group(1)
    assert "opacity: 1" in rule and "var(--mf-muted)" in rule
    muted = re.search(r"--mf-muted:\s*(#[0-9a-fA-F]{6})", sheet).group(1)
    assert ratio(rgb(muted), (255, 255, 255)) >= 4.5


def test_no_file_path_on_a_clinician_screen(app):
    """The report, a workbench and the Feedback page name no repository file (QA round 2 found
    "docs/VISION.md" on the Feedback page and "src/muffle/data/tcga.py" on the genomics card).
    The Methods page may cite the project's docs; provenance names data sources, not files."""
    import re

    path = re.compile(r"\b(?:docs|src|app|tests|scripts)/[\w/.-]+\.(?:py|md|json)\b")
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    assert not path.findall(shown(at))
    at.segmented_control(key="view").set_value("Tests").run()
    for test in (("Sequencing", 0, "Tumor sequencing"), ("Clinic note", 13, "Clinic visit")):
        at.session_state[f"picked-{SYN}"] = test
        at.run()
        assert not path.findall(shown(at)) and not at.exception, test
    at.selectbox(key="patient").select(app.case).run()  # its public MRI study
    at.segmented_control(key="view").set_value("Tests").run()
    tests = at.dataframe[0].value
    mri = tests[tests["Type"] == "Imaging"]["Test"].iloc[0]
    at.session_state[f"picked-{app.case}"] = ("Imaging", None, mri)
    at.run()
    assert "radiology pipeline (MRI)" in shown(at) and not path.findall(shown(at))
    pages = {i.get("url_pathname"): h for h, i in at._registered_pages.items()}
    at._page_hash = pages["feedback"]
    at.run()
    assert "Feedback" in shown(at) and not path.findall(shown(at)) and not at.exception


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
    # the id Chromium gives it: Streamlit splits words at a case change (QA R4-6)
    assert anchor("Lesion contours (MedSAM, breast MRI)") == "lesion-contours-med-sam-breast-mri"

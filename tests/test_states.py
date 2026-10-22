"""Error states, the patient list's order and SOS badge, the sidebar's session block and the
report's cards (docs/ux.md §4): a part that fails says which part and where its method is
described, never a traceback; the list sorts by last update, risk or open SOS alerts."""

import sys

import pytest

from muffle import overview
from tests.appfixture import popovers, shown

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

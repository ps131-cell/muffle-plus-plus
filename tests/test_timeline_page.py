"""The Timeline's version diff under AppTest (the ``app`` fixture, tests/conftest.py): the compare
slider on the viewed version and the one before, a wide comparison folded with its counts, "Open"
on a changed finding, "Compare versions" after time travel, and the version table's row click."""

import pytest

from muffle import version_diff as vd
from tests.appfixture import shown

pytestmark = pytest.mark.filterwarnings("error")  # a warning from a page fails the test
SYN = "SYNTHETIC-001"


def test_the_version_diff_compares_opens_and_follows_time_travel(app):
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    at.segmented_control(key="view").set_value("Timeline").run()
    last = len(at.select_slider(key=f"version-{SYN}").options) - 1
    key = f"diff-{SYN}-{last}-{last + 1}"
    assert at.select_slider(key=key).value == (last - 1, last) and not at.exception
    text = shown(at)
    assert "▲ risk up 14 points" in text and "`46% → 60%`" in text and "beyond" in text
    assert "not a trend: nothing here forecasts" in text
    assert "(+ added, ~ changed, − removed)" in text
    assert all(e.proto.expanded for e in at.expander if "that changed" in e.label)
    # the whole record, v1 to v16: a long list stays folded, its counts in the headers
    at.select_slider(key=key).set_range(0, last).run()  # both ends dragged
    labels = {e.label: e for e in at.expander}
    findings = next(e for name, e in labels.items() if name.startswith("Findings that changed"))
    assert not findings.proto.expanded and not at.exception
    assert "**`v1`** month -40 · Diagnosis → **`v16`**" in shown(at)
    # a narrow comparison inside the spread says so, in gray
    at.select_slider(key=key).set_range(7, 8).run()  # month 1 → month 4: 52% → 50%
    assert ":gray-badge[≈ -2 points: within the model's uncertainty]" in shown(at)
    # "Open" on a changed finding lands on its evidence, as of the later version
    at.select_slider(key=key).set_range(last - 1, last).run()
    opens = [b for b in at.button if (b.key or "").startswith(f"dv-{SYN}-{last - 1}-{last}-f")]
    lab = next(b for b in opens if b.proto.help.startswith("Open its evidence as of v16"))
    lab.click().run()
    assert at.segmented_control(key="view").value in ("Tests", "Report") and not at.exception
    # time travel to v12, then "Compare versions": v11 against v12
    at.session_state[f"version-{SYN}"] = 11
    at.run()
    at.button(key="act-compare").click().run()
    assert at.segmented_control(key="view").value == "Timeline"
    assert at.select_slider(key=f"diff-{SYN}-11-{last + 1}").value == (10, 11)
    assert "▲ risk up 51 points" in shown(at) and "the month-12 model takes over" in shown(at)
    assert not at.exception


def test_the_report_header_says_what_the_version_changed_and_methods_keys_the_shifts(app):
    """QA R4-3 and R4-7: the report's header carries version_diff.version_delta_line (planned
    in #154, never shown), labeled a model inference; the first version and a one-version file
    show none; the Methods page's colour code keys the Timeline's shift marks."""
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    text = shown(at)
    assert "Since the previous version (month 19): 12-month risk +14 points" in text
    assert "Compare versions opens the whole difference on the Timeline" in text
    line = next(m for m in at.markdown if "Since the previous version" in m.value)
    assert "-badge[model inference]" in line.value
    at.session_state[f"version-{SYN}"] = 0
    at.run()
    assert "Since the previous version" not in shown(at) and not at.exception
    at.selectbox(key="patient").select(app.case).run()
    assert "Since the previous version" not in shown(at) and not at.exception
    pages = {i.get("url_pathname"): h for h, i in at._registered_pages.items()}
    at._page_hash = pages["methods"]
    at.run()
    legend = next(m.value for m in at.markdown if "Colour code" in m.value)
    for color, sign, words in vd.SHIFTS.values():
        assert f":{color}-badge[{sign} {words}]" in legend
    assert "not a trend" in legend and not at.exception


def test_a_tcga_file_has_nothing_to_compare_until_an_import(app):
    at = app.new().run()
    at.selectbox(key="patient").select(app.case).run()
    at.segmented_control(key="view").set_value("Timeline").run()
    assert "One report version so far: nothing earlier to compare with" in shown(at)
    assert not [s for s in at.select_slider if (s.key or "").startswith("diff-")]
    assert not at.exception

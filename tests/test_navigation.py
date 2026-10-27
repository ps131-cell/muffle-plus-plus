"""Navigation (docs/ux.md §3): breadcrumbs on every screen, the sticky patient header with its
open SOS count, the way back after an "Open", deep links (?patient, ?view, ?test, ?pointer,
?version) that reopen a screen with the pointer in the Spot panel, and the recently opened
files. The whole app under AppTest (the ``app`` fixture, tests/conftest.py)."""

import hashlib
import json
import re

import pytest

from muffle import evolution
from muffle.workspace import ASSAYS, synthetic_file
from tests.appfixture import APP, popovers, shown

pytestmark = pytest.mark.filterwarnings("error")  # a warning from a page fails the test
SYN = "SYNTHETIC-001"


def texts(at) -> list[str]:
    return [m.value for m in at.markdown]


def test_breadcrumbs_and_the_patient_header(app):
    at = app.new().run()
    assert not at.exception and "**Patients**" in texts(at)  # the list: one crumb, no button
    assert not [b for b in at.button if b.key == "crumb-patients"]
    at.selectbox(key="patient").select(SYN).run()
    assert at.button(key="crumb-patients").label == "Patients" and "Report" in texts(at)
    # the sticky header: the patient, the open SOS count, the views
    assert f"**{SYN}**" in shown(at) and ":red-badge[SOS: 7 open]" in shown(at)
    at.segmented_control(key="view").set_value("Tests").run()
    at.session_state[f"picked-{SYN}"] = ("Lab", 24, "CA 15-3")
    at.run()
    assert "Tests › **CA 15-3, month 24**" in texts(at) and not at.exception
    at.segmented_control(key="view").set_value("Timeline").run()
    assert "Timeline" in texts(at)
    at.button(key="crumb-patients").click().run()  # back to the list
    assert at.selectbox(key="patient").value is None and "**Patients**" in texts(at)
    pages = {i.get("url_pathname"): h for h, i in at._registered_pages.items()}
    at._page_hash = pages["methods"]
    at.run()
    assert "**Methods and validation**" in texts(at) and not at.exception


def test_the_sticky_header_takes_the_themes_own_background(app):
    """The header's background is the app's own in either theme, worked out by the browser's
    CSS (inherited from Streamlit's app root), never a colour picked in Python from
    st.context.theme, which can be stale after a theme change: a black band on a light page."""
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    css = [h.value for h in at.html if "st-key-patient-header" in h.value]
    assert len(css) == 1 and "background-color: inherit" in css[0] and "Canvas" in css[0]
    assert not re.search(r"background[^;{}]*#[0-9a-fA-F]{3,8}", css[0])  # no fixed colour
    # Streamlit wraps the header in a layout wrapper of its own height: the wrapper is what sticks
    assert '[data-testid="stLayoutWrapper"]:has(> .st-key-patient-header)' in css[0]


def test_open_from_the_queue_writes_the_address_and_leads_back(app):
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    at.select_slider(key=f"version-{SYN}").set_value(11).run()  # month 12
    queue = f"queue-{SYN}-11"
    for _ in range(5):
        at.button(key=f"next-{queue}").click().run()
    assert "6/15 · `L4` CA 15-3 rose from 30 to 52" in shown(at)
    at.button(key=f"open-{queue}").click().run()  # the lab workbench, on L4
    assert at.segmented_control(key="view").value == "Tests"
    assert at.selectbox(key=f"{SYN}_spot").value.startswith("L4 · month 11")
    q = at.query_params
    assert (q["test"], q["pointer"], q["version"]) == ("Lab|11|CA 15-3", "L4", "11")
    assert at.button(key="back-queue").label == "← Back to the queue, item 6 of 15"
    at.button(key="back-queue").click().run()  # the queue, on the item it was opened from
    assert at.segmented_control(key="view").value == "Report"
    assert "6/15 · `L4`" in shown(at) and not at.exception
    assert "test" not in at.query_params and "pointer" not in at.query_params
    at.button(key=f"open-{queue}").click().run()
    at.button(key="back-report").click().run()  # the report, without the queue position
    assert at.segmented_control(key="view").value == "Report" and not at.exception


def test_a_deep_link_reopens_the_screen_with_the_pointer(app):
    at = app.new()
    at.query_params.update({"patient": SYN, "view": "Tests", "test": "Lab|11|CA 15-3",
                            "pointer": "L4", "version": "11"})
    at.run()
    assert not at.exception
    assert at.select_slider(key=f"version-{SYN}").value == 11
    assert at.selectbox(key=f"{SYN}_spot").value.startswith("L4 · month 11")
    assert f"Blood and lab workbench · {SYN} · CA 15-3, month 11 · as of month 12" in shown(at)
    # the reader moves on: the link is not applied again
    spot = at.selectbox(key=f"{SYN}_spot")
    other = next(o for o in spot.options if not o.startswith("L4"))
    spot.select(other).run()
    assert at.selectbox(key=f"{SYN}_spot").value == other and not at.exception

    # the Evolution view's pointer opens that hypothesis in its Spot panel
    tl = json.loads((APP.parent / "timeline_synthetic.json").read_text(encoding="utf-8"))
    item = evolution.queue(synthetic_file(tl))[-1]
    ev = app.new()
    ev.query_params.update({"patient": SYN, "view": "Evolution", "pointer": item["pointer"]})
    ev.run()
    assert not ev.exception and ev.session_state[f"evolution-spot-{SYN}"] == item["key"]

    # an address the file can't answer opens the file as usual
    odd = app.new()
    odd.query_params.update({"patient": SYN, "view": "Tests", "test": "Lab|99|nothing",
                             "pointer": "Z9", "version": "999"})
    odd.run()
    assert not odd.exception and "Blood and lab workbench" in shown(odd)


def test_a_dated_test_opens_on_its_own_value(app):
    """A lab or ctDNA test opened without a pointer (a link, the Timeline's Open, a row of the
    tests table) shows its own value in the Spot panel, not the latest (QA round 2)."""
    at = app.new()
    at.query_params.update({"patient": SYN, "view": "Tests", "test": "Lab|11|CA 15-3"})
    at.run()
    assert not at.exception and at.selectbox(key=f"{SYN}_spot").value.startswith("L4 · month 11")
    ct = app.new()
    ct.query_params.update({"patient": SYN, "view": "Tests",
                            "test": "ctDNA (liquid biopsy)|11|ctDNA panel (synthetic series)"})
    ct.run()
    assert not ct.exception and "month 11 ·" in ct.selectbox(key=f"{SYN}_ctdna_spot").value
    tl = app.new().run()
    tl.selectbox(key="patient").select(SYN).run()
    slider = tl.select_slider(key=f"version-{SYN}")
    i = next(k for k, o in enumerate(slider.options) if o.startswith("month 11 "))
    slider.set_value(i).run()
    keys = []
    for n in range(4):  # the Timeline's tests added in this version: open each until the lab's
        tl.segmented_control(key="view").set_value("Timeline").run()
        keys = [b.key for b in tl.button if (b.key or "").startswith(f"new-{SYN}-{i}-t")]
        if n >= len(keys):
            break
        tl.button(key=keys[n]).click().run()
        if "Blood and lab workbench" in shown(tl):
            break
    assert not tl.exception and tl.selectbox(key=f"{SYN}_spot").value.startswith("L4 · month 11")


def test_a_look_here_spot_lands_and_switching_files_drops_the_old_address(app):
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    at.segmented_control(key="view").set_value("Tests").run()
    at.session_state[f"picked-{SYN}"] = ("Lab", 24, "CA 15-3")
    at.run()
    spot = next(b for b in at.button if b.label == "Spot")  # the first look-here item
    spot.click().run()
    assert at.query_params.get("pointer") and at.query_params["test"] == "Lab|24|CA 15-3"
    at.selectbox(key="patient").select(app.case).run()
    assert not at.exception and "pointer" not in at.query_params
    assert at.query_params.get("test", "").split("|")[0] != "Lab"


def series(kind: str, name: str) -> str:
    """A launcher tile's key part, as the app makes it from the test's kind and name."""
    return hashlib.sha1(f"{kind}|{name}".encode()).hexdigest()[:10]


def test_the_tests_launcher_opens_every_test(app):
    """Tests opens on a launcher: a tile per test, grouped by kind, a dated series (CA 15-3 at
    eight months) one tile with a pill per month, each with its look-here count and "Open"; the
    open test's tile says so, and every test is a row of "All tests (n)" too."""
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    at.segmented_control(key="view").set_value("Tests").run()
    assert "**Open a test** · 29 tests in 6 kinds" in shown(at) and not at.exception
    assert "All tests (29)" in [e.label for e in at.expander]
    assert "**CA 15-3** · 8 tests, months -2 to 24" in shown(at)
    assert "**4 items to look at** (month 4, 11, 16, 24)" in shown(at)  # the labs queue()
    lab = next(p for p in at.pills
               if (p.key or "").startswith(f"months-{series('Lab', 'CA 15-3')}-"))
    lab.set_value(11).run()  # a month opens that test, on its own value
    assert at.selectbox(key=f"{SYN}_spot").value.startswith("L4 · month 11")
    assert "Tests › **CA 15-3, month 11**" in texts(at) and at.query_params["test"] == \
        "Lab|11|CA 15-3"
    assert ":blue-badge[:material/arrow_downward: month 11 open below]" in shown(at)
    ctdna = series("ctDNA (liquid biopsy)", "ctDNA panel (synthetic series)")
    next(b for b in at.button if (b.key or "").startswith(f"launch-{ctdna}-")).click().run()
    assert (f"ctDNA monitor (liquid biopsy) · {SYN} · ctDNA panel (synthetic series), month 24"
            in shown(at)) and not at.exception  # a tile's Open: the latest of its series
    # a TCGA file's tests carry no dates: a tile each
    at.selectbox(key="patient").select(app.case).run()
    at.segmented_control(key="view").set_value("Tests").run()
    assert "Genomics workbench" in shown(at) and not at.exception  # opens as before
    rna = series("Data layer", ASSAYS["rna"])
    next(b for b in at.button if (b.key or "").startswith(f"launch-{rna}-")).click().run()
    assert "Expression, methylation and protein" in shown(at) and not at.exception
    assert ":blue-badge[:material/arrow_downward: open below]" in shown(at)


def test_the_files_action_row(app):
    """Under the views, on every view, real buttons with their tooltips: the attention queue
    (on its first item not marked), Import a test, Compare versions, the report's export, the
    reviewer's marks (the Feedback page) and the guide; the queue says what to do next."""
    at = app.new().run()
    at.selectbox(key="patient").select(SYN).run()
    acts = [b for b in at.button if (b.key or "").startswith("act-")]
    assert [b.label.split(" (")[0] for b in acts] == ["Attention queue", "Import a test",
                                                      "Compare versions", "Your marks"]
    assert all(b.help for b in acts) and "How to read this" in popovers(at)
    assert "Export this report (Markdown)" in [b.label for b in at.get("download_button")]
    queue = f"queue-{SYN}-{len(at.select_slider(key=f'version-{SYN}').options) - 1}"
    n = int(at.button(key="act-queue").label.split("(")[1].rstrip(")"))
    assert f"**Next step:** {n} items need a look" in shown(at) and not at.exception
    at.button(key="act-import").click().run()
    assert at.segmented_control(key="view").value == "Import tests" and not at.exception
    at.button(key="act-compare").click().run()
    assert at.segmented_control(key="view").value == "Timeline"
    assert "Compare two versions" in shown(at) and not at.exception
    at.button(key="act-queue").click().run()
    assert at.segmented_control(key="view").value == "Report" and at.session_state[queue] == 0
    at.button(key=f"reviewed-{queue}").click().run()  # the first item marked: the queue moves on
    assert at.button(key="act-queue").label == f"Attention queue ({n - 1})"
    at.segmented_control(key="view").set_value("Tests").run()
    at.button(key="act-queue").click().run()
    assert at.segmented_control(key="view").value == "Report" and at.session_state[queue] == 1
    assert at.button(key="act-marks").label == "Your marks (1)"
    at.button(key="act-marks").click().run()  # the Feedback page, its ledger holding the mark
    assert not at.exception and at.title[0].value == "Feedback"
    one = app.new().run()  # a TCGA file has one version: nothing to compare yet
    one.selectbox(key="patient").select(app.case).run()
    assert one.button(key="act-compare").disabled and not one.exception


def test_recently_opened_files_on_the_patients_page(app):
    at = app.new().run()
    for pid in (SYN, app.case):
        at.selectbox(key="patient").select(pid).run()
        at.button(key="crumb-patients").click().run()
    assert [b.label for b in at.button if (b.key or "").startswith("recent-")] == [app.case, SYN]
    at.button(key=f"recent-{SYN}").click().run()
    assert at.selectbox(key="patient").value == SYN and not at.exception

"""Navigation (docs/ux.md §3): breadcrumbs on every screen, the sticky patient header with its
open SOS count, the way back after an "Open", deep links (?patient, ?view, ?test, ?pointer,
?version) that reopen a screen with the pointer in the Spot panel, and the recently opened
files. The whole app under AppTest (the ``app`` fixture, tests/conftest.py)."""

import json

import pytest

from muffle import evolution
from muffle.workspace import synthetic_file
from tests.appfixture import APP, shown

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


def test_recently_opened_files_on_the_patients_page(app):
    at = app.new().run()
    for pid in (SYN, app.case):
        at.selectbox(key="patient").select(pid).run()
        at.button(key="crumb-patients").click().run()
    assert [b.label for b in at.button if (b.key or "").startswith("recent-")] == [app.case, SYN]
    at.button(key=f"recent-{SYN}").click().run()
    assert at.selectbox(key="patient").value == SYN and not at.exception

"""The guide inside the app (docs/ux.md §3): "How to read this" behind the "?" on every screen,
the four-step walk-through on the Patients page, and the glossary behind every status chip."""

import pytest

from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workbench.grammar import GLOSSARY, WORKBENCH_GUIDE, glossary
from muffle.workspace import PLANNED, VALIDATED
from tests.appfixture import ROOT, popovers

pytestmark = pytest.mark.filterwarnings("error")  # a warning from a page fails the test


def test_every_label_has_its_sentence():
    for label in (OBSERVED, INFERENCE, HYPOTHESIS, "trust", "placeholder", "SOS", PLANNED):
        assert GLOSSARY[label].endswith(".")
    assert glossary("placeholder threshold") == GLOSSARY["placeholder"]
    assert glossary("subtype call: experimentally validated") == GLOSSARY[VALIDATED]
    assert glossary("5 parts planned") == GLOSSARY["parts planned"]
    assert glossary("a label no page has").startswith("A label of this page")
    assert all(shows and cannot for shows, cannot in WORKBENCH_GUIDE.values())


def test_the_walkthrough_guide_and_glossary(app):
    at = app.new().run()
    assert not at.exception
    walk = " ".join(m.value for m in at.markdown)
    assert "First time here? 1 of 4 · Your patients" in walk
    at.button(key="walk-next").click().run()
    assert "2 of 4 · A file opens on its latest report" in " ".join(m.value for m in at.markdown)
    at.button(key="walk-back").click().run()
    assert "1 of 4" in " ".join(m.value for m in at.markdown)
    at.button(key="walk-skip").click().run()  # dismissed for the browser session
    assert not any("First time here?" in m.value for m in at.markdown)
    # "?" on the list: the labels, this screen, the keys
    guide = popovers(at)["?"]
    assert "How to read this" in guide and GLOSSARY[INFERENCE] in guide
    assert WORKBENCH_GUIDE["patients"][0] in guide and "`j` next item" in guide

    at.selectbox(key="patient").select("SYNTHETIC-001").run()
    assert not any("First time here?" in m.value for m in at.markdown)
    labels = popovers(at)
    assert labels[":violet-badge[model inference]"] == GLOSSARY[INFERENCE]  # the report's chips
    assert WORKBENCH_GUIDE["report"][0] in labels["?"]
    at.segmented_control(key="view").set_value("Tests").run()
    at.session_state["picked-SYNTHETIC-001"] = ("Lab", 24, "CA 15-3")
    at.run()
    labels = popovers(at)
    assert labels[":orange-badge[placeholder threshold]"] == GLOSSARY["placeholder"]
    assert WORKBENCH_GUIDE["labs"][1] in labels["?"] and not at.exception
    pages = {i.get("url_pathname"): h for h, i in at._registered_pages.items()}
    at._page_hash = pages["methods"]
    at.run()
    assert WORKBENCH_GUIDE["methods"][0] in popovers(at)["?"] and not at.exception


def test_a_page_on_its_own_explains_its_chips():
    AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
    at = AppTest.from_string(f"""
import json, sys
sys.path[:0] = [{str(ROOT / "app")!r}, {str(ROOT / "src")!r}]
from pathlib import Path
from muffle.workspace import synthetic_file
from workbenches import ctdna
tl = json.loads(Path({str(ROOT / "app" / "timeline_synthetic.json")!r}).read_text("utf-8"))
ctdna.render(synthetic_file(tl))
""", default_timeout=120).run()
    assert not at.exception
    labels = popovers(at)
    assert labels[":red-badge[synthetic]"] == GLOSSARY["synthetic"]
    assert labels[":gray-badge[literature rule]"] == GLOSSARY["literature"]

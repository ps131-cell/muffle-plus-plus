"""Every workbench page follows one skeleton (docs/ux.md), and its empty state says what is
missing and which test would provide it. Each page is rendered on its own through AppTest."""

from pathlib import Path

import pytest

from tests.skeleton import assert_skeleton, headings

AppTest = pytest.importorskip("streamlit.testing.v1").AppTest
ROOT = Path(__file__).resolve().parents[1]
HEAD = f"""
import json, sys
sys.path[:0] = [{str(ROOT / "app")!r}, {str(ROOT / "src")!r}]
from pathlib import Path
from types import SimpleNamespace
from muffle.workspace import Test, case_file, synthetic_file
TL = json.loads(Path({str(ROOT / "app" / "timeline_synthetic.json")!r}).read_text("utf-8"))
SYN = synthetic_file(TL)
CASE = case_file(SimpleNamespace(index=4242, site="site-0", percentile=50.0, group="medium",
                                 age=50.0, stage="II", layers=["clinical"], missing=["rna"],
                                 mutations=None))
"""


def page(body: str):
    at = AppTest.from_string(HEAD + body, default_timeout=180).run()
    assert not at.exception, at.exception
    return at


def text(at) -> str:
    return " ".join(str(e.value) for kind in ("subheader", "markdown", "caption", "info",
                                              "warning") for e in getattr(at, kind))


@pytest.mark.parametrize("workbench, body, missing", [
    ("labs", "from workbenches import labs\nlabs.render(CASE)",
     ["No lab results in this file", "Import tests"]),
    ("ctdna", "from workbenches import ctdna\nctdna.render(CASE)",
     ["No ctDNA in this file", "plasma ctDNA panel"]),
    ("ctdna", "from workbenches import ctdna\nctdna.render(SYN, version=0)",
     ["No ctDNA sample yet as of this version"]),
    ("omics", "from workbenches import omics\nomics.render(SYN)",
     ["No expression, methylation or protein data in this file", "RNA-seq"]),
    ("genomics", "from workbenches import genomics\ngenomics.render(CASE)",
     ["Not sequenced", "Tumor sequencing"]),
    ("slides", "from workbenches import slides\nslides.render(SYN)",
     ["nothing below is this patient's tissue", "scanned H&E section", "Nothing to export"]),
    ("evolution", "from workbenches import evolution\nevolution.render(CASE)",
     ["One timepoint, no dated events", "No observed driver in this file"]),
    ("radiology", "from workbenches import radiology\nradiology.render(CASE)",
     ["No imaging in this file", "Import tests", "Nothing to export"]),
    ("radiology", "from workbenches import radiology\nradiology.render(SYN, version=0)",
     ["No imaging read in the record up to this version"]),
    ("documents", "from workbenches import documents\ndocuments.render(CASE)",
     ["No document in this file yet", "Import tests", "Nothing to export"]),
    ("imports", "from workbenches import imports\nimports.render_view(CASE)",
     ["Nothing imported into this file in this session", "Nothing to export"]),
    ("intake", "from workbenches import imports\n"
               "imports.render_test(CASE, Test('DICOM file', 3, 'scan.dcm', 'queued', 'intake', "
               "'queued', {'header': {'Modality': 'MR'}, 'identifiers_present': []}))",
     ["Queued for the local pipeline", "Nothing to export: nothing was analyzed"]),
])
def test_empty_pages_follow_the_skeleton_and_say_what_is_missing(workbench, body, missing):
    at = page(body)
    parts = assert_skeleton(at, workbench)
    assert parts[0][0] == "title" and parts[0][1].split(" · ")[1] in ("Case 4242",
                                                                       "SYNTHETIC-001")
    shown = text(at)
    for words in missing:
        assert words in shown, (workbench, words)
    assert not any(w in shown.lower() for w in ("hackathon", "demo"))


def test_a_full_page_keeps_the_order_with_counted_details():
    at = page("from workbenches import labs\nlabs.render(SYN, test='CA 15-3, month 24')")
    parts = assert_skeleton(at, "labs")
    assert parts[0] == ("title", "Blood and lab workbench · SYNTHETIC-001 · CA 15-3, month 24")
    details = [h for p, h in parts if p == "details"]
    assert details[0] == "Details" and all(h.endswith(")") for h in details[1:])
    order = headings(at)
    assert order.index("Overview") < order.index("Trends") < order.index("Details") \
        < order.index("Spot panel") < order.index("Model and validation card") \
        < order.index("What this test cannot see") < order.index("Export")
    assert "The full story of one value" in text(at)  # the Spot panel's subtitle


def test_a_page_out_of_order_fails_under_the_tests():
    at = AppTest.from_string(HEAD + """
from workbenches._page import Page
p = Page("labs", SYN)
p.title("implemented")
with p.export():
    pass
with p.overview():
    pass
""", default_timeout=60).run()
    assert at.exception and "breaks the page order" in at.exception[0].message

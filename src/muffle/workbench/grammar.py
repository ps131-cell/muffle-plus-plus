"""The shared grammar of every page (docs/WORKBENCHES.md §1): one badge color per label and one
name per recurring section, so the evidence chips (observed, model inference, hypothesis), the
status badges (implemented, experimentally validated, planned) and placeholders read the same on
the report, every workbench and the Methods and validation page. Pure strings, no Streamlit."""

from __future__ import annotations

import re

from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workspace import IMPLEMENTED, PLANNED, VALIDATED

COLORS = {OBSERVED: "blue", INFERENCE: "violet", HYPOTHESIS: "orange",
          IMPLEMENTED: "blue", VALIDATED: "green", PLANNED: "gray"}
OVERVIEW = "Overview"                     # one paragraph, the look-here queue and search
LOOK_HERE = "Look here"                   # the workbench's queue: worth a look, never a verdict
DETAILS = "Details"                       # collapsed sections, each with its count
SPOT = "Spot panel"                       # one value, variant, tile or lesion in full
CARD = "Model and validation card"       # the method, its numbers, sources and known failures
CANNOT_SEE = "What this test cannot see"  # and which test could
EXPORT = "Export"                         # buttons read "Download the <what> (<format>)"
SPOT_SUBTITLE = ("The full story of one value, variant, tile or lesion: pick it here, or click "
                 "it in the picture or the look-here list.")
# The skeleton of every workbench page (docs/ux.md), in order: the title (the workbench, the
# patient, the test), the status chips, the overview, the picture (map, viewer, chart or
# table; its heading names it), the details, the Spot panel, the card, what the test cannot
# see, the export. Details repeat (one collapsed section each); every other part comes once.
SKELETON = ("title", "chips", "overview", "picture", "details", "spot", "card", "cannot_see",
            "export")
HEADINGS = {"overview": OVERVIEW, "details": DETAILS, "spot": SPOT, "card": CARD,
            "cannot_see": CANNOT_SEE, "export": EXPORT}
REQUIRED = ("title", "chips", "overview", "card", "cannot_see", "export")  # on every page
WORKBENCHES = {  # the page titles, one name per workbench
    "labs": "Blood and lab workbench", "ctdna": "ctDNA monitor (liquid biopsy)",
    "genomics": "Genomics workbench", "slides": "Pathology slide workbench",
    "omics": "Expression, methylation and protein workbench",
    "radiology": "Radiology workbench", "documents": "Clinical documents workbench",
    "evolution": "Tumor evolution and treatment evidence", "imports": "Import tests",
    "intake": "Imported image, queued"}


def count_label(name: str, count=None) -> str:
    """A details section's header: its name and how many items it holds ("Satellite islands
    (19)"); ``count`` may be a short phrase ("3 excluded") or None."""
    return name if count is None or count == "" else f"{name} ({count})"


def title(workbench: str, patient: str, test: str | None = None, as_of: str | None = None) -> str:
    """A workbench page's one-line title: the workbench, the patient and the test opened
    ("Pathology slide workbench · Case 299 · Diagnostic H&E section"), and the report version
    when it isn't the latest."""
    return " · ".join([WORKBENCHES.get(workbench, workbench), patient,
                       *([test] if test else []), *([f"as of {as_of}"] if as_of else [])])


def chip(label: str, color: str | None = None) -> str:
    """A Markdown badge. A label naming a placeholder is always orange, so a placeholder never
    looks validated; other labels take the shared color, then ``color``, then gray."""
    if "placeholder" in label:
        color = "orange"
    return f":{COLORS.get(label) or color or 'gray'}-badge[{label}]"


VARIANT_MARKS = re.compile(r"(?<=\d)\*|(?<=fs)\*|(?<=\d)_(?=\w)")  # not URLs' evidence_items


def esc(text) -> str:
    """Text for Markdown with the emphasis characters of variant names escaped: a stop after a
    position ("TP53 R196*"), a frameshift ("RUNX1 D96Gfs*15") and an underscore inside a word
    ("TP53 X225_splice") would otherwise turn into italics. Emphasis that is meant (**bold**,
    *italic*) is left alone, so a note written in Markdown passes through too."""
    return VARIANT_MARKS.sub(lambda m: "\\" + m.group(0), str(text))

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
CARD = "Model and validation card"       # the method, its numbers, sources and known failures
CANNOT_SEE = "What this test cannot see"  # and which test could
EXPORT = "Export"                         # buttons read "Download the <what> (<format>)"


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

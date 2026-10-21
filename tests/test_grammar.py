"""One badge color per label on every page; variant names survive Markdown."""

from muffle.workbench.grammar import chip, esc
from muffle.workspace import IMPLEMENTED, PLANNED, VALIDATED


def test_shared_colors_win_and_placeholders_are_orange():
    assert chip(IMPLEMENTED, "green") == ":blue-badge[implemented]"  # a page can't recolor it
    assert chip(VALIDATED) == ":green-badge[experimentally validated]"
    assert chip(PLANNED) == ":gray-badge[planned]"
    assert chip("placeholder threshold", "green") == ":orange-badge[placeholder threshold]"
    assert chip("example slide", "violet") == ":violet-badge[example slide]"
    assert chip("anything else") == ":gray-badge[anything else]"


def test_variant_names_keep_their_asterisks():
    assert esc("RUNX1 D96Gfs*15, TP53 R196*") == r"RUNX1 D96Gfs\*15, TP53 R196\*"
    assert esc("TP53 X225_splice") == r"TP53 X225\_splice"
    note = ("- [Observed] **PIK3CA H1047R**, *italic*, KMT2C Q2018Sfs*7 and CDH1 K668*; "
            "https://civicdb.org/links/evidence_items/12045")
    assert esc(note) == (r"- [Observed] **PIK3CA H1047R**, *italic*, KMT2C Q2018Sfs\*7 and "
                         r"CDH1 K668\*; https://civicdb.org/links/evidence_items/12045")

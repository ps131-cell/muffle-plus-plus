"""The workbench pages' first-time reader aids (app/workbenches/_howto.py): the look-here items
as instructions with a reason, a target and the consequence, the reason shortened without its
parentheses, the "How to use this page" line folding away after the first visit, and the typed
lab values of the import dialog read as the intake's CSV."""

import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "app")]

from workbenches._howto import instruct, reason  # noqa: E402
from workbenches.imports import typed_csv  # noqa: E402

from muffle import imports as intake  # noqa: E402


def item(**kw) -> dict:
    return {"pointer": "L4", "what": "CA 15-3 52 U/mL at month 11: above limit, rising",
            "why": "rising: at least 25% above the previous value (threshold: EGTM (Hayes "
                   "1986)); unconfirmed until a second specimen within a month",
            "evidence": "observed", "trust": "moderate", "consequence": 2,
            "focus": {"marker": "ca153", "month": 11}, "key": "k", **kw}


def test_an_item_reads_as_an_instruction_with_reason_target_and_consequence():
    x = instruct([item()])[0]
    assert x["what"] == ("Look at CA 15-3 52 U/mL at month 11: above limit, rising. *Why:* "
                         "rising: at least 25% above the previous value; unconfirmed until a "
                         "second specimen within a month. *Consequence:* may change care. "
                         "Opens L4 in the Spot panel.")
    assert x["why"] == item()["why"] and x["key"] == "k"  # the full reason stays on hover
    watch = instruct([item(what="Watch for PTEN loss", pointer=None, focus=None,
                           consequence=1, why="")])[0]["what"]
    assert watch == "Watch for PTEN loss. *Consequence:* worth a look."


def test_the_reason_drops_parentheses_and_stops_at_a_word():
    assert reason("a (b (c) d) e; f (g)") == "a e; f"
    long = reason("word " * 60)
    assert len(long) <= 162 and long.endswith(" …") and "  " not in long


def test_how_to_is_open_on_the_first_visit_and_folded_after_another_page():
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(f"""
import sys
sys.path[:0] = [{str(ROOT / "app")!r}]
import streamlit as st
from workbenches._howto import how_to
how_to(st.session_state.get("page", "labs"), "Trends draws each analyte.")
""", default_timeout=180).run()
    assert at.markdown[0].value.startswith(":material/lightbulb: **How to use this page:**")
    at.session_state["page"] = "ctdna"
    at.run()
    at.session_state["page"] = "labs"
    at.run()
    assert [e.label for e in at.expander] == ["How to use this page"] and not at.markdown[1:]


def test_typed_lab_values_are_read_as_the_intakes_csv():
    rows = pd.DataFrame([{"month": 25, "marker": "CA 15-3", "value": 44.0, "unit": "U/mL",
                          "reference interval": "<30"},
                         {"month": 25, "marker": "CEA", "value": float("nan"), "unit": "ng/mL",
                          "reference interval": ""}])
    ok, bad = intake.parse_labs(typed_csv(rows), 24)
    assert [(r["marker"], r["value"], r["limit"]) for r in ok] == [("CA 15-3", 44.0, 30.0)]
    assert not bad  # the row without a value is not a row
    assert typed_csv(rows.iloc[1:]) is None

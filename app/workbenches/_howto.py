"""What every workbench page tells a first-time reader, in one place: the "How to use this page"
line under the title, the look-here items phrased as instructions with their reason, target and
consequence, and the pin beside a Spot panel's review mark. Kept out of ``_page.py`` (the shell's
skeleton helper) so the two can change apart."""

from __future__ import annotations

import streamlit as st

CONSEQUENCE = {3: "changes the picture of the disease", 2: "may change care", 1: "worth a look"}
VERBS = ("Look", "Watch", "Check", "Compare", "Read", "Open")


JUMP = ("[Model and validation card](#model-and-validation-card) · [What this test cannot "
        "see](#what-this-test-cannot-see) · [Export](#export)")


def how_to(workbench: str, text: str, spot: bool = True) -> None:
    """One line under the title: what the picture shows, what the queue means, where the Spot
    panel is. Open during the page's first visit in the browser session; once the reader has
    been on another workbench, folded into a "How to use this page" expander. Under it, always,
    links to the page's lower parts (the Spot panel, the card, what it cannot see, export)."""
    ss = st.session_state
    seen = ss.setdefault("_how_to_seen", set())
    last = ss.get("_how_to_last")
    if last and last != workbench:
        seen.add(last)
    ss["_how_to_last"] = workbench
    if workbench in seen:
        with st.expander("How to use this page"):
            st.markdown(text)
    else:
        st.markdown(f":material/lightbulb: **How to use this page:** {text}")
    st.caption("Jump to: " + ("[Spot panel](#spot-panel) · " if spot else "") + JUMP)


def reason(why: str, limit: int = 160) -> str:
    """The reason of a look-here item in a line: its top-level clauses, without the
    parentheses (thresholds and citations stay on hover), cut at a word near ``limit``."""
    depth, out = 0, []
    for ch in why:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(depth - 1, 0)
        elif depth == 0:
            out.append(ch)
    text = " ".join("".join(out).split()).replace(" ;", ";").replace(" ,", ",").strip(" ;,")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0].rstrip(";,: ") + " …"
    return text


def instruct(items: list[dict]) -> list[dict]:
    """The look-here items as instructions: "Look at CA 15-3 52 U/mL at month 11: above limit,
    rising. Why: … Consequence: may change care. Opens L4 in the Spot panel." The item's own
    fields are kept (its key, mark and full why on hover); only ``what`` is rewritten, on a
    copy, so the report's attention queue keeps its own wording."""
    out = []
    for x in items:
        what, first = x["what"], x["what"].split(" ", 1)[0]
        if what.startswith(VERBS):
            verb = ""
        elif first.istitle() and first.isalpha():  # a sentence ("Two ploidy estimates disagree")
            verb, what = "Check: ", what[:1].lower() + what[1:]
        else:  # a named thing: a marker, a variant, a gene
            verb = "Look at "
        x = {**x, "what": what}
        why = reason(x["why"]) if x["why"] else ""
        target = (f" Opens {x['pointer']} in the Spot panel." if x.get("focus") and x["pointer"]
                  else " Opens in the Spot panel." if x.get("focus") else "")
        why = why if not why or why.endswith("…") else why + "."
        out.append({**x, "what": f"{verb}{x['what']}." + (f" *Why:* {why}" if why else "")
                    + f" *Consequence:* {CONSEQUENCE[x['consequence']]}." + target})
    return out


def pin_toggle(key: str, what: str, label: str = "Pin to the top of the report") -> None:
    """A finding's pin, beside its review mark: pinned findings head the report's "Pinned and
    reviewed" list (the shell's ``pins`` store, finding key -> what it is)."""
    pins = st.session_state.setdefault("pins", {})

    def flip() -> None:
        if pins.pop(key, None) is None:
            pins[key] = what

    st.session_state[f"pin-{key}"] = key in pins  # from the store: a pin made elsewhere shows
    st.checkbox(label, key=f"pin-{key}", on_change=flip,
                help="Pinned findings head the report's \"Pinned and reviewed\" list, with your "
                     "review marks; kept for this browser session")

"""The skeleton every workbench page follows (docs/ux.md), drawn by one helper so that the order
and the headings are the same on every page and a reader who has learned one page can read the
next:

    title: the workbench · the patient · the test
    status chips, then the page's provenance line and honesty labels
    Overview: one paragraph, the look-here queue, search
    the picture: map, viewer, chart or table (its heading names it)
    Details: collapsed sections, each with its count ("Satellite islands (19)")
    Spot panel: one value, variant, tile or lesion in full
    Model and validation card
    What this test cannot see
    Export

``Page`` opens each part in the current container (``muffle.workbench.grammar.SKELETON``). Parts
come in that order, details may repeat; a part out of order raises ``SkeletonError`` when
MUFFLE_STRICT_PAGES=1 (the tests set it) and is otherwise drawn as asked, so a page never breaks
in front of a clinician. The parts drawn are recorded in ``st.session_state["page_parts"]``
(workbench -> [(part, heading)]) for the heading-order test. ``land`` points a workbench's own
widgets at a finding (the report's "Open", a look-here item's "Spot"), so both share one rule.
"""

from __future__ import annotations

import hashlib
import os
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import streamlit as st

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:  # a page run on its own still finds the app's modules
    sys.path.insert(0, str(APP))

from guide import chip_row  # noqa: E402
from muffle.workbench.grammar import (  # noqa: E402
    DETAILS,
    HEADINGS,
    LOOK_HERE,
    SKELETON,
    SPOT_SUBTITLE,
    chip,
    count_label,
    esc,
    title,
)
from muffle.workspace import TRUST  # noqa: E402

TRUST_COLORS = {"strong": "green", "moderate": "orange", "weak": "red"}
EVIDENCE = ("observed", "model inference", "hypothesis")


class SkeletonError(AssertionError):
    """A page drew a part of the skeleton out of its order."""


def strict() -> bool:
    return os.getenv("MUFFLE_STRICT_PAGES") == "1"


def test_label(test) -> str | None:
    """The opened test in words: "CA 15-3, month 11"; None without one."""
    if test is None:
        return None
    if isinstance(test, str):
        return test
    return test.name + ("" if test.month is None else f", month {test.month}")


def chips(*labels: str, colors: dict | None = None) -> None:
    """One row of status chips in the shared grammar's colors (placeholders orange)."""
    st.caption(" ".join(chip(label, (colors or {}).get(label)) for label in labels if label))


class Page:
    """One workbench page: ``Page("labs", pf, test, version)``, then its parts in order."""

    def __init__(self, workbench: str, pf, test=None, version: int | None = None):
        self.workbench, self.pf = workbench, pf
        last = len(pf.versions) - 1
        self.version = last if version is None else version
        self.as_of = None if self.version == last else pf.versions[self.version].label
        self.test = test_label(test)
        self.parts: list[tuple[str, str]] = []
        st.session_state.setdefault("page_parts", {})[workbench] = self.parts

    # --- order -----------------------------------------------------------------------------
    def _enter(self, part: str, heading: str) -> None:
        rank = SKELETON.index(part)
        if self.parts:
            prev = SKELETON.index(self.parts[-1][0])
            if rank < prev or (rank == prev and part != "details"):
                msg = (f"{self.workbench}: '{part}' after '{self.parts[-1][0]}' breaks the page "
                       f"order {' → '.join(SKELETON)}")
                if strict():
                    raise SkeletonError(msg)
        self.parts.append((part, heading))

    def _heading(self, part: str, heading: str | None = None) -> str:
        text = heading or HEADINGS[part]
        self._enter(part, text)
        st.markdown(f"#### {text}")
        return text

    # --- the parts -------------------------------------------------------------------------
    def title(self, *labels: str, colors: dict | None = None) -> None:
        """The one-line title and the status chips under it; a click on a chip says what it
        means (``guide.chip_row``)."""
        text = title(self.workbench, self.pf.id, self.test, self.as_of)
        self._enter("title", text)
        st.subheader(text)
        self._enter("chips", " ".join(labels))
        chip_row(*labels, colors=colors, key=f"chips-{self.workbench}")

    @contextmanager
    def overview(self):
        self._heading("overview")
        yield

    def look_here(self, items: list[dict], *, empty: str = "Nothing to look at in this "
                  "version.", land=None, limit: int = 8, more: str | None = None) -> None:
        """The workbench's look-here queue (its ``queue()`` items, ``workspace.look``): the
        pointer, what, its evidence label, trust and review mark, the reason on hover, and
        "Spot", which lands on the pointer where the page can (``land(focus)``). Strongest
        first (consequence × trust), then the latest."""
        reviews = st.session_state.get("reviews", {})
        order = sorted(items, key=lambda x: (-x["consequence"] * TRUST[x["trust"]],
                                             -(x["month"] if x["month"] is not None else -999)))
        st.markdown(f"**{LOOK_HERE}** · {len(order)} item{'' if len(order) == 1 else 's'}, "
                    "worth a look, never a verdict")
        if not order:
            st.caption(empty)
            return
        for n, x in enumerate(order[:limit]):
            done = reviews.get(x["key"])
            text = ((f"`{x['pointer']}` " if x["pointer"] else "") + esc(x["what"]) + " · "
                    + " ".join(chip(e) for e in EVIDENCE if e in x["evidence"])
                    + f" :{TRUST_COLORS[x['trust']]}-badge[trust: {x['trust']}]"
                    + (f" · ✓ {done['mark']}" if done else ""))
            if land is not None and x.get("focus"):
                line, act = st.columns([9, 1], vertical_alignment="center")
                line.markdown(text, help=x["why"] or None)
                h = hashlib.sha1(x["key"].encode()).hexdigest()[:10]
                act.button("Spot", key=f"look-{self.workbench}-{h}-{n}", on_click=self._spot,
                           args=(land, x), help="Open it in the Spot panel below")
            else:
                st.markdown(text, help=x["why"] or None)
        if len(order) > limit:
            st.caption(f"{len(order) - limit} more" + (f" in {more}" if more else "") + ".")

    def _spot(self, land, x: dict) -> None:
        """A look-here item's "Spot": land on it, and let the address carry its pointer."""
        land(x["focus"])
        ss = st.session_state
        view = ss.get("view")
        ss["_pointer"] = {"pid": self.pf.id, "view": view, "pointer": x["pointer"],
                          "test": ss.get("_test_shown") if view == "Tests" else None}

    @contextmanager
    def picture(self, heading: str, caption: str | None = None):
        """The page's main view; its heading names it ("Trends", "Slide viewer")."""
        self._heading("picture", heading)
        if caption:
            st.caption(caption)
        yield

    def details(self, name: str, count=None, *, key: str | None = None, lazy: bool = False,
                expanded: bool = False):
        """One collapsed details section with its count in the header. ``lazy``: its content
        runs only while it is open (check the returned expander's ``.open``)."""
        label = count_label(name, count)
        if not any(p == "details" for p, _ in self.parts):
            self._heading("details", DETAILS)
            st.caption("Each section opens with a click; the number is how many items it holds.")
        self._enter("details", label)
        if lazy:
            return st.expander(label, expanded=expanded, key=key, on_change="rerun")
        return st.expander(label, expanded=expanded, key=key)

    @contextmanager
    def spot(self, subtitle: str = SPOT_SUBTITLE):
        self._heading("spot")
        st.caption(subtitle)
        yield

    @contextmanager
    def card(self):
        self._heading("card")
        yield

    @contextmanager
    def cannot_see(self, lines: list[str] | tuple = ()):
        self._heading("cannot_see")
        if lines:
            st.markdown("\n".join(f"- {line}" for line in lines))
        yield

    @contextmanager
    def export(self, empty: str | None = None):
        """The page's downloads; ``empty`` says why there is nothing to download."""
        self._heading("export")
        if empty:
            st.caption(empty)
        yield


def queue_items(name: str, pf, version: int | None, compute) -> list[dict]:
    """A workbench's look-here items (``compute()``, its module's pure ``queue``), once per
    browser session, file state and version: a click inside a page reruns the whole page, and
    the items do not change with it (marks are read when drawn)."""
    memo = st.session_state.setdefault("_queues", {})
    key = (name, pf.id, len(pf.versions), version)
    if key not in memo:
        memo[key] = compute()
    return memo[key]


# --- landing on a finding ------------------------------------------------------------------

def land(pf, i: int, focus: dict) -> None:
    """Set the opened workbench's own widget state so it opens on the finding ``focus`` names
    (``workspace.look``'s focus): the lab value's Spot panel, the variant, the gene, the slide
    tile, the omics finding, the document's sentence, the imaging site.
    ponytail: these are the pages' widget keys; a page that renames one opens at its top
    instead (a pure focus() per page would carry this if pages multiply)."""
    ss = st.session_state
    if "marker" in focus:  # labs: the Spot panel's value
        from muffle.workbench.labs import file_rows
        from workbenches import labs

        row = next((r for r in file_rows(pf, i)
                    if (r["key"], r["month"]) == (focus["marker"], focus["month"])), None)
        if row:
            ss[f"{pf.id}_spot"] = labs._lab(row)
    if "variant" in focus:  # genomics: the variant browser narrowed to it, its Spot panel below
        ss[f"genomics-{pf.id}-{i}-search"] = focus["variant"]
        ss[f"genomics-{pf.id}-{i}-spotmode"] = "Variant"
    if "gene" in focus:  # genomics: the copy-number landscape's Spot panel on the gene
        ss[f"genomics-{pf.id}-{i}-gene"] = focus["gene"]
        ss[f"genomics-{pf.id}-{i}-spotmode"] = "Gene"
    if "slide" in focus:  # slides: the section, then the pointer in its Spot panel and viewer
        ss[f"{pf.id}-section"] = focus["slide"]
        if "tile" in focus:
            k = f"{pf.id}|{focus['slide']}"
            ss[f"{k}-pick"], ss[f"{k}-spot"] = f"{focus['pointer']} · {focus['tile']}", ""
            row, col = (int(v) for v in focus["tile"][1:].split("c"))
            ss[f"{k}-goto"] = {"slide": focus["slide"], "row": row, "col": col,
                               "nonce": datetime.now().timestamp()}
    if "omics" in focus:  # omics: the finding in its Spot panel
        ss[f"omics-spot-{pf.id}"] = focus["omics"]
    if "doc" in focus:  # documents: the document at the sentence
        ss[f"docs-jump-{pf.id}"] = (focus["doc"], tuple(focus["sentence"]))
    if "site" in focus:  # radiology: the lesion table's Spot panel on the site
        ss[f"rad-site-{pf.id}"] = focus["site"]
    if "candidate" in focus:  # radiology: the study's candidate in the viewer and Spot panel
        ss[f"rad-{pf.id}-{focus['study']}-cand"] = focus["candidate"]
    if "evolution" in focus:  # evolution: the watched event in its Spot panel
        ss[f"evolution-spot-{pf.id}"] = focus["evolution"]
    if "ctdna" in focus:  # ctDNA: the sample and variant in its Spot panel
        from muffle.workbench.ctdna import file_series
        from workbenches import ctdna

        row = next((r for r in file_series(pf, i)[0]
                    if (r["variant"], r["month"]) == (focus["ctdna"], focus["month"])), None)
        if row:
            ss[f"{pf.id}_ctdna_spot"] = ctdna._label(row)

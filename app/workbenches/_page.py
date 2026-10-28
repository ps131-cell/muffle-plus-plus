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

The instrument's pieces (docs/ux.md §8), one look on every page: ``table`` (a finding list:
dense rows, values, ids, dates and variants in monospace, labels as chips, its provenance
under it; a grid that sorts when the list is long or a row click opens it), ``strip`` (a row of
numbers instead of metric tiles) and ``empty`` (what is missing and what would fill it).
"""

from __future__ import annotations

import hashlib
import html
import os
import re
import sys
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

APP = Path(__file__).resolve().parents[1]
if str(APP) not in sys.path:  # a page run on its own still finds the app's modules
    sys.path.insert(0, str(APP))

from guide import chip_row  # noqa: E402
from navigation import PAGES  # noqa: E402
from muffle.workbench.grammar import (  # noqa: E402
    COLORS,
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
from muffle.overview import IMPACT_COLORS, LEVEL_COLORS  # noqa: E402
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


def line_and_action():
    """A line of text with its button or popover at the right end, as ``(line, action)``, a
    drop-in for ``st.columns([10, 1])``: the text wraps and the button keeps its label whole
    (a fixed column cut "Open" to "O…" at 800 px)."""
    row = st.container(horizontal=True, vertical_alignment="center", gap="small")
    return row.container(), row


def chips(*labels: str, colors: dict | None = None) -> None:
    """One row of status chips in the shared grammar's colors (placeholders orange)."""
    st.caption(" ".join(chip(label, (colors or {}).get(label)) for label in labels if label))


# --- the instrument's pieces: finding tables, number strips, empty states ---------------------

# columns set in monospace by their name (any numeric column too): values, ids, dates, variants
MONO = {"pointer", "month", "months", "value", "values", "variant", "vaf", "z", "z-score", "id",
        "eid", "date", "when", "copies", "beta", "previous", "due_by", "due by", "started",
        "months_after", "per month", "change from previous", "change from nadir", "pmid", "nct",
        "cohort percentile", "percentile"}
CHIPS = {"evidence", "status", "label", "labels", "evidence label"}  # columns of label chips
GRID_ROWS, GRID_COLUMNS = 25, 12  # a longer or wider list is a grid: it scrolls and sorts
MD_LEAD = re.compile(r"^(\s*)([#>+*-]|\d+[.)])(?=\s|$)")  # a cell that would open a list
NO_DATA = {"", "nan", "NaT", "<NA>"}  # a missing value: an empty cell
LONG = re.compile(r"\S{22,}")  # a token too long for a column: a DOI, a chain of units


def _breakable(text: str) -> str:
    """A long token may break after / . : _ = ; or - (a zero-width space there), so a DOI does not
    push its column wider than the table's box; links are left whole."""
    return LONG.sub(lambda m: m.group(0) if "http" in m.group(0) or "](" in m.group(0)
                    else re.sub(r"(?<=[/.:_=;-])", "​", m.group(0)), text)


def _chip_color(text: str, colors: dict | None = None) -> str | None:
    """A chip's colour: the page's own (``colors``), else the grammar's by the label the text
    starts with, a CIViC level's (A–B green, C–E orange) or an Ensembl VEP severity's."""
    if colors and text in colors:
        return colors[text]
    if text.startswith("synthetic"):
        return "red"
    return next((c for k, c in COLORS.items() if text.startswith(k)), None) or \
        LEVEL_COLORS.get(text) or IMPACT_COLORS.get(text.upper())


def _labels(text) -> list[str]:
    """A cell's labels: "observed (mutation), hypothesis (evidence)" is two, "implemented, not
    validated" one (it is split only where every part starts with a known label)."""
    text = "" if text is None or str(text) in NO_DATA else str(text).strip()
    parts = [p.strip() for p in re.split(r"[;,] ", text) if p.strip()]
    if len(parts) > 1 and all(_chip_color(p) or "placeholder" in p for p in parts):
        return parts
    return [text] if text else []


def _cell(v, mono: bool, chips: bool, link: str | None = None,
          colors: dict | None = None, percent: bool = False) -> str:
    """A value for a static table's Markdown cell: chips as badges, mono as code, a link as its
    ``link`` text, a share as a percent, the rest with the characters Markdown would read as
    emphasis, math or a list escaped."""
    if chips:
        return " ".join(chip(x, _chip_color(x, colors)) for x in _labels(v))
    if v is None or isinstance(v, float) and v != v:
        return ""
    if link is not None:  # a link's text, or a pattern whose group names it (as LinkColumn's)
        found = re.search(link, str(v)) if "(" in link else None
        text = found.group(1) if found else link
        return f"[{text}]({v})" if str(v).startswith("http") else ""
    if percent and isinstance(v, (int, float)) and not isinstance(v, bool):
        text = f"{100 * v:.2f}".rstrip("0").rstrip(".") + "%"  # as the grid's "percent" shows it
    elif isinstance(v, bool):
        text = "yes" if v else "no"
    elif isinstance(v, float):  # up to 4 decimals as the grid shows them; tiny ones in e-notation
        text = (f"{v:.2g}" if 0 < abs(v) < 1e-3 else f"{v:.6g}" if abs(v) >= 1e6
                else f"{v:.4f}".rstrip("0").rstrip("."))
    else:
        text = str(v)
    if text in NO_DATA:
        return ""
    if mono:
        tick = "``" if "`" in text else "`"
        return f"{tick}{text}{tick}"
    return _breakable(MD_LEAD.sub(r"\1\\\2", esc(text).replace("$", "\\$").replace("~", "\\~")))


def table(data, *, mono=(), chips=(), caption: str | None = None, empty: str | None = None,
          grid: bool = False, key: str | None = None, on_select=None,
          column_config: dict | None = None, height: int | None = None, plain=(),
          links: dict | None = None, colors: dict | None = None, percent=()):
    """A finding list, densely (docs/ux.md §8.1): no index, compact rows, the values, pointers,
    months, ids and variants in monospace (``MONO`` by column name, every numeric column, and
    ``mono``), the evidence and status columns as chips (``CHIPS`` and ``chips``; the grammar's
    colours, CIViC levels' and VEP severities', or the page's ``colors``), ``links`` as
    {column: the link's text}, ``percent`` columns (shares) as percents, ``plain`` columns left
    as text, and its one-line provenance ``caption`` under it. A short, narrow list is a static
    table (its text wraps); with ``grid`` (it sorts), a row click (``on_select``, ``key``), more
    than ``GRID_ROWS`` rows or more than ``GRID_COLUMNS`` columns it is Streamlit's grid (one
    line a row, it scrolls), its chips as coloured pills. ``empty`` is said when there is no
    row. Returns the grid's selection state, else None."""
    df = data if isinstance(data, pd.DataFrame) else pd.DataFrame(data)
    if df.empty:
        if empty:
            st.caption(empty)
        return None
    links = links or {}
    names = {c: str(c).lower() for c in df.columns}
    chip_cols = {c for c in df.columns if names[c] in CHIPS or c in chips} - {*plain, *links}
    mono_cols = {c for c in df.columns if c not in chip_cols and c not in plain and (
        names[c] in MONO or c in mono or (pd.api.types.is_numeric_dtype(df[c])
                                          and not pd.api.types.is_bool_dtype(df[c])))}
    out = None
    if grid or on_select is not None or len(df) > GRID_ROWS or len(df.columns) > GRID_COLUMNS:
        shown, cfg = df.copy(), {}
        for c in chip_cols:  # pills in the labels' colours
            shown[c] = [_labels(v) for v in shown[c]]
            options = sorted({x for v in shown[c] for x in v})
            cfg[c] = st.column_config.MultiselectColumn(
                str(c), options=options, color=[_chip_color(x, colors) or (
                    "orange" if "placeholder" in x else "gray") for x in options])
        cfg.update({c: st.column_config.LinkColumn(str(c), display_text=t)
                    for c, t in links.items()})
        cfg.update({c: st.column_config.NumberColumn(str(c), format="percent") for c in percent})
        cfg.update(column_config or {})
        kw = {"key": key, "on_select": on_select, "selection_mode": "single-row"} \
            if on_select is not None else {"key": key}
        out = st.dataframe(shown, hide_index=True, width="stretch", row_height=30,
                           column_config=cfg, height=height or "auto", **kw)
    else:
        shown = pd.DataFrame({str(c): [_cell(v, c in mono_cols, c in chip_cols, links.get(c),
                                             colors, c in percent) for v in df[c]]
                              for c in df.columns})
        st.table(shown, hide_index=True, border="horizontal", height=height or "content")
    if caption:
        st.caption(caption)
    return out


def strip(*stats) -> None:
    """A row of numbers instead of metric tiles: each stat ``(label, value[, note[, help]])``,
    the label small, the value in monospace with its note (a unit, a z-score) after it, the help
    (its source or method) on hover. It wraps on a narrow screen. A number whose change carries
    meaning (an arrow, a colour) stays Streamlit's own ``st.metric``."""
    def h(x) -> str:
        return html.escape(str(x), quote=True).replace("$", "&#36;")

    cells = []
    for s in stats:
        label, value, note, tip = (*s, "", "")[:4]
        tip = f' title="{h(tip)}"' if tip else ""
        note = f'<span class="mf-stat-note">{h(note)}</span>' if note else ""
        cells.append(f'<div class="mf-stat"{tip}><div class="mf-stat-label">{h(label)}</div>'
                     f'<div class="mf-stat-value">{h(value)}{note}</div></div>')
    st.markdown('<div class="mf-strip">' + "".join(cells) + "</div>", unsafe_allow_html=True)


def empty(text: str, icon: str = ":material/inbox:") -> None:
    """A workbench or a part with nothing to show: what is missing and what would fill it, in
    one quiet card, the same on every page."""
    st.info(text, icon=icon)


class Page:
    """One workbench page: ``Page("labs", pf, test, version)``, then its parts in order."""

    def __init__(self, workbench: str, pf, test=None, version: int | None = None):
        import charts  # noqa: F401 - the app's chart theme, enabled before this page draws one

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
                line, act = line_and_action()
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
        if "methods" in PAGES:  # a page drawn on its own (its tests) has no app around it
            st.page_link(PAGES["methods"], label="Methods and validation",
                         icon=":material/fact_check:", help="How every model and rule of the app "
                         "was validated: its numbers, sources and known failures")
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

def dated_focus(t) -> dict | None:
    """Where a dated lab or ctDNA test opens when nothing else is asked (a row of the tests
    table, a link without ?pointer, the Timeline's "Open"): on its own value, not the latest
    one (QA round 2: "CA 15-3, month 11" opened with month 24 in the Spot panel)."""
    if t.workbench == "labs" and "marker" in t.details:
        return {"marker": t.details["marker"], "month": t.month}
    if t.workbench == "ctdna" and t.month is not None:
        return {"ctdna": None, "month": t.month}
    return None


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

        row = next((r for r in file_series(pf, i)[0] if r["month"] == focus["month"]
                    and focus["ctdna"] in (None, r["variant"])), None)  # None: the sample's first
        if row:
            ss[f"{pf.id}_ctdna_spot"] = ctdna._label(row)

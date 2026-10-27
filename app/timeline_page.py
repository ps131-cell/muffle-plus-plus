"""The patient file's Timeline view (docs/timeline.md): the record in lanes on one month axis, time
travel from any point, what the viewed version brought, the risk with the record beside it, every
version in a table and two versions side by side.

The shell calls ``render`` from its Timeline view and ``banner`` under the report version slider.
Time travel sets that slider (``version-<file id>``), so the report, the tests, the attention queue
and this page re-open as they were at that version. The data come from the pure
``muffle.timeline_view``.
"""

from __future__ import annotations

from functools import partial

import pandas as pd
import streamlit as st

import charts
from muffle import crosstest
from muffle import timeline_view as tv
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workbench.grammar import chip, esc
from workbenches._page import line_and_action

TRUST_COLORS = {"strong": "green", "moderate": "orange", "weak": "red"}
SHOWN = ("CA 15-3", "Treatments")  # the overlays the risk chart opens with


def tags(text: str) -> str:
    return " ".join(chip(e) for e in (OBSERVED, INFERENCE, HYPOTHESIS) if e in text)


def travel(pf, k: int) -> None:
    """Open the file as of version ``k``: the shell's version slider (none with one version)."""
    if len(pf.versions) > 1:
        st.session_state[f"version-{pf.id}"] = k


def banner(pf, i: int) -> None:
    """Under the version slider, on every view: which version is open, and the way back."""
    last = len(pf.versions) - 1
    if i == last:
        return
    v = pf.versions[i]
    when = "the baseline" if v.month is None else f"month {v.month}"
    with st.container(border=True):
        text, back = line_and_action()
        text.markdown(f"You are viewing **{when}** ({esc(v.label)}): the report, tests, queue and "
                      "timeline as they were then. Later entries are not in it.")
        back.button("Back to latest", key=f"latest-{pf.id}", on_click=travel, args=(pf, last),
                    help="The file as it is now: its latest report version")


def render(pf, i: int, tl: dict | None, sums, open_evidence) -> None:
    """The Timeline view as of version ``i``. ``tl``: app/timeline_synthetic.json; ``sums(j)``:
    every workbench's summary as of version ``j`` (the shell's memo); ``open_evidence(pf, i,
    opens, focus)``: the shell's "Open"."""
    if pf.kind != "synthetic":
        st.info("One sample; the timeline grows with imports. TCGA holds one tumor sample per "
                "patient (month 0 here); every import adds a version after it.")
    lanes(pf, i)
    new_in(pf, i, sums, open_evidence)
    if pf.kind == "synthetic" and tl:
        risk(pf, i, tl)
    shown = pf.versions[: i + 1]
    scored = any(v.risk and "value" in v.risk for v in shown)
    st.markdown(f"**Every version so far** {tags(OBSERVED)}" + (
        f" · the 12-month risk: {chip(INFERENCE)}" if scored else ""))
    table = pd.DataFrame([{
        "Month": v.month, "Version": v.label, "What arrived": v.event,
        "12-month risk": f"{v.risk['value']:.0%}" if v.risk and "value" in v.risk else
        "not scored", "SOS": len(v.alerts),
        "Tests added": ", ".join(t.name for t in v.tests),
        "Treatment started": ", ".join(v.treatments),
        "Source": v.imported or "the record"} for v in shown])
    # columns with nothing in them (a TCGA file: no dates, no 12-month model) say so above,
    # instead of a column of "None"
    table = table.drop(columns=[c for c, empty in (("Month", table["Month"].isna().all()),
                                                     ("12-month risk", not scored)) if empty])
    st.dataframe(table, hide_index=True, width="stretch")
    if i:
        compare(pf, i)


def _picked(pf, key: str) -> None:
    """A click on the event chart: open the file as of the point's version."""
    sel = st.session_state[key].selection.get("node") or []
    if sel:
        travel(pf, int(sel[0]["version"]))


def lanes(pf, i: int) -> None:
    data = tv.lanes(pf)
    key = f"lanes-{pf.id}-{i}-{len(pf.versions)}"  # a fresh chart per version: no stale click
    st.markdown(f"**The record over time** {tags(OBSERVED)} · click any point to open the file as "
                "it was at the report version that point created")
    st.altair_chart(charts.event_lanes(data, i), key=key, on_select=partial(_picked, pf, key),
                    selection_mode="node", width="stretch",
                    alt="The record over time on a month axis: the report versions on the top "
                        "lane, then one lane per kind of entry, SOS alerts marked in red on the "
                        "lane of the test that raised them.")
    st.caption(
        "Top lane: the report versions; below, the record's entries by kind, each at its month "
        "(hover: its own words, its evidence label and the version it created). Red ▼: an SOS "
        "alert, on the lane of the test that raised it, with its evidence label and trust. Faded: "
        "after the version you are viewing. Treatment bars: " + tv.SPAN_RULE + ". "
        + (f"No entries: {', '.join(data['empty'])}. " if data["empty"] else "")
        + "Save the chart with Download as PNG in its toolbar.")


def _row(label: str, opens: tuple, key: str, open_evidence, pf, i: int,
         focus: dict | None = None) -> None:
    line, act = line_and_action()
    line.markdown(label)
    if opens:
        act.button("Open", key=key, on_click=open_evidence, args=(pf, i, opens, focus))


def new_in(pf, i: int, sums, open_evidence) -> None:
    """The viewed version's card: tests added, observed rows that changed, SOS alerts raised,
    treatments started, the risk move with its attribution and the workbench findings that
    changed, each with "Open" on its evidence."""
    c = tv.changes(pf, i, sums(i), sums(i - 1) if i else None)
    k = f"new-{pf.id}-{i}"
    with st.container(border=True):
        head, go = line_and_action()
        head.markdown(f"**New in this version** · {esc(c['label'])}"
                      + ("" if i else " (the first version: everything in it is new)"))
        go.button("Open its report", key=f"{k}-report", on_click=open_evidence,
                  args=(pf, i, ("Report",)))
        st.caption(f"What arrived, in the record's words: {esc(c['event'])} · "
                   + (c["imported"] or "from the record"))
        if c["tests"]:
            st.markdown(f"**Tests added** · {len(c['tests'])} {tags(OBSERVED)}")
        for n, t in enumerate(c["tests"]):
            _row(f"{t.kind} · {esc(t.name)}" + ("" if t.month is None else f", month {t.month}")
                 + f": {esc(t.result)}", ("Tests", t.kind, t.month, t.name), f"{k}-t{n}",
                 open_evidence, pf, i)
        if c["treatments"]:
            st.markdown(f"**Treatments started** {tags(OBSERVED)} · " + ", ".join(c["treatments"]))
        if c["observed"]:
            st.markdown(f"**Observed record** · {len(c['observed'])} changed {tags(OBSERVED)}\n"
                        + "\n".join(f"- {o['what']}: " + (
                            esc(o["after"]) if o["before"] is None else
                            f"{esc(o['before'])} → {esc(o['after'] or 'removed')}")
                            for o in c["observed"]))
        if c["alerts"]:
            st.markdown(f"**SOS alerts raised** · {len(c['alerts'])}")
        for n, a in enumerate(c["alerts"]):
            _row(f":red[**{esc(a.what)}**] {tags(a.evidence)} "
                 f":{TRUST_COLORS[a.trust]}-badge[trust: {a.trust}]"
                 + (" " + chip("placeholder threshold") if "placeholder" in a.threshold else ""),
                 tuple(a.opens), f"{k}-a{n}", open_evidence, pf, i)
        st.markdown(f"**Risk** {tags(INFERENCE)}"
                    + ("".join(f" · {d['finding']}: {d['before'] or '—'} → {d['after'] or '—'}"
                               for d in c["risk"]) if c["risk"] else f" · {esc(c['summary'])}"))
        if c["risk"] and c["attribution"]:
            st.caption("Why, one change at a time against the previous record: " + "; ".join(
                f"{a['what']} {a['points']:+.0f} points" for a in c["attribution"]))
        if c["workbenches"]:
            st.markdown(f"**Workbench findings that changed** · {len(c['workbenches'])}")
        for n, w in enumerate(c["workbenches"]):
            text = {"added": f":green[**+**] {esc(w['after'])}",
                    "removed": f":red[**−**] ~~{esc(w['before'])}~~",
                    "changed": f":orange[**~**] {esc(w['before'])} → {esc(w['after'])}",
                    }[w["status"]]
            _row(f"{w['workbench']} · **{esc(w['what'])}**: {text} {tags(w['evidence'])}",
                 w["opens"], f"{k}-w{n}", open_evidence, pf, i, w["focus"])


def risk(pf, i: int, tl: dict) -> None:
    """The 12-month risk over time with the record beside it; nothing new is predicted."""
    updates = tl["updates"][: i + 1]
    st.markdown(f"**Risk over time** {tags(INFERENCE)} · with the record beside it "
                f"{tags(OBSERVED)}")
    if not any("risk" in u for u in updates):
        st.caption("No risk estimate yet at this version: the models start at the first tumor "
                   "sequencing (month 0).")
        return
    show = st.pills("Show with the risk", charts.OVERLAYS, selection_mode="multi",
                    default=list(SHOWN), key=f"overlays-{pf.id}") or ()
    ctx = tv.context(pf, i)
    st.altair_chart(charts.risk_timeline(updates, tl["events"], pf.versions[i].month, ctx, show),
                    width="stretch",
                    alt="The predicted risk at each report version up to this one, with the "
                        "range of the five models as a band and the diagnosis-only baseline"
                        + (f"; shown with {', '.join(show)}." if show else "."))
    lines = [f"{chip(INFERENCE)} Risk: {tl['task']} of this synthetic patient, scored by the "
             "record-so-far models trained on MSK-CHORD (the band: the range of 5 models) and "
             "the diagnosis-only baseline, from the first tumor sequencing (month 0) on; "
             "calibration not checked. Imports are not scored."]
    if "CA 15-3" in show:
        lines.append(f"{chip(OBSERVED)} CA 15-3: the record's values and any imported ones, in "
                     "U/mL on the right axis (orange squares).")
    if "Treatments" in show:
        lines.append(f"{chip(OBSERVED)} Treatments: shaded from each drug's start; "
                     + tv.SPAN_RULE + ".")
    if "Imaging reads" in show:
        lines.append(f"{chip(OBSERVED)} Imaging reads: a line per imaging report, red where it "
                     "reads progression; hover for its words.")
    if "ctDNA" in show:
        lines.append(f"{chip(OBSERVED)} {chip('synthetic')} ctDNA: allele fractions of the "
                     "synthetic plasma series in the file so far (lower panel; hollow points at "
                     f"0 = not detected; the dashed line is the {ctx['lod']:g}% detection limit, "
                     f"a placeholder).")
    st.caption("  \n".join(lines))


def compare(pf, i: int) -> None:
    """Any two versions so far, side by side in the three evidence columns, with the
    attribution underneath; each side can be opened."""
    st.markdown("**Compare two versions** · what changed and why")
    a, b = st.columns(2)
    ia = a.selectbox("From", range(i + 1), index=i - 1, key=f"from-{pf.id}-{i}",
                     format_func=lambda k: pf.versions[k].label)
    ib = b.selectbox("To", range(i + 1), index=i, key=f"to-{pf.id}-{i}",
                     format_func=lambda k: pf.versions[k].label)
    for col, k, side in ((a, ia, "from"), (b, ib, "to")):
        col.button("Jump to this version", key=f"jump-{side}-{pf.id}-{i}", disabled=k == i,
                   on_click=travel, args=(pf, k), type="primary",  # the Timeline's one primary
                   help="Open the report, tests, queue and timeline as they were at it")
    lo, hi = sorted((ia, ib))
    diff = crosstest.diff_versions(pf, lo, hi)
    if not diff:
        st.caption("Nothing changed between these versions.")
    for col, kind in zip(st.columns(3), (OBSERVED, INFERENCE, HYPOTHESIS), strict=True):
        items = [d for d in diff if d["column"] == kind]
        with col:
            st.markdown(f"**{kind.capitalize()}** {tags(kind)} · {len(items)} changed")
            for d in items:
                st.markdown({
                    "added": f":green[**+ {d['finding']}**]: {d['after']}",
                    "removed": f":red[**− {d['finding']}**]: ~~{d['before']}~~",
                    "changed": f":orange[**~ {d['finding']}**]: {d['before']} → {d['after']}",
                }[d["status"]])
    why = [v for v in pf.versions[lo + 1: hi + 1] if v.changes]
    if why:
        st.markdown(f"**Why the risk changed** {tags(INFERENCE)}")
        st.markdown("\n".join(f"- **{v.label}** · {v.summary}" for v in why))

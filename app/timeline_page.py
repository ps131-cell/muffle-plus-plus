"""The patient file's Timeline view (docs/WORKSPACE.md, Timeline): two report versions compared
(the risk delta against the model's uncertainty, then the findings, tests, attention queue and
note that changed), the record in lanes on one month axis with time travel from any point, the
risk with the record beside it, and every version in a table.

The shell calls ``render`` from its Timeline view, ``banner`` under the report version slider and
``open_compare`` from the file's "Compare versions". Time travel sets that slider
(``version-<file id>``), so the report, the tests, the attention queue and this page re-open as
they were at that version. The data come from the pure ``muffle.timeline_view`` and
``muffle.version_diff``.
"""

from __future__ import annotations

from functools import partial

import pandas as pd
import streamlit as st

import charts
from muffle import timeline_view as tv
from muffle import version_diff as vd
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workbench.grammar import chip, esc
from workbenches._page import line_and_action

TRUST_COLORS = {"strong": "green", "moderate": "orange", "weak": "red"}
SHOWN = ("CA 15-3", "Treatments")  # the overlays the risk chart opens with
GLYPH = {"added": ":green[**+**]", "changed": ":orange[**~**]", "removed": ":red[**−**]"}
SHORT = 28  # characters: a value this short is shown as a value (monospace), a longer one as text
TABLE_COLORS = {"up": "#b42318", "down": "#137a33"}  # AA on white; the shift words say it too
# inline code (dates, values, identifiers) in the text colour: Streamlit's own code colour would
# read as one more signal next to the shift's red and green
STYLE = """<style>
.st-key-tl-diff code, .st-key-tl-versions code {
  color: inherit; background-color: rgba(128, 128, 128, 0.12); padding: 0.05em 0.3em;
  border-radius: 0.25rem; font-size: 0.88em; white-space: nowrap;
}
</style>"""


def tags(text: str) -> str:
    return " ".join(chip(e) for e in (OBSERVED, INFERENCE, HYPOTHESIS) if e in text)


def vid(k: int) -> str:
    """A version's identifier: v1 is the first report version."""
    return f"v{k + 1}"


def mono(text) -> str:
    """A date, value or identifier in monospace (backticks inside it dropped)."""
    return f"`{str(text).replace('`', '')}`"


def value(text) -> str:
    """A finding's value: monospace when short, else plain text."""
    return mono(text) if len(str(text)) <= SHORT else esc(text)


def changed(before, after) -> str:
    """A changed value: both short ones in monospace, "before → after"; in longer text only the
    words that changed, the old struck through and the new in bold (``version_diff.inline``)."""
    if len(str(before)) <= SHORT and len(str(after)) <= SHORT:
        return f"{mono(before)} → {mono(after)}"
    out, prev = [], None
    for kind, text in vd.inline(str(before), str(after)):
        core = text.strip()
        lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()):]
        if prev == "del" and kind == "ins":  # "~~34~~ → **31**", not "3431"
            lead = " → "
        out.append(lead + ({"same": "{}", "del": "~~{}~~", "ins": "**{}**"}[kind].format(
            esc(core)) if core else "") + trail)
        prev = kind
    return "".join(out)


def option(pf, k: int) -> str:
    """A version in the compare slider: its identifier and date."""
    return f"{vid(k)} · {vd.when(pf, k)}"


def travel(pf, k: int) -> None:
    """Open the file as of version ``k``: the shell's version slider (none with one version)."""
    if len(pf.versions) > 1:
        st.session_state[f"version-{pf.id}"] = k


def compare_key(pf, i: int) -> str:
    """The compare slider's key: fresh per viewed version and per import."""
    return f"diff-{pf.id}-{i}-{len(pf.versions)}"


def open_compare(pf, i: int) -> None:
    """The file's "Compare versions": the Timeline, comparing version ``i`` with the one before
    (the latest and the previous, unless an older version is open)."""
    st.session_state.view = "Timeline"
    if i:
        st.session_state[compare_key(pf, i)] = (i - 1, i)


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


def render(pf, i: int, tl: dict | None, data, open_evidence) -> None:
    """The Timeline view as of version ``i``. ``tl``: app/timeline_synthetic.json; ``data(j)``:
    version ``j``'s overview, {"sums", "queue", ...} (the shell's memo); ``open_evidence(pf, i,
    opens, focus, pointer)``: the shell's "Open"."""
    st.html(STYLE)  # a style only: it takes no space
    if pf.kind != "synthetic":
        st.info("One sample; the timeline grows with imports. TCGA holds one tumor sample per "
                "patient (month 0 here); every import adds a version after it.")
    pair = compare(pf, i, data, open_evidence)
    lanes(pf, i, pair)
    if pf.kind == "synthetic" and tl:
        risk(pf, i, tl)
    versions(pf, i)


def _picked(pf, key: str) -> None:
    """A click on the event chart: open the file as of the point's version."""
    sel = st.session_state[key].selection.get("node") or []
    if sel:
        travel(pf, int(sel[0]["version"]))


def lanes(pf, i: int, pair: tuple[int, int] | None = None) -> None:
    data = tv.lanes(pf)
    key = f"lanes-{pf.id}-{i}-{len(pf.versions)}"  # a fresh chart per version: no stale click
    st.markdown(f"**The record over time** {tags(OBSERVED)} · click any point to open the file as "
                "it was at the report version that point created")
    st.altair_chart(charts.event_lanes(data, i, pair), key=key,
                    on_select=partial(_picked, pf, key), selection_mode="node", width="stretch",
                    alt="The record over time on a month axis: the report versions on the top "
                        "lane, each marked by how the risk moved since the one before, then one "
                        "lane per kind of entry, SOS alerts marked in red on the lane of the test "
                        "that raised them.")
    scored = any(p.get("shift") in ("up", "down", "within") for p in data["points"])
    st.caption(
        "Top lane: the report versions, " + (
            "▲ red where the 12-month risk rose beyond the 5 models' spread since the version "
            "before, ▼ green where it fell beyond it, ● gray otherwise (within it, or no "
            "estimate); " if scored else "") + "the latest is ringed"
        + (", the shaded span is the pair compared above" if pair and pair[0] != pair[1] else "")
        + ". Below, the record's entries by kind, each at its month. Red ◆: an SOS alert, on the "
        "lane of the test that raised it. Faded: after the version you are viewing. Hover a point "
        "for its words, evidence label and version. Treatment bars: " + tv.SPAN_RULE + ". "
        + (f"No entries: {', '.join(data['empty'])}. " if data["empty"] else "")
        + "Save the chart with Download as PNG in its toolbar.")


# --- the diff viewer ----------------------------------------------------------------------------
def _open(pf, i: int, at: int, opens: tuple, focus, pointer, open_evidence) -> None:
    """"Open" on a changed item: its evidence as of the version that holds it (a finding gone by
    the later version opens as of the earlier one)."""
    if at != i:
        travel(pf, at)
    open_evidence(pf, at, opens, focus, pointer)


def _row(text: str, item: dict, key: str, pf, i: int, open_evidence) -> None:
    line, act = line_and_action()
    line.markdown(text)
    if item.get("opens"):
        act.button("Open", key=key, on_click=_open,
                   args=(pf, i, item["at"], tuple(item["opens"]), item.get("focus"),
                         item.get("pointer"), open_evidence),
                   help=f"Open its evidence as of {vid(item['at'])} "
                        f"({vd.when(pf, item['at'])})")


def risk_chip(d: dict) -> str:
    """The risk delta as one line: a chip with its direction and size (red up, green down, gray
    within the model's uncertainty or not compared; the words say it too), the two values in
    monospace and what the uncertainty is."""
    r = d["risk"]
    color, sign, words = vd.SHIFTS[r["shift"]]
    if r["kind"] == "probability":
        size = f"{abs(r['points']):.0f} point{'' if round(abs(r['points'])) == 1 else 's'}"
        badge = (f"{sign} risk {r['direction']} {size}" if r["exceeds"] or r["direction"] ==
                 "same" else f"{sign} {r['points']:+.0f} points: within the model's uncertainty")
        (alo, ahi), (blo, bhi) = r["uncertainty"]["before"], r["uncertainty"]["after"]
        values = "{:.0%} → {:.0%}".format(r["before"], r["after"])
        line = (f":{color}-badge[{badge}] {mono(values)} · "
                + ("beyond" if r["exceeds"] else "inside") + " the 5 models' spread "
                + mono(f"{alo:.0%}–{ahi:.0%}") + " → " + mono(f"{blo:.0%}–{bhi:.0%}"))
        if r["models"][0] != r["models"][1]:
            line += (f" · the month-{r['models'][1]} model takes over from the "
                     f"month-{r['models'][0]} one")
    elif r["kind"] == "percentile":
        line = (f":{color}-badge[{sign} risk {words}] "
                + mono(f"{r['after']:.0f}th percentile" if not r["delta"] else
                       f"{r['before']:.0f} → {r['after']:.0f}")
                + " · the estimate rests on the tumor sample alone (no per-patient interval)")
    else:
        line = f":{color}-badge[{sign} no risk delta] {esc(r['text'])}"
    return f"**Risk** {tags(INFERENCE)} {line}"


def _counts(d: dict) -> str:
    c = d["counts"]
    return " · ".join([
        "**Findings** " + " ".join(mono(f"{vd.STATUS[s]}{c[s]}") for s in vd.STATUS),
        f"**Tests** {mono('+' + str(c['tests']))}",
        "**Attention queue** " + " ".join(mono(f"{vd.STATUS[s]}{c['queue_' + s]}")
                                          for s in vd.STATUS),
        f"**Note** {mono('~' + str(c['note']))}"]) + " (+ added, ~ changed, − removed)"


def compare(pf, i: int, data, open_evidence) -> tuple[int, int] | None:
    """Two report versions compared (``muffle.version_diff.diff``), the previous and the viewed one
    unless the slider says otherwise: the risk delta first, then the findings, tests, attention
    queue and note that changed, each with "Open" on its evidence. Returns the pair."""
    st.markdown("**Compare two versions** · what changed between two snapshots of the record")
    if not i:
        st.caption("One report version so far: nothing earlier to compare with. Each import "
                   "adds a version, and what it changed appears here.")
        return None
    key = compare_key(pf, i)
    st.session_state.setdefault(key, (i - 1, i))
    a, b = st.select_slider(
        "Versions compared", options=range(i + 1), key=key, format_func=partial(option, pf),
        help="Drag either end to compare any two report versions so far; the change between "
             "them is listed below. Version v1 is the first; later versions are not in it "
             "while an older one is open.")
    if a == b:
        st.caption(f"Both ends are on {vid(a)}: move one to compare two versions.")
        return a, b
    d = vd.diff(pf, a, b, data)
    k = f"dv-{pf.id}-{a}-{b}"
    with st.container(border=True, key="tl-diff"):
        head, go = line_and_action()
        head.markdown(
            f"**{mono(vid(a))}** {esc(d['from'])} → **{mono(vid(b))}** {esc(d['to'])} · "
            + (f"{d['versions']} versions apart" if d["versions"] > 1 else "consecutive")
            + (f" · imported in this session: {', '.join(d['imported'])}" if d["imported"]
               else ""))
        for side, j in (("from", a), ("to", b)):
            go.button(f"Go to {vid(j)}", key=f"jump-{side}-{pf.id}-{i}", disabled=j == i,
                      on_click=travel, args=(pf, j), type="primary" if side == "from" else
                      "secondary",  # the Timeline's one primary: step back
                      help=f"Open the file as it was at {vid(j)} ({vd.when(pf, j)}): the "
                           "report, tests, queue and timeline")
        st.markdown(risk_chip(d))
        why = [mono(vid(w["k"])) + " " + " · ".join(
            esc(c["what"]) + " " + mono("{:+.0f}".format(c["points"])) for c in w["changes"])
            for w in d["risk"]["why"]]
        st.caption(vd.SNAPSHOT + (" Why the risk moved, one change at a time against the "
                                  "record before it, in points: " + "; ".join(why) if why
                                  else ""))
        st.markdown(_counts(d))
        rows = len(d["findings"]) + len(d["tests"]) + len(d["queue"]) + len(d["note"])
        open_all = rows <= 14  # a long list stays folded, its counts in the headers
        if d["findings"]:
            with st.expander(f"Findings that changed ({len(d['findings'])})", expanded=open_all):
                for n, f in enumerate(d["findings"]):
                    text = {"added": value(f["after"]), "removed": f"~~{esc(f['before'])}~~",
                            "changed": changed(f["before"], f["after"])}[f["status"]]
                    _row(f"{GLYPH[f['status']]} **{esc(f['where'])}** · {esc(f['what'])}: {text} "
                         f"{tags(f['evidence'])}", f, f"{k}-f{n}", pf, i, open_evidence)
        if d["tests"]:
            with st.expander(f"Tests added ({len(d['tests'])})", expanded=open_all):
                for n, t in enumerate(d["tests"]):
                    x = t["test"]
                    _row(f"{GLYPH['added']} "
                         + (mono(f"month {x.month}") + " " if x.month is not None else "")
                         + f"{x.kind} · {esc(x.name)}: {esc(x.result)} {tags(OBSERVED)} · in "
                         + mono(vid(t["version"]))
                         + (f" · {esc(t['imported'])}" if t["imported"] else ""),
                         {"opens": ("Tests", x.kind, x.month, x.name), "at": b},
                         f"{k}-t{n}", pf, i, open_evidence)
        if d["queue"]:
            with st.expander(f"Attention queue that changed ({len(d['queue'])})",
                             expanded=open_all):
                for n, q in enumerate(d["queue"]):
                    kind = chip("SOS", "red") if q["sos"] else chip(q["kind"])
                    what = (f"~~{esc(q['what'])}~~ (left the queue)" if q["status"] == "removed"
                            else changed(q["before"], q["what"]) if q["status"] == "changed"
                            else esc(q["what"]))
                    _row(f"{GLYPH[q['status']]} {kind} {what} {tags(q['evidence'])} "
                         f":{TRUST_COLORS[q['trust']]}-badge[trust: {q['trust']}]",
                         q, f"{k}-q{n}", pf, i, open_evidence)
        if d["note"]:
            with st.expander(f"Summary note that changed ({len(d['note'])} sentence"
                             f"{'' if len(d['note']) == 1 else 's'})", expanded=open_all):
                st.markdown("\n".join(
                    f"- {GLYPH[s['status']]} " + {
                        "added": esc(s["after"]), "removed": f"~~{esc(s['before'])}~~",
                        "changed": changed(s["before"], s["after"])}[s["status"]]
                    + f" {tags(s['evidence'])}" for s in d["note"]))
        if not rows:
            st.caption("No finding, test, queue item or note sentence differs between these two "
                       "versions.")
    return a, b


def versions(pf, i: int) -> None:
    """Every version so far, newest first: what arrived, the risk and its shift since the version
    before, what it added; a click on a row opens the file as of that version."""
    shown = list(range(i, -1, -1))
    scored = any(pf.versions[k].risk and "value" in pf.versions[k].risk for k in shown)
    last = len(pf.versions) - 1
    rows = []
    for k in shown:
        v = pf.versions[k]
        r = vd.risk_delta(pf, k - 1, k) if k else None
        shift = "" if r is None else (
            "first estimate" if r["shift"] == "none" and v.risk and "value" in v.risk else
            "—" if r["shift"] == "none" else f"{vd.SHIFTS[r['shift']][1]} "
            + (f"{r['points']:+.0f}" if r["kind"] == "probability" else "unchanged")
            + (" within" if r["shift"] == "within" else ""))
        rows.append({
            "Version": vid(k) + (" latest" if k == last else " viewing" if k == i else ""),
            "Month": "sample" if v.month is None else str(v.month),
            "12-month risk": f"{v.risk['value']:.0%}" if v.risk and "value" in v.risk else
            "not scored", "Shift": shift, "What arrived": v.event, "Tests": len(v.tests),
            "SOS": len(v.alerts), "Source": v.imported or "the record",
            "_shift": r and r["shift"]})
    table = pd.DataFrame(rows)
    if not scored:  # a TCGA file: its risk is a cohort percentile, the report's
        table = table.drop(columns=["12-month risk", "Shift"])
    marks = table.pop("_shift")
    st.markdown(f"**Every version so far** · newest first {tags(OBSERVED)}" + (
        f" · the 12-month risk and its shift: {chip(INFERENCE)}" if scored else "")
        + " · click a row to open the file as of that version")

    def tint(col):
        if col.name == "Shift":
            return [f"color: {TABLE_COLORS[m]}" if m in TABLE_COLORS else "" for m in marks]
        return ["font-weight: 700" if n == 0 else "" for n in range(len(col))]

    key = f"versions-{pf.id}-{i}-{len(pf.versions)}"  # fresh per version: no stale selection
    cfg = st.column_config
    with st.container(key="tl-versions"):
        st.dataframe(
            table.style.apply(tint), hide_index=True, width="stretch", key=key,
            height=35 * (min(len(table), 16) + 1) + 3,  # every version of a long file in view
            on_select=partial(_row_picked, pf, key, shown), selection_mode="single-row",
            column_config={
                "Version": cfg.TextColumn("Version", width=92, pinned=True),
                "Month": cfg.TextColumn("Month", width=58),
                "12-month risk": cfg.TextColumn("Risk", width=50, help="The 12-month risk"),
                "Shift": cfg.TextColumn(
                    "Shift", width=86, help="The 12-month risk since the version before, in "
                    "points: ▲ up or ▼ down beyond the 5 models' spread, ≈ within it (a model "
                    "inference; a difference between two snapshots, not a trend)"),
                "What arrived": cfg.TextColumn("What arrived", width="large"),
                "Tests": cfg.NumberColumn("Tests", width=50, help="Tests added in that version"),
                "SOS": cfg.NumberColumn("SOS", width=44, help="SOS alerts raised in that "
                                                               "version")})


def _row_picked(pf, key: str, shown: list[int]) -> None:
    rows = st.session_state[key].selection.get("rows") or []
    if rows:
        travel(pf, shown[rows[0]])


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
                    default=list(SHOWN), key=f"overlays-{pf.id}",
                    help="The record drawn beside the risk, on the same month axis") or ()
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


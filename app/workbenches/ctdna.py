"""ctDNA monitor (liquid biopsy) for a patient file (docs/ctdna.md).

streamlit run app/workbenches/ctdna.py        # the synthetic patient's monitor, standalone page

The workspace pages call ``render(pf, version=None)`` with a ``muffle.workspace.PatientFile``; it
draws inside the current container only. SYNTHETIC-001 carries a hand-written ctDNA series
(``muffle.timeline.CTDNA``), labeled synthetic on every screen; no other file has ctDNA. Overview
first (pointers C1..Cn shared by every view), then the allele fractions over time with the
detection limit, treatment spans and imaging progressions, CA 15-3 on the same axis, the calls
per variant with their rules, the ESR1 rule (PADA-1, SERENA-6) as evidence for clinician review,
the clonal-hematopoiesis caveat, lead and lag, the Spot panel with links to the genomics
workbench and the Evolution view, the look-here queue with review marks, what ctDNA cannot see,
the rules card and the exports. Rules only, no model (``muffle.workbench.ctdna``).
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle.timeline import CTDNA, EVENTS  # noqa: E402
from muffle.workbench import ctdna as wb  # noqa: E402
from muffle.workbench import labs  # noqa: E402
from muffle.workbench.grammar import CANNOT_SEE, CARD, EXPORT, chip  # noqa: E402
from muffle.workspace import (  # noqa: E402
    IMPLEMENTED,
    MARKS,
    PatientFile,
    finding_key,
    synthetic_file,
)

COLORS = {"PIK3CA H1047R": "#2a78d6", "ESR1 D538G": "#eb6834", "DNMT3A R882H": "#8a8f98"}
GRAY, RED = "#8a8f98", "#e34948"
GRID = {"gridOpacity": 0.4, "domainOpacity": 0.4, "tickOpacity": 0.4}
NO_MARK = "no mark"
PROVENANCE = ("Data: a synthetic ctDNA series written by hand for this synthetic patient "
              "(observed values in form, not measured). Method: rules, version 1, no model. "
              "Thresholds: the detection limit and the rising, falling, cleared and flat criteria "
              "are placeholders; the clonal-hematopoiesis flag follows Razavi 2019 and Jaiswal "
              "2014, the ESR1 rule PADA-1 and SERENA-6 (literature). Status: implemented, not "
              "validated.")
CAVEAT = ("A ctDNA variant is not proven tumor-derived without matched white-cell sequencing, and "
          "\"not detected\" is not \"absent\". Trial evidence is for clinician review; nothing "
          "here is a recommendation.")


def chips(*labels: str) -> None:
    """Status captions in the shared grammar's colors; "synthetic" in red, on every screen."""
    st.caption(" ".join(chip(label, "red" if label == "synthetic" else None)
                        for label in labels))


def _vaf(r: dict) -> str:
    return f"{r['vaf']:g}%" if r["detected"] else f"not detected (<{r['lod']:g}%)"


def _label(r: dict) -> str:
    return (f"{r['pointer'] or '·'} · month {r['month']} · {r['variant']} {_vaf(r)}, "
            f"{r['call']}")


def chart(rows: list[dict], intervals: list[dict], events: list[dict], lod: float,
          span: tuple[int, int]) -> alt.Chart:
    """Allele fractions over months on a log axis: one line per variant, points with their
    pointers (hover for the call and its rule), not-detected samples as hollow points under the
    detection limit, the limit itself (placeholder), treatment spans and imaging progressions."""
    df = pd.DataFrame(rows)
    df["y"] = [r["vaf"] if r["detected"] else lod / 2 for r in rows]
    df["vaf_text"] = [_vaf(r) for r in rows]
    df["therapy_text"] = [" + ".join(r["therapy"]) or "none" for r in rows]
    x = alt.X("month:Q", title="months since the first tumor sequencing",
              scale=alt.Scale(domain=[span[0] - 1, span[1] + 1]))
    y_scale = alt.Scale(type="log", domain=[lod / 4, 10])
    y = alt.Y("y:Q", title="variant allele fraction (%, log scale)", scale=y_scale)
    tip = [alt.Tooltip("pointer:N", title="pointer"), alt.Tooltip("variant:N", title="variant"),
           alt.Tooltip("month:Q", title="month"), alt.Tooltip("vaf_text:N", title="VAF"),
           alt.Tooltip("call:N", title="call"), alt.Tooltip("rule:N", title="rule"),
           alt.Tooltip("origin:N", title="origin"),
           alt.Tooltip("therapy_text:N", title="therapy at the time")]
    layers = []
    if intervals:
        iv = (pd.DataFrame(intervals).groupby(["start", "end"])["agent"].agg(" + ".join)
              .reset_index())
        iv = iv[iv["end"] > span[0] - 1].assign(  # spans that began before the axis start on it
            start=lambda d: d["start"].clip(lower=span[0] - 1))
        layers.append(alt.Chart(iv).mark_rect(opacity=0.08, color=GRAY).encode(
            x="start:Q", x2="end:Q", tooltip=[alt.Tooltip("agent:N", title="treatment"),
                                              "start:Q", "end:Q"]))
        layers.append(alt.Chart(iv.assign(y=8)).mark_text(align="left", dx=3, fontSize=10,
                                                         color=GRAY).encode(
            x="start:Q", y=alt.Y("y:Q", scale=y_scale), text="agent:N"))
    prog = pd.DataFrame([{"month": e["month"], "what": e["text"]} for e in events
                         if e.get("progression")])
    if not prog.empty:
        layers.append(alt.Chart(prog).mark_rule(color=RED, strokeDash=[2, 3]).encode(
            x="month:Q", tooltip=[alt.Tooltip("what:N", title="imaging, progression")]))
    lim = pd.DataFrame({"y": [lod], "label": [f"detection limit {lod:g}% (placeholder)"]})
    layers.append(alt.Chart(lim).mark_rule(strokeDash=[5, 4], color=GRAY).encode(
        y=alt.Y("y:Q", scale=y_scale), tooltip=alt.Tooltip("label:N", title="limit")))
    vscale = alt.Scale(domain=list(COLORS), range=list(COLORS.values()))
    color = alt.Color("variant:N", scale=vscale, legend=alt.Legend(orient="bottom", title=None))
    base = alt.Chart(df).encode(x=x, y=y, color=color)
    layers.append(base.transform_filter("datum.detected").mark_line(strokeWidth=1.5))
    layers.append(base.mark_point(size=90, filled=True, strokeWidth=2).encode(
        fill=alt.condition("datum.detected", color, alt.value("white")),
        stroke=alt.Stroke("variant:N", scale=vscale, legend=None), tooltip=tip))
    layers.append(base.mark_text(dy=-12, fontSize=10, fontWeight="bold").encode(
        text="pointer:N"))
    return alt.layer(*layers).properties(height=340).configure_axis(**GRID)


def marker_chart(lab_rows: list[dict], span: tuple[int, int]) -> alt.Chart | None:
    rows = [r for r in lab_rows if r["key"] == "ca153"]
    if not rows:
        return None
    df = pd.DataFrame(rows)[["month", "value", "flag", "pointer"]]
    base = alt.Chart(df).encode(
        x=alt.X("month:Q", title=None, scale=alt.Scale(domain=[span[0] - 1, span[1] + 1])),
        y=alt.Y("value:Q", title="CA 15-3 (U/mL)"),
        tooltip=["pointer:N", "month:Q", "value:Q", "flag:N"])
    return alt.layer(base.mark_line(color=GRAY), base.mark_circle(size=60, color=GRAY),
                     base.mark_text(dy=-10, fontSize=10).encode(text="pointer:N")).properties(
        height=140).configure_axis(**GRID)


def _key(pf: PatientFile, variant: str, month) -> str:
    return finding_key(pf, "ctdna", variant, month)


def _sync_reviews(pf: PatientFile, items: list[dict], reviews: dict) -> None:
    by = st.session_state.get("reviewer", "") or ""
    for i in items:
        key = _key(pf, i["variant"], i["month"])
        choice = st.session_state.get(f"mark_{key}", NO_MARK)
        if choice == NO_MARK:
            reviews.pop(key, None)
        elif key not in reviews or reviews[key]["mark"] != choice:
            reviews[key] = {"what": i["what"], "mark": choice, "by": by,
                            "at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _open(view: str, picked: tuple | None = None, pf_id: str = "") -> None:
    st.session_state["view"] = view
    if picked:
        st.session_state[f"picked-{pf_id}"] = picked


def render(pf: PatientFile, version: int | None = None) -> None:
    """The ctDNA monitor for one patient file, inside the current container (no page config, no
    sidebar). With ``version`` the series is shown as of that report version's month."""
    st.subheader("ctDNA monitor (liquid biopsy)")
    st.caption(f"{pf.id} · {pf.title}")
    series = CTDNA if pf.kind == "synthetic" else None
    events = list(EVENTS) if pf.kind == "synthetic" else []
    card = wb.rules_card(series or CTDNA)
    if series is None:
        st.info("No ctDNA on file: TCGA-BRCA holds one tumor sample per patient and no blood "
                "samples. Serial ctDNA would follow the tumor's mutations under treatment.")
        _cannot_see()
        _card(card)
        return
    cutoff = None if version is None else pf.versions[version].month
    if cutoff is not None:
        events = [e for e in events if e["month"] <= cutoff]
        series = {**series, "samples": [s for s in series["samples"] if s["month"] <= cutoff]}
        st.caption(f"As of month {cutoff} ({pf.versions[version].label}): samples after it "
                   "hidden, calls computed from the samples up to here.")
    chips(IMPLEMENTED, "placeholder threshold", "literature rule", "synthetic")
    st.warning(wb.SYNTHETIC_NOTE + " Every allele fraction on this page is part of that "
               "synthetic series.")
    st.caption(PROVENANCE)
    if not series["samples"]:
        st.info("No ctDNA sample yet as of this version.")
        _cannot_see()
        _card(card)
        return

    rows = wb.series_rows(series, events)
    vs = wb.variants(rows, events)
    rule = wb.esr1_rule(rows, events)
    shed = wb.low_shedding(rows)
    lab_rows = labs.results_table(events)
    lag = wb.lead_lag(rows, events, lab_rows)
    queue = wb.queue(rows, vs, rule, shed)
    intervals = labs.treatment_intervals(events)
    months = [s["month"] for s in series["samples"]]
    span = (min(months + [e["month"] for e in events if e["month"] >= min(months)]),
            max(months + [e["month"] for e in events]))
    findings = ([{"variant": r["variant"], "month": r["month"], "pointer": r["pointer"],
                  "what": f"{r['variant']} {_vaf(r)} at month {r['month']}: {r['call']} "
                          f"({r['pointer']})"} for r in rows if r["call"] in (wb.NEW, wb.RISING)]
                + [{"variant": v["variant"], "month": v["latest_month"], "pointer": "",
                    "what": f"{v['variant']}: {v['origin']}"}
                   for v in vs if v["origin"] == wb.POSSIBLE_CH])
    reviews = st.session_state.setdefault("reviews", {})
    _sync_reviews(pf, findings, reviews)
    mine = {k: v for k, v in reviews.items() if k.startswith(f"{pf.id}|ctdna|")}

    # overview
    latest = {v["variant"]: v for v in vs}
    applies = [i for i in rule if i["applies"]]
    lines = [f"**{len(months)} plasma samples** (synthetic) from month {min(months)} to "
             f"{max(months)}, {len(vs)} variants: " + "; ".join(
                 f"{v['variant']} {v['origin']}, latest {v['latest']} at month "
                 f"{v['latest_month']}" for v in latest.values()) + "."]
    lines += [f"{i['pointer']}: {i['what']}; evidence for clinician review, never a "
              "recommendation to switch." for i in applies]
    lines += [f"{v['variant']} is {v['origin']}: {v['pattern']}; excluded from the tumor picture."
              for v in vs if v["origin"] == wb.POSSIBLE_CH]
    before = {}  # the first new or rising call of each variant before each progression
    for x in lag:
        if x["imaging_month"] is not None:
            before.setdefault(x["imaging_month"], {}).setdefault(x["variant"], x)
    for month, first in before.items():
        ca = {x["ca153_month"] for x in first.values()} - {None}
        lines.append(f"Before the progression on imaging at month {month}: " + ", ".join(
            f"{v} {x['call']} from month {x['month']} ({x['pointer']})" for v, x in first.items())
            + (f"; CA 15-3 flagged at month {min(ca)}" if ca else "")
            + " (observed order in this record, not a lead time).")
    lines.append(f"{len(queue)} items to look at, {len(mine)} review marks.")
    st.markdown(" ".join(lines))

    # allele fractions over time
    st.markdown("#### Allele fractions over time")
    chips(IMPLEMENTED, "placeholder threshold", "synthetic")
    st.caption("Hover a point for its call, the rule behind it, its origin and the therapy at the "
               "time. Hollow points under the dashed line were not detected (below the "
               f"{series['detection_limit']:g}% detection limit, a placeholder); gray spans are "
               "treatment intervals (starts only in the record); red dotted lines are imaging "
               "reports that read progression. CA 15-3 below shares the axis.")
    st.altair_chart(chart(rows, intervals, events, series["detection_limit"], span),
                    width="stretch")
    mc = marker_chart(lab_rows, span)
    if mc is not None:
        st.altair_chart(mc, width="stretch")

    # calls per variant
    st.markdown("#### Calls per variant")
    chips(IMPLEMENTED, "placeholder threshold", "literature rule")
    st.dataframe(pd.DataFrame([{
        "variant": v["variant"], "origin": v["origin"], "in the tumor picture":
        "yes" if v["in_picture"] else "no", "latest call": f"{v['latest']} (month "
                                                           f"{v['latest_month']})",
        "detected": v["detected"], "pattern": v["pattern"], "calls": "; ".join(v["calls"]),
        "why": v["why"]} for v in vs]), hide_index=True, width="stretch")
    st.caption(f"Calls: rising at {wb.RISE_FACTOR:g}x the previous detected value or more, "
               f"falling at {wb.FALL_FACTOR:g}x or less, cleared after {wb.CLEAR_SAMPLES} "
               "consecutive samples below the limit, new when detected after samples below it "
               "(all placeholders).")

    # ESR1 rule
    st.markdown("#### ESR1 under an aromatase inhibitor (PADA-1, SERENA-6)")
    chips(IMPLEMENTED, "literature rule", "hypothesis")
    st.caption("A new or rising ESR1 mutation in blood under an aromatase inhibitor is the "
               "trigger PADA-1 tested and the design of SERENA-6. Shown as evidence for "
               "clinician review, with how this record differs from the trials; never a "
               "recommendation to switch.")
    for i in rule:
        with st.container(border=True):
            st.markdown(f"**{i['pointer']}** · {wb_cap(i['what'])}.")
            if i["compare"]:
                st.markdown("\n".join(f"- **{a}** · " + (f"the trials: {t}; " if t else "") + r
                                      for a, t, r in i["compare"]))
            st.caption("Sources: " + " · ".join(i["sources"]) + f". Use: {i['use']}.")
    if not rule:
        st.caption("No new or rising ESR1 call in the samples shown.")

    # clonal hematopoiesis
    st.markdown("#### Clonal hematopoiesis")
    chips(IMPLEMENTED, "literature rule")
    st.markdown(f"Without matched white-cell sequencing no plasma variant is proven "
                f"tumor-derived: {wb.RAZAVI_2019}. A variant the tumor sequencing did not find, "
                f"in {', '.join(wb.CH_GENES)} ({wb.JAISWAL_2014}), is flagged as possible clonal "
                "hematopoiesis and kept out of the tumor picture.")
    for v in vs:
        st.markdown(f"- **{v['variant']}**: {v['origin']}. {wb_cap(v['why'])}.")

    # lead and lag
    st.markdown("#### Against imaging and CA 15-3")
    chips(IMPLEMENTED)
    st.caption("Each new or rising call against the next imaging progression and the next CA "
               "15-3 flagged above its limit or rising: the observed order of events in this "
               "record, not a validated lead time.")
    st.markdown("\n".join(f"- {x['pointer']}: {x['what']}" for x in lag) or "None.")
    for s in shed:
        st.caption(s["what"])

    # spot panel
    st.markdown("#### Spot panel")
    chips(IMPLEMENTED, "placeholder threshold", "synthetic")
    labels = [_label(r) for r in rows]
    flagged = [r for r in rows if r["pointer"]]
    default = labels.index(_label(flagged[-1])) if flagged else len(labels) - 1
    r = rows[labels.index(st.selectbox("Sample and variant", labels, index=default,
                                       key=f"{pf.id}_ctdna_spot"))]
    s = wb.spot(r, rows, events, lab_rows)
    st.markdown(f"**{r['variant']} {_vaf(r)}** at month {r['month']} "
                f"({r['pointer'] or 'no pointer'}; evidence: {s['evidence']}, synthetic). "
                f"Call: **{r['call']}** "
                f"({r['rule']}; {r['status']}). Origin: {r['origin']}. Therapy at the time: "
                f"{' + '.join(r['therapy']) or 'none recorded'}."
                + (f" CA 15-3 at or before it: {s['ca153']['value']:g} U/mL at month "
                   f"{s['ca153']['month']} ({s['ca153']['flag']})." if s["ca153"] else ""))
    st.markdown("**Events around it (±2 months):**\n" + ("\n".join(
        f"- month {e['month']}, {e['kind']}: {e['text']}" for e in s["events_around"]) or "none"))
    st.markdown("**Check by eye:**\n" + "\n".join(f"- {c}" for c in s["check_by_eye"]))
    st.dataframe(pd.DataFrame([{"month": h["month"], "VAF": _vaf(h), "call": h["call"],
                                "pointer": h["pointer"]} for h in s["history"]]),
                 hide_index=True, width="stretch")
    c1, c2 = st.columns(2)
    seq = [t for v in pf.versions for t in v.tests if t.workbench == "mutations"]
    if seq:
        found = r["variant"] in seq[-1].details.get("variants", [])
        c1.button(f"Open the tumor sequencing (month {seq[-1].month}) in the genomics workbench"
                  + ("" if found else f": {r['variant']} is not in it"),
                  key=f"{pf.id}_ctdna_genomics", on_click=_open,
                  args=("Tests", (seq[-1].kind, seq[-1].month, seq[-1].name), pf.id))
    c2.button("Open the Evolution view: what to watch next", key=f"{pf.id}_ctdna_evolution",
              on_click=_open, args=("Evolution",))

    # look here, with review marks
    st.markdown("#### Look here")
    chips(IMPLEMENTED, "literature rule", "placeholder threshold")
    if queue:
        st.dataframe(pd.DataFrame(queue), hide_index=True, width="stretch")
    st.markdown("#### Flagged findings: your review")
    for f in findings:
        with st.expander(f["what"]):
            st.selectbox("Your review mark", (NO_MARK, *MARKS),
                         key=f"mark_{_key(pf, f['variant'], f['month'])}",
                         help="Marks go into this file's report export")

    _cannot_see()
    _card(card)

    # export
    st.markdown(f"#### {EXPORT}")
    chips(IMPLEMENTED)
    md = wb.report_markdown(pf.id, rows, vs, rule, lag, shed, card, mine)
    e1, e2 = st.columns(2)
    e1.download_button("Download the ctDNA report (Markdown)", md, file_name=f"{pf.id}_ctdna.md",
                       mime="text/markdown", key=f"{pf.id}_ctdna_md")
    csv = pd.DataFrame([{**{k: r[k] for k in ("pointer", "month", "variant", "vaf", "detected",
                                              "lod", "call", "rule", "origin")},
                         "therapy": " + ".join(r["therapy"]), "synthetic": r["synthetic"]}
                        for r in rows]).to_csv(index=False)
    e2.download_button("Download the series (CSV)", csv, file_name=f"{pf.id}_ctdna.csv",
                       mime="text/csv", key=f"{pf.id}_ctdna_csv")
    st.caption(CAVEAT)


def wb_cap(s: str) -> str:
    return s[:1].upper() + s[1:]


def _cannot_see() -> None:
    st.markdown(f"#### {CANNOT_SEE}")
    st.markdown("\n".join(f"- {c}" for c in wb.CANNOT_SEE))


def _card(card: dict) -> None:
    st.markdown(f"#### {CARD}")
    chips(card["status"])
    st.markdown(f"**{card['name']}** · {card['kind']}  \n**Inputs:** {card['inputs']}  \n"
                f"**Outputs:** {card['outputs']}  \n**Validation:** {card['validation']}")
    st.dataframe(pd.DataFrame(card["thresholds"]), hide_index=True, width="stretch")
    st.markdown("**Known failures:**\n" + "\n".join(f"- {f}" for f in card["known_failures"]))


if __name__ == "__main__":
    st.set_page_config(page_title="ctDNA monitor", layout="wide")
    st.text_input("Reviewer initials", key="reviewer", max_chars=5)  # the shell's field
    render(synthetic_file(json.loads((APP / "timeline_synthetic.json").read_text("utf-8"))))

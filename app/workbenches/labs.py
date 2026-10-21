"""Blood and lab workbench for a patient file (docs/WORKSPACE.md, "Blood and lab panels").

streamlit run app/workbenches/labs.py        # the synthetic patient's workbench, standalone page

The workspace pages call ``render(file, events=None, version=None)`` with a
``muffle.workspace.PatientFile``; it draws inside the current container only. Overview first
(with pointers L1..Ln shared by every view), then a trend per marker (hover for brief stats, the
baseline band, the kinetics extrapolation, treatment spans and caution windows), the spot panel
for one value, kinetics, the EGTM confirmation tracker, therapy windows, the baseline band,
markers against imaging, the cross-marker view, plain-word search, the results table with
filters, one expander per flagged result with review marks, the "look here" queue, quality
checks, the rules card and the exports. Every number is plain arithmetic on observed values
(``muffle.workbench.labs``) except the kinetics, which are model inference with a placeholder
method; an out-of-range value is not evidence of progression by itself.
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

from muffle.timeline import EVENTS  # noqa: E402
from muffle.workbench.labs import (  # noqa: E402
    ABOVE,
    FALLING,
    FLARE_MONTHS,
    PLANNED_PANELS,
    RISING,
    WITHIN,
    baseline_band,
    confirmation_tracker,
    cross_marker,
    kinetics,
    lead_lag,
    look_here,
    quality_checks,
    report_markdown,
    results_table,
    rules_card,
    search,
    spot,
    therapy_windows,
    treatment_intervals,
)
from muffle.workspace import (  # noqa: E402
    IMPLEMENTED,
    MARKERS,
    PLANNED,
    REFERENCE_LIMITS,
    PatientFile,
    finding_key,
    synthetic_file,
)
from muffle.workspace import MARKS as WORKSPACE_MARKS  # noqa: E402
from muffle.workbench.grammar import CARD, chip  # noqa: E402

BLUE, ORANGE, RED, GRAY = "#2a78d6", "#eb6834", "#e34948", "#8a8f98"
COLORS = {WITHIN: BLUE, ABOVE: RED, f"{ABOVE}, {RISING}": RED, f"{ABOVE}, {FALLING}": ORANGE,
          RISING: ORANGE, FALLING: BLUE}
GRID = {"gridOpacity": 0.4, "domainOpacity": 0.4, "tickOpacity": 0.4}
PLACEHOLDER_CHIP, LITERATURE_CHIP = "placeholder threshold", "literature threshold"
INFERENCE_CHIP, PLACEHOLDER_METHOD_CHIP = "model inference", "placeholder method"
NO_MARK = "no mark"
MARKS = (NO_MARK, *WORKSPACE_MARKS)  # the workspace's marks, plus none
PROVENANCE = ("Data: the patient record's lab results (observed). Method: rules, version 1, "
              "plain arithmetic, no model; kinetics are a log-linear extrapolation (model "
              "inference, placeholder method). Thresholds: the reference limit from the "
              "record's lab report; the 25% rise criterion from the EGTM guidance (literature); "
              "the fall, gap, caution-window and baseline rules are placeholders. Status: "
              "implemented, not validated on a cohort.")
CAVEAT = ("An out-of-range or rising value is not evidence of progression by itself: it is an "
          "observed value to look at next to imaging and the clinic. Nothing here is a "
          "recommendation.")


def chips(*labels: str) -> None:
    """Small status captions in the shared grammar's colors (placeholders orange)."""
    st.caption(" ".join(chip(label) for label in labels))  # the shared grammar's colors


def pct(v) -> str:
    return "first value" if v is None or pd.isna(v) else f"{v:+.0%}"


def n_of(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def cap(s: str) -> str:
    """Sentence case that leaves units and acronyms alone."""
    return s[:1].upper() + s[1:]


def _lab(r: dict) -> str:
    """One result as a short label: pointer, month, marker, value, flag."""
    return (f"{r['pointer'] or 'no flag'} · month {r['month']} · {r['marker']} {r['value']:g} "
            f"{r['unit']}, {r['flag']}")


def trend(rows: list[dict], intervals: list[dict], unit: str, limit: tuple | None,
          span: tuple[int, int], band: dict | None, kin: dict) -> alt.Chart:
    """One marker over months: points colored by flag with their pointers (hover for brief
    stats), the reference limit, the within-person baseline band, the kinetics extrapolation
    as a dashed band, treatment spans with their agents and the caution windows after each."""
    df = pd.DataFrame(rows)
    df["value_text"] = df["value"].map(lambda v: f"{v:g} {unit}")
    df["change_text"] = df["change"].map(pct)
    df["nadir_text"] = df["from_nadir"].map(pct)
    df["rate_text"] = df["per_month"].map(
        lambda v: "first value" if pd.isna(v) else f"{v:+.1f} {unit} per month")
    top = 1.3 * max([df["value"].max()] + ([limit[0]] if limit else []))
    right = span[1] + 1 + (len(kin["band"]) if "band" in kin else 0)
    x = alt.X("month:Q", title="months since the first tumor sequencing",
              scale=alt.Scale(domain=[span[0] - 1, right]))
    y_scale = alt.Scale(domain=[0, top])
    tip = [alt.Tooltip("pointer:N", title="pointer"), alt.Tooltip("month:Q", title="month"),
           alt.Tooltip("value_text:N", title="value"), alt.Tooltip("flag:N", title="flag"),
           alt.Tooltip("change_text:N", title="change from previous"),
           alt.Tooltip("nadir_text:N", title="change from nadir"),
           alt.Tooltip("rate_text:N", title="rate"),
           alt.Tooltip("event:N", title="source event"),
           alt.Tooltip("evidence:N", title="evidence")]
    layers = []
    if intervals:
        iv = (pd.DataFrame(intervals).groupby(["start", "end", "ended_by"])["agent"]
              .agg(" + ".join).reset_index().sort_values("start").reset_index(drop=True))
        iv["lane"] = top * (0.98 - 0.07 * (iv.index % 3))
        iv["caution_end"] = iv["start"] + FLARE_MONTHS
        iv["caution"] = (f"first {FLARE_MONTHS} months after a therapy change: interpret with "
                         "caution (window is a placeholder)")
        layers.append(alt.Chart(iv).mark_rect(opacity=0.08, color=GRAY).encode(
            x="start:Q", x2="end:Q",
            tooltip=[alt.Tooltip("agent:N", title="treatment"), "start:Q", "end:Q",
                     alt.Tooltip("ended_by:N", title="interval ends by")]))
        layers.append(alt.Chart(iv).mark_rect(opacity=0.12, color=ORANGE).encode(
            x="start:Q", x2="caution_end:Q",
            tooltip=[alt.Tooltip("agent:N", title="after"),
                     alt.Tooltip("caution:N", title="window")]))
        layers.append(alt.Chart(iv).mark_text(align="left", dx=3, fontSize=10, color=GRAY)
                      .encode(x="start:Q", y=alt.Y("lane:Q", scale=y_scale), text="agent:N"))
    if band:
        bb = pd.DataFrame({"x": [span[0] - 1], "x2": [right], "lo": [band["lo"]],
                           "hi": [band["hi"]], "median": [band["median"]],
                           "label": [f"baseline band: median {band['median']:g}, range "
                                     f"{band['lo']:g} to {band['hi']:g} {unit}, from months "
                                     f"{band['months'][0]} to {band['months'][1]}"],
                           "method": [band["method"]]})
        layers.append(alt.Chart(bb).mark_rect(opacity=0.1, color=BLUE).encode(
            x="x:Q", x2="x2:Q", y=alt.Y("lo:Q", scale=y_scale), y2="hi:Q",
            tooltip=[alt.Tooltip("label:N", title="within-person baseline"),
                     alt.Tooltip("method:N", title="method")]))
        layers.append(alt.Chart(bb).mark_text(align="left", dx=3, dy=-6, fontSize=10,
                                              color=BLUE).encode(
            x="x:Q", y="hi:Q", text=alt.value(f"baseline, months {band['months'][0]} to "
                                              f"{band['months'][1]}")))
    if limit:
        ref = pd.DataFrame({"y": [limit[0]], "label": [f"reference limit {limit[0]:g} {unit}"],
                            "source": [limit[1]], "month": [right]})
        layers.append(alt.Chart(ref).mark_rule(strokeDash=[5, 4], color=RED, opacity=0.7).encode(
            y=alt.Y("y:Q", scale=y_scale),
            tooltip=[alt.Tooltip("label:N", title="reference"),
                     alt.Tooltip("source:N", title="source")]))
        layers.append(alt.Chart(ref).mark_text(align="right", dy=-7, fontSize=10, color=RED)
                      .encode(x="month:Q", y="y:Q", text="label:N"))
    if "band" in kin:
        kb = pd.DataFrame(kin["band"])
        kb["what"] = ("extrapolation at the current rate (model inference, placeholder method): "
                      + kin["caveat"])
        kb["range"] = (f"pairwise-rate range {kin['rate_range'][0]:+.3f} to "
                       f"{kin['rate_range'][1]:+.3f} log-units per month")
        ktip = [alt.Tooltip("month:Q", title="month", format=".0f"),
                alt.Tooltip("value:Q", title="if the rate held", format=".0f"),
                alt.Tooltip("lo:Q", title="low", format=".0f"),
                alt.Tooltip("hi:Q", title="high", format=".0f"),
                alt.Tooltip("what:N", title="what this is"),
                alt.Tooltip("range:N", title="uncertainty")]
        layers.append(alt.Chart(kb).mark_area(opacity=0.15, color=ORANGE).encode(
            x="month:Q", y=alt.Y("lo:Q", scale=y_scale), y2="hi:Q", tooltip=ktip))
        layers.append(alt.Chart(kb).mark_line(strokeDash=[3, 3], color=ORANGE).encode(
            x="month:Q", y="value:Q", tooltip=ktip))
    base = alt.Chart(df).encode(x=x, y=alt.Y("value:Q", title=f"{rows[0]['marker']} ({unit})",
                                              scale=y_scale))
    layers.append(base.mark_line(color=GRAY, strokeWidth=1.5))
    layers.append(base.mark_circle(size=110, opacity=1).encode(
        color=alt.Color("flag:N", scale=alt.Scale(domain=list(COLORS),
                                                  range=list(COLORS.values())),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=tip))
    layers.append(base.mark_text(dy=-13, fontSize=10, fontWeight="bold").encode(
        text="pointer:N"))
    return alt.layer(*layers).properties(height=340).configure_axis(**GRID)


def _table(rows: list[dict], reviews: dict | None = None,
           file: PatientFile | None = None) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "pointer": df["pointer"], "marker": df["marker"], "month": df["month"],
        "value": [f"{v:g} {u}" for v, u in zip(df["value"], df["unit"], strict=True)],
        "reference": df["reference"], "reference source": df["reference_source"],
        "flag": df["flag"], "change from previous": df["change"].map(pct),
        "per month": df["per_month"].map(lambda v: "" if pd.isna(v) else f"{v:+.1f}"),
        "change from nadir": df["from_nadir"].map(pct), "evidence": df["evidence"],
        "source event": df["event"]})
    if reviews is not None:
        out.insert(1, "review", [_marks_of(file, r, reviews) for r in rows])
    return out


def _key(file: PatientFile, r: dict) -> str:
    """The workspace's name for this result's finding, shared with the shell's review store."""
    return finding_key(file, "lab", r["key"], r["month"])


def _marks_of(file: PatientFile, r: dict, reviews: dict) -> str:
    done = reviews.get(_key(file, r)) if r["flags"] else None
    return f"{done['mark']} ({done['by'] or 'no initials'})" if done else ""


def _sync_reviews(file: PatientFile, flagged: list[dict], reviews: dict) -> None:
    """Read the review widgets' state into the workspace's review store, in its shape
    ({"what", "mark", "by", "at"} under ``finding_key``), before anything that shows the marks
    is drawn, so filters never lag a click."""
    by = st.session_state.get("reviewer", "") or ""  # the shell's sidebar field
    for r in flagged:
        key = _key(file, r)
        choice = st.session_state.get(f"mark_{key}", NO_MARK)
        if choice == NO_MARK:
            reviews.pop(key, None)
        elif key not in reviews or reviews[key]["mark"] != choice:
            reviews[key] = {"what": f"{r['marker']} {r['value']:g} {r['unit']} at month "
                                    f"{r['month']}: {r['flag']} ({r['pointer']})",
                            "mark": choice, "by": by,
                            "at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def render(file: PatientFile, events: list[dict] | None = None,
           version: int | None = None) -> None:
    """The workbench for one patient file, drawn inside the current container (no page config,
    no sidebar). Synthetic files use ``muffle.timeline.EVENTS`` (or ``events``); with
    ``version`` (an index into ``file.versions``) the workbench is shown as of that version's
    month, with flags computed from the results up to it only. A TCGA file holds no lab
    results unless some were imported in this session (``events``), and the page says so."""
    st.subheader("Blood and lab workbench")
    st.caption(f"{file.id} · {file.title}")
    events = (EVENTS if file.kind == "synthetic" else []) if events is None else events
    if version is not None:
        cutoff = file.versions[version].month  # None: a TCGA baseline, before any import
        kept = [e for e in events if cutoff is not None and e["month"] <= cutoff]
        later, events = len(events) - len(kept), kept
        if events:
            st.caption(f"As of month {cutoff} ({file.versions[version].label}): {later} later "
                       "events hidden, flags computed from the results up to here.")
    if not events:
        chips(IMPLEMENTED)
        st.info("This file holds no lab results: TCGA-BRCA has one tumor sample per patient and "
                "no blood panels, so there is no series to trend. Lab results can be imported "
                "(Import tests); see the synthetic patient's file for what the workbench shows.")
        _planned()
        _card()
        st.caption(CAVEAT)
        return
    rows, queue = results_table(events), look_here(events)
    checks, intervals = quality_checks(events), treatment_intervals(events)
    span = (min(e["month"] for e in events), max(e["month"] for e in events))
    flagged = [r for r in rows if r["flags"]]
    kin = {key: kinetics(rows, key) for key in MARKERS}
    bands = {key: baseline_band(rows, key) for key in MARKERS}
    tracker, windows = confirmation_tracker(rows), therapy_windows(rows, intervals)
    lag, cross = lead_lag(rows, events), cross_marker(rows)
    reviews = st.session_state.setdefault("reviews", {})  # the workspace's one store per file
    _sync_reviews(file, flagged, reviews)
    mine = {k: v for k, v in reviews.items() if k.startswith(f"{file.id}|lab|")}
    synthetic = file.kind == "synthetic"
    chips(IMPLEMENTED, LITERATURE_CHIP, PLACEHOLDER_CHIP,
          "synthetic patient" if synthetic else "imported this session")
    if synthetic:
        st.warning("Synthetic patient: this record was written by hand and is not a real "
                   "person. Its values exist to show how the workbench reads a series.")
    else:
        st.info("These lab results were imported in this browser session; TCGA-BRCA itself "
                "holds none.")
    st.caption(PROVENANCE)

    # overview: one paragraph, with the pointers every view shares
    measured = sorted({r["marker"] for r in rows})
    latest = {r["marker"]: r for r in rows}  # rows are in month order, so the last wins
    unmeasured = [name for name, _ in MARKERS.values() if name not in measured]
    lines = [
        f"**{len(rows)} results** for {', '.join(measured) or 'no marker'} over months "
        f"{span[0]} to {span[1]}"
        + (f"; {', '.join(unmeasured)} never measured" if unmeasured else "") + ". Latest: "
        + "; ".join(f"{m} {r['value']:g} {r['unit']} at month {r['month']} "
                    f"({r['pointer'] or 'no flag'}, {r['flag']})" for m, r in latest.items())
        + f". {len(flagged)} of {len(rows)} results flagged"
        + (f" ({flagged[0]['pointer']} to {flagged[-1]['pointer']})" if flagged else "")
        + f", {n_of(len(queue), 'open item')} in the look-here queue, "
        f"{n_of(sum(not c['ok'] for c in checks), 'quality check')} failing, "
        f"{n_of(len(mine), 'review mark')}."]
    for t in tracker:
        lines.append(f"{t['pointer']}: the rise at month {t['month']} is **{t['outcome']}** "
                     f"({t['detail']}).")
    for w in windows:
        lines.append(f"{w['pointer'] or 'month ' + str(w['month'])} lies {w['months_after']} "
                     f"months after {w['therapy']} started: {w['note']}.")
    for k in kin.values():
        if "rate_per_month" in k:
            time = next((f"{n.split('_')[0]} time about {k[n]:.0f} months" for n in
                         ("doubling_months", "halving_months") if n in k), "flat")
            lines.append(f"Kinetics (model inference, placeholder method): {k['marker']} "
                         f"{k['direction']}, {time}"
                         + (f"; {k['crossing']['text']}" if k["crossing"] else "")
                         + f". {cap(k['caveat'])}.")
    lines.append("All values observed; every flag is plain arithmetic against the record's "
                 "reference limit or the EGTM 25% rise criterion (a rise is unconfirmed until "
                 "a second specimen within a month).")
    st.markdown(" ".join(lines))

    # trends: one chart per marker, hover for brief stats
    st.markdown("#### Trends")
    chips(IMPLEMENTED, LITERATURE_CHIP, PLACEHOLDER_CHIP, INFERENCE_CHIP)
    st.caption("Hover a point for its pointer, value, change from the previous value and from "
               "the nadir, rate and source event. Gray spans are treatment intervals (the "
               "record holds starts only: a span ends at the next treatment event or the "
               "record's end); the orange strip after each start is the caution window. The "
               "dashed red line is the reference limit the record states; the blue band is the "
               "within-person baseline; the orange dashed band after the last value is the "
               "kinetics extrapolation, model inference with a placeholder method.")
    for key, (name, unit) in MARKERS.items():
        series = [r for r in rows if r["key"] == key]
        if not series:
            st.caption(f"{name}: no values in the record.")
            continue
        st.altair_chart(trend(series, intervals, unit, REFERENCE_LIMITS.get(key), span,
                              bands[key], kin[key]), width="stretch")

    # spot panel: one value in full
    st.markdown("#### Spot panel")
    chips(IMPLEMENTED, LITERATURE_CHIP, PLACEHOLDER_CHIP)
    labels = [_lab(r) for r in rows]
    default = labels.index(_lab(flagged[-1])) if flagged else len(labels) - 1
    picked = st.selectbox("Value", labels, index=default, key=f"{file.id}_spot")
    s = spot(rows[labels.index(picked)], rows, events)
    r = s["row"]
    st.markdown(
        f"**{r['marker']} {r['value']:g} {r['unit']}** at month {r['month']} "
        f"({r['pointer'] or 'no flag'}; evidence: {s['evidence']}). Reference {r['reference']} "
        f"({r['reference_source']}). Change from previous {pct(r['change'])}, from nadir "
        f"{pct(r['from_nadir'])}, rate "
        + ("first value" if r["per_month"] is None else f"{r['per_month']:+.1f} {r['unit']} per "
                                                        "month") + ".")
    st.markdown("**Rules that fired:** " + ("; ".join(
        f"{f['flag']} ({f['rule']}; threshold: {f['threshold']}; {f['status']})"
        for f in s["fired"]) or "none: within the limit, no rise or fall by the rules"))
    st.markdown("**Events around it (±2 months):**\n" + "\n".join(
        f"- month {e['month']}, {e['kind']}: {e['text']}" for e in s["events_around"]))
    st.markdown("**Check by eye before reading anything into it:**\n"
                + "\n".join(f"- {c}" for c in s["check_by_eye"]))

    # kinetics
    st.markdown("#### Marker kinetics")
    chips(IMPLEMENTED, INFERENCE_CHIP, PLACEHOLDER_METHOD_CHIP)
    for k in kin.values():
        if "rate_per_month" not in k:
            st.caption(f"{k['marker']}: {k.get('note', 'no values')}.")
            continue
        time = [(n.split("_")[0] + " time", k[n], k.get(f"{n}_range"))
                for n in ("doubling_months", "halving_months") if n in k]
        st.markdown(
            f"**{k['marker']}**, from the values at months {k['months'][0]} to "
            f"{k['months'][1]}: rate {k['rate_per_month']:+.3f} log-units per month "
            f"(pairwise range {k['rate_range'][0]:+.3f} to {k['rate_range'][1]:+.3f}), "
            f"{k['direction']}"
            + "".join(f"; {n} about {v:.0f} months"
                      + (f" (range {rng[0]:.0f} to {rng[1]:.0f})" if rng else "")
                      for n, v, rng in time)
            + (f". {cap(k['crossing']['text'])}"
               + (f" (range {k['crossing']['range_months'][0]:.1f} to "
                  f"{k['crossing']['range_months'][1]:.1f})"
                  if k["crossing"]["range_months"] else "") if k["crossing"] else
               ". Not heading towards the reference limit at the current rate") + ".")
        st.caption(f"Method: {k['method']}. Evidence: {k['evidence']}. Status: {k['status']}. "
                   f"{cap(k['caveat'])}.")

    # EGTM confirmation tracker
    st.markdown("#### Rise confirmation (EGTM)")
    chips(IMPLEMENTED, LITERATURE_CHIP)
    st.caption("A 25% rise is unconfirmed until a second specimen within a month confirms it. "
               "Each flagged rise, with the month its confirming specimen was due by and what "
               "the next value did.")
    if tracker:
        st.dataframe(pd.DataFrame(tracker)[["pointer", "marker", "month", "value", "previous",
                                            "due_by", "outcome", "detail", "evidence",
                                            "status"]], hide_index=True, width="stretch")
    else:
        st.caption("No flagged rise in the results shown.")

    # therapy windows
    st.markdown("#### Early after a therapy change")
    chips(IMPLEMENTED, LITERATURE_CHIP, PLACEHOLDER_CHIP)
    source = windows[0]["source"] if windows else "see the rules card"
    st.caption(f"Values within {FLARE_MONTHS} months of a new systemic therapy. A transient "
               "marker surge in the first weeks of effective therapy is in the literature; "
               f"the window length is a placeholder. Source: {source}.")
    if windows:
        st.dataframe(pd.DataFrame(windows)[["pointer", "marker", "month", "value", "therapy",
                                            "started", "months_after", "note", "window"]],
                     hide_index=True, width="stretch")
    else:
        st.caption("No value falls in a caution window.")

    # baseline band
    st.markdown("#### Within-person baseline")
    chips(IMPLEMENTED, PLACEHOLDER_CHIP)
    for key, band in bands.items():
        if band:
            st.markdown(f"**{band['marker']}**: median {band['median']:g}, range {band['lo']:g} "
                        f"to {band['hi']:g} {MARKERS[key][1]}, built from {band['n']} results in "
                        f"months {band['months'][0]} to {band['months'][1]}. Method: "
                        f"{band['method']}. Evidence: {band['evidence']}.")
        elif any(r["key"] == key for r in rows):
            st.caption(f"{MARKERS[key][0]}: no run of three consecutive results without a rise "
                       "or fall, so no baseline band.")

    # lead and lag against imaging
    st.markdown("#### Markers against imaging")
    chips(IMPLEMENTED)
    st.caption("Each imaging report against the last marker result before it: the observed "
               "order of events in this record, not a validated lead time.")
    if lag:
        st.markdown("\n".join(f"- {x['pointer'] + ': ' if x['pointer'] else ''}{x['what']}"
                              for x in lag))
    else:
        st.caption("No imaging report after a result in the results shown.")

    # cross-marker view
    st.markdown("#### Cross-marker view")
    chips(cross["status"])
    a, b = cross["markers"]
    st.caption(f"{a} and {b}, each against its own limit; at every month both were measured, "
               f"a concordant rise, a discordant one, or neither. {cap(cross['caveat'])}.")
    if cross["pairs"]:
        st.dataframe(pd.DataFrame(cross["pairs"]), hide_index=True, width="stretch")
    else:
        st.caption(f"{cap(cross['note'])}.")

    # search
    st.markdown("#### Search")
    chips(IMPLEMENTED)
    query = st.text_input("Search the results in plain words", key=f"{file.id}_search",
                          placeholder="above the limit · rising · after palbociclib · month 11 "
                                      "· L4")
    if query:
        hit = search(query, rows, intervals)
        (st.markdown if hit["understood"] else st.warning)(hit["answer"])
        if hit["rows"]:
            st.dataframe(_table(hit["rows"], reviews, file), hide_index=True, width="stretch")

    # results table with filters
    st.markdown("#### Results")
    chips(IMPLEMENTED)
    c1, c2, c3 = st.columns([3, 1, 1])
    pick = c1.multiselect("Marker", measured, default=measured, key=f"{file.id}_labs_marker")
    only = c2.checkbox("Flagged only", key=f"{file.id}_labs_flagged")
    reviewed = c3.selectbox("Reviewed", ["all", "reviewed", "not reviewed"],
                            key=f"{file.id}_labs_reviewed")
    shown = [r for r in rows if r["marker"] in pick and (r["flags"] or not only)
             and (reviewed == "all"
                  or (reviewed == "reviewed") == bool(_marks_of(file, r, reviews)))]
    if shown:
        st.dataframe(_table(shown, reviews, file), hide_index=True, width="stretch")
    else:
        st.caption("No results match the filters.")

    # more info: one expander per flagged result, with review marks
    st.markdown("#### Flagged results: why, and your review")
    chips(IMPLEMENTED, LITERATURE_CHIP, PLACEHOLDER_CHIP)
    for r in reversed(flagged):
        with st.expander(f"{r['pointer']} · month {r['month']}: {r['marker']} {r['value']:g} "
                         f"{r['unit']}, {r['flag']}"):
            s = spot(r, rows, events)
            for f in s["fired"]:
                st.markdown(f"**{f['flag']}** · rule: {f['rule']} · threshold: "
                            f"{f['threshold']} · evidence: observed · status: {f['status']}")
            st.selectbox("Your review mark for this result", MARKS,
                         key=f"mark_{_key(file, r)}",
                         help="Marks go into this file's report export")
            st.markdown(f"Change from previous {pct(r['change'])}, from nadir "
                        f"{pct(r['from_nadir'])}; source: {r['event']}.")
            st.caption(f"Full {r['marker']} history (this result at month {r['month']}):")
            st.dataframe(_table(s["history"], reviews, file), hide_index=True, width="stretch")

    # look here
    st.markdown("#### Look here")
    chips(IMPLEMENTED, LITERATURE_CHIP, PLACEHOLDER_CHIP)
    st.caption("Every flagged result, latest first, one row per rule that fired, with its "
               "pointer and review mark. Observed values; the status names the source of each "
               "threshold.")
    if queue:
        q = pd.DataFrame(queue)
        q.insert(1, "review", [reviews.get(_key(file, i), {}).get("mark", "") for i in queue])
        st.dataframe(q[["pointer", "review", "month", "marker", "value", "unit", "flag", "rule",
                        "threshold", "evidence", "status", "event"]],
                     hide_index=True, width="stretch")
    else:
        st.caption("Nothing flagged.")

    # quality checks
    st.markdown("#### Quality checks")
    chips(IMPLEMENTED, PLACEHOLDER_CHIP)
    qc = pd.DataFrame(checks)
    qc.insert(0, "result", qc.pop("ok").map({True: "pass", False: "issue"}))
    st.dataframe(qc, hide_index=True, width="stretch")

    _planned()
    card = _card()

    # export
    st.markdown("#### Export")
    chips(IMPLEMENTED)
    main_key = next((k for k in MARKERS if "rate_per_month" in kin[k]), next(iter(MARKERS)))
    md = report_markdown(file.id, rows, queue, checks, card, kin[main_key], tracker, windows,
                         bands[main_key], lag, mine)
    e1, e2 = st.columns(2)
    e1.download_button("Download the lab report (Markdown)", md, file_name=f"{file.id}_labs.md",
                       mime="text/markdown", key=f"{file.id}_labs_md")
    e2.download_button("Download the results (CSV)",
                       _table(rows, reviews, file).to_csv(index=False),
                       file_name=f"{file.id}_labs.csv", mime="text/csv",
                       key=f"{file.id}_labs_csv")
    st.caption(CAVEAT)


def _planned() -> None:
    st.markdown("#### Planned")
    chips(PLANNED)
    st.dataframe(pd.DataFrame(PLANNED_PANELS, columns=["panel", "why not yet", "status"]),
                 hide_index=True, width="stretch")


def _card() -> dict:
    card = rules_card()
    st.markdown(f"#### {CARD}")
    chips(card["status"])
    st.markdown(f"**{card['name']}** · {card['kind']}  \n**Inputs:** {card['inputs']}  \n"
                f"**Outputs:** {card['outputs']}  \n**Evidence:** {card['evidence']}  \n"
                f"**Validation:** {card['validation']}")
    st.dataframe(pd.DataFrame(card["thresholds"]), hide_index=True, width="stretch")
    st.markdown("**Known failures:**\n" + "\n".join(f"- {f}" for f in card["known_failures"]))
    return card


if __name__ == "__main__":
    st.set_page_config(page_title="Blood and lab workbench", layout="wide")
    st.text_input("Reviewer initials", key="reviewer", max_chars=5)  # the shell's field
    render(synthetic_file(json.loads((APP / "timeline_synthetic.json").read_text("utf-8"))))

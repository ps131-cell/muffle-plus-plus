"""Blood and lab workbench for a patient file (docs/WORKSPACE.md, "Blood and lab panels").

streamlit run app/workbenches/labs.py        # the synthetic patient's workbench, standalone page

The workspace pages call ``render(file, events=None, version=None)`` with a
``muffle.workspace.PatientFile``; it draws inside the current container only. Any analyte in the
record or imported this session: the reference table (``muffle.workbench.labs_reference``) gives
the interval when the lab report did not. The page follows the shared skeleton
(``workbenches._page``): the overview (with pointers L1..Ln shared by every view, the look-here
queue and plain-word search), the trends by panel (hover for brief stats, the reference interval,
the baseline band and kinetics for tumor markers, treatment spans and caution windows), the
details (flagged results, the results table with filters, the EGTM confirmation tracker, therapy
windows, kinetics, the baseline band, markers against imaging, the cross-analyte hypotheses, the
cross-marker view, quality checks, planned panels), the Spot panel for one value with its review
mark, the rules card with the reference table, what the test cannot see and the exports. Every
number is plain arithmetic on observed values (``muffle.workbench.labs``) except the kinetics and
the calculated values (eGFR, adjusted calcium), which are model inference; an out-of-range value
is not evidence of progression by itself.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))
if str(APP) not in sys.path:  # standalone: streamlit run app/workbenches/labs.py
    sys.path.insert(0, str(APP))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle.timeline import EVENTS  # noqa: E402
from muffle.workbench import labs_reference as ref  # noqa: E402
from muffle.workbench.labs import (  # noqa: E402
    ABOVE,
    BELOW,
    FALLING,
    FLARE_MONTHS,
    LARGE_FALL,
    LARGE_RISE,
    PLANNED_PANELS,
    RISING,
    WITHIN,
    baseline_band,
    confirmation_tracker,
    cross_analyte,
    cross_marker,
    kinetics,
    lead_lag,
    look_here,
    quality_checks,
    reference_table,
    report_markdown,
    results_table,
    rules_card,
    search,
    spot,
    therapy_windows,
    treatment_intervals,
)
from muffle.workbench.labs import queue as lab_queue  # noqa: E402
from muffle.workspace import (  # noqa: E402
    IMPLEMENTED,
    PLANNED,
    PatientFile,
    finding_key,
    synthetic_file,
)
from muffle.workspace import MARKS as WORKSPACE_MARKS  # noqa: E402
from muffle.workbench.grammar import chip, count_label  # noqa: E402
from workbenches import imports  # noqa: E402
from workbenches._howto import how_to, instruct, pin_toggle  # noqa: E402
from workbenches._page import Page, land, line_and_action, queue_items  # noqa: E402

BLUE, ORANGE, RED, GRAY = "#2a78d6", "#eb6834", "#e34948", "#8a8f98"
COLORS = {WITHIN: BLUE, ABOVE: RED, BELOW: RED, RISING: ORANGE, FALLING: BLUE,
          LARGE_RISE: ORANGE, LARGE_FALL: ORANGE}  # by the first flag of a value
GRID = {"gridOpacity": 0.4, "domainOpacity": 0.4, "tickOpacity": 0.4}
PLACEHOLDER_CHIP, LITERATURE_CHIP = "placeholder threshold", "literature threshold"
INFERENCE_CHIP, PLACEHOLDER_METHOD_CHIP = "model inference", "placeholder method"
REFERENCE_LAB_CHIP, HYPOTHESIS_CHIP = "reference-laboratory interval", "hypothesis"
NO_MARK = "no mark"
MARKS = (NO_MARK, *WORKSPACE_MARKS)  # the workspace's marks, plus none
PROVENANCE = ("Data: the patient record's lab results and this session's imported ones "
              "(observed). Method: rules, version 2, plain arithmetic, no model; kinetics are a "
              "log-linear extrapolation and eGFR and adjusted calcium published equations "
              "(model inference). Thresholds: the reference interval on the lab report or in "
              "the record, else Mayo Clinic Laboratories' published adult interval (a reference "
              "laboratory's, read 2026-10-20); the 25% tumor-marker rise from the EGTM guidance "
              "(literature); low-count grades from CTCAE v5.0 (guideline); the fall, large "
              "change, gap, caution-window, baseline and cross-analyte rules are placeholders. "
              "Status: implemented, not validated on a cohort.")
CANNOT_SEE_LABS = [
    "lesions, their size or their site: imaging does; a raised value is not evidence of "
    "progression by itself (ASCO: tumor markers are adjuncts, never used alone)",
    "a change of assay or laboratory the record does not state; only a changed reference "
    "interval shows",
    "analytical and within-person variation: the change flags know no reference change value "
    "(biological variation data planned)",
    "whether a raised liver value comes from metastases or from a drug: the cross-analyte "
    "hypotheses name both, and a liver biopsy or imaging would tell",
    "an analyte that was never measured: the search names the panel that would show it",
]
HOW_TO = ("**Trends**: each analyte against its limits (click a point to open it). **Look "
          "here**: what to check first, and why. **Spot panel**, below: one value with its "
          "rules, your mark and a pin. **Add … values** brings in new results.")
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


def trend(rows: list[dict], intervals: list[dict], band: dict | None, kin: dict,
          picked: int | None = None) -> alt.Chart:
    """One analyte over months: points colored by their first flag with their pointers (hover
    for brief stats, a click selects the month: selection "pick"), the reference limits of the
    latest value with their source, the within-person baseline band and the kinetics
    extrapolation (tumor markers), treatment spans with their agents and, for tumor markers, the
    caution windows after each start. ``picked``: the month of the value in the Spot panel,
    ringed."""
    unit, last = rows[0]["unit"], rows[-1]
    span = (min(r["month"] for r in rows), max(r["month"] for r in rows))  # this analyte's own
    df = pd.DataFrame(rows)
    df["value_text"] = df["value"].map(lambda v: f"{v:g} {unit}")
    df["change_text"] = df["change"].map(pct)
    df["nadir_text"] = df["from_nadir"].map(pct)
    df["rate_text"] = df["per_month"].map(
        lambda v: "first value" if pd.isna(v) else f"{v:+.3g} {unit} per month")
    df["first_flag"] = [r["flags"][0] if r["flags"] else WITHIN for r in rows]
    limits = [(v, side) for v, side in ((last["low"], "lower"), (last["high"], "upper"))
              if v is not None]
    top = 1.3 * max([df["value"].max()] + [v for v, _ in limits])
    right = span[1] + 1 + (len(kin["band"]) if "band" in kin else 0)
    x_scale = alt.Scale(domain=[span[0] - 1, right], zero=False)  # every layer: rects add 0
    x = alt.X("month:Q", title="months since the first tumor sequencing", scale=x_scale)
    y_scale = alt.Scale(domain=[0, top])
    tip = [alt.Tooltip("pointer:N", title="pointer"), alt.Tooltip("month:Q", title="month"),
           alt.Tooltip("value_text:N", title="value"), alt.Tooltip("flag:N", title="flag"),
           alt.Tooltip("reference:N", title="reference"),
           alt.Tooltip("change_text:N", title="change from previous"),
           alt.Tooltip("nadir_text:N", title="change from nadir"),
           alt.Tooltip("rate_text:N", title="rate"),
           alt.Tooltip("event:N", title="source event"),
           alt.Tooltip("evidence:N", title="evidence")]
    layers = []
    if intervals:
        iv = (pd.DataFrame(intervals).groupby(["start", "end", "ended_by"])["agent"]
              .agg(" + ".join).reset_index().sort_values("start"))
        iv = iv[iv["end"] > span[0] - 1].assign(  # spans that began before the axis start on it
            start=lambda d: d["start"].clip(lower=span[0] - 1)).reset_index(drop=True)
        iv["lane"] = top * (0.98 - 0.07 * (iv.index % 3))
        layers.append(alt.Chart(iv).mark_rect(opacity=0.08, color=GRAY).encode(
            x=alt.X("start:Q", scale=x_scale), x2="end:Q",
            tooltip=[alt.Tooltip("agent:N", title="treatment"), "start:Q", "end:Q",
                     alt.Tooltip("ended_by:N", title="interval ends by")]))
        if rows[0]["tumor_marker"]:
            iv["caution_end"] = iv["start"] + FLARE_MONTHS
            iv["caution"] = (f"first {FLARE_MONTHS} months after a therapy change: interpret "
                             "with caution (window is a placeholder)")
            layers.append(alt.Chart(iv).mark_rect(opacity=0.12, color=ORANGE).encode(
                x=alt.X("start:Q", scale=x_scale), x2="caution_end:Q",
                tooltip=[alt.Tooltip("agent:N", title="after"),
                         alt.Tooltip("caution:N", title="window")]))
        layers.append(alt.Chart(iv).mark_text(align="left", dx=3, fontSize=10, color=GRAY)
                      .encode(x=alt.X("start:Q", scale=x_scale),
                              y=alt.Y("lane:Q", scale=y_scale), text="agent:N"))
    if band:
        bb = pd.DataFrame({"x": [span[0] - 1], "x2": [right], "lo": [band["lo"]],
                           "hi": [band["hi"]], "median": [band["median"]],
                           "label": [f"baseline band: median {band['median']:g}, range "
                                     f"{band['lo']:g} to {band['hi']:g} {unit}, from months "
                                     f"{band['months'][0]} to {band['months'][1]}"],
                           "method": [band["method"]]})
        layers.append(alt.Chart(bb).mark_rect(opacity=0.1, color=BLUE).encode(
            x=alt.X("x:Q", scale=x_scale), x2="x2:Q", y=alt.Y("lo:Q", scale=y_scale), y2="hi:Q",
            tooltip=[alt.Tooltip("label:N", title="within-person baseline"),
                     alt.Tooltip("method:N", title="method")]))
        layers.append(alt.Chart(bb).mark_text(align="left", dx=3, dy=-6, fontSize=10,
                                              color=BLUE).encode(
            x=alt.X("x:Q", scale=x_scale), y="hi:Q",
            text=alt.value(f"baseline, months {band['months'][0]} to {band['months'][1]}")))
    if limits:
        lim = pd.DataFrame({"y": [v for v, _ in limits],
                            "label": [f"{side} limit {v:g} {unit}" for v, side in limits],
                            "source": [last["reference_source"]] * len(limits),
                            "month": [right] * len(limits)})
        layers.append(alt.Chart(lim).mark_rule(strokeDash=[5, 4], color=RED, opacity=0.7).encode(
            y=alt.Y("y:Q", scale=y_scale),
            tooltip=[alt.Tooltip("label:N", title="reference"),
                     alt.Tooltip("source:N", title="source")]))
        layers.append(alt.Chart(lim).mark_text(align="right", dy=-7, fontSize=10, color=RED)
                      .encode(x=alt.X("month:Q", scale=x_scale), y="y:Q", text="label:N"))
    if "band" in kin:
        kb = pd.DataFrame(kin["band"])
        kb["what"] = ("extrapolation at the current rate (model inference, placeholder method): "
                      + kin["caveat"])
        kb["range"] = (f"pairwise-rate range {kin['rate_range'][0]:+.3f} to "
                       f"{kin['rate_range'][1]:+.3f} log-units per month")
        ktip = [alt.Tooltip("month:Q", title="month", format=".0f"),
                alt.Tooltip("value:Q", title="if the rate held", format=".3g"),
                alt.Tooltip("lo:Q", title="low", format=".3g"),
                alt.Tooltip("hi:Q", title="high", format=".3g"),
                alt.Tooltip("what:N", title="what this is"),
                alt.Tooltip("range:N", title="uncertainty")]
        layers.append(alt.Chart(kb).mark_area(opacity=0.15, color=ORANGE).encode(
            x=alt.X("month:Q", scale=x_scale), y=alt.Y("lo:Q", scale=y_scale), y2="hi:Q",
            tooltip=ktip))
        layers.append(alt.Chart(kb).mark_line(strokeDash=[3, 3], color=ORANGE).encode(
            x=alt.X("month:Q", scale=x_scale), y="value:Q", tooltip=ktip))
    base = alt.Chart(df).encode(x=x, y=alt.Y("value:Q", title=f"{rows[0]['marker']} ({unit})",
                                              scale=y_scale))
    layers.append(base.mark_line(color=GRAY, strokeWidth=1.5))
    if picked is not None and (df["month"] == picked).any():
        layers.append(alt.Chart(df[df["month"] == picked]).mark_point(
            size=420, filled=False, strokeWidth=2.5, color="#1f2329").encode(
            x=x, y=alt.Y("value:Q", scale=y_scale),
            tooltip=alt.value("this value is open in the Spot panel")))
    layers.append(base.mark_circle(size=110, opacity=1).encode(
        color=alt.Color("first_flag:N", scale=alt.Scale(
            domain=[f for f in COLORS if f in set(df["first_flag"])],
            range=[c for f, c in COLORS.items() if f in set(df["first_flag"])]),
            legend=alt.Legend(orient="bottom", title="flag (observed value)")),
        tooltip=tip).add_params(alt.selection_point(name="pick", fields=["month"], on="click")))
    layers.append(base.mark_text(dy=-13, fontSize=10, fontWeight="bold").encode(
        text="pointer:N"))
    return alt.layer(*layers).properties(height=300).configure_axis(**GRID)


def trend_alt(series: list[dict]) -> str:
    """A trend chart in words, for a screen reader: the analyte, its values and its flags."""
    return (f"{series[0]['marker']} in {series[0]['unit']} over months {series[0]['month']} to "
            f"{series[-1]['month']}: " + "; ".join(
                f"month {r['month']} {r['value']:g}" + (f" ({r['pointer']}, {r['flag']})"
                                                       if r["pointer"] else "")
                for r in series))


def _table(rows: list[dict], reviews: dict | None = None,
           file: PatientFile | None = None) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "pointer": df["pointer"], "marker": df["marker"], "month": df["month"],
        "value": [f"{v:g} {u}" for v, u in zip(df["value"], df["unit"], strict=True)],
        "reference": df["reference"], "reference source": df["reference_source"],
        "flag": df["flag"], "change from previous": df["change"].map(pct),
        "per month": df["per_month"].map(lambda v: "" if pd.isna(v) else f"{v:+.3g}"),
        "change from nadir": df["from_nadir"].map(pct), "panel": df["panel"],
        "evidence": df["evidence"], "source event": df["event"]})
    if reviews is not None:
        out.insert(1, "review", [_marks_of(file, r, reviews) for r in rows])
    return out


def _key(file: PatientFile, r: dict) -> str:
    """The workspace's name for this result's finding, shared with the shell's review store."""
    return finding_key(file, "lab", r["key"], r["month"])


def _marks_of(file: PatientFile, r: dict, reviews: dict) -> str:
    done = reviews.get(_key(file, r)) if r["flags"] else None
    return f"{done['mark']} ({done['by'] or 'no initials'})" if done else ""


def _set_mark(file: PatientFile, r: dict) -> None:
    """A review widget changed: write its mark into the workspace's review store, in its shape
    ({"what", "mark", "by", "at"} under ``finding_key``). The store is the truth (the report's
    attention queue marks lab results too); a callback runs before the page, so filters never
    lag a click."""
    key = _key(file, r)
    reviews = st.session_state.setdefault("reviews", {})
    choice = st.session_state[f"mark_{key}"]
    if choice == NO_MARK:
        reviews.pop(key, None)
    else:
        reviews[key] = {"what": f"{r['marker']} {r['value']:g} {r['unit']} at month "
                                f"{r['month']}: {r['flag']} ({r['pointer']})",
                        "mark": choice, "by": st.session_state.get("reviewer", "") or "",
                        "at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def render(file: PatientFile, events: list[dict] | None = None,
           version: int | None = None, test=None) -> None:
    """The workbench for one patient file, drawn inside the current container (no page config,
    no sidebar) in the shared page skeleton (``workbenches._page``). Synthetic files use
    ``muffle.timeline.EVENTS`` (or ``events``); with ``version`` (an index into
    ``file.versions``) the workbench is shown as of that version's month, with flags computed
    from the results up to it only. A TCGA file holds no lab results unless some were imported
    in this session (``events``), and the page says so. ``test`` is the test it was opened
    from, for the title."""
    page = Page("labs", file, test, version)
    events = (EVENTS if file.kind == "synthetic" else []) if events is None else events
    later = 0
    if version is not None:
        cutoff = file.versions[version].month  # None: a TCGA baseline, before any import
        kept = [e for e in events if cutoff is not None and e["month"] <= cutoff]
        later, events = len(events) - len(kept), kept
    if not any(k in ref.ANALYTES or k.startswith("lab:") for e in events for k in e):
        page.title(IMPLEMENTED)
        st.caption(PROVENANCE)
        with page.overview():
            st.info("No lab results in this file: TCGA-BRCA holds one tumor sample per patient "
                    "and no blood panels, so there is no series to trend. A lab results file "
                    "(CSV) brought in through **Import tests** would open this workbench; the "
                    "synthetic patient's file shows what it does with a series.", icon="🧪")
        _planned(page)
        _card(page)
        with page.cannot_see(CANNOT_SEE_LABS):
            pass
        with page.export(empty="Nothing to export: this file holds no lab results."):
            pass
        st.caption(CAVEAT)
        return
    synthetic = file.kind == "synthetic"
    imported = any("(imported" in e.get("text", "") for e in events)
    page.title(IMPLEMENTED, REFERENCE_LAB_CHIP, LITERATURE_CHIP, PLACEHOLDER_CHIP,
               *(["synthetic patient"] if synthetic else []),
               *(["imported this session"] if imported else []))
    how_to("labs", HOW_TO)
    if synthetic:
        st.warning("Synthetic patient: this record was written by hand and is not a real "
                   "person. Its values exist to show how the workbench reads a series"
                   + (", next to the results imported in this session." if imported else "."))
    else:
        st.info("These lab results were imported in this browser session; TCGA-BRCA itself "
                "holds none.")
    st.caption(PROVENANCE)
    if later:
        st.caption(f"As of month {file.versions[version].month} "
                   f"({file.versions[version].label}): {later} later events hidden, flags "
                   "computed from the results up to here.")
    c1, c2 = st.columns(2)
    sex = c1.selectbox("Sex, for sex-specific intervals and eGFR", ["not recorded", "female",
                                                                     "male"],
                       key=f"{file.id}_labs_sex",
                       help="The record states no sex; set it here to use the sex-specific "
                            "intervals. Kept for this browser session.")
    sex = None if sex == "not recorded" else sex
    age = c2.number_input("Age in years, for eGFR", min_value=18, max_value=110, value=None,
                          step=1, key=f"{file.id}_labs_age",
                          help="The 2021 CKD-EPI equation needs age and sex; the record "
                               "states no age.")
    rows = results_table(events, sex=sex, age=age)
    queue = look_here(events, sex=sex, age=age)
    checks = quality_checks(events, sex=sex, age=age)
    intervals = treatment_intervals(events)
    span = (min(r["month"] for r in rows), max(r["month"] for r in rows))
    flagged = [r for r in rows if r["flags"]]
    keys = list(dict.fromkeys(r["key"] for r in rows))
    markers = [k for k in keys if k in ref.TUMOR_MARKERS]
    kin = {key: kinetics(rows, key) for key in markers}
    bands = {key: baseline_band(rows, key) for key in markers}
    tracker, windows = confirmation_tracker(rows), therapy_windows(rows, intervals)
    lag, cross = lead_lag(rows, events), cross_marker(rows)
    hyp = cross_analyte(rows, events)
    reviews = st.session_state.setdefault("reviews", {})  # the workspace's one store per file
    mine = {k: v for k, v in reviews.items() if k.startswith(f"{file.id}|lab|")}
    labels = [_lab(r) for r in rows]
    spot_key = f"{file.id}_spot"
    if st.session_state.get(spot_key) not in labels:  # the latest flagged value, else the last
        st.session_state[spot_key] = _lab(flagged[-1]) if flagged else labels[-1]
    open_row = rows[labels.index(st.session_state[spot_key])]  # ringed in its trend

    # overview: one paragraph with the pointers every view shares, the look-here queue, search
    measured = list(dict.fromkeys(r["marker"] for r in rows))
    latest = {r["marker"]: r for r in rows}  # rows are in month order, so the last wins
    unmeasured = [ref.ANALYTES[k]["name"] for k in ("ca153", "cea") if k not in keys]
    lines = [
        f"**{len(rows)} results** for {n_of(len(measured), 'analyte')} over months {span[0]} "
        f"to {span[1]}" + (f"; {', '.join(unmeasured)} never measured" if unmeasured else "")
        + ". Latest: " + "; ".join(
            f"{m} {r['value']:g} {r['unit']} at month {r['month']} ({r['pointer'] or 'no flag'}, "
            f"{r['flag']})" for m, r in latest.items() if r["flags"] or len(latest) <= 3)
        + "".join(f"; within the interval: {', '.join(ok)}" for ok in [
            [m for m, r in latest.items() if not r["flags"]]] if ok and len(latest) > 3)
        + f". {len(flagged)} of {len(rows)} results flagged"
        + (f" ({flagged[0]['pointer']} to {flagged[-1]['pointer']})" if flagged else "")
        + f", {n_of(sum(not c['ok'] for c in checks), 'quality check')} failing, "
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
    if hyp:
        lines.append(f"{n_of(len(hyp), 'cross-analyte hypothesis')}"
                     .replace("hypothesiss", "hypotheses") + " (for clinician review): "
                     + "; ".join(f"{h['site'].lower()} report of month {h['imaging_month']} with "
                                 + ", ".join(h["pointers"]) for h in hyp) + ".")
    with page.overview():
        st.markdown(" ".join(lines))
        st.caption("All values observed; every flag is plain arithmetic against the value's "
                   "reference interval (its source named with it), the EGTM 25% rise criterion "
                   "for tumor markers (a rise is unconfirmed until a second specimen within a "
                   "month) or a placeholder.")
        page.look_here(instruct(look_items(file, version)),
                       land=lambda focus: land(file, page.version, focus),
                       more="Details › Flagged results")
        query = st.text_input("Search the results in plain words", key=f"{file.id}_search",
                              placeholder="above the limit · below · rising · after palbociclib "
                                          "· month 11 · L4 · liver · neutrophils")
        if query:
            hit = search(query, rows, intervals)
            (st.markdown if hit["understood"] else st.warning)(hit["answer"])
            if hit["rows"]:
                st.dataframe(_table(hit["rows"], reviews, file), hide_index=True,
                             width="stretch")

    # the picture: one trend per analyte, by panel, hover for brief stats
    with page.picture("Trends", caption=(
            "Hover a point for its pointer, value, reference, change from the previous value "
            "and from the nadir, rate and source event. Gray spans: treatment intervals (the "
            "record holds starts only, so a span ends at the next treatment or the record's "
            "end). For tumor markers: the orange strip after each start is the caution window, "
            "the blue band the within-person baseline, the orange dashed band after the last "
            "value the kinetics extrapolation (model inference, placeholder method). Dashed red "
            "lines: the latest value's reference limits. **Click a point** to open it in the "
            "Spot panel; the ringed point is the one open there. The chart cannot show lesions "
            "or their size (imaging does), an assay change the record does not state, or "
            "analytical variation (no reference change value).")):
        chips(IMPLEMENTED, REFERENCE_LAB_CHIP, LITERATURE_CHIP, PLACEHOLDER_CHIP, INFERENCE_CHIP)
        panels = [p for p in (*ref.PANELS, ref.UNLISTED) if any(r["panel"] == p for r in rows)]
        synced = f"{file.id}_labs_panel_of"  # the tabs follow the Spot value to its panel
        if st.session_state.get(synced) != st.session_state[spot_key]:
            st.session_state[synced] = st.session_state[spot_key]
            st.session_state[f"{file.id}_labs_panels"] = open_row["panel"]
        tabs = st.tabs(panels, key=f"{file.id}_labs_panels", on_change="rerun")
        for tab, panel in zip(tabs, panels, strict=True):
            with tab:  # a panel's charts run only while its tab is open
                if not tab.open:
                    continue
                for key in dict.fromkeys(r["key"] for r in rows if r["panel"] == panel):
                    series = [r for r in rows if r["key"] == key]
                    picked = open_row["month"] if open_row["key"] == key else None
                    chart_key = f"{file.id}_trend_{key}"
                    st.altair_chart(trend(series, intervals, bands.get(key), kin.get(key, {}),
                                          picked), width="stretch", alt=trend_alt(series),
                                    key=chart_key, on_select=_point_to_spot(chart_key, series,
                                                                           spot_key),
                                    selection_mode="pick")
                    a = ref.ANALYTES.get(key)
                    note, add = line_and_action()
                    note.caption(f"{series[0]['marker']}: " + (
                        f"{a['why']} ({a['why_source']})." if a else
                        f"{ref.UNLISTED}: flagged only against the interval its lab report "
                        "gave."))
                    if add.button(f"Add {series[0]['marker']} values…", key=f"{chart_key}_add",
                                  help="Opens Import tests with this analyte and its unit filled "
                                       "in; the values join the file as a new report version"):
                        imports.open_dialog(file, {"marker": series[0]["marker"],
                                                   "unit": series[0]["unit"]})

    # details: collapsed, each with its count
    with page.details("Flagged results", len(queue)):
        chips(IMPLEMENTED, REFERENCE_LAB_CHIP, LITERATURE_CHIP, PLACEHOLDER_CHIP)
        st.caption("Every flagged result, latest first, one row per rule that fired, with its "
                   "pointer and review mark; the status names the source of each threshold. "
                   "Click a row to open the value in the Spot panel.")
        if queue:
            q = pd.DataFrame(queue)
            q.insert(1, "review", [reviews.get(_key(file, i), {}).get("mark", "") for i in queue])
            picks = [_lab(next(r for r in rows if (r["key"], r["month"]) == (i["key"],
                                                                          i["month"])))
                     for i in queue]
            _pick_table(q[["pointer", "review", "month", "marker", "value", "unit", "flag",
                           "rule", "threshold", "evidence", "status", "event"]], picks,
                        f"{file.id}_labs_flags", spot_key)
        else:
            st.caption("Nothing flagged.")
    with page.details("Results", len(rows)):
        chips(IMPLEMENTED)
        c1, c2, c3 = st.columns([3, 1, 1])
        pick = c1.multiselect("Analyte", measured, key=f"{file.id}_labs_marker",
                              placeholder="all analytes") or measured  # new ones join "all"
        only = c2.checkbox("Flagged only", key=f"{file.id}_labs_flagged")
        reviewed = c3.selectbox("Reviewed", ["all", "reviewed", "not reviewed"],
                                key=f"{file.id}_labs_reviewed")
        shown = [r for r in rows if r["marker"] in pick and (r["flags"] or not only)
                 and (reviewed == "all"
                      or (reviewed == "reviewed") == bool(_marks_of(file, r, reviews)))]
        if shown:
            _pick_table(_table(shown, reviews, file), [_lab(r) for r in shown],
                        f"{file.id}_labs_results", spot_key)
            st.caption("Click a row to open the value in the Spot panel.")
        else:
            st.caption("No results match the filters.")
    with page.details("Rise confirmation, EGTM", len(tracker)):
        chips(IMPLEMENTED, LITERATURE_CHIP)
        st.caption("A 25% rise of a tumor marker is unconfirmed until a second specimen within a "
                   "month confirms it. Each flagged rise, with the month its confirming specimen "
                   "was due by and what the next value did.")
        if tracker:
            st.dataframe(pd.DataFrame(tracker)[["pointer", "marker", "month", "value",
                                                "previous", "due_by", "outcome", "detail",
                                                "evidence", "status"]],
                         hide_index=True, width="stretch")
        else:
            st.caption("No flagged rise in the results shown.")
    with page.details("Early after a therapy change", len(windows)):
        chips(IMPLEMENTED, LITERATURE_CHIP, PLACEHOLDER_CHIP)
        source = windows[0]["source"] if windows else "see the Model and validation card"
        st.caption(f"Tumor-marker values within {FLARE_MONTHS} months of a new systemic therapy. "
                   "A transient marker surge in the first weeks of effective therapy is in the "
                   f"literature; the window length is a placeholder. Source: {source}.")
        if windows:
            st.dataframe(pd.DataFrame(windows)[["pointer", "marker", "month", "value",
                                                "therapy", "started", "months_after", "note",
                                                "window"]],
                         hide_index=True, width="stretch")
        else:
            st.caption("No value falls in a caution window.")
    moving = [k for k in kin.values() if "rate_per_month" in k]
    with page.details("Marker kinetics", len(moving)):
        chips(IMPLEMENTED, INFERENCE_CHIP, PLACEHOLDER_METHOD_CHIP)
        if not kin:
            st.caption("No tumor marker on file: kinetics are drawn for tumor markers only.")
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
            st.caption(f"Method: {k['method']}. Evidence: {k['evidence']}. Status: "
                       f"{k['status']}. {cap(k['caveat'])}.")
    with page.details("Within-person baseline", sum(bool(b) for b in bands.values())):
        chips(IMPLEMENTED, PLACEHOLDER_CHIP)
        if not bands:
            st.caption("No tumor marker on file: baseline bands are built for tumor markers "
                       "only.")
        for key, band in bands.items():
            if band:
                st.markdown(f"**{band['marker']}**: median {band['median']:g}, range "
                            f"{band['lo']:g} to {band['hi']:g} {ref.ANALYTES[key]['unit']}, built "
                            f"from {band['n']} results in months {band['months'][0]} to "
                            f"{band['months'][1]}. Method: {band['method']}. Evidence: "
                            f"{band['evidence']}.")
            else:
                st.caption(f"{ref.ANALYTES[key]['name']}: no run of three consecutive results "
                           "without a rise or fall, so no baseline band.")
    with page.details("Markers against imaging", len(lag)):
        chips(IMPLEMENTED)
        st.caption("Each imaging report against the last tumor-marker result before it: the "
                   "observed order of events in this record, not a validated lead time.")
        if lag:
            st.markdown("\n".join(f"- {x['pointer'] + ': ' if x['pointer'] else ''}{x['what']}"
                                  for x in lag))
        else:
            st.caption("No imaging report after a tumor-marker result in the results shown.")
    with page.details("Cross-analyte hypotheses", len(hyp)):
        chips(IMPLEMENTED, HYPOTHESIS_CHIP, LITERATURE_CHIP, PLACEHOLDER_CHIP)
        st.caption("Raised or rising bone or liver values next to an imaging report that names "
                   "the site: hypotheses for clinician review, each naming the report it refers "
                   "to, its literature and the other causes the rule cannot rule out.")
        for h in hyp:
            with st.container(border=True):
                st.markdown(f"**{h['site']}** · {cap(h['hypothesis'])}. *{h['evidence']}*")
                st.markdown("Values: " + "; ".join(h["values"]) + "."
                            + "".join(f" {cap(g)}." for g in h["ggt"]))
                st.caption(f"{cap(h['other_causes'])}. Source: {h['source']}. Window: "
                           f"{h['window']}.")
        if not hyp:
            st.caption("None raised: they need raised or rising alkaline phosphatase or calcium "
                       "(bone), or liver enzymes or bilirubin (liver), next to an imaging report "
                       "naming that site.")
    a, b = cross["markers"]
    with page.details(f"Cross-marker view, {a} and {b}", len(cross["pairs"])):
        chips(cross["status"])
        st.caption(f"{a} and {b}, each against its own limit; at every month both were "
                   f"measured, a concordant rise, a discordant one, or neither. "
                   f"{cap(cross['caveat'])}.")
        if cross["pairs"]:
            st.dataframe(pd.DataFrame(cross["pairs"]), hide_index=True, width="stretch")
        else:
            st.caption(f"{cap(cross['note'])}.")
    failing = sum(not c["ok"] for c in checks)
    with page.details("Quality checks", f"{failing} failing of {len(checks)}"):
        chips(IMPLEMENTED, PLACEHOLDER_CHIP)
        qc = pd.DataFrame(checks)
        qc.insert(0, "result", qc.pop("ok").map({True: "pass", False: "issue"}))
        st.dataframe(qc, hide_index=True, width="stretch")
    _planned(page)

    # Spot panel: one value in full, with the review mark
    with page.spot():
        picked = st.selectbox("Value", labels, key=spot_key,
                              help="Or click a point in Trends, a row of Flagged results or "
                                   "Results, or a look-here item's Spot")
        r = rows[labels.index(picked)]
        s = spot(r, rows, events)
        st.markdown(f"##### {r['marker']} at month {r['month']}"
                    + (f" · {r['pointer']}" if r["pointer"] else ""))
        st.caption(" ".join(chip(x) for x in (s["evidence"], r["flag"] if r["flags"] else "")
                            if x) + f" · Method: rules, version 2, plain arithmetic, no model · "
                   f"Reference interval: {r['reference_source']}")
        st.markdown(
            f"**{r['marker']} {r['value']:g} {r['unit']}** at month {r['month']} "
            f"({r['pointer'] or 'no flag'}; evidence: {s['evidence']}). Reference "
            f"{r['reference']} ({r['reference_source']}). Change from previous "
            f"{pct(r['change'])}, from nadir {pct(r['from_nadir'])}, rate "
            + ("first value" if r["per_month"] is None else
               f"{r['per_month']:+.3g} {r['unit']} per month") + f". Source: {r['event']}.")
        st.markdown(f"**Why it matters here:** {s['why'][0]}"
                    + (f" ({s['why'][1]})." if s["why"][1] else "."))
        st.markdown("**Rules that fired:** " + ("; ".join(
            f"{f['flag'] if f['flag'] != 'CTCAE grade' else 'CTCAE grade ' + str(r['grade'])} "
            f"({f['rule']}; threshold: {f['threshold']}; {f['status']})"
            for f in s["fired"]) or "none: within the interval, no rise or fall by the rules"))
        if r["flags"]:
            key = _key(file, r)  # the widget starts from the store: a mark made elsewhere shows
            st.session_state[f"mark_{key}"] = (reviews.get(key) or {}).get("mark", NO_MARK)
            with st.container(horizontal=True, vertical_alignment="bottom", gap="medium"):
                st.selectbox("Your review mark for this result", MARKS, key=f"mark_{key}",
                             on_change=_set_mark, args=(file, r), width=320,
                             help="Marks carry your initials from the sidebar and go into this "
                                  "file's report export")
                pin_toggle(key, f"{r['marker']} {r['value']:g} {r['unit']} at month "
                                f"{r['month']}: {r['flag']} ({r['pointer']}), blood and lab")
        else:
            st.caption("No flag on this value, so nothing to mark.")
        st.markdown("**Events around it (±2 months):**\n" + "\n".join(
            f"- month {e['month']}, {e.get('kind', 'Lab')}: {e['text']}"
            for e in s["events_around"]))
        st.markdown("**Check by eye before reading anything into it:**\n"
                    + "\n".join(f"- {c}" for c in s["check_by_eye"]))
        st.caption(f"Full {r['marker']} history (this value at month {r['month']}):")
        st.dataframe(_table(s["history"], reviews, file), hide_index=True, width="stretch")

    card = _card(page)
    with page.cannot_see(CANNOT_SEE_LABS):
        pass

    with page.export():
        main_key = next((k for k in markers if "rate_per_month" in kin[k]),
                        markers[0] if markers else None)
        md = report_markdown(file.id, rows, queue, checks, card, kin.get(main_key), tracker,
                             windows, bands.get(main_key), lag, mine, hyp)
        e = st.container(horizontal=True, gap="small")  # labels whole, wraps
        e.download_button("Download the lab report (Markdown)", md,
                          file_name=f"{file.id}_labs.md", mime="text/markdown",
                          key=f"{file.id}_labs_md")
        e.download_button("Download the results (CSV)",
                          _table(rows, reviews, file).to_csv(index=False),
                          file_name=f"{file.id}_labs.csv", mime="text/csv",
                          key=f"{file.id}_labs_csv")
    st.caption(CAVEAT)


def look_items(file: PatientFile, version: int | None) -> list[dict]:
    """The workbench's look-here items (``muffle.workbench.labs.queue``), the ones the report's
    attention queue carries."""
    return queue_items("labs", file, version, lambda: lab_queue(file, version))


def _point_to_spot(chart_key: str, series: list[dict], spot_key: str):
    """A trend's click: the clicked month's value of that analyte opens in the Spot panel."""
    def pick():
        sel = st.session_state[chart_key].selection.get("pick") or []
        row = next((r for r in series if sel and r["month"] == sel[0].get("month")), None)
        if row:
            st.session_state[spot_key] = _lab(row)
    return pick


def _pick_table(df: pd.DataFrame, labels: list[str], key: str, spot_key: str) -> None:
    """A table whose row click opens that value in the Spot panel."""
    def pick():
        sel = st.session_state[key].selection.rows
        if sel:
            st.session_state[spot_key] = labels[sel[0]]

    st.dataframe(df, hide_index=True, width="stretch", on_select=pick,
                 selection_mode="single-row", key=key)


def _planned(page: Page) -> None:
    with page.details("Planned panels", len(PLANNED_PANELS)):
        chips(PLANNED)
        st.dataframe(pd.DataFrame(PLANNED_PANELS, columns=["panel", "why not yet", "status"]),
                     hide_index=True, width="stretch")


def _card(page: Page) -> dict:
    card = rules_card()
    with page.card():
        chips(card["status"])
        st.markdown(f"**{card['name']}** · {card['kind']}  \n**Inputs:** {card['inputs']}  \n"
                    f"**Outputs:** {card['outputs']}  \n**Evidence:** {card['evidence']}  \n"
                    f"**Validation:** {card['validation']}")
        st.markdown("**Known failures:**\n" + "\n".join(f"- {f}" for f in card["known_failures"]))
        with st.expander(count_label("Every threshold and its source",
                                     len(card["thresholds"]))):
            st.dataframe(pd.DataFrame(card["thresholds"]), hide_index=True, width="stretch")
        table = reference_table()
        with st.expander(count_label("Reference table", n_of(len(table), "analyte"))):
            chips(IMPLEMENTED, REFERENCE_LAB_CHIP)
            st.caption("The analytes this workbench knows, with their adult intervals, units "
                       "and conversions, the interval's source and why each matters here. The "
                       "intervals are a reference laboratory's, for its own methods: the "
                       "interval on the patient's own lab report always wins. Any other analyte "
                       "can be imported; it is flagged only against the interval its lab report "
                       "gives.")
            st.dataframe(pd.DataFrame(table).drop(columns=["key"]), hide_index=True,
                         width="stretch")
    return card

if __name__ == "__main__":
    st.set_page_config(page_title="Blood and lab workbench", layout="wide")
    st.text_input("Reviewer initials", key="reviewer", max_chars=5)  # the shell's field
    render(synthetic_file(json.loads((APP / "timeline_synthetic.json").read_text("utf-8"))))

"""Blood and lab workbench for a patient file (docs/WORKSPACE.md, "Blood and lab panels").

streamlit run app/workbenches/labs.py        # the synthetic patient's workbench on its own

The workspace pages call ``render(file)`` with a ``muffle.workspace.PatientFile``. Overview first,
then a trend per marker (hover for brief stats), the results table with filters, one expander per
flagged result (the full history and why the flag appeared), the "look here" queue, the quality
checks and the rules card. Every number is plain arithmetic on observed values
(``muffle.workbench.labs``); an out-of-range value is not evidence of progression by itself.
"""

from __future__ import annotations

import json
import sys
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
    PLANNED_PANELS,
    RISING,
    RULES,
    WITHIN,
    look_here,
    quality_checks,
    results_table,
    rules_card,
    treatment_intervals,
)
from muffle.workspace import (  # noqa: E402
    IMPLEMENTED,
    MARKERS,
    PLANNED,
    REFERENCE_LIMITS,
    PatientFile,
    synthetic_file,
)

BLUE, ORANGE, RED, GRAY = "#2a78d6", "#eb6834", "#e34948", "#8a8f98"
COLORS = {WITHIN: BLUE, ABOVE: RED, f"{ABOVE}, {RISING}": RED, f"{ABOVE}, {FALLING}": ORANGE,
          RISING: ORANGE, FALLING: BLUE}
GRID = {"gridOpacity": 0.4, "domainOpacity": 0.4, "tickOpacity": 0.4}
PLACEHOLDER_CHIP = "placeholder threshold"
CAVEAT = ("An out-of-range or rising value is not evidence of progression by itself: it is an "
          "observed value to look at next to imaging and the clinic. Nothing here is a "
          "recommendation.")


def chips(*labels: str) -> None:
    """Small status captions: implemented (gray), placeholder threshold (orange), planned (blue)."""
    color = {PLACEHOLDER_CHIP: "orange", PLANNED: "blue"}
    st.caption(" ".join(f":{color.get(label, 'gray')}-badge[{label}]" for label in labels))


def pct(v) -> str:
    return "first value" if v is None or pd.isna(v) else f"{v:+.0%}"


def trend(rows: list[dict], intervals: list[dict], unit: str, limit: tuple | None,
          span: tuple[int, int]) -> alt.Chart:
    """One marker over months: points colored by flag (hover for brief stats), the reference
    limit as a dashed rule, and the treatment intervals shaded with their agents."""
    df = pd.DataFrame(rows)
    df["value_text"] = df["value"].map(lambda v: f"{v:g} {unit}")
    df["change_text"] = df["change"].map(pct)
    df["nadir_text"] = df["from_nadir"].map(pct)
    df["rate_text"] = df["per_month"].map(
        lambda v: "first value" if pd.isna(v) else f"{v:+.1f} {unit} per month")
    top = 1.3 * max([df["value"].max()] + ([limit[0]] if limit else []))
    x = alt.X("month:Q", title="months since the first tumor sequencing",
              scale=alt.Scale(domain=[span[0] - 1, span[1] + 1]))
    y_scale = alt.Scale(domain=[0, top])
    tip = [alt.Tooltip("month:Q", title="month"), alt.Tooltip("value_text:N", title="value"),
           alt.Tooltip("flag:N", title="flag"),
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
        rect = alt.Chart(iv).mark_rect(opacity=0.08, color=GRAY).encode(
            x="start:Q", x2="end:Q",
            tooltip=[alt.Tooltip("agent:N", title="treatment"), "start:Q", "end:Q",
                     alt.Tooltip("ended_by:N", title="interval ends by")])
        names = alt.Chart(iv).mark_text(align="left", dx=3, fontSize=10, color=GRAY).encode(
            x="start:Q", y=alt.Y("lane:Q", scale=y_scale), text="agent:N")
        layers += [rect, names]
    if limit:
        ref = pd.DataFrame({"y": [limit[0]], "label": [f"reference limit {limit[0]:g} {unit}"],
                            "source": [limit[1]], "month": [span[1] + 1]})
        layers.append(alt.Chart(ref).mark_rule(strokeDash=[5, 4], color=RED, opacity=0.7).encode(
            y=alt.Y("y:Q", scale=y_scale),
            tooltip=[alt.Tooltip("label:N", title="reference"),
                     alt.Tooltip("source:N", title="source")]))
        layers.append(alt.Chart(ref).mark_text(align="right", dy=-7, fontSize=10, color=RED)
                      .encode(x="month:Q", y="y:Q", text="label:N"))
    base = alt.Chart(df).encode(x=x, y=alt.Y("value:Q", title=f"{rows[0]['marker']} ({unit})",
                                              scale=y_scale))
    layers.append(base.mark_line(color=GRAY, strokeWidth=1.5))
    layers.append(base.mark_circle(size=110, opacity=1).encode(
        color=alt.Color("flag:N", scale=alt.Scale(domain=list(COLORS),
                                                  range=list(COLORS.values())),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=tip))
    return alt.layer(*layers).properties(height=320).configure_axis(**GRID)


def _table(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    out = pd.DataFrame({
        "marker": df["marker"], "month": df["month"],
        "value": [f"{v:g} {u}" for v, u in zip(df["value"], df["unit"], strict=True)],
        "reference": df["reference"], "reference source": df["reference_source"],
        "flag": df["flag"], "change from previous": df["change"].map(pct),
        "per month": df["per_month"].map(lambda v: "" if pd.isna(v) else f"{v:+.1f}"),
        "change from nadir": df["from_nadir"].map(pct), "evidence": df["evidence"],
        "source event": df["event"]})
    return out


def render(file: PatientFile, events: list[dict] | None = None) -> None:
    """The workbench for one patient file. Synthetic files use ``muffle.timeline.EVENTS`` (or
    ``events``); a TCGA file holds no lab results, and the page says so."""
    st.subheader("Blood and lab workbench")
    st.caption(f"{file.id} · {file.title}")
    if file.kind != "synthetic":
        chips(IMPLEMENTED)
        st.info("This file holds no lab results: TCGA-BRCA has one tumor sample per patient and "
                "no blood panels, so there is no series to trend. The workbench is implemented; "
                "see the synthetic patient's file for what it shows.")
        _planned()
        _card()
        st.caption(CAVEAT)
        return

    events = EVENTS if events is None else events
    rows, queue = results_table(events), look_here(events)
    checks, intervals = quality_checks(events), treatment_intervals(events)
    span = (min(e["month"] for e in events), max(e["month"] for e in events))
    chips(IMPLEMENTED, PLACEHOLDER_CHIP, "synthetic patient")
    st.warning(file.note)

    # overview: one paragraph
    measured = sorted({r["marker"] for r in rows})
    latest = {r["marker"]: r for r in rows}  # rows are in month order, so the last wins
    unmeasured = [name for name, _ in MARKERS.values() if name not in measured]
    flagged = [r for r in rows if r["flags"]]
    st.markdown(
        f"**{len(rows)} results** for {', '.join(measured) or 'no marker'} over months "
        f"{span[0]} to {span[1]}"
        + (f"; {', '.join(unmeasured)} never measured" if unmeasured else "") + ". Latest: "
        + "; ".join(f"{m} {r['value']:g} {r['unit']} at month {r['month']} ({r['flag']})"
                    for m, r in latest.items())
        + f". {len(flagged)} of {len(rows)} results flagged, {len(queue)} open items in the "
        f"look-here queue, {sum(not c['ok'] for c in checks)} quality checks failing. "
        "All values observed; every flag is plain arithmetic against the record's reference "
        "limit or the placeholder 25% rule.")

    # trends: one chart per marker, hover for brief stats
    st.markdown("#### Trends")
    chips(IMPLEMENTED, PLACEHOLDER_CHIP)
    st.caption("Hover a point for its value, change from the previous value and from the "
               "nadir, rate and source event. Shaded spans are treatment intervals (the record "
               "holds starts only: a span ends at the next treatment event or the record's "
               "end). The dashed line is the reference limit the record states.")
    for key, (name, unit) in MARKERS.items():
        series = [r for r in rows if r["key"] == key]
        if not series:
            st.caption(f"{name}: no values in the record.")
            continue
        st.altair_chart(trend(series, intervals, unit, REFERENCE_LIMITS.get(key), span),
                        width="stretch")

    # results table with filters
    st.markdown("#### Results")
    chips(IMPLEMENTED)
    left, right = st.columns([3, 1])
    pick = left.multiselect("Marker", measured, default=measured, key="labs_marker")
    only = right.checkbox("Flagged only", key="labs_flagged")
    shown = [r for r in rows if r["marker"] in pick and (r["flags"] or not only)]
    if shown:
        st.dataframe(_table(shown), hide_index=True, width="stretch")
    else:
        st.caption("No results match the filters.")

    # more info: one expander per flagged result
    st.markdown("#### Flagged results: why")
    chips(IMPLEMENTED, PLACEHOLDER_CHIP)
    for r in reversed(flagged):
        with st.expander(f"Month {r['month']}: {r['marker']} {r['value']:g} {r['unit']}, "
                         f"{r['flag']}"):
            for flag in r["flags"]:
                rule, threshold, status = RULES[flag]
                if flag == ABOVE:
                    threshold = f"{r['reference']}, from {r['reference_source']}"
                st.markdown(f"**{flag}** · rule: {rule} · threshold: {threshold} · "
                            f"evidence: observed · status: {status}")
            st.markdown(f"Change from previous {pct(r['change'])}, from nadir "
                        f"{pct(r['from_nadir'])}; source: {r['event']}.")
            st.caption(f"Full {r['marker']} history (this result at month {r['month']}):")
            st.dataframe(_table([h for h in rows if h["key"] == r["key"]]), hide_index=True,
                         width="stretch")

    # look here
    st.markdown("#### Look here")
    chips(IMPLEMENTED, PLACEHOLDER_CHIP)
    st.caption("Every flagged result, latest first, one row per rule that fired. Observed "
               "values; the status names the source of each threshold.")
    if queue:
        st.dataframe(pd.DataFrame(queue)[["month", "marker", "value", "unit", "flag", "rule",
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
    _card()
    st.caption(CAVEAT)


def _planned() -> None:
    st.markdown("#### Planned")
    chips(PLANNED)
    st.dataframe(pd.DataFrame(PLANNED_PANELS, columns=["panel", "why not yet", "status"]),
                 hide_index=True, width="stretch")


def _card() -> None:
    card = rules_card()
    st.markdown("#### Rules card")
    chips(card["status"])
    st.markdown(f"**{card['name']}** · {card['kind']}  \n**Inputs:** {card['inputs']}  \n"
                f"**Outputs:** {card['outputs']}  \n**Evidence:** {card['evidence']}  \n"
                f"**Validation:** {card['validation']}")
    st.dataframe(pd.DataFrame(card["thresholds"]), hide_index=True, width="stretch")
    st.markdown("**Known failures:**\n" + "\n".join(f"- {f}" for f in card["known_failures"]))


if __name__ == "__main__":
    st.set_page_config(page_title="Blood and lab workbench", layout="wide")
    render(synthetic_file(json.loads((APP / "timeline_synthetic.json").read_text("utf-8"))))

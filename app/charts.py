"""Altair charts for the demo. Colors come from one validated palette, assigned by role:

- categorical (identity): federated = blue, pooled data = orange, baselines = aqua, in that fixed
  order (the first three slots pass colorblind checks pairwise in light and dark mode)
- diverging (polarity): raises risk = red, lowers risk = blue
- ordinal (low / medium / high risk): one blue ramp, light to dark, plus direct labels

Every chart has hover tooltips, and text stays in the theme's ink, never the series color.
"""

from __future__ import annotations

import altair as alt
import numpy as np
import pandas as pd

BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"
RAMP = {"low": "#6da7ec", "medium": "#2a78d6", "high": "#184f95"}  # blue 300 / 450 / 600
GRID = {"gridOpacity": 0.4, "domainOpacity": 0.4, "tickOpacity": 0.4}


def risk_position(cohort_risks: np.ndarray, patient_risk: float, label: str) -> alt.Chart:
    """Histogram of every patient's predicted log-risk, with this patient marked."""
    counts, edges = np.histogram(cohort_risks, bins=30)
    gap = (edges[1] - edges[0]) * 0.08  # a thin surface gap between bars
    bins = pd.DataFrame({"start": edges[:-1] + gap / 2, "end": edges[1:] - gap / 2,
                         "patients": counts.astype(int)})
    bars = alt.Chart(bins).mark_rect(color="#86b6ef", cornerRadiusTopLeft=2,
                                     cornerRadiusTopRight=2).encode(
        x=alt.X("start:Q", title="predicted log-risk (higher = shorter expected survival)"),
        x2="end:Q",
        y=alt.Y("patients:Q", title="patients"), y2=alt.datum(0),
        tooltip=[alt.Tooltip("start:Q", format=".2f", title="from"),
                 alt.Tooltip("end:Q", format=".2f", title="to"), "patients:Q"])
    marker = pd.DataFrame({"x": [float(patient_risk)], "label": [label]})
    rule = alt.Chart(marker).mark_rule(strokeWidth=2, color=BLUE).encode(
        x="x:Q", tooltip=[alt.Tooltip("label:N", title="this patient")])
    right_half = patient_risk > np.median(cohort_risks)  # put the label where there is room
    text = alt.Chart(marker).mark_text(align="right" if right_half else "left",
                                       dx=-6 if right_half else 6, dy=4, baseline="top",
                                       fontWeight="bold").encode(
        x="x:Q", y=alt.value(0), text="label:N")
    return (bars + rule + text).properties(height=240).configure_axis(**GRID)


def contributions(contrib: dict[str, float]) -> alt.Chart:
    """Horizontal bars: how much each layer moves this patient's log-risk vs a typical patient."""
    df = pd.DataFrame({"layer": list(contrib), "value": list(contrib.values())})
    df["effect"] = np.where(df["value"] >= 0, "raises risk", "lowers risk")
    df["label"] = df["value"].map(lambda v: f"{v:+.2f}")
    order = df.sort_values("value", key=abs, ascending=False)["layer"].tolist()
    lo, hi = min(0.0, df["value"].min()), max(0.0, df["value"].max())
    pad = 0.3 * max(hi - lo, 0.05)  # room for the value labels
    base = alt.Chart(df).encode(y=alt.Y("layer:N", sort=order, title=None,
                                        axis=alt.Axis(labelOverlap=False, labelLimit=200)))
    bars = base.mark_bar(cornerRadiusEnd=4, height=18).encode(
        x=alt.X("value:Q", title="change in log-risk vs a typical patient",
                scale=alt.Scale(domain=[lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else 0)],
                                nice=False)),
        color=alt.Color("effect:N", scale=alt.Scale(domain=["raises risk", "lowers risk"],
                                                    range=[RED, BLUE]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["layer:N", "effect:N", alt.Tooltip("value:Q", format="+.3f", title="log-risk")])
    labels = base.mark_text(dx=alt.expr("datum.value >= 0 ? 6 : -6"),
                            align=alt.expr("datum.value >= 0 ? 'left' : 'right'")).encode(
        x="value:Q", text="label:N")
    zero = alt.Chart(pd.DataFrame({"x": [0]})).mark_rule(opacity=0.5).encode(x="x:Q")
    return (bars + labels + zero).properties(height=40 * len(df) + 40).configure_axis(**GRID)


GROUPS = {"Federated: no patient data shared": BLUE, "Pooled: all patients in one place": ORANGE,
          "Baselines": AQUA}


def results(methods: list[dict]) -> alt.Chart:
    """Leave-one-hospital-out C-index, mean ± sd over seeds, one row per method."""
    df = pd.DataFrame(methods)
    df["kind"] = np.where(df["federated"], "Federated: no patient data shared",
                          np.where(df["method"].isin(["residual", "centralized"]),
                                   "Pooled: all patients in one place", "Baselines"))
    df["lo"], df["hi"] = df["mean"] - df["sd"], df["mean"] + df["sd"]
    df["text"] = df.apply(lambda r: f"{r['mean']:.3f} ± {r['sd']:.3f}", axis=1)
    y = alt.Y("label:N", sort=df["label"].tolist(), title=None,
              axis=alt.Axis(labelLimit=320, labelOverlap=False))
    x_scale = alt.Scale(domain=[0.6, 0.75])
    color = alt.Color("kind:N", scale=alt.Scale(domain=list(GROUPS), range=list(GROUPS.values())),
                      legend=alt.Legend(orient="bottom", title=None, labelLimit=400))
    tip = ["label:N", "kind:N", alt.Tooltip("mean:Q", format=".3f", title="C-index"),
           alt.Tooltip("sd:Q", format=".3f", title="sd over seeds"), "seeds:Q"]
    base = alt.Chart(df).encode(y=y)
    err = base.mark_rule(strokeWidth=2).encode(
        x=alt.X("lo:Q", scale=x_scale, title="C-index on the held-out hospital"), x2="hi:Q",
        color=color, tooltip=tip)
    dots = base.mark_circle(size=110, opacity=1).encode(x="mean:Q", color=color, tooltip=tip)
    text = base.mark_text(align="left", dx=10, dy=-10).encode(x="hi:Q", text="text:N")
    return (err + dots + text).properties(height=44 * len(df) + 60).configure_axis(**GRID)


def survival_by_group(km: dict[str, tuple[np.ndarray, np.ndarray, int]]) -> alt.Chart:
    """Kaplan-Meier curves of the held-out patients per predicted risk group."""
    rows = [{"months": float(t), "survival": float(s), "group": g, "patients": n}
            for g, (ts, ss, n) in km.items() for t, s in zip(ts, ss, strict=True)]
    df = pd.DataFrame(rows)
    df["name"] = df["group"] + " risk (" + df["patients"].astype(str) + ")"
    names = [f"{g} risk ({km[g][2]})" for g in km]
    color = alt.Color("name:N", scale=alt.Scale(domain=names, range=[RAMP[g] for g in km]),
                      legend=alt.Legend(orient="bottom", title=None))
    lines = alt.Chart(df).mark_line(strokeWidth=2, interpolate="step-after").encode(
        x=alt.X("months:Q", title="months since diagnosis", scale=alt.Scale(domain=[0, 60])),
        y=alt.Y("survival:Q", title="alive (Kaplan-Meier)", scale=alt.Scale(domain=[0.5, 1]),
                axis=alt.Axis(format="%")),
        color=color)
    hover = alt.selection_point(fields=["months"], nearest=True, on="pointerover", empty=False)
    points = alt.Chart(df).mark_point(size=60, filled=True).encode(
        x="months:Q", y="survival:Q", color=color,
        opacity=alt.condition(hover, alt.value(1), alt.value(0)),
        tooltip=["name:N", alt.Tooltip("months:Q", format=".0f"),
                 alt.Tooltip("survival:Q", format=".1%", title="alive")]).add_params(hover)
    ends = df[df["months"] == df["months"].max()]
    labels = alt.Chart(ends).mark_text(align="left", dx=6).encode(
        x="months:Q", y="survival:Q", text="group:N")
    return (lines + points + labels).properties(height=280).configure_axis(**GRID)

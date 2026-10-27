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


def contributions(contrib: dict[str, float],
                  title: str = "change in log-risk vs a typical patient",
                  fmt: str = "+.2f") -> alt.Chart:
    """Horizontal bars: how much each layer moves this patient's log-risk vs a typical patient
    (or, with ``title`` and ``fmt``, any signed change in risk)."""
    df = pd.DataFrame({"layer": list(contrib), "value": list(contrib.values())})
    df["effect"] = np.where(df["value"] >= 0, "raises risk", "lowers risk")
    df["label"] = df["value"].map(lambda v: format(v, fmt))
    order = df.sort_values("value", key=abs, ascending=False)["layer"].tolist()
    lo, hi = min(0.0, df["value"].min()), max(0.0, df["value"].max())
    pad = 0.3 * max(hi - lo, 0.05)  # room for the value labels
    base = alt.Chart(df).encode(y=alt.Y("layer:N", sort=order, title=None,
                                        axis=alt.Axis(labelOverlap=False, labelLimit=200)))
    bars = base.mark_bar(cornerRadiusEnd=4, height=18).encode(
        x=alt.X("value:Q", title=title,
                scale=alt.Scale(domain=[lo - (pad if lo < 0 else 0), hi + (pad if hi > 0 else 0)],
                                nice=False)),
        color=alt.Color("effect:N", scale=alt.Scale(domain=["raises risk", "lowers risk"],
                                                    range=[RED, BLUE]),
                        legend=alt.Legend(orient="bottom", title=None)),
        tooltip=["layer:N", "effect:N", alt.Tooltip("value:Q", format=fmt, title="change")])
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


TONES = {"from the record": BLUE, "imported in this session": ORANGE, "SOS alert": RED}
MARKS = {"version": ("circle", 150), "test": ("circle", 60), "treatment": ("triangle-right", 70),
         "alert": ("triangle-down", 120)}


def event_lanes(data: dict, viewing: int) -> alt.LayerChart:
    """The record in lanes on one month axis (``muffle.timeline_view.lanes``): report versions on
    top, tests, treatment starts and their bars, SOS alerts in red on the lane of the test that
    raised them. Points after version ``viewing`` are faded behind a rule at its month. A click
    selects a point's report version (the selection "node")."""
    pts = pd.DataFrame(data["points"])
    pts["alpha"] = np.where(pts["version"] > viewing, 0.3, 1.0)
    lo, hi = pts["x"].min() - 1, pts["x"].max() + 1
    x = alt.X("x:Q", title=data["axis"], scale=alt.Scale(domain=[lo, hi], nice=False))
    y = alt.Y("lane:N", title=None, scale=alt.Scale(domain=data["lanes"]),
              axis=alt.Axis(labelLimit=200, labelOverlap=False))
    node = alt.selection_point(name="node", fields=["version"], on="click")
    tones = [t for t in TONES if t in set(pts["tone"])]
    points = alt.Chart(pts).mark_point(filled=True, opacity=1).encode(
        x=x, y=y,
        shape=alt.Shape("mark:N", scale=alt.Scale(domain=list(MARKS),
                                                  range=[s for s, _ in MARKS.values()]),
                        legend=None),
        size=alt.Size("mark:N", scale=alt.Scale(domain=list(MARKS),
                                                range=[z for _, z in MARKS.values()]),
                      legend=None),
        color=alt.Color("tone:N", scale=alt.Scale(domain=tones, range=[TONES[t] for t in tones]),
                        legend=alt.Legend(orient="bottom", title=None)),
        opacity=alt.Opacity("alpha:Q", scale=None),
        tooltip=[alt.Tooltip("lane:N"), alt.Tooltip("when:N"), alt.Tooltip("what:N"),
                 alt.Tooltip("result:N"), alt.Tooltip("evidence:N"),
                 alt.Tooltip("version_label:N", title="report version"),
                 alt.Tooltip("entry:N", title="the version's entry"),
                 alt.Tooltip("source:N")]).add_params(node)
    layers = []
    if data["spans"]:
        bars = pd.DataFrame(data["spans"])
        bars["lane"], bars["alpha"] = "Treatments", np.where(bars["version"] > viewing, 0.3, 1.0)
        bars["state"] = np.where(bars["open"], "no stop recorded (open)", "until the next entry")
        tip = [alt.Tooltip("drug:N"), alt.Tooltip("start:Q"), alt.Tooltip("end:Q"),
               alt.Tooltip("state:N", title="end"), alt.Tooltip("words:N", title="the record")]
        base = alt.Chart(bars).encode(y=y, yOffset="track:N")
        layers.append(base.mark_bar(height=7, cornerRadius=3, color="#86b6ef", clip=True).encode(
            x="start:Q", x2="end:Q", opacity=alt.Opacity("alpha:Q", scale=None), tooltip=tip))
        layers.append(base.transform_filter("datum.end - datum.start >= 6").mark_text(
            align="left", dx=8, fontSize=10, clip=True).encode(x="start:Q", text="drug:N",
                                                               tooltip=tip))  # room for a name
    now = pts.loc[(pts["mark"] == "version") & (pts["version"] == viewing), "x"].min()
    layers.append(alt.Chart(pd.DataFrame({"x": [now]})).mark_rule(
        strokeDash=[4, 3], opacity=0.6).encode(x="x:Q"))
    # Streamlit fits the whole chart, month axis and legend included (about 100 px), into this
    # height: with +50 a two- or three-lane TCGA file got lanes 8 px apart, labels overprinted
    return alt.layer(*layers, points).properties(
        height=34 * len(data["lanes"]) + 110).configure_axis(**GRID)


OVERLAYS = ("CA 15-3", "ctDNA", "Treatments", "Imaging reads")
VARIANT_COLORS = [BLUE, ORANGE, "#8a8f98"]  # the ctDNA workbench's colors, in its variants' order


def risk_timeline(updates: list[dict], events: list[dict], month: float, ctx: dict | None = None,
                  show=()) -> alt.Chart:
    """The synthetic patient's 12-month risk at each event: the record-so-far models (mean, and
    their range over seeds as a band) and the diagnosis-only baseline; a rule marks ``month``.
    ``show`` (from OVERLAYS) adds the record beside it from ``ctx``
    (``muffle.timeline_view.context``): CA 15-3 on its own axis, treatment bars, imaging reads as
    rules (progression red), ctDNA allele fractions in a panel below."""
    rows = [{"month": u["month"], "risk": u["risk"], "lo": u["risk_range"][0],
             "hi": u["risk_range"][1], "baseline": u["baseline"],
             "event": events[u["event"]]["text"]} for u in updates if "risk" in u]
    df, ctx = pd.DataFrame(rows), ctx or {}
    ca = pd.DataFrame(ctx.get("ca153", []) if "CA 15-3" in show else [],
                      columns=["month", "value", "words", "source"])
    dna = pd.DataFrame(ctx.get("ctdna", []) if "ctDNA" in show else [],
                       columns=["month", "variant", "vaf"])
    reads = pd.DataFrame(ctx.get("imaging", []) if "Imaging reads" in show else [],
                         columns=["month", "words", "read"])
    bars = pd.DataFrame(ctx.get("treatments", []) if "Treatments" in show else [],
                        columns=["drug", "start", "end", "open", "track", "words"])
    months = [*df["month"], *ca["month"], *dna["month"], *reads["month"], month]
    lo = min(months) - 0.5
    bars = bars[bars["end"] > lo].copy()  # only what runs within the axis
    x = alt.X("month:Q", title="months from the first tumor sequencing (month 0)",
              scale=alt.Scale(domain=[lo, max(months) + 3], nice=False))
    pct = alt.Axis(format="%")
    y = alt.Y("risk:Q", title="12-month risk", scale=alt.Scale(domain=[0, 1]), axis=pct)
    tip = [alt.Tooltip("month:Q", title="month"), alt.Tooltip("event:N"),
           alt.Tooltip("risk:Q", format=".0%", title="record so far"),
           alt.Tooltip("lo:Q", format=".0%", title="lowest of 5 models"),
           alt.Tooltip("hi:Q", format=".0%", title="highest of 5 models"),
           alt.Tooltip("baseline:Q", format=".0%", title="diagnosis only")]
    base = alt.Chart(df).encode(x=x)
    band = base.mark_area(opacity=0.15, color=BLUE, interpolate="step-after").encode(
        y=alt.Y("lo:Q", scale=alt.Scale(domain=[0, 1]), axis=pct, title="12-month risk"),
        y2="hi:Q")
    line = base.mark_line(color=BLUE, strokeWidth=2, interpolate="step-after").encode(y=y)
    dots = base.mark_circle(color=BLUE, size=70, opacity=1).encode(y=y, tooltip=tip)
    baseline = base.mark_line(color=AQUA, strokeWidth=2, strokeDash=[5, 4],
                              interpolate="step-after").encode(y="baseline:Q", tooltip=tip)
    last = df.tail(1)
    names = alt.Chart(pd.concat([last.assign(v=last["risk"], name="record so far"),
                                 last.assign(v=last["baseline"], name="diagnosis only")])
                      ).mark_text(align="left", dx=8).encode(x="month:Q", y="v:Q", text="name:N")
    now = alt.Chart(pd.DataFrame({"month": [month]})).mark_rule(opacity=0.5).encode(x="month:Q")
    layers = []
    if len(bars):
        bars["state"] = np.where(bars["open"], "no stop recorded (open)", "until the next entry")
        bars["ty"] = 0.97 - 0.05 * bars["track"]  # the labels' height, in risk units
        bars["lx"] = bars["start"].clip(lower=lo)  # a bar from before the axis: named at its edge
        tip = [alt.Tooltip("drug:N"), alt.Tooltip("start:Q"), alt.Tooltip("end:Q"),
               alt.Tooltip("state:N", title="end"), alt.Tooltip("words:N", title="the record")]
        b = alt.Chart(bars).encode(tooltip=tip)
        layers += [b.mark_rect(color=BLUE, opacity=0.08, clip=True).encode(x="start:Q", x2="end:Q"),
                   b.mark_text(align="left", dx=3, fontSize=10, clip=True).encode(
                       x="lx:Q", y="ty:Q", text="drug:N")]
    if len(reads):
        layers.append(alt.Chart(reads).mark_rule(strokeDash=[2, 3], strokeWidth=2).encode(
            x="month:Q", color=alt.Color("read:N", scale=alt.Scale(
                domain=["progression", "no progression stated"], range=[RED, "#8a8f98"]),
                legend=alt.Legend(orient="bottom", title="imaging read")),
            tooltip=[alt.Tooltip("month:Q"), alt.Tooltip("read:N"),
                     alt.Tooltip("words:N", title="the report")]))
    top = alt.layer(*layers, band, line, baseline, dots, names, now).properties(height=280)
    if len(ca):
        y_ca = alt.Y("value:Q", title="CA 15-3 (U/mL)", axis=alt.Axis(orient="right"))
        tip = [alt.Tooltip("month:Q"), alt.Tooltip("words:N", title="CA 15-3"),
               alt.Tooltip("source:N")]
        c = alt.Chart(ca).encode(x=x, y=y_ca)
        top = alt.layer(top, c.mark_line(color=ORANGE, strokeWidth=1.5, strokeDash=[6, 2]) +
                        c.mark_square(color=ORANGE, size=40, opacity=1).encode(tooltip=tip)
                        ).resolve_scale(y="independent")
    if not len(dna):
        return top.configure_axis(**GRID)
    dna["detected"] = np.where(dna["vaf"].notna(), "detected", "not detected (shown at 0)")
    dna["shown"] = dna["vaf"].fillna(0.0)
    color = alt.Color("variant:N", scale=alt.Scale(domain=list(dict.fromkeys(dna["variant"])),
                                                   range=VARIANT_COLORS),
                      legend=alt.Legend(orient="bottom", title="ctDNA (synthetic series)"))
    tip = [alt.Tooltip("month:Q"), alt.Tooltip("variant:N"),
           alt.Tooltip("vaf:Q", format=".2f", title="allele fraction (%)"),
           alt.Tooltip("detected:N")]
    d = alt.Chart(dna).encode(x=x, y=alt.Y("shown:Q", title="allele fraction (%)"), color=color)
    lod = alt.Chart(pd.DataFrame({"lod": [ctx["lod"]]})).mark_rule(
        strokeDash=[3, 3], opacity=0.6).encode(
        y="lod:Q", tooltip=[alt.Tooltip("lod:Q", title="detection limit (placeholder), %")])
    seen = d.transform_filter("datum.vaf != null")
    panel = alt.layer(seen.mark_line(strokeWidth=1.5),
                      seen.mark_point(size=40, filled=True, opacity=1).encode(tooltip=tip),
                      d.transform_filter("datum.vaf == null").mark_point(size=40, opacity=1)
                      .encode(tooltip=tip), lod).properties(height=130)
    return alt.vconcat(top, panel).resolve_scale(x="shared", color="independent").configure_axis(
        **GRID)


def cohort_strip(values: dict[str, float], patient: str, axis: str, fmt: str = ".2f") -> alt.Chart:
    """One score across the files as a strip of ticks (``muffle.cohort.cohort_position``), this
    patient a larger blue dot; hover names each file and its value. The axis is named beside the
    chart (``axis``, in the tooltip too): a title under a chart this low is cut."""
    df = pd.DataFrame({"file": list(values), "value": [float(v) for v in values.values()]})
    df["who"] = np.where(df["file"] == patient, "this patient", "another file")
    x = alt.X("value:Q", title=None, scale=alt.Scale(zero=False, nice=True),
              axis=alt.Axis(tickCount=4, labelFontSize=11, titleFontSize=11))
    tip = ["file:N", alt.Tooltip("value:Q", format=fmt, title=axis)]
    others = alt.Chart(df[df["who"] == "another file"]).mark_tick(
        color="#8a8f98", thickness=1.5, size=18).encode(x=x, tooltip=tip)
    me = alt.Chart(df[df["who"] == "this patient"]).mark_point(
        filled=True, size=140, color=BLUE, opacity=1).encode(x="value:Q", tooltip=tip)
    return (others + me).properties(height=44).configure_axis(**GRID).configure_view(
        strokeWidth=0)

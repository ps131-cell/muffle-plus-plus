"""The app's chart palette and theme as plain data, without Altair (docs/ux.md §8). ``charts``
registers the theme with Altair for every chart of the workbenches; the patient list draws its
one chart, the cohort strip's risk groups, from ``risk_bands`` here as a Vega-Lite dict, so the
first screen never imports Altair (and jsonschema with it: about 1.5 s of a fresh start and the
schema check on top, docs/qa.md "First screen after the worklist")."""

from __future__ import annotations

import hashlib
import json

BLUE, ORANGE, AQUA, RED = "#2a78d6", "#eb6834", "#1baf7a", "#e34948"
GRAY, VIOLET, GREEN = "#8a8f98", "#6250d6", "#137a33"
RAMP = {"low": "#6da7ec", "medium": "#2a78d6", "high": "#184f95"}  # blue 300 / 450 / 600
# the categorical slots in their validated order (docs/ux.md §8); a ninth series folds into "other"
CATEGORY = [BLUE, ORANGE, AQUA, "#eda100", "#e87ba4", "#008300", VIOLET, RED]
INK, MUTED, RULE, HAIRLINE = "#0e1117", "#4d5260", "#c3c9d2", "#e6e9ee"  # muted: 7.6:1 on white
SANS = "IBM Plex Sans, sans-serif"
# the Vega-Lite schema of the Altair the app runs (6.3): what Altair writes into every spec
SCHEMA = "https://vega.github.io/schema/vega-lite/v6.4.1.json"


def config() -> dict:
    """The theme's Vega-Lite config: IBM Plex Sans, axis titles and legends at 13 px and tick
    labels at 12 px in the muted ink, hairline axes, no frame, horizontal gridlines only where
    the value is read off a vertical axis."""
    axis = {"labelFont": SANS, "titleFont": SANS, "labelFontSize": 12, "titleFontSize": 13,
            "labelColor": MUTED, "titleColor": MUTED, "titleFontWeight": 500,
            "domainColor": RULE, "tickColor": RULE, "domainWidth": 1, "tickWidth": 1,
            "tickSize": 4, "gridColor": HAIRLINE, "gridWidth": 1, "labelPadding": 4,
            "titlePadding": 8}
    legend = {"labelFont": SANS, "titleFont": SANS, "labelFontSize": 12, "titleFontSize": 12,
              "labelColor": MUTED, "titleColor": MUTED, "titleFontWeight": 500,
              "symbolSize": 64, "symbolStrokeWidth": 0, "rowPadding": 3, "columnPadding": 12,
              "padding": 0, "offset": 10, "labelLimit": 320}
    return {
        "font": SANS,
        "view": {"stroke": "transparent"},  # no box around the plot
        "axis": axis,
        "axisX": {"grid": False},  # values are read across, so only horizontal hairlines
        "axisY": {"domain": False, "ticks": False},
        "axisBand": {"domain": False, "ticks": False, "labelPadding": 6},
        "legend": legend,
        "title": {"font": SANS, "fontSize": 13, "fontWeight": 600, "color": INK,
                  "anchor": "start", "offset": 8},
        "header": {"labelFont": SANS, "titleFont": SANS, "labelColor": MUTED},
        "text": {"font": SANS, "fontSize": 12, "color": INK},
        "line": {"strokeWidth": 2, "strokeCap": "round", "strokeJoin": "round"},
        "range": {"category": CATEGORY},
    }


def risk_bands(counts: dict[str, int], shown: dict[str, int] | None = None) -> dict:
    """The patient list's cohort strip: how many TCGA files sit in each risk group (cohort
    tertiles, model inference), low to high in the ordinal ramp, each bar labeled with its
    count; ``shown``, the files of each group the list's filters keep, as a darker overlay.
    Key for key the spec Altair writes for this chart (tests/test_overview.py builds it with
    Altair and compares)."""
    order = [g for g in ("low", "medium", "high") if g in counts]
    shown = counts if shown is None else shown  # an empty list keeps none, not all
    rows = [{"group": g, "files": int(counts[g]), "shown": int(shown.get(g, 0))} for g in order]
    name = "data-" + hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()[:32]
    tip = [{"field": "group", "title": "risk group", "type": "nominal"},
           {"field": "files", "title": "files", "type": "quantitative"},
           {"field": "shown", "title": "in the list now", "type": "quantitative"}]
    x = {"axis": {"domainOpacity": 0.4, "labelAngle": 0, "labelFontSize": 11, "ticks": False},
         "field": "group", "sort": order, "title": None, "type": "nominal"}
    corners = {"cornerRadiusTopLeft": 2, "cornerRadiusTopRight": 2}
    bars = {"mark": {"type": "bar", **corners, "opacity": 0.35}, "encoding": {
        "color": {"field": "group", "legend": None,
                  "scale": {"domain": order, "range": [RAMP[g] for g in order]},
                  "type": "nominal"},
        "tooltip": tip, "x": x,
        "y": {"axis": None, "field": "files",
              "scale": {"domainMax": max(r["files"] for r in rows) * 1.3}, "title": None,
              "type": "quantitative"}}}
    kept = {"mark": {"type": "bar", **corners}, "encoding": {
        "color": {"field": "group", "legend": None, "type": "nominal"}, "tooltip": tip, "x": x,
        "y": {"axis": None, "field": "shown", "title": None, "type": "quantitative"}}}
    labels = {"mark": {"type": "text", "baseline": "bottom", "dy": -6, "fontSize": 11},
              "encoding": {"text": {"field": "files", "type": "quantitative"}, "tooltip": tip,
                           "x": x, "y": {"field": "files", "type": "quantitative"}}}
    cfg = config()
    cfg["view"] = {**cfg["view"], "strokeWidth": 0}
    # the count labels sit above the bars: padding inside the chart's own box keeps them there
    spec = {"config": cfg, "layer": [bars, kept, labels],
            "autosize": {"contains": "padding", "type": "fit-x"}, "data": {"name": name},
            "height": 52, "padding": {"top": 14, "bottom": 0, "left": 2, "right": 2},
            "$schema": SCHEMA, "datasets": {name: rows}}
    return json.loads(json.dumps(spec))  # the layers share no dict with each other

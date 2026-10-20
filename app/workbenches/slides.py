"""Pathology slide workbench for a patient file (docs/WORKSPACE.md, "Pathology slides";
docs/WORKBENCHES.md §5), first version: one precomputed slide region.

streamlit run app/workbenches/slides.py        # standalone page on the example region

The workspace pages call ``render(file, version=None)`` with a ``muffle.workspace.PatientFile``;
it draws inside the current container only. No file in the app holds a slide image yet, so the
page says so and shows the pipeline on a public example: a BCSS-annotated region of a TCGA-BRCA
diagnostic slide scored by the tissue head (``scripts/slide_spike.py result``). The folder holds
only derived numbers (tile positions, class probabilities, quality measures) and a thumbnail.

Tissue map with probabilities on hover, the certainty map (top probability below a placeholder
cutoff = unsure here), the quality exclusions, the tumor region with its front and zones, what
the front faces, the head's measured accuracy and training data, and what a tile map cannot see.
Every class is a model inference; every cutoff names its source; nothing here is a diagnosis.
"""

from __future__ import annotations

import sys
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle.report.case_tools import INFERENCE, OBSERVED  # noqa: E402
from muffle.workbench.slides import (  # noqa: E402
    CANNOT_SEE,
    COLORS,
    CUTOFFS,
    LABELS,
    PLACEHOLDER,
    QC_OK,
    TILE_UM,
    analyze,
    load_result,
)
from muffle.workspace import PLANNED, PatientFile  # noqa: E402

EXAMPLE = APP / "workbenches" / "slides_example"
ZONE_COLORS = {"core": "#8e1b1b", "front band": "#f39c12", "peritumoral": "#f9e79f",
               "outside": "#dfe6e9", "": "#ffffff"}
GRID = {"gridOpacity": 0, "domainOpacity": 0, "tickOpacity": 0, "labels": False, "title": None}


def chips(*labels: str) -> None:
    color = {"placeholder cutoffs": "orange", PLANNED: "blue", "example slide": "violet"}
    st.caption(" ".join(f":{color.get(label, 'gray')}-badge[{label}]" for label in labels))


def tile_chart(tiles: pd.DataFrame, color_field: str, scale: alt.Scale, title: str,
               tooltip: list, grid_shape: list[int], height: int = 360) -> alt.Chart:
    """One square per tile; hover shows the tooltip fields."""
    h, w = grid_shape
    step = max(4, int(height / h))  # square tiles: discrete axes size by step, not by width
    return (alt.Chart(tiles).mark_rect(stroke="white", strokeWidth=0.3)
            .encode(x=alt.X("col:O", axis=alt.Axis(**GRID)),
                    y=alt.Y("row:O", axis=alt.Axis(**GRID)),
                    color=alt.Color(f"{color_field}:N", scale=scale, title=title),
                    tooltip=tooltip)
            .properties(width=alt.Step(step), height=alt.Step(step)))


def render(file: PatientFile, version: int | None = None) -> None:
    result = load_result(EXAMPLE)
    slide_tests = [t for t in file.tests if t.workbench == "slides"]
    st.subheader("Pathology slides")
    if slide_tests:
        st.markdown("**In this file:** " + "; ".join(
            f"{t.name} (month {t.month}): {t.result}" for t in slide_tests))
        st.info("The record holds the pathology report's text, not the slide image. Below, the "
                "slide workbench is shown on a public example region so that what it would do "
                "with this patient's slide is visible; nothing below is this patient's tissue.")
    else:
        st.info("This file holds no slide image. Below, the slide workbench on a public example "
                "region; nothing below is this patient's tissue.")
    if result is None:
        chips(PLANNED)
        st.warning("The example slide result is not in this checkout (app/workbenches/"
                   "slides_example). Run `python scripts/slide_spike.py result` to make it.")
        return
    chips("example slide", "placeholder cutoffs", "implemented, validated on held-out BCSS slides")

    meta, tiles = result["meta"], result["tiles"]
    head = meta.get("head", {})
    classes = head.get("classes", [])
    res = analyze(tiles, classes)
    df, s = res["tiles"], res["summary"]
    df["class"] = df["label"].map(LABELS).fillna("")
    df["certainty"] = df["unsure"].map({True: "unsure here", False: "confident"})
    bad = df["qc"] != QC_OK
    df.loc[bad, "class"] = "excluded: " + df.loc[bad, "qc"]
    df.loc[bad, "certainty"] = "excluded"
    for k in classes:
        df[LABELS[k]] = df[f"p_{k}"].map(lambda v: f"{v:.0%}")
    df["where"] = df.apply(lambda r: f"tile r{int(r.row)} c{int(r.col)} · {r.zone or 'no zone'}"
                           + (f" · {r.dist_to_front_um:+.0f} µm from the front"
                              if "dist_to_front_um" in df and pd.notna(r.get("dist_to_front_um"))
                              else ""), axis=1)
    hover = ["where:N", "class:N", "certainty:N"] + [f"{LABELS[k]}:N" for k in classes]
    enc = meta.get("encoder", {})
    st.caption(f"Source: {meta.get('source', 'public TCGA-BRCA slide region')} · slide "
               f"{meta.get('slide', '')}, region {s['tiles']} tiles of {TILE_UM:.0f} µm · encoder "
               f"{enc.get('name', '?')} ({enc.get('license', '?')}, {enc.get('access', '?')}) · "
               f"head: {head.get('kind', '?')} · method version 0.1 (spike) · "
               f"status: {meta.get('status', 'implemented')}.")

    # --- overview ----------------------------------------------------------------------------
    st.markdown("#### Overview")
    frac = s["tissue_fractions"]
    top3 = sorted(frac.items(), key=lambda kv: -kv[1])[:3]
    st.markdown(
        f"**Model inference.** Of {s['usable_tiles']} usable tiles, the map reads "
        + ", ".join(f"{LABELS[k].lower()} {v:.0%}" for k, v in top3)
        + f". The main tumor region covers {s['main_tumor_mm2']} mm² with a front of "
        f"{s['front_length_mm']} mm; {s['satellite_pieces']} separate tumor piece(s). "
        f"{s['unsure_share']:.0%} of the tissue is marked unsure (top probability below "
        f"{CUTOFFS['unsure_below'][0]}, a placeholder cutoff). "
        + ("Excluded by quality control: "
           + ", ".join(f"{v} {k}" for k, v in s["excluded"].items()) + "."
           if s["excluded"] else "No tile was excluded by quality control.")
    )
    if s["facing"]:
        faces = ", ".join(f"{LABELS.get(k, k).lower()} {v:.0%}" for k, v in s["facing"].items())
        st.markdown(f"**What the front faces** (tiles touching the front, outside the tumor): "
                    f"{faces}. A 2D snapshot of this section: where the tumor is, not where it "
                    "is going.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Tumor area (map)", f"{s['tumor_mm2']} mm²")
    c2.metric("Front length", f"{s['front_length_mm']} mm")
    c3.metric("Unsure share", f"{s['unsure_share']:.0%}")
    c4.metric("Head accuracy (held out)", f"{head.get('accuracy', float('nan')):.0%}")

    # --- maps --------------------------------------------------------------------------------
    st.markdown("#### Tissue map")
    st.caption("Hover a tile for its class probabilities. Each tile is one score for 112 µm of "
               "tissue; the class is a model inference, smoothed over a 3×3 neighbourhood.")
    cls_domain = [LABELS[k] for k in classes] + sorted(
        v for v in df["class"].unique() if v.startswith("excluded"))
    cls_range = [COLORS[k] for k in classes] + ["#bbbbbb"] * (len(cls_domain) - len(classes))
    left, right = st.columns([3, 2])
    with left:
        st.altair_chart(tile_chart(df, "class", alt.Scale(domain=cls_domain, range=cls_range),
                                   "Tissue class", hover, res["grid_shape"]), width="content")
    with right:
        if result["thumbnail"]:
            st.image(str(result["thumbnail"]), caption="The region (H&E, public TCGA-BRCA slide)",
                     width="stretch")

    m1, m2 = st.columns(2)
    with m1:
        st.markdown("**Certainty map**")
        chips("placeholder cutoffs")
        st.caption(f"Unsure here = top probability below {CUTOFFS['unsure_below'][0]} "
                   f"({CUTOFFS['unsure_below'][2]}). On the held-out BCSS tiles the head was right "
                   f"on {head.get('accuracy_below_cutoff', float('nan')):.0%} of tiles below the "
                   f"cutoff and {head.get('accuracy_at_or_above_cutoff', float('nan')):.0%} at or "
                   f"above it ({head.get('share_below_cutoff', float('nan')):.0%} of tiles below).")
        st.altair_chart(tile_chart(
            df, "certainty", alt.Scale(domain=["confident", "unsure here", "excluded"],
                                       range=["#2a78d6", "#f39c12", "#bbbbbb"]),
            "Certainty", hover, res["grid_shape"], 300), width="content")
    with m2:
        st.markdown("**Tumor region, front and zones**")
        st.caption("Tumor = smoothed P(invasive carcinoma) ≥ 0.5 (design); zones by distance to "
                   "the front: core (> 500 µm inside), front band (± 500 µm), peritumoral "
                   "(0.5–2 mm outside). Geometry on model inferences.")
        zdf = df.copy()
        zdf["zone_shown"] = zdf["zone"].where(~zdf["front"], "front line")
        zdf.loc[zdf["zone_shown"] == "", "zone_shown"] = "no tissue zone"
        st.altair_chart(tile_chart(
            zdf, "zone_shown", alt.Scale(
                domain=["core", "front line", "front band", "peritumoral", "outside",
                        "no tissue zone"],
                range=[ZONE_COLORS["core"], "#000000", ZONE_COLORS["front band"],
                       ZONE_COLORS["peritumoral"], ZONE_COLORS["outside"], "#ffffff"]),
            "Zone", hover + ["zone:N"], res["grid_shape"], 300), width="content")

    # --- quality control ---------------------------------------------------------------------
    st.markdown("#### Quality control")
    chips("placeholder cutoffs")
    excluded = df[df["qc"] != QC_OK]
    st.caption("Glass, pen ink and blur are checked per tile from texture and colour measures "
               "(edge density, structure coverage, ink colour shares, Laplacian variance). The "
               "cutoffs were set by eye on the team's colon slides and have not been re-checked "
               "on breast tissue: placeholders. Blood, folds and stain variation are not checked "
               "yet (planned).")
    if excluded.empty:
        st.markdown(f"No tile excluded ({s['tiles']} tiles, all passed).")
    else:
        cols = ["row", "col", "qc", "edges", "structure_cov", "ink_bluegreen", "ink_black",
                "ink_red", "blur"]
        st.dataframe(excluded[cols], hide_index=True, width="stretch")

    # --- the head's card ---------------------------------------------------------------------
    st.markdown("#### Tissue head: measured accuracy and training data")
    st.markdown(
        f"**Training data:** {head.get('training_data', '?')}, labels from BCSS (Amgad et al. "
        f"2019, CC0; crowd-drawn region masks on TCGA-BRCA slides). **Held out:** "
        f"{head.get('held_out', '?')}. **Accuracy:** {head.get('accuracy', float('nan')):.1%} "
        f"(balanced {head.get('balanced_accuracy', float('nan')):.1%}). Per class, on the held-out "
        "slides:")
    per = head.get("per_class", {})
    if per:
        st.dataframe(pd.DataFrame([{"class": LABELS.get(k, k), "training tiles": v["n_train"],
                                    "held-out tiles": v["n_test"],
                                    "recall": f"{v['recall']:.0%}" if v["recall"] is not None
                                    else "no held-out tiles"} for k, v in per.items()]),
                     hide_index=True, width="stretch")
    not_learned = head.get("not_learned", {})
    if not_learned:
        st.markdown("**Not in the head:** " + "; ".join(
            f"{LABELS.get(k, k).lower()} ({why})" for k, why in not_learned.items())
            + ". Tiles of these tissues get one of the classes above: a known failure.")
    conf = head.get("confusion")
    if conf:
        with st.expander("Confusion matrix on the held-out tiles (rows true, columns predicted)"):
            labels = [LABELS.get(k, k) for k in conf["labels"]]
            st.dataframe(pd.DataFrame(conf["rows_true_cols_pred"], index=labels, columns=labels),
                         width="stretch")
    st.caption(f"Encoder: {enc.get('name', '?')}, {enc.get('license', '?')}, "
               f"{enc.get('access', '?')}; measured {enc.get('tiles_per_s_cpu', '?')} tiles/s on "
               f"this PC's CPU with {enc.get('peak_rss_gb', '?')} GB peak memory. The encoder's "
               "own benchmarks are not evidence for this task. Not reviewed by a pathologist.")

    # --- what this map cannot see ------------------------------------------------------------
    st.markdown("#### What this map cannot see")
    st.dataframe(pd.DataFrame([{"not visible here": what, "why": why, "what can": how}
                               for what, why, how in CANNOT_SEE]), hide_index=True,
                 width="stretch")
    with st.expander("Every cutoff and its source"):
        st.dataframe(pd.DataFrame([{"cutoff": k, "value": v, "source": tag, "note": note}
                                   for k, (v, tag, note) in CUTOFFS.items()]), hide_index=True,
                     width="stretch")
        st.caption(f"{sum(1 for v in CUTOFFS.values() if v[1] == PLACEHOLDER)} of "
                   f"{len(CUTOFFS)} cutoffs are placeholders. Evidence types on this page: "
                   f"tile positions and the thumbnail are {OBSERVED}; every class, region, front "
                   f"and zone is {INFERENCE}.")
    st.caption("Planned, not shown: direction-of-invasion arrows, budding hotspots, risk map and "
               "flags, comparison with earlier slides, pins and exports.")


if __name__ == "__main__":
    import json

    from muffle.workspace import synthetic_file

    st.set_page_config(page_title="Pathology slide workbench", layout="wide")
    tl = json.loads((APP / "timeline_synthetic.json").read_text(encoding="utf-8"))
    render(synthetic_file(tl))

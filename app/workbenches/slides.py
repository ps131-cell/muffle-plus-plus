"""Pathology slide workbench for a patient file (docs/WORKSPACE.md, "Pathology slides";
docs/WORKBENCHES.md §5; docs/pathology.md).

streamlit run app/workbenches/slides.py        # standalone page on the example region

The workspace pages call ``render(file, version=None)`` with a ``muffle.workspace.PatientFile``;
it draws inside the current container only. When ``slides_results/<slide>/`` holds the
patient's own scored diagnostic section(s) (``scripts/slide_pipeline.py``), the page shows
them: the tissue map with layers, the direction of invasion (arrows and a rose), breakaway
candidates with the counting field, immune pattern, satellite islands, the risk map with its
cards, a Spot panel per tile, search, review marks, a comparison of two sections, the model
and validation card and export. Otherwise it shows the pipeline on a public example region and
says so. Every class is a model inference; every cutoff names its source; nothing here is a
diagnosis.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import sys
import time
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))
if str(APP) not in sys.path:  # standalone: streamlit run app/workbenches/slides.py
    sys.path.insert(0, str(APP))

import altair as alt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle.report.case_tools import INFERENCE, OBSERVED  # noqa: E402
from muffle.workbench import invasion as inv  # noqa: E402
from muffle.workbench.slides import (  # noqa: E402
    COLORS,
    CUTOFFS,
    LABELS,
    PLACEHOLDER,
    QC_OK,
    TILE_UM,
    analyze,
    load_result,
)
from muffle.workbench.grammar import chip  # noqa: E402
from muffle.workbench.slides import queue as slide_queue  # noqa: E402
from muffle.workspace import MARKS, PLANNED, PatientFile, finding_key  # noqa: E402
from workbenches import slide_viewer  # noqa: E402
from workbenches._page import Page, land, queue_items  # noqa: E402

EXAMPLE = APP / "workbenches" / "slides_example"
RESULTS = APP / "workbenches" / "slides_results"
ZONE_COLORS = {"core": "#8e1b1b", "front band": "#f39c12", "peritumoral": "#f9e79f",
               "outside": "#dfe6e9", "": "#ffffff"}
RISK_COLORS = ["#f4f6f7", "#fde9c9", "#f5b041", "#c0392b"]
GRID = {"gridOpacity": 0, "domainOpacity": 0, "tickOpacity": 0, "labels": False, "title": None}
LAYERS = ["tissue", "certainty", "QC", "zones", "immune", "lymphocytes (second model)", "risk"]
OVERLAYS = ["front", "arrows", "breakaway", "pointers"]
NO_MARK = "no mark"


CHIP_COLORS = {"example slide": "violet",  # statuses, evidence, placeholders: the shared grammar
               "patient's own slide": "green", "hypothesis": "orange",
               "not reviewed by a pathologist": "red", "weak until validated": "orange"}


def chips(*labels: str) -> None:
    st.caption(" ".join(chip(label, CHIP_COLORS.get(label)) for label in labels))


def own_slides(index) -> list[str]:
    """The scored slide folders of a cohort index (``slides_results/cases.json``)."""
    path = RESULTS / "cases.json"
    if not path.exists():
        return []
    names = json.loads(path.read_text(encoding="utf-8")).get(str(index), [])
    return [n for n in names if (RESULTS / n / "tiles.json").exists()]


def tile_chart(tiles: pd.DataFrame, color_field: str, scale: alt.Scale, title: str,
               tooltip: list, grid_shape: list[int], height: int = 360) -> alt.Chart:
    """One square per tile on ordinal axes; hover shows the tooltip fields (example page)."""
    h, w = grid_shape
    step = max(4, int(height / h))
    return (alt.Chart(tiles).mark_rect(stroke="white", strokeWidth=0.3)
            .encode(x=alt.X("col:O", axis=alt.Axis(**GRID)),
                    y=alt.Y("row:O", axis=alt.Axis(**GRID)),
                    color=alt.Color(f"{color_field}:N", scale=scale, title=title),
                    tooltip=tooltip)
            .properties(width=alt.Step(step), height=alt.Step(step)))


# --- review marks (the workspace's store, kind "slide") --------------------------------------

def slide_key(pf: PatientFile, slide: str, tile: str) -> str:
    return finding_key(pf, "slide", slide, tile)


def mark_box(pf: PatientFile, key: str, what: str) -> None:
    """Agree / disagree / second look and a pin for one finding."""
    reviews = st.session_state.setdefault("reviews", {})
    pins = st.session_state.setdefault("pins", {})
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    done = reviews.get(key)
    choice = st.segmented_control("Your mark", [NO_MARK, *MARKS], key=f"smark-{h}",
                                  default=done["mark"] if done else NO_MARK)
    if choice in (None, NO_MARK):
        reviews.pop(key, None)
    elif not done or done["mark"] != choice:
        reviews[key] = {"what": what, "mark": choice,
                        "by": (st.session_state.get("reviewer") or "").strip(),
                        "at": dt.datetime.now().strftime("%Y-%m-%d %H:%M")}
    if st.checkbox("Pin", key=f"spin-{h}", value=key in pins):
        pins[key] = what
    else:
        pins.pop(key, None)
    if key in reviews:
        r = reviews[key]
        st.caption(f"{r['mark']} · {r['by'] or 'no initials'} · {r['at']}")


# --- the viewer and the Spot panel follow each other --------------------------------------

def go_to(k: str, slide: str, tile: str) -> None:
    """Point the viewer and the Spot panel at a tile ("r12c34"); a callback, so it runs before
    the page is drawn again."""
    try:
        rr, cc = (int(v) for v in tile.strip()[1:].split("c"))
    except ValueError:
        return
    st.session_state[f"{k}-spot"] = tile.strip()
    st.session_state[f"{k}-goto"] = {"slide": slide, "row": rr, "col": cc, "nonce": time.time()}


def viewer_event(pid: str, key: str) -> None:
    """A click, n / p or "jump to" in a viewer opens its tile in that section's Spot panel; a
    browser that cannot load the tiles switches the page to its tile map."""
    ev = st.session_state.get(key) or {}
    if ev.get("failed"):
        st.session_state[f"{pid}|{ev['slide']}-viewer-failed"] = ev["failed"]
    elif ev.get("tile"):
        st.session_state[f"{pid}-section"] = ev["slide"]
        st.session_state[f"{pid}|{ev['slide']}-spot"] = ev["tile"]


# --- the patient's own slide -------------------------------------------------------------

def load_slide(folder: Path) -> dict | None:
    if not (folder / "tiles.json").exists():
        return None
    tiles = pd.read_json(folder / "tiles.json", orient="split")
    meta = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    nuc = json.loads((folder / "nuclei.json").read_text(encoding="utf-8")) \
        if (folder / "nuclei.json").exists() else {"tiles": [], "points": {}}
    if nuc.get("tiles") and nuc["tiles"].get("data"):
        summ = pd.DataFrame(nuc["tiles"]["data"], columns=nuc["tiles"]["columns"])
        tiles = tiles.merge(summ, on=["row", "col"], how="left")
    til = None
    if (folder / "til.json").exists():  # the second lymphocyte model, where it scored
        til = json.loads((folder / "til.json").read_text(encoding="utf-8"))
        scores = til.pop("tiles", {})
        if scores:
            tiles["tile_id"] = "r" + tiles["row"].astype(str) + "c" + tiles["col"].astype(str)
            tiles["p_til"] = tiles["tile_id"].map(scores)
            tiles = tiles.drop(columns="tile_id")
    return {"tiles": tiles, "meta": meta, "points": nuc.get("points", {}), "nuclei": nuc,
            "til": til,
            "thumbnail": folder / "thumbnail.jpg" if (folder / "thumbnail.jpg").exists()
            else None, "crops": folder / "crops", "folder": folder}


def frame(res: dict, classes: list[str]) -> pd.DataFrame:
    """The per-tile frame the charts and tables use, with readable columns."""
    df = res["tiles"].copy()
    df["tile"] = "r" + df["row"].astype(str) + "c" + df["col"].astype(str)
    df["class"] = df["label"].map(LABELS).fillna("")
    df["certainty"] = df["unsure"].map({True: "unsure here", False: "confident"})
    bad = df["qc"] != QC_OK
    df.loc[bad, "class"] = "excluded: " + df.loc[bad, "qc"]
    df.loc[bad, "certainty"] = "excluded"
    df["top"] = df[[f"p_{k}" for k in classes]].max(axis=1).map(lambda v: f"{v:.0%}")
    df["scores"] = df.apply(lambda r: " ".join(
        f"{LABELS[k].split()[0].lower()} {r[f'p_{k}']:.0%}" for k in classes), axis=1)
    df["zone_shown"] = df["zone"].where(~df["front"], "front line")
    df.loc[df["zone_shown"] == "", "zone_shown"] = "no tissue zone"
    df["risk"] = df["risk_level"].map({0: "none", 1: "level 1", 2: "level 2", 3: "level 3"})
    if "n_nuclei" in df:
        df["nuclei"] = df.apply(lambda r: "not counted" if pd.isna(r["n_nuclei"]) else
                                f"{int(r['n_nuclei'])} nuclei, {int(r['n_lymph'])} lymphocyte-"
                                f"like, {int(r['buds'])} breakaway cluster(s)", axis=1)
        df["immune"] = np.where(df["n_nuclei"].isna(), "not counted",
                                np.where(df["n_lymph"].fillna(0) >= 20, "many lymphocytes",
                                         np.where(df["n_lymph"].fillna(0) >= 5, "some", "few")))
    else:
        df["nuclei"], df["immune"] = "not counted", "not counted"
    if "til_lymph" in df:
        df["second model"] = np.where(df["til_lymph"].isna(), "not scored",
                                      np.where(df["til_lymph"] == 1, "lymphocytes",
                                               "not lymphocytes"))
        df.loc[df["disagree"].fillna(False).astype(bool), "second model"] += " (disagrees)"
    else:
        df["second model"] = "not scored"
    df["dist"] = df["dist_to_front_um"].map(lambda v: f"{v + 0.0:+.0f} µm from the front"
                                            if pd.notna(v) else "no front") \
        if "dist_to_front_um" in df else "no front"
    df["where"] = df["tile"] + " · " + df["zone"].replace("", "no zone") + " · " + df["dist"]
    return df


def slide_map(df: pd.DataFrame, res: dict, layer: str, overlays: list[str], classes: list[str],
              px: int) -> alt.Chart:
    """The map on quantitative axes so arrows, markers and labels can be layered on it."""
    h, w = res["grid_shape"]
    tooltip = ["where:N", "class:N", "top:N", "scores:N", "certainty:N", "nuclei:N",
               alt.Tooltip("second model:N", title="lymphocytes (second model)"),
               alt.Tooltip("risk_points:Q", title="risk points")]
    cls_domain = [LABELS[k] for k in classes] + sorted(
        v for v in df["class"].unique() if v.startswith("excluded"))
    cls_range = [COLORS[k] for k in classes] + ["#bbbbbb"] * (len(cls_domain) - len(classes))
    scales = {
        "tissue": ("class", alt.Scale(domain=cls_domain, range=cls_range), "Tissue class"),
        "certainty": ("certainty", alt.Scale(domain=["confident", "unsure here", "excluded"],
                                             range=["#2a78d6", "#f39c12", "#bbbbbb"]),
                      "Certainty"),
        "QC": ("qc", alt.Scale(domain=[QC_OK, "glass", "pen ink", "blur"],
                               range=["#dfe6e9", "#74b9ff", "#6c5ce7", "#d63031"]), "Quality"),
        "zones": ("zone_shown", alt.Scale(
            domain=["core", "front line", "front band", "peritumoral", "outside",
                    "no tissue zone"],
            range=[ZONE_COLORS["core"], "#000000", ZONE_COLORS["front band"],
                   ZONE_COLORS["peritumoral"], ZONE_COLORS["outside"], "#ffffff"]), "Zone"),
        "immune": ("immune", alt.Scale(domain=["many lymphocytes", "some", "few", "not counted"],
                                       range=["#1b4f72", "#5dade2", "#d6eaf8", "#f4f6f7"]),
                   "Lymphocyte-like nuclei"),
        "risk": ("risk", alt.Scale(domain=["none", "level 1", "level 2", "level 3"],
                                   range=RISK_COLORS), "Risk level (placeholder points)"),
        "lymphocytes (second model)": ("second model", alt.Scale(
            domain=["lymphocytes", "lymphocytes (disagrees)", "not lymphocytes",
                    "not lymphocytes (disagrees)", "not scored"],
            range=["#1b4f72", "#e67e22", "#d6eaf8", "#f5b7b1", "#f4f6f7"]),
            "Second model (orange and red: the head disagrees)"),
    }
    field, scale, title = scales[layer]
    x = alt.X("col:Q", scale=alt.Scale(domain=[0, w], nice=False), axis=None)
    y = alt.Y("row:Q", scale=alt.Scale(domain=[h, 0], nice=False), axis=None)
    base = (alt.Chart(df.assign(col2=df["col"] + 1, row2=df["row"] + 1))
            .mark_rect(stroke="white", strokeWidth=0.2)
            .encode(x=x, y=y, x2="col2:Q", y2="row2:Q",
                    color=alt.Color(f"{field}:N", scale=scale, title=title), tooltip=tooltip))
    layers = [base]
    if "front" in overlays and df["front"].any():
        f = df[df["front"]]
        layers.append(alt.Chart(f.assign(col2=f["col"] + 1, row2=f["row"] + 1))
                      .mark_rect(fill="black", fillOpacity=0.55)
                      .encode(x=x, y=y, x2="col2:Q", y2="row2:Q"))
    if "arrows" in overlays and res["arcs"]:
        a = pd.DataFrame(res["arcs"])
        a["x"], a["y"] = a["col"] + 0.5, a["row"] + 0.5
        length = 4 + 14 * a["push"]
        rad = np.radians(a["direction_deg"])
        a["x2"], a["y2"] = a["x"] + length * np.cos(rad), a["y"] - length * np.sin(rad)
        a["tip"] = (90 - a["direction_deg"]) % 360
        a["text"] = a["arc"] + " " + a["pattern"]
        shaft = alt.Chart(a).mark_rule(strokeWidth=3, color="#111").encode(
            x="x:Q", y="y:Q", x2="x2:Q", y2="y2:Q",
            tooltip=["arc:N", "pattern:N", alt.Tooltip("direction_deg:Q", title="direction °"),
                     "push:Q", "roughness:Q", "faces_top:N", "length_mm:Q"])
        tip = alt.Chart(a).mark_point(shape="triangle", size=160, filled=True, color="#111")\
            .encode(x="x2:Q", y="y2:Q", angle=alt.Angle("tip:Q", scale=alt.Scale(domain=[0, 360],
                                                                                 range=[0, 360])))
        label = alt.Chart(a).mark_text(dx=8, dy=-8, fontSize=10, color="#111").encode(
            x="x2:Q", y="y2:Q", text="arc:N")
        layers += [shaft, tip, label]
    if "breakaway" in overlays and "buds" in df and df["buds"].fillna(0).gt(0).any():
        b = df[df["buds"].fillna(0) > 0]
        layers.append(alt.Chart(b.assign(x=b["col"] + 0.5, y=b["row"] + 0.5))
                      .mark_point(shape="diamond", color="#8e44ad", filled=True)
                      .encode(x="x:Q", y="y:Q", size=alt.Size("buds:Q", legend=None),
                              tooltip=["where:N", "nuclei:N"]))
        hs = res["hotspot"]
        if hs:
            circle = pd.DataFrame({"x": [hs["col"] + 0.5], "y": [hs["row"] + 0.5]})
            layers.append(alt.Chart(circle).mark_point(
                size=(2 * hs["radius_tiles"] * px) ** 2, color="#8e44ad", strokeWidth=2,
                strokeDash=[4, 3]).encode(x="x:Q", y="y:Q"))
    if "pointers" in overlays and res["queue"]:
        q = pd.DataFrame(res["queue"])
        q["x"], q["y"] = q["col"] + 0.5, q["row"] + 0.5
        layers.append(alt.Chart(q).mark_point(shape="square", size=220, color="#00bcd4",
                                              strokeWidth=2).encode(
            x="x:Q", y="y:Q", tooltip=["pointer:N", "what:N", "check:N"]))
        layers.append(alt.Chart(q).mark_text(dx=12, dy=-10, fontSize=11, fontWeight="bold",
                                             color="#006064").encode(x="x:Q", y="y:Q",
                                                                     text="pointer:N"))
    return alt.layer(*layers).properties(width=w * px, height=h * px)


def rose_chart(rose: list[dict]) -> alt.Chart:
    r = pd.DataFrame(rose)
    r["t1"] = np.radians((90 - r["to_deg"]) % 360)
    r["t2"] = r["t1"] + np.radians(r["to_deg"] - r["from_deg"])
    r["label"] = r.apply(lambda b: f"{int(b.from_deg)}–{int(b.to_deg)}° "
                         f"({inv.compass((b.from_deg + b.to_deg) / 2)})", axis=1)
    return (alt.Chart(r).mark_arc(innerRadius=4, stroke="white")
            .encode(theta=alt.Theta("t1:Q", scale=alt.Scale(domain=[0, 2 * math.pi])),
                    theta2="t2:Q",
                    radius=alt.Radius("push_sum:Q", scale=alt.Scale(type="sqrt", zero=True)),
                    color=alt.Color("push_mean:Q", scale=alt.Scale(scheme="reds"),
                                    title="mean push"),
                    tooltip=["label:N", "tiles:Q", "push_sum:Q", "push_mean:Q"])
            .properties(width=220, height=220))


def crop_image(result: dict, row: int, col: int):
    """The 224 px crop with nuclei dots (lymphocyte-like blue, others red), or None."""
    from PIL import Image, ImageDraw

    path = result["crops"] / f"{row}_{col}.jpg"
    if not path.exists():
        return None
    img = Image.open(path).convert("RGB")
    pts = result["points"].get(f"{row}_{col}")
    if pts:
        d = ImageDraw.Draw(img)
        k = img.width / TILE_UM  # px per µm
        for x, y, lymph in pts:
            d.ellipse([x * k - 3, y * k - 3, x * k + 3, y * k + 3],
                      outline="#2e86de" if lymph else "#c0392b", width=2)
    return img


def spot_panel(pf: PatientFile, slide: str, result: dict, df: pd.DataFrame, res: dict,
               classes: list[str], r: int, c: int, meta: dict) -> None:
    rows = df[(df["row"] == r) & (df["col"] == c)]
    if rows.empty:
        st.warning("No tile at that position.")
        return
    t = rows.iloc[0]
    left, right = st.columns([1, 2])
    with left:
        img = crop_image(result, r, c)
        if img is not None:
            st.image(img, caption=f"{t['tile']}: 112 µm, the patient's own section", width=260,
                     alt=f"H&E crop of tile {t['tile']}, 112 µm across, with the nuclei found "
                         "marked: lymphocyte-like in blue, others in red")
        else:
            st.caption("No crop stored for this tile (crops are kept for the queue, the "
                       "counting field, the cards and the roughest front tiles).")
    with right:
        step, mpp = meta.get("step_base_px", 448), meta.get("base_mpp", 0.25)
        r0, c0 = meta.get("scored", {}).get("origin_tile", [0, 0])
        st.markdown(f"**{t['tile']}** · {(c0 + c) * step * mpp / 1000:.1f} mm from the left, "
                    f"{(r0 + r) * step * mpp / 1000:.1f} mm from the top of the slide · "
                    f"{t['zone'] or 'no zone'} · {t['dist']}"
                    + (" · on the front" if t["front"] else "")
                    + (" · finger" if t.get("finger") else ""))
        st.markdown(f"**Class** {t['class']} ({t['top']}) · **certainty** {t['certainty']}"
                    + (f": top probability below {CUTOFFS['unsure_below'][0]} (placeholder "
                       "cutoff)" if t["unsure"] else "")
                    + f" · {INFERENCE}")
        scores = pd.DataFrame({"class": [LABELS[k] for k in classes],
                               "probability": [float(t[f"p_{k}"]) for k in classes]})
        st.altair_chart(alt.Chart(scores).mark_bar().encode(
            x=alt.X("probability:Q", scale=alt.Scale(domain=[0, 1])), y=alt.Y("class:N", sort=None),
            color=alt.Color("class:N", legend=None, scale=alt.Scale(
                domain=[LABELS[k] for k in classes], range=[COLORS[k] for k in classes])))
            .properties(height=120), width="stretch")
        counted = "n_nuclei" in t and pd.notna(t.get("n_nuclei"))
        cv_txt = ("n/a" if not counted or pd.isna(t.get("nuc_area_cv"))
                  else f"{t['nuc_area_cv']:.2f}")
        st.markdown(f"**Nuclei** {t['nuclei']}"
                    + (f"; {int(t['n_lymph_near_tumor'])} lymphocyte-like within 50 µm of a "
                       f"tumor candidate; nuclear-area variation {cv_txt} (a proxy, never a "
                       "grade)" if counted else "")
                    + f" · **risk points** {t['risk_points']:.0f} ({t['risk']}, placeholder)")
        checks = []
        if t["front"]:
            checks.append("the edge at 20×: single cells or small nests beyond the line")
        if t.get("buds", 0) and t["buds"] > 0:
            checks.append("each breakaway cluster: tumor cells, or stromal / inflammatory nuclei "
                          "cut by the tile border?")
        if t["unsure"]:
            checks.append("what tissue this is: the head could not decide")
        if t["label"] == "necrosis":
            checks.append("necrosis against a tumor nest, or debris / secretion?")
        if t["label"] == "lymphocytes":
            checks.append("stromal versus intratumoral lymphocytes (TILs Working Group)")
        if t["qc"] != QC_OK:
            checks.append(f"excluded for {t['qc']}: judge the tissue by eye")
        st.markdown("**What to check by eye:** " + ("; ".join(checks) if checks else
                                                     "nothing specific flagged here"))
        hs = res["hotspot"]
        if hs and (r, c) == (hs["row"], hs["col"]):  # one mark per finding on the page
            st.caption("This tile is the counting field's centre: your mark for it is with the "
                       "breakaway candidates above.")
        else:
            mark_box(pf, slide_key(pf, slide, t["tile"]),
                     f"Slide {slide}, tile {t['tile']}: {t['class']} ({t['zone'] or 'no zone'})")


def head_card(meta: dict, classes: list[str]) -> None:
    head, enc = meta.get("head", {}), meta.get("encoder", {})
    st.markdown(
        f"**Tissue head.** {inv.MODEL_CARD['tissue head']}. **Training data:** "
        f"{head.get('training_data', '?')}, labels from BCSS (Amgad et al. 2019, CC0). "
        f"**Held out:** {head.get('held_out', '?')}. **Accuracy:** "
        f"{head.get('accuracy', float('nan')):.1%} (balanced "
        f"{head.get('balanced_accuracy', float('nan')):.1%}); below the unsure cutoff the head "
        f"was right on {head.get('accuracy_below_cutoff', float('nan')):.0%} of tiles, at or "
        f"above it {head.get('accuracy_at_or_above_cutoff', float('nan')):.0%}."
        + (" **This patient's slide was among the head's training or held-out slides.**"
           if head.get("this_patient_in_training") else
           " This patient is not among the head's training or held-out slides."))
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
               f"{enc.get('access', '?')}; {enc.get('tiles_per_s_cpu', '?')} tiles/s on this "
               f"PC's CPU ({enc.get('threads', '?')} threads, shared with other work). The "
               "encoder's own benchmarks are not evidence for this task.")


def cannot_see(page: Page, cutoffs: dict | None = None) -> None:
    with page.cannot_see():
        st.dataframe(pd.DataFrame([{"not visible here": what, "why": why, "what can": how}
                                   for what, why, how in inv.CANNOT_SEE]), hide_index=True,
                     width="stretch")
        both = {**CUTOFFS, **(cutoffs or {})}
        n = sum(1 for v in both.values() if v[1] == PLACEHOLDER)
        with st.expander(f"Every cutoff and its source ({n} of {len(both)} placeholders)"):
            st.dataframe(pd.DataFrame([{"cutoff": k, "value": v, "source": tag, "note": note}
                                       for k, (v, tag, note) in both.items()]),
                         hide_index=True, width="stretch")
            st.caption(f"{n} of {len(both)} cutoffs are placeholders. Evidence types: tile "
                       f"positions, crops and the thumbnail are {OBSERVED}; every class, "
                       f"nucleus, region, front, zone and point is {INFERENCE}; the direction of "
                       "invasion is a hypothesis about this section.")


@st.cache_data(max_entries=16, show_spinner=False)
def section_numbers(slide: str) -> dict | None:
    """A scored section's stored numbers (its summary.json), for the comparison of sections:
    the other sections are read, not analysed again."""
    path = RESULTS / slide / "summary.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8")).get("numbers", {})


@st.cache_data(max_entries=8, show_spinner="Reading the scored section…")
def scored(slide: str) -> tuple[dict, dict, pd.DataFrame] | None:
    """A scored section, its analysis and its tile frame: they depend on the slide only, so
    they are computed once per process, not on every click in the workbench."""
    result = load_slide(RESULTS / slide)
    if result is None:
        return None
    classes = result["meta"]["head"]["classes"]
    til = result.get("til")
    res = inv.analyze_slide(result["tiles"], classes, til_cutoff=til["cutoff"] if til else None,
                            til_calibrated=bool(til and "calibrated" in til.get(
                                "cutoff_source", "")))
    return result, res, frame(res, classes)


def look_items(pf: PatientFile, slide: str, version: int | None, res: dict) -> list[dict]:
    """The section's look-here items: the ones the report's attention queue carries
    (``muffle.workbench.slides.queue``), or, for a section scored before those were stored,
    the page's own pointers in the same shape."""
    items = [x for x in queue_items("slides", pf, version, lambda: slide_queue(pf, version))
             if x["focus"]["slide"] == slide]
    if items:
        return items
    return [{"pointer": q["pointer"], "what": q["what"], "why": f"{q['why']}; check by eye: "
             f"{q['check']}", "evidence": q["evidence"], "trust": "weak", "consequence": 1,
             "month": None, "key": slide_key(pf, slide, f"r{q['row']}c{q['col']}"),
             "focus": {"slide": slide, "pointer": q["pointer"],
                       "tile": f"r{q['row']}c{q['col']}"}} for q in res["queue"]]


def render_slide(page: Page, pf: PatientFile, slide: str, version: int | None,
                 compare=None) -> None:
    """One scored section in the page skeleton; ``compare`` draws the details that compare it
    with the file's other sections."""
    if (got := scored(slide)) is None:
        return
    result, res, df = got
    meta = result["meta"]
    classes = meta["head"]["classes"]
    s, n = res["summary"], res["numbers"]
    sc, nuc, til = meta.get("scored", {}), meta.get("nuclei", {}), result.get("til")
    k = f"{pf.id}|{slide}"
    st.caption(
        f"Source: {meta.get('source', '')} · slide {slide} · scored: {sc.get('mode', '?')}, "
        f"{sc.get('scored_tiles', '?')} of {sc.get('tissue_tiles_total', '?')} tissue tiles of "
        f"{TILE_UM:.0f} µm ({sc.get('why', '')}) · encoder {meta.get('encoder', {}).get('name')} "
        f"· head: {meta.get('head', {}).get('kind')} · nuclei: {nuc.get('model') or 'not run'} on "
        f"{nuc.get('tiles', 0)} tiles · method version {meta.get('method_version', '0.2')} · "
        f"status: {meta.get('status', 'implemented')}.")
    if sc.get("skipped_tiles"):
        st.warning(f"{sc['skipped_tiles']} tissue tiles outside the scored window were skipped "
                   "(the budget for this PC's CPU): tumor outside the window is not in this "
                   "map. The whole slide is in the pathology report.")
    reviews = st.session_state.setdefault("reviews", {})

    # --- overview, look here, search ---------------------------------------------------------
    frac = s["tissue_fractions"]
    top3 = sorted(frac.items(), key=lambda kv: -kv[1])[:3]
    infil = [a for a in res["arcs"] if a["pattern"] == "infiltrative"]
    main_dir = inv.compass(inv._circular_mean(
        np.array([a["direction_deg"] for a in infil]), np.array([a["push"] for a in infil]))) \
        if infil else None
    hs = res["hotspot"]
    text = (
        f"**{INFERENCE}.** Of {s['usable_tiles']} usable tiles the map reads "
        + ", ".join(f"{LABELS[k].lower()} {v:.0%}" for k, v in top3)
        + f". The main tumor covers {s['main_tumor_mm2']} mm² with a {s['front_length_mm']} mm "
        f"front cut into {n['arcs']} arcs, {n['infiltrative_arcs']} of them infiltrative"
        + (f", invading mostly {main_dir}" if main_dir else "")
        + f"; the front mostly faces {LABELS.get(n['faces_top'], n['faces_top']).lower()}. "
        f"{n['islands']} satellite island(s). Immune pattern: {n['immune_pattern']} "
        f"(placeholder cutoffs); tumor–stroma ratio {n['tsr']}. "
        + (f"Breakaway candidates: {hs['buds_in_field']} cluster(s) in the 0.785 mm² counting "
           f"field (weak until validated; {hs['coverage']:.0%} of the field counted). "
           if hs else "No breakaway candidate found in the counted tiles. ")
        + f"{s['unsure_share']:.0%} of the tissue is unsure. "
        + ("Excluded by quality control: " + ", ".join(f"{v} {k}" for k, v in
                                                       s["excluded"].items()) + "."
           if s["excluded"] else "No tile was excluded by quality control.")
    )
    with page.overview():
        st.markdown(text)
        st.markdown("**Hypothesis.** The arrows show where the tumor is invading in this "
                    "section: a 2D snapshot, not a forecast of where it will go.")
        row = st.container(horizontal=True)  # wraps on a narrow screen instead of cutting values
        row.metric("Tumor area (map)", f"{s['tumor_mm2']} mm²", width="content",
                   help="Tiles whose smoothed class is invasive carcinoma, at 112 µm per tile "
                        "(model inference).")
        row.metric("Front length", f"{s['front_length_mm']} mm", width="content",
                   help="The tumor's border on the tile grid, in mm of tissue (model inference).")
        row.metric("Infiltrative arcs", f"{n['infiltrative_arcs']} / {n['arcs']}",
                   width="content", help="Arcs of the front whose roughness passes the "
                                         "infiltrative cutoff (a placeholder).")
        row.metric("Breakaway in field", "—" if not hs else str(hs["buds_in_field"]),
                   help="clusters of up to 4 tumor-candidate nuclei in the 0.785 mm² field; "
                        "weak until validated", width="content")
        row.metric("Unsure share", f"{s['unsure_share']:.0%}", width="content",
                   help=f"Share of tiles whose top class probability is under "
                        f"{CUTOFFS['unsure_below'][0]} (a placeholder cutoff).")
        page.look_here(look_items(pf, slide, version, res),
                       land=lambda focus: land(pf, page.version, focus),
                       more="Details › Every look-here pointer")
        query = st.text_input("Search inside the slide, in plain words", key=f"{k}-search",
                              placeholder="budding · lymphocytes at the border · fat · unsure · "
                                          "satellite · direction · T2 · grade")
        if query:
            hit = inv.search(query, res)
            (st.markdown if hit["understood"] else st.warning)(hit["answer"])
            if len(hit["rows"]):
                show = df.merge(hit["rows"][["row", "col"]], on=["row", "col"])
                st.dataframe(show[["tile", "class", "top", "certainty", "zone", "nuclei",
                                   "risk_points"]].head(200), hide_index=True, width="stretch")

    # --- the picture: the viewer, or the tile map when the tiles can't be had ----------------
    src = slide_viewer.source(slide)
    failed = st.session_state.get(f"{k}-viewer-failed")
    has_rose = bool(res["rose"]) and res["normals"] is not None and len(res["normals"]) > 0
    rose_text = ("Rose of the front normals, push-weighted: the direction the front points and "
                 "how much tumor probability lies beyond it. A hypothesis about this section.")
    if isinstance(src, dict) and not failed:
        with page.picture("Slide viewer", caption=(
                f"The patient's own section (H&E) at {src['mpp']:.2f} µm per pixel, the scan's "
                "own level nearest 1 µm. Scroll or double-click to zoom from the whole section "
                "down to single nuclei, drag to pan; the minimap (top right) shows where you are. "
                "Colour the tiles by tissue class, certainty, quality control, zones, "
                "lymphocyte-like nuclei or risk level, and draw the front line, the arcs with "
                "their arrows, breakaway candidates with the counting field, islands, risk "
                "regions, the pointers and, zoomed in, every nucleus StarDist found on the "
                "counted tiles. Hover a tile for its scores; click it to open it in the Spot "
                "panel; n and p step through the pointers."
                + (" Only the tumor-centred window (dashed) was scored: the rest of the section "
                   "is shown, not analysed." if src["window"] else ""))):
            slide_viewer.show([src], key=f"{k}-viewer", goto=st.session_state.get(f"{k}-goto"),
                              on_change=lambda: viewer_event(pf.id, f"{k}-viewer"))
            rc, pc = st.columns([1, 3])
            if has_rose:
                rc.altair_chart(rose_chart(res["rose"]), width="content")
                rc.caption(rose_text)
            pc.caption(f"Tiles: a Deep Zoom pyramid of {slide} (GDC open access; JPEG, cut with "
                       "OpenSlide); viewer: OpenSeadragon 6.1.1. Each coloured tile is one score "
                       f"for {TILE_UM:.0f} µm of tissue; classes are model inferences smoothed "
                       "over 3×3 tiles, so their edges are a tile's width, not a cell's.")
    else:
        with page.picture("Tile map", caption=(
                "Hover a tile for its scores, zone, nuclei and risk points. Each tile is one "
                "score for 112 µm of tissue; classes are model inferences smoothed over 3×3 "
                "tiles. Arrows: one per arc, length by push; the dashed circle is the counting "
                "field; squares are the pointers.")):
            why = (failed or src).rstrip(".")  # the browser's reason is a sentence of its own
            st.info(f"The slide viewer is not available here: {why[:1].lower() + why[1:]}. The "
                    "tile map draws the same analysis on the scored grid, next to a picture of "
                    "the scored region.", icon="🔬")
            l1, l2 = st.columns([1, 2])
            layer = l1.radio("Layer", LAYERS, horizontal=True, key=f"{k}-layer")
            overlays = l2.pills("Overlays", OVERLAYS, selection_mode="multi",
                                default=["front", "arrows", "pointers"], key=f"{k}-overlays")
            h, w = res["grid_shape"]
            px = max(3, min(8, int(640 / max(h, w))))
            mc, tc = st.columns([3, 2])
            with mc:
                st.altair_chart(slide_map(df, res, layer, overlays or [], classes, px),
                                width="content",
                                alt=f"Tile map of slide {slide} coloured by {layer}: "
                                    + ", ".join(f"{LABELS[k].lower()} {v:.0%}" for k, v in
                                                top3) + f"; {len(res['queue'])} pointers")
            with tc:
                if result["thumbnail"]:
                    st.image(str(result["thumbnail"]), caption="The scored region (H&E, the "
                             "patient's own section)", width="stretch",
                             alt=f"H&E thumbnail of the scored region of slide {slide}")
                if has_rose:
                    st.altair_chart(rose_chart(res["rose"]), width="content")
                    st.caption(rose_text)

    # --- details ----------------------------------------------------------------------------
    with page.details("Direction of invasion: arcs of the front", len(res["arcs"])):
        chips("hypothesis", "placeholder cutoffs")
        st.caption(f"The front is cut into {CUTOFFS_INV['sectors'][0]} arcs around the tumor's "
                   "centroid. Direction = push-weighted mean outward normal; push = mean "
                   "P(invasive) over 3 tiles beyond the front (0 sharp, near 0.5 fading into the "
                   "tissue); roughness = share of the arc's tiles in fingers (opening of radius 2 "
                   f"tiles); infiltrative at {CUTOFFS_INV['infiltrative_arc'][0]:.0%} "
                   "(placeholder). Faces = classes of the tissue touching the arc.")
        if res["arcs"]:
            a = pd.DataFrame(res["arcs"])
            a["direction"] = a["direction_deg"].map(lambda d: f"{inv.compass(d)} ({d:.0f}°)")
            a["faces"] = a["faces"].map(lambda f: ", ".join(
                f"{LABELS.get(c, c).lower()} {v:.0%}" for c, v in list(f.items())[:3]))
            st.dataframe(a[["arc", "from_deg", "to_deg", "length_mm", "direction", "push",
                            "roughness", "pattern", "faces"]], hide_index=True, width="stretch")
            st.caption(f"Fingers found: {res['fingers']['n']}"
                       + ("" if res["fingers"]["judged"] else " (tumor too small to judge)")
                       + ".")
        else:
            st.caption("No tumor front in the map.")

    cells = (f"{hs['buds_in_field']} breakaway in the field" if hs else
             f"nuclei on {nuc.get('tiles', 0)} tiles")
    with page.details("Cells: breakaway candidates, lymphocytes, stroma and necrosis", cells):
        chips("weak until validated", "placeholder cutoffs")
        st.caption(f"{inv.MODEL_CARD['nuclei'][0].upper() + inv.MODEL_CARD['nuclei'][1:]}. "
                   f"Counted on {nuc.get('tiles', 0)} tiles ({nuc.get('nuclei', 0)} nuclei; "
                   f"{nuc.get('s_per_tile', '?')} s per tile), front tiles first, then the band "
                   "outside, then the rest of the front band and the peritumoral zone, up to the "
                   "budget. Every flag below is weak until validated.")
        g1, g2 = st.columns(2)
        with g1:
            st.markdown("**Breakaway (budding) candidates**")
            if hs:
                st.markdown(f"Counting field at tile r{hs['row']}c{hs['col']} (0.785 mm², the "
                            f"ITBCC 20× field): **{hs['buds_in_field']}** cluster(s) of ≤ 4 "
                            f"tumor-candidate nuclei outside the main tumor; {hs['coverage']:.0%} "
                            "of the field was counted. Budding grades (Bd1–3) are defined for "
                            "colorectal cancer and are not applied here. A cluster is a "
                            "tumor-nucleus candidate by its tile's class, not by cell "
                            "morphology.")
                st.number_input("Buds you count in this field at 20× (your count, kept with the "
                                "export)", min_value=0, max_value=200, step=1,
                                key=f"{k}-budcount")
                mark_box(pf, slide_key(pf, slide, f"r{hs['row']}c{hs['col']}"),
                         f"Slide {slide}: counting field, {hs['buds_in_field']} breakaway "
                         "candidate(s)")
            else:
                st.markdown("No breakaway candidate in the counted tiles" + (
                    "" if nuc.get("tiles") else " (nuclei were not counted)") + ".")
        with g2:
            st.markdown("**Stromal lymphocytes by zone** (International TILs Working Group "
                        "zones; a count proxy, not the WG's area percentage)")
            im = res["immune"]
            # numeric columns with NaN where a zone has nothing, so no mixed dtype reaches Arrow
            rows = [{"zone": z, "tiles": v["tiles"],
                     "lymphocyte-class tiles": v["lymph_tile_share"],
                     "lymphocyte tiles (second model)": v.get("til_lymph_share"),
                     "counted stroma tiles": v.get("counted_tiles", 0),
                     "lymphocyte-like nuclei / mm²": v.get("lymph_nuclei_per_mm2"),
                     "within 50 µm of tumor": v.get("tumor_contacting_share")}
                    for z, v in im["zones"].items()]
            zones = pd.DataFrame(rows)
            for col in ("lymphocyte-class tiles", "lymphocyte tiles (second model)",
                        "lymphocyte-like nuclei / mm²", "within 50 µm of tumor"):
                zones[col] = pd.to_numeric(zones[col], errors="coerce")
            st.dataframe(zones, hide_index=True, width="stretch", column_config={
                "lymphocyte-class tiles": st.column_config.NumberColumn(format="percent"),
                "lymphocyte tiles (second model)": st.column_config.NumberColumn(
                    format="percent"),
                "lymphocyte-like nuclei / mm²": st.column_config.NumberColumn(format="%d"),
                "within 50 µm of tumor": st.column_config.NumberColumn(format="percent")})
            st.caption("An empty cell means the zone has no tiles, no counted stroma tiles or no "
                       "tile scored by the second model.")
            d = res["til"]
            if til and d["scored"]:
                ho = til.get("held_out", {})
                at = ho.get("at_cutoff", {})
                st.markdown(f"**Second opinion ({INFERENCE}).** {inv.TIL_SECOND}: scored "
                            f"{d['scored']} front-band and peritumoral tiles; the head and it "
                            f"disagree on {d['disagree']} ({d['share']:.0%}; kappa {d['kappa']}; "
                            f"{d['head_only']} head only, {d['til_only']} second model only). "
                            f"Cutoff {d['cutoff']}: {til.get('cutoff_source', 'placeholder')}. "
                            f"Held out on the head's {len(ho.get('slides', []))} test slides "
                            f"({ho.get('tiles', '?')} tiles): AUROC "
                            f"{ho.get('auroc', float('nan'))}, recall "
                            f"{at.get('recall_lymphocytes', float('nan')):.0%}, specificity "
                            f"{at.get('specificity', float('nan')):.0%}. Switch the map's layer "
                            "to 'lymphocytes (second model)'; disagreeing tiles are in the "
                            "queue.")
            elif til is None:
                st.caption("No second lymphocyte model has scored this section.")
            else:
                st.caption("The second lymphocyte model scored no tile here: the map has no "
                           "front band or peritumoral zone to score.")
            st.markdown(f"Pattern: **{im['pattern']}** ({im['status']}).")
        row = st.container(horizontal=True)  # wraps on a narrow screen instead of cutting values
        tsr, nec = res["tsr"], res["necrosis"]
        row.metric("Tumor–stroma ratio", tsr["verdict"], width="content",
                   help=f"stroma {tsr['stroma_share']:.0%} of tumor-plus-stroma tiles in the "
                        f"tumor and its front band; stroma-high above 50% (literature, "
                        "colorectal)" if tsr["stroma_share"] is not None else "not assessed")
        n_nec = nec["touching_tumor_tiles"]
        row.metric("Necrosis touching tumor", f"{n_nec} tile{'' if n_nec == 1 else 's'}",
                   width="content",
                   help=f"{nec['necrosis_mm2']} mm² of necrosis-class tiles, "
                        f"{nec['share_touching'] or 0:.0%} touching tumor")
        cv = df["nuc_area_cv"].dropna() if "nuc_area_cv" in df else pd.Series(dtype=float)
        row.metric("Nuclear-area variation", f"{cv.median():.2f}" if len(cv) else "—",
                   width="content",
                   help="median coefficient of variation of non-lymphocyte nuclear area per "
                        "counted tile: a proxy only, never a grade")

    with page.details("Satellite islands", len(res["islands"])):
        if res["islands"]:
            isl = pd.DataFrame(res["islands"])
            isl["tissue between"] = isl["between_shares"].map(lambda f: ", ".join(
                f"{LABELS.get(c, c).lower()} {v:.0%}" for c, v in f.items()) or "touching")
            st.dataframe(isl[["island", "area_mm2", "distance_um", "tissue between"]],
                         hide_index=True, width="stretch")
            st.caption("Geometry on the tile classes. An island may be a satellite, a "
                       "tangential cut of the same tumor, or in-situ disease (DCIS is not a "
                       "class of the head).")
        else:
            st.caption("No separate tumor piece in the map.")

    cards = res["risk"]["cards"]
    with page.details("Risk map: points within 1 mm", f"{len(cards)} at level 2 or more"):
        chips("placeholder cutoffs")
        r1, r2 = st.columns([1, 2])
        with r1:
            st.dataframe(pd.DataFrame(res["risk"]["table"]), hide_index=True, width="stretch")
            st.caption(f"Level 2 at {CUTOFFS_INV['risk_level_2'][0]} points, level 3 at "
                       f"{CUTOFFS_INV['risk_level_3'][0]}; every value a placeholder, not an "
                       "outcome model. Switch the map's layer to 'risk'.")
        with r2:
            if cards:
                cols = st.columns(min(len(cards), 3))
                for i, c in enumerate(cards[:6]):
                    with cols[i % len(cols)]:
                        st.markdown(f"**{c['card']} · level {c['level']}** ({c['points']} "
                                    f"points, {c['mm2']} mm²)  \n" + ", ".join(c["features"]))
                        st.button(f"Open {c['card']} in the Spot panel", key=f"{k}-card-{i}",
                                  on_click=go_to, args=(k, slide, f"r{c['row']}c{c['col']}"))
            else:
                st.caption("No region reaches level 2.")

    excluded = df[df["qc"] != QC_OK]
    with page.details("Quality control", f"{len(excluded)} of {s['tiles']} tiles excluded"):
        chips("placeholder cutoffs")
        st.caption("Glass, pen ink and blur are checked per tile from texture and colour "
                   "measures; the cutoffs were set by eye on colon slides and not re-checked on "
                   "breast: placeholders. Blood, folds and stain variation are not checked "
                   "(planned). Switch the map's layer to 'QC' to see where.")
        st.markdown(f"{len(excluded)} of {s['tiles']} tiles excluded"
                    + (": " + ", ".join(f"{v} {k}" for k, v in s["excluded"].items())
                       if s["excluded"] else "") + ".")

    with page.details("Every look-here pointer", len(res["queue"])):
        st.caption("Pointers T1…Tn, shared by the text, the map and the Spot panel, with why "
                   "each is there and what to check by eye.")
        if res["queue"]:
            q = pd.DataFrame(res["queue"])
            q["review"] = [reviews.get(slide_key(pf, slide, f"r{p['row']}c{p['col']}"), {})
                           .get("mark", "") for p in res["queue"]]
            st.dataframe(q[["pointer", "review", "what", "why", "check", "evidence", "status"]],
                         hide_index=True, width="stretch")
        else:
            st.caption("Nothing in the queue: no tumor front, island or counted candidate.")
    if compare is not None:
        compare(page)

    # --- Spot panel -------------------------------------------------------------------------
    with page.spot("The full story of one tile: pick a pointer or a stored crop, type a tile, or "
                   "click one in the viewer."):
        options = [f"{p['pointer']} · r{p['row']}c{p['col']}" for p in res["queue"]] + [
            f"{c['why']} · r{c['row']}c{c['col']}" for c in meta.get("crops", [])
            if not any((c["row"], c["col"]) == (p["row"], p["col"]) for p in res["queue"])]
        s1, s2 = st.columns([2, 1])
        pick = s1.selectbox("A pointer or a stored crop", options, key=f"{k}-pick",
                            on_change=lambda: go_to(k, slide, (st.session_state[f"{k}-pick"]
                                                               or "").split("· ")[-1]))
        typed = s2.text_input("or a tile (r12c34), or click one in the viewer", key=f"{k}-spot",
                              placeholder="r12c34",
                              on_change=lambda: go_to(k, slide, st.session_state[f"{k}-spot"])
                              ).strip()
        target = typed or (pick.split("· ")[-1] if pick else "")
        try:
            rr, cc = target[1:].split("c")
            spot_panel(pf, slide, result, df, res, classes, int(rr), int(cc), meta)
        except (ValueError, IndexError):
            st.caption("Pick a pointer or type a tile such as r12c34.")

    # --- model and validation card, limits, export -------------------------------------------
    with page.card():
        chips("not reviewed by a pathologist")
        head_card(meta, classes)
        st.markdown(f"**Nuclei.** {inv.MODEL_CARD['nuclei']}. **Geometry.** "
                    f"{inv.MODEL_CARD['geometry']}. **Review.** {inv.MODEL_CARD['review']}.")
        if til:
            st.markdown(f"**Second lymphocyte model.** {inv.TIL_SECOND}; normalization "
                        f"{til.get('model', {}).get('normalization', '?')}; "
                        f"{til.get('s_per_tile', '?')} s per tile at {til.get('threads', '?')} "
                        f"threads ({til.get('uptime', '')}). "
                        "Its disagreement with the head is a queue item, never a verdict.")
        tm = meta.get("timings", {})
        st.caption("Timings on this PC's CPU: " + ", ".join(
            f"{k.replace('_s', '')} {v} s" for k, v in tm.items() if k.endswith("_s"))
            + f"; {tm.get('uptime_at_start', '')} at the start, {tm.get('uptime_at_end', '')} "
            "at the end (shared machine).")
        st.markdown("**Known failures:**\n" + "\n".join(f"- {f}" for f in inv.KNOWN_FAILURES))
    cannot_see(page, CUTOFFS_INV)

    with page.export():
        mine = {kk: v for kk, v in reviews.items() if kk.startswith(f"{pf.id}|slide|{slide}|")}
        export = {"patient": pf.id, "slide": slide,
                  "summary": {kk: v for kk, v in meta.items() if kk != "crops"},
                  "second_lymphocyte_model": {**(til or {}), "disagreement": {
                      kk: v for kk, v in res["til"].items() if kk != "rows"}} if til else None,
                  "your_bud_count": st.session_state.get(f"{k}-budcount"),
                  "review_marks": mine, "pins": {kk: v for kk, v in
                                                 st.session_state.get("pins", {}).items()
                                                 if kk.startswith(f"{pf.id}|slide|{slide}|")}}
        e = st.container(horizontal=True, gap="small")  # labels whole, wraps
        e.download_button("Download the findings (JSON)", json.dumps(export, indent=1,
                                                                      default=str),
                          file_name=f"{slide}_slide.json", mime="application/json",
                          key=f"{k}-json")
        cols = ["tile", "row", "col", "class", "top", "certainty", "qc", "zone", "dist", "front",
                "finger", "risk_points", "risk_level", "nuclei"]
        e.download_button("Download the tiles (CSV)", df[cols].to_csv(index=False),
                          file_name=f"{slide}_tiles.csv", mime="text/csv", key=f"{k}-csv")
        e.download_button("Download the map (PNG)",
                          inv.map_png(res["tiles"], inv.grid(res["tiles"], "front", False, bool),
                                      queue=res["queue"]),
                          file_name=f"{slide}_map.png", mime="image/png", key=f"{k}-png")


CUTOFFS_INV = inv.CUTOFFS


def render_own(page: Page, pf: PatientFile, slides: list[str], version: int | None) -> None:
    page.title("patient's own slide", "placeholder cutoffs", "not reviewed by a pathologist",
               "implemented, validated on held-out BCSS slides", colors=CHIP_COLORS)
    st.markdown(f"**{len(slides)} diagnostic section(s) of this patient's tumor** scored by the "
                "slide pipeline: " + ", ".join(slides) + ". Each section is one cut through the "
                "block: a 2D sample of the tumor, not the whole tumor.")
    chosen = st.radio("Section", slides, horizontal=True, key=f"{pf.id}-section") \
        if len(slides) > 1 else slides[0]

    def compare(page: Page) -> None:
        numbers = {}  # the open section's own analysis; the others' stored numbers, unanalysed
        for name in slides:
            if name == chosen and (got := scored(name)):
                numbers[name] = {**got[1]["numbers"], "slide": name}
            elif name != chosen and (stored := section_numbers(name)) is not None:
                numbers[name] = {**stored, "slide": name}
        pairs = [(a, b) for i, a in enumerate(slides) for b in slides[i + 1:]
                 if numbers.get(a) and numbers.get(b)]
        with page.details("The sections compared", len(slides)):
            for a, b in pairs:  # a column mixes numbers and words ("no front"), so show text
                st.dataframe(pd.DataFrame(inv.compare(numbers[a], numbers[b])).map(
                    lambda v: "—" if v is None else f"{v:.3g}" if isinstance(v, float)
                    else str(v)), hide_index=True, width="stretch")
            st.caption("Why sections differ: each is one plane through the block, so a front "
                       "that is infiltrative in one cut can be pushing in another, a satellite "
                       "in one section can be the same tumor cut tangentially, and the counted "
                       "tiles differ. Differences between sections are not change over time: "
                       "both were cut from the same specimen. Numbers differ by more than 20% "
                       "are marked.")
            st.caption("Differences in the immune pattern, the tumor–stroma ratio and the "
                       "breakaway count are between placeholder-rule outputs, not validated "
                       "measurements.")
        with page.details("The sections side by side", len(slides), key=f"{pf.id}-side-open",
                          lazy=True) as box:
            if box.open:
                side_by_side(pf, slides)
            else:
                st.caption("Opens two or three sections in viewers next to each other.")

    render_slide(page, pf, chosen, version, compare if len(slides) > 1 else None)


def side_by_side(pf: PatientFile, slides: list[str]) -> None:
    """Two or three sections in viewers next to each other, pan and zoom linked in µm."""
    srcs = {n: slide_viewer.source(n) for n in slides
            if not st.session_state.get(f"{pf.id}|{n}-viewer-failed")}
    ok = [n for n, s in srcs.items() if isinstance(s, dict)]
    if len(ok) < 2:
        st.caption("Side by side needs the slide viewer for two sections, and it is not "
                   "available here: " + "; ".join(f"{n}: {s}" for n, s in srcs.items()
                                                  if isinstance(s, str)) + ".")
        return
    show = st.multiselect("Sections", ok, default=ok[:3], max_selections=3, key=f"{pf.id}-side")
    if len(show) < 2:
        st.caption("Pick two or three sections.")
        return
    mpp = ", ".join(f"{n} {srcs[n]['mpp']:.3f}" for n in show)
    ratio = max(srcs[n]["mpp"] for n in show) / min(srcs[n]["mpp"] for n in show)
    st.caption((f"The sections' scales match ({mpp} µm per pixel)" if ratio <= 1.01 else
                f"The sections' scales differ by {ratio - 1:.1%} ({mpp} µm per pixel)")
               + ": zoom is linked by physical size, one screen pixel showing the same µm in "
               "each, and pan moves every section by the same distance. The sections are not "
               "registered to each other: linked pan does not line up their anatomy, and each "
               "is one plane through the block. Untick \"link pan and zoom\" to move them "
               "apart; click a tile to open it in that section's Spot panel above.")
    slide_viewer.show([srcs[n] for n in show], key=f"{pf.id}-compare", height=520,
                      on_change=lambda: viewer_event(pf.id, f"{pf.id}-compare"))


def render_example(page: Page, pf: PatientFile, result: dict | None) -> None:
    slide_tests = [t for t in pf.tests if t.workbench == "slides"]
    if result is None:
        page.title(PLANNED)
        with page.overview():
            st.warning("The public example region is not installed on this server, so there "
                       "is nothing to show here. A scanned H&E section of this tumor would open "
                       "the patient's own map.")
        with page.card():
            st.caption("The tissue head's card appears with a scored section.")
        cannot_see(page)
        with page.export(empty="Nothing to export: no section of this patient's tumor is "
                               "scored here."):
            pass
        return
    page.title("example slide", "placeholder cutoffs",
               "implemented, validated on held-out BCSS slides", colors=CHIP_COLORS)
    if slide_tests:
        st.markdown("**In this file:** " + "; ".join(
            f"{t.name} (month {t.month}): {t.result}" for t in slide_tests))
        st.info("The record holds the pathology report's text, not the slide image. Below, the "
                "slide workbench is shown on a public example region so that what it would do "
                "with this patient's slide is visible; nothing below is this patient's tissue. "
                "A scanned H&E section of this tumor would open the patient's own map.",
                icon="🔬")
    else:
        st.info("This file holds no slide image. Below, the slide workbench on a public example "
                "region; nothing below is this patient's tissue. A scanned H&E section of this "
                "tumor would open the patient's own map.", icon="🔬")

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

    with page.overview():
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
            faces = ", ".join(f"{LABELS.get(k, k).lower()} {v:.0%}"
                              for k, v in s["facing"].items())
            st.markdown(f"**What the front faces** (tiles touching the front, outside the "
                        f"tumor): {faces}. A 2D snapshot of this section: where the tumor is, "
                        "not where it is going.")
        row = st.container(horizontal=True)  # wraps on a narrow screen instead of cutting values
        row.metric("Tumor area (map)", f"{s['tumor_mm2']} mm²", width="content")
        row.metric("Front length", f"{s['front_length_mm']} mm", width="content")
        row.metric("Unsure share", f"{s['unsure_share']:.0%}", width="content")
        row.metric("Head accuracy (held out)", f"{head.get('accuracy', float('nan')):.0%}",
                   width="content")
        page.look_here([], empty="Nothing to look at: this is a public example region, not "
                                 "this patient's tissue.")

    cls_domain = [LABELS[k] for k in classes] + sorted(
        v for v in df["class"].unique() if v.startswith("excluded"))
    cls_range = [COLORS[k] for k in classes] + ["#bbbbbb"] * (len(cls_domain) - len(classes))
    with page.picture("Tissue map", caption="Hover a tile for its class probabilities. Each tile "
                      "is one score for 112 µm of tissue; the class is a model inference, "
                      "smoothed over a 3×3 neighbourhood."):
        left, right = st.columns([3, 2])
        with left:
            st.altair_chart(tile_chart(df, "class", alt.Scale(domain=cls_domain,
                                                              range=cls_range),
                                       "Tissue class", hover, res["grid_shape"]),
                            width="content")
        with right:
            if result["thumbnail"]:
                st.image(str(result["thumbnail"]), caption="The region (H&E, public TCGA-BRCA "
                         "slide)", width="stretch",
                         alt="H&E thumbnail of a public example region of a TCGA-BRCA slide")

    with page.details("Certainty map", f"{(df['certainty'] == 'unsure here').sum()} unsure "
                                       "tiles"):
        chips("placeholder cutoffs")
        nan = float("nan")
        st.caption(f"Unsure here = top probability below {CUTOFFS['unsure_below'][0]} "
                   f"({CUTOFFS['unsure_below'][2]}). On the held-out BCSS tiles the head was "
                   f"right on {head.get('accuracy_below_cutoff', nan):.0%} of tiles below the "
                   f"cutoff and {head.get('accuracy_at_or_above_cutoff', nan):.0%} at or above "
                   f"it ({head.get('share_below_cutoff', nan):.0%} of tiles below).")
        st.altair_chart(tile_chart(
            df, "certainty", alt.Scale(domain=["confident", "unsure here", "excluded"],
                                       range=["#2a78d6", "#f39c12", "#bbbbbb"]),
            "Certainty", hover, res["grid_shape"], 300), width="content")
    with page.details("Tumor region, front and zones", f"{s['front_length_mm']} mm of front"):
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
    excluded = df[df["qc"] != QC_OK]
    with page.details("Quality control", f"{len(excluded)} of {s['tiles']} tiles excluded"):
        chips("placeholder cutoffs")
        st.caption("Glass, pen ink and blur are checked per tile from texture and colour "
                   "measures (edge density, structure coverage, ink colour shares, Laplacian "
                   "variance). The cutoffs were set by eye on the team's colon slides and have "
                   "not been re-checked on breast tissue: placeholders. Blood, folds and stain "
                   "variation are not checked yet (planned).")
        if excluded.empty:
            st.markdown(f"No tile excluded ({s['tiles']} tiles, all passed).")
        else:
            cols = ["row", "col", "qc", "edges", "structure_cov", "ink_bluegreen", "ink_black",
                    "ink_red", "blur"]
            st.dataframe(excluded[cols], hide_index=True, width="stretch")

    with page.card():
        head_card(meta, classes)
        st.caption("On a patient's own scored section this workbench adds the direction of "
                   "invasion, breakaway candidates with the counting field, the immune pattern, "
                   "satellite islands, the risk map, a Spot panel per tile, search, review marks "
                   "and export (see a TCGA case with a scored slide).")
    cannot_see(page)
    with page.export(empty="Nothing to export: no section of this patient's tumor is scored; "
                           "the example region is public data, not this patient's."):
        pass


def render(file: PatientFile, version: int | None = None, test=None) -> None:
    page = Page("slides", file, test, version)
    slides = own_slides(file.id.split()[-1]) if file.kind == "TCGA-BRCA" else []
    if slides:
        render_own(page, file, slides, version)
    else:
        render_example(page, file, load_result(EXAMPLE))

if __name__ == "__main__":
    from muffle.workspace import synthetic_file

    st.set_page_config(page_title="Pathology slide workbench", layout="wide")
    st.text_input("Reviewer initials", key="reviewer", max_chars=5)  # the shell's field
    cases = json.loads((RESULTS / "cases.json").read_text()) if (RESULTS / "cases.json").exists() \
        else {}
    which = st.selectbox("File", ["SYNTHETIC-001 (example region)"]
                         + [f"Case {i} (own slides)" for i in cases])
    if which.startswith("Case"):
        from types import SimpleNamespace

        from muffle.workspace import case_file

        idx = int(which.split()[1])
        pf = case_file(SimpleNamespace(index=idx, site="site-0", percentile=50.0, group="medium",
                                       age=50.0, stage="II", layers=["clinical"], missing=[],
                                       mutations=None), slides=cases[str(idx)])
        render(pf)
    else:
        tl = json.loads((APP / "timeline_synthetic.json").read_text(encoding="utf-8"))
        render(synthetic_file(tl))

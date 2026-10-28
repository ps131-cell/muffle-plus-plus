# Built on muffle.workbench.slide_export (adapted from the team's Colon Tumor Front Analyzer, app/export.py): the map picture and the Markdown report, for a scan  # noqa: E501
"""Exports of one radiology study, made when someone clicks a download button
(docs/radiology.md §8):
  - map_png:         a labelled picture of the map in one view at the shown slice or view (title,
                     the image with the colour layer, the contours and pointers, the colour key,
                     a footer)
  - report_markdown: the study's report in Markdown, like the file's "Export this report
                     (Markdown)": what was imaged, the measurements with their evidence labels,
                     the look-here pointers with your marks, the change over time, every cutoff
                     with its source, the known failures
Both use a white page (for printing) and only restate what the page says.
"""

from __future__ import annotations

import io
import math
from datetime import date

import numpy as np
from PIL import Image, ImageDraw

from muffle.workbench import radiology as rad
from muffle.workbench import radiology_map as rm
from muffle.workbench.slide_export import _font, _table
from muffle.workbench.tile_map import hex_rgb

FOOTER = ("Model inferences on the patient's own public study (8-bit copies, not the diagnostic "
          "originals), not reviewed by a radiologist. Decision support only, not a diagnosis.")
NO_CALL = ("No BI-RADS assessment or diagnosis is made here; the BI-RADS category shown is the "
           "study's own structured report (observed).")


# ---------------------------------------------------------------- map picture

def _plain(text: str) -> str:
    """Characters the picture's bitmap font has (it has no minus sign or ≤)."""
    return text.replace("−", "-").replace("≤", "<=").replace("≥", ">=")


def _wrap(text: str, font, width: float) -> list[str]:
    """Words laid out in lines no wider than ``width`` pixels."""
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lines, line = [], ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if line and probe.textlength(trial, font=font) > width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + ([line] if line else [])


def map_picture(img: np.ndarray, m: rm.ScanMap, mode: str, opacity: float = 0.55, *,
                study: dict | None = None, values=None, markers=(), title: str = "",
                subtitle: str = "", legend=None) -> Image.Image:
    """The shown image with one view blended on top, the contours and pointers drawn, a title
    above and the colour key below, as a PIL image."""
    base = Image.fromarray(img).convert("RGBA")
    layer = Image.fromarray(rm.overlay_rgba(m, mode, values), "RGBA")
    layer.putalpha(layer.getchannel("A").point(lambda a: int(a * opacity)))
    pic = Image.alpha_composite(base, layer).convert("RGB")
    k = max(1, math.ceil(900 / pic.width))      # whole pixels stay whole: no smoothing
    pic = pic.resize((pic.width * k, pic.height * k), Image.NEAREST)
    d = ImageDraw.Draw(pic)
    if study is not None and m.kind == "MR" and mode in ("lesion", "kinetics"):
        for ln in rm.contour_lines(study, m.index):
            color = (rm.CANDIDATE_COLORS.get(ln["id"], rm.OTHER_CANDIDATE) if mode == "lesion"
                     else rm.CURVE_COLORS.get(ln["curve"], "#FFFFFF"))
            pts = [(x * k, y * k) for x, y in zip(ln["x"], ln["y"], strict=True)
                   if x is not None]
            if len(pts) > 2:
                d.line(pts, fill=hex_rgb(color), width=2)
            if mode == "lesion" and ln["ld"]:
                (x0, x1), (y0, y1) = ln["ld"]
                d.line([(x0 * k, y0 * k), (x1 * k, y1 * k)], fill=hex_rgb(rm.LD_COLOR), width=2)
    if study is not None and m.kind == "MR":
        y = study["region"]["limit_row_display"] * k
        for x in range(0, pic.width, 14):
            d.line([(x, y), (min(x + 7, pic.width), y)], fill=hex_rgb(rm.LIMIT_COLOR), width=1)
    font = _font(18)
    for p in markers:
        x, y = p["c"] * k, p["r"] * k
        col = hex_rgb(p["color"])
        text = _plain(p["label"])
        d.ellipse([x - 13, y - 13, x + 13, y + 13], outline=col, width=3)
        tw = d.textlength(text, font=font)
        d.rectangle([x + 16, y - 34, x + 24 + tw, y - 12], fill="white", outline=col, width=2)
        d.text((x + 20, y - 33), text, fill=col, font=font)

    pad, width = 28, max(pic.width + 56, 760)
    title_font, key_font, small = (_font(s) for s in (28, 19, 16))
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    rows, row, x = [], [], pad
    for text, color in legend if legend is not None else rm.legend_items(m, mode, study):
        text = _plain(text)
        w = 24 + 8 + probe.textlength(text, font=key_font) + 28
        if row and x + w > width - pad:
            rows.append(row)
            row, x = [], pad
        row.append((text, color[:7], x))
        x += w
    if row:
        rows.append(row)
    foot = _wrap(_plain(f"{FOOTER} {NO_CALL} {date.today():%Y-%m-%d}."), small, width - 2 * pad)
    header, key_h, footer = 92, 34 * len(rows) + 14, 24 * len(foot) + 18
    canvas = Image.new("RGB", (width, header + pic.height + key_h + footer), "white")
    c = ImageDraw.Draw(canvas)
    c.text((pad, 20), _plain(f"{title}  ·  {rm.MODES.get(mode, mode)} view"), fill=(20, 20, 20),
           font=title_font)
    c.text((pad, 58), _plain(subtitle), fill=(90, 90, 90), font=small)
    canvas.paste(pic, (pad, header))
    y = header + pic.height + 12
    for row in rows:
        for text, color, x in row:
            c.rounded_rectangle([x, y + 4, x + 24, y + 26], radius=5, fill=hex_rgb(color),
                                outline=(200, 200, 200))
            c.text((x + 32, y + 4), text, fill=(40, 40, 40), font=key_font)
        y += 34
    for n, line in enumerate(foot):
        c.text((pad, header + pic.height + key_h + 6 + 24 * n), line, fill=(90, 90, 90),
               font=small)
    return canvas


def map_png(img: np.ndarray, m: rm.ScanMap, mode: str, opacity: float = 0.55, **kw) -> bytes:
    buf = io.BytesIO()
    map_picture(img, m, mode, opacity, **kw).save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- the report (Markdown)

def _report_facts(rep: dict) -> str:
    return "; ".join(f"{name} {rep[key]}" for key, name in (
        ("procedure", "procedure"), ("laterality", "laterality"), ("birads", "BI-RADS"),
        ("pathology", "pathology"), ("er", "ER"), ("pr", "PR"), ("her2", "HER2")) if rep.get(key))


def report_markdown(patient: str, study: dict, *, look: list[dict], marks: dict,
                    overview: str = "", change: dict | None = None, notes: str = "",
                    square_marks: list[dict] | None = None,
                    known_failures: list[str] | tuple = ()) -> str:
    """The study's report, in the page's order: what was imaged, the overview, the
    measurements (or, for mammograms, the density opinions), the look-here pointers with the
    reviewer's marks, the change over time, every cutoff and its source, the known failures.
    ``look``: the page's look-here items (``workspace.look``); ``marks``: finding key ->
    {"mark", "by", "at", "what"}; ``change``: ``rad.pair_change``'s result or None."""
    s, src, rep = study["study"], study["source"], study.get("report", {})
    mri = study["modality"] == "MR"
    lines = [f"# Radiology study report: {study['kind']} · {s['date']}", "",
             f"Patient file {patient} · study {study['barcode']} of {s['date']} (de-identified "
             f"date) · {s.get('scanner', '')} · {src['collection']}, {src['license']}, "
             f"doi:{src['doi']} · exported {date.today():%Y-%m-%d}", "",
             f"> {FOOTER} {NO_CALL} Evidence labels: observed (the images, the study's "
             "structured report), model inference (every contour, measurement, curve, score and "
             "density class), placeholder (a cutoff nobody has validated yet).", ""]
    if study.get("example"):
        lines += [f"**{study['example']}**", ""]
    lines += ["## What was imaged (observed)", ""]
    if mri:
        d = study["display"]
        acq = d.get("acquisition", {})
        lines += [f"- {study['kind']}: {s.get('scanner', '?')} {s.get('field_t', '?')} T; "
                  f"{len(study['phases'])} phases: "
                  + ", ".join(p["label"] for p in study["phases"])
                  + f" ({study['phases'][1]['time_source']})",
                  f"- Acquired {acq.get('plane', 'axial')}; shown as {d['slices']} axial slices "
                  f"of {d['rows']} × {d['cols']} pixels at {d['pixel_mm']:g} mm (native "
                  f"{d['native_pixel_mm'][0]:g} mm, slices {d['slice_mm']:g} mm apart); 8-bit "
                  "copies: " + d.get("window", "")]
    else:
        lines += [f"- {study['kind']}: {s.get('scanner', '?')}; views "
                  + ", ".join(f"{v['key']} ({v['pixel_mm']:g} mm shown, "
                              f"{v['native_pixel_mm'][0]:g} mm native)" for v in study["views"])]
    lines += [f"- The study's structured report: {_report_facts(rep) or 'none'}", ""]
    if overview:
        lines += ["## Overview", "", overview, ""]
    if mri:
        lines += ["## Measurements (model inference: MedSAM contours on the seed rule's "
                  "candidates)", ""]
        lines += _table([{
            "candidate": c["id"], "side": c["side"],
            "longest diameter": f"{c['longest_diameter_mm']:g} mm (± "
                                f"{c['ld_uncertainty_mm']:g})",
            "craniocaudal": f"{c['cc_extent_mm']:g} mm",
            "volume": f"{c['volume_ml']:g} mL ({c['volume_range_ml'][0]:g}–"
                      f"{c['volume_range_ml'][1]:g})",
            "wash-in": f"{c['kinetics'].get('initial')} ({c['kinetics'].get('initial_pct')}%)",
            "delayed": f"{c['kinetics'].get('delayed')} ({c['kinetics'].get('delayed_pct'):+g}%)",
            "curve type": c["kinetics"].get("curve_type"),
            "unsure slices": f"{len(c['unsure_slices'])} of {len(c['per_slice'])}",
            "evidence": c["evidence"]} for c in study["candidates"]])
        lines += ["", "Kinetics: the mean signal inside each contour per phase on the original "
                  "data; curve cutoffs " + ", ".join(
                      f"{k} {rad.CUTOFFS[k][0]}" for k in ("initial_slow_below",
                                                           "initial_fast_above",
                                                           "delayed_band_pct"))
                  + f" ({rad.LITERATURE}). " + rad.KUHL + "."]
    else:
        lines += ["## Density and scores (model inference)", ""]
        monai = study.get("density_monai", {}).get("views", {})
        score = study.get("screening_score", {}).get("breasts", {})
        lines += _table([{
            "view": v["key"], "dense-pixel share": f"{v['dense']['dense_fraction']:.0%} "
                                                   "(placeholder rule)",
            "MONAI density": monai.get(v["key"], {}).get("density_class", "not run"),
            "mammoscreen (breast)": (f"{score[v['laterality']]['cancer']:.2g}, density "
                                     f"{score[v['laterality']]['density_class']}"
                                     if v["laterality"] in score else "not run"),
            "evidence": "model inference"} for v in study["views"]])
        lines += ["", "No lesion detector runs on the mammograms (none open, permissive and "
                  "CPU-ready was found): no candidates, no sizes."]
    done = sum(1 for x in look if marks.get(x["key"]))
    lines += ["", f"## Look here ({done} of {len(look)} marked by you)", ""]
    lines += _table([{"pointer": x["pointer"] or "", "what": x["what"], "why": x["why"],
                      "evidence": x["evidence"], "trust": x["trust"],
                      "your mark": (marks.get(x["key"]) or {}).get("mark", "")} for x in look])
    if square_marks:
        lines += ["", "Your marks on map squares:", ""] + [
            f"- {q['what']}: {q['mark']} · {q.get('by') or 'no initials'} · {q.get('at', '')}"
            for q in square_marks]
    if notes.strip():
        lines += ["", "## Your notes", "", notes.strip()]
    lines += ["", "## Change over time", ""]
    if change:
        if change.get("label"):
            lines += [f"**{change['label']}**", ""]
        lines += [change["what_changed"], ""]
        lines += _table([{"lesion": r["lesion"], "side": r["side"],
                          "longest diameter": (f"{r['change']['ld_mm'][0]:g} → "
                                               f"{r['change']['ld_mm'][1]:g} mm"
                                               if r["change"].get("ld_mm") else "—"),
                          "status": r["change"]["status"],
                          "alignment here": ("unreliable" if r["reliable"] is False else
                                             "checked" if r["reliable"] else "—"),
                          "evidence": r["evidence"]} for r in change["rows"]])
        lines += ["", "A comparison of two dates on model contours after a rigid alignment, "
                  "not a forecast and not a response call."]
    else:
        lines += [f"One {study['modality']} study date on file: no prior, so no change."]
    both = rad.CUTOFFS
    n_ph = sum(1 for v in both.values() if v[1] == rad.PLACEHOLDER)
    lines += ["", f"## Every cutoff and its source ({n_ph} of {len(both)} placeholders; the "
                  "kinetics cutoffs are literature values used as placeholders)", ""]
    lines += _table([{"cutoff": k, "value": v, "source": tag, "note": note}
                     for k, (v, tag, note) in both.items()])
    if known_failures:
        lines += ["", "## Known failures", ""] + [f"- {f}" for f in known_failures]
    lines += ["", "---", FOOTER, NO_CALL, ""]
    return "\n".join(lines)

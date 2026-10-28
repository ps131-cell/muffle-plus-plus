# Adapted from the team's Colon Tumor Front Analyzer (Ashby Prize Hackathon, Oct 2026): app/export.py  # noqa: E501
"""Exports of one scored section, made when someone clicks a download button
(docs/pathology.md §8):
  - map_png:         a labelled picture of the map in one view (title, map, colour key, footer)
  - report_markdown: the section's report in Markdown, like the file's "Export this report
                     (Markdown)": what was scored, the tissue mix, the look-here pointers with
                     your marks, your notes, the findings with their evidence labels, every
                     cutoff with its source, the known failures
Both use a white page (for printing) and only restate what the analysis says.
"""

from __future__ import annotations

import io
from datetime import date

from PIL import Image, ImageDraw, ImageFont

from muffle.workbench import invasion, tile_map
from muffle.workbench.slides import CUTOFFS, LABELS, PLACEHOLDER

FOOTER = ("Model inferences on the patient's own section, not reviewed by a pathologist. "
          "Decision support only, not a diagnosis.")


def _font(size: int):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10.1 has one bitmap size
        return ImageFont.load_default()


# ---------------------------------------------------------------- map picture

def map_picture(thumb, data, mode: str = "tissue", opacity: float = 0.55, focus=None,
                values=None, title: str = "", subtitle: str = "", legend=None) -> Image.Image:
    """The map with a title above and a colour key below, as a PIL image."""
    img = tile_map.map_image(thumb, data, mode, opacity, True, focus, values)
    if img.width < 1400:                        # make small thumbnails bigger, tile edges crisp
        img = img.resize((img.width * 2, img.height * 2), Image.NEAREST)

    pad, width = 28, img.width + 56
    title_font, font, small = (_font(s) for s in (30, 21, 18))
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    rows, row, x = [], [], pad                  # lay out the colour key in rows that fit
    for text, color in legend if legend is not None else tile_map.legend_items(data, mode):
        w = 24 + 8 + probe.textlength(text, font=font) + 28
        if row and x + w > width - pad:
            rows.append(row)
            row, x = [], pad
        row.append((text, color, x))
        x += w
    if row:
        rows.append(row)

    header, key_h, footer = 88, 36 * len(rows) + 14, 42
    canvas = Image.new("RGB", (width, header + img.height + key_h + footer), "white")
    d = ImageDraw.Draw(canvas)
    d.text((pad, 22), f"{title}  ·  {tile_map.MODES.get(mode, mode)} view", fill=(20, 20, 20),
           font=title_font)
    d.text((pad, 58), subtitle, fill=(90, 90, 90), font=small)
    canvas.paste(img, (pad, header))
    y = header + img.height + 12
    for row in rows:
        for text, color, x in row:
            d.rounded_rectangle([x, y + 4, x + 24, y + 28], radius=5,
                                fill=tile_map.hex_rgb(color), outline=(200, 200, 200))
            d.text((x + 32, y + 4), text, fill=(40, 40, 40), font=font)
        y += 36
    d.text((pad, canvas.height - 32), f"{FOOTER}  {date.today():%Y-%m-%d}.", fill=(90, 90, 90),
           font=small)
    return canvas


def map_png(thumb, data, mode: str = "tissue", opacity: float = 0.55, **kw) -> bytes:
    buf = io.BytesIO()
    map_picture(thumb, data, mode, opacity, **kw).save(buf, "PNG")
    return buf.getvalue()


# ---------------------------------------------------------------- the report (Markdown)

def _cell(v) -> str:
    return str(v).replace("|", "/").replace("\n", " ")


def _table(rows: list[dict]) -> list[str]:
    if not rows:
        return ["(none)"]
    keys = list(rows[0])
    return (["| " + " | ".join(keys) + " |", "|" + "---|" * len(keys)]
            + ["| " + " | ".join(_cell(r.get(k, "")) for k in keys) + " |" for r in rows])


def report_markdown(patient: str, slide: str, meta: dict, res: dict, *, marks: dict,
                    notes: str = "", bud_count=None, cutoffs: dict | None = None,
                    known_failures: list[str] = (), overview: str = "") -> str:
    """The section's report, in the order of the analyzer's PDF report and the workbench page."""
    s, n = res["summary"], res["numbers"]
    head, enc, sc = meta.get("head", {}), meta.get("encoder", {}), meta.get("scored", {})
    lines = [f"# Pathology slide report: {slide}", "",
             f"Patient file {patient} · section {slide} · {meta.get('source', '')} · exported "
             f"{date.today():%Y-%m-%d}", "",
             f"Scored: {sc.get('mode', '?')}, {sc.get('scored_tiles', '?')} of "
             f"{sc.get('tissue_tiles_total', '?')} tissue tiles of 112 µm"
             + (f"; {sc['skipped_tiles']} tiles outside the scored window were not scored"
                if sc.get("skipped_tiles") else "") + ". "
             f"Tissue head: {head.get('kind', '?')} on {enc.get('name', '?')} embeddings, "
             f"held-out accuracy {head.get('accuracy', float('nan')):.1%} on "
             f"{head.get('held_out', '?')}. Method version {meta.get('method_version', '?')}. "
             f"Status: {meta.get('status', '?')}.", "",
             f"> {FOOTER} Evidence labels: observed (tile positions, crops, the scan), model "
             "inference (every class, nucleus, region, front, zone and point), hypothesis (the "
             "direction of invasion).", ""]
    for note in meta.get("known_failures", []):
        lines += [f"**Known failure on this section:** {note}", ""]
    if overview:
        lines += ["## Overview (model inference)", "", overview, ""]
    lines += ["## Tissue mix (model inference)", ""]
    lines += [f"- {LABELS.get(k, k)}: {v:.0%}" for k, v in
              sorted(s["tissue_fractions"].items(), key=lambda kv: -kv[1])]
    lines += ["", "## Key findings", ""] + _table([
        {"finding": "Tumor area (map)", "value": f"{s['tumor_mm2']} mm²",
         "evidence": "model inference"},
        {"finding": "Main tumor", "value": f"{s['main_tumor_mm2']} mm²",
         "evidence": "model inference"},
        {"finding": "Front length", "value": f"{s['front_length_mm']} mm",
         "evidence": "model inference"},
        {"finding": "Infiltrative arcs", "value": f"{n['infiltrative_arcs']} of {n['arcs']}",
         "evidence": "hypothesis (placeholder cutoff)"},
        {"finding": "Breakaway candidates in the 0.785 mm² field",
         "value": "—" if n["buds_in_field"] is None else n["buds_in_field"],
         "evidence": "model inference, weak until validated"},
        {"finding": "Satellite islands", "value": n["islands"], "evidence": "model inference"},
        {"finding": "Immune pattern", "value": n["immune_pattern"],
         "evidence": "model inference (placeholder cutoffs)"},
        {"finding": "Tumor–stroma ratio", "value": n["tsr"],
         "evidence": "model inference (literature cutoff, colorectal)"},
        {"finding": "Unsure share", "value": f"{s['unsure_share']:.0%}" if s["unsure_share"]
         is not None else "—", "evidence": "model inference (placeholder cutoff)"},
        {"finding": "Excluded by quality control",
         "value": ", ".join(f"{v} {k}" for k, v in s["excluded"].items()) or "none",
         "evidence": "rules (placeholder cutoffs; one calibrated)"}])
    zones = invasion.tissue_by_zone(res["tiles"])
    lines += ["", "## Tissue by zone (model inference)", "",
              f"Class shares of the usable tiles per zone; {invasion.ZONE_PRECEDENT}.", ""]
    lines += _table([{"zone": z, "tiles": v["tiles"], **{
        LABELS[c]: "—" if v["shares"] is None else f"{v['shares'][c]:.0%}"
        for c in invasion.ZONE_CLASSES}, "other": "—" if v["other"] is None
        else f"{v['other']:.0%}"} for z, v in zones.items()])
    lines += ["", f"**Stroma and ECM3 (hypothesis).** {invasion.TSR_ECM3_HYPOTHESIS}"]
    if bud_count is not None:
        lines += ["", f"Your bud count in the counting field: {bud_count}."]
    reviewed = sum(1 for q in res["queue"] if marks.get((q["row"], q["col"])))
    lines += ["", f"## Look here ({reviewed} of {len(res['queue'])} marked by you)", ""]
    lines += _table([{"pointer": q["pointer"], "tile": f"r{q['row']}c{q['col']}",
                      "what": q["what"], "check by eye": q["check"], "evidence": q["evidence"],
                      "status": q["status"],
                      "your mark": (marks.get((q["row"], q["col"])) or {}).get("mark", "")}
                     for q in res["queue"]])
    other = {k: v for k, v in marks.items() if k not in {(q["row"], q["col"])
                                                          for q in res["queue"]}}
    if other:
        lines += ["", "Your other marks:", ""] + [
            f"- r{r}c{c}: {m.get('mark', '')} · {m.get('what', '')} · "
            f"{m.get('by') or 'no initials'} · {m.get('at', '')}"
            for (r, c), m in sorted(other.items())]
    if notes.strip():
        lines += ["", "## Your notes", "", notes.strip()]
    if res["arcs"]:
        lines += ["", "## Direction of invasion (hypothesis)", ""] + _table([
            {"arc": a["arc"], "length mm": a["length_mm"], "direction°": a["direction_deg"],
             "push": a["push"], "roughness": a["roughness"], "pattern": a["pattern"],
             "faces": LABELS.get(a["faces_top"], a["faces_top"]).lower()} for a in res["arcs"]])
    if res["islands"]:
        lines += ["", "## Satellite islands (model inference)", ""] + _table([
            {"island": i["island"], "area mm²": i["area_mm2"], "distance µm": i["distance_um"],
             "between": LABELS.get(i["between"], i["between"]).lower()} for i in res["islands"]])
    cards = res["risk"]["cards"]
    lines += ["", f"## Risk regions, level 2 or more ({len(cards)}; placeholder points)", ""]
    lines += _table([{"region": c["card"], "level": c["level"], "points": c["points"],
                      "mm²": c["mm2"], "tile": f"r{c['row']}c{c['col']}",
                      "features": ", ".join(c["features"])} for c in cards])
    both = {**CUTOFFS, **(cutoffs or {})}
    n_ph = sum(1 for v in both.values() if v[1] == PLACEHOLDER)
    lines += ["", f"## Every cutoff and its source ({n_ph} of {len(both)} placeholders)", ""]
    lines += _table([{"cutoff": k, "value": v, "source": tag, "note": note}
                     for k, (v, tag, note) in both.items()])
    if known_failures:
        lines += ["", "## Known failures", ""] + [f"- {f}" for f in known_failures]
    lines += ["", "---", f"{FOOTER}", ""]
    return "\n".join(lines)

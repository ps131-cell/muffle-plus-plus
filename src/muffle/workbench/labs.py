"""The blood and lab workbench's measurements (docs/WORKSPACE.md, "Blood and lab panels"): pure
functions over a patient record shaped like ``muffle.timeline.EVENTS``.

Every number here is plain arithmetic on observed values: no model, no fit, no imputation. The
markers, their units, the reference limits the record states, the 25% rise criterion and the
per-marker series come from ``muffle.workspace``; this module only reads them. Every finding is
**observed** and every threshold names its source: the record, the EGTM guidance (literature) or
a placeholder. An out-of-range or rising value is something to look at, not evidence of
progression by itself.
"""

from __future__ import annotations

import math
import re
from statistics import median

from muffle.report.case_tools import INFERENCE, OBSERVED
from muffle.workspace import IMPLEMENTED, MARKERS, PLANNED, REFERENCE_LIMITS, RISE, lab_series

WITHIN, ABOVE, RISING, FALLING = "within limit", "above limit", "rising", "falling"
FROM_RECORD = f"{IMPLEMENTED}, reference from the record"
LITERATURE = f"{IMPLEMENTED}, threshold from the literature"
PLACEHOLDER = f"{IMPLEMENTED}, threshold placeholder"
NO_REFERENCE = "none in the record"
GAP_MONTHS = 6  # PLACEHOLDER: a gap between two results of one marker worth a quality note
# The rise criterion is the European Group on Tumor Markers (EGTM) guidance on serial tumor
# marker measurements; a rise counts as confirmed only with a second specimen within a month.
RISE_SOURCE = (f"European Group on Tumor Markers (EGTM) guidance: a {RISE:.0%} rise over the "
               "previous value is a significant change (literature; Hayes et al., J Clin Oncol "
               "1986, doi:10.1200/JCO.1986.4.10.1542, saw a rise of at least 25% in 19 of 21 "
               "progressions)")
RISE_CAVEAT = "unconfirmed until a second specimen within a month"
CONFIRM_MONTHS = 1  # EGTM: the confirming specimen comes within a month
# Transient marker surge after a therapy change: the phenomenon is in the literature, the
# length of the caution window is not (placeholder).
FLARE_SOURCE = ("transient marker surge after chemotherapy starts, seen in responders: Kiang, "
                "Greenberg and Kennedy, Cancer 1990, doi:10.1002/1097-0142(19900115)65:2<193::"
                "aid-cncr2820650202>3.0.co;2-e; Sonoo and Kurebayashi, Surg Today 1996, "
                "doi:10.1007/BF00311583 (literature)")
FLARE_MONTHS = 2  # PLACEHOLDER: how long after a systemic therapy change to read with caution
KINETICS_POINTS = 3  # PLACEHOLDER: a log-linear fit over the last three values
HOOK_FACTOR = 10  # PLACEHOLDER: a value this many times the limit is worth an assay check
# A fall is the same ratio the other way round: the previous value at least RISE above this one,
# so a fall that undoes a flagged rise is flagged too (value / previous <= 1 / (1 + RISE)).
FALL = 1 / (1 + RISE) - 1
FALL_SOURCE = (f"the EGTM {RISE:.0%} rise criterion applied the other way round: a placeholder, "
               "not a guideline value")

RULES = {  # flag: (how it was decided, threshold source, status)
    ABOVE: ("the value is above the reference limit the record states",
            "the reference limit the record states", FROM_RECORD),
    RISING: (f"at least {RISE:.0%} above the previous value; {RISE_CAVEAT}",
             RISE_SOURCE, LITERATURE),
    FALLING: (f"the previous value was at least {RISE:.0%} above this one", FALL_SOURCE,
              PLACEHOLDER),
}

# what the spec's row names and the record lacks: shown as planned, never as results
PLANNED_PANELS = [
    ("CBC and differential", "no values in the record", PLANNED),
    ("Chemistry (liver, kidney, electrolytes)", "no values in the record", PLANNED),
    ("Unit and method checks against the assay", "the record states no method", PLANNED),
    ("Cross-marker view (CA 15-3 with CEA)", "CEA has no values in the record", PLANNED),
]


def results_table(events: list[dict], markers: dict = MARKERS,
                  limits: dict = REFERENCE_LIMITS) -> list[dict]:
    """One row per recorded marker value, in month order: value, unit, the reference interval
    and its source, flags, change from the previous value, rate per month, change from the
    nadir and the source event. Observed values, plain arithmetic."""
    rows = []
    for key, (name, unit) in markers.items():
        limit = limits.get(key)
        for r in lab_series(events, key):
            flags = []
            if limit and r["value"] > limit[0]:
                flags.append(ABOVE)
            if r.get("change", 0) >= RISE:
                flags.append(RISING)
            elif r.get("change", 0) <= FALL:
                flags.append(FALLING)
            rows.append({
                "marker": name, "key": key, "month": r["month"], "value": r["value"],
                "unit": unit,
                "reference": f"below {limit[0]:g} {unit}" if limit else NO_REFERENCE,
                "reference_source": limit[1] if limit else NO_REFERENCE,
                "flag": ", ".join(flags) or WITHIN, "flags": flags,
                "change": r.get("change"), "per_month": r.get("per_month"),
                "from_nadir": r.get("from_nadir"), "event": r["event"], "evidence": OBSERVED})
    rows.sort(key=lambda r: (r["month"], r["marker"]))
    n = 0  # pointers L1..Ln: one per flagged result, in month order, shared by every view
    for r in rows:
        n += bool(r["flags"])
        r["pointer"] = f"L{n}" if r["flags"] else ""
    return rows


def treatment_intervals(events: list[dict]) -> list[dict]:
    """Start month of each agent and the month it stops or changes, for marking on trends. The
    record holds treatment starts only, so an interval ends at the next treatment event or, with
    none, at the last event of the record; ``ended_by`` says which."""
    starts = [e for e in events if e.get("treatments")]
    last = max(e["month"] for e in events)
    out = []
    for i, e in enumerate(starts):
        nxt = starts[i + 1]["month"] if i + 1 < len(starts) else None
        for cls, agent in e["treatments"]:
            out.append({"agent": agent.lower(), "class": cls, "start": e["month"],
                        "end": last if nxt is None else nxt,
                        "ended_by": "end of the record: no stop recorded" if nxt is None
                        else f"next treatment event (month {nxt})", "event": e["text"]})
    return out


def quality_checks(events: list[dict], markers: dict = MARKERS,
                   limits: dict = REFERENCE_LIMITS) -> list[dict]:
    """Per marker: a unit recorded, values plausible (positive), a reference interval in the
    record, and no gap over ``GAP_MONTHS`` between results. One row per check and marker."""
    def row(check, marker, ok, detail, threshold):
        return {"check": check, "marker": marker, "ok": ok, "detail": detail,
                "threshold": threshold}

    out = []
    for key, (name, unit) in markers.items():
        series = lab_series(events, key)
        months = [r["month"] for r in series]
        steps = [b - a for a, b in zip(months, months[1:], strict=False)]
        none = "no results recorded"
        out.append(row("unit recorded", name, bool(unit), unit or "no unit for this marker",
                       "the record"))
        bad = [f"{r['value']:g} at month {r['month']}" for r in series if r["value"] <= 0]
        out.append(row("values plausible (positive)", name, not bad,
                       "; ".join(bad) if bad else (f"{len(series)} values" if series else none),
                       "arithmetic: a concentration is positive"))
        limit = limits.get(key)
        out.append(row("reference interval", name, bool(limit),
                       f"below {limit[0]:g} {unit} ({limit[1]})" if limit
                       else f"{NO_REFERENCE}: no above-limit flag is possible", "the record"))
        gaps = [f"month {a} to {a + s}" for a, s in zip(months, steps, strict=False)
                if s > GAP_MONTHS]
        out.append(row(f"no gap over {GAP_MONTHS} months", name, not gaps,
                       "; ".join(gaps) if gaps else
                       (f"largest gap {max(steps)} months" if steps else none),
                       f"{GAP_MONTHS} months is a placeholder"))
    return out


def look_here(events: list[dict], markers: dict = MARKERS,
              limits: dict = REFERENCE_LIMITS) -> list[dict]:
    """The flagged results as a queue, latest first, one item per flag: the rule, the threshold
    source, the evidence label and the status of the rule that raised it."""
    queue = []
    for r in sorted(results_table(events, markers, limits), key=lambda r: -r["month"]):
        for flag in r["flags"]:
            rule, threshold, status = RULES[flag]
            if flag == ABOVE:
                threshold = f"{r['reference']}, from {r['reference_source']}"
            queue.append({"pointer": r["pointer"], "marker": r["marker"], "key": r["key"],
                          "month": r["month"],
                          "value": r["value"], "unit": r["unit"], "flag": flag, "rule": rule,
                          "threshold": threshold, "evidence": OBSERVED, "status": status,
                          "event": r["event"]})
    return queue


def spot(row: dict, rows: list[dict], events: list[dict], limits: dict = REFERENCE_LIMITS) -> dict:
    """Everything about one value: its numbers, the events around it, the rules that fired and
    why, and what to check by eye before reading anything into it."""
    near = [e for e in events if abs(e["month"] - row["month"]) <= 2]
    fired = []
    for flag in row["flags"]:
        rule, threshold, status = RULES[flag]
        if flag == ABOVE:
            threshold = f"{row['reference']}, from {row['reference_source']}"
        fired.append({"flag": flag, "rule": rule, "threshold": threshold, "status": status})
    limit = limits.get(row["key"])
    checks = [
        "assay change: the record states no method or laboratory, so a change of assay between "
        "this value and the previous one cannot be ruled out from the record",
        "specimen quality: hemolysis, a delayed or mislabeled specimen; the record carries no "
        "specimen note",
    ]
    if limit and row["value"] >= HOOK_FACTOR * limit[0]:
        checks.append(f"hook effect: the value is over {HOOK_FACTOR}x the limit, where some "
                      "immunoassays under-read; a diluted re-run settles it (placeholder "
                      "factor)")
    else:
        checks.append(f"hook effect: not a concern here (under {HOOK_FACTOR}x the limit, a "
                      "placeholder factor)")
    history = [r for r in rows if r["key"] == row["key"]]
    return {"row": row, "events_around": near, "fired": fired, "check_by_eye": checks,
            "history": history, "evidence": OBSERVED}


def kinetics(rows: list[dict], key: str, limits: dict = REFERENCE_LIMITS,
             points: int = KINETICS_POINTS) -> dict:
    """Marker kinetics as **model inference** with a placeholder method: a log-linear fit over
    the last ``points`` values gives a rate, a doubling or halving time, and, if the current
    rate held, when the reference limit would be crossed. The uncertainty is the spread of the
    pairwise rates among those points. An extrapolation, never a prediction of progression."""
    series = [r for r in rows if r["key"] == key and r["value"] > 0]
    out = {"marker": MARKERS[key][0], "evidence": INFERENCE,
           "method": f"log-linear least squares over the last {points} values (placeholder "
                     "method, not validated)",
           "status": f"{IMPLEMENTED}, method placeholder",
           "caveat": "an extrapolation of the last values at their current rate, not a "
                     "prediction of progression"}
    if len(series) < points:
        out["note"] = f"needs at least {points} values, {len(series)} recorded"
        return out
    last = series[-points:]
    xs, ys = [r["month"] for r in last], [math.log(r["value"]) for r in last]
    xm, ym = sum(xs) / points, sum(ys) / points
    slope = sum((x - xm) * (y - ym) for x, y in zip(xs, ys, strict=True)) / sum(
        (x - xm) ** 2 for x in xs)
    pairwise = [(ys[j] - ys[i]) / (xs[j] - xs[i])
                for i in range(points) for j in range(i + 1, points)]
    lo, hi = min(pairwise), max(pairwise)
    out.update(months=(xs[0], xs[-1]), rate_per_month=slope, rate_range=(lo, hi),
               direction="rising" if slope > 0 else "falling" if slope < 0 else "flat")
    if slope:
        name = "doubling_months" if slope > 0 else "halving_months"
        out[name] = math.log(2) / abs(slope)
        same = [s for s in (lo, hi) if s * slope > 0]
        out[f"{name}_range"] = (math.log(2) / max(abs(s) for s in same),
                                math.log(2) / min(abs(s) for s in same)) if same else None
    limit = limits.get(key)
    v0, m0 = last[-1]["value"], last[-1]["month"]
    if limit and slope and (v0 - limit[0]) * slope < 0:  # heading towards the limit
        months = math.log(limit[0] / v0) / slope
        both = [math.log(limit[0] / v0) / s for s in (lo, hi) if s * slope > 0]
        out["crossing"] = {"months": months, "month": m0 + months,
                           "range_months": (min(both), max(both)) if both else None,
                           "direction": "below" if slope < 0 else "above",
                           "text": f"if the current rate held, the limit of {limit[0]:g} "
                                   f"{MARKERS[key][1]} would be crossed in about "
                                   f"{months:.0f} month{'s' if round(months) != 1 else ''}"}
    else:
        out["crossing"] = None
    horizon = 12
    if out["crossing"] is not None:
        horizon = max(1, min(12, math.ceil(out["crossing"]["months"])))
    out["band"] = [{"month": m0 + t, "value": v0 * math.exp(slope * t),
                    "lo": v0 * math.exp(min(lo, hi) * t), "hi": v0 * math.exp(max(lo, hi) * t)}
                   for t in range(0, horizon + 1)]
    return out


def confirmation_tracker(rows: list[dict]) -> list[dict]:
    """The EGTM confirmation of each flagged rise: confirmed when a second specimen within
    ``CONFIRM_MONTHS`` still stands at least RISE above the pre-rise value, withdrawn when it
    does not, otherwise unconfirmed with the month the specimen was due by."""
    out = []
    for key in {r["key"] for r in rows}:
        series = [r for r in rows if r["key"] == key]
        for i, r in enumerate(series):
            if RISING not in r["flags"]:
                continue
            previous = series[i - 1]["value"]
            due = r["month"] + CONFIRM_MONTHS
            nxt = series[i + 1] if i + 1 < len(series) else None
            item = {"pointer": r["pointer"], "marker": r["marker"], "month": r["month"],
                    "value": r["value"], "previous": previous, "due_by": due,
                    "evidence": OBSERVED, "source": RISE_SOURCE, "status": LITERATURE}
            if nxt is None:
                item.update(outcome="unconfirmed", detail=f"next specimen due by month {due}")
            elif nxt["month"] > due:
                item.update(outcome="unconfirmed", detail=f"no specimen within {CONFIRM_MONTHS} "
                            f"month of the rise; the next result came at month {nxt['month']} "
                            f"({nxt['value']:g}), too late to confirm it")
            elif nxt["value"] >= previous * (1 + RISE):
                item.update(outcome="confirmed", detail=f"month {nxt['month']}: "
                            f"{nxt['value']:g} is still at least {RISE:.0%} above {previous:g}")
            else:
                item.update(outcome="withdrawn", detail=f"month {nxt['month']}: "
                            f"{nxt['value']:g} is no longer {RISE:.0%} above {previous:g}")
            out.append(item)
    return sorted(out, key=lambda i: i["month"])


def therapy_windows(rows: list[dict], intervals: list[dict],
                    months: int = FLARE_MONTHS) -> list[dict]:
    """Values within ``months`` of a new systemic therapy: read with caution, since a transient
    surge after a therapy change is in the literature. The window length is a placeholder."""
    starts = {}
    for iv in intervals:
        starts.setdefault(iv["start"], []).append(iv["agent"])
    out = []
    for r in rows:
        for start, agents in sorted(starts.items()):
            if 0 <= r["month"] - start <= months:
                out.append({"pointer": r["pointer"], "marker": r["marker"], "month": r["month"],
                            "value": r["value"], "therapy": " + ".join(agents),
                            "started": start, "months_after": r["month"] - start,
                            "note": "early after a therapy change: interpret with caution",
                            "source": FLARE_SOURCE,
                            "window": f"{months} months is a placeholder", "evidence": OBSERVED,
                            "status": f"{IMPLEMENTED}, window placeholder"})
    return out


def baseline_band(rows: list[dict], key: str, min_points: int = 3) -> dict | None:
    """A within-person baseline: the median and min-max of the longest run of consecutive
    results with no rise or fall flag (placeholder definition), labeled by its months."""
    series = [r for r in rows if r["key"] == key]
    runs, run = [], []
    for r in series:
        if run and (RISING in r["flags"] or FALLING in r["flags"]):
            runs.append(run)
            run = []
        run.append(r)
    runs.append(run)
    best = max(runs, key=len) if runs else []
    if len(best) < min_points:
        return None
    values = [r["value"] for r in best]
    return {"marker": MARKERS[key][0], "months": (best[0]["month"], best[-1]["month"]),
            "n": len(best), "median": median(values), "lo": min(values), "hi": max(values),
            "method": "median and min-max of the longest run of consecutive results with no "
                      "rise or fall flag (placeholder definition)",
            "evidence": OBSERVED, "status": PLACEHOLDER}


def lead_lag(rows: list[dict], events: list[dict]) -> list[dict]:
    """Each imaging report against the last marker result before it: an observed fact of this
    record (which came first, by how many months), not a validated lead time."""
    out = []
    for e in events:
        if e["kind"] != "Imaging":
            continue
        before = [r for r in rows if r["month"] <= e["month"]]
        if not before:
            continue
        r = before[-1]
        gap = e["month"] - r["month"]
        progression = bool(e.get("progression"))
        when = ("in the same month as" if gap == 0 else
                f"{gap} month{'s' if gap != 1 else ''} before")
        read = "progression on imaging" if progression else "imaging that read stable"
        if r["flags"]:
            what = (f"{r['marker']} {r['flag']} at month {r['month']} came {when} the "
                    f"{read} at month {e['month']}")
        else:
            what = (f"{r['marker']} within the limit at month {r['month']} came {when} the "
                    f"{read} at month {e['month']}")
        what += (": concordant" if (progression == bool(r["flags"])) else ": discordant")
        out.append({"imaging_month": e["month"], "imaging": e["text"], "progression": progression,
                    "pointer": r["pointer"], "marker": r["marker"], "marker_month": r["month"],
                    "value": r["value"], "flag": r["flag"], "lead_months": gap, "what": what,
                    "evidence": OBSERVED,
                    "caveat": "an observed order of events in this record, not a validated "
                              "lead time"})
    return out


def cross_marker(rows: list[dict], a: str = "ca153", b: str = "cea") -> dict:
    """Two markers side by side, each with its own limit: at every month both were measured,
    a concordant rise, a discordant one, or neither. Correlation is not causation."""
    sa = {r["month"]: r for r in rows if r["key"] == a}
    sb = {r["month"]: r for r in rows if r["key"] == b}
    na, nb = MARKERS[a][0], MARKERS[b][0]
    pairs = []
    for month in sorted(set(sa) & set(sb)):
        ra, rb = sa[month], sb[month]
        up_a, up_b = RISING in ra["flags"], RISING in rb["flags"]
        relation = ("concordant rise" if up_a and up_b else
                    f"discordant: {na} rising, {nb} not" if up_a else
                    f"discordant: {nb} rising, {na} not" if up_b else "neither rising")
        pairs.append({"month": month, f"{a}_value": ra["value"], f"{a}_flag": ra["flag"],
                      f"{b}_value": rb["value"], f"{b}_flag": rb["flag"], "relation": relation})
    note = None
    if not sb:
        note = f"{nb} has no values in the record: the cross-marker view needs both markers"
    elif not sa:
        note = f"{na} has no values in the record: the cross-marker view needs both markers"
    elif not pairs:
        note = "the two markers were never measured in the same month"
    return {"markers": (na, nb), "pairs": pairs, "note": note, "evidence": OBSERVED,
            "caveat": "correlation is not causation: two markers rising together share a "
                      "cause only if the record shows one",
            "status": IMPLEMENTED if pairs else PLANNED}


def search(query: str, rows: list[dict], intervals: list[dict]) -> dict:
    """Plain-word search over the results: a flag ("above the limit", "rising", "falling",
    "within limit"), a treatment ("after palbociclib", "before letrozole"), a month
    ("month 11"), a pointer ("L5") or a marker name. Anything else gets an honest answer."""
    q = query.strip().lower()
    cant = ("this panel can't see that. It searches flags (above the limit, rising, falling, "
            "within limit), treatments (after palbociclib, before letrozole), months (month "
            "11), pointers (L5) and marker names.")
    if not q:
        return {"understood": False, "answer": "type a flag, a treatment, a month, a pointer or "
                                               "a marker", "rows": []}
    hits, what = None, None
    for flag in (ABOVE, RISING, FALLING, WITHIN):
        if flag.split()[0] in q:
            hits, what = [r for r in rows if flag in r["flag"]], f"results {flag}"
            break
    m = re.search(r"\b(after|before|on)\s+([a-z]+)", q)
    if hits is None and m:
        agent = m.group(2)
        starts = [iv["start"] for iv in intervals if iv["agent"] == agent]
        if starts:
            start = min(starts)
            if m.group(1) == "before":
                hits = [r for r in rows if r["month"] < start]
            else:
                hits = [r for r in rows if r["month"] >= start]
            what = f"results {m.group(1)} {agent} (started month {start})"
        else:
            return {"understood": False, "rows": [],
                    "answer": f"no treatment called {agent} in the record. " + cant}
    m = re.search(r"\bmonth\s*(-?\d+)", q)
    if hits is None and m:
        month = int(m.group(1))
        hits, what = [r for r in rows if r["month"] == month], f"results at month {month}"
    m = re.fullmatch(r"l(\d+)", q)
    if hits is None and m:
        hits, what = [r for r in rows if r["pointer"].lower() == q], f"pointer {q.upper()}"
    if hits is None:
        def squash(s):
            return re.sub(r"[\s\-]", "", s.lower())
        for key, (name, _) in MARKERS.items():
            if squash(name) in squash(q):
                hits, what = [r for r in rows if r["key"] == key], f"{name} results"
                break
    if hits is None:
        return {"understood": False, "answer": cant, "rows": []}
    answer = f"{len(hits)} {what}" + ("" if hits else " (none in the record)")
    return {"understood": True, "rows": hits,
            "answer": answer.replace("1 results", "1 result") if len(hits) == 1 else answer}


def report_markdown(file_id: str, rows: list[dict], queue: list[dict], checks: list[dict],
                    card: dict, kin: dict | None = None, tracker: list[dict] | None = None,
                    windows: list[dict] | None = None, band: dict | None = None,
                    lag: list[dict] | None = None, reviews: dict | None = None) -> str:
    """A Markdown report: the figures' numbers, the flags with their sources, every placeholder,
    and the review marks (``reviews`` maps ``muffle.workspace.finding_key`` names to
    {"what", "mark", "by", "at"}). Plain text for the clinician's record, nothing recommended."""
    L = [f"# Blood and lab workbench report: {file_id}", "",
         "All values observed; flags are plain arithmetic; kinetics are model inference with a "
         "placeholder method. Nothing here is a recommendation.", "", "## Results", "",
         "| pointer | marker | month | value | reference | flag | change | per month | "
         "from nadir |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        per_month = "" if r["per_month"] is None else f"{r['per_month']:+.1f}"
        L.append(f"| {r['pointer']} | {r['marker']} | {r['month']} | {r['value']:g} {r['unit']} "
                 f"| {r['reference']} | {r['flag']} | {_pct(r['change'])} | {per_month} | "
                 f"{_pct(r['from_nadir'])} |")
    L += ["", "## Flags and their sources", ""]
    for i in queue:
        L.append(f"- {i['pointer']} month {i['month']}, {i['marker']} {i['value']:g} {i['unit']}: "
                 f"{i['flag']} ({i['rule']}); threshold: {i['threshold']}; {i['evidence']}; "
                 f"{i['status']}")
    if kin and "rate_per_month" in kin:
        L += ["", "## Kinetics (model inference, placeholder method)", "",
              f"- {kin['marker']}, months {kin['months'][0]} to {kin['months'][1]}: rate "
              f"{kin['rate_per_month']:+.3f} log-units per month (pairwise range "
              f"{kin['rate_range'][0]:+.3f} to {kin['rate_range'][1]:+.3f}), {kin['direction']}"]
        for name in ("doubling_months", "halving_months"):
            if name in kin:
                rng = kin.get(f"{name}_range")
                L.append(f"- {name.replace('_', ' ')}: {kin[name]:.0f}"
                         + (f" (range {rng[0]:.0f} to {rng[1]:.0f})" if rng else ""))
        if kin["crossing"]:
            L.append(f"- {kin['crossing']['text']}")
        L.append(f"- {kin['caveat']}")
    if tracker:
        L += ["", "## EGTM confirmation of rises", ""]
        L += [f"- {t['pointer']} month {t['month']}: {t['outcome']}, {t['detail']}"
              for t in tracker]
    if windows:
        L += ["", "## Early after a therapy change", ""]
        L += [f"- {w['pointer'] or 'month ' + str(w['month'])}: {w['marker']} {w['value']:g}, "
              f"{w['months_after']} months after {w['therapy']} (window {w['window']})"
              for w in windows]
    if band:
        L += ["", "## Within-person baseline", "",
              f"- {band['marker']}: median {band['median']:g}, range {band['lo']:g} to "
              f"{band['hi']:g}, from {band['n']} results in months {band['months'][0]} to "
              f"{band['months'][1]} ({band['method']})"]
    if lag:
        L += ["", "## Markers against imaging (observed order in this record)", ""]
        L += [f"- {x['what']}" for x in lag]
    L += ["", "## Quality checks", ""]
    L += [f"- {'pass' if c['ok'] else 'ISSUE'}: {c['check']}, {c['marker']}: {c['detail']}"
          for c in checks]
    L += ["", "## Placeholders", ""]
    L += [f"- {t['name']}: {t['value']} ({t['source']})" for t in card["thresholds"]
          if t["status"] == PLACEHOLDER]
    if kin and "method" in kin:
        L.append(f"- kinetics method: {kin['method']}")
    if windows:
        L.append(f"- therapy caution window: {windows[0]['window']}")
    if band:
        L.append(f"- baseline band: {band['method']}")
    L += ["", "## Review marks", ""]
    L += [f"- {v['what']}: {v['mark']} ({v['by'] or 'no initials'}, {v['at']})"
          for v in (reviews or {}).values()] or ["- none"]
    L += ["", f"Rules: {card['name']}; validation: {card['validation']}."]
    return "\n".join(L) + "\n"


def _pct(v) -> str:
    return "" if v is None else f"{v:+.0%}"


def rules_card(markers: dict = MARKERS, limits: dict = REFERENCE_LIMITS) -> dict:
    """The model card for the rules: there is no model, only arithmetic on observed values."""
    thresholds = [{"name": f"{markers[k][0]} reference limit",
                   "value": f"below {v:g} {markers[k][1]}", "source": src, "status": FROM_RECORD}
                  for k, (v, src) in limits.items() if k in markers]
    thresholds += [
        {"name": "rise", "value": f"{RISE:.0%} above the previous value; {RISE_CAVEAT}",
         "source": RISE_SOURCE, "status": LITERATURE},
        {"name": "fall", "value": f"the previous value {RISE:.0%} above this one",
         "source": FALL_SOURCE, "status": PLACEHOLDER},
        {"name": "gap", "value": f"over {GAP_MONTHS} months between results",
         "source": "placeholder, not validated", "status": PLACEHOLDER},
    ]
    return {
        "name": "Lab result rules (blood and lab workbench)",
        "kind": "rules only: no model, no fit, plain arithmetic on observed values",
        "inputs": "each recorded value of a marker with its month and unit; the reference limit "
                  "the record states; the treatment starts in the record",
        "outputs": "flags (above limit, rising, falling, within limit); change from the "
                   "previous value, rate per month, change from the nadir; quality checks",
        "thresholds": thresholds,
        "evidence": OBSERVED,
        "validation": "none here: no cohort, no outcome, no assay study; the rise criterion "
                      "is the EGTM guidance, not validated on this record",
        "known_failures": [
            "a rise within the assay's noise is flagged like a real one: the rules know no "
            f"analytical variation, and a flagged rise is {RISE_CAVEAT}",
            "a changed assay method or laboratory shifts values without the record saying so: "
            "the checks only see what the record states",
            "an out-of-range value is not evidence of progression by itself: the rules read no "
            "imaging and no symptoms",
        ],
        "status": IMPLEMENTED,
    }

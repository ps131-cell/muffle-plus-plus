"""The blood and lab workbench's measurements (docs/WORKSPACE.md, "Blood and lab panels"): pure
functions over a patient record shaped like ``muffle.timeline.EVENTS``.

Every number here is plain arithmetic on observed values: no model, no fit, no imputation. The
markers, their units, the reference limits the record states, the placeholder rise rule and the
per-marker series come from ``muffle.workspace``; this module only reads them. Every finding is
**observed**. An out-of-range or rising value is something to look at, not evidence of
progression by itself.
"""

from __future__ import annotations

from muffle.report.case_tools import OBSERVED
from muffle.workspace import IMPLEMENTED, MARKERS, PLANNED, REFERENCE_LIMITS, RISE, lab_series

WITHIN, ABOVE, RISING, FALLING = "within limit", "above limit", "rising", "falling"
FROM_RECORD = f"{IMPLEMENTED}, reference from the record"
PLACEHOLDER = f"{IMPLEMENTED}, threshold placeholder"
NO_REFERENCE = "none in the record"
GAP_MONTHS = 6  # PLACEHOLDER: a gap between two results of one marker worth a quality note
# A fall is the same ratio the other way round: the previous value at least RISE above this one,
# so a fall that undoes a flagged rise is flagged too (value / previous <= 1 / (1 + RISE)).
FALL = 1 / (1 + RISE) - 1

RULES = {  # flag: (how it was decided, threshold source, status)
    ABOVE: ("the value is above the reference limit the record states",
            "the reference limit the record states", FROM_RECORD),
    RISING: (f"at least {RISE:.0%} above the previous value",
             f"{RISE:.0%} is a placeholder, not validated", PLACEHOLDER),
    FALLING: (f"the previous value was at least {RISE:.0%} above this one",
              f"{RISE:.0%} is a placeholder, not validated", PLACEHOLDER),
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
    return sorted(rows, key=lambda r: (r["month"], r["marker"]))


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
            queue.append({"marker": r["marker"], "month": r["month"], "value": r["value"],
                          "unit": r["unit"], "flag": flag, "rule": rule, "threshold": threshold,
                          "evidence": OBSERVED, "status": status, "event": r["event"]})
    return queue


def rules_card(markers: dict = MARKERS, limits: dict = REFERENCE_LIMITS) -> dict:
    """The model card for the rules: there is no model, only arithmetic on observed values."""
    thresholds = [{"name": f"{markers[k][0]} reference limit",
                   "value": f"below {v:g} {markers[k][1]}", "source": src, "status": FROM_RECORD}
                  for k, (v, src) in limits.items() if k in markers]
    thresholds += [
        {"name": "rise", "value": f"{RISE:.0%} above the previous value",
         "source": "placeholder, not validated", "status": PLACEHOLDER},
        {"name": "fall", "value": f"the previous value {RISE:.0%} above this one",
         "source": "placeholder, not validated", "status": PLACEHOLDER},
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
        "validation": "none: no cohort, no outcome, no assay study",
        "known_failures": [
            "a rise within the assay's noise is flagged like a real one: the rules know no "
            "analytical variation",
            "a changed assay method or laboratory shifts values without the record saying so: "
            "the checks only see what the record states",
            "an out-of-range value is not evidence of progression by itself: the rules read no "
            "imaging and no symptoms",
        ],
        "status": IMPLEMENTED,
    }

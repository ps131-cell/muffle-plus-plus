"""The blood and lab workbench's measurements (docs/WORKSPACE.md, "Blood and lab panels";
docs/labs.md): pure functions over a patient record shaped like ``muffle.timeline.EVENTS``.

Any analyte works: a record event carries a value under the analyte's key (``ca153``, ``alp``,
``anc`` ... from ``muffle.workbench.labs_reference``, or ``lab:<name>`` for one the table does not
list), and optionally ``meta[key]`` with the imported lab report's own reference interval
(``ref``: low, high, source) and, for an unlisted analyte, its ``name`` and ``unit``. Values are
in the table's canonical unit (the import converts them).

Every number is plain arithmetic on observed values: no model, no fit, no imputation. The derived
values (albumin-adjusted calcium, eGFR) are published equations and are labeled model inference.
Every threshold names its source: the record or the imported lab report, a reference laboratory's
published interval, the EGTM guidance or CTCAE v5.0 (literature and guideline), or a placeholder.
An out-of-range or rising value is something to look at, not evidence of progression by itself.
"""

from __future__ import annotations

import math
import re
from statistics import median

from muffle.memo import per_file
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workbench import labs_reference as ref
from muffle.workspace import (
    IMPLEMENTED,
    PLANNED,
    REFERENCE_LIMITS,
    RISE,
    card,
    finding_key,
    lab_series,
    look,
    record_events,
)

WITHIN, ABOVE, BELOW, RISING, FALLING = ("within limit", "above limit", "below limit", "rising",
                                         "falling")
LARGE_RISE, LARGE_FALL, GRADED = "large rise", "large fall", "CTCAE grade"
FROM_RECORD = f"{IMPLEMENTED}, reference from the record"
REFERENCE_LAB = f"{IMPLEMENTED}, interval from a reference laboratory"
LITERATURE = f"{IMPLEMENTED}, threshold from the literature"
GUIDELINE = f"{IMPLEMENTED}, grade from a guideline"
PLACEHOLDER = f"{IMPLEMENTED}, threshold placeholder"
NO_REFERENCE = "none in the record"
GAP_MONTHS = 6  # PLACEHOLDER: a gap between two results of one analyte worth a quality note
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
CHANGE = 0.3  # PLACEHOLDER: a change from the previous value worth a look, analytes other than
# tumor markers; a reference change value from biological variation would replace it (planned)
CHANGE_SOURCE = (f"{CHANGE:.0%} from the previous value: a placeholder, not a reference change "
                 "value from biological variation")
HYPOTHESIS_MONTHS = 3  # PLACEHOLDER: an imaging report this long after a lab value still counts
INTERVAL_SOURCE = "the reference interval shown with the value, and its source"

RULES = {  # flag: (how it was decided, threshold source, status); ABOVE and BELOW take theirs
    # from each value's own reference interval (the record, the lab report or the table)
    ABOVE: ("the value is above the upper reference limit", INTERVAL_SOURCE, FROM_RECORD),
    BELOW: ("the value is below the lower reference limit", INTERVAL_SOURCE, REFERENCE_LAB),
    RISING: (f"at least {RISE:.0%} above the previous value; {RISE_CAVEAT}",
             RISE_SOURCE, LITERATURE),
    FALLING: (f"the previous value was at least {RISE:.0%} above this one", FALL_SOURCE,
              PLACEHOLDER),
    LARGE_RISE: (f"at least {CHANGE:.0%} above the previous value (not a tumor marker)",
                 CHANGE_SOURCE, PLACEHOLDER),
    LARGE_FALL: (f"at least {CHANGE:.0%} below the previous value (not a tumor marker)",
                 CHANGE_SOURCE, PLACEHOLDER),
    GRADED: ("CTCAE v5.0 grade of a low blood count, counted from the lower limit", ref.CTCAE_V5,
             GUIDELINE),
}
UP, DOWN = (ABOVE, RISING, LARGE_RISE), (BELOW, FALLING, LARGE_FALL)

# what the spec's row names and this workbench does not do yet: shown as planned, never as results
PLANNED_PANELS = [
    ("Reference change values from biological variation (EuBIVAS)",
     "the published within-person variation was not read; change flags use placeholders",
     PLANNED),
    ("Assay or method change detection", "only a changed reference interval is seen; the "
                                         "record states no method", PLANNED),
    ("Derived ratios (e.g. neutrophil-to-lymphocyte)", "only where clinically established, each "
                                                       "with its source; none added yet", PLANNED),
    ("Age-banded adult intervals", "one adult band per analyte; calcium's 60-90 years band is not "
                                   "applied", PLANNED),
]


def analytes_in(events: list[dict]) -> list[str]:
    """The analyte keys the record holds, table analytes in the table's order, then the others."""
    keys = {k for e in events for k in e if k in ref.ANALYTES or k.startswith("lab:")}
    return ([k for k in ref.ANALYTES if k in keys]
            + sorted(k for k in keys if k not in ref.ANALYTES))


def _meta(events: list[dict], key: str) -> dict:
    return next((e["meta"][key] for e in reversed(events) if key in e.get("meta", {})), {})


def name_unit(events: list[dict], key: str) -> tuple[str, str]:
    """An analyte's name and unit: the table's, or what the import recorded for it."""
    a = ref.ANALYTES.get(key)
    if a:
        return a["name"], a["unit"]
    m = _meta(events, key)
    return m.get("name", key.removeprefix("lab:")), m.get("unit", "")


def with_derived(events: list[dict], sex: str | None = None, age: float | None = None) -> list:
    """``events`` plus the derived values: albumin-adjusted calcium for each month with calcium
    and albumin (Payne 1973), and eGFR for each creatinine when age and sex are known (2021
    CKD-EPI). Derived events carry ``derived`` and the inputs in their text; the result stays in
    month order (an import gives each value its own event, so calcium and albumin pair by
    month)."""
    out, pairs = list(events), {}
    for e in events:
        for k in ("calcium", "albumin"):
            if k in e:
                pairs.setdefault(e["month"], {})[k] = e[k]
    for month, p in pairs.items():
        if len(p) == 2:
            v = ref.adjusted_calcium(p["calcium"], p["albumin"])
            out.append({"month": month, "kind": "Lab", "ca_adj": v, "derived": True,
                        "text": f"calculated: calcium {p['calcium']:g} mg/dL − albumin "
                                f"{p['albumin']:g} g/dL + 4.0 (Payne 1973)"})
    for e in events:
        if "creatinine" in e and sex in ("female", "male") and age is not None:
            v = ref.egfr_ckd_epi_2021(e["creatinine"], age, sex == "female")
            out.append({"month": e["month"], "kind": "Lab", "egfr": v, "derived": True,
                        "text": f"calculated: 2021 CKD-EPI from creatinine {e['creatinine']:g} "
                                f"mg/dL, age {age:g}, {sex}"})
    return sorted(out, key=lambda e: e["month"])  # stable: the record's order within a month


def _reference(events: list[dict], key: str, month: int, sex: str | None,
               limits: dict) -> dict:
    """The reference interval for one value: the lab report's own (imported with it), the
    record's, the reference table's, or none."""
    e = next((e for e in events if e["month"] == month and key in e), {})
    own = e.get("meta", {}).get(key, {}).get("ref")
    if own:
        lo, hi, source = own
        return {"low": lo, "high": hi, "source": source, "status": FROM_RECORD}
    if key in limits:
        return {"low": None, "high": limits[key][0], "source": limits[key][1],
                "status": FROM_RECORD}
    iv = ref.interval(key, sex)
    if iv is None:
        return {"low": None, "high": None, "source": NO_REFERENCE, "status": None}
    a = ref.ANALYTES[key]
    return {"low": iv[0], "high": iv[1],
            "source": a["source"] + ("" if iv[2] in ("adults", sex) else f"; {iv[2]}"),
            "status": PLACEHOLDER if a["kind"] == ref.PLACEHOLDER else REFERENCE_LAB}


def _ref_text(lo, hi, unit: str) -> str:
    if lo is not None and hi is not None:
        return f"{lo:g}-{hi:g} {unit}"
    if hi is not None:
        return f"below {hi:g} {unit}"
    if lo is not None:
        return f"{lo:g} {unit} or above"
    return NO_REFERENCE


def _flag_text(flags: list[str], grade: int | None) -> str:
    return ", ".join(f"{GRADED} {grade}" if f == GRADED else f for f in flags) or WITHIN


def results_table(events: list[dict], markers: dict | None = None,
                  limits: dict = REFERENCE_LIMITS, sex: str | None = None,
                  age: float | None = None) -> list[dict]:
    """One row per recorded value of every analyte (``markers``: only these keys, as {key: (name,
    unit)}), in month order: value, unit, the reference interval with its source and status,
    flags, the CTCAE grade of a low count, change from the previous value, rate per month,
    change from the nadir and the source event. Observed values, plain arithmetic; derived
    values (see ``with_derived``) are model inference."""
    events = with_derived(events, sex, age)
    rows = []
    for key in (markers or analytes_in(events)):
        name, unit = (markers or {}).get(key) or name_unit(events, key)
        a = ref.ANALYTES.get(key, {})
        marker = bool(a.get("marker"))
        for r in lab_series(events, key):
            iv = _reference(events, key, r["month"], sex, limits)
            lo, hi, v, change = iv["low"], iv["high"], r["value"], r.get("change", 0)
            flags = [ABOVE] * (hi is not None and v > hi) + [BELOW] * (lo is not None and v < lo)
            grade = ref.ctcae_grade(key, v, lo)
            if marker and change >= RISE:
                flags.append(RISING)
            elif marker and change <= FALL:
                flags.append(FALLING)
            elif not marker and change >= CHANGE:
                flags.append(LARGE_RISE)
            elif not marker and change <= -CHANGE:
                flags.append(LARGE_FALL)
            if grade:
                flags.append(GRADED)
            derived = bool(a.get("derived"))
            rows.append({
                "marker": name, "key": key, "panel": a.get("panel", ref.UNLISTED),
                "tumor_marker": marker, "month": r["month"], "value": v, "unit": unit,
                "low": lo, "high": hi, "reference": _ref_text(lo, hi, unit),
                "reference_source": iv["source"], "reference_status": iv["status"],
                "flag": _flag_text(flags, grade), "flags": flags, "grade": grade,
                "change": r.get("change"), "per_month": r.get("per_month"),
                "from_nadir": r.get("from_nadir"), "event": r["event"], "derived": derived,
                "evidence": INFERENCE if derived else OBSERVED})
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


def quality_checks(events: list[dict], markers: dict | None = None,
                   limits: dict = REFERENCE_LIMITS, sex: str | None = None,
                   age: float | None = None) -> list[dict]:
    """Per measured analyte: a unit recorded, values plausible (positive), a reference interval
    and where it comes from, the interval unchanged across the series, and no gap over
    ``GAP_MONTHS``. Then the record as a whole: the EGTM panel (a MUC-1 marker with CEA), the
    sex for sex-specific intervals, and eGFR's inputs. One row per check."""
    def row(check, marker, ok, detail, threshold):
        return {"check": check, "marker": marker, "ok": ok, "detail": detail,
                "threshold": threshold}

    rows = results_table(events, markers, limits, sex, age)
    out = []
    for key in dict.fromkeys(r["key"] for r in rows):
        series = [r for r in rows if r["key"] == key]
        name, unit = series[0]["marker"], series[0]["unit"]
        months = [r["month"] for r in series]
        steps = [b - a for a, b in zip(months, months[1:], strict=False)]
        out.append(row("unit recorded", name, bool(unit), unit or "no unit for this analyte",
                       "the record"))
        bad = [f"{r['value']:g} at month {r['month']}" for r in series
               if r["value"] <= 0 and key != "ca_adj"]
        out.append(row("values plausible (positive)", name, not bad,
                       "; ".join(bad) if bad else f"{len(series)} values",
                       "arithmetic: a concentration or count is positive"))
        last = series[-1]
        has = last["reference"] != NO_REFERENCE
        out.append(row("reference interval", name, has,
                       f"{last['reference']} ({last['reference_source']})" if has
                       else f"{NO_REFERENCE}: no out-of-interval flag is possible",
                       "the record, the lab report or the reference table"))
        seen = list(dict.fromkeys(r["reference"] for r in series))
        out.append(row("reference interval unchanged", name, len(seen) < 2,
                       " → ".join(seen) + ": a changed interval may mean a changed method; compare "
                       "across it with care (EGTM)" if len(seen) > 1 else "one interval",
                       "EGTM: changing the method during serial monitoring needs care"))
        gaps = [f"month {a} to {a + s}" for a, s in zip(months, steps, strict=False)
                if s > GAP_MONTHS]
        out.append(row(f"no gap over {GAP_MONTHS} months", name, not gaps,
                       "; ".join(gaps) if gaps else
                       (f"largest gap {max(steps)} months" if steps else "one value"),
                       f"{GAP_MONTHS} months is a placeholder"))
    keys = {r["key"] for r in rows}
    if keys & set(ref.TUMOR_MARKERS) and markers is None:
        muc1 = keys & {"ca153", "ca2729"}
        missing = [n for n, ok in (("a MUC-1 marker (CA 15-3 or CA 27.29)", muc1),
                                   ("CEA", "cea" in keys)) if not ok]
        out.append(row("EGTM panel (a MUC-1 marker with CEA)", " and ".join(missing) or "panel",
                       not missing, ("never measured: " + " and ".join(missing)) if missing
                       else "both measured", ref.EGTM_PANEL))
    split = [ref.ANALYTES[k]["name"] for k in ref.ANALYTES
             if k in keys and "any" not in ref.ANALYTES[k]["interval"]]
    if split and sex not in ("female", "male"):
        out.append(row("sex for sex-specific intervals", ", ".join(split), False,
                       "not recorded: these are flagged against the wider of the female and male "
                       "intervals", "the reference table"))
    if "creatinine" in keys and (age is None or sex not in ("female", "male")):
        out.append(row("eGFR inputs (age and sex)", "eGFR (2021 CKD-EPI)", False,
                       "not recorded: no eGFR is calculated", ref.CKD_EPI_2021))
    return out


def _fired(r: dict) -> list[dict]:
    out = []
    for flag in r["flags"]:
        rule, threshold, status = RULES[flag]
        if flag in (ABOVE, BELOW):
            threshold = f"{r['reference']}, from {r['reference_source']}"
            status = r["reference_status"] or status
        if flag == GRADED:
            rule = f"CTCAE v5.0 grade {r['grade']} of a low count, counted from the lower limit"
        out.append({"flag": flag, "rule": rule, "threshold": threshold, "status": status})
    return out


def look_here(events: list[dict], markers: dict | None = None,
              limits: dict = REFERENCE_LIMITS, sex: str | None = None,
              age: float | None = None) -> list[dict]:
    """The flagged results as a queue, latest first, one item per flag: the rule, the threshold
    source, the evidence label and the status of the rule that raised it."""
    queue = []
    for r in sorted(results_table(events, markers, limits, sex, age), key=lambda r: -r["month"]):
        for f in _fired(r):
            queue.append({"pointer": r["pointer"], "marker": r["marker"], "key": r["key"],
                          "month": r["month"], "value": r["value"], "unit": r["unit"],
                          "flag": f["flag"] if f["flag"] != GRADED else r["flag"].split(", ")[-1],
                          "rule": f["rule"], "threshold": f["threshold"],
                          "evidence": r["evidence"], "status": f["status"], "event": r["event"]})
    return queue


def spot(row: dict, rows: list[dict], events: list[dict], limits: dict = REFERENCE_LIMITS) -> dict:
    """Everything about one value: its numbers, the events around it, the rules that fired and
    why, why the analyte matters here, and what to check by eye before reading anything into
    it."""
    near = [e for e in events if abs(e["month"] - row["month"]) <= 2]
    checks = [
        "assay change: the record states no method or laboratory, so a change of assay between "
        "this value and the previous one cannot be ruled out from the record",
        "specimen quality: hemolysis, a delayed or mislabeled specimen; the record carries no "
        "specimen note",
    ]
    if row["tumor_marker"]:
        if row["high"] and row["value"] >= HOOK_FACTOR * row["high"]:
            checks.append(f"hook effect: the value is over {HOOK_FACTOR}x the limit, where some "
                          "immunoassays under-read; a diluted re-run settles it (placeholder "
                          "factor)")
        else:
            checks.append(f"hook effect: not a concern here (under {HOOK_FACTOR}x the limit, a "
                          "placeholder factor)")
    if row["derived"]:
        checks.append(f"a calculated value ({row['event']}): it carries the error of its inputs "
                      "and the equation's own")
    a = ref.ANALYTES.get(row["key"])
    history = [r for r in rows if r["key"] == row["key"]]
    return {"row": row, "events_around": near, "fired": _fired(row), "check_by_eye": checks,
            "history": history, "evidence": row["evidence"],
            "why": (a["why"], a["why_source"]) if a else
            (f"{ref.UNLISTED}: flagged only against the interval its own lab report gave", "")}


def kinetics(rows: list[dict], key: str, limits: dict = REFERENCE_LIMITS,
             points: int = KINETICS_POINTS) -> dict:
    """Kinetics as **model inference** with a placeholder method: a log-linear fit over the last
    ``points`` values gives a rate, a doubling or halving time, and, if the current rate held,
    when the reference limit would be crossed. The uncertainty is the spread of the pairwise
    rates among those points. An extrapolation, never a prediction of progression."""
    series = [r for r in rows if r["key"] == key and r["value"] > 0]
    name = series[0]["marker"] if series else ref.ANALYTES.get(key, {}).get("name", key)
    out = {"marker": name, "evidence": INFERENCE,
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
    v0, m0, unit = last[-1]["value"], last[-1]["month"], last[-1]["unit"]
    limit = next((b for b in (last[-1]["high"], last[-1]["low"])
                  if b and slope and (v0 - b) * slope < 0), None)  # heading towards it
    if limit:
        months = math.log(limit / v0) / slope
        both = [math.log(limit / v0) / s for s in (lo, hi) if s * slope > 0]
        out["crossing"] = {"months": months, "month": m0 + months,
                           "range_months": (min(both), max(both)) if both else None,
                           "direction": "below" if slope < 0 else "above",
                           "text": f"if the current rate held, the limit of {limit:g} {unit} "
                                   f"would be crossed in about {months:.0f} "
                                   f"month{'s' if round(months) != 1 else ''}"}
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
    """Tumor-marker values within ``months`` of a new systemic therapy: read with caution, since
    a transient surge after a therapy change is in the literature. The window is a
    placeholder."""
    starts = {}
    for iv in intervals:
        starts.setdefault(iv["start"], []).append(iv["agent"])
    out = []
    for r in rows:
        if not r["tumor_marker"]:
            continue
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
    results with no change flag (placeholder definition), labeled by its months."""
    series = [r for r in rows if r["key"] == key]
    runs, run = [], []
    for r in series:
        if run and set(r["flags"]) & {RISING, FALLING, LARGE_RISE, LARGE_FALL}:
            runs.append(run)
            run = []
        run.append(r)
    runs.append(run)
    best = max(runs, key=len) if runs else []
    if len(best) < min_points:
        return None
    values = [r["value"] for r in best]
    return {"marker": best[0]["marker"], "months": (best[0]["month"], best[-1]["month"]),
            "n": len(best), "median": median(values), "lo": min(values), "hi": max(values),
            "method": "median and min-max of the longest run of consecutive results with no "
                      "rise or fall flag (placeholder definition)",
            "evidence": OBSERVED, "status": PLACEHOLDER}


def lead_lag(rows: list[dict], events: list[dict]) -> list[dict]:
    """Each imaging report against the last tumor-marker result before it: an observed fact of
    this record (which came first, by how many months), not a validated lead time."""
    rows = [r for r in rows if r["tumor_marker"]]
    out = []
    for e in events:
        if e.get("kind") != "Imaging":
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
        up = bool(set(r["flags"]) & {ABOVE, RISING})
        if r["flags"]:
            what = (f"{r['marker']} {r['flag']} at month {r['month']} came {when} the "
                    f"{read} at month {e['month']}")
        else:
            what = (f"{r['marker']} within the limit at month {r['month']} came {when} the "
                    f"{read} at month {e['month']}")
        what += (": concordant" if (progression == up) else ": discordant")
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
    na, nb = ref.ANALYTES[a]["name"], ref.ANALYTES[b]["name"]
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


# cross-analyte hypotheses: lab values that rose, next to an imaging report naming the site
SITE_HYPOTHESES = [
    {"site": "Bone", "keys": ("alp", "calcium", "ca_adj"),
     "what": "bone involvement can raise alkaline phosphatase (osteoblastic activity) and "
             "calcium (hypercalcemia of malignancy)",
     "source": f"{ref.STEWART_2005}; {ref.MAYO}, test ALP (8340), interpretation",
     "other": "other causes are not ruled out by the rule: liver disease (for ALP), healing "
              "fractures, primary hyperparathyroidism, dehydration (for calcium)"},
    {"site": "Liver", "keys": ("alt", "ast", "ggt", "bilirubin", "alp"),
     "what": "liver involvement can raise the liver enzymes and bilirubin",
     "source": f"{ref.ESMO_2011}; {ref.MAYO}, tests ALT (8362) and GGT (8677), interpretation",
     "other": "other causes are not ruled out by the rule: drug toxicity (several breast cancer "
              "drugs list hepatotoxicity), biliary obstruction, alcohol, viral hepatitis"},
]


def _sites(e: dict) -> set[str]:
    named = {s.title() for s in e.get("sites", [])}
    return named | {s["site"] for s in SITE_HYPOTHESES if s["site"].lower() in e["text"].lower()}


def cross_analyte(rows: list[dict], events: list[dict],
                  months: int = HYPOTHESIS_MONTHS) -> list[dict]:
    """**Hypotheses**, one per site and imaging report: the lab values of that site's analytes
    flagged up (above the interval or rising) at or after an imaging report naming the site, or
    up to ``months`` before it (placeholder window). Each names the report it refers to, the
    values (pointers), the literature and the other causes the rule cannot rule out. For ALP,
    a GGT in the same month says which source fits (Mayo's GGT interpretation)."""
    out = []
    imaging = [e for e in events if e.get("kind") == "Imaging"]
    for s in SITE_HYPOTHESES:
        reports = [e for e in imaging if s["site"] in _sites(e)]
        if not reports:
            continue
        up = [r for r in rows if r["key"] in s["keys"] and set(r["flags"]) & {ABOVE, RISING,
                                                                               LARGE_RISE}]
        for e in reports:
            hits = [r for r in up if r["month"] >= e["month"] - months]
            if not hits:
                continue
            ggt = {r["month"]: r for r in rows if r["key"] == "ggt"}
            notes = []
            for r in hits:
                if r["key"] == "alp" and r["month"] in ggt:
                    g = ggt[r["month"]]
                    notes.append(f"GGT {g['value']:g} at month {r['month']} is "
                                 + ("raised too: with ALP, this points to hepatobiliary disease"
                                    if ABOVE in g["flags"] else
                                    "within its interval: a raised ALP with normal GGT points "
                                    "to bone"))
            out.append({
                "site": s["site"], "imaging_month": e["month"], "imaging": e["text"],
                "values": [f"{r['pointer']} {r['marker']} {r['value']:g} {r['unit']} at month "
                           f"{r['month']} ({r['flag']})" for r in hits],
                "pointers": [r["pointer"] for r in hits],
                "hypothesis": f"{s['what']}: the imaging report at month {e['month']} names the "
                              f"{s['site'].lower()} ({e['text']})",
                "ggt": notes, "source": s["source"], "other_causes": s["other"],
                "window": f"values from {months} months before the report on (placeholder)",
                "evidence": HYPOTHESIS, "status": f"{IMPLEMENTED}, window placeholder"})
    return out


def search(query: str, rows: list[dict], intervals: list[dict]) -> dict:
    """Plain-word search over the results: a flag ("above the limit", "below", "rising", "large
    rise", "within limit"), a treatment ("after palbociclib", "before letrozole"), a month
    ("month 11"), a pointer ("L5"), an analyte or a panel ("liver", "blood count"). An analyte or
    panel not on file, or anything else, gets an honest answer naming what would show it."""
    q = query.strip().lower()
    cant = ("this panel can't see that. It searches flags (above or below the limit, rising, "
            "falling, large rise or fall, within limit), treatments (after palbociclib, before "
            "letrozole), months (month 11), pointers (L5), analytes and panels (liver, blood "
            "count).")
    if not q:
        return {"understood": False, "answer": "type a flag, a treatment, a month, a pointer, an "
                                               "analyte or a panel", "rows": []}
    hits, what = None, None
    flags = (ABOVE, BELOW, LARGE_RISE, LARGE_FALL, RISING, FALLING, WITHIN)
    for flag in [f for f in flags if f in q] or [f for f in flags if f.split()[0] in q
                                                 and f.split()[0] != "large"]:
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
        on_file = {r["key"]: r["marker"] for r in rows}
        def words(s):
            return re.sub(r"[-.()]", " ", s.lower()).split()

        qw = words(q)

        def said(n):  # a name of two letters only counts as the whole query
            nw = words(n)
            return (len(n) > 2 or nw == qw) and any(
                qw[i:i + len(nw)] == nw for i in range(len(qw)))

        named = [k for k, a in ref.ANALYTES.items()
                 if any(said(n) for n in {a["name"], *a["aliases"]})]
        named += [k for k, name in on_file.items() if k not in ref.ANALYTES
                  and name.lower() in q]
        if named:
            key = named[0]
            name = on_file.get(key) or ref.ANALYTES[key]["name"]
            if key in on_file:
                hits, what = [r for r in rows if r["key"] == key], f"{name} results"
            else:
                panel = ref.ANALYTES[key]["panel"]
                return {"understood": False, "rows": [],
                        "answer": f"this record has no {name} result, so this panel can't see "
                                  f"it: a {panel.lower()} panel would "
                                  f"({ref.ANALYTES[key]['why']})."}
    if hits is None:
        panel = next((p for p in ref.PANELS if p.split()[0].lower() in q
                      or (p == ref.BLOOD and ("cbc" in q or "blood" in q))), None)
        if re.search(r"lesion|metasta|scan|tumou?r size|imaging", q):
            return {"understood": False, "rows": [],
                    "answer": "lab results can't see lesions: imaging does (the imaging reports "
                              "are in the record). Markers against imaging, and the cross-analyte "
                              "hypotheses, set the two side by side."}
        if panel:
            members = [k for k, a in ref.ANALYTES.items() if a["panel"] == panel]
            got = [r for r in rows if r["key"] in members]
            if not got:
                names = ", ".join(ref.ANALYTES[k]["name"] for k in members
                                  if not ref.ANALYTES[k].get("derived"))
                return {"understood": False, "rows": [],
                        "answer": f"no {panel.lower()} values on file, so this panel can't see "
                                  f"that: a {panel.lower()} panel ({names}) would."}
            hits, what = got, f"{panel.lower()} results"
    if hits is None:
        return {"understood": False, "answer": cant, "rows": []}
    answer = f"{len(hits)} {what}" + ("" if hits else " (none in the record)")
    return {"understood": True, "rows": hits,
            "answer": answer.replace("1 results", "1 result") if len(hits) == 1 else answer}


def report_markdown(file_id: str, rows: list[dict], queue: list[dict], checks: list[dict],
                    card: dict, kin: dict | None = None, tracker: list[dict] | None = None,
                    windows: list[dict] | None = None, band: dict | None = None,
                    lag: list[dict] | None = None, reviews: dict | None = None,
                    hypotheses: list[dict] | None = None) -> str:
    """A Markdown report: the figures' numbers, the flags with their sources, the cross-analyte
    hypotheses, every placeholder, and the review marks (``reviews`` maps
    ``muffle.workspace.finding_key`` names to {"what", "mark", "by", "at"}). Plain text for the
    clinician's record, nothing recommended."""
    L = [f"# Blood and lab workbench report: {file_id}", "",
         "All values observed; flags are plain arithmetic; kinetics and calculated values (eGFR, "
         "adjusted calcium) are model inference. Nothing here is a recommendation.", "",
         "## Results", "",
         "| pointer | analyte | month | value | reference | flag | change | per month | "
         "from nadir |", "|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        per_month = "" if r["per_month"] is None else f"{r['per_month']:+.1f}"
        L.append(f"| {r['pointer']} | {r['marker']} | {r['month']} | {r['value']:g} {r['unit']} "
                 f"| {r['reference']} | {r['flag']} | {_pct(r['change'])} | {per_month} | "
                 f"{_pct(r['from_nadir'])} |")
    L += ["", "## Reference intervals and their sources", ""]
    L += [f"- {name}: {text} ({source})" for name, text, source in dict.fromkeys(
        (r["marker"], r["reference"], r["reference_source"]) for r in rows)]
    L += ["", "## Flags and their sources", ""]
    for i in queue:
        L.append(f"- {i['pointer']} month {i['month']}, {i['marker']} {i['value']:g} {i['unit']}: "
                 f"{i['flag']} ({i['rule']}); threshold: {i['threshold']}; {i['evidence']}; "
                 f"{i['status']}")
    if hypotheses:
        L += ["", "## Cross-analyte hypotheses (hypothesis, for clinician review)", ""]
        L += [f"- {h['hypothesis']}. Values: {'; '.join(h['values'])}. Source: {h['source']}. "
              f"{h['other_causes'].capitalize()}." for h in hypotheses]
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


def reference_table() -> list[dict]:
    """The reference table as rows for the page and docs/labs.md: analyte, panel, unit, the
    units it converts, the adult interval(s), source, and why it matters here with its source."""
    out = []
    for key, a in ref.ANALYTES.items():
        iv = a["interval"]
        text = "; ".join(f"{sex}: {_ref_text(lo, hi, a['unit'])}" for sex, (lo, hi) in iv.items())
        out.append({"analyte": a["name"], "key": key, "panel": a["panel"], "unit": a["unit"],
                    "converts": ", ".join(u for u in a["units"] if u != a["unit"]) or "none",
                    "interval": text.replace("any: ", "adults: "), "source": a["source"],
                    "status": PLACEHOLDER if a["kind"] == ref.PLACEHOLDER else REFERENCE_LAB,
                    "why it matters here": a["why"], "why: source": a["why_source"],
                    "derived": bool(a.get("derived"))})
    return out


def rules_card(markers: dict | None = None, limits: dict = REFERENCE_LIMITS) -> dict:
    """The rules card: there is no model, only arithmetic on observed values and two published
    equations."""
    thresholds = [{"name": f"{ref.ANALYTES[k]['name']} reference limit",
                   "value": f"below {v:g} {ref.ANALYTES[k]['unit']}", "source": src,
                   "status": FROM_RECORD}
                  for k, (v, src) in limits.items() if k in (markers or ref.ANALYTES)]
    thresholds += [
        {"name": "reference intervals", "value": f"{len(ref.ANALYTES)} analytes; an interval on "
                                                 "the imported lab report wins",
         "source": f"{ref.MAYO}, adult reference values ({ref.READ}); docs/labs.md",
         "status": REFERENCE_LAB},
        {"name": "rise (tumor markers)", "value": f"{RISE:.0%} above the previous value; "
                                                  f"{RISE_CAVEAT}",
         "source": RISE_SOURCE, "status": LITERATURE},
        {"name": "fall (tumor markers)", "value": f"the previous value {RISE:.0%} above this one",
         "source": FALL_SOURCE, "status": PLACEHOLDER},
        {"name": "large rise or fall (other analytes)", "value": f"{CHANGE:.0%} from the "
                                                                 "previous value",
         "source": CHANGE_SOURCE, "status": PLACEHOLDER},
        {"name": "low-count grades", "value": "CTCAE v5.0 grades 1-4 for neutrophils, white "
                                              "cells, platelets; 1-3 for hemoglobin",
         "source": ref.CTCAE_V5, "status": GUIDELINE},
        {"name": "adjusted calcium", "value": "calcium − albumin + 4.0 (mg/dL, g/dL)",
         "source": ref.PAYNE_1973, "status": LITERATURE},
        {"name": "eGFR", "value": "2021 CKD-EPI creatinine equation, needs age and sex",
         "source": ref.CKD_EPI_2021, "status": LITERATURE},
        {"name": "gap", "value": f"over {GAP_MONTHS} months between results",
         "source": "placeholder, not validated", "status": PLACEHOLDER},
        {"name": "cross-analyte window", "value": f"values from {HYPOTHESIS_MONTHS} months before "
                                                  "an imaging report on",
         "source": "placeholder, not validated", "status": PLACEHOLDER},
    ]
    return {
        "name": "Lab result rules (blood and lab workbench)",
        "kind": "rules only: no model, no fit, plain arithmetic on observed values and two "
                "published equations",
        "inputs": "each recorded value of an analyte with its month and unit; its reference "
                  "interval (the lab report, the record or the reference table); the treatment "
                  "starts and imaging reports in the record; age and sex when given",
        "outputs": "flags (above or below the interval, rising, falling, large rise or fall, "
                   "CTCAE grade, within limit); change from the previous value, rate per month, "
                   "change from the nadir; quality checks; cross-analyte hypotheses",
        "thresholds": thresholds,
        "evidence": OBSERVED,
        "validation": "none here: no cohort, no outcome, no assay study; the rise criterion "
                      "is the EGTM guidance, not validated on this record",
        "known_failures": [
            "a rise within the assay's noise is flagged like a real one: the rules know no "
            f"analytical variation, and a flagged rise is {RISE_CAVEAT}",
            "a changed assay method or laboratory shifts values without the record saying so: "
            "the checks only see what the record states",
            "the table's intervals are a reference laboratory's, for its methods: another "
            "laboratory's interval can differ, so an imported interval always wins",
            "an out-of-range value is not evidence of progression by itself: the rules read no "
            "imaging and no symptoms",
        ],
        "status": IMPLEMENTED,
    }


# --- the workbench contract (docs/WORKBENCHES.md §1): the patient file's overview ----------------

METHOD = "rules on observed values, no model (lab workbench rules)"
CARDS = 4  # the most cards a summary shows: tumor markers first, then flagged analytes


def file_rows(pf, version: int | None = None) -> list[dict]:
    """``results_table`` of a patient file as of report version ``version`` (the latest when
    None): the record's results and this session's imported ones, up to that version's month."""
    cutoff = pf.versions[-1 if version is None else version].month
    return results_table([e for e in record_events(pf)
                          if cutoff is not None and e["month"] <= cutoff])


def _threshold(r: dict) -> str:
    return "; ".join(f["threshold"] for f in _fired(r)) or \
        f"reference {r['reference']} ({r['reference_source']})"


def _opens(r: dict) -> tuple:
    return ("Tests", "Lab", r["month"], r["marker"])


def _focus(r: dict) -> dict:
    return {"marker": r["key"], "month": r["month"]}


@per_file
def summary(pf, version: int | None = None) -> dict:
    """The latest value of each tumor marker and of each analyte whose latest value is flagged,
    and the latest rise still waiting for its confirming specimen (EGTM)."""
    rows = file_rows(pf, version)
    latest = {r["key"]: r for r in rows}  # month order: the last value wins
    shown = sorted((r for r in latest.values() if r["tumor_marker"] or r["flags"]),
                   key=lambda r: (not r["tumor_marker"], not r["flags"]))[:CARDS]
    cards = [card(
        f"Latest {r['marker']}", f"{r['marker']} {r['value']:g} {r['unit']} at month "
        f"{r['month']}: {r['flag']}" + (f" ({r['pointer']})" if r["pointer"] else ""),
        r["evidence"], f"{r['marker']}, month {r['month']}", METHOD, _threshold(r), "strong",
        _opens(r), _focus(r)) for r in shown]
    waiting = [t for t in confirmation_tracker(rows) if t["outcome"] == "unconfirmed"]
    if waiting:
        t = waiting[-1]
        r = next(r for r in rows if r["pointer"] == t["pointer"])
        cards.append(card(
            "Rise not confirmed", f"{t['marker']} {t['previous']:g} → {t['value']:g} "
            f"{r['unit']} at month {t['month']} ({t['pointer']}): {t['detail']}", OBSERVED,
            f"{t['marker']}, month {t['month']}", METHOD, t["source"], "moderate", _opens(r),
            _focus(r)))
    note = None if cards else ("no lab results in this file" if not rows else
                               "no tumor marker and no flagged result")
    return {"workbench": "labs", "title": "Blood and lab", "cards": cards, "note": note}


@per_file
def queue(pf, version: int | None = None) -> list[dict]:
    """Each change flag (a tumor marker's rise with its EGTM confirmation outcome, a fall, a
    large change of another analyte), each CTCAE-graded low count, and each analyte's latest
    value when it is out of its interval; older out-of-interval values stay in the workbench's
    own queue."""
    rows = file_rows(pf, version)
    latest = {r["key"]: r for r in rows}
    outcome = {t["pointer"]: t for t in confirmation_tracker(rows)}
    out = []
    for r in rows:
        flags = set(r["flags"])
        if not flags & {RISING, FALLING, LARGE_RISE, LARGE_FALL, GRADED} and not (
                flags & {ABOVE, BELOW} and latest[r["key"]] is r):
            continue
        why = [f"{f['flag']}: {f['rule']} (threshold: {f['threshold']})" for f in _fired(r)]
        trust, consequence, t = "strong", 1, outcome.get(r["pointer"])
        if RISING in flags:
            trust = {"confirmed": "strong", "withdrawn": "moderate"}.get(
                t["outcome"] if t else "", "moderate")
            consequence = 2 if ABOVE in flags and (not t or t["outcome"] != "withdrawn") else 1
            if t:
                why.append(f"EGTM confirmation: {t['outcome']}, {t['detail']}")
        elif flags & {FALLING, LARGE_RISE, LARGE_FALL}:
            trust = "weak"  # placeholder change thresholds
        if GRADED in flags:  # a guideline grade: grade 3 or 4 may change care
            trust, consequence = "strong", max(consequence, 2 if (r["grade"] or 0) >= 3 else 1)
        out.append(look(
            r["pointer"], f"{r['marker']} {r['value']:g} {r['unit']} at month {r['month']}: "
            f"{r['flag']}", "; ".join(why), r["evidence"], trust, consequence, _opens(r),
            source=f"{r['marker']}, month {r['month']}",
            key=finding_key(pf, "lab", r["key"], r["month"]), focus=_focus(r),
            month=r["month"], threshold=_threshold(r)))
    return out

"""The ctDNA (liquid biopsy) monitor's rules (docs/ctdna.md): pure functions over a ctDNA series
shaped like ``muffle.timeline.CTDNA`` and a record shaped like ``muffle.timeline.EVENTS``.

No model: every call is a rule on the variant allele fractions (VAF), and every rule names its
source. The detection limit and the rising, falling and cleared criteria are placeholders. The
literature rules: a new or rising ESR1 mutation under an aromatase inhibitor is the trigger of
PADA-1 (Bidard et al., Lancet Oncol 2022) and the design of SERENA-6 (Bidard et al., N Engl J Med
2025), shown as evidence for clinician review and never as a switch recommendation; a variant
the tumor sequencing did not find, in a gene most often mutated in clonal hematopoiesis, may come
from blood cells (Razavi et al., Nat Med 2019; Jaiswal et al., N Engl J Med 2014), so it is
flagged and kept out of the tumor picture. SYNTHETIC-001's series is synthetic, and says so.
"""

from __future__ import annotations

from muffle.longitudinal import DRIVERS
from muffle.report.case_tools import HYPOTHESIS, OBSERVED
from muffle.workbench import labs
from muffle.workbench.genomics import AROMATASE_INHIBITORS
from muffle.workspace import IMPLEMENTED

DETECTED, NOT_DETECTED, NEW, RISING, FALLING, STABLE, CLEARED = (
    "detected", "not detected", "new", "rising", "falling", "stable", "cleared")
FLAGGED = (NEW, RISING, FALLING, CLEARED)  # calls that get a pointer C1..Cn
RISE_FACTOR = 2.0   # PLACEHOLDER: at least twice the previous detected VAF
FALL_FACTOR = 0.5   # PLACEHOLDER: at most half the previous detected VAF
CLEAR_SAMPLES = 2   # PLACEHOLDER: consecutive samples below the detection limit after detection
STABLE_RATIO = 1.5  # PLACEHOLDER: highest over lowest detected VAF of a "flat whatever the
# treatment" variant, across at least three samples
LITERATURE = f"{IMPLEMENTED}, rule from the literature"
PLACEHOLDER = f"{IMPLEMENTED}, threshold placeholder"
TUMOR_MATCHED, POSSIBLE_CH, NOT_IN_TUMOR = (
    "tumor-matched", "possible clonal hematopoiesis", "not in the tumor sequencing")
SYNTHETIC_NOTE = ("Synthetic series: written by hand for this synthetic patient, not measured; "
                  "no open serial breast ctDNA data exists.")

RAZAVI_2019 = ("Razavi et al., Nat Med 2019, doi:10.1038/s41591-019-0652-7: 53.2% of cell-free "
               "DNA mutations in patients with cancer (81.6% in controls) had features of clonal "
               "hematopoiesis; matched white-cell sequencing is needed to call a variant "
               "tumor-derived")
JAISWAL_2014 = ("Jaiswal et al., N Engl J Med 2014, doi:10.1056/NEJMoa1408617: the majority of "
                "clonal hematopoiesis variants occurred in DNMT3A, TET2 and ASXL1")
CH_GENES = ("DNMT3A", "TET2", "ASXL1")  # Jaiswal 2014; not exhaustive (Razavi 2019 found more)
PADA_1 = ("Bidard et al., Lancet Oncol 2022 (PADA-1), doi:10.1016/S1470-2045(22)00555-1: "
          "patients monitored during first-line aromatase inhibitor plus palbociclib, with newly "
          "present or increased ESR1 mutation in ctDNA and no synchronous progression, were "
          "randomized to switch to fulvestrant plus palbociclib or continue (median PFS 11.9 vs "
          "5.7 months)")
SERENA_6 = ("Bidard et al., N Engl J Med 2025 (SERENA-6), doi:10.1056/NEJMoa2502929: an ESR1 "
            "mutation emerging during first-line aromatase inhibitor plus a CDK4/6 inhibitor, "
            "found by ctDNA every 2 to 3 months; switch to camizestrant (median PFS 16.0 vs 9.2 "
            "months)")
SCHIAVON_2015 = ("Schiavon et al., Sci Transl Med 2015, doi:10.1126/scitranslmed.aac7551: ESR1 "
                 "mutations are rarely acquired during adjuvant aromatase inhibitor therapy (5.8%, "
                 "3 of 52) and commonly during aromatase inhibitor therapy for metastatic disease "
                 "(36.4%, 16 of 44)")

CANNOT_SEE = [
    "where the disease is: ctDNA has no location; imaging does",
    "a tumor that sheds little DNA: a value near or below the detection limit can be a false "
    "negative, so \"not detected\" is not \"absent\"",
    "a blood-cell variant from a tumor variant, without matched white-cell sequencing "
    "(clonal hematopoiesis; Razavi 2019)",
    "anything off the panel: other genes, copy number, fusions, expression",
    "tumor size: an allele fraction moves with shedding and with the cell-free DNA of other "
    "cells, not only with burden",
    "what to give: the trial evidence shown is for clinician review, never a recommendation",
]


def tumor_sequencing(events: list[dict], panel: tuple = DRIVERS) -> dict:
    """The record's tumor sequencing: the variants found ("GENE CHANGE"), the panel's genes and
    the months sequenced."""
    seq = [e for e in events if "mutations" in e]
    return {"found": {f"{g} {c}" for e in seq for g, c in e["mutations"]},
            "panel": tuple(panel), "months": [e["month"] for e in seq]}


def origin(variant: str, seq: dict) -> dict:
    """Where a ctDNA variant comes from, as far as this record can say: found in the tumor
    sequencing (tumor-matched); not found there and in a clonal-hematopoiesis gene (possible
    clonal hematopoiesis: out of the tumor picture until matched white-cell sequencing); or
    neither (kept, origin unconfirmed). Every variant keeps the caveat."""
    gene = variant.split()[0]
    when = ", ".join(f"month {m}" for m in seq["months"]) or "never"
    if variant in seq["found"]:
        return {"origin": TUMOR_MATCHED, "in_picture": True, "source": RAZAVI_2019,
                "why": f"found in the tumor sequencing ({when}); without matched white-cell "
                       "sequencing it is still not proven tumor-derived in blood"}
    tested = (f"{gene} is on the tumor panel and was not found ({when})" if gene in seq["panel"]
              else f"{gene} is not on the tumor panel, so the tissue cannot say")
    if gene in CH_GENES:
        return {"origin": POSSIBLE_CH, "in_picture": False, "source": f"{RAZAVI_2019}; "
                f"{JAISWAL_2014}",
                "why": f"{tested}; {gene} is among the genes most often mutated in clonal "
                       "hematopoiesis: excluded from the tumor picture until matched white-cell "
                       "sequencing"}
    return {"origin": NOT_IN_TUMOR, "in_picture": True, "source": RAZAVI_2019,
            "why": f"{tested}: it may have emerged after the biopsy, sit in another lesion, or "
                   "come from blood cells; kept in the tumor picture, origin unconfirmed"}


def therapy_at(month: float, intervals: list[dict]) -> list[str]:
    """The agents whose interval covers ``month`` (``labs.treatment_intervals``: the record holds
    starts only, so an interval ends at the next treatment event)."""
    return [iv["agent"] for iv in intervals if iv["start"] <= month
            and (month < iv["end"] or "end of the record" in iv["ended_by"])]


def series_rows(series: dict, events: list[dict] = (), panel: tuple = DRIVERS) -> list[dict]:
    """One row per variant per sample, in month order: the VAF against the detection limit, the
    call with its rule, the therapy at the time and the variant's origin. Pointers C1..Cn on
    every new, rising, falling or cleared call."""
    lod, seq = series["detection_limit"], tumor_sequencing(list(events), panel)
    intervals = labs.treatment_intervals(list(events)) if events else []
    rows = []
    for variant in series["variants"]:
        where = origin(variant, seq)
        prev, seen, below, earlier = None, False, 0, False
        for s in sorted(series["samples"], key=lambda s: s["month"]):
            vaf = s["vaf"].get(variant)
            detected = vaf is not None and vaf >= lod
            ratio = None
            if not detected:
                below += seen
                call = CLEARED if seen and below >= CLEAR_SAMPLES else NOT_DETECTED
                rule = (f"below the detection limit at {below} consecutive samples after "
                        f"detection ({CLEAR_SAMPLES} needed)" if call == CLEARED else
                        f"below the detection limit; {below} of {CLEAR_SAMPLES} consecutive "
                        "samples needed to call it cleared" if seen else
                        "below the detection limit")
            elif not seen or below:
                call = NEW if earlier else DETECTED
                rule = (f"detected after {below} sample(s) below the limit" if below else
                        "detected after earlier samples below the limit" if earlier
                        else "detected at the first sample")
            else:
                ratio = vaf / prev
                call = (RISING if ratio >= RISE_FACTOR else FALLING if ratio <= FALL_FACTOR
                        else STABLE)
                rule = (f"{ratio:.1f}x the previous detected value (rising at {RISE_FACTOR:g}x "
                        f"or more, falling at {FALL_FACTOR:g}x or less)")
            if detected:
                prev, seen, below = vaf, True, 0
            earlier = True
            rows.append({
                "variant": variant, "gene": variant.split()[0], "month": s["month"], "vaf": vaf,
                "detected": detected, "lod": lod, "call": call, "rule": rule, "ratio": ratio,
                "status": PLACEHOLDER, "therapy": therapy_at(s["month"], intervals),
                "origin": where["origin"], "in_picture": where["in_picture"],
                "evidence": OBSERVED, "synthetic": bool(series.get("synthetic"))})
    rows.sort(key=lambda r: (r["month"], r["variant"]))
    n = 0
    for r in rows:
        n += r["call"] in FLAGGED
        r["pointer"] = f"C{n}" if r["call"] in FLAGGED else ""
    return rows


def variants(rows: list[dict], events: list[dict] = (), panel: tuple = DRIVERS) -> list[dict]:
    """One line per variant: origin and why, latest call, detected range, and whether its
    fraction stayed flat whatever the treatment (the clonal-hematopoiesis pattern; placeholder
    ratio)."""
    seq = tumor_sequencing(list(events), panel)
    out = []
    for v in dict.fromkeys(r["variant"] for r in rows):
        series = [r for r in rows if r["variant"] == v]
        found = [r["vaf"] for r in series if r["detected"]]
        therapies = {tuple(r["therapy"]) for r in series if r["detected"]}
        flat = (len(found) >= 3 and max(found) / min(found) < STABLE_RATIO)
        where = origin(v, seq)
        out.append({
            "variant": v, **where, "latest": series[-1]["call"],
            "latest_month": series[-1]["month"], "latest_vaf": series[-1]["vaf"],
            "detected": f"{min(found):g}-{max(found):g}% in {len(found)} of {len(series)} "
                        "samples" if found else f"never detected in {len(series)} samples",
            "flat": flat, "pattern": (f"flat whatever the treatment ({min(found):g}-"
                                      f"{max(found):g}% across {len(therapies)} treatment "
                                      f"periods; ratio under {STABLE_RATIO:g}, a placeholder)"
                                      if flat else "moves with time and treatment"),
            "calls": [f"{r['pointer']} month {r['month']}: {r['call']}" for r in series
                      if r["pointer"]]})
    return out


def esr1_rule(rows: list[dict], events: list[dict]) -> list[dict]:
    """The PADA-1 / SERENA-6 rule on every new or rising ESR1 call: whether an aromatase
    inhibitor was recorded at that sample, and how this record differs from the trials'
    situation. Evidence for clinician review, never a recommendation to switch."""
    events = list(events)
    starts = [e for e in events if e.get("treatments")]
    out = []
    for r in rows:
        if r["gene"] != "ESR1" or r["call"] not in (NEW, RISING):
            continue
        ai = [a for a in r["therapy"] if a in AROMATASE_INHIBITORS]
        prog = [e["month"] for e in events if e.get("progression") and e["month"] <= r["month"]]
        nxt = next((e for e in events if e.get("progression") and e["month"] > r["month"]), None)
        then = next((e for e in starts if e["month"] > r["month"]), None)
        on = next((e["text"] for e in reversed(starts) if e["month"] <= r["month"]), "none")
        item = {"pointer": r["pointer"], "variant": r["variant"], "month": r["month"],
                "vaf": r["vaf"], "call": r["call"], "therapy": " + ".join(r["therapy"]) or "none",
                "applies": bool(ai), "evidence": HYPOTHESIS,
                "use": "evidence for clinician review, never a recommendation to switch"}
        if not ai:
            item.update(
                what=f"{r['variant']} {r['call']} at month {r['month']} on "
                     f"{item['therapy']}: not under an aromatase inhibitor, so the PADA-1 / "
                     "SERENA-6 trigger does not apply; the call stands by this panel's "
                     "placeholder rule",
                compare=[], sources=[PADA_1, SERENA_6], status=LITERATURE)
            out.append(item)
            continue
        item.update(
            what=f"{r['variant']} {r['call']} at month {r['month']} while on {', '.join(ai)}: "
                 "the situation PADA-1 and SERENA-6 tested (a new or rising ESR1 mutation in "
                 "blood under an aromatase inhibitor)",
            compare=[
                ("Setting", "first-line therapy for advanced disease: an aromatase inhibitor "
                            "with palbociclib (PADA-1) or a CDK4/6 inhibitor (SERENA-6)",
                 f"this record: {on}"),
                ("Progression", "no synchronous progression (PADA-1 randomized only those)",
                 f"imaging read progression at month {prog[-1]}" if prog else
                 "no progression on imaging recorded at or before this sample"
                 + (f" (the next, at month {nxt['month']})" if nxt else "")),
                ("Monitoring", "serial ctDNA, every 2 to 3 months in SERENA-6",
                 "this panel's synthetic series, detection limit "
                 f"{r['lod']:g}% (placeholder)"),
                ("Adjuvant or metastatic", "ESR1 is acquired mostly under an aromatase inhibitor "
                                           "for metastatic disease (Schiavon 2015)",
                 "this record's letrozole is adjuvant" if "djuvant" in on else
                 "see the setting above"),
                ("What the record shows next", "",
                 f"month {then['month']}: {then['text']}" if then else "no later treatment"),
            ],
            sources=[PADA_1, SERENA_6, SCHIAVON_2015], status=LITERATURE)
        out.append(item)
    return out


def low_shedding(rows: list[dict]) -> list[dict]:
    """Samples in which no tumor-matched variant was detected: there, the absence of every other
    variant says little (low tumor shedding gives false negatives)."""
    matched = {r["variant"] for r in rows if r["origin"] == TUMOR_MATCHED}
    out = []
    for month in sorted({r["month"] for r in rows}):
        here = [r for r in rows if r["month"] == month and r["variant"] in matched]
        if matched and not any(r["detected"] for r in here):
            out.append({"month": month, "what": f"month {month}: no tumor-matched variant detected "
                                                "(" + ", ".join(sorted(matched)) + "): a "
                                                "\"not detected\" here may be low shedding, not "
                                                "absence", "evidence": OBSERVED})
    return out


def lead_lag(rows: list[dict], events: list[dict], lab_rows: list[dict]) -> list[dict]:
    """Each new or rising call against the next imaging progression and the next CA 15-3 value
    flagged above its limit or rising: the observed order of events in this record, not a
    validated lead time."""
    out = []
    marker = [r for r in lab_rows if r["key"] == "ca153"
              and set(r["flags"]) & {labs.ABOVE, labs.RISING}]
    for r in rows:
        if r["call"] not in (NEW, RISING):
            continue
        prog = next((e for e in events if e.get("progression") and e["month"] >= r["month"]),
                    None)
        ca = next((x for x in marker if x["month"] >= r["month"]), None)
        bits = []
        if prog:
            bits.append(_gap(prog["month"] - r["month"]) + f" the progression on imaging at "
                        f"month {prog['month']}")
        if ca:
            bits.append(_gap(ca["month"] - r["month"]) + f" CA 15-3 {ca['flag']} at month "
                        f"{ca['month']} ({ca['pointer']})")
        out.append({"pointer": r["pointer"], "variant": r["variant"], "month": r["month"],
                    "call": r["call"],
                    "imaging_month": prog["month"] if prog else None,
                    "ca153_month": ca["month"] if ca else None,
                    "what": f"{r['variant']} {r['call']} at month {r['month']} came "
                            + (" and ".join(bits) if bits else "with no later progression on "
                               "imaging and no later CA 15-3 flag in the record"),
                    "evidence": OBSERVED,
                    "caveat": "an observed order of events in this record, not a validated lead "
                              "time"})
    return out


def _gap(months: float) -> str:
    return ("in the same month as" if months == 0 else
            f"{months:g} month{'s' if months != 1 else ''} before")


def spot(row: dict, rows: list[dict], events: list[dict], lab_rows: list[dict]) -> dict:
    """One point in full: its value against the limit, the call and its rule, the variant's
    origin, the therapy at the time, the events around it, the nearest CA 15-3 at or before it,
    and what to check by eye."""
    ca = [x for x in lab_rows if x["key"] == "ca153" and x["month"] <= row["month"]]
    checks = [
        "clonal hematopoiesis: without matched white-cell sequencing, a blood-cell variant can "
        "look like a tumor variant (Razavi 2019)",
        f"detection limit: {row['lod']:g}% is a placeholder, not an assay's validated limit; "
        "values near it are the least certain",
        "low tumor shedding: a low or undetected value can be a false negative",
        "allele fraction is not tumor size: it also moves with shedding and with the cell-free "
        "DNA of other cells",
    ]
    if row["synthetic"]:
        checks.append("synthetic value: written by hand, not measured")
    return {"row": row, "history": [r for r in rows if r["variant"] == row["variant"]],
            "events_around": [e for e in events if abs(e["month"] - row["month"]) <= 2],
            "ca153": ca[-1] if ca else None, "check_by_eye": checks, "evidence": OBSERVED}


def queue(rows: list[dict], vs: list[dict], rule: list[dict], shed: list[dict]) -> list[dict]:
    """What to look at, latest first: the ESR1 rule items, new and rising calls, possible clonal
    hematopoiesis, and samples where low shedding limits a negative."""
    out = [{"pointer": i["pointer"], "month": i["month"], "what": i["what"],
            "why": "PADA-1 / SERENA-6 (literature)" if i["applies"] else "ESR1 rising, rule n/a",
            "evidence": HYPOTHESIS, "status": i["status"]} for i in rule]
    out += [{"pointer": r["pointer"], "month": r["month"],
             "what": f"{r['variant']} {r['call']}: {r['vaf']:g}%", "why": r["rule"],
             "evidence": OBSERVED, "status": r["status"]}
            for r in rows if r["call"] in (NEW, RISING) and r["gene"] != "ESR1"]
    out += [{"pointer": "", "month": v["latest_month"], "what": f"{v['variant']}: {v['origin']}",
             "why": v["why"], "evidence": OBSERVED, "status": LITERATURE}
            for v in vs if v["origin"] == POSSIBLE_CH]
    out += [{"pointer": "", "month": s["month"], "what": s["what"], "why": "low shedding",
             "evidence": OBSERVED, "status": IMPLEMENTED} for s in shed]
    return sorted(out, key=lambda i: -i["month"])


def rules_card(series: dict) -> dict:
    """The rules card: no model, rules on observed allele fractions, every threshold sourced."""
    lod = series["detection_limit"]
    return {
        "name": "ctDNA monitor rules",
        "kind": "rules only: no model, no fit",
        "inputs": "variant allele fractions per plasma sample with the sample's month; the "
                  "record's tumor sequencing, treatment starts and imaging reports",
        "outputs": "a call per variant per sample (detected, new, rising, falling, stable, not "
                   "detected, cleared); each variant's origin; the ESR1 rule items; lead and "
                   "lag against imaging and CA 15-3",
        "thresholds": [
            {"name": "detection limit", "value": f"{lod:g}% variant allele fraction",
             "source": "placeholder, not an assay's validated limit", "status": PLACEHOLDER},
            {"name": "rising", "value": f"at least {RISE_FACTOR:g}x the previous detected value, "
                                        "or newly detected", "source": "placeholder",
             "status": PLACEHOLDER},
            {"name": "falling", "value": f"at most {FALL_FACTOR:g}x the previous detected value",
             "source": "placeholder", "status": PLACEHOLDER},
            {"name": "cleared", "value": f"below the detection limit at {CLEAR_SAMPLES} "
                                         "consecutive samples after detection",
             "source": "placeholder", "status": PLACEHOLDER},
            {"name": "flat whatever the treatment", "value": f"highest over lowest detected VAF "
                                                             f"under {STABLE_RATIO:g}, 3 or more "
                                                             "samples", "source": "placeholder",
             "status": PLACEHOLDER},
            {"name": "possible clonal hematopoiesis", "value": "not in the tumor sequencing and "
                                                               f"in {', '.join(CH_GENES)}",
             "source": f"{RAZAVI_2019}; {JAISWAL_2014}", "status": LITERATURE},
            {"name": "ESR1 under an aromatase inhibitor", "value": "a new or rising ESR1 call "
                                                                   "while one is recorded",
             "source": f"{PADA_1}; {SERENA_6}", "status": LITERATURE},
        ],
        "evidence": OBSERVED,
        "validation": "none: no cohort, no outcome; SYNTHETIC-001's series is synthetic",
        "known_failures": [
            "clonal hematopoiesis outside DNMT3A, TET2 and ASXL1 (TP53 among them, Razavi 2019) "
            "is not flagged: only matched white-cell sequencing settles origin",
            "the rising and falling ratios know no assay noise: near the detection limit a "
            "doubling can be sampling noise",
            "the record holds treatment starts only, so the therapy at a sample is inferred "
            "from the next treatment event",
        ],
        "status": IMPLEMENTED,
    }


def report_markdown(file_id: str, rows: list[dict], vs: list[dict], rule: list[dict],
                    lag: list[dict], shed: list[dict], card: dict,
                    reviews: dict | None = None) -> str:
    """A Markdown report: the series, each variant's origin and calls, the ESR1 rule items with
    their trial comparison and sources, lead and lag, what ctDNA cannot see, every placeholder
    and the review marks. Nothing recommended."""
    L = [f"# ctDNA monitor report: {file_id}", "", SYNTHETIC_NOTE if rows and rows[0]["synthetic"]
         else "", "", "Observed allele fractions; calls are rules with placeholder thresholds; "
         "trial evidence is for clinician review. Nothing here is a recommendation.", "",
         "## Series", "", "| pointer | month | variant | VAF | call | rule | therapy |",
         "|---|---|---|---|---|---|---|"]
    L += [f"| {r['pointer']} | {r['month']} | {r['variant']} | "
          f"{_vaf(r)} | {r['call']} | {r['rule']} | {' + '.join(r['therapy']) or 'none'} |"
          for r in rows]
    L += ["", "## Variants and their origin", ""]
    L += [f"- {v['variant']}: {v['origin']} ({v['why']}); {v['detected']}; {v['pattern']}"
          for v in vs]
    L += ["", "## ESR1 under an aromatase inhibitor (PADA-1, SERENA-6; for clinician review)", ""]
    for i in rule:
        L.append(f"- {i['pointer']} {i['what']}")
        L += [f"  - {a}: trial: {t or '-'}; {r}" for a, t, r in i["compare"]]
    if not rule:
        L.append("- no new or rising ESR1 call")
    L += ["", "## Against imaging and CA 15-3 (observed order in this record)", ""]
    L += [f"- {x['pointer']} {x['what']}" for x in lag] or ["- none"]
    if shed:
        L += ["", "## Low shedding", ""] + [f"- {s['what']}" for s in shed]
    L += ["", "## What ctDNA cannot see", ""] + [f"- {c}" for c in CANNOT_SEE]
    L += ["", "## Placeholders", ""]
    L += [f"- {t['name']}: {t['value']}" for t in card["thresholds"]
          if t["status"] == PLACEHOLDER]
    L += ["", "## Sources", ""] + [f"- {s}" for s in (RAZAVI_2019, JAISWAL_2014, PADA_1,
                                                       SERENA_6, SCHIAVON_2015)]
    L += ["", "## Review marks", ""]
    L += [f"- {v['what']}: {v['mark']} ({v['by'] or 'no initials'}, {v['at']})"
          for v in (reviews or {}).values()] or ["- none"]
    L += ["", f"Rules: {card['name']}; validation: {card['validation']}."]
    return "\n".join(L) + "\n"


def _vaf(r: dict) -> str:
    return f"{r['vaf']:g}%" if r["detected"] else f"not detected (<{r['lod']:g}%)"

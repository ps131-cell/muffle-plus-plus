"""The Timeline view of a patient file (docs/timeline.md): every entry of the record in lanes on one
month axis with the report versions it created, what each version changed, and what the risk chart
can show beside the risk.

Pure functions over ``muffle.workspace.PatientFile``: no Streamlit, no model run, nothing new
estimated. Months count from the first tumor sequencing (SYNTHETIC-001) or the TCGA tumor sample
(month 0); a TCGA baseline test carries no date and sits at month 0. Every point keeps its evidence
label and where it comes from: the record, or an import with who and when.
"""

from __future__ import annotations

from muffle import crosstest
from muffle.report.case_tools import INFERENCE, OBSERVED
from muffle.timeline import CTDNA
from muffle.version_diff import risk_delta
from muffle.workbench import documents
from muffle.workbench.grammar import esc
from muffle.workspace import PatientFile, Test

VERSIONS, TREATMENTS, IMPORTED = "Report versions", "Treatments", "Imported tests"
LANES = (VERSIONS, TREATMENTS, "Imaging", "Labs and tumor markers", "ctDNA",
         "Sequencing and omics", "Pathology and documents", "Clinic visits", IMPORTED)
BY_WORKBENCH = {"imaging": "Imaging", "labs": "Labs and tumor markers", "ctdna": "ctDNA",
                "mutations": "Sequencing and omics", "omics": "Sequencing and omics",
                "record": "Sequencing and omics", "slides": "Pathology and documents",
                "documents": "Pathology and documents"}
SPAN_RULE = ("the record holds start dates only, so a drug's bar runs to the next treatment entry "
             "that does not name it, or stays open to the latest entry")
DODGE = 0.6  # months between versions (and their points) that share a month, so each is clickable


def lane(t: Test, imported: bool = False) -> str:
    """The lane of a test: imports on their own lane, clinic notes on theirs, else by workbench."""
    if imported:
        return IMPORTED
    return "Clinic visits" if t.kind == "Clinic note" else \
        BY_WORKBENCH.get(t.workbench, "Pathology and documents")


def _m(month: int | None) -> int:
    return 0 if month is None else month


def spans(pf: PatientFile) -> list[dict]:
    """Each drug as a bar {"drug", "start", "end", "open", "version", "words", "track"} (SPAN_RULE):
    "adds alpelisib to fulvestrant" keeps fulvestrant running and ends palbociclib. ``track``
    stacks bars that overlap in time."""
    out, active = [], {}
    for k, v in enumerate(pf.versions):
        if not v.treatments:
            continue
        for drug in [d for d in active if d not in v.event.lower()]:
            out.append({**active.pop(drug), "end": v.month, "open": False})
        for drug in v.treatments:
            active.setdefault(drug, {"drug": drug, "start": v.month, "version": k,
                                     "words": v.event})
    end = max(_m(v.month) for v in pf.versions)
    out = sorted(out + [{**s, "end": end, "open": True} for s in active.values()],
                 key=lambda s: (s["start"], s["drug"]))
    ends: list[float] = []  # each track's last end
    for s in out:
        s["track"] = next((n for n, e in enumerate(ends) if e <= s["start"]), len(ends))
        ends[s["track"]:s["track"] + 1] = [s["end"]]
    return out


def lanes(pf: PatientFile) -> dict:
    """The event chart's data: {"points", "spans", "lanes" (in use, in LANES order), "empty"
    (lanes with no entry), "axis"}. A point is a report version, a test, a treatment start or an
    SOS alert, with its ``version`` (the index a click opens), where it comes from and its
    evidence label; tests of one version on one lane and month share a point. A version's point
    also carries its risk ``shift`` since the version before (``muffle.version_diff.SHIFTS``),
    that move in words (``delta``) and whether it is the ``latest``."""
    docs = {d["doc"]: d for d in documents.timeline(documents.file_documents(pf))}
    points, shared, seen = [], {}, {}
    for k, v in enumerate(pf.versions):
        m = _m(v.month)
        dodge = DODGE * seen.setdefault(m, 0)
        seen[m] += 1
        source = v.imported or "the record"
        tone = "imported in this session" if v.imported else "from the record"
        base = {"version": k, "version_label": v.label, "entry": v.event, "source": source,
                "tone": tone}
        r = risk_delta(pf, k - 1, k) if k else None
        points.append({**base, "lane": VERSIONS, "month": m, "x": m + dodge, "mark": "version",
                       "what": f"v{k + 1} · {v.label}", "result": v.summary,
                       "when": "the tumor sample" if v.month is None else f"month {m}",
                       "evidence": OBSERVED + (f"; {INFERENCE} (risk)" if v.risk else ""),
                       "shift": "none" if r is None else r["shift"],
                       "delta": "the first version" if r is None else r["text"],
                       "latest": k == len(pf.versions) - 1})
        for t in v.tests:
            at = (lane(t, bool(v.imported)), _m(t.month), k)
            dates = docs.get(t.details.get("document"), {}).get("dates_in_text")
            when = f"month {t.month}" if t.month is not None else (
                f"the tumor sample; {t.name} carries the date {dates}" if dates else
                "the tumor sample (TCGA's de-identified record carries no date)")
            if at in shared:
                shared[at]["what"] += f"; {t.name}"
                shared[at]["result"] += f"; {t.result}"
                if when not in shared[at]["when"]:
                    shared[at]["when"] += f" | {when}"
                continue
            shared[at] = {**base, "lane": at[0], "month": at[1], "x": at[1] + dodge,
                          "mark": "test", "what": t.name, "result": t.result, "when": when,
                          "evidence": OBSERVED + (" (synthetic series)"
                                                  if t.details.get("synthetic") else "")}
            points.append(shared[at])
        points += [{**base, "lane": TREATMENTS, "month": m, "x": m + dodge, "mark": "treatment",
                    "what": f"starts {drug}", "result": v.event, "when": f"month {m}",
                    "evidence": OBSERVED} for drug in v.treatments]
        for a in v.alerts:
            kind, month, name = (tuple(a.opens) + (None,) * 4)[1:4]
            t = next((t for t in v.tests if (t.kind, t.month, t.name) == (kind, month, name)),
                     None)
            at = ("alert", VERSIONS if t is None else lane(t, bool(v.imported)), _m(a.month), k)
            if at in shared:  # alerts on one test share a point
                for f, text in (("what", a.what), ("result", f"rule: {a.rule}"),
                                ("evidence", f"{a.evidence}; trust {a.trust}")):
                    shared[at][f] += f" | {text}"
                continue
            shared[at] = {**base, "lane": at[1], "month": at[2], "x": at[2] + dodge,
                          "mark": "alert", "tone": "SOS alert", "what": a.what,
                          "result": f"rule: {a.rule}; threshold: {a.threshold}",
                          "when": f"month {at[2]}", "evidence": f"{a.evidence}; trust {a.trust}"}
            points.append(shared[at])
    bars = spans(pf)
    used = {p["lane"] for p in points}
    synthetic = pf.kind == "synthetic"
    first = min(_m(v.month) for v in pf.versions)
    return {"points": points, "spans": bars, "lanes": [n for n in LANES if n in used],
            "empty": [n for n in LANES if n not in used],
            "axis": f"months from the first tumor sequencing (month 0; diagnosis at month {first})"
                    if synthetic else "months from the TCGA tumor sample (month 0)"}


def summary_changes(before: dict, after: dict) -> list[dict]:
    """The workbench finding cards that differ between two versions' summaries
    (``muffle.overview.summaries``): added, changed (its text) or removed, each with its
    workbench, evidence label, trust and, unless removed, where it opens."""
    out = []
    for name in dict.fromkeys([*before, *after]):
        a = {c["what"]: c for c in before.get(name, {}).get("cards", [])}
        b = {c["what"]: c for c in after.get(name, {}).get("cards", [])}
        title = (after.get(name) or before[name])["title"]
        for what in dict.fromkeys([*a, *b]):
            x, y = a.get(what), b.get(what)
            if x and y and x["text"] == y["text"]:
                continue
            c = y or x
            out.append({"workbench": title, "what": what,
                        "status": "added" if x is None else "removed" if y is None else "changed",
                        "before": x and x["text"], "after": y and y["text"],
                        "evidence": c["evidence"], "trust": c["trust"],
                        "opens": tuple(y["opens"]) if y else (), "focus": y and y["focus"]})
    return out


def changes(pf: PatientFile, i: int, sums: dict | None = None,
            before: dict | None = None) -> dict:
    """What version ``i`` brought: its tests, the observed rows that changed, the SOS alerts it
    raised, the treatments it started, the risk move (``crosstest.diff_versions``) with its
    attribution, and, given the workbenches' summaries at ``i`` (``sums``) and at ``i - 1``
    (``before``), the finding cards that changed. Version 0 brings everything it holds."""
    v = pf.versions[i]
    old, new = (dict(pf.versions[i - 1].observed) if i else {}), dict(v.observed)
    observed = [{"what": k, "before": old.get(k), "after": new.get(k)}
                for k in dict.fromkeys([*old, *new]) if old.get(k) != new.get(k)]
    risk = [d for d in crosstest.diff_versions(pf, i - 1, i) if d["column"] == INFERENCE
            and not d["finding"].startswith("Alert: ")] if i and v.risk else []
    return {"label": v.label, "month": v.month, "event": v.event, "imported": v.imported,
            "tests": list(v.tests), "observed": observed, "alerts": list(v.alerts),
            "treatments": list(v.treatments), "risk": risk, "attribution": list(v.changes),
            "summary": v.summary,
            "workbenches": [] if sums is None else summary_changes(before or {}, sums)}


def context(pf: PatientFile, i: int, series: dict = CTDNA) -> dict:
    """What the risk chart can show beside the risk as of version ``i``, all observed: CA 15-3
    values (imported ones too), ctDNA allele fractions of the samples in the file so far (the
    synthetic series ``series``; None = not detected), imaging reads and the treatment bars,
    cut at the version's month (a bar running past it is open)."""
    upto = [(v, t) for v in pf.versions[: i + 1] for t in v.tests]
    now = _m(pf.versions[i].month)
    progressed = {a.month for v in pf.versions[: i + 1] for a in v.alerts
                  if a.what.startswith("Progression on imaging")}
    samples = {t.details["sample"] for _, t in upto if t.workbench == "ctdna"}
    return {
        "ca153": [{"month": t.month, "value": t.details["value"], "words": t.result,
                   "source": v.imported or "the record"} for v, t in upto
                  if t.kind == "Lab" and t.details.get("marker") == "ca153"],
        "ctdna": [{"month": s["month"], "variant": var, "vaf": vaf} for s in series["samples"]
                  if s["month"] in samples for var, vaf in s["vaf"].items()],
        "lod": series["detection_limit"],
        "imaging": [{"month": t.month, "words": t.result,
                     "read": "progression" if t.month in progressed or
                     t.details.get("read") == "progression" else "no progression stated"}
                    for _, t in upto if t.kind == "Imaging" and t.month is not None],
        "treatments": [{**s, "end": min(s["end"], now), "open": s["open"] or s["end"] > now}
                       for s in spans(pf) if s["start"] <= now],
    }


def markdown(pf: PatientFile, i: int) -> list[str]:
    """The report export's Timeline section: what each version up to ``i`` brought."""
    out = ["", f"## Timeline: what each version brought [{OBSERVED} unless marked]"]
    for k in range(i + 1):
        c = changes(pf, k)
        out.append(f"- **{esc(c['label'])}** ({c['imported'] or 'from the record'}): "
                   f"{esc(c['event'])}")
        if c["tests"]:
            out.append("  - Tests added: " + "; ".join(
                f"{t.kind} {esc(t.name)}: {esc(t.result)}" for t in c["tests"]))
        if c["treatments"]:
            out.append("  - Treatments started: " + ", ".join(c["treatments"]))
        if c["observed"]:
            out.append("  - Observed record: " + "; ".join(
                f"{o['what']}: " + (esc(o["after"]) if o["before"] is None else
                                    f"{esc(o['before'])} → {esc(o['after'] or 'removed')}")
                for o in c["observed"]))
        out += [f"  - SOS alert: {esc(a.what)} [{a.evidence}; trust {a.trust}]"
                for a in c["alerts"]]
        if c["risk"] or c["imported"]:
            out.append(f"  - Risk [{INFERENCE}]: {c['summary']}")
    return out

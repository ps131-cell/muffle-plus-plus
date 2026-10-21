"""Patient files for the clinician workspace (docs/WORKSPACE.md): report versions, tests and SOS
alerts, built only from data the demo already has.

* The synthetic timeline patient: its hand-written record (``muffle.timeline.EVENTS``) and its
  scores in ``app/timeline_synthetic.json``, with one report version per event.
* A held-out TCGA case (``muffle.demo.Case``): one report version, since TCGA holds one tumor
  sample per patient.

Nothing here runs a model. Every finding keeps its evidence type and every test its workbench and
status. Every alert keeps the rule that raised it and the source of its threshold: a placeholder
must never look validated (CLAUDE.md).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from muffle.data.tcga import DRIVERS as TCGA_PANEL
from muffle.demo import ordinal
from muffle.longitudinal import DRIVERS
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED, age_band
from muffle.timeline import EVENTS, PATIENT_ID

IMPLEMENTED, VALIDATED, PLANNED = "implemented", "experimentally validated", "planned"

MARKERS = {"ca153": ("CA 15-3", "U/mL"), "cea": ("CEA", "ng/mL")}
# Reference limits as the record states them. SYNTHETIC-001's first lab report reads
# "reference below 30"; CEA has none in the record, so it never raises an alert.
REFERENCE_LIMITS = {"ca153": (30.0, "the record's lab report (month -2)")}
# A significant marker rise per the EGTM breast cancer recommendations: at least 25% over the
# previous value with the second value above the reference interval, to be confirmed with a second
# specimen within a month (which an alert raised at one timepoint can't know yet)
RISE = 0.25
EGTM = "literature: EGTM breast cancer recommendations (egtm.eu; Molina et al., Tumour Biol 2005)"
RISK_JUMP = 20  # PLACEHOLDER: a rise in 12-month risk (points) worth an alert, not validated
# ponytail: alerts are ordered by consequence × these weights, a fixed rule (placeholder), not a
# validated score; a triage model calibrated on outcomes would replace it
TRUST = {"strong": 1.0, "moderate": 0.6, "weak": 0.3}
DISCLAIMER = "Research and decision support for clinicians; not a diagnosis or a prescription."

ASSAYS = {"clinical": "Clinical record (stage, T/N/M, age, histology)",
          "genomic": "Copy number (ASCAT3, gene level)",
          "rna": "RNA-seq (STAR TPM)",
          "methylation": "DNA methylation array (450K)",
          "protein": "Protein array (RPPA)"}


@dataclass
class Alert:
    what: str
    month: int | None
    source: str      # the test or event that raised it
    evidence: str    # observed / model inference / hypothesis
    rule: str        # how it was decided
    threshold: str   # where the threshold comes from
    trust: str = "strong"  # strong / moderate / weak (TRUST)
    why_trust: str = ""    # what the trust rests on
    consequence: int = 2   # 3 changes the picture of the disease, 2 may change care, 1 worth a look
    opens: tuple = ()      # where its evidence is: ("Tests", kind, month, name) or ("Timeline",)

    @property
    def priority(self) -> float:
        return self.consequence * TRUST[self.trust]


@dataclass
class Test:
    kind: str        # Lab, Imaging, Sequencing, Pathology report, Clinical record, Data layer, ...
    month: int | None
    name: str
    result: str
    workbench: str   # labs, mutations, omics, record, imaging, slides
    status: str      # status of that workbench: implemented or planned
    details: dict = field(default_factory=dict)  # what the workbench opens: marker, layer, variants


@dataclass
class Version:
    month: int | None  # months after the first tumor sequencing; None for a TCGA baseline
    label: str
    event: str         # what arrived
    observed: list[list[str]]
    risk: dict | None
    summary: str
    changes: list[dict] = field(default_factory=list)
    alerts: list[Alert] = field(default_factory=list)
    tests: list[Test] = field(default_factory=list)       # added in this version
    treatments: list[str] = field(default_factory=list)   # started in this version
    imported: str = ""  # who added it in this session, and when ("" = from the record)


@dataclass
class PatientFile:
    id: str
    kind: str          # "synthetic" or "TCGA-BRCA"
    title: str
    diagnosis: str
    versions: list[Version]
    note: str
    model: dict

    @property
    def latest(self) -> Version:
        return self.versions[-1]

    @property
    def tests(self) -> list[Test]:
        return [t for v in self.versions for t in v.tests]


def _event_tests(e: dict) -> list[Test]:
    """The tests one event of the synthetic record adds; treatments are events, not tests."""
    m, out = e["month"], []
    if e["kind"] == "Diagnosis":  # the slide workbench runs on a public example region for now
        out.append(Test("Pathology report", m, "Diagnosis", e["text"], "slides", IMPLEMENTED,
                        {"scope": "example region, first version"}))
    if e["kind"] == "Imaging":  # the radiology workbench reads the report's words (no images)
        out.append(Test("Imaging", m, "Imaging report", e["text"], "imaging", IMPLEMENTED,
                        {"scope": "report text, no images"}))
    if e["kind"] == "Clinic visit":  # the note's text is a document of the record
        out.append(Test("Clinic note", m, "Clinic visit", e["text"], "documents", IMPLEMENTED,
                        {"document": f"m{m}-clinic-visit"}))
    if "mutations" in e:
        found = [f"{g} {c}" for g, c in e["mutations"]]
        out.append(Test("Sequencing", m, "Tumor sequencing", ", ".join(found)
                        or "no panel driver mutated", "mutations", IMPLEMENTED,
                        {"variants": found, "panel": list(DRIVERS)}))
    for key, (name, unit) in MARKERS.items():
        if key in e:
            out.append(Test("Lab", m, name, f"{e[key]:g} {unit}", "labs", IMPLEMENTED,
                            {"marker": key, "value": float(e[key])}))
    return out


def marker_rise(key: str, value: float, before: float | None, month: int,
                limit: tuple[float, str] | None = None) -> Alert | None:
    """The tumor-marker rise alert (EGTM): ``value`` above the reference limit and at least
    ``RISE`` above the previous value ``before``; None otherwise. ``limit`` is (value, where it
    comes from), the record's ``REFERENCE_LIMITS`` entry by default; a marker without one never
    raises it."""
    name, unit = MARKERS[key]
    limit = limit or REFERENCE_LIMITS.get(key)
    if not (limit and before and value > limit[0] and value >= before * (1 + RISE)):
        return None
    return Alert(
        f"{name} rose from {before:g} to {value:g} {unit} ({value / before - 1:+.0%}), above the "
        f"reference limit of {limit[0]:g}", month, f"{name}, month {month}", OBSERVED,
        f"above the reference limit and at least {RISE:.0%} above the previous value; "
        "unconfirmed until a second specimen within a month",
        f"limit from {limit[1]}; the {RISE:.0%} rise from {EGTM}", "moderate",
        "measured values, but no confirming second specimen yet", 2, ("Tests", "Lab", month, name))


def synthetic_file(tl: dict, events: list[dict] = EVENTS) -> PatientFile:
    """SYNTHETIC-001 with one report version per event of its record. ``tl`` is
    ``app/timeline_synthetic.json``, whose updates are row-aligned with ``events``."""
    evidence, versions = tl.get("evidence", {}), []
    seen_sites, seen_drivers, last = set(), set(), {}
    for e, u in zip(events, tl["updates"], strict=True):
        m, alerts = e["month"], []
        source = f"{e['kind']}, month {m}"
        imaging = ("Tests", "Imaging", m, "Imaging report")
        if e.get("progression"):
            alerts.append(Alert(f"Progression on imaging: {e['text']}", m, source, OBSERVED,
                                "the imaging report reads progression", "none: recorded",
                                "strong", "recorded in the imaging report", 3, imaging))
        for site in e.get("sites", []):
            if site not in seen_sites:
                seen_sites.add(site)
                alerts.append(Alert(f"New metastatic site: {site.lower()}", m, source, OBSERVED,
                                    "a site not in the record before", "none: recorded",
                                    "strong", "recorded in the imaging report", 3, imaging))
        for key in MARKERS:
            if key in e:
                rise = marker_rise(key, float(e[key]), last.get(key), m)
                last[key] = float(e[key])
                alerts += [rise] if rise else []
        for gene, change in e.get("mutations", []):
            variant = f"{gene} {change}"
            if variant in seen_drivers:
                continue
            seen_drivers.add(variant)
            levels = sorted(i["evidence_level"] for i in evidence.get(variant, []))
            if levels and levels[0] in ("A", "B"):
                alerts.append(Alert(
                    f"Newly sequenced driver {variant} has CIViC level {levels[0]} treatment "
                    "evidence, for clinician review", m, f"Sequencing, month {m}",
                    f"{OBSERVED} (mutation), {HYPOTHESIS} (treatment evidence)",
                    "a sequenced driver with level A or B CIViC evidence",
                    "CIViC curated evidence levels", "strong",
                    "a sequenced variant; the evidence level is CIViC's", 2,
                    ("Tests", "Sequencing", m, "Tumor sequencing")))
        risk = None
        if "risk" in u:
            model = tl["models"][str(u["landmark"])]
            risk = {"value": u["risk"], "range": u["risk_range"], "baseline": u["baseline"],
                    "landmark": u["landmark"], "auroc": model["auroc"][0],
                    "baseline_auroc": model["baseline_auroc"][0], "evidence": INFERENCE}
            if "previous" in u and 100 * (u["risk"] - u["previous"]) >= RISK_JUMP:
                alerts.append(Alert(
                    f"12-month risk up {100 * (u['risk'] - u['previous']):+.0f} points "
                    f"({u['previous']:.0%} → {u['risk']:.0%})", m,
                    f"month-{u['landmark']} MSK-CHORD models", INFERENCE,
                    f"the 12-month risk rose at least {RISK_JUMP} points since the previous "
                    "result", "placeholder", "weak",
                    "a model estimate, judged by a placeholder threshold", 2, ("Timeline",)))
        alerts.sort(key=lambda a: -a.priority)  # stable: ties keep the record's order
        versions.append(Version(
            m, f"month {m} · {e['kind']}", e["text"], u["observed"], risk,
            u.get("summary") or "No risk estimate yet: the models start at the first tumor "
                                "sequencing (month 0).",
            u.get("changes", []), alerts, _event_tests(e),
            [agent.lower() for _, agent in e.get("treatments", [])]))
    dx = next(e for e in events if e["kind"] == "Diagnosis")
    return PatientFile(
        PATIENT_ID, "synthetic", "Synthetic patient: written by hand, not a real person",
        dx["text"], versions, tl["notice"],
        {"name": "MSK-CHORD landmark models (gradient boosting, 5 seeds)",
         "endpoint": tl["task"], "status": VALIDATED, "note": tl["model_note"]})


def case_file(case, c_index: float | None = None, slides: list[str] | tuple = (),
              documents: list[dict] | tuple = (),
              imaging: list[dict] | None = None) -> PatientFile:
    """A held-out TCGA case (``muffle.demo.Case``): one report version, its data layers and
    mutation panel as tests, and no alerts, since nothing earlier exists to compare with.
    ``slides``: the names of this patient's scored diagnostic sections, when the slide pipeline
    ran on them (``app/workbenches/slides_results/cases.json``); they add a pathology test.
    ``documents``: its pathology reports (``muffle.workbench.documents.case_documents``), each a
    Document test. ``imaging``: this patient's processed public studies (TCIA;
    ``muffle.workbench.radiology.load_index``), each a test that opens the image viewer."""
    muts = None if case.mutations is None else [m.replace(" p.", " ") for m in case.mutations]
    tests = [Test("Clinical record" if m == "clinical" else "Data layer", None, ASSAYS[m],
                  "measured", "record" if m == "clinical" else "omics", IMPLEMENTED, {"layer": m})
             for m in case.layers]
    if slides:
        tests.append(Test("Pathology slide", None, "Diagnostic H&E section(s) (GDC, open access)",
                          f"{len(slides)} section(s) scored: tissue map, front, invasion, "
                          "cells", "slides", IMPLEMENTED,
                          {"scope": "the patient's own slides", "slides": list(slides)}))
    if muts is not None:
        tests.append(Test("Mutation panel", None, f"Somatic mutations, {len(TCGA_PANEL)} breast "
                          "cancer drivers (exome sequencing)", ", ".join(muts) or "none of the "
                          "panel's genes mutated", "mutations", IMPLEMENTED,
                          {"variants": muts, "panel": TCGA_PANEL}))
    tests += [Test("Document", None, d["title"], "pathology report text, read by the documents "
                   "rules", "documents", IMPLEMENTED, {"document": d["id"], **d})
              for d in documents]
    tests += [Test("Imaging", None, s["name"], s["result"], "imaging", IMPLEMENTED,
                   {"barcode": s["barcode"], "study": s["study"], "folder": s["folder"],
                    "scope": "public TCIA images"}) for s in imaging or []]
    observed = [
        ["Stage", case.stage or "not recorded"],
        ["Age band", age_band(case.age)],
        ["Data layers measured", ", ".join(case.layers)],
        ["Not measured", ", ".join(case.missing) or "none"],
        ["Driver mutations", "not sequenced (unknown, not wild type)" if muts is None
         else ", ".join(muts) or "sequenced: none of the panel's genes mutated"],
    ]
    risk = {"percentile": case.percentile, "group": case.group, "c_index": c_index,
            "evidence": INFERENCE}
    summary = (f"Model estimate: risk at the {ordinal(case.percentile)} percentile of the cohort "
               f"({case.group} risk group).")
    version = Version(None, "Baseline: the TCGA tumor sample",
                      "One tumor sample from surgery, with its data layers", observed, risk,
                      summary, tests=tests)
    return PatientFile(
        f"Case {case.index}", "TCGA-BRCA",
        f"TCGA-BRCA public data · simulated hospital {case.site}",
        f"Breast cancer, stage {case.stage}" if case.stage else "Breast cancer, stage not recorded",
        [version], "One timepoint: TCGA holds one tumor sample per patient, so there is no earlier "
        "result to compare with and no alert.",
        {"name": "FedAvg clinical-anchored residual model (NVIDIA FLARE, 3 simulated hospitals)",
         "endpoint": "overall survival, as a relative risk shown by cohort percentile",
         "status": VALIDATED})


def add_version(pf: PatientFile, tests: list[Test], month: int, event: str, by: str, at: str,
                observed: list[list[str]] = ()) -> PatientFile:
    """``pf`` with one more report version, for tests that arrived (an import); earlier versions
    stay as they were. ``observed`` rows replace the latest version's rows of the same name or
    are added. The marker-rise rule runs on each new lab value (``details``: "marker", "value"
    and optionally "limit") against the file's previous value of that marker. The other alert
    rules need what an import does not carry (an imaging read, a sequenced driver, a new risk
    estimate). The risk is not re-estimated: the synthetic patient's models are not run on new
    data here, so its version has none; a TCGA risk rests on the tumor sample alone, which an
    import doesn't change, so it carries over."""
    prev, last = pf.latest, {}
    for t in pf.tests:
        if t.kind == "Lab" and "value" in t.details:
            last[t.details["marker"]] = t.details["value"]
    alerts = []
    for t in sorted(tests, key=lambda t: t.month):
        d = t.details
        if t.kind == "Lab" and "value" in d:
            rise = marker_rise(d["marker"], d["value"], last.get(d["marker"]), t.month,
                               d.get("limit"))
            last[d["marker"]] = d["value"]
            alerts += [rise] if rise else []
    alerts.sort(key=lambda a: -a.priority)
    rows = dict(prev.observed) | dict(observed)
    if pf.kind == "synthetic":
        risk = None
        estimate = next((v.label for v in reversed(pf.versions) if v.risk), None)
        summary = ("No new risk estimate: the risk models are not run on imported results"
                   + (f"; the last estimate is in the version {estimate}." if estimate else "."))
    else:
        risk, summary = prev.risk, (f"{prev.summary} The estimate rests on the tumor sample "
                                    "alone, which this import does not change.")
    who = f"imported by {by or 'no initials'} at {at}"
    v = Version(month, f"month {month} · {who}", event, [[k, val] for k, val in rows.items()],
                risk, summary, alerts=alerts, tests=list(tests),
                imported=f"{who}; kept for this browser session only")
    return replace(pf, versions=[*pf.versions, v])


def record_events(pf: PatientFile, events: list[dict] = EVENTS) -> list[dict]:
    """The file's record as events (the shape of ``muffle.timeline.EVENTS``) for the lab
    workbench: the synthetic patient's record, then each imported lab value."""
    imported = [t.details["event"] for t in pf.tests if "event" in t.details]
    return sorted((list(events) if pf.kind == "synthetic" else []) + imported,
                  key=lambda e: e["month"])


def lab_series(events: list[dict], key: str) -> list[dict]:
    """Each recorded value of a marker, with its change from the previous value, from the lowest
    earlier value (nadir) and per month: observed values, plain arithmetic, no model."""
    rows, prev, nadir = [], None, None
    for e in events:
        if key not in e:
            continue
        value, month = float(e[key]), e["month"]
        row = {"month": month, "value": value, "event": e["text"]}
        if prev is not None:
            row["change"] = value / prev["value"] - 1
            row["per_month"] = (value - prev["value"]) / (month - prev["month"])
        if nadir is not None:
            row["from_nadir"] = value / nadir - 1
        rows.append(row)
        prev, nadir = row, value if nadir is None else min(nadir, value)
    return rows


def sequencing_tests(pf: PatientFile, i: int) -> list[Test]:
    """The sequencing tests in the record up to report version ``i``."""
    return [t for v in pf.versions[: i + 1] for t in v.tests if t.workbench == "mutations"]


def missing_data(pf: PatientFile, i: int) -> list[str]:
    """What the record lacks at report version ``i``, and what that limits."""
    v = pf.versions[i]
    obs = dict(v.observed)
    out = [f"{k}: {val}" for k, val in v.observed if val.startswith("not ")]
    if obs.get("Not measured", "none") != "none":
        out.append(f"Not measured: {obs['Not measured']} (the model masks a missing layer; it is "
                   "unknown, not normal)")
    seq = sequencing_tests(pf, i)
    if seq and seq[-1].month is not None and v.month > seq[-1].month:
        out.append(f"Not sequenced since month {seq[-1].month}: mutations that arose under later "
                   "treatment would not show")
    tests = [t for w in pf.versions[: i + 1] for t in w.tests]
    planned = list(dict.fromkeys(t.kind for t in tests if t.status == PLANNED))
    if planned:
        out.append(f"{' and '.join(planned)} reports are text only: their workbench is planned")
    if any(t.workbench == "imaging" and "barcode" not in t.details for t in tests):
        out.append("Imaging reports are text only (no images on file): sites and reads are "
                   "known, lesion sizes are not")
    if any(t.workbench == "slides" and not t.details.get("slides") for t in tests):
        out.append("No slide image of this tumor is on file: the pathology workbench shows a "
                   "public example region")
    if len(pf.versions) == 1:
        out.append(pf.note)
    return out or ["Nothing recorded as missing."]


# Review marks: one store per browser session, ``st.session_state.reviews``, shared by the patient
# file and every workbench and carried by ``report_markdown``. Key: ``finding_key(pf, kind,
# *parts)``. Value: {"what": the finding in words, "mark": one of MARKS, "by": the reviewer's
# initials ("" if none), "at": "YYYY-MM-DD HH:MM"}. Pins: ``st.session_state.pins``, key -> what.
MARKS = ("reviewed", "agree", "disagree", "second look")
FINDING_KINDS = {  # kind -> the parts that follow it in the key
    "alert": "the alert's month, its what",
    "civic": "the variant ('PIK3CA H1047R'), the CIViC item's url",
    "risk": "the report version's month",
    "lab": "the marker key ('ca153'), the value's month",
    "variant": "the variant ('PIK3CA H1047R'), the sequencing test's month",
    "slide": "the slide ('TCGA-AN-A0AS-DX1'), the tile ('r12c34')",
    "omics": "the layer or block ('rna', 'subtype', 'pathway', 'receptor', 'score'), the feature "
             "or finding ('ESR1', 'E2F_TARGETS', 'ER: IHC vs RNA')",
    "document": "the document's id, the fact ('ER status: positive')",
    "evolution": "the watched event or 'trial', its source (a PMID or an NCT number)",
    "imaging": "the TCGA barcode (or 'report'), the study (its date, or the report's month), "
               "the lesion ('C1', or the named site)",
}


def finding_key(pf: PatientFile, kind: str, *parts) -> str:
    """A stable name for one finding, for review marks and pins (see MARKS and FINDING_KINDS):
    "SYNTHETIC-001|alert|11|CA 15-3 rose ..."."""
    if kind not in FINDING_KINDS:
        raise ValueError(f"finding kind must be one of {list(FINDING_KINDS)}")
    return "|".join([pf.id, kind, *map(str, parts)])


def report_markdown(pf: PatientFile, i: int, evidence: dict | None = None,
                    reviews: dict | None = None, sources: list[str] | tuple = (),
                    disagree: list[dict] | tuple = (), reducers: list[dict] | tuple = ()) -> str:
    """Report version ``i`` as one Markdown page: summary, alerts, the three kinds of finding,
    missing data, tests that disagree, what would reduce uncertainty, every placeholder, model
    and sources, and the reviewers' marks. ``evidence`` maps "GENE CHANGE" to its CIViC items
    (None: the table couldn't load); ``reviews`` maps ``finding_key`` names to {"what", "mark",
    "by", "at"}; ``disagree`` and ``reducers`` are ``muffle.crosstest``'s lists."""
    v, evidence, reviews = pf.versions[i], evidence or {}, reviews or {}
    when = "" if v.month is None else f" (month {v.month})"
    out = [f"# {pf.id} · report {v.label}", "", f"_{pf.title} · {pf.diagnosis}_", "",
           f"_{DISCLAIMER}_", ""]
    if pf.kind == "synthetic":
        out += [f"> {pf.note}", ""]
    out += ["## Summary", f"Latest in the record: {v.event}{when} [{OBSERVED}]", "",
            f"{v.summary}" + (f" [{INFERENCE}]" if v.risk else ""), "",
            "## SOS alerts in this version"]
    out += [f"- {a.what} [{a.evidence}; trust {a.trust}: {a.why_trust}]. Rule: {a.rule}. "
            f"Threshold: {a.threshold}." for a in v.alerts] or ["- none"]
    out += ["", f"## Observed [{OBSERVED}]"] + [f"- {k}: {val}" for k, val in v.observed]
    out += ["", f"## Model inference [{INFERENCE}]"]
    r = v.risk or {}
    if "value" in r:
        out.append(f"- 12-month risk {r['value']:.0%} (5 models: {r['range'][0]:.0%}–"
                   f"{r['range'][1]:.0%}); diagnosis only {r['baseline']:.0%}; month-"
                   f"{r['landmark']} {pf.model['name']}, held-out AUROC {r['auroc']:.2f}; "
                   "calibration not checked")
        out += [f"  - {c['what']}: {c['points']:+.0f} points" for c in v.changes]
    elif "percentile" in r:
        out.append(f"- Risk at the {ordinal(r['percentile'])} percentile ({r['group']} risk "
                   f"group); {pf.model['name']}"
                   + ("" if r.get("c_index") is None else f", held-out C-index "
                      f"{r['c_index']:.3f}") + "; it ranks patients and is only roughly "
                   "calibrated")
    else:
        out.append(f"- {v.summary}")
    out += ["", f"## Hypotheses and evidence [{HYPOTHESIS}; for clinician review, not a "
            "recommendation]"]
    for var in [var for t in sequencing_tests(pf, i) for var in t.details["variants"]]:
        items = evidence.get(var)
        if not items:
            out.append(f"- {var}: " + ("CIViC not available here" if items is None else
                                       "no CIViC breast cancer evidence"))
        out += [f"- {var} · CIViC level {e['evidence_level']} ({e['level_meaning']}) · "
                f"{e['therapies'].replace(',', ', ')} · {str(e['significance']).lower()} · "
                f"{e['citation']} {e['url']}" for e in items or []]
    if not sequencing_tests(pf, i):
        out.append("- Not sequenced: no treatment evidence")
    out += ["", "## Missing data and what it limits"]
    out += [f"- {m}" for m in missing_data(pf, i)]
    if disagree:
        out += ["", "## Tests that disagree"] + [
            f"- {d['what']} [{d['evidence']}]: {d['why']} What would settle it: "
            f"{d['would_settle']}" for d in disagree]
    if reducers:
        out += ["", f"## What would reduce uncertainty [{HYPOTHESIS}; evidence, not an order]"]
        out += [f"- {r['open_question']} → {r['test']}: {r['expectation']} (source: "
                f"{r['source']})" for r in reducers]
    placeholders = [  # the rules this file's alerts use; a TCGA file has no alerts
        f"An alert when the 12-month risk rises at least {RISK_JUMP} points",
        "Alert order: consequence × trust, with trust weights "
        + ", ".join(f"{k} {w:g}" for k, w in TRUST.items())] if pf.kind == "synthetic" else []
    out += ["", "## Placeholders (not validated)"] + [f"- {p}" for p in placeholders or ["none"]]
    out += ["", "## Model and sources",
            f"- {pf.model['name']} ({pf.model['status']}); endpoint: {pf.model['endpoint']}"]
    out += [f"- {s}" for s in sources]
    imports = [w for w in pf.versions[: i + 1] if w.imported]
    if imports:
        out += ["", "## Imported in this session (kept for this browser session only)"]
        out += [f"- {w.label}: {w.event}; tests: " + ", ".join(
            f"{t.kind} {t.name} ({t.status})" for t in w.tests) for w in imports]
    marks = [r for k, r in reviews.items() if k.startswith(pf.id + "|")]
    out += ["", "## Review marks"] + ([f"- {r['what']}: {r['mark']} ({r['by'] or 'no initials'}, "
                                       f"{r['at']})" for r in marks] or ["- none"])
    return "\n".join(out) + "\n"

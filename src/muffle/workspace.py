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
from muffle.timeline import CTDNA, EVENTS, PATIENT_ID

IMPLEMENTED, VALIDATED, PLANNED = "implemented", "experimentally validated", "planned"

# the tumor markers the EGTM rise rule (and its SOS alert) reads
MARKERS = {"ca153": ("CA 15-3", "U/mL"), "cea": ("CEA", "ng/mL"),
           "ca2729": ("CA 27.29", "U/mL")}
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
QUEUE_ORDER = ("ordered by consequence × trust (weights " + ", ".join(
    f"{k} {w:g}" for k, w in TRUST.items()) + "; a fixed rule with placeholder weights, not a "
    "validated score), then new in this version, then the latest first")
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
    workbench: str   # labs, mutations, omics, record, imaging, slides, ctdna
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


CTDNA_KIND = "ctDNA (liquid biopsy)"


def ctdna_tests(series: dict = CTDNA) -> list[Test]:
    """One ctDNA test per sample of the synthetic patient's series (``muffle.timeline.CTDNA``),
    for the ctDNA workbench; every one labeled synthetic."""
    lod = series["detection_limit"]
    return [Test(CTDNA_KIND, s["month"], "ctDNA panel (synthetic series)", ", ".join(
        f"{v} {vaf:g}%" if vaf is not None else f"{v} not detected (below {lod:g}%)"
        for v, vaf in s["vaf"].items()), "ctdna", IMPLEMENTED,
        {"sample": s["month"], "synthetic": True}) for s in series["samples"]]


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


def driver_alert(variant: str, items: list[dict] | None, month: int,
                 test: str = "Tumor sequencing") -> Alert | None:
    """The newly-sequenced-driver alert: ``variant`` ("GENE CHANGE") has level A or B CIViC
    treatment evidence among ``items``; None otherwise (also when CIViC isn't loaded)."""
    levels = sorted(i["evidence_level"] for i in items or [])
    if not levels or levels[0] not in ("A", "B"):
        return None
    return Alert(
        f"Newly sequenced driver {variant} has CIViC level {levels[0]} treatment evidence, for "
        "clinician review", month, f"Sequencing, month {month}",
        f"{OBSERVED} (mutation), {HYPOTHESIS} (treatment evidence)",
        "a sequenced driver with level A or B CIViC evidence", "CIViC curated evidence levels",
        "strong", "a sequenced variant; the evidence level is CIViC's", 2,
        ("Tests", "Sequencing", month, test))


def _sites(row: str) -> list[str]:
    """The site names of an observed "Metastatic sites" row ("Bone (month -1), Liver (month
    12)")."""
    return [] if row == "none" else [s.split(" (")[0] for s in row.split(", ")]


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
            found = driver_alert(variant, evidence.get(variant, []), m)
            alerts += [found] if found else []
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
    if events is EVENTS:  # the series belongs to this record: each sample joins the first
        for t in ctdna_tests():  # version at or after its month, so "as of" never shows it early
            next((v for v in versions if v.month >= t.month), versions[-1]).tests.append(t)
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
            "log_risk": getattr(case, "log_risk", None),  # ties precomputed scores to the build
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
                observed: list[list[str]] = (), evidence=None) -> PatientFile:
    """``pf`` with one more report version, for tests that arrived (an import); earlier versions
    stay as they were. ``observed`` rows replace the latest version's rows of the same name or
    are added. The alert rules run on the new tests against the file so far:
    * the marker rise on each lab value (``details``: "marker", "value", optionally "limit");
    * a newly sequenced driver with level A or B CIViC evidence on each variant of a sequencing
      test (``details["variants"]``) not sequenced before; ``evidence(variant)`` gives its CIViC
      items (None: CIViC isn't loaded, so no alert can be raised);
    * progression on imaging and a new metastatic site on an imaging read (``details``: "read",
      "words", "new_sites", from ``muffle.imports.imaging_read``); a site counts as new when the
      "Metastatic sites" row lacks it. These read the report's words by a text rule, not a
      person, so their trust is moderate.
    The driver, sites and progressions rows follow the new tests. The risk is not re-estimated:
    the synthetic patient's models are not run on new data here, so its version has none; a
    TCGA risk rests on the tumor sample alone, which an import doesn't change, so it carries
    over."""
    prev, last = pf.latest, {}
    for t in pf.tests:
        if t.kind == "Lab" and "value" in t.details:
            last[t.details["marker"]] = t.details["value"]
    rows = dict(prev.observed) | dict(observed)
    seen = {var for t in pf.tests if t.workbench == "mutations" for var in t.details["variants"]}
    sites, alerts = _sites(rows.get("Metastatic sites", "none")), []
    for t in sorted(tests, key=lambda t: t.month):
        d = t.details
        if t.kind == "Lab" and "value" in d and d["marker"] in MARKERS:  # tumor markers only
            rise = marker_rise(d["marker"], d["value"], last.get(d["marker"]), t.month,
                               d.get("limit"))
            last[d["marker"]] = d["value"]
            alerts += [rise] if rise else []
        if t.workbench == "mutations":
            new = [var for var in d["variants"] if var not in seen]
            seen |= set(new)
            found = [driver_alert(var, evidence(var) if evidence else None, t.month, t.name)
                     for var in new]
            alerts += [a for a in found if a]
            had = rows.get("Driver mutations", "")
            had = [] if had.startswith(("not sequenced", "sequenced")) or not had else [had]
            rows["Driver mutations"] = ", ".join(
                had + [f"{var} (month {t.month}, imported)" for var in new]) or \
                f"sequenced (month {t.month}, imported): none of the panel's genes in the file"
            genes = {var.split()[0] for var in new}
            if "Sequenced, not found" in rows:  # an earlier panel's genes, now found
                rows["Sequenced, not found"] = ", ".join(
                    g for g in rows["Sequenced, not found"].split(", ") if g not in genes)
        if t.kind == "Imaging" and "read" in d:
            opens, source = ("Tests", "Imaging", t.month, t.name), f"Imaging, month {t.month}"
            why = "the report's own words, read by a text rule (not yet by a person)"
            if d["read"] == "progression":
                words = d["words"] if len(d["words"]) <= 160 else d["words"][:157] + "…"
                alerts.append(Alert(f"Progression on imaging: \"{words}\"", t.month, source,
                                    OBSERVED, "the imported report states progression "
                                    f"({d['rule']})", "none: the report's words", "moderate",
                                    why, 3, opens))
                n = int(rows.get("Progressions on imaging", "0").split(",")[0]) + 1
                rows["Progressions on imaging"] = f"{n}, last at month {t.month}"
            for site in d["new_sites"]:
                if site not in sites:
                    sites.append(site)
                    alerts.append(Alert(f"New metastatic site: {site.lower()}", t.month, source,
                                        OBSERVED, "the imported report names a new site not in "
                                        f"the record before ({d['rule']})",
                                        "none: the report's words", "moderate", why, 3, opens))
                    had = rows.get("Metastatic sites", "none")
                    rows["Metastatic sites"] = ("" if had == "none" else had + ", ") + \
                        f"{site} (month {t.month}, imported report)"
    alerts.sort(key=lambda a: -a.priority)
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
    "document": "the document's id, the fact ('ER status: positive'); 'conflict', the field's "
                "label for a conflict between documents",
    "discrepancy": "the cross-test rule ('ERBB2 copy number vs HER2'), what it is about",
    "evolution": "the watched event or 'trial', its source (a PMID or an NCT number)",
    "imaging": "the TCGA barcode (or 'report'), the study (its date, or the report's month), "
               "the lesion ('C1', or the named site)",
    "ctdna": "the variant ('ESR1 D538G'), the ctDNA sample's month",
    "cn": "the gene of a copy-number call ('ERBB2')",
    "pathway": "the pathway's name on the genomics pathway map ('PI3K / AKT / mTOR')",
    "pathway_protein": "the RPPA pathway score's name ('PI3K/AKT', Akbani et al. 2014)",
    "methylation": "the gene whose promoter methylation is read ('BRCA1'), or 'index'",
}


def finding_key(pf: PatientFile, kind: str, *parts) -> str:
    """A stable name for one finding, for review marks and pins (see MARKS and FINDING_KINDS):
    "SYNTHETIC-001|alert|11|CA 15-3 rose ..."."""
    if kind not in FINDING_KINDS:
        raise ValueError(f"finding kind must be one of {list(FINDING_KINDS)}")
    return "|".join([pf.id, kind, *map(str, parts)])


# The workbench contract (docs/WORKBENCHES.md §1). Every workbench module has
# ``summary(pf, version=None) -> {"workbench", "title", "cards": [card], "note"}`` (a few key
# findings; "note" says why there are none) and ``queue(pf, version=None) -> [look]`` (what is
# worth a look now). ``opens`` has the shape of ``Alert.opens``; ``focus`` says where inside the
# workbench the evidence is (a pointer, a tile, a sentence), so "open" lands on it.
CARD_KEYS = ("what", "text", "evidence", "source", "method", "threshold", "trust", "opens",
             "focus")
ITEM_KEYS = ("pointer", "what", "why", "evidence", "trust", "consequence", "opens", "focus",
             "source", "key", "month", "threshold")


def card(what: str, text: str, evidence: str, source: str, method: str, threshold: str,
         trust: str, opens: tuple = (), focus: dict | None = None) -> dict:
    """One finding card: the statement, its evidence label, the test it comes from, the method
    and its version, where its threshold comes from and how far to trust it (TRUST)."""
    if trust not in TRUST:
        raise ValueError(f"trust must be one of {list(TRUST)}")
    return dict(zip(CARD_KEYS, (what, text, evidence, source, method, threshold, trust,
                                tuple(opens), focus), strict=True))


def look(pointer: str | None, what: str, why: str, evidence: str, trust: str, consequence: int,
         opens: tuple = (), *, source: str, key: str, focus: dict | None = None,
         month: int | None = None, threshold: str = "") -> dict:
    """One look-here item of a workbench's queue: its pointer in the workbench (L5, T2, ...), why
    it is there, the evidence label, trust and consequence (as ``Alert``: 3 changes the picture of
    the disease, 2 may change care, 1 worth a look), and ``key``, its ``finding_key``."""
    if trust not in TRUST or consequence not in (1, 2, 3):
        raise ValueError("trust must be one of TRUST and consequence 1, 2 or 3")
    return dict(zip(ITEM_KEYS, (pointer, what, why, evidence, trust, consequence, tuple(opens),
                                focus, source, key, month, threshold), strict=True))


def report_markdown(pf: PatientFile, i: int, evidence: dict | None = None,
                    reviews: dict | None = None, sources: list[str] | tuple = (),
                    disagree: list[dict] | tuple = (), reducers: list[dict] | tuple = (),
                    summaries: dict | None = None, queue: list[dict] | None = None) -> str:
    """Report version ``i`` as one Markdown page: summary, alerts, every workbench's finding
    cards, the attention queue, the three kinds of finding, missing data, tests that disagree,
    what would reduce uncertainty, every placeholder, model and sources, and the reviewers' marks
    by finding kind. ``evidence`` maps "GENE CHANGE" to its CIViC items (None: the table couldn't
    load); ``reviews`` maps ``finding_key`` names to {"what", "mark", "by", "at"}; ``disagree``
    and ``reducers`` are ``muffle.crosstest``'s lists; ``summaries`` and ``queue`` are
    ``muffle.overview``'s. Variant names keep their stars and underscores (``esc``)."""
    from muffle.workbench.grammar import esc  # here, not at the top: grammar imports this module

    v, evidence, reviews = pf.versions[i], evidence or {}, reviews or {}
    when = "" if v.month is None else f" (month {v.month})"
    out = [f"# {pf.id} · report {v.label}", "", f"_{pf.title} · {pf.diagnosis}_", "",
           f"_{DISCLAIMER}_", ""]
    if pf.kind == "synthetic":
        out += [f"> {pf.note}", ""]
    out += ["## Summary", f"Latest in the record: {v.event}{when} [{OBSERVED}]", "",
            f"{v.summary}" + (f" [{INFERENCE}]" if v.risk else ""), "",
            "## SOS alerts in this version"]
    out += [f"- {esc(a.what)} [{a.evidence}; trust {a.trust}: {a.why_trust}]. Rule: {a.rule}. "
            f"Threshold: {a.threshold}." for a in v.alerts] or ["- none"]
    marks = {k: r for k, r in reviews.items() if k.startswith(pf.id + "|")}
    if summaries:
        out += ["", "## Findings by workbench"]
    for s in (summaries or {}).values():
        out += ["", f"### {s['title']}"] + [
            f"- **{c['what']}**: {esc(c['text'])} [{c['evidence']}; trust {c['trust']}]. Source: "
            f"{c['source']}. Method: {c['method']}. Threshold: {c['threshold']}."
            for c in s["cards"]] + ([f"- {s['note']}"] if s.get("note") else [])
    if queue is not None:
        out += ["", f"## Attention queue ({QUEUE_ORDER})"]
        out += [f"{x['n']}. [{x['label']}] " + (f"{esc(x['pointer'])} · " if x["pointer"] else "")
                + f"{esc(x['what'])} [{x['evidence']}; trust {x['trust']}; consequence "
                f"{x['consequence']}]: {esc(x['why'])}"
                + (f" What would settle it: {esc(x['settle'])}" if x["settle"] else "")
                + (f" Also raised by {', '.join(x['also'])}." if x["also"] else "")
                + (f" Review: {marks[x['key']]['mark']}." if x["key"] in marks else "")
                for x in queue] or ["- nothing needs attention"]
    out += ["", f"## Observed [{OBSERVED}]"] + [f"- {k}: {esc(val)}" for k, val in v.observed]
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
            out.append(f"- {esc(var)}: " + ("CIViC not available here" if items is None else
                                       "no CIViC breast cancer evidence"))
        out += [f"- {esc(var)} · CIViC level {e['evidence_level']} ({e['level_meaning']}) · "
                f"{e['therapies'].replace(',', ', ')} · {str(e['significance']).lower()} · "
                f"{e['citation']} {e['url']}" for e in items or []]
    if not sequencing_tests(pf, i):
        out.append("- Not sequenced: no treatment evidence")
    out += ["", "## Missing data and what it limits"]
    out += [f"- {m}" for m in missing_data(pf, i)]
    if disagree:
        out += ["", "## Tests that disagree"] + [
            f"- {esc(d['what'])} [{d['evidence']}" + (f"; trust {d['trust']}" if "trust" in d
                                                      else "")
            + f"]: {esc(d['why'])} Sources: {' vs '.join(d['sources'])}. What would settle it: "
            f"{d['would_settle']}" + (f" Basis: {d['basis']}." if d.get("basis") and d["basis"]
                                     not in d["would_settle"] else "") for d in disagree]
    if reducers:
        out += ["", f"## What would reduce uncertainty [{HYPOTHESIS}; evidence, not an order]"]
        out += [f"- {esc(r['open_question'])} → {r['test']}: {esc(r['expectation'])} (source: "
                f"{r['source']})" for r in reducers]
    placeholders = [  # the rules this file's alerts use; a TCGA file has no alerts
        f"An alert when the 12-month risk rises at least {RISK_JUMP} points",
        "Alert order: consequence × trust, with trust weights "
        + ", ".join(f"{k} {w:g}" for k, w in TRUST.items())] if pf.kind == "synthetic" else []
    if queue is not None:  # the queue's order, then every placeholder threshold shown above
        placeholders.append(f"Attention queue: {QUEUE_ORDER}")
        placeholders += list(dict.fromkeys(
            f"{esc(x['what'])}: {x['threshold']}" for x in [
                *(c for s in (summaries or {}).values() for c in s["cards"]), *queue]
            if "placeholder" in x["threshold"].lower()))
    out += ["", "## Placeholders (not validated)"] + [f"- {p}" for p in placeholders or ["none"]]
    out += ["", "## Model and sources",
            f"- {pf.model['name']} ({pf.model['status']}); endpoint: {pf.model['endpoint']}"]
    out += [f"- {s}" for s in sources]
    imports = [w for w in pf.versions[: i + 1] if w.imported]
    if imports:
        out += ["", "## Imported in this session (kept for this browser session only)"]
        out += [f"- {w.label}: {esc(w.event)}; tests: " + ", ".join(
            f"{t.kind} {esc(t.name)} ({t.status})" for t in w.tests) for w in imports]
    out += ["", "## Review marks"] + ([] if marks else ["- none"])
    for kind in FINDING_KINDS:  # by kind: alerts, CIViC items, lab values, slide tiles, ...
        mine = [r for k, r in marks.items() if k.split("|")[1] == kind]
        out += [f"### {kind}"] * bool(mine) + [
            f"- {esc(r['what'])}: {r['mark']} ({r['by'] or 'no initials'}, {r['at']})"
            for r in mine]
    return "\n".join(out) + "\n"

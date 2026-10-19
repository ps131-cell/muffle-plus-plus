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

from dataclasses import dataclass, field

from muffle.demo import ordinal
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED, age_band
from muffle.timeline import EVENTS, PATIENT_ID

IMPLEMENTED, VALIDATED, PLANNED = "implemented", "experimentally validated", "planned"

MARKERS = {"ca153": ("CA 15-3", "U/mL"), "cea": ("CEA", "ng/mL")}
# Reference limits as the record states them. SYNTHETIC-001's first lab report reads
# "reference below 30"; CEA has none in the record, so it never raises an alert.
REFERENCE_LIMITS = {"ca153": (30.0, "the record's lab report (month -2)")}
RISE = 0.25    # PLACEHOLDER: a marker rise worth an alert, not validated
RISK_JUMP = 20  # PLACEHOLDER: a rise in 12-month risk (points) worth an alert, not validated

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


@dataclass
class Test:
    kind: str        # Lab, Imaging, Sequencing, Pathology report, Clinical record, Data layer, ...
    month: int | None
    name: str
    result: str
    workbench: str   # labs, mutations, omics, record, imaging, slides
    status: str      # status of that workbench: implemented or planned


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
    if e["kind"] == "Diagnosis":
        out.append(Test("Pathology report", m, "Diagnosis", e["text"], "slides", PLANNED))
    if e["kind"] == "Imaging":
        out.append(Test("Imaging", m, "Imaging report", e["text"], "imaging", PLANNED))
    if "mutations" in e:
        found = ", ".join(f"{g} {c}" for g, c in e["mutations"]) or "no panel driver mutated"
        out.append(Test("Sequencing", m, "Tumor sequencing", found, "mutations", IMPLEMENTED))
    for key, (name, unit) in MARKERS.items():
        if key in e:
            out.append(Test("Lab", m, name, f"{e[key]:g} {unit}", "labs", IMPLEMENTED))
    return out


def synthetic_file(tl: dict, events: list[dict] = EVENTS) -> PatientFile:
    """SYNTHETIC-001 with one report version per event of its record. ``tl`` is
    ``app/timeline_synthetic.json``, whose updates are row-aligned with ``events``."""
    evidence, versions = tl.get("evidence", {}), []
    seen_sites, seen_drivers, last = set(), set(), {}
    for e, u in zip(events, tl["updates"], strict=True):
        m, alerts = e["month"], []
        source = f"{e['kind']}, month {m}"
        if e.get("progression"):
            alerts.append(Alert(f"Progression on imaging: {e['text']}", m, source, OBSERVED,
                                "the imaging report reads progression", "none: recorded"))
        for site in e.get("sites", []):
            if site not in seen_sites:
                seen_sites.add(site)
                alerts.append(Alert(f"New metastatic site: {site.lower()}", m, source, OBSERVED,
                                    "a site not in the record before", "none: recorded"))
        for key, (name, unit) in MARKERS.items():
            if key not in e:
                continue
            value, before = float(e[key]), last.get(key)
            last[key] = value
            limit = REFERENCE_LIMITS.get(key)
            if limit and before and value > limit[0] and value >= before * (1 + RISE):
                alerts.append(Alert(
                    f"{name} rose from {before:g} to {value:g} {unit} ({value / before - 1:+.0%}),"
                    f" above the reference limit of {limit[0]:g}", m, f"{name}, month {m}",
                    OBSERVED, f"above the reference limit and at least {RISE:.0%} above the "
                    "previous value", f"limit from {limit[1]}; {RISE:.0%} rise is a placeholder"))
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
                    "CIViC curated evidence levels"))
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
                    "result", "placeholder"))
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


def case_file(case, c_index: float | None = None) -> PatientFile:
    """A held-out TCGA case (``muffle.demo.Case``): one report version, its data layers and
    mutation panel as tests, and no alerts, since nothing earlier exists to compare with."""
    muts = None if case.mutations is None else [m.replace(" p.", " ") for m in case.mutations]
    tests = [Test("Clinical record" if m == "clinical" else "Data layer", None, ASSAYS[m],
                  "measured", "record" if m == "clinical" else "omics", IMPLEMENTED)
             for m in case.layers]
    if muts is not None:
        tests.append(Test("Mutation panel", None, "Somatic mutations, 16 breast cancer drivers "
                          "(exome sequencing)", ", ".join(muts) or "none of the panel's genes "
                          "mutated", "mutations", IMPLEMENTED))
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

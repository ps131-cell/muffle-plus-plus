"""Learning from clinicians, first version (docs/VISION.md part four; docs/feedback.md): the review
marks a clinician makes become a ledger they can see, export and load again, and the share of
findings they disagreed with, per model or rule, is the signal a future training round would use.

Nothing here trains, re-calibrates or changes a model. The marks stay in the browser session
(``st.session_state.reviews``: ``workspace.finding_key`` -> {"what", "mark", "by", "at"}) and in
the files the clinician downloads; storing a mark, updating a research dataset and retraining a
model are different steps, and the last two are roadmap (consent, ethics approval and data
agreements first).

A mark stores only the finding's words, so the model or rule behind it comes from the finding's
key: its kind and parts (``workspace.FINDING_KINDS``) name one entry of ``SOURCES``, with the
card it has on the Methods and validation page, its version where the code names one, what it
reads and the finding's evidence label.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime

from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.timeline import PATIENT_ID
from muffle.workbench.documents import RULES_VERSION as DOCUMENT_RULES
from muffle.workspace import ASSAYS, FINDING_KINDS, MARKS, PatientFile

SCHEMA = "muffle-feedback/1"
MAX_BYTES = 2_000_000  # an upload larger than this is refused before it is read
MAX_RECORDS = 5000
REVIEWER_CHARS = 5     # the sidebar's "Reviewer initials" field
WHEN = "%Y-%m-%d %H:%M"
DISAGREE = "disagree"
ROADMAP = "planned (roadmap): not running; needs consent, ethics approval and data agreements"

# Methods and validation headings the per-card lines go under (app/methods_page.py)
SURVIVAL, LANDMARK = "Multi-omic survival model", "MSK-CHORD landmark models"
SLIDES, ALERTS = "Breast tissue head (pathology slides)", "SOS alerts and their order"
LABS, CTDNA = "Lab result rules", "ctDNA monitor rules"
GENOMICS = "Genomics: detection, interpretation and evidence"
OMICS, DOCUMENTS = "Expression, methylation and protein scores", "Clinical documents"
EVOLUTION, RADIOLOGY = "Tumor evolution and treatment evidence", "Radiology"


@dataclass(frozen=True)
class Source:
    """A model or rule behind findings: its Methods card, model or rule, version and inputs."""
    card: str
    type: str      # "model" or "rule"
    version: str   # as the code names it; "app build" when it names none
    inputs: str    # what it reads, in words (never the patient's values)


SOURCES = {
    "Multi-omic survival model": Source(
        SURVIVAL, "model", "FedAvg clinical-anchored residual model, the loaded bundle",
        "the TCGA tumor sample's data layers (copy number, RNA, methylation, protein, clinical)"),
    "MSK-CHORD landmark models": Source(
        LANDMARK, "model", "gradient boosting, 5 seeds, app/timeline_synthetic.json",
        "the synthetic record so far (stage, receptors, treatments, markers, sites)"),
    "Risk jump alert": Source(
        ALERTS, "rule", "placeholder threshold, app build",
        "two consecutive 12-month risk estimates of the landmark models"),
    "Tumor marker rise (EGTM)": Source(
        ALERTS, "rule", "EGTM breast cancer recommendations, app build",
        "the record's tumor-marker values and the lab report's reference limit"),
    "Progression and new sites on imaging": Source(
        ALERTS, "rule", "app build", "the imaging report's words"),
    "Newly sequenced driver (CIViC A/B)": Source(
        ALERTS, "rule", "CIViC evidence levels, app build",
        "the sequenced variants and their CIViC items"),
    "Tests that disagree (cross-test rules)": Source(
        ALERTS, "rule", "app build", "two tests' results in the file"),
    "CIViC treatment evidence": Source(
        GENOMICS, "rule", "CIViC (CC0) evidence table", "an observed variant's name"),
    "Variant calls": Source(
        GENOMICS, "rule", "as recorded or imported (no caller runs here)",
        "the sequencing test's variant list"),
    "Copy-number calls (ASCAT3)": Source(
        GENOMICS, "rule", "placeholder cutoffs, app build",
        "gene-level copy number and the tumor ploidy"),
    "Genomics pathway map": Source(
        GENOMICS, "rule", "cited pathway membership, app build", "the observed variants"),
    "Lab result rules": Source(
        LABS, "rule", "lab workbench rules, app build",
        "the record's lab values and their reference intervals"),
    "ctDNA monitor rules": Source(
        CTDNA, "rule", "ctDNA rules, app build", "the synthetic series' allele fractions"),
    "Slide tile findings": Source(
        SLIDES, "model", "QuiltNet-B-32 with the five-class breast tissue head, StarDist nuclei "
        "and the slide rules, precomputed offline", "the diagnostic section's tiles"),
    "PAM50 subtype call": Source(
        OMICS, "model", "nearest centroid (Parker et al. 2009), ER-balanced centering",
        "the tumor's RNA expression"),
    "Receptor consistency": Source(
        OMICS, "rule", "cutoffs calibrated in-sample, app build",
        "recorded receptor status, RNA, copy number and RPPA"),
    "Pathway and immune scores": Source(
        OMICS, "model", "Hallmark v2025.1 and ESTIMATE gene lists, z-score averages",
        "the tumor's RNA expression"),
    "Data-layer features": Source(
        OMICS, "rule", "cohort percentiles, the loaded bundle",
        "one measured feature of a data layer"),
    "Protein pathways (RPPA)": Source(
        OMICS, "model", "Akbani et al. 2014 members and signs", "the tumor's RPPA antibodies"),
    "Promoter methylation calls": Source(
        OMICS, "rule", "placeholder cutoffs, app build", "450K promoter CpGs"),
    "Clinical document extraction": Source(
        DOCUMENTS, "rule", DOCUMENT_RULES, "the document's text"),
    "Evolution table": Source(
        EVOLUTION, "rule", "18 cited context → event rows, app build",
        "the file's treatments, receptor status and drivers"),
    "Trial matching": Source(
        EVOLUTION, "rule", "ClinicalTrials.gov snapshot", "the file's observed genes"),
    "Radiology report reading": Source(
        RADIOLOGY, "rule", "report reading rules, app build", "the imaging report's words"),
    "Radiology image models": Source(
        RADIOLOGY, "model", "MedSAM ViT-B, mammoscreen and MONAI, precomputed offline",
        "the public TCIA study's images"),
}
INFERRED_RULES = {"PAM50 basal-like vs ER-positive", "slide immune vs RNA immune",
                  "risk vs markers"}


def parse(key: str) -> tuple[str, str, list[str]]:
    """A ``finding_key`` as (patient id, kind, parts)."""
    pid, kind, *parts = key.split("|")
    return pid, kind, parts


def source_of(key: str, what: str = "") -> tuple[str, str]:
    """The model or rule behind a finding (a ``SOURCES`` name) and its evidence label, from its
    key (and, for an SOS alert, its words)."""
    pid, kind, parts = parse(key)
    head = parts[0] if parts else ""
    if kind == "alert":
        if what.startswith("12-month risk"):
            return "Risk jump alert", INFERENCE
        if what.startswith("Newly sequenced driver"):
            return "Newly sequenced driver (CIViC A/B)", \
                f"{OBSERVED} (mutation), {HYPOTHESIS} (treatment evidence)"
        if "rose from" in what:
            return "Tumor marker rise (EGTM)", OBSERVED
        return "Progression and new sites on imaging", OBSERVED
    if kind == "risk":
        return ("MSK-CHORD landmark models" if pid == PATIENT_ID else
                "Multi-omic survival model"), INFERENCE
    if kind == "discrepancy":
        return "Tests that disagree (cross-test rules)", (
            f"{OBSERVED}, {INFERENCE}" if head in INFERRED_RULES else
            f"{OBSERVED}, {HYPOTHESIS}" if head == "evidence vs treatment" else OBSERVED)
    if kind == "omics":
        if head == "subtype":
            return "PAM50 subtype call", INFERENCE
        if head == "receptor":
            return "Receptor consistency", INFERENCE
        if head in ("pathway", "score", "immune"):
            return "Pathway and immune scores", INFERENCE
        return "Data-layer features", OBSERVED  # a measured value and its cohort percentile
    if kind == "methylation":
        return "Promoter methylation calls", HYPOTHESIS if head == "index" else INFERENCE
    if kind == "evolution":
        return ("Trial matching" if head == "trial" else "Evolution table"), HYPOTHESIS
    if kind == "imaging":
        return (("Radiology report reading", OBSERVED) if head == "report" else
                ("Radiology image models", INFERENCE))
    if kind == "cn":
        return "Copy-number calls (ASCAT3)", (f"{OBSERVED} (copies), {INFERENCE} (ploidy)"
                                             if head == "ploidy estimate" else OBSERVED)
    return {"civic": ("CIViC treatment evidence", HYPOTHESIS),
            "lab": ("Lab result rules", OBSERVED),
            "variant": ("Variant calls", OBSERVED),
            "slide": ("Slide tile findings", INFERENCE),
            "pathway_protein": ("Protein pathways (RPPA)", INFERENCE),
            "document": ("Clinical document extraction", OBSERVED),
            "ctdna": ("ctDNA monitor rules", OBSERVED),
            "pathway": ("Genomics pathway map", HYPOTHESIS)}[kind]


def _patient_kind(pid: str, files: dict | None) -> str:
    if files and pid in files:
        return files[pid].kind
    return "synthetic" if pid == PATIENT_ID else "TCGA-BRCA"


def ledger(reviews: dict, files: dict[str, PatientFile] | None = None,
           build: str = "") -> list[dict]:
    """One record per mark (the export's schema, docs/feedback.md), newest first: the patient,
    the finding (its kind, words and key), the mark, the reviewer and time, the model or rule
    behind it with its version and inputs, and its evidence label. ``build`` is the app build
    the marks were made under (a source names its version as "app build" when the code gives it
    none)."""
    out = []
    for key, r in reviews.items():
        pid, kind, parts = parse(key)
        if kind not in FINDING_KINDS:
            continue
        name, evidence = source_of(key, r["what"])
        s = SOURCES[name]
        out.append({
            "schema": SCHEMA, "patient": pid, "patient_kind": _patient_kind(pid, files),
            "kind": kind, "finding": r["what"], "key": key, "parts": parts, "mark": r["mark"],
            "reviewer": r.get("by") or "", "at": r["at"], "method": name,
            "method_type": s.type, "method_version": s.version.replace(
                "app build", f"app build {build}" if build else "app build"),
            "methods_card": s.card, "inputs": s.inputs, "evidence": evidence})
    return sorted(out, key=lambda x: (x["at"], x["key"]), reverse=True)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """The 95% Wilson interval of a proportion k/n ((0, 1) when n is 0): a few marks say little,
    and the interval says how little."""
    if not n:
        return 0.0, 1.0
    p, d = k / n, 1 + z * z / n
    mid, half = (p + z * z / (2 * n)) / d, z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return max(0.0, mid - half), min(1.0, mid + half)


def rates(records: list[dict], by: str = "method") -> list[dict]:
    """Counts per mark and the disagreement rate, grouped by ``by`` ("method", "kind",
    "methods_card" or "reviewer"): every mark counts as a reviewed finding; the rate is
    disagree / reviewed with its 95% Wilson interval. Most disagreed first."""
    groups: dict[str, dict] = {}
    for x in records:
        g = groups.setdefault(x[by], {by: x[by], **{m: 0 for m in MARKS}, "n": 0})
        g[x["mark"]] += 1
        g["n"] += 1
    for g in groups.values():
        g["rate"] = g[DISAGREE] / g["n"]
        g["low"], g["high"] = wilson(g[DISAGREE], g["n"])
    return sorted(groups.values(), key=lambda g: (-g["rate"], -g["n"], str(g[by])))


def line(records: list[dict], card: str) -> str:
    """The per-card line of the Methods page: "N findings reviewed, M disagreed this session"."""
    mine = [x for x in records if x["methods_card"] == card]
    n, m = len(mine), sum(x["mark"] == DISAGREE for x in mine)
    return (f"{n} finding{'s' if n != 1 else ''} reviewed, {m} disagreed this session"
            + (f" ({', '.join(sorted({x['method'] for x in mine}))})" if n else ""))


def disagreed(records: list[dict]) -> list[dict]:
    """The findings clinicians disagreed with, newest first."""
    return [x for x in records if x["mark"] == DISAGREE]


def reviewers(records: list[dict]) -> list[dict]:
    """Per reviewer: marks of each kind, patients, the first and last mark."""
    out = {}
    for x in sorted(records, key=lambda x: x["at"]):
        r = out.setdefault(x["reviewer"], {"reviewer": x["reviewer"] or "no initials",
                                           **{m: 0 for m in MARKS}, "n": 0, "patients": set(),
                                           "first": x["at"]})
        r[x["mark"]] += 1
        r["n"] += 1
        r["patients"].add(x["patient"])
        r["last"] = x["at"]
    return [{**r, "patients": len(r["patients"])} for r in out.values()]


def target(pf: PatientFile, key: str) -> tuple[tuple, dict | None] | None:
    """Where "open" lands for a finding: (``opens``, the shape of ``workspace.Alert.opens``;
    ``focus``, as a workbench's queue item gives it), found in the file's tests; None when the
    file no longer holds it (an import from another session, say)."""
    _, kind, parts = parse(key)
    tests = pf.tests

    def test(workbench: str, ok=lambda t: True):
        return next((t for t in tests if t.workbench == workbench and ok(t)), None)

    def opens(t) -> tuple:
        return ("Tests", t.kind, t.month, t.name)

    def month(s: str):
        return None if s in ("None", "") else int(s) if s.lstrip("-").isdigit() else s

    if kind == "alert":
        a = next((a for v in pf.versions for a in v.alerts
                  if str(a.month) == parts[0] and a.what == "|".join(parts[1:])), None)
        return (a.opens, None) if a and a.opens else None
    if kind in ("risk", "discrepancy"):
        return ("Report",), None
    if kind == "evolution":
        return ("Evolution",), None
    found, focus = None, None
    if kind == "lab":
        found = test("labs", lambda t: t.details.get("marker") == parts[0]
                     and t.month == month(parts[1]))
        focus = {"marker": parts[0], "month": month(parts[1])}
    elif kind in ("variant", "civic"):
        found = test("mutations", lambda t: parts[0] in t.details.get("variants", ())
                     and (kind == "civic" or t.month == month(parts[1])))
        focus = {"variant": parts[0]}
    elif kind in ("cn", "pathway"):
        found = test("mutations")
        focus = {"gene": parts[0]} if kind == "cn" and parts[0] != "ploidy estimate" else None
    elif kind == "slide":
        found = test("slides", lambda t: parts[0] in t.details.get("slides", ())) \
            or test("slides")
        focus = {"slide": parts[0]}
    elif kind in ("omics", "pathway_protein", "methylation"):
        layer = {"pathway_protein": "protein", "methylation": "methylation"}.get(
            kind, parts[0] if parts[0] in ASSAYS else "rna")
        found = test("omics", lambda t: t.details.get("layer") == layer) or test("omics") \
            or test("record")
        focus = {"omics": key}
    elif kind == "document":
        found = test("documents", lambda t: t.details.get("document") == parts[0]) \
            or test("documents")
    elif kind == "imaging":
        if parts[0] == "report":
            found = test("imaging", lambda t: "barcode" not in t.details
                         and t.month == month(parts[1]))
            site = parts[2] if len(parts) > 2 else "read"
            focus = None if site == "read" else {"site": site}
        else:
            found = test("imaging", lambda t: t.details.get("barcode") == parts[0])
    elif kind == "ctdna":
        found = test("ctdna", lambda t: t.month == month(parts[1])) or test("ctdna")
    return (opens(found), focus) if found else None


# --- export and import -------------------------------------------------------------------------
FIELDS = {"schema": str, "patient": str, "kind": str, "finding": str, "key": str, "mark": str,
          "reviewer": str, "at": str}


def export(records: list[dict]) -> str:
    """The ledger as a feedback dataset: JSON lines, one record per mark (docs/feedback.md)."""
    return "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in records)


def load(data: bytes, patients: set[str] | dict) -> tuple[dict, list[str]]:
    """A downloaded ledger read back, checked at the boundary: size, JSON, the schema version,
    each field's type, the finding kind, the mark, the time, a key that names this patient and
    kind, and a patient id this app holds. Returns (marks in the reviews store's shape, keyed by
    finding key; one reason per rejected line). The rest of a record (method, version, inputs)
    is derived again from the key, never trusted from the file."""
    if len(data) > MAX_BYTES:
        return {}, [f"the file is larger than {MAX_BYTES // 1_000_000} MB"]
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {}, ["the file is not UTF-8 text"]
    lines = [s for s in text.splitlines() if s.strip()]
    if len(lines) > MAX_RECORDS:
        return {}, [f"more than {MAX_RECORDS} records"]
    marks, rejected = {}, []
    for n, raw in enumerate(lines, 1):
        why = None
        try:
            x = json.loads(raw)
        except json.JSONDecodeError:
            x, why = None, "not JSON"
        if why is None and not isinstance(x, dict):
            why = "not a record"
        elif why is None:
            why = next((f"{f} missing or not text" for f, t in FIELDS.items()
                        if not isinstance(x.get(f), t)), None)
        if why is None:
            pid, kind, parts = parse(x["key"])
            if x["schema"] != SCHEMA:
                why = f"schema {x['schema']!r}, expected {SCHEMA!r}"
            elif x["patient"] not in patients:
                why = f"patient {x['patient']!r} is not in this app"
            elif x["kind"] not in FINDING_KINDS:
                why = f"finding kind {x['kind']!r} unknown"
            elif (pid, kind) != (x["patient"], x["kind"]) or not parts:
                why = "the key does not name this patient and finding kind"
            elif x["mark"] not in MARKS:
                why = f"mark {x['mark']!r} unknown"
            elif len(x["reviewer"]) > REVIEWER_CHARS:
                why = f"reviewer initials longer than {REVIEWER_CHARS} characters"
            else:
                try:
                    datetime.strptime(x["at"], WHEN)
                except ValueError:
                    why = f"time {x['at']!r} is not YYYY-MM-DD HH:MM"
        if why:
            rejected.append(f"line {n}: {why}")
            continue
        if x["key"] not in marks or x["at"] > marks[x["key"]]["at"]:
            marks[x["key"]] = {"what": x["finding"], "mark": x["mark"], "by": x["reviewer"],
                               "at": x["at"]}
    return marks, rejected


def merge(reviews: dict, loaded: dict) -> tuple[dict, int, int]:
    """``reviews`` with the loaded marks added: for a finding marked in both, the later mark
    wins (the session's on a tie). Returns (the merged store, added, replaced)."""
    out, added, replaced = dict(reviews), 0, 0
    for key, r in loaded.items():
        if key not in out:
            added += 1
        elif r["at"] > out[key]["at"]:
            replaced += 1
        else:
            continue
        out[key] = r
    return out, added, replaced


# --- the report's Feedback section -------------------------------------------------------------
def report_section(reviews: dict, pid: str, esc=str) -> list[str]:
    """Markdown lines for the report export: this patient's marks counted per finding kind and
    the findings marked disagree, with the model or rule behind each (``esc`` escapes a
    finding's words for Markdown)."""
    records = [x for x in ledger(reviews) if x["patient"] == pid]
    out = ["## Feedback (clinician marks in this session; nothing is sent or trained)"]
    if not records:
        return out + ["- no marks"]
    for g in sorted(rates(records, "kind"), key=lambda g: g["kind"]):
        out.append(f"- {g['kind']}: {g['n']} marked (" + ", ".join(
            f"{g[m]} {m}" for m in MARKS if g[m]) + ")")
    bad = disagreed(records)
    out += ["", f"Disagreed: {len(bad)}"] + [
        f"- {esc(x['finding'])} [{x['kind']}; {x['method']}; {x['evidence']}] "
        f"({x['reviewer'] or 'no initials'}, {x['at']})" for x in bad]
    return out

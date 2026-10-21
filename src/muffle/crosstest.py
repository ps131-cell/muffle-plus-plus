"""Cross-test intelligence for a patient file (docs/WORKBENCHES.md §2 and §9): the version diff
in the three evidence columns, the discrepancy queue and "what would reduce uncertainty".

Pure functions over ``muffle.workspace.PatientFile``. Nothing here runs a model: the rules read
the file's observed pairs, tests, alerts and risk estimates. Every item carries its evidence type,
and every threshold its source; a placeholder says so. Treatment content is evidence for the
clinician's judgment, phrased as a question, never a recommendation (CLAUDE.md).
"""

from __future__ import annotations

import re
from statistics import median

from muffle import evolution
from muffle.demo import ordinal
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workbench import documents, omics, slides
from muffle.workspace import ASSAYS, EGTM, MARKERS, RISK_JUMP, PatientFile, finding_key

CONFIRM = ("a marker rise is unconfirmed until a second specimen within a month confirms it "
           f"({EGTM})")
CTDNA_SOURCE = ("PADA-1 (Bidard et al., Lancet Oncol 2022) and SERENA-6 (Bidard et al., NEJM "
                "2025): ESR1 mutations emerging in blood under aromatase inhibitors were caught "
                "by ctDNA before progression (docs/VISION.md); hypothesis for this patient")
ENDOCRINE = {"letrozole", "anastrozole", "exemestane", "tamoxifen", "fulvestrant", "elacestrant",
             "camizestrant"}
SITES = ("bone", "liver", "lung", "brain", "pleura", "skin", "lymph node", "peritoneum", "adrenal")
IMAGING_AGE = 6  # months; PLACEHOLDER: when the latest imaging counts as old after a marker rise
CTDNA_CADENCE = 3  # months: SERENA-6 sampled ctDNA every 2 to 3 months (literature, CTDNA_SOURCE)
IMMUNE_HIGH = 75  # cohort percentile; PLACEHOLDER: a "high" immune RNA score against a slide desert
UNSURE_SHARE = 0.2  # PLACEHOLDER: a section share of unsure tiles worth a second model's opinion
# Cited bases (each PMID and DOI checked on PubMed, 2026-10-21)
HER2_GUIDE = ("ASCO/CAP HER2 testing guideline (Wolff et al., J Clin Oncol 2018;36:2105-22; "
              "PMID 29846122, doi:10.1200/JCO.2018.77.8738)")
ER_GUIDE = ("ASCO/CAP ER and PgR testing guideline (Allison et al., J Clin Oncol "
            "2020;38:1346-66; PMID 31928404, doi:10.1200/JCO.19.02309)")
SUBTYPE_SOURCE = ("intrinsic subtypes and IHC-based groups are related, not interchangeable "
                  "(Prat et al., Breast 2015;24 Suppl 2:S26-35; PMID 26253814, "
                  "doi:10.1016/j.breast.2015.07.008)")
TILS_SOURCE = ("International TILs Working Group recommendations (Salgado et al., Ann Oncol "
               "2015;26:259-71; PMID 25214542, doi:10.1093/annonc/mdu450)")

MARKER_NAMES = [name for name, _ in MARKERS.values()]
MARKER_KEYS = {name: key for key, (name, _) in MARKERS.items()}
_RISE = re.compile(r"from (\S+) to (\S+)")
_DRIVER = re.compile(r"driver (\S+ \S+) has")


# ----------------------------------------------------------------------------- version diff

def _findings(pf: PatientFile, i: int) -> dict[str, dict[str, str]]:
    """Version i as {column: {finding: value}}. Tests accumulate (a test stays in the file);
    observed pairs, alerts and the risk estimate are the version's own."""
    v = pf.versions[i]
    cols: dict[str, dict[str, str]] = {OBSERVED: {}, INFERENCE: {}, HYPOTHESIS: {}}
    for name, value in v.observed:
        cols[OBSERVED][name] = value
    for t in (t for ver in pf.versions[:i + 1] for t in ver.tests):
        when = "" if t.month is None else f" (month {t.month})"
        cols[OBSERVED][f"{t.kind}: {t.name}{when}"] = t.result
    for a in v.alerts:
        col = (HYPOTHESIS if HYPOTHESIS in a.evidence
               else INFERENCE if a.evidence == INFERENCE else OBSERVED)
        cols[col][f"Alert: {a.what}"] = f"{a.source}; rule: {a.rule}"
    r = v.risk or {}
    if "value" in r:
        lo, hi = r["range"]
        cols[INFERENCE]["12-month risk"] = f"{r['value']:.0%}"
        cols[INFERENCE]["Risk range across seeds"] = f"{lo:.0%} to {hi:.0%}"
        cols[INFERENCE]["Diagnosis-only baseline"] = f"{r['baseline']:.0%}"
        cols[INFERENCE]["Landmark model"] = f"month-{r['landmark']} model"
    if "percentile" in r:
        cols[INFERENCE]["Cohort percentile"] = ordinal(r["percentile"])
        cols[INFERENCE]["Risk group"] = str(r["group"])
    return cols


def diff_versions(pf: PatientFile, a: int, b: int) -> list[dict]:
    """What differs between ``pf.versions[a]`` and ``pf.versions[b]``, per evidence column.
    Unchanged findings are left out; the attribution (``versions[b].changes``) is the shell's."""
    before, after, out = _findings(pf, a), _findings(pf, b), []
    for col in (OBSERVED, INFERENCE, HYPOTHESIS):
        for finding in dict.fromkeys([*before[col], *after[col]]):
            x, y = before[col].get(finding), after[col].get(finding)
            if x == y:
                continue
            status = "added" if x is None else "removed" if y is None else "changed"
            out.append({"column": col, "finding": finding, "before": x, "after": y,
                        "status": status})
    return out


# --------------------------------------------------------------------------- shared lookups

def _marker_rises(pf: PatientFile, i: int) -> list[tuple]:
    """(version index, alert, marker name, before, after) for every marker-rise alert so far."""
    out = []
    for j, v in enumerate(pf.versions[:i + 1]):
        for a in v.alerts:
            name = next((n for n in MARKER_NAMES if a.source.startswith(n)), None)
            if name and a.evidence == OBSERVED:
                m = _RISE.search(a.what)
                vals = (float(m.group(1)), float(m.group(2))) if m else (None, None)
                out.append((j, a, name, *vals))
    return out


def _imaging(pf: PatientFile, i: int) -> list[tuple[int, str]]:
    return [(t.month, t.result) for v in pf.versions[:i + 1] for t in v.tests
            if t.kind == "Imaging" and t.month is not None]


def _labs(pf: PatientFile, i: int, name: str) -> list[tuple[int, float]]:
    """(month, value) of one marker's Lab tests so far; the result reads '<value> <unit>'."""
    out = []
    for v in pf.versions[:i + 1]:
        for t in v.tests:
            if t.kind == "Lab" and t.name == name and t.month is not None:
                try:
                    out.append((t.month, float(t.result.split()[0])))
                except ValueError:
                    pass
    return out


def _driver_alerts(pf: PatientFile, i: int) -> list[tuple[int, object, str]]:
    """(version index, alert, variant) for sequenced drivers with level A or B evidence."""
    out = []
    for j, v in enumerate(pf.versions[:i + 1]):
        for a in v.alerts:
            if HYPOTHESIS in a.evidence and ("level A" in a.what or "level B" in a.what):
                m = _DRIVER.search(a.what)
                out.append((j, a, m.group(1) if m else a.what))
    return out


def _status(threshold: str) -> str:
    """Call a threshold a placeholder only when its own source says so."""
    return " (a placeholder, not validated)" if "placeholder" in threshold else ""


def _sites(text: str) -> set[str]:
    low = text.lower()
    return {s for s in SITES if s in low}


# ------------------------------------------------------------------------ discrepancy queue

def _item(pf: PatientFile, rule: str, about, what: str, sources: list[str], months: list,
          why: str, would_settle: str, evidence: str, trust: str, consequence: int,
          opens: tuple = (), focus: dict | None = None, basis: str = "",
          key: str | None = None) -> dict:
    """One discrepancy: the two sources, why they disagree, what would settle it, the evidence
    labels, the cited basis (if any), trust and consequence (as ``workspace.Alert``), where the
    evidence opens, and its ``finding_key`` (a workbench's own key when the same finding is in
    that workbench's queue)."""
    return {"what": what, "sources": sources, "months": months, "why": why,
            "would_settle": would_settle, "evidence": evidence, "rule": rule, "basis": basis,
            "trust": trust, "consequence": consequence, "opens": tuple(opens), "focus": focus,
            "key": key or finding_key(pf, "discrepancy", rule, about)}


def _lab_focus(name: str, month) -> dict:
    return {"marker": MARKER_KEYS.get(name), "month": month}


def _pos(value: str | None) -> bool | None:
    """A documented or recorded status as positive (True), negative (False) or neither."""
    v = (value or "").lower()
    if v.startswith(("positive", "amplified")):
        return True
    return False if v.startswith(("negative", "not amplified")) else None


def _stage_group(text: str | None) -> str | None:
    """"II" from "Stage IIA", "IIB", "stage II, HR+, ..." or "II"; None when there is none."""
    m = re.search(r"(?:stage\s+)?\b(IV|I{1,3})[ABC]?\b", text or "", re.I)
    return m.group(1).upper() if m else None


def _recorded_stage(pf: PatientFile, i: int) -> str | None:
    obs = dict(pf.versions[i].observed)
    if "Stage" in obs:  # a TCGA case's clinical record
        return _stage_group(obs["Stage"])
    m = re.search(r"stage\s+(\w+)", obs.get("Diagnosis", ""), re.I)  # the synthetic record
    return _stage_group(m.group(1)) if m else None


def _quote(f: dict) -> str:
    return "“" + f["quote"][:200] + "”"


def _receptor_rules(pf: PatientFile, i: int, first: dict, titles: dict) -> list[dict]:
    """ERBB2 copy number against the recorded or documented HER2 status; ESR1 RNA and ER-alpha
    protein against the recorded or documented ER status; PAM50 Basal-like with an ER-positive
    status; the documented receptor status against the recorded one."""
    cs, out = omics.case_scores(pf), []
    if cs is None:
        return out
    opens, rec = omics._opens(pf), cs["receptors"]
    lines = {(x["receptor"], x["compare"]): x for x in omics.file_lines(pf)}
    refs = []  # (receptor, polarity, where it comes from, recorded or documented, the fact)
    for name, field in (("ER", "er"), ("HER2", "her2"), ("PR", "pr")):
        status = (rec.get(name) or {}).get("status")
        if _pos(status) is not None:
            refs.append((name, _pos(status), f"{name} recorded {status.lower()} (TCGA clinical "
                         "data)", "recorded", None))
        # HER2: the ISH result first when a document states one (it settles an equivocal IHC);
        # a hormone-receptor status is not an ER status (it can be PR alone)
        said = [first.get(k) for k in (("her2_ish", "her2") if name == "HER2" else (field,))]
        f = next((f for f in said if f is not None and _pos(f["value"]) is not None), None)
        if f is not None:
            refs.append((name, _pos(f["value"]), f"{f['label']} {f['value']} (documented in "
                         f"{titles[f['doc']]})", "documented", f))

    def own_key(name: str, kind: str) -> str | None:
        """The omics workbench's key when this is its own disagreement line (one finding)."""
        line = lines.get((name.split(":")[0], name.split(": ")[1]))
        return (finding_key(pf, "omics", "receptor", name)
                if kind == "recorded" and line and line["status"] == omics.DISAGREE else None)

    for name, ref, where, kind, fact in refs:
        r = rec.get(name) or {}
        if name == "HER2" and r.get("cn"):
            cn = r["cn"]
            amp = cn["copies"] >= 2 * cn["ploidy"]
            if amp != ref:
                reads = "amplified" if amp else "not amplified"
                out.append(_item(
                    pf, "ERBB2 copy number vs HER2", kind,
                    f"ERBB2 copy number {reads}, {where}",
                    ["ERBB2 copy number (ASCAT3, TCGA)", where], [None, None],
                    f"ERBB2 at {cn['copies']:g} copies with a tumor ploidy of {cn['ploidy']:g} "
                    f"reads {reads} (at least twice the ploidy: a placeholder by analogy with the "
                    f"ISH ratio of 2.0, not validated on ASCAT calls), while {where}. Tumor "
                    "purity and the ploidy estimate move the copy number; IHC and ISH decide "
                    "HER2 status.",
                    "In situ hybridization on the tumor block (HER2/CEP17 ratio and HER2 copies "
                    f"per cell), read with the IHC: {HER2_GUIDE}.",
                    f"{OBSERVED} (ERBB2 copy number), {OBSERVED} ({kind} HER2 status)", "weak", 3,
                    opens, {"omics": finding_key(pf, "omics", "receptor",
                                                 "HER2: IHC vs copy number")},
                    HER2_GUIDE, own_key("HER2: IHC vs copy number", kind)))
        if name == "ER":
            measures = [(m, r[m]) for m in ("rna", "protein") if r.get(m)]
            off = [(m, x) for m, x in measures if x["high"] != ref]
            if off:
                said = "; ".join(
                    f"{'ESR1 RNA' if m == 'rna' else 'ER-alpha protein (RPPA)'} at the "
                    f"{ordinal(x['pct'])} percentile, {'above' if x['high'] else 'below'} its "
                    "cutoff" for m, x in measures)
                out.append(_item(
                    pf, "ER RNA and protein vs ER status", kind,
                    f"{where}; " + ", ".join(
                        f"{'ESR1 RNA' if m == 'rna' else 'ER-alpha protein'} "
                        f"{'high' if x['high'] else 'low'}" for m, x in off),
                    [where, "ESR1 RNA and ER-alpha protein (TCGA, cohort percentiles)"],
                    [None, None],
                    f"{said}; {where}. The cutoffs are calibrated in-sample on this cohort's "
                    "recorded IHC (Methods and validation); bulk RNA and protein include stroma "
                    "and immune cells, and RNA is not protein.",
                    "A repeat ER immunohistochemistry on the tumor block with its controls, "
                    "reporting the percentage of positive nuclei (1 to 10% is ER low positive): "
                    f"{ER_GUIDE}.",
                    f"{OBSERVED} ({kind} ER status), {OBSERVED} (RNA and protein levels; cutoffs "
                    "calibrated on this cohort)", "moderate", 3, opens,
                    {"omics": finding_key(pf, "omics", "receptor", "ER: IHC vs RNA")}, ER_GUIDE,
                    own_key("ER: IHC vs RNA", kind)))
        status = r.get("status")
        if kind == "documented" and _pos(status) is not None and _pos(status) != ref:
            out.append(_item(
                pf, "documented vs recorded receptor", name,
                f"{name}: {where}, recorded {status.lower()}",
                [where, f"{name} status, TCGA clinical data"], [None, None],
                f"The report reads {_quote(fact)}. TCGA's clinical field says {status.lower()}; "
                "it was abstracted from the whole record, so the report may describe another "
                "specimen, or one side is an error.",
                "A re-read of the source sentence (documents workbench); if it stands, a repeat "
                f"{'ISH' if name == 'HER2' else 'IHC'} on the block: "
                f"{HER2_GUIDE if name == 'HER2' else ER_GUIDE}.",
                f"{OBSERVED} (documented), {OBSERVED} (recorded)", "moderate",
                3 if name in ("ER", "HER2") else 2, documents.doc_opens(pf, i, fact["doc"]),
                {"doc": fact["doc"], "sentence": tuple(fact["sentence"])},
                documents.measured([fact["field"]])))
    sub = cs["pam50"]
    positive = [where for name, ref, where, *_ in refs if name == "ER" and ref]
    if sub["call"] == "Basal" and positive:
        out.append(_item(
            pf, "PAM50 basal-like vs ER-positive", "ER",
            "PAM50 Basal-like with an ER-positive status", [ASSAYS["rna"], positive[0]],
            [None, None],
            f"Bulk RNA is nearest the Basal-like centroid (margin {sub['margin']:.2f}; "
            f"{omics.published(sub)}) while {'; '.join(positive)}. A Basal-like call is unusual "
            f"with ER-positive disease: {SUBTYPE_SOURCE}.",
            "The ER read itself (the percentage of positive nuclei; ER low positive is 1 to 10%: "
            f"{ER_GUIDE}) and the tumor content of the sequenced sample.",
            f"{INFERENCE} (PAM50 call), {OBSERVED} (ER status)",
            "weak" if sub["margin"] < omics.LOW_MARGIN else "moderate", 2, opens,
            {"omics": finding_key(pf, "omics", "subtype", "PAM50")}, SUBTYPE_SOURCE))
    return out


def _slide_rules(pf: PatientFile, i: int) -> list[dict]:
    """A slide section read as an immune desert while the RNA's cytolytic score is high."""
    cs, out = omics.case_scores(pf), []
    if cs is None:
        return out
    pct = cs["scores"]["immune"][1]
    for s in slides.sections(pf, i):
        pattern = str(s["meta"].get("numbers", {}).get("immune_pattern", ""))
        if pattern.startswith("desert") and pct >= IMMUNE_HIGH:
            out.append(_item(
                pf, "slide immune vs RNA immune", s["slide"],
                f"Immune desert on section {s['slide']}, high immune score in the RNA",
                [f"Pathology slide {s['slide']}", ASSAYS["rna"]], [None, None],
                f"Section {s['slide']} reads '{pattern}' (stromal lymphocytes by zone, "
                f"placeholder cutoffs); the bulk RNA's cytolytic activity (GZMA, PRF1) is at the "
                f"{ordinal(pct)} percentile of this cohort (a high score from the "
                f"{ordinal(IMMUNE_HIGH)} percentile on is a placeholder). One section is one "
                "plane; the RNA came from another piece of the tumor.",
                f"A pathologist's stromal TILs read on the H&E section: {TILS_SOURCE}.",
                f"{INFERENCE} (slide immune pattern), {INFERENCE} (immune RNA score)", "weak", 1,
                s["opens"], {"slide": s["slide"]}, TILS_SOURCE))
    return out


def _document_rules(pf: PatientFile, i: int) -> tuple[list[dict], dict, dict]:
    """Documents that contradict each other, and documented stage, laterality or specimen type
    against the clinical record. Returns (items, each field's first fact, document titles)."""
    docs = documents.file_documents(pf, i)
    titles = {d["id"]: d["title"] for d in docs}
    facts = documents.facts(docs)
    first: dict[str, dict] = {}
    for f in facts:
        first.setdefault(f["field"], f)
    out = []
    for c in documents.conflicts(facts):
        doc = c["values"][0]["docs"][0]
        f = next(f for f in facts if f["field"] == c["field"] and f["doc"] == doc)
        out.append(_item(
            pf, "documents disagree", c["label"], f"{c['label']}: the documents disagree",
            [", ".join(titles[d] for d in v["docs"]) for v in c["values"]][:2], [None, None],
            "; ".join(f"{v['value']}: “{v['quotes'][0][:160]}”" for v in c["values"]),
            "A re-read of both source sentences; if both stand, which specimen each describes "
            "(biopsy or excision, which side) or an addendum.",
            f"{OBSERVED} (documented), {OBSERVED} (documented)", "moderate",
            2 if c["field"] in documents.KEY_FIELDS else 1, documents.doc_opens(pf, i, doc),
            {"doc": doc, "sentence": tuple(f["sentence"])}, documents.measured([c["field"]]),
            finding_key(pf, "document", "conflict", c["label"])))
    obs = dict(pf.versions[i].observed)
    stage, recorded = first.get("stage"), _recorded_stage(pf, i)
    if stage and recorded and _stage_group(stage["value"]) not in (None, recorded):
        out.append(_item(
            pf, "documented vs recorded", "stage",
            f"Stage: documented {stage['value']}, recorded {recorded}",
            [titles[stage["doc"]], "the clinical record's stage"], [None, None],
            f"The document reads {_quote(stage)}; the clinical record holds stage {recorded}. A "
            "clinical and a pathological stage, two staging editions, or an error on one side.",
            "A re-read of the source sentence and the staging edition behind the record's "
            "stage.", f"{OBSERVED} (documented), {OBSERVED} (recorded)", "moderate", 3,
            documents.doc_opens(pf, i, stage["doc"]),
            {"doc": stage["doc"], "sentence": tuple(stage["sentence"])},
            documents.measured(["stage"])))
    for field, row in (("laterality", "Laterality"), ("specimen", "Specimen type")):
        held = obs.get(row)
        differ = [f for f in facts if f["field"] == field and held and f["value"] != held.lower()]
        if differ:
            f = differ[0]
            out.append(_item(
                pf, "documented vs recorded", field,
                f"{f['label']}: documented {f['value']}, recorded {held}",
                [titles[f["doc"]], "the clinical record"], [None, None],
                f"The document reads {_quote(f)}; the record says {held}. Another specimen, the "
                "other side, or a document filed to the wrong record.",
                "A re-read of the document's header and specimen description against the "
                "record (patient, side, specimen).",
                f"{OBSERVED} (documented), {OBSERVED} (recorded)", "moderate", 2,
                documents.doc_opens(pf, i, f["doc"]),
                {"doc": f["doc"], "sentence": tuple(f["sentence"])},
                documents.measured([field])))
    return out, first, titles


def _import_rules(pf: PatientFile, i: int) -> list[dict]:
    """An imported lab value that differs from the record's value of that marker in the same
    month (intake rejects most of these; this catches the rest)."""
    recorded, out = {}, []
    for v in pf.versions[:i + 1]:
        for t in v.tests:
            if t.kind == "Lab" and "value" in t.details and not v.imported:
                recorded[(t.name, t.month)] = t
    for v in pf.versions[:i + 1]:
        for t in v.tests:
            r = recorded.get((t.name, t.month))
            if not (v.imported and t.kind == "Lab" and r and "value" in t.details):
                continue
            if t.details["value"] != r.details["value"]:
                out.append(_item(
                    pf, "imported vs recorded lab", f"{t.name} {t.month}",
                    f"{t.name} at month {t.month}: imported {t.result}, recorded {r.result}",
                    [f"{t.name}, month {t.month} ({v.imported.split(';')[0]})",
                     f"{t.name}, month {t.month} (the record)"], [t.month, t.month],
                    f"Two values of {t.name} for month {t.month}: {t.result} imported and "
                    f"{r.result} in the record. Two specimens in one month, or a transcription "
                    "error on one side.",
                    "The laboratory's own report for that month (specimen date and accession), "
                    "or a repeat specimen.", f"{OBSERVED} (imported), {OBSERVED} (recorded)",
                    "strong", 2, ("Tests", "Lab", t.month, t.name),
                    _lab_focus(t.name, t.month)))
    return out


def discrepancies(pf: PatientFile, i: int) -> list[dict]:
    """Tests that disagree as of version i. Each item names both sources, why that is a
    discrepancy, which test or document would settle it, the evidence labels, the cited basis
    when one exists, trust and consequence, and where its evidence opens."""
    out, v, now = [], pf.versions[i], pf.versions[i].month
    imaging = _imaging(pf, i)

    # 1. a marker rose while the latest imaging so far read stable
    if imaging:
        im_month, im_text = imaging[-1]
        for _, a, name, *_ in _marker_rises(pf, i):
            if "stable" in im_text.lower() and im_month < a.month:
                out.append(_item(
                    pf, "marker vs imaging", f"{name}, month {a.month}",
                    f"{name} rising while the latest imaging read stable",
                    [a.source, f"Imaging, month {im_month}"], [a.month, im_month],
                    f"{a.what} at month {a.month}, but the latest imaging (month "
                    f"{im_month}) read: {im_text}. A marker can move before imaging "
                    "shows a change, or a single rise can be transient; the alert's "
                    f"threshold: {a.threshold}{_status(a.threshold)}.",
                    f"A second {name} specimen within a month ({CONFIRM}) and the next imaging.",
                    OBSERVED, "moderate", 2, a.opens, _lab_focus(name, a.month), EGTM))

    # 2. the 12-month risk jumped while every marker measured in this version fell
    prev = pf.versions[i - 1] if i > 0 else None
    if prev and prev.risk and v.risk and "value" in v.risk and "value" in prev.risk:
        jump = 100 * (v.risk["value"] - prev.risk["value"])
        fell, rose = [], []
        for name in MARKER_NAMES:
            labs = _labs(pf, i, name)
            this = [(m, x) for m, x in labs if m == now]
            earlier = [x for m, x in labs if m < now]
            if this and earlier:
                (fell if this[-1][1] < earlier[-1] else rose).append(
                    f"{name} {earlier[-1]:g} to {this[-1][1]:g}")
        if jump >= RISK_JUMP and fell and not rose:
            out.append(_item(
                pf, "risk vs markers", now, "12-month risk up while the markers fell",
                [f"month-{v.risk.get('landmark')} model", f"Lab, month {now}"], [now, now],
                f"The model's 12-month risk rose {jump:+.0f} points since the previous "
                f"version ({prev.risk['value']:.0%} to {v.risk['value']:.0%}; alert "
                f"threshold {RISK_JUMP} points, a placeholder) while every marker measured "
                f"in this version fell ({', '.join(fell)}). The rise comes from other "
                "features (see what changed), not from the markers.",
                "The attribution under the report (which feature group moved the estimate) and "
                "the next imaging.", INFERENCE, "weak", 1, ("Timeline",)))

    # 3. two versions' summaries name different metastatic sites
    named = [(ver.month, _sites(ver.summary)) for ver in pf.versions[:i + 1]
             if _sites(ver.summary)]
    if len(named) >= 2:
        (m_old, old), (m_new, new) = named[-2], named[-1]
        missing = sorted(old - new)
        if missing:
            out.append(_item(
                pf, "sites in summaries", f"{m_old}-{m_new}",
                "Metastatic sites named differently in two report versions",
                [f"Summary, month {m_old}", f"Summary, month {m_new}"], [m_old, m_new],
                f"The month-{m_old} summary names {', '.join(sorted(old))}; the "
                f"month-{m_new} summary names {', '.join(sorted(new))} and no longer "
                f"{', '.join(missing)}. A site that disappears from a report is either a "
                "response or an omission.",
                "The imaging reports themselves (radiology workbench), read side by side.",
                OBSERVED, "moderate", 2, ("Timeline",)))

    # 4. a sequenced driver with level A/B evidence and no treatment change recorded after it
    for j, a, variant in _driver_alerts(pf, i):
        if not any(ver.treatments for ver in pf.versions[j + 1:i + 1]):
            out.append(_item(
                pf, "evidence vs treatment", variant,
                f"Level A/B evidence for {variant} with no treatment change recorded",
                [a.source, f"Clinical record, month {now}"], [a.month, now],
                f"{a.what} (month {a.month}); as of month {now} the record shows no "
                "treatment start after the sequencing. A question for the clinician: was "
                "the evidence reviewed, or is a decision recorded elsewhere? The evidence "
                "is CIViC's, for review, not a recommendation.",
                "The clinical record: a treatment entry or a note that the evidence was "
                "reviewed (CIViC, curated evidence levels).", HYPOTHESIS, "moderate", 2,
                a.opens, {"variant": variant}, "CIViC curated evidence levels"))

    # 5-11. receptors and subtype, the slide against the RNA, documents, imports
    docs, first, titles = _document_rules(pf, i)
    out += _receptor_rules(pf, i, first, titles) + _slide_rules(pf, i) + docs
    return out + _import_rules(pf, i)


# ---------------------------------------------------------------- what would reduce uncertainty

def uncertainty_reducers(pf: PatientFile, i: int) -> list[dict]:
    """Open hypotheses as of version i and the test that would resolve each: evidence for the
    clinician's judgment, never an instruction."""
    out, v, now = [], pf.versions[i], pf.versions[i].month

    if now is not None:
        # an unconfirmed marker rise: no later specimen of that marker yet
        for _, a, name, lo, hi in _marker_rises(pf, i):
            if not any(m > a.month for m, _ in _labs(pf, i, name)):
                expect = (f"a second value near {hi:g} or above confirms the rise; a value back "
                          f"near {lo:g} means it was transient" if lo is not None else
                          "a second value confirms or withdraws the rise")
                out.append({
                    "open_question": f"Is the {name} rise at month {a.month} real? "
                                     "No second specimen yet.",
                    "test": f"Repeat {name} specimen within a month",
                    "expectation": expect,
                    "source": CONFIRM, "evidence": HYPOTHESIS})

        # not sequenced since the last tumor sequencing while on endocrine therapy; a ctDNA
        # series sampled within the trials' cadence already answers it (the ctDNA workbench)
        seq = [t.month for ver in pf.versions[:i + 1] for t in ver.tests
               if t.kind == "Sequencing" and t.month is not None]
        ctdna = [t.month for ver in pf.versions[:i + 1] for t in ver.tests
                 if t.workbench == "ctdna" and t.month is not None]
        endocrine = [(rx, ver.month) for ver in pf.versions[:i + 1] for rx in ver.treatments
                     if rx in ENDOCRINE]
        last = max(seq[-1:] + ctdna, default=None)
        if seq and endocrine and now > seq[-1] and not (ctdna and now - last <= CTDNA_CADENCE):
            rx = ", ".join(f"{name} (month {m})" for name, m in endocrine)
            since = (f"the last ctDNA sample at month {last}" if ctdna and last > seq[-1]
                     else f"the sequencing at month {seq[-1]}")
            # the ESR1 rows the Evolution view raises for this file, with their own sources
            esr1 = [it for it in evolution.hypothesis_set(pf, i)["items"]
                    if "ESR1" in it["genes"]][:1]
            out.append({
                "open_question": f"Has the tumor acquired resistance alterations (ESR1 and "
                                 f"others) since {since}, under endocrine therapy ({rx})?",
                "test": "ctDNA sequencing for ESR1 and other endocrine-resistance alterations",
                "expectation": "an emerging ESR1 mutation would be an observed finding that "
                               "changes the evidence base; none found narrows the hypothesis. "
                               "The cited trials followed patients on aromatase inhibitors; "
                               "this record's agents differ, so the transfer is a hypothesis."
                               + "".join(f" The Evolution view ranks “{it['event']}” "
                                         f"here; when it would matter: {it['matters']}"
                                         for it in esr1),
                "source": CTDNA_SOURCE + "".join(f"; {it['frequency']}" for it in esr1)
                + (f"; a ctDNA sample older than {CTDNA_CADENCE} months is outside SERENA-6's "
                   "cadence" if ctdna else ""),
                "evidence": HYPOTHESIS})

        # imaging older than IMAGING_AGE months while a marker rose since it
        imaging = _imaging(pf, i)
        rises = _marker_rises(pf, i)
        if imaging and rises:
            im_month = imaging[-1][0]
            after = [a for _, a, *_ in rises if a.month > im_month]
            if after and now - im_month > IMAGING_AGE:
                gaps = [b - a for (a, _), (b, _) in zip(imaging, imaging[1:], strict=False)]
                cadence = (f"this record's own cadence: imaging every {median(gaps):g} months "
                           f"(median of {len(gaps)} intervals)" if gaps else
                           "this record holds one imaging study, so it has no cadence yet")
                out.append({
                    "open_question": f"The latest imaging is {now - im_month} months old (month "
                                     f"{im_month}) and {after[-1].source} rose since it.",
                    "test": "Repeat imaging per the clinic's schedule",
                    "expectation": "imaging confirms progression, finds the marker rise "
                                   "unexplained, or reads stable",
                    "source": f"{cadence}; the {IMAGING_AGE}-month interval is a placeholder, "
                              "not a guideline", "evidence": HYPOTHESIS})

    # a TCGA case: a data layer not measured, and what measuring it would do to the estimate
    if pf.kind == "TCGA-BRCA":
        missing = dict(v.observed).get("Not measured", "none")
        what_if = pf.model.get("what_if", {})
        for layer in ([] if missing == "none" else missing.split(", ")):
            name = ASSAYS.get(layer, layer)
            numbers = what_if.get(layer)
            out.append({
                "open_question": f"Would the {layer} layer move the estimate? It was not "
                                 "measured, so the model scored it as missing (a mask), not as "
                                 "normal.",
                "test": name,
                "expectation": (f"what-if from the model: {numbers}" if numbers is not None else
                                "the model takes a mask per layer, so the layer would enter the "
                                "estimate directly; this file's model exposes no what-if numbers,"
                                " so the effect is named, not quantified"),
                "source": "model inference: the clinical-anchored residual model with a layer "
                          "mask (tests/test_model.py)",
                "evidence": INFERENCE})

    # a receptor status that other tests contradict: the clinical test that decides it
    found = discrepancies(pf, i)
    for d in found:
        her2 = d["rule"] == "ERBB2 copy number vs HER2" or (
            d["rule"] == "documented vs recorded receptor" and d["what"].startswith("HER2"))
        if d["rule"] in ("ERBB2 copy number vs HER2", "ER RNA and protein vs ER status",
                         "documented vs recorded receptor", "PAM50 basal-like vs ER-positive"):
            out.append({
                "open_question": f"{d['what']}: which status holds?",
                "test": "HER2 in situ hybridization with the IHC" if her2 else
                        "Repeat ER immunohistochemistry with controls",
                "expectation": "a guideline read on the block settles the status; RNA, copy "
                               "number and a subtype call are not the clinical tests",
                "source": HER2_GUIDE if her2 else ER_GUIDE, "evidence": HYPOTHESIS})

    # many unsure tiles on a scored section: a second model's opinion on them
    for s in slides.sections(pf, i):
        share, head = s["meta"].get("numbers", {}).get("unsure_share"), s["meta"].get("head", {})
        if share is not None and share >= UNSURE_SHARE and "accuracy_below_cutoff" in head:
            out.append({
                "open_question": f"What tissue is in the {share:.0%} of section {s['slide']} the "
                                 "tile head is unsure about?",
                "test": "A second encoder's tile classes on the unsure tiles (a stronger "
                        "pathology encoder, docs/model_access.md), then the pathologist where "
                        "the two disagree",
                "expectation": "tiles where two models agree firm up the map; the rest go to "
                               "the eye",
                "source": f"the head's held-out accuracy: {head['accuracy_below_cutoff']:.0%} on "
                          "tiles below its certainty cutoff, "
                          f"{head['accuracy_at_or_above_cutoff']:.0%} at or above it "
                          f"({head.get('held_out', 'held-out slides')}); the "
                          f"{UNSURE_SHARE:.0%} share is a placeholder",
                "evidence": HYPOTHESIS})

    # documents that disagree with each other or with the record: a re-read
    for d in found:
        if d["rule"] in ("documents disagree", "documented vs recorded"):
            out.append({
                "open_question": f"{d['what']}: which does the record mean?",
                "test": "A re-read of the source sentences (documents workbench)",
                "expectation": "the sentence stands or the rule misread it; two standing "
                               "sentences mean two specimens or an error to correct",
                "source": d["basis"], "evidence": HYPOTHESIS})
    return out

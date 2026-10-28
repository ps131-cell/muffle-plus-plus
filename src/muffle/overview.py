"""The patient file as one product (docs/WORKBENCHES.md §1 and §2): the report's header of
finding cards, one attention queue for the patient, and the patient list's rows and filters.

Pure functions over ``muffle.workspace.PatientFile``; nothing new is computed here. The cards come
from each workbench's ``summary``; the queue merges each workbench's ``queue``, the SOS alerts and
``muffle.crosstest.discrepancies``, de-duplicated by finding key (an alert on a lab value and the
lab workbench's flag of that value are one finding) and ordered by consequence × trust
(``workspace.TRUST``, placeholder weights). Radiology and evolution join once their modules carry
the contract; every workbench module here does (labs, ctDNA, genomics, slides, omics,
documents, radiology, evolution).
"""

from __future__ import annotations

import re
from dataclasses import replace

from muffle import crosstest, evolution
from muffle.demo import ordinal
from muffle.report.case_tools import INFERENCE, OBSERVED
from muffle.workbench import ctdna, documents, genome, genomics, labs, omics, radiology, slides
from muffle.workspace import QUEUE_ORDER, TRUST, PatientFile, card, finding_key

WORKBENCHES = {"labs": labs, "ctdna": ctdna, "genomics": genomics, "slides": slides,
               "omics": omics, "documents": documents, "radiology": radiology,
               "evolution": evolution}
NAMES = {"labs": "Labs", "ctdna": "ctDNA", "genomics": "Genomics", "slides": "Slides",
         "omics": "Expression", "documents": "Documents", "radiology": "Imaging",
         "evolution": "Evolution"}
ORDER_RULE = QUEUE_ORDER
MARKER_KEYS, DRIVER = crosstest.MARKER_KEYS, crosstest._DRIVER  # names in the alerts' text


def _kw(name: str, pf: PatientFile, lookup) -> dict:
    """CIViC for a TCGA file's variants; the synthetic record carries its own frozen items."""
    return {"lookup": lookup} if name == "genomics" and pf.kind != "synthetic" else {}


def summaries(pf: PatientFile, i: int, lookup=None) -> dict[str, dict]:
    """Every workbench's ``summary`` as of report version ``i``."""
    return {name: m.summary(pf, i, **_kw(name, pf, lookup)) for name, m in WORKBENCHES.items()}


def queues(pf: PatientFile, i: int, lookup=None) -> dict[str, list[dict]]:
    """Every workbench's ``queue`` as of report version ``i``."""
    return {name: m.queue(pf, i, **_kw(name, pf, lookup)) for name, m in WORKBENCHES.items()}


def _cards(sums: dict, name: str) -> dict[str, dict]:
    return {c["what"]: c for c in sums.get(name, {}).get("cards", [])}


def _recorded(pf: PatientFile, i: int) -> tuple[str, str] | None:
    """The clinical record's stage and receptor status: (text, where it comes from)."""
    obs = dict(pf.versions[i].observed)
    if pf.kind == "synthetic":
        dx = obs.get("Diagnosis")
        return (dx, "the record's diagnosis entry") if dx else None
    bits = [f"stage {obs['Stage']}" if obs.get("Stage", "not recorded") != "not recorded"
            else "stage not recorded"]
    cs = omics.case_scores(pf)
    if cs:
        bits.append(omics.recorded_text(cs["receptors"]))
    return "; ".join(bits), "TCGA clinical data" + (" (stage; IHC and ISH)" if cs else "")


def _latest_imaging(pf: PatientFile, i: int) -> dict | None:
    t = next((t for v in reversed(pf.versions[: i + 1]) for t in reversed(v.tests)
              if t.kind == "Imaging"), None)
    if t is None:
        return None
    return card("Imaging", f"month {t.month}: {t.result}", OBSERVED,
                f"Imaging report, month {t.month}", "the imaging report's text (the radiology "
                "workbench is planned: no images read here)", "none: the reader's own words",
                "strong", ("Tests", t.kind, t.month, t.name))


def _risk(pf: PatientFile, i: int) -> dict | None:
    v = pf.versions[i]
    r = v.risk or {}
    if "value" in r:
        lo, hi = r["range"]
        return card("12-month risk", f"{r['value']:.0%} (5 models {lo:.0%}–{hi:.0%}; diagnosis "
                    f"only {r['baseline']:.0%})", INFERENCE,
                    f"month-{r['landmark']} model, {v.label}", f"{pf.model['name']}; held-out "
                    f"AUROC {r['auroc']:.2f}", "none: an estimate; calibration not checked",
                    "moderate", ("Timeline",))
    if "percentile" in r:
        c = r.get("c_index")
        return card("Cohort risk", f"{ordinal(r['percentile'])} percentile ({r['group']} risk "
                    "group), overall survival", INFERENCE, "the tumor sample's data layers",
                    pf.model["name"] + ("" if c is None else f"; held-out C-index {c:.3f}"),
                    "cohort tertiles (risk group); it ranks patients, roughly calibrated",
                    "moderate")
    return None


def header(pf: PatientFile, i: int, sums: dict, queue: list[dict] | None = None,
           reviews: dict | None = None) -> list[dict]:
    """The report's header: stage and receptors (recorded and documented side by side), the
    PAM50 call, key drivers, the slide picture, imaging, the risk, the top evolution hypothesis
    and the open SOS alerts (``queue``'s alerts without a review mark in ``reviews``). Each a
    ``workspace.card``; nothing new is computed."""
    out = []
    rec, doc = _recorded(pf, i), _cards(sums, "documents").get("Documented stage and receptors")
    if rec or doc:
        sides = ([("Recorded", rec[0], rec[1])] if rec else []) + (
            [("Documented", doc["text"], doc["source"])] if doc else [])
        c = card("Stage and receptors", " · ".join(f"{k}: {t}" for k, t, _ in sides),
                 OBSERVED, "; ".join(f"{k.lower()}: {s}" for k, _, s in sides),
                 doc["method"] if doc else "the clinical record",
                 doc["threshold"] if doc else "none: recorded", doc["trust"] if doc else
                 "strong", doc["opens"] if doc else (), doc["focus"] if doc else None)
        c["sides"] = sides
        out.append(c)
    om = _cards(sums, "omics")
    out += [om[k] for k in ("PAM50 subtype",) if k in om]
    out += list(_cards(sums, "genomics").values()) + list(_cards(sums, "ctdna").values())
    out += list(_cards(sums, "slides").values())
    rad = list(_cards(sums, "radiology").values())
    out += rad[:1] or [c for c in [_latest_imaging(pf, i)] if c]
    out += [c for c in [_risk(pf, i)] if c]
    out += list(_cards(sums, "evolution").values())[:1]
    alerts = [q for q in queue or [] if q["sos"]]
    still = [q for q in alerts if q["key"] not in (reviews or {})]
    if alerts:
        top = (still or alerts)[0]
        out.append({**card(
            "SOS", f"{len(still)} open of {len(alerts)} alert(s), "
            f"{sum(q['new'] for q in alerts)} new in this version; "
            f"{'top open' if still else 'all marked'}: {top['what']}", top["evidence"],
            top["source"], top["why"], top["threshold"], top["trust"], top["opens"],
            top["focus"]), "open": len(still), "alerts": len(alerts), "pointer": top["pointer"]})
    else:
        out.append({**card("SOS", "nothing alarming in this version or before", OBSERVED,
                           "the file's alert rules", "the SOS rules (Methods and validation)",
                           "each rule's own (Methods and validation)", "strong"),
                    "open": 0, "alerts": 0})
    return out


def absent(sums: dict) -> list[tuple[str, str]]:
    """What the file lacks, as (workbench, why) for an empty card beside the header's ("what
    a test cannot see is said")."""
    return [(n, s["note"]) for n, s in sums.items() if s.get("note")]


# ------------------------------------------------------------------- the report's driver column

# Ensembl VEP's consequence severity ("IMPACT"), from its table of calculated consequences
# (ensembl.org/info/genome/variation/prediction/predicted_data.html); anything else: MODIFIER
VEP_IMPACT = {
    "HIGH": {"transcript_ablation", "splice_acceptor_variant", "splice_donor_variant",
             "stop_gained", "frameshift_variant", "stop_lost", "start_lost"},
    "MODERATE": {"inframe_insertion", "inframe_deletion", "missense_variant",
                 "protein_altering_variant"},
    "LOW": {"splice_region_variant", "synonymous_variant", "start_retained_variant",
            "stop_retained_variant", "incomplete_terminal_codon_variant"}}
# the colours of the report and of the Methods page's legend: severity, and CIViC's level
# (A and B, as the genomics queue's strong trust; C to E, as its moderate; none gray)
IMPACT_COLORS = {"HIGH": "red", "MODERATE": "orange", "LOW": "gray", "MODIFIER": "gray"}
LEVEL_COLORS = {"A": "green", "B": "green", "C": "orange", "D": "orange", "E": "orange"}


def vep_impact(effect: dict) -> str | None:
    """A variant's consequence severity in Ensembl VEP's words (``genome.effect``'s annotation);
    None when it was not looked up."""
    if not effect["found"]:
        return None
    c = effect["annotation"]["consequence"] or ""
    return next((k for k, terms in VEP_IMPACT.items() if c in terms), "MODIFIER")


def drivers(pf: PatientFile, i: int, lookup=None, log_risk: float | None = None
            ) -> tuple[list[dict], dict]:
    """The observed variants as of version ``i`` (``genomics.variants``), each once (a variant
    found again by a later test, QA R3-16), and their read counts where this build's precomputed
    genome numbers belong to the file (``genome.case_block``: as the genomics workbench reads
    them; never another build's numbers). ``lookup``: CIViC for a TCGA file; the synthetic
    record's items are frozen with it."""
    upto = replace(pf, versions=pf.versions[: i + 1])  # its imported sequencing as of then too
    block = genome.case_block(genome.load(genome.CN_JSON), upto, log_risk)
    vaf = genome.load(genome.APP / "evolution_vaf.json") if block else None
    reads = {r["variant"]: r for r in (((vaf or {}).get("cases") or {}).get(
        str(genome.case_index(upto))) or {}).get("variants", [])}
    vs = genomics.variants(upto, genomics.events_until(None, pf.versions[i].month), None,
                           None if pf.kind == "synthetic" else lookup, reads=reads or None)
    once: dict[str, dict] = {}
    for v in vs:
        once.setdefault(v["variant"], v)
    return list(once.values()), reads


# ------------------------------------------------------------------------------- the queue

def alert_key(pf: PatientFile, a) -> str:
    """An alert's review key: the finding it is about when a workbench names that finding (a
    lab value, a sequenced driver, a site or read in an imaging report), so the queue, the
    workbench and the patient list share one mark; else the alert's own ``finding_key``."""
    kind, month, name = (tuple(a.opens) + (None, None, None))[1:4]
    if kind == "Lab" and name in MARKER_KEYS:
        return finding_key(pf, "lab", MARKER_KEYS[name], month)
    driver = DRIVER.search(a.what)
    if kind == "Sequencing" and driver:
        return finding_key(pf, "variant", driver.group(1), month)
    if kind == "Imaging" and a.what.startswith("New metastatic site: "):
        site = a.what.split(": ", 1)[1]
        return finding_key(pf, "imaging", "report", month,
                           radiology.SITE_WORDS.get(site, site.capitalize()))
    if kind == "Imaging" and a.what.startswith("Progression on imaging"):
        return finding_key(pf, "imaging", "report", month, "read")
    return finding_key(pf, "alert", a.month, a.what)


def _alert_item(pf: PatientFile, v_month, a) -> dict:
    return {"pointer": None, "what": a.what, "why": f"{a.rule}; trust: {a.why_trust}",
            "evidence": a.evidence, "trust": a.trust, "consequence": a.consequence,
            "opens": tuple(a.opens), "focus": None, "source": a.source,
            "key": alert_key(pf, a), "month": a.month,
            "threshold": a.threshold, "kind": "SOS", "new": a.month == v_month,
            "settle": ""}


def _discrepancy_item(d: dict, v_month) -> dict:
    months = [m for m in d["months"] if m is not None]
    return {"pointer": None, "what": d["what"], "why": d["why"], "evidence": d["evidence"],
            "trust": d["trust"], "consequence": d["consequence"], "opens": d["opens"],
            "focus": d["focus"], "source": " vs ".join(d["sources"]), "key": d["key"],
            "month": max(months) if months else None, "threshold": d["basis"],
            "kind": "discrepancy", "new": bool(months) and max(months) == v_month,
            "settle": d["would_settle"]}


def attention(pf: PatientFile, i: int, wb_queues: dict, disagree: list[dict]) -> list[dict]:
    """One queue for the patient as of version ``i``: the SOS alerts so far, the cross-test
    discrepancies and every workbench's queue, each with a priority (consequence × trust), its
    kind ("SOS", "discrepancy" or the workbench), whether it is new in this version, and the
    other places the same finding was raised ("also"). An alert takes the pointer of the
    workbench item behind it (the lab value, the variant), so "open" lands there."""
    v_month = pf.versions[i].month
    items = []
    by_opens = {}  # workbench items by where they open, for the alerts to find their pointer
    wb_items = []
    for name, q in wb_queues.items():
        for it in q:
            item = {**it, "kind": name, "new": it["month"] is not None and it["month"] == v_month,
                    "settle": ""}
            wb_items.append(item)
            by_opens.setdefault(item["opens"], []).append(item)
    for v in pf.versions[: i + 1]:
        for a in v.alerts:
            item = _alert_item(pf, v_month, a)
            for w in by_opens.get(item["opens"], []):  # the workbench item behind the alert
                if w["key"] == item["key"]:
                    item.update(pointer=w["pointer"], focus=w["focus"])
                    break
            items.append(item)
    items += [_discrepancy_item(d, v_month) for d in disagree]
    items += wb_items
    for n, item in enumerate(items):
        item.update(priority=item["consequence"] * TRUST[item["trust"]], order=n,
                    sos=item["kind"] == "SOS", also=[], label=_label(item["kind"]))
    items.sort(key=lambda x: (-x["priority"], not x["new"],
                              -(x["month"] if x["month"] is not None else -10**6), x["order"]))
    kept: dict[str, dict] = {}
    for item in items:
        first = kept.setdefault(item["key"], item)
        if first is not item:  # the same finding raised again: keep the first, say where else
            first["also"].append(_where(item))
            first.update(sos=first["sos"] or item["sos"], new=first["new"] or item["new"])
            if first["pointer"] is None and item["pointer"]:
                first.update(pointer=item["pointer"], focus=item["focus"])
    out = list(kept.values())
    for n, item in enumerate(out, 1):
        item["n"] = n
    return out


def _label(kind: str) -> str:
    return {"SOS": "SOS alert", "discrepancy": "tests disagree"}.get(
        kind, f"{NAMES.get(kind, kind)} workbench")


def _where(item: dict) -> str:
    name = {"SOS": "an SOS alert", "discrepancy": "the cross-test rules"}.get(
        item["kind"], f"the {NAMES.get(item['kind'], item['kind']).lower()} workbench")
    return name + (f" ({item['pointer']})" if item["pointer"] else "")


def unsure(items: list[dict], reviews: dict) -> list[dict]:
    """The unsure list: items a reviewer marked "second look", and items of weak trust."""
    return [x for x in items if (reviews.get(x["key"]) or {}).get("mark") == "second look"
            or x["trust"] == "weak"]


# ------------------------------------------------------------------------- the patient list

# the worklist's tests column: one letter per workbench, in this order (docs/WORKSPACE.md)
LETTERS = {"labs": "L", "ctdna": "C", "genomics": "G", "omics": "O", "slides": "P",
           "radiology": "R", "documents": "D"}
LETTER_WORDS = {"L": "labs", "C": "ctDNA", "G": "genomics", "O": "omics (expression)",
                "P": "pathology slides", "R": "radiology (imaging)", "D": "documents"}
BANDS = ("high", "medium", "low", "12-month")  # a TCGA file's risk group, or the synthetic's
STAGE_RANK = {"I": 1, "II": 2, "III": 3, "IV": 4}
RECEPTOR_SIGNS = {"positive": "+", "negative": "−", "equivocal": " eq"}


def _receptors(pf: PatientFile, cs: dict | None) -> str:
    """The recorded receptor status in short ("ER+ PR+ HER2−"): a TCGA file's clinical data
    (IHC and ISH), the synthetic record's diagnosis entry ("HR+, HER2−"); "" when neither."""
    if cs:
        return " ".join(f"{name}{RECEPTOR_SIGNS.get((r.get('status') or '').lower(), '?')}"
                        for name, r in cs["receptors"].items())
    rec = _recorded(pf, len(pf.versions) - 1)
    return " ".join(m.group(0).replace("-", "−") for m in
                    re.finditer(r"\b(?:HR|ER|PR|HER2)[+−-](?![A-Za-z])", rec[0] if rec else ""))


def _tested(pf: PatientFile, cs: dict | None) -> dict[str, list[str]]:
    """Each workbench that holds this patient's own data, with the names of its tests (a
    document's title, a section count), in ``LETTERS``' order; absent workbenches left out."""
    def names(keep) -> list[str]:
        return list(dict.fromkeys(t.name for t in pf.tests if keep(t)))
    sections = slides.sections(pf)
    held = {
        "labs": names(lambda t: t.kind == "Lab"),
        "ctdna": names(lambda t: t.workbench == "ctdna"),
        "genomics": names(lambda t: t.workbench == "mutations"),
        "omics": names(lambda t: t.workbench == "omics") or (
            ["RNA, copy number, protein scores"] if cs is not None else []),
        "slides": [f"{len(sections)} H&E section{'' if len(sections) == 1 else 's'}"]
        if sections else [],
        "radiology": names(lambda t: t.kind == "Imaging" or t.details.get("pipeline")
                           == "imaging"),
        "documents": list(dict.fromkeys(d["title"] for d in documents.file_documents(pf))),
    }
    return {k: v for k, v in held.items() if v}


def list_risk(pf: PatientFile) -> dict:
    """The list's risk, model inference: a TCGA file's risk group (cohort tertile) and
    percentile, ranked by one federated model, so no spread between models; the synthetic
    patient's latest 12-month risk, the mean of 5 models with their range (another model and
    another measure, MSK-CHORD)."""
    r = next((v.risk for v in reversed(pf.versions) if v.risk
              and ("value" in v.risk or "percentile" in v.risk)), None)
    if r is None:
        return {"band": None, "percentile": None, "risk": "not estimated", "spread": ""}
    if "percentile" in r:
        return {"band": r["group"], "percentile": r["percentile"],
                "risk": f"{r['group'].capitalize()} · {ordinal(r['percentile'])}",
                "spread": "one model"}
    lo, hi = r["range"]
    return {"band": "12-month", "percentile": None, "risk": f"{r['value']:.0%} 12-mo",
            "spread": f"{lo:.0%}–{hi:.0%}, 5 models"}


def list_row(pf: PatientFile) -> dict:
    """What the patient list shows, filters and searches on, for one file, all read from the
    file: subtype (model inference) and recorded receptors, mutated genes, stage, alerts, the
    workbenches that hold this patient's data and their tests, the versions, the latest
    update and the risk (``list_risk``, model inference)."""
    cs = omics.case_scores(pf)
    genes = sorted({var.split()[0] for t in pf.tests if t.workbench == "mutations"
                    for var in t.details.get("variants", [])})
    tested = _tested(pf, cs)
    return {"id": pf.id, "subtype": omics.SUBTYPES[cs["pam50"]["call"]] if cs else "not called",
            "receptors": _receptors(pf, cs),
            "genes": genes, "stage": crosstest._recorded_stage(pf, len(pf.versions) - 1)
            or "not recorded", "alerts": [alert_key(pf, a) for v in pf.versions
                                          for a in v.alerts],
            "holds": [NAMES[k] for k in tested], "tested": tested,
            "versions": len(pf.versions), "latest": pf.latest.label, "updated": pf.latest.month,
            "imported": bool(pf.versions[-1].imported), **list_risk(pf)}


def letters(row: dict) -> str:
    """The tests column: a letter per workbench holding data, "·" where it holds none."""
    return " ".join(LETTERS[k] if k in row["tested"] else "·" for k in LETTERS)


def tests_named(row: dict, most: int = 3) -> list[str]:
    """The tests behind the letters, one entry a letter: "L: CA 15-3 · CEA · ALP +4"."""
    return [f"{LETTERS[k]}: " + " · ".join(v[:most]) + (f" +{len(v) - most}" if len(v) > most
                                                      else "")
            for k, v in row["tested"].items()]


def matches(row: dict, query: str) -> bool:
    """Every word of ``query`` appears in the row's patient ID, diagnosis, subtype, receptors,
    stage, risk group, genes or workbenches (case-insensitive): "PIK3CA", "luminal", "case 299
    slides", "her2+"."""
    hay = " ".join([row["id"], row.get("diagnosis", ""), row["subtype"],
                    row.get("receptors", ""), f"stage {row['stage']}", row.get("band") or "",
                    *row["genes"], *row["holds"]]).lower()
    return all(w in hay for w in query.lower().split())


SORTS = ("Last update", "Risk", "Open SOS", "Stage", "ID", "Versions")


def open_alerts(row: dict, reviews: dict | None = None) -> int:
    """A list row's SOS alerts without a review mark."""
    return sum(k not in (reviews or {}) for k in row["alerts"])


def _natural(text: str) -> tuple:
    """"Case 47" before "Case 299": numbers compared as numbers."""
    return tuple((0, int(p), "") if p.isdigit() else (1, 0, p.lower())
                 for p in re.split(r"(\d+)", text) if p)


def sort_rows(rows: list[dict], by: str = "Last update", reviews: dict | None = None,
              reverse: bool = False) -> list[dict]:
    """The list in the order asked for (``SORTS``), each in its natural direction, which
    ``reverse`` flips: the latest update first (a file imported into this session, then the
    record's latest month), the highest cohort risk percentile first, the most open SOS alerts
    first, the highest stage first, IDs in order ("Case 47" before "Case 299"), the most report
    versions first. Rows without the value (a TCGA file's single sample has no month; the
    synthetic patient's 12-month risk is another measure; a stage not recorded) stay last
    either way, and ties keep the list's own order. Rows carry "updated" (a month or None),
    "imported", "percentile" (None without one), "stage", "id" and "versions"."""
    value = {
        "Risk": lambda r: r.get("percentile"),
        "Open SOS": lambda r: open_alerts(r, reviews),
        "Stage": lambda r: STAGE_RANK.get(r.get("stage")),
        "ID": lambda r: _natural(r["id"]),
        "Versions": lambda r: r.get("versions", 1),
    }.get(by, lambda r: (True, r.get("updated") or 0) if r.get("imported") else
          None if r.get("updated") is None else (False, r["updated"]))
    have = [r for r in rows if value(r) is not None]
    first = by != "ID"  # IDs read up; every other column puts its largest first
    return (sorted(have, key=value, reverse=first != reverse)
            + [r for r in rows if value(r) is None])


def filter_rows(rows: list[dict], query: str = "", subtypes=(), genes=(), stages=(),
                open_sos: bool = False, holds=(), reviews: dict | None = None, bands=(),
                pinned=None) -> list[dict]:
    """The rows that match the search and every filter: subtype, any of the genes, stage, an
    open (unreviewed) SOS alert, each workbench in ``holds`` ("Slides", "Imaging", ...), any of
    the risk ``bands`` (``BANDS``) and, when ``pinned`` is a collection of IDs, those files."""
    reviews = reviews or {}
    return [r for r in rows if matches(r, query)
            and (not subtypes or r["subtype"] in subtypes)
            and (not genes or set(genes) & set(r["genes"]))
            and (not stages or r["stage"] in stages)
            and (not open_sos or any(k not in reviews for k in r["alerts"]))
            and all(h in r["holds"] for h in holds)
            and (not bands or r.get("band") in bands)
            and (pinned is None or r["id"] in pinned)]


def review_state(row: dict, reviews: dict | None = None) -> str:
    """The file's review: its SOS alerts marked so far ("done", "open"), and the reviewer's
    marks on any of its findings in this session."""
    reviews = reviews or {}
    n, still = len(row["alerts"]), open_alerts(row, reviews)
    marks = sum(k.startswith(row["id"] + "|") for k in reviews)
    state = ("no alerts" if not n else f"✓ done, {n} of {n}" if not still
             else f"open, {n - still} of {n}")
    return state + (f" · {marks} mark{'' if marks == 1 else 's'}" if marks else "")


# --------------------------------------------------- the list's state: the address and "seen"

# the address's names for the list's controls (``list_address``), and the sort's
SORT_WORDS = dict(zip(SORTS, ("update", "risk", "open", "stage", "id", "versions"),
                      strict=True))
LIST_DEFAULTS = {"query": "", "open_sos": False, "pinned": False, "bands": [], "holds": [],
                 "subtypes": [], "genes": [], "stages": [], "sort": SORTS[0], "reverse": False}
LIST_ADDRESS = {"query": "q", "open_sos": "sos", "pinned": "pinned", "bands": "band",
            "holds": "tests", "subtypes": "subtype", "genes": "gene", "stages": "stage",
            "sort": "sort", "reverse": "rev"}
_LETTER_NAME = {LETTERS[k]: NAMES[k] for k in LETTERS}


def list_address(state: dict) -> dict[str, str]:
    """The list's state as address parameters, only those not at their default: q=pik3ca,
    sos=1, pinned=1, band=high,medium, tests=P,R (the letters), subtype=…, gene=…, stage=…,
    sort=risk, rev=1."""
    out = {}
    for k, name in LIST_ADDRESS.items():
        v = state.get(k, LIST_DEFAULTS[k])
        if v == LIST_DEFAULTS[k] or v in (None, ""):
            continue
        if k == "holds":
            v = [letter for letter, n in _LETTER_NAME.items() if n in v]
        if not v:
            continue
        out[name] = (SORT_WORDS[v] if k == "sort" else "1" if isinstance(v, bool)
                     else ",".join(v) if isinstance(v, list) else str(v).strip())
    return out


def from_address(params: dict, options: dict | None = None) -> dict:
    """``list_address``'s inverse: the list's state from an address (a link someone shared),
    every value it does not know dropped; ``options`` holds the values each list filter
    offers ({"subtypes": [...], "genes": [...], "stages": [...]})."""
    options = options or {}
    state = {**LIST_DEFAULTS}
    for k, name in LIST_ADDRESS.items():
        raw = (params.get(name) or "").strip()
        if not raw:
            continue
        if k in ("open_sos", "pinned", "reverse"):
            state[k] = raw.lower() in ("1", "true", "yes")
        elif k == "query":
            state[k] = raw
        elif k == "sort":
            state[k] = next((s for s, w in SORT_WORDS.items() if w == raw.lower()), SORTS[0])
        else:
            parts = [p.strip() for p in raw.split(",") if p.strip()]
            if k == "holds":
                parts = [_LETTER_NAME[p.upper()] for p in parts if p.upper() in _LETTER_NAME]
            allowed = {"bands": BANDS, "holds": NAMES.values()}.get(k, options.get(k))
            state[k] = list(dict.fromkeys(p for p in parts
                                          if allowed is None or p in allowed))
    return state


def seen(row: dict, reviews: dict | None = None) -> dict:
    """What a file held when it was opened: its report versions and open SOS alerts."""
    return {"versions": row["versions"], "open": open_alerts(row, reviews)}


def changed_since(row: dict, before: dict | None, reviews: dict | None = None) -> str:
    """What a file gained since it was last opened in this session ("+1 version (…); +2 open
    alerts"), "" when nothing was gained or it was never opened (``before`` None)."""
    if not before:
        return ""
    bits = []
    more = row["versions"] - before["versions"]
    if more > 0:
        bits.append(f"+{more} version{'' if more == 1 else 's'} ({row['latest']})")
    opened = open_alerts(row, reviews) - before["open"]
    if opened > 0:
        bits.append(f"+{opened} open alert{'' if opened == 1 else 's'}")
    return "; ".join(bits)

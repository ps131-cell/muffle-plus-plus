"""The patient file as one product (docs/WORKBENCHES.md §1 and §2): the report's header of
finding cards, one attention queue for the patient, and the patient list's rows and filters.

Pure functions over ``muffle.workspace.PatientFile``; nothing new is computed here. The cards come
from each workbench's ``summary``; the queue merges each workbench's ``queue``, the SOS alerts and
``muffle.crosstest.discrepancies``, de-duplicated by finding key (an alert on a lab value and the
lab workbench's flag of that value are one finding) and ordered by consequence × trust
(``workspace.TRUST``, placeholder weights). Radiology and evolution join once their modules carry
the contract; every workbench module here does (labs, genomics, slides, omics, documents,
radiology, evolution).
"""

from __future__ import annotations

from muffle import crosstest, evolution
from muffle.demo import ordinal
from muffle.report.case_tools import INFERENCE, OBSERVED
from muffle.workbench import documents, genomics, labs, omics, radiology, slides
from muffle.workspace import QUEUE_ORDER, TRUST, PatientFile, card, finding_key

WORKBENCHES = {"labs": labs, "genomics": genomics, "slides": slides, "omics": omics,
               "documents": documents, "radiology": radiology, "evolution": evolution}
NAMES = {"labs": "Labs", "genomics": "Genomics", "slides": "Slides", "omics": "Expression",
         "documents": "Documents", "radiology": "Imaging", "evolution": "Evolution"}
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
    out += list(_cards(sums, "genomics").values())
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


def absent(sums: dict) -> list[str]:
    """What the file lacks, by workbench, for a line under the header ("what a test cannot
    see is said")."""
    return [f"{NAMES[n]}: {s['note']}" for n, s in sums.items() if s.get("note")]


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

def list_row(pf: PatientFile) -> dict:
    """What the patient list filters and searches on, for one file: subtype, mutated genes,
    stage, alerts, and which workbenches hold this patient's data."""
    cs = omics.case_scores(pf)
    genes = sorted({var.split()[0] for t in pf.tests if t.workbench == "mutations"
                    for var in t.details.get("variants", [])})
    holds = {
        "labs": any(t.kind == "Lab" for t in pf.tests),
        "genomics": any(t.workbench == "mutations" for t in pf.tests),
        "slides": bool(slides.sections(pf)),
        "omics": cs is not None or any(t.workbench == "omics" for t in pf.tests),
        "documents": bool(documents.file_documents(pf)),
        "radiology": any(t.kind == "Imaging" or t.details.get("pipeline") == "imaging"
                         for t in pf.tests),
    }
    return {"id": pf.id, "subtype": omics.SUBTYPES[cs["pam50"]["call"]] if cs else "not called",
            "genes": genes, "stage": crosstest._recorded_stage(pf, len(pf.versions) - 1)
            or "not recorded", "alerts": [alert_key(pf, a) for v in pf.versions
                                          for a in v.alerts],
            "holds": [NAMES[k] for k, held in holds.items() if held]}


def matches(row: dict, query: str) -> bool:
    """Every word of ``query`` appears in the row's patient ID, diagnosis, subtype, stage, genes
    or workbenches (case-insensitive): "PIK3CA", "luminal", "case 299 slides"."""
    hay = " ".join([row["id"], row.get("diagnosis", ""), row["subtype"], f"stage {row['stage']}",
                    *row["genes"], *row["holds"]]).lower()
    return all(w in hay for w in query.lower().split())


def filter_rows(rows: list[dict], query: str = "", subtypes=(), genes=(), stages=(),
                open_sos: bool = False, holds=(), reviews: dict | None = None) -> list[dict]:
    """The rows that match the search and every filter: subtype, any of the genes, stage, an
    open (unreviewed) SOS alert, and each workbench in ``holds`` ("Slides", "Imaging", ...)."""
    reviews = reviews or {}
    return [r for r in rows if matches(r, query)
            and (not subtypes or r["subtype"] in subtypes)
            and (not genes or set(genes) & set(r["genes"]))
            and (not stages or r["stage"] in stages)
            and (not open_sos or any(k not in reviews for k in r["alerts"]))
            and all(h in r["holds"] for h in holds)]

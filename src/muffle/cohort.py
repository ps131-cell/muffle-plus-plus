"""Across the patient files (docs/cohort.md): one search over every file's findings, the files
nearest to one patient on its recorded and derived fields, and where a patient sits among the
TCGA files.

Lookups over what the files already hold: every workbench's ``summary`` cards and ``queue``
items (``muffle.overview``), the tests that disagree (``muffle.crosstest``), the documented
facts, the variants, the promoter methylation calls, the evolution hypotheses and a profile of
each file. No model is trained or run here and nothing is a prognosis. Nothing from MSK-CHORD
is compared: the synthetic patient's 12-month risk comes from MSK-CHORD models, so it never
enters a similarity or a distribution, and the synthetic patient is not in the cohort.
"""

from __future__ import annotations

import re
from urllib.parse import urlencode

from muffle import crosstest, evolution, overview
from muffle.demo import ordinal
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workbench import documents, genome, genomics, omics
from muffle.workspace import finding_key

LOOKUP = "a lookup on recorded and derived fields, not a model"
POSITION = "percentiles among the TCGA files, not a prognosis"
LABELS = (OBSERVED, INFERENCE, HYPOTHESIS)


def label(evidence: str) -> str:
    """The first evidence label an evidence text names ("observed (mutation), hypothesis
    (CIViC evidence)" -> observed); a text naming none ("documented") counts as observed."""
    found = [(evidence.find(e), e) for e in LABELS if e in evidence]
    return min(found)[1] if found else OBSERVED


def link(pid: str, opens: tuple = (), pointer: str | None = None) -> str:
    """The deep link (docs/ux.md §3) an entry opens: ?patient, ?view, ?test (``kind|month|name``,
    as ``app/navigation.test_key``) and ?pointer."""
    q = {"patient": pid, "view": opens[0] if opens else "Report"}
    if opens and opens[0] == "Tests":
        kind, month, name = opens[1:4]
        q["test"] = f"{kind}|{'' if month is None else month}|{name}"
    if pointer:
        q["pointer"] = pointer
    return "?" + urlencode(q)


def _entry(pf, workbench: str, kind: str, what: str, text: str, evidence: str,
           opens: tuple = (), focus: dict | None = None, pointer: str | None = None) -> dict:
    opens = tuple(opens)
    return {"patient": pf.id, "workbench": workbench, "kind": kind, "what": what, "text": text,
            "evidence": evidence, "label": label(evidence), "opens": opens, "focus": focus,
            "pointer": pointer, "link": link(pf.id, opens, pointer)}


# ----------------------------------------------------------------------------------- profile

def profile(pf, row: dict | None = None) -> dict:
    """The recorded and derived fields of one file that the similarity lookup and the cohort
    position read; None where the file lacks one (unknown, not negative):
    pam50 (model inference), stage (recorded), receptors {ER, PR, HER2: positive / negative}
    (recorded IHC and ISH; "HR" where a record states only the hormone receptors), drivers
    (mutated panel genes, observed; None if not sequenced), cn ("GENE amplification",
    observed copies with a placeholder rule), risk_band (the risk model's tertile group, model
    inference; never the synthetic patient's MSK-CHORD risk), immune (the RNA immune
    signature's band, placeholder cutoffs), tests (the workbenches holding the patient's data)
    and scores (the numbers the cohort position plots). ``row``: the file's
    ``overview.list_row``, when the caller has it."""
    row, cs, last = row or overview.list_row(pf), omics.case_scores(pf), len(pf.versions) - 1
    sequenced = any(t.workbench == "mutations" for t in pf.tests)
    if cs:
        receptors = {k: (r.get("status") or "").lower() or None
                     for k, r in cs["receptors"].items()}
    else:  # the synthetic record's diagnosis line: "hormone-receptor positive, HER2 negative"
        said = {f["field"]: f["value"] for f in documents.extract(pf.diagnosis)}
        receptors = {k: said.get(k.lower()) for k in ("ER", "PR", "HR", "HER2")}
    receptors = {k: v for k, v in receptors.items() if v in ("positive", "negative")} or None
    data = genome.load(genome.CN_JSON) or {}
    block = genome.case_block(data, pf) if data else None
    cn = None
    if block:
        cn = sorted(f"{r['gene']} {r['call_text']}" for r in genome.landscape(block, data["genes"])
                    if r["call"] in (2, -2) and (r["interest"] or r["pathways"]))
    risk = (pf.versions[0].risk or {}) if pf.kind == "TCGA-BRCA" else {}
    scores = {}
    if "log_risk" in risk and risk["log_risk"] is not None:
        scores["risk"] = float(risk["log_risk"])
    bur = genome.burden(block, data)
    if bur.get("measured"):
        scores["burden"] = float(bur["rate"])
    immune = None
    if cs:
        sc, est = cs["scores"], cs.get("estimate") or {}
        scores["proliferation"] = sc["proliferation"][0]
        scores["cytolytic"] = sc["immune"][0]
        if est.get("immune"):
            scores["immune"] = est["immune"][0]
            p = est["immune"][1]
            immune = ("high" if p >= omics.IMMUNE_HIGH else "low" if p <= omics.IMMUNE_LOW
                      else "middle")
        if est.get("stromal"):
            scores["stromal"] = est["stromal"][0]
        pi3k = (cs.get("rppa") or {}).get("pathways", {}).get("PI3K/AKT")
        if pi3k:
            scores["pi3k"] = pi3k[0]
        index = (cs.get("methylation") or {}).get("index")
        if index:
            scores["methylation"] = index[0]
    return {"id": pf.id, "kind": pf.kind,
            "pam50": omics.SUBTYPES[cs["pam50"]["call"]] if cs else None,
            "stage": crosstest._recorded_stage(pf, last), "receptors": receptors,
            "drivers": row["genes"] if sequenced else None, "cn": cn,
            "risk_band": risk.get("group"), "immune": immune, "tests": row["holds"],
            "scores": scores}


def profile_text(p: dict) -> str:
    """The profile in words, for the search index."""
    rec = p["receptors"] or {}
    bits = [f"stage {p['stage']}" if p["stage"] else "stage not recorded",
            ", ".join(f"{k} {v}" for k, v in rec.items()) or "receptors not recorded",
            f"PAM50 {p['pam50']}" if p["pam50"] else "PAM50 not called",
            ("mutated: " + ", ".join(p["drivers"]) if p["drivers"] else
             "sequenced: no panel driver mutated") if p["drivers"] is not None else
            "not sequenced",
            "copy number: " + (", ".join(p["cn"]) or "no amplification or deep deletion")
            if p["cn"] is not None else "",
            f"{p['risk_band']} risk group" if p["risk_band"] else "",
            f"RNA immune signature {p['immune']}" if p["immune"] else "",
            "data in: " + ", ".join(p["tests"])]
    return " · ".join(b for b in bits if b)


# ------------------------------------------------------------------------------------- index

def entries(pf, lookup=None) -> list[dict]:
    """Every finding of one file, as of its latest report version, as search entries: {patient,
    workbench, kind, what, text, evidence, label, opens, focus, pointer, link}. ``lookup`` is
    CIViC's (``muffle.demo.evidence_lookup``) for a TCGA file's variants."""
    i = len(pf.versions) - 1
    sums = overview.summaries(pf, i, lookup)
    queue = overview.attention(pf, i, overview.queues(pf, i, lookup),
                               crosstest.discrepancies(pf, i))
    p = profile(pf)
    out = [_entry(pf, "Report", "profile", "File profile", profile_text(p),
                  f"{OBSERVED} (stage, receptors, mutations, copy number), {INFERENCE} (PAM50, "
                  "risk group, immune band)")]

    def pointer(c):  # a card's pointer: the queue item landing on the same evidence
        return next((x["pointer"] for x in queue if c["focus"] and x["focus"] == c["focus"]),
                    None)

    in_sums = [c for s in sums.values() for c in s["cards"]]
    for c in overview.header(pf, i, sums)[:-1]:  # the header's own cards (its SOS card: below)
        if c not in in_sums:
            out.append(_entry(pf, "Report", "finding card", c["what"], c["text"], c["evidence"],
                              c["opens"], c["focus"], pointer(c)))
    for name, s in sums.items():
        for c in s["cards"]:
            out.append(_entry(pf, overview.NAMES[name], "finding card", c["what"], c["text"],
                              c["evidence"], c["opens"], c["focus"], pointer(c)))
    for x in queue:
        sos = x["kind"] in ("SOS", "discrepancy")
        out.append(_entry(pf, "Report" if sos else overview.NAMES[x["kind"]],
                          x["label"] if sos else "attention item", x["what"],
                          f"{x['what']}: {x['why']}" + (f" What would settle it: {x['settle']}"
                                                         if x["settle"] else ""),
                          x["evidence"], x["opens"], x["focus"], x["pointer"]))
    for v in genomics.file_variants(pf, None, lookup)[0]:
        level = v["strongest_level"]
        out.append(_entry(pf, "Genomics", "variant", v["variant"],
                          f"{v['variant']} mutation ({v['sample']}, {v['detection']['when']})"
                          + (f"; CIViC level {level}" if level else ""),
                          f"{OBSERVED} (mutation)" + (f", {HYPOTHESIS} (CIViC evidence)"
                                                       if level else ""),
                          genomics._seq_opens(pf, v), {"variant": v["variant"]},
                          next((x["pointer"] for x in queue
                                if x["focus"] == {"variant": v["variant"]}), None)))
    cs = omics.case_scores(pf)
    for m in omics.methylation_lines(cs) if cs else []:
        call = "methylated" if m["methylated"] else "unmethylated"
        out.append(_entry(pf, "Expression", "methylation call", f"{m['gene']} promoter",
                          f"{m['gene']} {call} (promoter): {m['text']}",
                          f"{OBSERVED} (beta); call at a placeholder cutoff", omics._opens(pf),
                          {"omics": finding_key(pf, "methylation", m["gene"])}))
    for f in documents.facts(documents.file_documents(pf)):
        if f["field"] == "date":
            continue
        out.append(_entry(pf, "Documents", "documented fact", f"{f['label']}: {f['value']}",
                          f"{f['label']}: {f['value']}. “{f['quote'][:240]}”",
                          f"{OBSERVED} (documented)", documents.doc_opens(pf, None, f["doc"]),
                          documents._focus(f)))
    for h in evolution.hypothesis_set(pf, i)["items"]:
        out.append(_entry(pf, "Evolution", "hypothesis", h["event"],
                          f"{h['event']}; {h['status']}", HYPOTHESIS, ("Evolution",),
                          {"evolution": h["key"]}))
    return out


def build_index(files: dict, lookup=None) -> list[dict]:
    """Every file's ``entries``, once per bundle (the app caches it)."""
    return [e for pf in files.values() for e in entries(
        pf, None if pf.kind == "synthetic" else lookup)]


# ------------------------------------------------------------------------------------ search

QUALIFIERS = {"level", "stage", "grade", "bi-rads", "birads"}  # "level A", "stage III"
POLARITY = {"positive", "negative", "methylated", "unmethylated"}       # "ER positive"


def terms(query: str) -> list[str]:
    """The query's terms: quoted text is one phrase; a word after a qualifier ("level A",
    "stage III", "grade 3") and a status after its subject ("ER positive", "ESR1 methylated")
    join it as a phrase; every other word stands alone."""
    out = []
    for quoted, word in re.findall(r'"([^"]+)"|(\S+)', (query or "").lower()):
        if quoted:
            out.append(" ".join(quoted.split()))
        elif out and (out[-1].split()[-1] in QUALIFIERS or word in POLARITY):
            out[-1] += " " + word
        else:
            out.append(word)
    return out


def _pattern(term: str) -> re.Pattern:
    """A term at a word start ("basal" finds "Basal-like", "methylated" not "unmethylated");
    its last word whole when short ("level A" not "level AB", "stage I" not "stage II")."""
    words = term.split()
    end = r"(?![\w])" if len(words[-1]) <= 3 else ""
    return re.compile(r"(?<![\w])" + r"[\s,:;]+".join(map(re.escape, words)) + end, re.I)


def search(index: list[dict], query: str, labels=()) -> dict:
    """Patients with findings matching ``query`` (``terms``), each term case-insensitive at a
    word start. A patient matches when one of its findings holds every term; ranked by how many
    of its findings do, then by how close the terms sit in the best one, then by evidence
    (observed, then model inference, then hypothesis). When no finding of any file holds every
    term, files whose findings hold them between them are returned instead ("across": True).
    ``labels`` keeps only findings of those evidence labels. Returns {"terms", "across",
    "patients": [{"patient", "findings": [entry + "span"]}]}."""
    ts = terms(query)
    if not ts:
        return {"terms": [], "across": False, "patients": []}
    pats = [_pattern(t) for t in ts]
    rank = {e: n for n, e in enumerate(LABELS)}
    by: dict[str, list[tuple]] = {}
    for e in index:
        if labels and e["label"] not in labels:
            continue
        hay = f"{e['what']} · {e['text']}"
        hits = [p.search(hay) for p in pats]
        found = [h for h in hits if h]
        if found:
            span = max(h.end() for h in found) - min(h.start() for h in found)
            by.setdefault(e["patient"], []).append((len(found), span, e))
    full = {pid: [h for h in hs if h[0] == len(ts)] for pid, hs in by.items()}
    full = {pid: hs for pid, hs in full.items() if hs}
    across = not full
    if across:  # the terms spread over a file's findings
        full = {pid: hs for pid, hs in by.items()
                if all(any(p.search(f"{h[2]['what']} · {h[2]['text']}") for h in hs)
                       for p in pats)}
    out = []
    for pid, hs in full.items():
        hs = sorted(hs, key=lambda h: (-h[0], h[1], rank[h[2]["label"]]))
        out.append({"patient": pid, "findings": [{**h[2], "span": h[1]} for h in hs]})
    out.sort(key=lambda r: (-len(r["findings"]), r["findings"][0]["span"],
                            rank[r["findings"][0]["label"]]))
    return {"terms": ts, "across": across, "patients": out}


# -------------------------------------------------------------------------------- similarity

FIELDS = {  # field -> (its name, its evidence label)
    "pam50": ("PAM50 subtype", INFERENCE), "stage": ("stage", OBSERVED),
    "receptors": ("receptor status", OBSERVED), "drivers": ("mutated driver genes", OBSERVED),
    "cn": ("copy-number calls", OBSERVED), "risk_band": ("risk group", INFERENCE),
    "immune": ("RNA immune band", INFERENCE), "tests": ("tests on file", OBSERVED)}
# ponytail: every field weighs the same (a placeholder, not tuned on outcomes); a field either
# file lacks counts as not shared, so a sparse file is never "very similar" on one field
WEIGHTS = {k: 1.0 for k in FIELDS}
PLACEHOLDERS = [  # listed on Methods and validation with every other placeholder
    ("similar patients: field weights", f"every field the same ({len(FIELDS)} fields)"),
    ("similar patients: RNA immune band", f"high from the {omics.IMMUNE_HIGH}th, low to the "
     f"{omics.IMMUNE_LOW}th cohort percentile"),
]


SAY = {"pam50": "{} (PAM50)", "stage": "{}", "receptors": "{}", "drivers": "mutated: {}",
       "cn": "copy number: {}", "risk_band": "{} risk group", "immune": "RNA immune band {}",
       "tests": "data in {}"}  # a shared field in words


def _show(field: str, v) -> str:
    if v is None:
        return "not on file"
    if field == "receptors":
        return ", ".join(f"{k} {s}" for k, s in v.items())
    if isinstance(v, list):
        return ", ".join(v) or "none"
    return f"stage {v}" if field == "stage" else str(v)


def _hr(rec: dict) -> dict:
    """The receptors with the hormone receptors as one ("HR"): positive when ER or PR is,
    negative when both are stated negative."""
    hr = rec.get("HR") or ("positive" if "positive" in (rec.get("ER"), rec.get("PR")) else
                           "negative" if rec.get("ER") == rec.get("PR") == "negative" else None)
    return {k: v for k, v in {"HR": hr, "HER2": rec.get("HER2")}.items() if v}


def _agree(field: str, a, b) -> float | None:
    """How far two values agree: 1 or 0 for one value; the share of shared items (Jaccard) for a
    set, 1 when both are empty (sequenced, nothing mutated); per receptor both files state (as
    HR and HER2 when one file states only the hormone receptors). None: nothing to compare."""
    if field == "receptors":
        if ("HR" in a) != ("HR" in b):
            a, b = _hr(a), _hr(b)
        both = [k for k in a if k in b]
        return sum(a[k] == b[k] for k in both) / len(both) if both else None
    if isinstance(a, list):
        sa, sb = set(a), set(b)
        return len(sa & sb) / len(sa | sb) if sa | sb else 1.0
    return float(a == b)


def _sides(field: str, a, b) -> tuple[str, str, str]:
    """What differs, as (here, there, in both): the receptors that differ; a set's items on one
    side only and those in common; a value on each side."""
    if field == "receptors":
        if ("HR" in a) != ("HR" in b):
            a, b = _hr(a), _hr(b)
        off = [k for k in a if k in b and a[k] != b[k]]
        return ", ".join(f"{k} {a[k]}" for k in off), ", ".join(f"{k} {b[k]}" for k in off), ""
    if isinstance(a, list):
        return (", ".join(x for x in a if x not in b), ", ".join(x for x in b if x not in a),
                ", ".join(x for x in a if x in b))
    return _show(field, a), _show(field, b), ""


def similar_patients(p: dict, profiles: dict[str, dict], k: int = 5) -> dict:
    """The ``k`` TCGA files nearest to profile ``p`` (``profile``) on ``FIELDS``: a score from 0
    to 1, the weighted share of the fields on which the two agree (``_agree``; a field either
    lacks agrees 0). Each with the fields shared, those that differ (both values) and those not
    compared (shared: "said", the field in words; differing: "here", "there" and "both", what
    differs on each side). The synthetic patient is never a candidate (a hand-written record),
    and the risk group is compared between TCGA files only."""
    total, out = sum(WEIGHTS.values()), []
    for pid, q in profiles.items():
        if pid == p["id"] or q["kind"] != "TCGA-BRCA":
            continue
        shared, differ, missing, score = [], [], [], 0.0
        for f, (name, lab) in FIELDS.items():
            a, b = p[f], q[f]
            s = None if a is None or b is None else _agree(f, a, b)
            if s is None:
                missing.append(name)
                continue
            score += WEIGHTS[f] * s
            here, there, both = _sides(f, a, b)
            row = {"field": name, "label": lab, "this": _show(f, a), "other": _show(f, b),
                   "agree": s, "said": SAY[f].format(_show(f, a)), "here": here,
                   "there": there, "both": both}
            (shared if s == 1 else differ).append(row)
        out.append({"patient": pid, "score": score / total, "shared": shared, "differ": differ,
                    "missing": missing})
    out.sort(key=lambda r: -r["score"])
    return {"method": LOOKUP, "weights": "every field the same (placeholder)",
            "candidates": len(out), "nearest": out[:k]}


# ---------------------------------------------------------------------------- cohort position

METRICS = {  # score -> (name, axis title, evidence label, where it comes from)
    "risk": ("Risk", "predicted log-risk", INFERENCE,
             "the federated risk model (overall survival; ranks patients)"),
    "burden": ("Mutation burden", "somatic calls per Mb", f"{OBSERVED} (count), derived (rate)",
               "GDC open-access masked somatic calls over a 38 Mb exome"),
    "proliferation": ("Proliferation", "cohort z-score", INFERENCE,
                      "the PAM50 proliferation genes (RNA)"),
    "immune": ("Immune signature", "cohort z-score", INFERENCE,
               "ESTIMATE immune genes (RNA; Yoshihara 2013)"),
    "cytolytic": ("Cytolytic activity", "cohort z-score", INFERENCE,
                  "GZMA and PRF1 (RNA; Rooney 2015)"),
    "stromal": ("Stromal signature", "cohort z-score", INFERENCE,
                "ESTIMATE stromal genes (RNA)"),
    "pi3k": ("PI3K/AKT protein", "pathway z-score", INFERENCE,
             "RPPA pathway score (Akbani 2014)"),
    "methylation": ("Methylation index", "mean promoter beta", HYPOTHESIS,
                    "CpG-island promoter probes (450K)"),
}


def cohort_position(p: dict, profiles: dict[str, dict]) -> dict:
    """Where profile ``p`` sits among the TCGA files on each score it has (``METRICS``): its
    value, its percentile among the other files with that score (the share with a lower value,
    ties half) and every file's value for the distribution. The cohort is the TCGA files only;
    the synthetic patient is excluded (its scores, where it has any, are not measured the same
    way). Percentiles, not a prognosis."""
    cohort = {pid: q for pid, q in profiles.items() if q["kind"] == "TCGA-BRCA"}
    metrics = []
    for key, (name, axis, lab, source) in METRICS.items():
        values = {pid: q["scores"][key] for pid, q in cohort.items() if key in q["scores"]}
        if p["id"] not in cohort or key not in p["scores"] or len(values) < 2:
            continue
        x = p["scores"][key]
        others = [v for pid, v in values.items() if pid != p["id"]]
        pct = 100 * (sum(v < x for v in others) + 0.5 * sum(v == x for v in others)) / len(others)
        metrics.append({"key": key, "name": name, "axis": axis, "label": lab, "source": source,
                        "value": x, "percentile": pct, "n": len(values),
                        "text": f"{ordinal(pct)} percentile of {len(values)} files",
                        "values": values})
    excluded = [pid for pid, q in profiles.items() if q["kind"] != "TCGA-BRCA"]
    return {"method": POSITION, "cohort": len(cohort), "excluded": excluded,
            "in_cohort": p["id"] in cohort, "metrics": metrics}

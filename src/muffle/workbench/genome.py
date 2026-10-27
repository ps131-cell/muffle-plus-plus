"""The tumor genome as a picture, for the genomics workbench (docs/genomics.md): copy-number
landscape, mutation burden and allele fractions, predicted effect, a curated pathway map and the
longitudinal variant table. Pure functions, no Streamlit; no model runs here.

Evidence stays apart, as on the rest of the page: a copy number, a read count, a call count and a
recorded variant are **observed**; a copy-number call is a rule on an observed number, with each
cutoff tagged (definition, literature, placeholder); a rate per megabase is **derived**; an
expected allele fraction, an AlphaMissense score and a percentile-based "high" are **model
inference**; ClinVar and CIViC classifications are **interpretation** (shown as hypothesis, for
clinician review); a pathway grouping is a **hypothesis** with its sources. Derived numbers come
from ``app/genomics_cn.json`` (scripts/genomics_scores.py) and ``app/genomics_effect.json``
(scripts/genomics_effect.py), both offline; nothing here reads a patient file from disk.
"""

from __future__ import annotations

import csv
import io
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED

APP = Path(__file__).resolve().parents[3] / "app"
CN_JSON, EFFECT_JSON = APP / "genomics_cn.json", APP / "genomics_effect.json"
IMPLEMENTED, PLANNED = "implemented", "planned"
DEFINITION, LITERATURE, PLACEHOLDER, METHOD = "definition", "literature", "placeholder", "method"
DERIVED = "derived"
VERIFIED = "2026-10-20"  # every PMID and DOI in REFERENCES, checked against PubMed that day

REFERENCES = {  # key -> the paper as PubMed lists it
    "tcga2012": ("Cancer Genome Atlas Network 2012", "Nature 2012;490:61-70", "23000897",
                 "10.1038/nature11412",
                 "Comprehensive molecular portraits of human breast tumours"),
    "sanchezvega2018": ("Sanchez-Vega et al. 2018", "Cell 2018;173:321-337.e10", "29625050",
                        "10.1016/j.cell.2018.03.035",
                        "Oncogenic Signaling Pathways in The Cancer Genome Atlas"),
    "razavi2018": ("Razavi et al. 2018", "Cancer Cell 2018;34:427-438.e6", "30205045",
                   "10.1016/j.ccell.2018.08.008",
                   "The Genomic Landscape of Endocrine-Resistant Advanced Breast Cancers"),
    "nikzainal2016": ("Nik-Zainal et al. 2016", "Nature 2016;534:47-54", "27135926",
                      "10.1038/nature17676",
                      "Landscape of somatic mutations in 560 breast cancer whole-genome sequences"),
    "pereira2016": ("Pereira et al. 2016", "Nat Commun 2016;7:11479", "27161491",
                    "10.1038/ncomms11479", "The somatic mutation profiles of 2,433 breast cancers "
                    "refines their genomic and transcriptomic landscapes"),
    "chalmers2017": ("Chalmers et al. 2017", "Genome Med 2017;9:34", "28420421",
                     "10.1186/s13073-017-0424-2", "Analysis of 100,000 human cancer genomes "
                     "reveals the landscape of tumor mutational burden"),
    "marabelle2020": ("Marabelle et al. 2020 (KEYNOTE-158)", "Lancet Oncol 2020;21:1353-1365",
                      "32919526", "10.1016/S1470-2045(20)30445-9",
                      "Association of tumour mutational burden with outcomes in patients with "
                      "advanced solid tumours treated with pembrolizumab"),
    "cheng2023": ("Cheng et al. 2023 (AlphaMissense)", "Science 2023;381:eadg7492", "37733863",
                  "10.1126/science.adg7492", "Accurate proteome-wide missense variant effect "
                  "prediction with AlphaMissense"),
    "mclaren2016": ("McLaren et al. 2016 (Ensembl VEP)", "Genome Biol 2016;17:122", "27268795",
                    "10.1186/s13059-016-0974-4", "The Ensembl Variant Effect Predictor"),
    "landrum2018": ("Landrum et al. 2018 (ClinVar)", "Nucleic Acids Res 2018;46:D1062-D1067",
                    "29165669", "10.1093/nar/gkx1153", "ClinVar: improving access to variant "
                    "interpretations and supporting evidence"),
    "carter2012": ("Carter et al. 2012 (ABSOLUTE)", "Nat Biotechnol 2012;30:413-21", "22544022",
                   "10.1038/nbt.2203",
                   "Absolute quantification of somatic DNA alterations in human cancer"),
    "taylor2018": ("Taylor et al. 2018", "Cancer Cell 2018;33:676-689.e3", "29622463",
                   "10.1016/j.ccell.2018.03.007",
                   "Genomic and Functional Approaches to Understanding Cancer Aneuploidy"),
    "vanloo2010": ("Van Loo et al. 2010 (ASCAT)", "Proc Natl Acad Sci U S A 2010;107:16910-5",
                   "20837533", "10.1073/pnas.1009843107",
                   "Allele-specific copy number analysis of tumors"),
    "mermel2011": ("Mermel et al. 2011 (GISTIC2.0)", "Genome Biol 2011;12:R41", "21527027",
                   "10.1186/gb-2011-12-4-r41", "GISTIC2.0 facilitates sensitive and confident "
                   "localization of the targets of focal somatic copy-number alteration in human "
                   "cancers"),
}

# --------------------------------------------------------------------------- copy number

# breast drivers of interest for the copy-number view (the brief's list; the data holds them all)
INTEREST = ("ERBB2", "CCND1", "FGFR1", "MYC", "PIK3CA", "PTEN", "RB1", "CDKN2A", "TP53", "ESR1",
            "MDM2", "AURKA")
CALLS = {-2: "deep deletion", -1: "loss", 0: "neutral", 1: "gain", 2: "amplification"}
ALTERED = {-2, -1, 1, 2}
CUTOFFS = [  # the copy-number call rule, one row per cutoff, each with its source tag
    {"name": "ploidy estimate", "rule": "the tumor's median gene-level copy number, rounded, at "
     "least 1", "tag": METHOD,
     "source": "the rule that built the model's copy-number input (muffle.data.tcga."
               "copy_number_calls); ASCAT's own ploidy is not in the open gene-level file, so "
               "ABSOLUTE's (TCGA PanCanAtlas) is shown beside it"},
    {"name": "deep deletion", "rule": "0 copies", "tag": DEFINITION,
     "source": "no copy of the gene left in ASCAT's estimate (Van Loo et al. 2010)"},
    {"name": "loss", "rule": "at least 1 copy, fewer than the ploidy", "tag": PLACEHOLDER,
     "source": "this project's rule; not calibrated"},
    {"name": "gain", "rule": "more copies than the ploidy, fewer than twice it", "tag": PLACEHOLDER,
     "source": "this project's rule; not calibrated"},
    {"name": "amplification", "rule": "at least twice the ploidy", "tag": PLACEHOLDER,
     "source": "by analogy with the ASCO/CAP in situ hybridization ratio of 2.0 (the omics "
               "workbench's rule); not validated on ASCAT calls"},
]
LEVELS_NOTE = ("Five levels in the format of GISTIC's thresholded calls (Mermel et al. 2011); the "
               "cutoffs are this project's rule, not GISTIC's.")


def cn_call(copies, ploidy) -> int | None:
    """The copy-number call of one gene, relative to the tumor's ploidy: -2 deep deletion (0
    copies), -1 loss, 0 neutral, 1 gain, 2 amplification (at least twice the ploidy). The same
    rule as ``muffle.data.tcga.copy_number_calls``, which built the model's input; None when the
    copy number is unknown."""
    if copies is None or ploidy is None or (isinstance(copies, float) and math.isnan(copies)):
        return None
    if copies == 0:
        return -2
    if copies < ploidy:
        return -1
    if copies == ploidy:
        return 0
    return 1 if copies < 2 * ploidy else 2


def load(path: Path) -> dict | None:
    """A precomputed file (copy number, variant effects), parsed once per version on disk and
    shared, so read-only for every caller; None when absent."""
    try:
        s = Path(path).stat()
    except FileNotFoundError:
        return None
    return _parsed(str(path), s.st_mtime_ns, s.st_size)


@lru_cache(maxsize=8)
def _parsed(path: str, mtime_ns: int, size: int) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def case_index(file) -> int | None:
    """The cohort index of a TCGA file ("Case 564" -> 564); None for any other file."""
    m = re.fullmatch(r"Case (\d+)", getattr(file, "id", ""))
    return int(m.group(1)) if m and file.kind == "TCGA-BRCA" else None


def case_block(data: dict | None, file, log_risk: float | None = None) -> dict | None:
    """This file's entry of ``genomics_cn.json``, only when it belongs to the same build: the
    bundle's log-risk must match (``log_risk``, the loaded ``Case``'s) or, without it, the risk
    percentile the file carries. None otherwise, so a rebuilt cohort never pairs these numbers
    with another patient."""
    i = case_index(file)
    block = (data or {}).get("cases", {}).get(str(i)) if i is not None else None
    if block is None:
        return None
    risk = file.versions[0].risk or {}
    log_risk = risk.get("log_risk") if log_risk is None else log_risk
    if log_risk is not None:  # the file carries the case's log-risk (workspace.case_file)
        return block if abs(block["log_risk"] - log_risk) <= 1e-3 else None
    pct = risk.get("percentile")  # an older file without it: the percentile, less strict
    return block if pct is not None and abs(block["percentile"] - pct) <= 0.5 else None


PLOIDY_RATIO = 1.5  # PLACEHOLDER: the two ploidy estimates disagree when one is 1.5x the other


def ploidy_check(block: dict | None) -> dict | None:
    """The model's ploidy estimate (median gene copy number) against ABSOLUTE's; None without
    both. When one is ``PLOIDY_RATIO`` times the other or more, every call relative to the median
    rule is in doubt: a ploidy of 1 makes 2 copies an amplification."""
    if not block or "ploidy" not in block or not block.get("absolute"):
        return None
    med, ab = block["ploidy"], block["absolute"]["ploidy"]
    ratio = max(med, ab) / min(med, ab)
    off = ratio >= PLOIDY_RATIO
    return {"median": med, "absolute": ab, "ratio": round(ratio, 2), "disagree": off,
            "text": f"ploidy {med:g} by the median rule against {ab:.2f} by ABSOLUTE"
                    + (f" ({ratio:.1f}-fold): calls relative to the median rule are in doubt; "
                       "compare the calls relative to ABSOLUTE's ploidy" if off else "")}


def landscape(block: dict, genes: dict, ploidy: float | None = None) -> list[dict]:
    """One row per measured gene in genome order: copies (observed), the ploidy estimate, the
    call by ``cn_call`` (rule), the cohort percentile of copies relative to ploidy and the
    cohort's share of the same call. ``ploidy`` overrides the median-rule estimate (e.g.
    ABSOLUTE's); percentiles and shares stay those of the median rule."""
    pl, rows = ploidy or block.get("ploidy"), []
    for g, (copies, pct) in block.get("cn", {}).items():
        meta = genes.get(g, {})
        call = cn_call(copies, pl)
        rows.append({
            "gene": g, "chrom": meta.get("chrom", "?"), "start_mb": meta.get("start_mb"),
            "order": meta.get("order", 1e9), "copies": copies, "ploidy": pl,
            "ratio": None if copies is None else copies / pl,
            "log2": None if copies is None else round(math.log2(max(copies, 0.25) / pl), 3),
            "call": call, "call_text": CALLS.get(call, "not measured"), "pct": pct,
            "share": None if call is None else meta.get("cohort_calls", [None] * 5)[call + 2],
            "in_layer": meta.get("in_layer", False), "interest": meta.get("interest", False),
            "pathways": meta.get("pathways", []), "evidence": OBSERVED})
    rows.sort(key=lambda r: r["order"])
    for n, r in enumerate(rows):
        r["rank"] = n
    return rows


def cn_queue(rows: list[dict], block: dict | None = None) -> list[str]:
    """What to check by eye on the landscape: two ploidy estimates that disagree, amplified or
    deeply deleted genes of interest or on the pathway map, then the rule's limits."""
    pc = ploidy_check(block)
    out = [pc["text"][0].upper() + pc["text"][1:]] if pc and pc["disagree"] else []
    out += [f"{r['gene']} {r['call_text']} ({r['copies']:g} copies at ploidy {r['ploidy']:g}; "
            f"{_pct(r['pct'])} of the cohort)" for r in rows
            if r["call"] in (2, -2) and (r["interest"] or r["pathways"])]
    out.append("Copy-number calls rest on placeholder cutoffs and an estimated ploidy; tumor "
               "purity changes what a copy number means (see the method card)")
    return out


def neighbors(rows: list[dict], gene: str, window_mb: float = 10.0) -> dict:
    """The measured genes within ``window_mb`` of ``gene`` on its chromosome and how many share
    its call: a hint, for the eye, of a focal change versus a broad one (the segments would
    settle it; only gene-level values are here)."""
    me = next((r for r in rows if r["gene"] == gene), None)
    if me is None or me["start_mb"] is None:
        return {"near": [], "same": 0}
    near = [r for r in rows if r["gene"] != gene and r["chrom"] == me["chrom"]
            and r["start_mb"] is not None and abs(r["start_mb"] - me["start_mb"]) <= window_mb]
    return {"near": near, "same": sum(r["call"] == me["call"] for r in near),
            "window_mb": window_mb}


CN_PROFILE = (r"\b{gene} (?:Amplification|Copy Number Gain|Loss|Deletion|Homozygous Deletion|"
              r"Copy Number Loss)\b")


def cn_items(gene: str, call: int | None, table, k: int = 8) -> dict:
    """CIViC's accepted items in breast cancer for a copy-number change of ``gene`` (its
    amplification, gain, loss or deletion profiles), strongest level first, each marked whether
    its direction matches this tumor's call. For clinician review."""
    if table is None or table.empty:
        return {"items": [], "total": 0}
    pat = CN_PROFILE.format(gene=re.escape(gene))
    t = table[table["disease"].str.contains("breast", case=False, regex=False)
              & table["molecular_profile"].str.contains(pat, regex=True)]
    t = t.assign(_level=t["evidence_level"].map(lambda v: "ABCDE".find(v) % 6))
    t = t.sort_values(["_level", "molecular_profile"])
    items = []
    for _, r in t.head(k).iterrows():
        up = re.search(r"Amplification|Gain", r["molecular_profile"]) is not None
        items.append({"molecular_profile": r["molecular_profile"],
                      "therapies": r["therapies"] or "none named",
                      "evidence_level": r["evidence_level"], "significance": r["significance"],
                      "direction": r["evidence_direction"], "citation": r["citation"],
                      "url": r["evidence_civic_url"],
                      "matches_call": None if call is None else (up and call > 0)
                      or (not up and call < 0)})
    return {"items": items, "total": len(t)}


def _pct(p) -> str:
    if p is None:
        return "percentile unknown"
    n = int(p)
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix} percentile"


def consistency(rows: list[dict], receptor_lines: list[dict],
                rna: dict | None = None) -> list[dict]:
    """Consistency lines for the copy-number view. The ERBB2-versus-HER2 line is the omics
    workbench's own (``muffle.workbench.omics.receptor_lines``, compare "IHC vs copy number"),
    reused, never recomputed; a second line says if the two workbenches read different ERBB2
    copy numbers. ``rna`` maps a gene to its RNA cohort percentile from the expression workbench:
    an amplified gene above the cohort median, or a deleted one below it, agrees (median:
    placeholder)."""
    out = []
    for x in receptor_lines:
        if x["compare"] == "IHC vs copy number":
            out.append({"what": "ERBB2 copy number vs recorded HER2 status", "text": x["text"],
                        "status": x["status"], "source": "the omics workbench's line, reused",
                        "evidence": x["evidence"], "check": x["check"]})
    erbb2 = next((r for r in rows if r["gene"] == "ERBB2"), None)
    m = re.search(r"ERBB2 copy number ([\d.]+) at a tumor ploidy of ([\d.]+)",
                  " ".join(x["text"] for x in receptor_lines))
    read = (float(m.group(1)), float(m.group(2))) if m else None
    if erbb2 and read and read != (erbb2["copies"], erbb2["ploidy"]):
        out.append({"what": "ERBB2 in two workbenches", "status": "disagree",
                    "text": f"the omics workbench reads {m.group(1)} copies at ploidy "
                            f"{m.group(2)}; this view reads {erbb2['copies']:g} at "
                            f"{erbb2['ploidy']:g}", "source": "both from ASCAT3 gene level",
                    "evidence": OBSERVED, "check": "a rebuilt score file on one side"})
    for r in rows:
        if r["call"] not in (2, -2) or rna is None or r["gene"] not in rna:
            continue
        pct = rna[r["gene"]]
        agree = pct >= 50 if r["call"] == 2 else pct < 50
        out.append({"what": f"{r['gene']} copy number vs RNA",
                    "text": f"{r['gene']} {r['call_text']}; its RNA at the {_pct(pct)} of the "
                            "cohort (expression workbench)",
                    "status": "agree" if agree else "disagree",
                    "source": "RNA percentile from the expression workbench; the cohort median "
                              "as the line (placeholder)",
                    "evidence": f"{OBSERVED} (copy number, RNA)",
                    "check": "tumor purity and the RNA's tumor content; a gained gene need not be "
                             "expressed"})
    return out


# --------------------------------------------------------------------------- burden, fractions

EXOME_MB = 38.0  # Chalmers et al. 2017: "We used 38 Mb as the estimate of the exome size" (TCGA)
HIGH_PCT = 90.0  # PLACEHOLDER: "high in this cohort" = the top decile of the cohort's rate
KEYNOTE_RATE = 10.0  # Marabelle et al. 2020: tTMB-high, FoundationOne CDx, ten non-breast cohorts
CLASSES = {"missense_variant": "missense", "stop_gained": "nonsense",
           "frameshift_variant": "frameshift", "splice_acceptor_variant": "splice site",
           "splice_donor_variant": "splice site", "inframe_deletion": "in-frame deletion",
           "inframe_insertion": "in-frame insertion", "start_lost": "start lost",
           "stop_lost": "stop lost", "protein_altering_variant": "protein-altering (other)",
           "synonymous_variant": "silent"}


def consequence_class(term: str) -> str:
    """A VEP consequence term in clinician words (missense, nonsense, frameshift, splice site)."""
    return CLASSES.get(term, term.replace("_", " "))


def burden(block: dict | None, data: dict | None) -> dict:
    """The mutation burden of one case: the observed count of somatic calls (and of coding and
    protein-altering ones), the derived rate over the 38 Mb exome, its cohort percentile, and two
    labeled reference lines (the cohort's top decile, a placeholder; KEYNOTE-158's 10 per Mb,
    literature from another assay and other cancers)."""
    b = (block or {}).get("burden")
    if not b:
        return {"measured": False, "note": "not sequenced: the burden is unknown"}
    ref = (data or {}).get("burden", {})
    return {"measured": True, **b, "exome_mb": ref.get("exome_mb", EXOME_MB),
            "median_rate": ref.get("rate_median"), "high": b["pct"] >= HIGH_PCT,
            "above_keynote": b["rate"] >= KEYNOTE_RATE,
            "evidence": {"count": OBSERVED, "rate": f"{DERIVED} (count / {EXOME_MB:g} Mb)",
                         "high": f"{INFERENCE} (cohort percentile; placeholder cutoff)"},
            "text": (f"{b['calls']} somatic calls in the open masked file ({b['altering']} "
                     f"protein-altering): {b['rate']:.2f} per Mb over a {EXOME_MB:g} Mb exome, "
                     f"the {_pct(b['pct'])} of this cohort")}


def wilson(alt: int, depth: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval of an allele fraction (as in ``muffle.evolution.wilson``)."""
    if depth <= 0:
        return (0.0, 1.0)
    p = alt / depth
    half = z * math.sqrt(p * (1 - p) / depth + z * z / (4 * depth * depth)) / (1 + z * z / depth)
    mid = (p + z * z / (2 * depth)) / (1 + z * z / depth)
    return (max(0.0, mid - half), min(1.0, mid + half))


def clonal_range(purity: float | None, copies: float | None) -> tuple[float, float] | None:
    """The allele fraction a clonal mutation would show at this purity and copy number, from one
    mutant copy to all of them: f = purity x m / (purity x copies + 2 x (1 - purity)) (the
    ABSOLUTE relation, Carter et al. 2012; normal cells diploid). None without purity or copies."""
    if not purity or not copies:
        return None
    denom = purity * copies + 2 * (1 - purity)
    return (purity / denom, purity * copies / denom)


def allele_fractions(block: dict | None, reads: dict | None) -> list[dict]:
    """The observed drivers of one case: consequence class, read counts (``reads``: this case's
    entry of ``app/evolution_vaf.json``), allele fraction with its 95% interval, purity
    (ABSOLUTE), the gene's copies, the clonal range and how the observed fraction sits in it
    (model inference)."""
    if not block:
        return []
    by_name = {v["variant"]: v for v in (reads or {}).get("variants", [])}
    purity = (block.get("absolute") or {}).get("purity")
    out = []
    for d in block.get("drivers", []):
        r = by_name.get(d["variant"], {})
        alt, depth = r.get("alt"), r.get("depth")
        vaf = alt / depth if alt is not None and depth else d.get("dna_vaf")
        lo, hi = wilson(alt, depth) if alt is not None and depth else (None, None)
        rng = clonal_range(purity, d.get("copies"))
        if rng is None or lo is None:
            fit = "not assessed: purity or read depth unknown"
        elif hi < rng[0]:
            fit = ("below the clonal range: possibly subclonal, or lower tumor content at this "
                   "spot")
        elif lo > rng[1]:
            fit = "above the clonal range: the purity or copy-number estimate may be off here"
        else:
            fit = "within the clonal range"
        out.append({**d, "alt": alt, "depth": depth, "vaf": vaf, "lo": lo, "hi": hi,
                    "purity": purity, "clonal_range": rng, "fit": fit,
                    "evidence": {"reads": OBSERVED, "interval": f"{METHOD} (Wilson 95%)",
                                 "purity": f"{INFERENCE} (ABSOLUTE)",
                                 "fit": f"{INFERENCE} (assumes the gene's copy number at the "
                                        "variant and diploid normal cells)"}})
    return out


# --------------------------------------------------------------------------- predicted effect

AM_CLASSES = {"likely_benign": "likely benign", "ambiguous": "ambiguous",
              "likely_pathogenic": "likely pathogenic"}
AM_LIMITS = ("AlphaMissense has not been validated for, and is not approved for, any clinical use "
             "(its authors). It predicts pathogenicity from protein structure and population "
             "frequency, not somatic oncogenicity: a known hotspot can score ambiguous. Missense "
             "changes only.")
CLINVAR_NOTE = ("ClinVar classifications as Ensembl serves them with the co-located variant "
                "record (germline clinical significance; somatic oncogenicity), for clinician "
                "review; submitters' evidence is on ClinVar.")


def effect(variant: str, effects: dict | None) -> dict:
    """The three evidence types of one variant's effect, kept apart: the annotation of the call
    (Ensembl VEP: consequence on the MANE Select transcript; observed), its interpretation
    (ClinVar via Ensembl; hypothesis, for clinician review) and its prediction (AlphaMissense;
    model inference, not approved for clinical use). Missing parts say so."""
    e = ((effects or {}).get("variants") or {}).get(variant)
    snap = (effects or {}).get("snapshot", "not taken")
    if not e:
        return {"variant": variant, "found": False, "snapshot": snap,
                "note": "not in the effect snapshot: no annotation, ClinVar or AlphaMissense "
                        "lookup for this variant yet"}
    am = e.get("alphamissense")
    clin = e.get("clinvar") or {}
    return {
        "variant": variant, "found": True, "snapshot": snap, "live": bool(e.get("live")),
        "annotation": {"evidence": OBSERVED, "source": "Ensembl VEP (REST)",
                       "consequence": e.get("consequence"), "hgvsc": e.get("hgvsc"),
                       "hgvsp": e.get("hgvsp"), "transcript": e.get("mane") or e.get("transcript"),
                       "position": e.get("position")},
        "interpretation": {"evidence": HYPOTHESIS, "source": "ClinVar via Ensembl (REST)",
                           "germline": clin.get("germline") or [],
                           "somatic": clin.get("somatic") or "",
                           "record": clin.get("record") or "", "note": CLINVAR_NOTE,
                           "found": bool(clin)},
        "prediction": {"evidence": INFERENCE, "predictor": "AlphaMissense (Cheng et al. 2023)",
                       "score": None if not am else am["score"],
                       "class": None if not am else AM_CLASSES.get(am["class"], am["class"]),
                       "source": None if not am else am.get("source"),
                       "applies": e.get("consequence") == "missense_variant",
                       "limits": AM_LIMITS},
    }


def effect_text(ef: dict) -> dict[str, str]:
    """One line per evidence type for tables and exports."""
    if not ef["found"]:
        return {"annotation": ef["note"], "interpretation": "", "prediction": ""}
    a, i, p = ef["annotation"], ef["interpretation"], ef["prediction"]
    clin = ", ".join(c.replace("_", " ") for c in i["germline"]) or "no germline classification"
    if i["somatic"]:
        clin += f"; somatic: {i['somatic']}"
    pred = (f"{p['score']:.3f} ({p['class']})" if p["score"] is not None else
            "not applicable (missense changes only)" if not p["applies"] else "no score")
    return {"annotation": f"{(a['consequence'] or '?').replace('_', ' ')} · {a['hgvsp'] or ''}",
            "interpretation": clin if i["found"] else "no ClinVar record found",
            "prediction": pred}


# --------------------------------------------------------------------------- pathway map

PATHWAYS = {  # name -> genes, the sources and what each reports (checked in the full text)
    "ER signaling": {
        "genes": ["ESR1", "GATA3", "FOXA1", "TBX3", "MYC"],
        "says": [("tcga2012", "GATA3 is one of three genes mutated in more than 10% of breast "
                              "cancers; TBX3 newly significantly mutated; FOXA1 at or near "
                              "significance"),
                 ("razavi2018", "ESR1 and the estrogen receptor transcriptional regulators MYC, "
                                "CTCF, FOXA1 and TBX3 were altered more often in tumors exposed "
                                "to hormonal therapy (692 of 1,918)")]},
    "HER2 / RTK": {
        "genes": ["ERBB2", "EGFR", "FGFR1"],
        "says": [("tcga2012", "focal amplifications of regions containing HER2/ERBB2 and "
                              "HER1/EGFR; FGFR amplifications in luminal tumours, FGFR1 among "
                              "the RTKs amplified in some basal-like cancers"),
                 ("razavi2018", "activating ERBB2 mutations were more than twice as common in "
                                "endocrine-resistant tumors"),
                 ("nikzainal2016", "ERBB2 and the ZNF703/FGFR1 locus among the 10 most "
                                   "frequently altered driver genes in 560 genomes")]},
    "PI3K / AKT / mTOR": {
        "genes": ["PIK3CA", "PTEN", "AKT1", "PIK3R1"],
        "says": [("tcga2012", "PIK3CA, PTEN, AKT1 and PIK3R1 significantly mutated; PIK3CA in "
                              "45% of luminal A tumors"),
                 ("sanchezvega2018", "the PI3K pathway altered by activating PIK3CA events and "
                                     "inactivating events in PTEN or PIK3R1")]},
    "Cell cycle": {
        "genes": ["CCND1", "CDK4", "CDK6", "RB1", "CDKN2A"],
        "says": [("tcga2012", "amplifications of cyclin D1/CDK4/CDK6 in luminal tumours; RB1 "
                              "significantly mutated"),
                 ("sanchezvega2018", "cell-cycle events include CDKN2A mutation, RB1 loss and "
                                     "CDK6 amplification; MDM2 and CDK4 lie close in the genome "
                                     "and were almost always co-amplified")]},
    "TP53 and DNA repair": {
        "genes": ["TP53", "MDM2", "ATM", "BRCA1", "BRCA2", "PALB2"],
        "says": [("tcga2012", "TP53 mutated in more than 10% of breast cancers; the pathway "
                              "also inactivated by ATM loss and MDM2 amplification; germline "
                              "variants in ATM, BRCA1, BRCA2, CHEK2 and others"),
                 ("nikzainal2016", "rearrangement signatures tied to deficient BRCA1 or BRCA2 "
                                   "function (homologous-recombination repair); ATM and PALB2 "
                                   "among the double-strand-break repair genes examined")]},
    "MAP kinase": {
        "genes": ["NF1", "KRAS", "MAP3K1", "MAP2K4"],
        "says": [("tcga2012", "likely inactivating mutations in MAP3K1 and MAP2K4 in 12% of "
                              "luminal A tumors; NF1 newly significantly mutated"),
                 ("razavi2018", "NF1 loss-of-function mutations more than twice as common in "
                                "endocrine-resistant tumors; KRAS among the enriched MAPK-pathway "
                                "genes")]},
    "Chromatin": {
        "genes": ["ARID1A", "KMT2C"],
        "says": [("pereira2016", "KMT2C (MLL3) mutated in 11.4% of 2,433 primary breast tumours"),
                 ("razavi2018", "ARID1A among the epigenetic regulators enriched in hormone-"
                                "receptor-positive metastatic tumors"),
                 ("tcga2012", "MLL3 (KMT2C) significantly mutated, with focal deletions")]},
}
PATHWAY_GENES = tuple(dict.fromkeys(g for p in PATHWAYS.values() for g in p["genes"]))
PATHWAY_NOTE = ("A grouping of genes by pathway, curated for this workbench from the sources "
                "listed; arrows of signaling are not drawn. Hypothesis: a hit on a pathway is not "
                "proof the pathway is active in this tumor.")
STATUS_ORDER = ["mutated", "amplification", "deep deletion", "gain", "loss", "not altered",
                "not measured"]


def reference(key: str) -> dict:
    cite, where, pmid, doi, title = REFERENCES[key]
    return {"key": key, "cite": cite, "where": where, "pmid": pmid, "doi": doi, "title": title,
            "url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/", "doi_url": f"https://doi.org/{doi}"}


def pathway_map(variants: list[str], rows: list[dict], sequenced: bool) -> list[dict]:
    """One row per pathway gene with this tumor's observed alterations: "mutated" (a sequenced
    variant), the copy-number call when altered, "not altered" when measured without either, "not
    measured" otherwise (unknown, not normal). ``variants``: observed "GENE CHANGE" names;
    ``rows``: ``landscape`` rows (empty when there is no copy number); ``sequenced``: whether the
    sample's sequencing covered the pathway genes."""
    cn = {r["gene"]: r for r in rows}
    hits: dict[str, list[str]] = {}
    for v in variants:
        hits.setdefault(v.split(" ")[0], []).append(v)
    out = []
    for name, pw in PATHWAYS.items():
        for n, g in enumerate(pw["genes"]):
            r = cn.get(g)
            marks = []
            if g in hits:
                marks.append("mutated")
            if r and r["call"] in ALTERED:
                marks.append(r["call_text"])
            measured = (sequenced or g in hits) or r is not None
            status = marks[0] if marks else "not altered" if measured else "not measured"
            out.append({"pathway": name, "gene": g, "slot": n, "status": status,
                        "statuses": marks, "variants": hits.get(g, []),
                        "copies": None if r is None else r["copies"],
                        "call": None if r is None else r["call_text"],
                        "pct": None if r is None else r["pct"],
                        "sequenced": sequenced, "cn_measured": r is not None,
                        "evidence": f"{OBSERVED} (alterations); {HYPOTHESIS} (grouping)"})
    return out


def pathway_summary(nodes: list[dict]) -> list[dict]:
    """Per pathway: the altered genes and how, with the sources."""
    out = []
    for name, pw in PATHWAYS.items():
        mine = [n for n in nodes if n["pathway"] == name]
        hit = [f"{n['gene']} ({', '.join(n['statuses'])})" for n in mine if n["statuses"]]
        out.append({"pathway": name, "genes": pw["genes"], "altered": hit,
                    "unknown": [n["gene"] for n in mine if n["status"] == "not measured"],
                    "sources": [reference(k) | {"says": s} for k, s in pw["says"]],
                    "evidence": HYPOTHESIS})
    return out


def pathway_items(name: str, table, k: int = 6) -> dict:
    """CIViC's accepted predictive items in breast cancer whose molecular profile names a gene of
    the pathway, strongest level first: {"items": first k, "total"}. For clinician review."""
    if table is None or table.empty:
        return {"items": [], "total": 0}
    genes = "|".join(PATHWAYS[name]["genes"])
    t = table[table["disease"].str.contains("breast", case=False, regex=False)
              & table["molecular_profile"].str.contains(rf"\b(?:{genes})\b", regex=True)]
    t = t.assign(_level=t["evidence_level"].map(lambda v: "ABCDE".find(v) % 6))
    t = t.sort_values(["_level", "molecular_profile"]).drop_duplicates(
        ["molecular_profile", "therapies", "significance", "citation"])
    return {"total": len(t), "items": [
        {"molecular_profile": r["molecular_profile"], "therapies": r["therapies"] or "none named",
         "evidence_level": r["evidence_level"], "significance": r["significance"],
         "direction": r["evidence_direction"], "citation": r["citation"],
         "url": r["evidence_civic_url"]} for _, r in t.head(k).iterrows()]}


# --------------------------------------------------------------------------- longitudinal table

NOT_RESEQUENCED = ""  # a blank cell: the sample did not look, which is never "absent"


def _tissue_samples(file, version: int | None) -> list[dict]:
    """Every sequencing test of the file up to ``version`` (the record's and imported ones)."""
    vs = file.versions if version is None else file.versions[:version + 1]
    out = []
    for v in vs:
        for t in v.tests:
            if t.workbench != "mutations":
                continue
            d = t.details
            found = d.get("variants") or []
            panel = d.get("panel")
            if file.kind == "synthetic" and not v.imported:
                panel = None  # the record names what it found, not its panel
            out.append({"id": f"{t.name} · {'baseline' if t.month is None else f'month {t.month}'}",
                        "month": t.month, "kind": "imported sequencing" if v.imported else
                        "tumor sequencing", "assay": d.get("assay", t.name), "found": found,
                        "vaf": d.get("vaf") or {}, "panel": None if panel is None else set(panel),
                        "variants_only": False, "imported": v.imported})
    return out


def _ctdna_samples(ctdna: dict | None, month: int | None) -> list[dict]:
    if not ctdna:
        return []
    tracked = set(ctdna.get("variants", ()))
    limit = ctdna.get("detection_limit")
    out = []
    for s in ctdna.get("samples", []):
        if month is not None and s["month"] > month:
            continue
        vaf = {k: v for k, v in s["vaf"].items()}
        out.append({"id": f"ctDNA · month {s['month']}", "month": s["month"], "kind": "ctDNA",
                    "assay": ctdna.get("assay", "ctDNA"),
                    "found": [k for k, v in vaf.items() if v is not None],
                    "vaf": {k: v / 100 for k, v in vaf.items() if v is not None},
                    "panel": tracked, "variants_only": True, "limit": limit,
                    "synthetic": ctdna.get("synthetic", False), "imported": ""})
    return out


def longitudinal_table(file, version: int | None = None, ctdna: dict | None = None,
                       vaf: dict | None = None) -> dict:
    """One row per variant, one column per sample (tumor sequencing, ctDNA, imported sequencing),
    in time order. A cell is "detected" with its allele fraction, "not detected" only when the
    sample looked (its panel covered the gene, or the ctDNA assay tracked the variant), and blank
    otherwise: not re-sequenced or not covered, never "absent". ``ctdna`` is shaped like
    ``muffle.timeline.CTDNA`` (None: not yet available); ``vaf`` maps a variant to its allele
    fraction in the baseline TCGA sample (from the read counts)."""
    month = None if version is None else file.versions[version].month
    samples = _tissue_samples(file, version) + _ctdna_samples(ctdna, month)
    samples.sort(key=lambda s: (-1e9 if s["month"] is None else s["month"], s["kind"] != "ctDNA"))
    names = list(dict.fromkeys(v for s in samples for v in s["found"]))
    rows = []
    for name in names:
        gene = name.split(" ")[0]
        cells = []
        for s in samples:
            if name in s["found"]:
                f = s["vaf"].get(name)
                if f is None and s["kind"] == "tumor sequencing":
                    f = (vaf or {}).get(name)
                cells.append({"state": "detected", "vaf": f,
                              "text": "detected" + ("" if f is None else f" ({f:.1%})")})
            elif s["panel"] is not None and (name in s["panel"] if s["variants_only"]
                                             else gene in s["panel"]):
                lim = s.get("limit")
                cells.append({"state": "not detected", "vaf": None,
                              "text": "not detected" + (f" (below {lim:g}%)" if lim else "")})
            else:
                cells.append({"state": "blank", "vaf": None, "text": NOT_RESEQUENCED})
        rows.append({"variant": name, "gene": gene, "cells": cells})
    notes = []
    if ctdna is None:
        notes.append("ctDNA series: not yet available in this record")
    elif any(s.get("synthetic") for s in samples):
        notes.append("the ctDNA series is synthetic, written for this synthetic patient")
    if file.kind == "synthetic":
        notes.append("the record names the variants its tumor sequencing found, not its panel, "
                     "so other variants are blank there, not 'not detected'")
    if len([s for s in samples if s["kind"] != "ctDNA"]) <= 1:
        notes.append("one tissue sample: blank cells are not re-sequenced, never absent")
    return {"samples": [{k: s[k] for k in ("id", "month", "kind", "assay")} for s in samples],
            "rows": rows, "notes": notes, "evidence": OBSERVED,
            "rule": "detected / not detected only where the sample looked; blank = not "
                    "re-sequenced or not covered (unknown, never absent)"}


def escape_links(gene: str, hs: dict | None) -> list[dict]:
    """The Evolution view's escape-route rows (``muffle.evolution.hypothesis_set``) that name
    ``gene``: raised ones with their status, and ones not raised with the reason."""
    if not hs:
        return []
    out = [{"id": i["id"], "event": i["event"], "raised": True, "status": i["status"]}
           for i in hs.get("items", []) if gene in i.get("genes", [])]
    from muffle.evolution import TABLE  # the table rows name their genes; not_raised does not
    genes = {r["id"]: r["genes"] for r in TABLE}
    out += [{"id": s["id"], "event": s["event"], "raised": False, "status": s["reason"]}
            for s in hs.get("not_raised", []) if gene in genes.get(s["id"], [])]
    return out


# --------------------------------------------------------------------------- patient overview

def _opens(file) -> tuple:
    t = next((t for t in file.tests if t.workbench == "mutations"), None)
    return () if t is None else ("Tests", t.kind, t.month, t.name)


def overview_cards(file, data: dict | None = None) -> list[dict]:
    """Finding cards for the patient overview (``workspace.card``): the copy-number calls of the
    breast drivers and pathway genes, and the mutation burden. [] for a file without the
    precomputed numbers (the synthetic patient, another build)."""
    from muffle.workspace import card
    data = load(CN_JSON) if data is None else data
    block = case_block(data, file)
    if not block:
        return []
    rows = [r for r in landscape(block, data["genes"]) if r["interest"] or r["pathways"]]
    pc = ploidy_check(block)
    trust = "weak" if pc and pc["disagree"] else "moderate"
    hits = {c: [r["gene"] for r in rows if r["call"] == c] for c in (2, -2)}
    text = "; ".join(f"{CALLS[c]}: {', '.join(g)}" for c, g in hits.items() if g) or (
        "no amplification or deep deletion among the breast drivers and pathway genes")
    text += f" (ploidy {block['ploidy']:g} by the median rule" + (
        f", {block['absolute']['ploidy']:.2f} by ABSOLUTE)" if block.get("absolute") else ")")
    out = [card("Copy number", text, f"{OBSERVED} (copies); calls by a rule with placeholder "
                "cutoffs", "ASCAT3 gene-level copy number, the TCGA tumor sample",
                f"calls relative to the ploidy, {data.get('version', '?')}",
                "placeholder: amplification at twice the ploidy, by analogy with the ASCO/CAP "
                "in situ hybridization ratio of 2.0", trust, _opens(file),
                {"gene": (hits[2] or hits[-2] or ["ERBB2"])[0]})]
    bur = burden(block, data)
    if bur.get("measured"):
        out.append(card("Mutation burden", f"{bur['rate']:.2f} somatic calls per Mb, the "
                        f"{_pct(bur['pct'])} of this cohort" + (" (high in this cohort)"
                                                                 if bur["high"] else ""),
                        f"{OBSERVED} (count), {DERIVED} (rate)",
                        "GDC open-access masked somatic calls, the TCGA tumor sample",
                        f"calls / {EXOME_MB:g} Mb (Chalmers et al. 2017)",
                        "placeholder: high = the cohort's top decile", "moderate", _opens(file)))
    return out


def overview_items(file, data: dict | None = None) -> list[dict]:
    """Look-here items for the patient overview (``workspace.look``): two ploidy estimates that
    disagree, then each amplified or deeply deleted breast driver or pathway gene (ERBB2
    amplification weighs 2: the clinical HER2 test settles it; the rest 1)."""
    from muffle.workspace import finding_key, look
    data = load(CN_JSON) if data is None else data
    block = case_block(data, file)
    if not block:
        return []
    pc = ploidy_check(block)
    trust = "weak" if pc and pc["disagree"] else "moderate"
    src = "ASCAT3 gene-level copy number, the TCGA tumor sample"
    out = []
    if pc and pc["disagree"]:
        out.append(look("ploidy", "Two ploidy estimates disagree", pc["text"],
                        f"{OBSERVED} (copies), {INFERENCE} (ploidy)", "moderate", 1, _opens(file),
                        source=src, key=finding_key(file, "cn", "ploidy estimate"),
                        focus={"gene": "ERBB2"},
                        threshold=f"placeholder: {PLOIDY_RATIO:g}-fold apart"))
    for r in landscape(block, data["genes"]):
        if r["call"] not in (2, -2) or not (r["interest"] or r["pathways"]):
            continue
        weight = 2 if (r["gene"], r["call"]) == ("ERBB2", 2) else 1
        out.append(look(r["gene"], f"{r['gene']} {r['call_text']}",
                        f"{r['copies']:g} copies at ploidy {r['ploidy']:g}, the {_pct(r['pct'])} "
                        "of this cohort" + ("; in situ hybridization is the clinical test"
                                            if weight == 2 else ""),
                        f"{OBSERVED} (copies); rule with placeholder cutoffs", trust, weight,
                        _opens(file), source=src, key=finding_key(file, "cn", r["gene"]),
                        focus={"gene": r["gene"]},
                        threshold="placeholder: amplification at twice the ploidy, deep "
                                  "deletion at 0 copies (definition)"))
    return out


# --------------------------------------------------------------------------- search, card, export

def search(query: str, rows: list[dict], nodes: list[dict], bur: dict,
           variants: list[str]) -> dict:
    """Plain-word search over the genome views: "amplified", "deleted", "loss", "gain", a gene
    symbol, a pathway ("PI3K pathway"), "high burden" or "burden". Returns {"genes", "pathways",
    "burden", "note"}; a query the views cannot answer gets an honest note."""
    q = (query or "").strip().lower()
    out = {"genes": [], "pathways": [], "burden": None, "note": None}
    if not q:
        return out
    words = {"amplified": {2}, "amplification": {2}, "deleted": {-2}, "deep deletion": {-2},
             "deletion": {-2}, "loss": {-1, -2}, "lost": {-1, -2}, "gain": {1, 2},
             "gained": {1, 2}}
    if q in words:
        out["genes"] = [r["gene"] for r in rows if r["call"] in words[q]]
        if not rows:
            out["note"] = "no copy number for this file: the copy-number view can't answer that"
        elif not out["genes"]:
            out["note"] = f"no measured gene is {q} here"
        return out
    if "burden" in q or q in ("tmb", "mutation load"):
        out["burden"] = bur
        if not bur.get("measured"):
            out["note"] = "not sequenced: the burden is unknown"
        elif "high" in q and not bur["high"]:
            out["note"] = (f"not high: {bur['text']} (high = top decile of this cohort, a "
                           "placeholder)")
        return out
    pq = q.removesuffix(" pathway").strip()
    out["pathways"] = [p for p in PATHWAYS if pq and (pq in p.lower() or any(
        pq == w.strip().lower() for w in re.split(r"[/,]| and ", p)))]
    sym = q.upper()
    if sym in {r["gene"] for r in rows} | {n["gene"] for n in nodes} | {
            v.split(" ")[0] for v in variants}:
        out["genes"] = [sym]
        out["pathways"] += [p for p in PATHWAYS if sym in PATHWAYS[p]["genes"]
                            and p not in out["pathways"]]
    if not out["genes"] and not out["pathways"]:
        out["note"] = (f"\"{query}\" is not in the copy-number, burden or pathway views. RNA and "
                       "protein: the expression workbench; tissue: the slide workbench; a gene "
                       "outside the views' gene set is not read here.")
    return out


def card(data: dict | None, effects: dict | None,
         omics_validation: dict | None = None) -> list[dict]:
    """The model-and-validation card: every predictor, rule and cutoff of the genome views with
    its source, its tag and its status."""
    her2 = ((omics_validation or {}).get("receptors", {}).get("HER2", {}) or {}).get("cn")
    check = (data or {}).get("checks", {}).get("calls_vs_bundle")
    amp_check = (f"against recorded HER2 status in this cohort, ERBB2 at this cutoff: sensitivity "
                 f"{her2['sensitivity']:.2f}, specificity {her2['specificity']:.2f} "
                 f"(n = {her2['n']}; the omics workbench's check)" if her2 else
                 "not checked here")
    ref = lambda k: f"{REFERENCES[k][0]}, {REFERENCES[k][1]}, doi:{REFERENCES[k][3]}"  # noqa: E731
    rows = [
        {"what": f"copy-number call: {c['name']}", "rule": c["rule"], "source": c["source"]
         + (f"; {amp_check}" if c["name"] == "amplification" else ""), "tag": c["tag"],
         "status": IMPLEMENTED} for c in CUTOFFS]
    rows += [
        {"what": "calls against the model's input", "rule": "the same rule on the same file",
         "source": f"{check[0]} of {check[1]} gene calls of the bundled cases equal the model's "
                   "copy-number input" if check else "not checked", "tag": METHOD,
         "status": IMPLEMENTED},
        {"what": "copy-number percentile", "rule": "copies relative to ploidy, mid-rank among the "
         "cohort's tumors (ties split)",
         "source": f"{(data or {}).get('reference', {}).get('copy_number_tumors', '?')} TCGA-BRCA "
                   "tumors of the model's cohort", "tag": METHOD, "status": IMPLEMENTED},
        {"what": "purity and ploidy", "rule": "ABSOLUTE calls of TCGA PanCanAtlas",
         "source": f"{ref('carter2012')}; {ref('taylor2018')}", "tag": INFERENCE,
         "status": IMPLEMENTED},
        {"what": "ploidy estimates disagree", "rule": f"one of the median rule and ABSOLUTE at "
         f"least {PLOIDY_RATIO:g} times the other", "source": "this project's rule; the page "
         "warns and offers calls relative to ABSOLUTE's ploidy", "tag": PLACEHOLDER,
         "status": IMPLEMENTED},
        {"what": "mutation burden rate", "rule": f"somatic calls / {EXOME_MB:g} Mb",
         "source": f"exome size as in {ref('chalmers2017')} for TCGA", "tag": LITERATURE,
         "status": IMPLEMENTED},
        {"what": "high burden (in this cohort)", "rule": f"at or above the {HIGH_PCT:g}th "
         "percentile of this cohort's rate", "source": "this project's rule", "tag": PLACEHOLDER,
         "status": IMPLEMENTED},
        {"what": "reference line: 10 mutations per Mb", "rule": "tTMB-high in KEYNOTE-158",
         "source": f"{ref('marabelle2020')}: FoundationOne CDx panel, ten non-breast tumour "
                   "types; not this exome, not breast cancer: orientation only, not applied",
         "tag": LITERATURE, "status": "shown, not used for any call"},
        {"what": "allele fraction interval", "rule": "Wilson 95% interval from alt reads / depth",
         "source": "GDC per-case masked MAFs (read counts, app/evolution_vaf.json)",
         "tag": METHOD, "status": IMPLEMENTED},
        {"what": "clonal range", "rule": "purity x m / (purity x copies + 2 (1 - purity)), m = 1 "
         "to copies", "source": ref("carter2012"), "tag": INFERENCE, "status": IMPLEMENTED},
        {"what": "predicted effect", "rule": "AlphaMissense score and class (its authors' "
         "classes)", "source": f"{ref('cheng2023')}; predictions CC BY 4.0; {AM_LIMITS}",
         "tag": INFERENCE, "status": IMPLEMENTED},
        {"what": "consequence annotation", "rule": "Ensembl VEP on the MANE Select transcript",
         "source": f"{ref('mclaren2016')}; Ensembl REST, snapshot "
                   f"{(effects or {}).get('snapshot', 'not taken')}", "tag": METHOD,
         "status": IMPLEMENTED},
        {"what": "ClinVar classification", "rule": "as Ensembl serves it with the co-located "
         "variant", "source": f"{ref('landrum2018')}", "tag": "interpretation",
         "status": IMPLEMENTED},
        {"what": "pathway map", "rule": "curated grouping of 30 genes into 7 pathways",
         "source": "; ".join(sorted({REFERENCES[k][0] for p in PATHWAYS.values()
                                     for k, _ in p["says"]})) + f" (checked {VERIFIED})",
         "tag": HYPOTHESIS, "status": IMPLEMENTED},
    ]
    return rows


def findings(file, rows: list[dict], bur: dict, nodes: list[dict], afs: list[dict],
             effects: dict | None) -> list[dict]:
    """Every genome finding with its evidence and review key, for the CSV and JSON exports."""
    from muffle.workspace import finding_key
    out = [{"kind": "cn", "name": r["gene"], "value": r["call_text"],
            "detail": f"{r['copies']:g} copies at ploidy {r['ploidy']:g}; {_pct(r['pct'])}",
            "evidence": f"{OBSERVED} (copies); rule ({PLACEHOLDER} cutoffs)",
            "key": finding_key(file, "cn", r["gene"])} for r in rows if r["copies"] is not None]
    if bur.get("measured"):
        out.append({"kind": "burden", "name": "mutation burden", "value": f"{bur['rate']:.2f}/Mb",
                    "detail": bur["text"], "evidence": f"{OBSERVED} (count); {DERIVED} (rate)",
                    "key": ""})
    for a in afs:
        ef = effect_text(effect(a["variant"], effects))
        out.append({"kind": "variant", "name": a["variant"], "value": a["class"],
                    "detail": (f"allele fraction {a['vaf']:.1%}" if a["vaf"] is not None else
                               "allele fraction unknown") + f"; {a['fit']}; predicted: "
                    f"{ef['prediction'] or 'none'}; ClinVar: {ef['interpretation'] or 'none'}",
                    "evidence": f"{OBSERVED} (reads); {INFERENCE} (fit, prediction)", "key": ""})
    for p in pathway_summary(nodes):
        out.append({"kind": "pathway", "name": p["pathway"],
                    "value": ", ".join(p["altered"]) or "no observed alteration",
                    "detail": "; ".join(s["cite"] for s in p["sources"]), "evidence": HYPOTHESIS,
                    "key": finding_key(file, "pathway", p["pathway"])})
    return out


def report_markdown(file, rows: list[dict], bur: dict, afs: list[dict], nodes: list[dict],
                    effects: dict | None, lon: dict, reviews: dict) -> str:
    """The genome sections of the workbench's Markdown report, every placeholder named."""
    out = ["## Copy-number landscape", ""]
    if rows:
        altered = [r for r in rows if r["call"] in ALTERED]
        out += [f"Ploidy estimate {rows[0]['ploidy']:g} (median gene copy number). "
                f"{len(altered)} of {len(rows)} measured genes altered.", "",
                "| Gene | Chr | Copies | Call | Cohort percentile |", "|---|---|---|---|---|"]
        out += [f"| {r['gene']} | {r['chrom']} | {r['copies']:g} | {r['call_text']} | "
                f"{'' if r['pct'] is None else round(r['pct'])} |" for r in altered
                if r["copies"] is not None]
        out += ["", "Cutoffs: " + "; ".join(f"{c['name']} = {c['rule']} [{c['tag']}]"
                                            for c in CUTOFFS), ""]
    else:
        out += ["No copy number for this file.", ""]
    out += ["## Mutation burden", "", (bur["text"] + ".") if bur.get("measured") else bur["note"],
            "", "## Observed drivers: allele fraction and effect", ""]
    for a in afs:
        ef = effect_text(effect(a["variant"], effects))
        vaf = "unknown" if a["vaf"] is None else f"{a['vaf']:.1%}"
        out.append(f"- {a['variant']} ({a['class']}): allele fraction {vaf}"
                   + (f" (95% {a['lo']:.1%}-{a['hi']:.1%}, {a['alt']}/{a['depth']} reads)"
                      if a["lo"] is not None else "") + f"; {a['fit']} [model inference]; "
                   f"annotation: {ef['annotation']}; ClinVar: {ef['interpretation'] or 'none'} "
                   f"[interpretation]; AlphaMissense: {ef['prediction'] or 'none'} [model "
                   "inference, not approved for clinical use]")
    if not afs:
        out.append("- none")
    out += ["", "## Pathway map (hypothesis)", ""]
    for p in pathway_summary(nodes):
        out.append(f"- {p['pathway']}: {', '.join(p['altered']) or 'no observed alteration'} · "
                   + "; ".join(f"{s['cite']} (PMID {s['pmid']})" for s in p["sources"]))
    out += ["", "## Variants over time", "",
            "| Variant | " + " | ".join(s["id"] for s in lon["samples"]) + " |",
            "|---|" + "---|" * len(lon["samples"])]
    out += [f"| {r['variant']} | " + " | ".join(c["text"] for c in r["cells"]) + " |"
            for r in lon["rows"]]
    out += ["", f"Rule: {lon['rule']}.", *(f"- {n}" for n in lon["notes"]), ""]
    mine = {k: r for k, r in reviews.items() if k.startswith(file.id + "|")
            and k.split("|")[1] in ("cn", "pathway")}
    out += ["## Review marks on the genome views", ""]
    out += [f"- {r['what']}: {r['mark']} ({r['by'] or 'no initials'}, {r['at']})"
            for r in mine.values()] or ["- none"]
    return "\n".join(out) + "\n"


def landscape_csv(rows: list[dict], reviews: dict, file) -> str:
    from muffle.workspace import finding_key
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["gene", "chrom", "start_mb", "copies", "ploidy", "call", "cohort_percentile",
                "cohort_share_same_call", "model_layer", "pathways", "mark"])
    for r in rows:
        m = reviews.get(finding_key(file, "cn", r["gene"]))
        w.writerow([r["gene"], r["chrom"], r["start_mb"], r["copies"], r["ploidy"], r["call_text"],
                    r["pct"], r["share"], r["in_layer"], ";".join(r["pathways"]),
                    "" if not m else f"{m['mark']} ({m['by']}, {m['at']})"])
    return buf.getvalue()


def report_json(file, findings_: list[dict], reviews: dict, provenance: dict) -> str:
    marks = {k: r for k, r in reviews.items() if k.startswith(file.id + "|")}
    return json.dumps({"file": file.id, "provenance": provenance, "findings": findings_,
                       "review_marks": marks}, indent=2)

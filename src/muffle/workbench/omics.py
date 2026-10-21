"""Expression, methylation and protein workbench (docs/WORKBENCHES.md §7): pure functions.

Two halves, both plain arithmetic:

* Offline, on the local TCGA-BRCA files (``scripts/omics_scores.py``): the PAM50 nearest-centroid
  call, cohort z-scored gene-set scores, cutoffs calibrated against recorded IHC, and agreement
  with published calls. The script ships only derived numbers (``app/omics_scores.json``).
* In the app (``app/workbenches/omics.py``): a feature's cohort percentile from the shipped
  quantiles, the receptor consistency lines, the layer cards, search and the exports.

Every finding keeps its evidence type: an IHC status or a measured value is observed; a subtype
call, a pathway score or a layer's contribution is a model inference; nothing here is a
hypothesis. Thresholds name their source (guideline, calibrated, placeholder).
"""

from __future__ import annotations

import csv
import io
import json
from functools import lru_cache
from pathlib import Path

import numpy as np
import pandas as pd

from muffle.data.preprocess import zscore
from muffle.demo import ordinal
from muffle.report.case_tools import INFERENCE, OBSERVED
from muffle.workspace import ASSAYS, card, finding_key, look

IMPLEMENTED, VALIDATED, PLANNED = "implemented", "experimentally validated", "planned"
AGREE, DISAGREE, NO_COMPARISON = "agree", "disagree", "nothing to compare"

SUBTYPES = {"LumA": "Luminal A", "LumB": "Luminal B", "Her2": "HER2-enriched",
            "Basal": "Basal-like", "Normal": "Normal-like"}
# genefu's centroid table uses the symbols of 2009; GENCODE v36 names these genes differently
PAM50_ALIASES = {"CDCA1": "NUF2", "KNTC2": "NDC80", "ORC6L": "ORC6"}
# Parker et al. 2009: the proliferation score is the mean expression of these 11 PAM50 genes
PROLIFERATION = ("BIRC5", "CCNB1", "CDC20", "NUF2", "CEP55", "NDC80", "MKI67", "PTTG1", "RRM2",
                 "TYMS", "UBE2C")
CYTOLYTIC = ("GZMA", "PRF1")  # Rooney et al. 2015: immune cytolytic activity
# receptor -> (gene, RPPA antibody in the TCGA protein file)
RECEPTORS = {"ER": ("ESR1", "ERALPHA"), "PR": ("PGR", "PR"), "HER2": ("ERBB2", "HER2")}
ANTIBODY_NAMES = {"ERALPHA": "ER-alpha", "PR": "PR", "HER2": "HER2"}

REFERENCES = {
    "pam50": "Parker JS et al. Supervised risk predictor of breast cancer based on intrinsic "
             "subtypes. J Clin Oncol 2009;27:1160-7. doi:10.1200/JCO.2008.18.1370",
    "genefu": "Gendoo DMA et al. Genefu: an R/Bioconductor package for computation of gene "
              "expression-based signatures in breast cancer. Bioinformatics 2016;32:1097-9. "
              "doi:10.1093/bioinformatics/btv693 (centroids: genefu data/pam50.rda, Artistic-2.0)",
    "hallmark": "Liberzon A et al. The Molecular Signatures Database Hallmark gene set "
                "collection. Cell Syst 2015;1:417-25. doi:10.1016/j.cels.2015.12.004 (MSigDB "
                "v2025.1.Hs, CC BY 4.0)",
    "zscore": "Lee E et al. Inferring pathway activity toward precise disease classification. "
              "PLoS Comput Biol 2008;4:e1000217. doi:10.1371/journal.pcbi.1000217 (z-score "
              "averaging)",
    "cytolytic": "Rooney MS et al. Molecular and genetic properties of tumors associated with "
                 "local immune cytolytic activity. Cell 2015;160:48-61. "
                 "doi:10.1016/j.cell.2014.12.033",
    "published": "TCGA PanCanAtlas clinical data in cBioPortal (study brca_tcga_pan_can_atlas_2018,"
                 " column SUBTYPE; Hoadley KA et al. Cell 2018;173:291-304, "
                 "doi:10.1016/j.cell.2018.03.022)",
    "ihc": "TCGA clinical data (GDAC Firehose 2016-01-28) in cBioPortal (study brca_tcga): "
           "ER_STATUS_BY_IHC, PR_STATUS_BY_IHC, IHC_HER2, HER2_FISH_STATUS",
    "her2": "ASCO/CAP HER2 testing guideline (Wolff AC et al. J Clin Oncol 2018;36:2105-22, "
            "doi:10.1200/JCO.2018.77.8738): IHC 3+ positive, 0 or 1+ negative, 2+ equivocal and "
            "settled by in situ hybridization",
}

# One card per data layer: how the model input was made (scripts/prepare_tcga.py), its own
# validation (app/results_tcga_brca.json, single-layer rows), what to check and what it can't see.
LAYERS = {
    "clinical": {
        "name": "Clinical record", "result": "only_clinical",
        "normalization": "age, stage, T and N median-imputed and z-scored over the cohort; M1, "
                         "ductal, lobular and 'stage unknown' as 0/1 flags",
        "check": "the pathology report for stage, T and N; a missing stage was imputed",
        "cannot": "the tumor's biology (the omic layers), receptors (IHC), mutations "
                  "(genomics workbench)",
        "failure": "",
    },
    "genomic": {
        "name": "Copy number", "result": "only_genomic",
        "normalization": "ASCAT3 absolute gene-level copy number turned into calls relative to "
                         "the tumor's ploidy (its median gene copy number): −2 deep deletion, −1 "
                         "loss, 0 neutral, +1 gain, +2 amplification (at least twice the ploidy); "
                         "the 200 most variable genes",
        "check": "tumor purity and the ploidy estimate; an arm-level gain versus a focal "
                 "amplification",
        "cannot": "whether a gained gene is expressed (RNA layer) or made into protein (protein "
                  "layer); point mutations (genomics workbench)",
        "failure": "Known failure: on its own this layer ranks patients worse than chance on "
                   "hospitals it never saw, a sign of site and batch effects. Its contribution to "
                   "this patient's risk is shown, but read it with that in mind.",
    },
    "rna": {
        "name": "RNA expression", "result": "only_rna",
        "normalization": "STAR TPM, log(1 + TPM), z-scored per gene over the TCGA-BRCA primary "
                         "tumors; the 1,000 most variable genes",
        "check": "tumor content of the bulk sample: stroma, immune cells and normal breast dilute "
                 "or add expression",
        "cannot": "protein level (protein layer, IHC); where in the tumor a gene is expressed "
                  "(slides)",
        "failure": "",
    },
    "methylation": {
        "name": "DNA methylation", "result": "only_methylation",
        "normalization": "450K array beta values as M-values, log2(β / (1 − β)); the 500 most "
                         "variable CpGs; a missing value is filled with the cohort mean",
        "check": "tumor purity; a CpG is linked to a gene by position only, which does not prove "
                 "the gene is silenced",
        "cannot": "the expression of the nearby gene (RNA layer)",
        "failure": "",
    },
    "protein": {
        "name": "Protein (RPPA)", "result": "only_protein",
        "normalization": "reverse-phase protein array (TCPA), log2 and median-centered by the "
                         "provider, z-scored per antibody over the cohort; the 100 most variable "
                         "antibodies",
        "check": "antibody validation status; RPPA measures a lysate of the whole sample, not "
                 "the tumor cells alone",
        "cannot": "where in the tissue the protein sits (IHC on a slide)",
        "failure": "",
    },
}
OMIC_LAYERS = ("genomic", "rna", "methylation", "protein")


# --- offline: scores on the cohort ---------------------------------------------------------

def centroid_call(x: pd.Series, centroids: pd.DataFrame) -> dict:
    """Nearest-centroid subtype (Parker et al. 2009): Spearman correlation of one tumor's
    median-centered log expression ``x`` (by gene) with each centroid (``centroids``: genes x
    subtypes). Genes ``x`` lacks are left out. Returns the call, every correlation, the margin
    from the best to the second best, and how many genes were used."""
    genes = centroids.index.intersection(x.dropna().index)
    cor = centroids.loc[genes].corrwith(x[genes], method="spearman").sort_values(ascending=False)
    return {"call": str(cor.index[0]), "cor": {str(k): round(float(v), 3) for k, v in cor.items()},
            "margin": round(float(cor.iloc[0] - cor.iloc[1]), 3), "genes": int(len(genes))}


def set_scores(z: pd.DataFrame, sets: dict[str, list[str]] | dict[str, tuple]) -> pd.DataFrame:
    """Per tumor and gene set: the mean of the set's measured gene-wise cohort z-scores (``z``:
    tumors x genes), z-scored again over the cohort, so 0 is the cohort average and 1 one standard
    deviation above it (z-score averaging, Lee et al. 2008, up to scale)."""
    return zscore(pd.DataFrame({name: z[z.columns.intersection(list(genes))].mean(axis=1)
                                for name, genes in sets.items()}))


def youden(values, positive) -> dict:
    """The cutoff on ``values`` that best separates recorded positives from negatives (highest
    sensitivity + specificity − 1), with the AUC: a threshold calibrated on this data."""
    v, pos = np.asarray(values, float), np.asarray(positive, bool)
    cuts = np.unique(v)
    sens = (v[pos][:, None] >= cuts).mean(0)
    spec = (v[~pos][:, None] < cuts).mean(0)
    k = int(np.argmax(sens + spec - 1))
    ranks = pd.Series(v).rank().to_numpy()
    n1, n0 = pos.sum(), (~pos).sum()
    auc = (ranks[pos].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)
    return {"cutoff": float(cuts[k]), "sensitivity": round(float(sens[k]), 3),
            "specificity": round(float(spec[k]), 3), "auc": round(float(auc), 3),
            "positives": int(n1), "negatives": int(n0)}


def agreement(pred, truth) -> dict:
    """Agreement of calls ``pred`` with reference calls ``truth`` (pairs with a missing side are
    dropped): share agreeing, Cohen's kappa and the confusion matrix {reference: {call: n}}."""
    t = pd.DataFrame({"pred": list(pred), "truth": list(truth)}).dropna()
    po = float((t["pred"] == t["truth"]).mean())
    p, r = t["pred"].value_counts(normalize=True), t["truth"].value_counts(normalize=True)
    pe = float((p * r.reindex(p.index).fillna(0)).sum())
    conf = pd.crosstab(t["truth"], t["pred"])
    return {"n": len(t), "agree": int((t["pred"] == t["truth"]).sum()),
            "share": round(po, 3), "kappa": round((po - pe) / (1 - pe), 3),
            "confusion": {str(a): {str(b): int(n) for b, n in row.items()}
                          for a, row in conf.iterrows()}}


def her2_status(ihc: str | None, fish: str | None) -> str | None:
    """Clinical HER2 status per ASCO/CAP: IHC positive (3+) or negative (0, 1+) stands; IHC
    equivocal (2+) is settled by in situ hybridization; anything else is unknown (None)."""
    if ihc in ("Positive", "Negative"):
        return ihc
    if ihc == "Equivocal" and fish in ("Positive", "Negative"):
        return fish
    return None


# --- in the app ----------------------------------------------------------------------------

def percentile(value: float, quantiles: list[float]) -> float:
    """A value's cohort percentile from the cohort's quantiles at 0, 5, ..., 100 % (linear
    interpolation; outside the range, 0 or 100)."""
    q = np.asarray(quantiles, float)
    return float(np.interp(value, q, np.linspace(0, 100, len(q))))


def _pos(status: str | None) -> bool | None:
    return {"Positive": True, "Negative": False}.get(status)


def receptor_lines(receptors: dict, calibration: dict) -> list[dict]:
    """One line per comparison, each with its status and evidence: recorded IHC (observed) against
    the gene's RNA level, ERBB2 copy number against HER2, RPPA protein against RNA. ``receptors``
    is one case's block of ``omics_scores.json``; ``calibration`` the cutoffs calibrated on the
    cohort ("validation" → "receptors")."""
    out = []
    for name, r in receptors.items():
        gene, antibody = RECEPTORS[name]
        ihc = r.get("status")
        recorded = (f"{name} IHC {r['ihc'].lower()}" if r.get("ihc") else f"{name} IHC not "
                    "recorded")
        if name == "HER2" and r.get("ihc") == "Equivocal":
            recorded += f", in situ hybridization {(r.get('fish') or 'not recorded').lower()}"
        cal = calibration.get(name, {})
        rna, prot, cn = r.get("rna"), r.get("protein"), r.get("cn")
        if rna is not None:
            side = "above" if rna["high"] else "below"
            text = (f"{recorded}; {gene} RNA at the {ordinal(rna['pct'])} percentile, {side} the "
                    "cutoff that best separates recorded-positive from recorded-negative tumors "
                    f"in this cohort ({ordinal(cal['rna']['cutoff_pct'])} percentile)")
            short = (f"{recorded}, {gene} RNA {'high' if rna['high'] else 'low'} "
                     f"({ordinal(rna['pct'])} percentile)")
            out.append(_line(name, "IHC vs RNA", text, short, _pos(ihc), rna["high"],
                             "the specimen and its tumor content; RNA is not protein",
                             f"{OBSERVED} (IHC, RNA); cutoff calibrated on this cohort's IHC "
                             f"(AUC {cal['rna']['auc']:.2f}, in-sample)"))
        if cn is not None:
            amp = cn["copies"] >= 2 * cn["ploidy"]
            text = (f"{recorded}; ERBB2 copy number {cn['copies']:g} at a tumor ploidy of "
                    f"{cn['ploidy']:g}: {'amplified' if amp else 'not amplified'}")
            short = (f"{recorded}, ERBB2 {'amplified' if amp else 'not amplified'} "
                     f"({cn['copies']:g} copies at ploidy {cn['ploidy']:g})")
            out.append(_line(name, "IHC vs copy number", text, short, _pos(ihc), amp,
                             "tumor purity and the ploidy estimate; in situ hybridization is the "
                             "clinical test for amplification",
                             f"{OBSERVED} (IHC, copy number); amplification = at least twice the "
                             "ploidy (placeholder, by analogy with the ASCO/CAP ISH ratio of 2.0; "
                             "not validated on ASCAT calls)"))
        if prot is not None:
            pname = ANTIBODY_NAMES[antibody]
            side = "above" if prot["high"] else "below"
            vs, other = ("RNA", rna["high"]) if rna is not None else ("IHC", _pos(ihc))
            text = (f"{pname} protein (RPPA) at the {ordinal(prot['pct'])} percentile, {side} its "
                    f"IHC-calibrated cutoff ({ordinal(cal['protein']['cutoff_pct'])} percentile)"
                    + (f"; {gene} RNA {'above' if rna['high'] else 'below'} its cutoff"
                       if rna is not None else "") + f"; {recorded}")
            short = (f"{pname} protein {'high' if prot['high'] else 'low'} "
                     f"({ordinal(prot['pct'])} percentile), {gene} RNA "
                     f"{'high' if rna['high'] else 'low'}" if rna is not None else
                     f"{recorded}, {pname} protein {'high' if prot['high'] else 'low'}")
            out.append(_line(name, f"protein vs {vs}", text, short, other, prot["high"],
                             "RNA is not protein: RPPA measures the whole sample's lysate, IHC "
                             "the tumor cells",
                             f"{OBSERVED} (RPPA, {vs}); cutoff calibrated on this cohort's IHC "
                             f"(AUC {cal['protein']['auc']:.2f}, in-sample)"))
    return out


def _line(receptor, compare, text, short, reference, measured, check, evidence) -> dict:
    status = NO_COMPARISON if reference is None else AGREE if reference == measured else DISAGREE
    tail = {AGREE: "agree", DISAGREE: "disagree, worth a second look",
            NO_COMPARISON: "nothing recorded to compare with"}[status]
    return {"receptor": receptor, "compare": compare, "text": f"{text}. {compare}: {tail}.",
            "short": short, "status": status, "check": check, "evidence": evidence}


def look_here(case: dict | None, lines: list[dict], measured: list[str]) -> list[str]:
    """What to check by eye, in order: receptor disagreements, a subtype call that differs from
    the published one or barely beats the runner-up, and the copy-number layer's known failure."""
    out = [f"{x['receptor']}, {x['compare']} disagree: {x['short']}" for x in lines
           if x["status"] == DISAGREE]
    sub = (case or {}).get("pam50")
    if sub and sub.get("published") and not sub["agrees"]:
        out.append(f"PAM50 call {SUBTYPES[sub['call']]} differs from TCGA's published call "
                   f"{SUBTYPES[sub['published']]}")
    if sub and sub["margin"] < LOW_MARGIN:
        out.append(f"PAM50 call {SUBTYPES[sub['call']]} beats the runner-up by only "
                   f"{sub['margin']:.2f} in correlation: a borderline call")
    if "genomic" in measured:
        out.append("Copy number: a known failure across hospitals (see its layer card)")
    return out


LOW_MARGIN = 0.1  # PLACEHOLDER: a centroid correlation margin under which a call is borderline


def search(query: str, items: list[dict]) -> dict:
    """Items (each {"kind", "name", "text"}) matching ``query`` in plain words: a gene or feature
    name, a pathway word ("proliferation"), or a status ("disagree"). An unanswerable query gets
    an honest answer naming the test that could answer it."""
    q = (query or "").strip().lower()
    if not q:
        return {"hits": items, "note": None}
    hits = [i for i in items if q in i["name"].lower() or q in i["text"].lower()]
    note = None if hits else (
        f"\"{query}\" is not in these layers. Mutations: the genomics workbench; tissue and "
        "cells: the slide workbench; blood markers: the lab workbench; a gene outside the "
        "model's 1,000 most variable genes is not read here.")
    return {"hits": hits, "note": note}


def report_json(file_id: str, findings: list[dict], reviews: dict, provenance: dict) -> str:
    """The workbench's findings, the reviewers' marks on this file and the provenance, as JSON."""
    marks = {k: r for k, r in reviews.items() if k.startswith(file_id + "|") and "|omics|" in k}
    return json.dumps({"file": file_id, "provenance": provenance, "findings": findings,
                       "review_marks": marks}, indent=2)


def report_csv(findings: list[dict], reviews: dict) -> str:
    """One row per finding with its mark (if any)."""
    out = io.StringIO()
    cols = ["kind", "layer", "name", "value", "percentile", "evidence", "status", "key"]
    w = csv.DictWriter(out, [*cols, "mark", "by", "at"], extrasaction="ignore")
    w.writeheader()
    for f in findings:
        r = reviews.get(f.get("key"), {})
        w.writerow({**f, "mark": r.get("mark", ""), "by": r.get("by", ""), "at": r.get("at", "")})
    return out.getvalue()


# --- the workbench contract (docs/WORKBENCHES.md §1): the patient file's overview ----------------

SCORES = Path(__file__).resolve().parents[3] / "app" / "omics_scores.json"


@lru_cache(maxsize=2)
def scores(path: Path = SCORES) -> dict:
    """``app/omics_scores.json`` (scripts/omics_scores.py), read once; {} when absent."""
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def case_scores(pf) -> dict | None:
    """A TCGA file's precomputed block of ``omics_scores.json``, or None: not a TCGA file, not
    computed, or computed for another build of the cohort (its log-risk differs, the page's
    guard)."""
    if pf.kind != "TCGA-BRCA":
        return None
    cs = scores().get("cases", {}).get(pf.id.removeprefix("Case "))
    log_risk = (pf.versions[0].risk or {}).get("log_risk")
    if cs is None or log_risk is None or abs(cs["log_risk"] - log_risk) > 1e-3:
        return None
    return cs


def file_lines(pf) -> list[dict]:
    """``receptor_lines`` of a TCGA file with the cohort's calibration ([] without scores)."""
    cs = case_scores(pf)
    return [] if cs is None else receptor_lines(
        cs["receptors"], scores().get("validation", {}).get("receptors", {}))


def _opens(pf) -> tuple:
    """The omics workbench opens from the RNA layer's test, else any data-layer test."""
    tests = [t for t in pf.tests if t.workbench in ("omics", "record")]
    t = next((t for t in tests if t.details.get("layer") == "rna"), tests[0] if tests else None)
    return () if t is None else ("Tests", t.kind, t.month, t.name)


def published(sub: dict) -> str:
    if sub.get("published") is None:
        return "no published call"
    return ("agrees with TCGA's published call" if sub["agrees"] else
            f"differs from TCGA's published call ({SUBTYPES[sub['published']]})")


def recorded_text(receptors: dict) -> str:
    """"ER positive, PR positive, HER2 negative (IHC equivocal, ISH negative)": the recorded
    status, per ASCO/CAP for HER2 (``status``), with the IHC and ISH it rests on."""
    out = []
    for name, r in receptors.items():
        status = (r.get("status") or "not recorded").lower()
        if name == "HER2" and r.get("ihc") == "Equivocal":
            status += f" (IHC equivocal, ISH {(r.get('fish') or 'not recorded').lower()})"
        out.append(f"{name} {status}")
    return ", ".join(out)


def summary(pf, version: int | None = None) -> dict:
    """The PAM50 call with its margin, the recorded receptor status, how RNA, copy number and
    protein agree with it, and the proliferation and immune scores."""
    cs = case_scores(pf)
    if cs is None:
        return {"workbench": "omics", "title": "Expression, methylation, protein", "cards": [],
                "note": "no expression, methylation or protein scores in this file"}
    data, sub, opens = scores(), cs["pam50"], _opens(pf)
    runner = sorted(sub["cor"], key=lambda k: -sub["cor"][k])[1]
    focus = {"omics": finding_key(pf, "omics", "subtype", "PAM50")}
    trust = ("weak" if sub["margin"] < LOW_MARGIN else
             "moderate" if sub.get("published") and not sub["agrees"] else "strong")
    val = data.get("validation", {}).get("pam50", {})
    cards = [card(
        "PAM50 subtype", f"{SUBTYPES[sub['call']]}, margin {sub['margin']:.2f} over "
        f"{SUBTYPES[runner]}; {published(sub)}", INFERENCE, ASSAYS["rna"],
        f"PAM50 nearest centroid (Parker 2009, genefu), ER-balanced centering; "
        f"{data.get('version', '?')}; agrees with TCGA's published calls for "
        f"{val.get('share', 0):.1%} of {val.get('n', '?')} tumors",
        f"a margin under {LOW_MARGIN} is called borderline (placeholder)", trust, opens, focus)]
    lines = file_lines(pf)
    compared = [x for x in lines if x["status"] != NO_COMPARISON]
    off = [x for x in compared if x["status"] == DISAGREE]
    first = (off or compared or lines or [None])[0]
    receptor = None if first is None else {"omics": finding_key(
        pf, "omics", "receptor", f"{first['receptor']}: {first['compare']}")}
    cards.append(card(
        "Recorded receptors", recorded_text(cs["receptors"]), OBSERVED,
        "TCGA clinical data (IHC; ISH for HER2)", REFERENCES["ihc"],
        "the recording laboratory's; HER2 per ASCO/CAP (IHC 3+, or 2+ with ISH)", "strong",
        opens, receptor))
    if compared:
        cards.append(card(
            "Receptors in RNA and protein", f"{len(compared) - len(off)} of {len(compared)} "
            "comparisons agree with the recorded status" + (
                "; disagree: " + "; ".join(x["short"] for x in off) if off else ""),
            f"{OBSERVED} (IHC, RNA, copy number, protein)", "RNA, copy number and RPPA layers",
            "receptor consistency (omics workbench)", "cutoffs calibrated in-sample on this "
            "cohort's IHC (Youden); ERBB2 amplified at twice the ploidy (placeholder)",
            "moderate", opens, receptor))
    prolif, immune = cs["scores"]["proliferation"], cs["scores"]["immune"]
    cards.append(card(
        "Proliferation and immune", f"proliferation at the {ordinal(prolif[1])} percentile, "
        f"immune cytolytic activity at the {ordinal(immune[1])} (this cohort)", INFERENCE,
        ASSAYS["rna"], "cohort z-scores of the PAM50 proliferation genes and of GZMA and PRF1 "
        "(Rooney 2015)", "none: relative to this cohort", "moderate", opens,
        {"omics": finding_key(pf, "omics", "score", "immune")}))
    return {"workbench": "omics", "title": "Expression, methylation, protein", "cards": cards,
            "note": None}


def queue(pf, version: int | None = None) -> list[dict]:
    """Receptor comparisons that disagree with the recorded status (consequence 2 for ER and
    HER2, which decide endocrine and anti-HER2 eligibility; 1 for PR), a subtype call that differs
    from the published one or barely beats the runner-up. The copy-number layer's known failure
    is a standing caveat of the page, not a finding about this patient."""
    cs = case_scores(pf)
    if cs is None:
        return []
    opens, out = _opens(pf), []
    for x in file_lines(pf):
        if x["status"] != DISAGREE:
            continue
        name = f"{x['receptor']}: {x['compare']}"
        out.append(look(
            name, f"{x['receptor']}, {x['compare']}: disagree", f"{x['short']}; check: "
            f"{x['check']}", x["evidence"], "weak" if "copy number" in x["compare"] else
            "moderate", 2 if x["receptor"] in ("ER", "HER2") else 1, opens,
            source=f"{ASSAYS['rna']} and the recorded {x['receptor']} status",
            key=finding_key(pf, "omics", "receptor", name),
            focus={"omics": finding_key(pf, "omics", "receptor", name)},
            threshold=x["evidence"].split("; ", 1)[-1]))
    sub = cs["pam50"]
    pam50 = {"omics": finding_key(pf, "omics", "subtype", "PAM50")}
    if sub.get("published") and not sub["agrees"]:
        out.append(look(
            "PAM50", f"PAM50 {SUBTYPES[sub['call']]} {published(sub)}", "the same method agrees "
            "with the published calls for most tumors of this cohort; a differing call is worth "
            "a look at its correlations", INFERENCE, "moderate", 1, opens, source=ASSAYS["rna"],
            key=finding_key(pf, "omics", "subtype", "PAM50"), focus=pam50,
            threshold="nearest centroid, experimentally validated on this cohort"))
    elif sub["margin"] < LOW_MARGIN:
        out.append(look(
            "PAM50", f"PAM50 {SUBTYPES[sub['call']]} is borderline (margin {sub['margin']:.2f})",
            f"the call beats the runner-up by under {LOW_MARGIN} in correlation", INFERENCE,
            "weak", 1, opens, source=ASSAYS["rna"],
            key=finding_key(pf, "omics", "subtype", "PAM50"), focus=pam50,
            threshold=f"margin {LOW_MARGIN} (placeholder)"))
    return out

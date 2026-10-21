"""Expression, methylation and protein scores for the bundled TCGA-BRCA cases (omics_scores.json).

Runs offline on the local TCGA-BRCA files (scripts/prepare_tcga.py's --raw folder and its
cohort.npz) and ships only derived numbers: subtype calls with their correlations, set scores and
percentiles, receptor calls, per-feature cohort quantiles and validation summaries. Never an
expression, methylation or protein vector of a patient.

* PAM50 (Parker et al. 2009, J Clin Oncol, doi:10.1200/JCO.2008.18.1370), centroids from genefu
  (data/pam50.rda, Artistic-2.0). Normalization: the hub's log2(TPM + 1), each gene centered on
  its median over an ER-balanced subset of this cohort (every ER-negative tumor by IHC and as
  many ER-positive ones, drawn with seed 0; Zhao et al. 2015, Breast Cancer Res,
  doi:10.1186/s13058-015-0520-4), so the reference population is this TCGA-BRCA cohort, not
  Parker's; Spearman correlation with each centroid; the highest wins. Validated against TCGA's
  published calls (cBioPortal brca_tcga_pan_can_atlas_2018, SUBTYPE), with plain cohort-median
  centering and seeds 1-4 reported alongside.
* Hallmark gene sets (MSigDB v2025.1.Hs, Liberzon et al. 2015, CC BY 4.0), the 11 PAM50
  proliferation genes and immune cytolytic activity (GZMA, PRF1; Rooney et al. 2015): each gene
  z-scored over the cohort, the set's mean z-score z-scored again over the cohort.
* Receptors: ESR1, PGR and ERBB2 RNA and the RPPA antibodies ERALPHA, PR and HER2 against the
  recorded IHC (TCGA clinical data, cBioPortal brca_tcga; HER2 status per ASCO/CAP), each with the
  cutoff that best separates recorded positives from negatives in this cohort (Youden, in-sample);
  ERBB2 copy number (ASCAT3) against the tumor's ploidy.

The extra public files (genefu, MSigDB, cBioPortal, the 450K probe map) are downloaded once into
--extra. Reading genefu's .rda needs the ``rdata`` package (pip install rdata), nothing else.

python scripts/omics_scores.py --data data/tcga_brca --raw data/raw/tcga_brca \
    --extra data/raw/omics --bundle outputs/demo_bundle.pt --out app/omics_scores.json
"""

from __future__ import annotations

import argparse
import json
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from muffle.data.tcga import primary_samples, read_header, read_matrix
from muffle.demo import load_bundle
from muffle.explain import risk_percentile as rank_percentile  # (cohort < x).mean() * 100
from muffle.workbench import omics

GENEFU = ("https://raw.githubusercontent.com/bhklab/genefu/"
          "9c9b66d1ef22cbfda1df75b626d2dbc68fb9b25c/data/pam50.rda")
HALLMARK = ("https://data.broadinstitute.org/gsea-msigdb/msigdb/release/2025.1.Hs/"
            "h.all.v2025.1.Hs.symbols.gmt")
PROBEMAP = "https://gdc-hub.s3.us-east-1.amazonaws.com/download/HM450.hg38.manifest.gencode.v36.probeMap"
CBIOPORTAL = ("https://www.cbioportal.org/api/studies/{study}/clinical-data"
              "?clinicalDataType=PATIENT&projection=SUMMARY&pageSize=10000000")
QUANTILES = np.linspace(0, 1, 11)  # cohort deciles: enough for "about the Nth percentile"


def fetch(url: str, path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, path.with_name(path.name + ".part"))
        path.with_name(path.name + ".part").rename(path)
    return path


def patient_table(extra: Path, study: str, columns: list[str]) -> pd.DataFrame:
    rows = json.loads(fetch(CBIOPORTAL.format(study=study), extra / f"{study}.json").read_text())
    t = pd.DataFrame(rows)
    t = t[t["clinicalAttributeId"].isin(columns)]
    return t.pivot(index="patientId", columns="clinicalAttributeId", values="value")


def centroids(extra: Path) -> pd.DataFrame:
    import rdata  # only this script needs it

    pam50 = rdata.read_rda(fetch(GENEFU, extra / "pam50.rda"))["pam50"]["centroids"]
    c = pd.DataFrame(pam50.values, index=[str(g) for g in pam50.coords["dim_0"].values],
                     columns=[str(s) for s in pam50.coords["dim_1"].values])
    return c.rename(index=omics.PAM50_ALIASES)


def hallmark(extra: Path) -> dict[str, list[str]]:
    lines = fetch(HALLMARK, extra / Path(HALLMARK).name).read_text().splitlines()
    return {f.split("\t")[0]: f.split("\t")[2:] for f in lines if f}


def expression(raw: Path, patients: list[str], genes: set[str]) -> pd.DataFrame:
    """log2(TPM + 1) of ``genes`` (symbols) for ``patients``' primary tumors; a symbol with
    several Ensembl IDs keeps the most expressed one."""
    probes = pd.read_csv(raw / "gencode.v36.annotation.gtf.gene.probemap", sep="\t")
    probes = probes[probes["gene"].isin(genes)]
    source = raw / "TCGA-BRCA.star_tpm.tsv.gz"
    samples = {s: p for s, p in primary_samples(read_header(source)[1:]).items()
               if p in set(patients)}
    x = pd.concat([b[b.columns.intersection(probes["id"])] for b in read_matrix(source, samples)],
                  axis=1)
    x.columns = probes.set_index("id").loc[x.columns, "gene"]
    best = x.T.assign(mean=x.mean().to_numpy()).sort_values("mean", ascending=False)
    x = best[~best.index.duplicated()].drop(columns="mean").T
    return x.reindex([p for p in patients if p in x.index])


def protein(raw: Path, patients: list[str]) -> pd.DataFrame:
    source = raw / "TCGA-BRCA.protein.tsv.gz"
    samples = {s: p for s, p in primary_samples(read_header(source)[1:]).items()
               if p in set(patients)}
    x = pd.concat(list(read_matrix(source, samples)), axis=1)
    return x[[a for _, a in omics.RECEPTORS.values()]]


def erbb2_copies(raw: Path, patients: list[str]) -> pd.DataFrame:
    """ERBB2 absolute copy number and the tumor's ploidy (median gene copy number, rounded, at
    least 1: the rule of muffle.data.tcga.copy_number_calls)."""
    source = raw / "TCGA-BRCA.gene-level_ascat3.tsv.gz"
    samples = {s: p for s, p in primary_samples(read_header(source)[1:]).items()
               if p in set(patients)}
    cn = pd.concat(list(read_matrix(source, samples)), axis=1)
    erbb2 = "ENSG00000141736"
    col = next(c for c in cn.columns if c.split(".")[0] == erbb2)
    ploidy = np.clip(np.round(np.nanmedian(cn.to_numpy(np.float32), axis=1)), 1, None)
    return pd.DataFrame({"copies": cn[col], "ploidy": ploidy}, index=cn.index)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=Path("data/tcga_brca"))
    p.add_argument("--raw", type=Path, default=Path("data/raw/tcga_brca"))
    p.add_argument("--extra", type=Path, default=Path("data/raw/omics"))
    p.add_argument("--bundle", default="outputs/demo_bundle.pt")
    p.add_argument("--out", type=Path, default=Path("app/omics_scores.json"))
    args = p.parse_args()
    log = lambda *a: print(*a, flush=True)  # noqa: E731

    cohort = np.load(args.data / "cohort.npz")
    patients = [str(x) for x in cohort["patient"]]
    cases = {c.index: c for c in load_bundle(args.bundle).cases}
    log(f"{len(patients)} cohort patients, {len(cases)} bundled cases")

    cent, sets = centroids(args.extra), hallmark(args.extra)
    prolif = omics.PROLIFERATION
    genes = (set(cent.index) | set(prolif) | set(omics.CYTOLYTIC)
             | {g for g, _ in omics.RECEPTORS.values()} | {g for s in sets.values() for g in s})
    x = expression(args.raw, patients, genes)
    log(f"RNA: {x.shape[0]} tumors x {x.shape[1]} genes "
        f"({len(cent.index.intersection(x.columns))}/50 PAM50 genes)")

    # recorded receptor status (IHC; HER2 per ASCO/CAP)
    ihc = patient_table(args.extra, "brca_tcga", ["ER_STATUS_BY_IHC", "PR_STATUS_BY_IHC",
                                                  "IHC_HER2", "HER2_FISH_STATUS"])
    status = pd.DataFrame({
        "ER": ihc["ER_STATUS_BY_IHC"], "PR": ihc["PR_STATUS_BY_IHC"],
        "HER2": [omics.her2_status(a, b) for a, b in zip(ihc["IHC_HER2"], ihc["HER2_FISH_STATUS"],
                                                         strict=True)]}, index=ihc.index)
    status = status.where(status.isin(["Positive", "Negative"]))
    # PAM50, against the published calls. Each gene is centered on its median over an
    # ER-balanced subset (every ER-negative tumor and as many ER-positive ones drawn at random):
    # TCGA-BRCA is about three quarters ER-positive, unlike PAM50's training set, and plain
    # cohort-median centering then shifts calls (Zhao et al. 2015). Reported alongside: plain
    # centering, and the balanced subset's other draws (seeds 1-4).
    pub = patient_table(args.extra, "brca_tcga_pan_can_atlas_2018", ["SUBTYPE"])["SUBTYPE"]
    pub = pub.str.replace("BRCA_", "", regex=False).reindex(x.index)
    er = status["ER"].reindex(x.index)
    neg, erpos = er.index[er == "Negative"], er.index[er == "Positive"].to_series()

    def pam50(reference: pd.Index) -> dict:
        centered = x - x.loc[reference].median()
        return {pt: omics.centroid_call(centered.loc[pt], cent) for pt in x.index}

    def balanced(seed: int) -> pd.Index:
        return neg.append(erpos.sample(len(neg), random_state=seed).index)

    calls = pam50(balanced(0))
    pam50_val = omics.agreement([calls[pt]["call"] for pt in x.index], pub)
    pam50_val["reference_tumors"] = 2 * len(neg)
    pam50_val["other_draws"] = [omics.agreement([c["call"] for c in pam50(balanced(k)).values()],
                                                pub)["share"] for k in range(1, 5)]
    plain = omics.agreement([c["call"] for c in pam50(x.index).values()], pub)
    pam50_val["plain_centering"] = {k: plain[k] for k in ("n", "agree", "share", "kappa")}
    log(f"PAM50 vs published: {pam50_val['share']:.1%} of {pam50_val['n']}, kappa "
        f"{pam50_val['kappa']}; other draws {pam50_val['other_draws']}; plain centering "
        f"{plain['share']:.1%}")

    # gene-set scores
    z = (x - x.mean()) / x.std(ddof=0).replace(0, 1)
    named = {**{k.removeprefix("HALLMARK_"): v for k, v in sets.items()},
             "proliferation": list(prolif), "immune": list(omics.CYTOLYTIC)}
    scores = omics.set_scores(z, named)

    # receptors: RNA and RPPA against recorded IHC; ERBB2 copy number
    prot, cn = protein(args.raw, patients), erbb2_copies(args.raw, patients)
    calibration, rppa_rna = {}, {}
    for name, (gene, antibody) in omics.RECEPTORS.items():
        calibration[name] = {}
        for kind, values in (("rna", x[gene]), ("protein", prot[antibody])):
            v = values.dropna()
            s = status[name].reindex(v.index).dropna()
            cut = omics.youden(v[s.index], s == "Positive")
            cut["cutoff_pct"] = rank_percentile(cut["cutoff"], v.to_numpy())
            cut["n"] = int(len(s))
            calibration[name][kind] = cut
        both = pd.concat([x[gene], prot[antibody]], axis=1).dropna()
        rppa_rna[name] = {"spearman": round(float(both.corr("spearman").iloc[0, 1]), 3),
                          "n": len(both)}
    s = status["HER2"].reindex(cn.index).dropna()
    amp = cn.loc[s.index, "copies"] >= 2 * cn.loc[s.index, "ploidy"]
    pos = s == "Positive"
    calibration["HER2"]["cn"] = {"n": int(len(s)),
                                 "sensitivity": round(float(amp[pos].mean()), 3),
                                 "specificity": round(float((~amp[~pos]).mean()), 3)}
    log("receptors:", json.dumps(calibration))

    def receptor_block(pt: str) -> dict:
        out = {}
        for name, (gene, antibody) in omics.RECEPTORS.items():
            r = {"status": None if pd.isna(status[name].get(pt)) else status[name][pt]}
            key = {"ER": "ER_STATUS_BY_IHC", "PR": "PR_STATUS_BY_IHC", "HER2": "IHC_HER2"}[name]
            r["ihc"] = None if pt not in ihc.index or pd.isna(ihc.at[pt, key]) else ihc.at[pt, key]
            if name == "HER2" and pt in ihc.index and not pd.isna(ihc.at[pt, "HER2_FISH_STATUS"]):
                r["fish"] = ihc.at[pt, "HER2_FISH_STATUS"]
            for kind, values in (("rna", x[gene]), ("protein", prot[antibody])):
                v = values.dropna()
                if pt in v.index:
                    r[kind] = {"pct": round(rank_percentile(v[pt], v.to_numpy()), 1),
                               "high": bool(v[pt] >= calibration[name][kind]["cutoff"])}
            if name == "HER2" and pt in cn.index and not cn.loc[pt].isna().any():
                r["cn"] = {"copies": float(cn.at[pt, "copies"]),
                           "ploidy": float(cn.at[pt, "ploidy"])}
            out[name] = r
        return out

    # per-feature cohort quantiles of the model inputs (an aggregate, never a patient's vector)
    names = {m: [str(n) for n in cohort[f"names_{m}"]] for m in omics.OMIC_LAYERS}
    mask = cohort["mask"]
    layer_col = {m: j for j, m in enumerate(["genomic", "rna", "methylation", "protein",
                                             "clinical"])}
    quant = {}
    for m in omics.OMIC_LAYERS:
        v = cohort[f"x_{m}"][mask[:, layer_col[m]] > 0]
        if m == "genomic":  # calls: the cohort's share of each call -2..2
            quant[m] = {n: [round(float((v[:, j] == c).mean()), 3) for c in range(-2, 3)]
                        for j, n in enumerate(names[m])}
        else:
            q = np.quantile(v, QUANTILES, axis=0)
            quant[m] = {n: [round(float(a), 2) for a in q[:, j]] for j, n in enumerate(names[m])}
    probemap = pd.read_csv(fetch(PROBEMAP, args.extra / Path(PROBEMAP).name), sep="\t",
                           index_col=0)
    cpg_genes = {c: str(probemap.at[c, "gene"]) for c in names["methylation"]
                 if c in probemap.index and isinstance(probemap.at[c, "gene"], str)
                 and probemap.at[c, "gene"] not in (".", "")}
    readable = set(names["rna"]) | set(names["genomic"]) | set(cent.index) | set(cpg_genes.values())
    readable |= {g for v in cpg_genes.values() for g in v.split(",")}
    members: dict[str, list[str]] = {}
    for k, v in sets.items():
        for g in set(v) & readable:
            members.setdefault(g, []).append(k.removeprefix("HALLMARK_"))

    out_cases = {}
    for i in sorted(cases):
        pt = patients[i]
        if pt not in x.index:
            continue
        call = calls[pt]
        published = None if pd.isna(pub.get(pt)) else pub[pt]
        out_cases[str(i)] = {
            # the bundle's log-risk for this case: the app shows these scores only when its
            # loaded case matches, so a rebuilt cohort never pairs them with another patient
            "log_risk": round(cases[i].log_risk, 4),
            "pam50": {**call, "published": published,
                      "agrees": None if published is None else call["call"] == published},
            "scores": {k: [round(float(scores.at[pt, k]), 2),
                           round(rank_percentile(scores.at[pt, k], scores[k].to_numpy()), 1)]
                       for k in scores.columns},
            "receptors": receptor_block(pt),
        }

    result = {
        "version": f"omics-scores 1 ({date.today().isoformat()})",
        "reference": {"cohort": "TCGA-BRCA primary tumors in the model's cohort (cohort.npz)",
                      "rna_tumors": int(x.shape[0]), "pam50_genes": int(len(
                          cent.index.intersection(x.columns))),
                      "published_calls": int(pub.notna().sum())},
        "references": omics.REFERENCES,
        "validation": {"pam50": pam50_val, "receptors": calibration, "rppa_vs_rna": rppa_rna},
        "sets": {k.removeprefix("HALLMARK_"): {"size": len(v),
                                               "measured": int(len(x.columns.intersection(v)))}
                 for k, v in sets.items()},
        "members": {g: sorted(v) for g, v in sorted(members.items())},
        "cpg_genes": cpg_genes,
        "quantiles": quant,
        "cases": out_cases,
    }
    args.out.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    log(f"-> {args.out} ({args.out.stat().st_size / 1e3:.0f} kB, {len(out_cases)} cases)")


if __name__ == "__main__":
    main()

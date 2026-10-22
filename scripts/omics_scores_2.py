"""Round 2 of the omics scores: protein pathways, promoter methylation, immune and stromal scores.

Adds fields to app/omics_scores.json (scripts/omics_scores.py writes round 1; its fields and the
per-case log-risk guard stay as they are). Runs offline on the local TCGA-BRCA files and ships
only derived numbers: scores, percentiles, a gene-level promoter beta, cohort quantiles and
correlations. Never an expression, methylation or protein vector of a patient.

* RPPA pathway scores, Akbani et al. 2014 (Nat Commun 5:3887, Supplementary Table 13): each
  antibody median-centered and divided by its standard deviation over the cohort, the members'
  signed mean (a negative regulator subtracted), z-scored again over the cohort. Members measured
  in under half of the cohort's RPPA tumors are left out and listed. Protein against RNA: the
  Spearman correlation of each antibody with its gene's log2(TPM + 1) over the cohort.
* Promoter methylation: the core-promoter probes (UCSC_RefGene_Group TSS200 or 1stExon; RASSF1A
  and p16INK4a transcripts for RASSF1 and CDKN2A) of ESR1, PGR, BRCA1, RASSF1, GSTP1 and CDKN2A
  from the Illumina 450K v1.2 manifest, kept when unmethylated in TCGA's normal breast samples
  (median beta under omics.NORMAL_MAX); per tumor the mean beta over them. The hypermethylation
  index = the mean beta over the autosomal CpG-island promoter probes (TSS1500, TSS200, 5'UTR,
  1stExon) unmethylated in normal breast. The 450K betas (~3 GB) are streamed from the Xena GDC
  hub once; the derived per-tumor numbers are cached in --extra.
* Immune and stromal scores: the 141-gene immune and stromal signatures of ESTIMATE (Yoshihara et
  al. 2013, Supplementary Data 1) by z-score averaging, not the ESTIMATE package; the immune-cell
  antibodies on the RPPA array by the same averaging; the slide workbench's stromal lymphocytes by
  zone for the cases with scored sections (muffle.workbench.invasion, as the slide page computes
  them, with the second lymphocyte model where it scored).

python scripts/omics_scores_2.py --data data/tcga_brca --raw data/raw/tcga_brca \
    --extra data/raw/omics --scores app/omics_scores.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from omics_scores import expression, fetch  # noqa: E402  (round 1's readers)

from muffle.data.tcga import XENA_GDC_HUB, primary_samples, read_header, read_matrix  # noqa: E402
from muffle.explain import risk_percentile as rank_percentile  # noqa: E402
from muffle.workbench import invasion, omics  # noqa: E402

MANIFEST = ("https://webdata.illumina.com/downloads/productfiles/humanmethylation450/"
            "humanmethylation450_15017482_v1-2.csv")
ESTIMATE = ("https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2F"
            "ncomms3612/MediaObjects/41467_2013_BFncomms3612_MOESM488_ESM.xlsx")
METHYLATION = f"{XENA_GDC_HUB}/TCGA-BRCA.methylation450.tsv.gz"
SLIDES = Path(__file__).resolve().parents[1] / "app" / "workbenches" / "slides_results"
QUANTILES = np.linspace(0, 1, 21)  # cohort distribution at 0, 5, ..., 100 %
MIN_COVERAGE = 0.5  # an antibody measured in under half of the RPPA tumors stays out of a score


def pct(value: float, cohort: pd.Series) -> float:
    return round(rank_percentile(value, cohort.dropna().to_numpy()), 1)


def estimate_sets(extra: Path) -> dict[str, list[str]]:
    """The stromal and immune gene lists of Supplementary Data 1 (an .xlsx read with the standard
    library: row 3 the stromal signature, row 4 the immune one, genes from column C on)."""
    z = zipfile.ZipFile(fetch(ESTIMATE, extra / "estimate_supplementary_data_1.xlsx"))
    strings = ["".join(re.findall(r"<t[^>]*>([^<]*)</t>", s)) for s in
               re.findall(r"<si>(.*?)</si>", z.read("xl/sharedStrings.xml").decode(), re.S)]
    rows = {}
    for r, body in re.findall(r'<row r="(\d+)"[^>]*>(.*?)</row>',
                              z.read("xl/worksheets/sheet1.xml").decode(), re.S):
        cells = re.findall(r'<c r="[A-Z]+\d+"([^>]*)>(?:<v>([^<]*)</v>)?', body)
        rows[int(r)] = [strings[int(v)] if 't="s"' in a else v for a, v in cells]
    assert rows[3][0].startswith("Stromal") and rows[4][0].startswith("Immune"), rows.get(3)
    return {"stromal": rows[3][2:], "immune": rows[4][2:]}


def manifest(extra: Path) -> pd.DataFrame:
    path = fetch(MANIFEST, extra / Path(MANIFEST).name)
    m = pd.read_csv(path, skiprows=7, dtype=str, low_memory=False,
                    usecols=["IlmnID", "CHR", "UCSC_RefGene_Name", "UCSC_RefGene_Accession",
                             "UCSC_RefGene_Group", "Relation_to_UCSC_CpG_Island"])
    return m[m["IlmnID"].str.startswith("cg", na=False)]  # drops the [Controls] section


def methylation(patients: list[str], probes: dict[str, list[str]], index: list[str],
                extra: Path) -> dict:
    """Streamed from the hub once and cached: the tumors' betas of the genes' core-promoter
    probes ("tumor", tumors x probes), those probes' median beta in TCGA's normal breast samples
    ("normal"), and per tumor the hypermethylation index ("index"): the mean beta over the
    CpG-island promoter probes that are unmethylated in normal breast (median under NORMAL_MAX,
    at least 10 normal samples measured; "index_probes" of them)."""
    keep = sorted({p for v in probes.values() for p in v})
    key = hashlib.sha1("\n".join([METHYLATION, *keep, str(len(index)), str(omics.NORMAL_MAX),
                                  *sorted(patients)]).encode()).hexdigest()[:10]
    cache = extra / f"methylation_round2.{key}.pkl"
    if cache.exists():
        return pd.read_pickle(cache)
    header = read_header(METHYLATION)[1:]
    samples = {s: p for s, p in primary_samples(header).items() if p in set(patients)}
    normals = {s: f"N:{s}" for s in header if s[13:15] == "11"}  # sample type 11: normal tissue
    parts, normal, total, count, used, isl = [], [], 0.0, 0, 0, pd.Index(index)
    for n, block in enumerate(read_matrix(METHYLATION, {**samples, **normals})):
        is_normal = block.index.str.startswith("N:")
        tum, nor = block[~is_normal], block[is_normal]
        cols = block.columns.intersection(keep)
        parts.append(tum[cols])
        normal.append(nor[cols].median())
        cols = block.columns.intersection(isl)
        ok = cols[((nor[cols].median() < omics.NORMAL_MAX) & (nor[cols].notna().sum() >= 10))
                  .to_numpy()]
        total, count = total + tum[ok].sum(axis=1), count + tum[ok].notna().sum(axis=1)
        used += len(ok)
        print(f"  methylation block {n}: {block.shape[1]} probes, {len(nor)} normal samples",
              flush=True)
    out = {"tumor": pd.concat(parts, axis=1), "normal": pd.concat(normal),
           "index": total / count.replace(0, np.nan), "index_probes": used,
           "normal_samples": int(len(nor))}
    pd.to_pickle(out, cache)
    return out


def section_immune(slide: str) -> dict | None:
    """A scored section's stromal lymphocytes by zone, computed as the slide page does (tile
    head, nuclei, and the second lymphocyte model where it scored)."""
    folder = SLIDES / slide
    if not (folder / "tiles.json").exists():
        return None
    tiles = pd.read_json(folder / "tiles.json", orient="split")
    meta = json.loads((folder / "summary.json").read_text(encoding="utf-8"))
    nuc = folder / "nuclei.json"
    nuc = json.loads(nuc.read_text(encoding="utf-8")) if nuc.exists() else {}
    if (nuc.get("tiles") or {}).get("data"):
        tiles = tiles.merge(pd.DataFrame(nuc["tiles"]["data"], columns=nuc["tiles"]["columns"]),
                            on=["row", "col"], how="left")
    til = folder / "til.json"
    til = json.loads(til.read_text(encoding="utf-8")) if til.exists() else None
    if til and til.get("tiles"):
        tiles["p_til"] = ("r" + tiles["row"].astype(str) + "c" + tiles["col"].astype(str)).map(
            til["tiles"])
    res = invasion.analyze_slide(tiles, meta["head"]["classes"],
                                 til_cutoff=til["cutoff"] if til else None,
                                 til_calibrated=bool(til and "calibrated" in til.get(
                                     "cutoff_source", "")))
    return {"pattern": res["immune"]["pattern"], "zones": res["immune"]["zones"],
            "til_model": (til or {}).get("model", {}).get("name"),
            "til_cutoff": (til or {}).get("cutoff"),
            "method_version": meta.get("method_version")}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=Path("data/tcga_brca"))
    p.add_argument("--raw", type=Path, default=Path("data/raw/tcga_brca"))
    p.add_argument("--extra", type=Path, default=Path("data/raw/omics"))
    p.add_argument("--scores", type=Path, default=Path("app/omics_scores.json"))
    args = p.parse_args()
    log = lambda *a: print(*a, flush=True)  # noqa: E731

    result = json.loads(args.scores.read_text())
    cohort = np.load(args.data / "cohort.npz")
    patients = [str(x) for x in cohort["patient"]]
    bundled = {int(i): patients[int(i)] for i in result["cases"]}
    log(f"{len(patients)} cohort patients, {len(bundled)} cases in {args.scores}")

    # --- RPPA: pathway scores, immune markers, protein against RNA ---------------------------
    source = args.raw / "TCGA-BRCA.protein.tsv.gz"
    samples = {s: pt for s, pt in primary_samples(read_header(source)[1:]).items()
               if pt in set(patients)}
    prot = pd.concat(list(read_matrix(source, samples)), axis=1)
    prot = prot[prot.notna().any(axis=1)]
    coverage = prot.notna().mean()
    named = {a for pw in omics.RPPA_PATHWAYS.values() for a in [*pw["members"], *pw["also"]]}
    named |= set(omics.RPPA_IMMUNE)
    missing = sorted(named - set(prot.columns))
    assert not missing, f"antibodies not in the RPPA file: {missing}"
    dropped = sorted(a for a in named if coverage[a] < MIN_COVERAGE)
    log(f"RPPA: {prot.shape[0]} tumors x {prot.shape[1]} antibodies; under {MIN_COVERAGE:.0%} "
        f"coverage, left out of scores: {dropped}")
    zp = (prot - prot.median()) / prot.std(ddof=0).replace(0, 1)  # Akbani: median-centered, SD
    sets = {name: {a: s for a, s in pw["members"].items() if a not in dropped}
            for name, pw in omics.RPPA_PATHWAYS.items()}
    immune_abs = [a for a in omics.RPPA_IMMUNE if a not in dropped]
    pw_scores = omics.signed_scores(zp, {**sets, "_immune": dict.fromkeys(immune_abs, 1)})
    measured = {name: zp[list(m)].notna().sum(axis=1) for name, m in sets.items()}

    # --- RNA of the antibodies' genes, the methylation genes and the signatures --------------
    sig = estimate_sets(args.extra)
    genes = (set(omics.ANTIBODY_GENES.values()) | set(omics.METHYLATION_GENES)
             | set(sig["immune"]) | set(sig["stromal"]) | set(omics.CYTOLYTIC))
    x = expression(args.raw, patients, genes)
    log(f"RNA: {x.shape[0]} tumors x {x.shape[1]} genes; ESTIMATE immune "
        f"{len(x.columns.intersection(sig['immune']))}/141, stromal "
        f"{len(x.columns.intersection(sig['stromal']))}/141 measured")
    z = (x - x.mean()) / x.std(ddof=0).replace(0, 1)
    estimate = omics.set_scores(z, {"immune": sig["immune"], "stromal": sig["stromal"],
                                    "cytolytic": list(omics.CYTOLYTIC)})

    protein_vs_rna = {}
    for a in sorted(named):
        gene = omics.ANTIBODY_GENES[a]
        if gene not in x.columns:
            continue
        both = pd.concat([prot[a], x[gene]], axis=1, join="inner").dropna()
        if len(both) >= 30:
            protein_vs_rna[a] = {"gene": gene, "n": len(both),
                                 "spearman": round(float(both.corr("spearman").iloc[0, 1]), 3)}
    weak = sorted(a for a, r in protein_vs_rna.items() if r["spearman"] < omics.WEAK_RHO)
    log(f"protein vs RNA: {len(protein_vs_rna)} antibodies, weak (< {omics.WEAK_RHO}): {weak}")
    both = pd.concat([pw_scores["_immune"], estimate], axis=1, join="inner").dropna()
    immune_val = {"rppa_immune_vs_estimate_immune": round(float(both.corr("spearman").iloc[
                      0, 1]), 3), "n": len(both),
                  "estimate_immune_vs_cytolytic": round(float(estimate["immune"].corr(
                      estimate["cytolytic"], method="spearman")), 3),
                  "estimate_immune_vs_stromal": round(float(estimate["immune"].corr(
                      estimate["stromal"], method="spearman")), 3), "rna_tumors": len(estimate)}
    log("immune:", immune_val)

    # --- methylation: promoter probes and the index ------------------------------------------
    man = manifest(args.extra)
    candidates, index = omics.promoter_probes(man, {g: omics.TRANSCRIPTS.get(g)
                                                    for g in omics.METHYLATION_GENES})
    meth = methylation(patients, candidates, index, args.extra)
    tumor, normal = meth["tumor"], meth["normal"]
    # a gene's probes: its core-promoter probes unmethylated in normal breast (all of them if none)
    probes = {g: [c for c in v if normal.get(c, np.nan) < omics.NORMAL_MAX] or v
              for g, v in candidates.items()}
    log(f"manifest: {len(man)} probes; core-promoter probes kept/candidates per gene "
        f"{ {g: f'{len(probes[g])}/{len(v)}' for g, v in candidates.items()} }; index probes "
        f"{meth['index_probes']} of {len(index)} island promoter probes; "
        f"{meth['normal_samples']} normal samples")
    gene_beta = omics.promoter_beta(tumor, probes)
    meth_index = meth["index"]
    meth_val = {}
    for g in omics.METHYLATION_GENES:
        both = pd.concat([gene_beta[g], x[g]], axis=1, join="inner").dropna()
        called = both.iloc[:, 0] >= omics.METHYLATED
        rna_pct = both.iloc[:, 1].rank(pct=True) * 100
        meth_val[g] = {"n": len(both), "methylated": int(called.sum()),
                       "spearman": round(float(both.corr("spearman").iloc[0, 1]), 3),
                       "rna_pct_median_methylated": None if not called.any() else
                       round(float(rna_pct[called].median()), 1),
                       "rna_pct_median_unmethylated": round(float(rna_pct[~called].median()), 1)}
    log("methylation vs RNA:", json.dumps(meth_val))
    annot = man.set_index("IlmnID").reindex([str(c) for c in cohort["names_methylation"]])
    cpg_annot = {c: "; ".join(v for v in (r["UCSC_RefGene_Name"], r["UCSC_RefGene_Group"],
                                         r["Relation_to_UCSC_CpG_Island"]) if isinstance(v, str))
                 for c, r in annot.iterrows()}

    # --- per case -----------------------------------------------------------------------------
    slide_cases = json.loads((SLIDES / "cases.json").read_text())
    pairs = sorted({(omics.ANTIBODY_GENES[a], a) for a in named})
    for i, pt in bundled.items():
        cs = result["cases"][str(i)]
        for k in ("rppa", "rna_pct", "estimate", "methylation", "slides"):  # a rerun replaces
            cs.pop(k, None)
        if pt in prot.index:
            cs["rppa"] = {
                "pathways": {name: [round(float(pw_scores.at[pt, name]), 2),
                                    pct(pw_scores.at[pt, name], pw_scores[name]),
                                    int(measured[name][pt])]
                             for name in sets if not np.isnan(pw_scores.at[pt, name])},
                "antibodies": {a: [round(float(zp.at[pt, a]), 2), pct(prot.at[pt, a], prot[a])]
                               for a in sorted(named) if not np.isnan(prot.at[pt, a])}}
            if not np.isnan(pw_scores.at[pt, "_immune"]):
                cs["rppa"]["immune"] = [round(float(pw_scores.at[pt, "_immune"]), 2),
                                        pct(pw_scores.at[pt, "_immune"], pw_scores["_immune"]),
                                        int(zp.loc[pt, immune_abs].notna().sum())]
        if pt in x.index:
            cs["rna_pct"] = {g: pct(x.at[pt, g], x[g]) for g in sorted(
                {g for g, _ in pairs} | set(omics.METHYLATION_GENES)) if g in x.columns}
            cs["estimate"] = {k: [round(float(estimate.at[pt, k]), 2),
                                  pct(estimate.at[pt, k], estimate[k])]
                              for k in ("immune", "stromal")}
        if pt in tumor.index and not np.isnan(meth_index.get(pt, np.nan)):
            cs["methylation"] = {
                "genes": {g: [round(float(gene_beta.at[pt, g]), 3),
                              pct(gene_beta.at[pt, g], gene_beta[g]),
                              int(tumor.loc[pt, tumor.columns.intersection(probes[g])].notna()
                                  .sum())]
                          for g in omics.METHYLATION_GENES if not np.isnan(gene_beta.at[pt, g])},
                "index": [round(float(meth_index[pt]), 3), pct(meth_index[pt], meth_index)]}
        secs = {s: section_immune(s) for s in slide_cases.get(str(i), [])}
        if any(secs.values()):
            cs["slides"] = {s: v for s, v in secs.items() if v}

    result["version2"] = f"omics-scores 2 ({date.today().isoformat()})"
    result["references"] = {**result.get("references", {}), **omics.REFERENCES}
    result["rppa"] = {"tumors": int(prot.shape[0]), "antibodies": int(prot.shape[1]),
                      "coverage": {a: round(float(coverage[a]), 3) for a in sorted(named)},
                      "left_out": dropped, "min_coverage": MIN_COVERAGE,
                      "pathway_tumors": {n: int(pw_scores[n].notna().sum()) for n in sets},
                      "immune_markers": immune_abs}
    result["methylation_markers"] = {
        "probes": probes, "candidates": candidates,
        "normal_median": {c: round(float(normal[c]), 3) for v in candidates.values() for c in v
                          if c in normal.index and not np.isnan(normal[c])},
        "normal_samples": meth["normal_samples"], "index_probes": meth["index_probes"],
        "index_candidates": len(index), "tumors": int(meth_index.notna().sum()),
        "quantiles": {g: [round(float(v), 3) for v in gene_beta[g].quantile(QUANTILES)]
                      for g in omics.METHYLATION_GENES},
        "index_quantiles": [round(float(v), 3) for v in meth_index.quantile(QUANTILES)],
        "cpg_annot": cpg_annot}
    result["immune_sets"] = {k: {"size": len(v), "measured": int(len(x.columns.intersection(v))),
                                 "genes": v} for k, v in sig.items()}
    result.setdefault("validation", {}).update({
        "protein_vs_rna": protein_vs_rna, "protein_vs_rna_weak": weak,
        "methylation_vs_rna": meth_val, "immune": immune_val})
    args.scores.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    log(f"-> {args.scores} ({args.scores.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()

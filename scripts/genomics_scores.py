"""Copy number, mutation burden and allele fractions of bundled TCGA-BRCA cases (genomics_cn.json).

Runs offline on the local TCGA-BRCA files (scripts/prepare_tcga.py's --raw folder and its
cohort.npz) and ships only derived numbers for the genomics workbench (docs/genomics.md):

* Copy number (ASCAT3 gene level, UCSC Xena GDC hub): per bundled case, the absolute copy number of
  the model's 200 copy-number genes, the breast drivers of interest and the pathway map's genes,
  the tumor's ploidy estimate (its median gene copy number, rounded, at least 1: the rule of
  muffle.data.tcga.copy_number_calls, which built the model's input) and each gene's cohort
  percentile of copies relative to ploidy (mid-rank, so ties split). Calls are made in the app by
  muffle.workbench.genome.cn_call, the same rule; this script checks them against the bundle's
  own copy-number inputs. Per gene: position (GENCODE v36 probe map) and the cohort's share of
  each call (an aggregate).
* Mutation burden (GDC open masked somatic calls, Xena file): per case the number of calls, of
  coding calls and of protein-altering calls, and the rate per megabase over the 38 Mb exome size
  Chalmers et al. 2017 used for TCGA (Genome Med 9:34, doi:10.1186/s13073-017-0424-2: "We used
  38 Mb as the estimate of the exome size", with TCGA's somatic calls as the raw count), with its
  cohort percentile; cohort quantiles of the rate (an aggregate).
* Observed drivers: per call its consequence class (VEP's first term in the GDC file), GRCh38
  position and alleles (for the effect lookup, scripts/genomics_effect.py), dna_vaf checked
  against the read counts in app/evolution_vaf.json, and the gene's copy number.
* Purity and ploidy from ABSOLUTE (TCGA PanCanAtlas, TCGA_mastercalls.abs_tables_JSedit.fixed.txt;
  Carter et al. 2012, doi:10.1038/nbt.2203; Taylor et al. 2018, doi:10.1016/j.ccell.2018.03.007),
  downloaded once into --extra: ASCAT's own purity and ploidy are not in the open gene-level file.

Each case carries the bundle's log-risk and percentile: the app shows these numbers only when its
loaded case matches, so a rebuilt cohort never pairs them with another patient. No barcode leaves.

python scripts/genomics_scores.py --data data/tcga_brca --raw data/raw/tcga_brca \
    --extra ~/muffle-genomics/raw --bundle outputs/demo_bundle.pt --out app/genomics_cn.json
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from muffle.data.preprocess import drop_sparse  # noqa: E402
from muffle.data.tcga import (  # noqa: E402
    DRIVERS,
    PROTEIN_ALTERING,
    is_primary_a,
    primary_samples,
    read_header,
    read_matrix,
)
from muffle.demo import load_bundle  # noqa: E402
from muffle.workbench import genome  # noqa: E402

ABSOLUTE = "https://api.gdc.cancer.gov/data/4f277128-f793-4354-a13d-30cc7fe9f6b5"
VAF_JSON = Path(__file__).resolve().parents[1] / "app" / "evolution_vaf.json"
CODING = PROTEIN_ALTERING | {"synonymous_variant", "stop_retained_variant",
                             "coding_sequence_variant", "incomplete_terminal_codon_variant"}
QUANTILES = np.linspace(0, 1, 21)


def fetch(url: str, path: Path) -> Path:
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        urllib.request.urlretrieve(url, path.with_name(path.name + ".part"))
        path.with_name(path.name + ".part").rename(path)
    return path


def midrank(values: np.ndarray, x: float) -> float:
    """Percent of the cohort below ``x``, ties counted half: the percentile of a discrete value."""
    v = values[~np.isnan(values)]
    return float(((v < x).sum() + 0.5 * (v == x).sum()) / len(v) * 100)


def gene_table(raw: Path) -> pd.DataFrame:
    """Ensembl id -> symbol, chromosome and start (GENCODE v36 probe map), PAR copies dropped."""
    g = pd.read_csv(raw / "gencode.v36.annotation.gtf.gene.probemap", sep="\t")
    return g[~g["id"].str.endswith("_PAR_Y")].set_index("id")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--data", type=Path, default=Path("data/tcga_brca"))
    p.add_argument("--raw", type=Path, default=Path("data/raw/tcga_brca"))
    p.add_argument("--extra", type=Path, default=Path("data/raw/genomics"))
    p.add_argument("--bundle", default="outputs/demo_bundle.pt")
    p.add_argument("--out", type=Path, default=Path("app/genomics_cn.json"))
    args = p.parse_args()
    log = lambda *a: print(*a, flush=True)  # noqa: E731

    cohort = np.load(args.data / "cohort.npz")
    patients = [str(x) for x in cohort["patient"]]
    demo = load_bundle(args.bundle)
    cases = {c.index: c for c in demo.cases}
    log(f"{len(patients)} cohort patients, {len(cases)} bundled cases")

    # --- copy number ---------------------------------------------------------------------
    source = args.raw / "TCGA-BRCA.gene-level_ascat3.tsv.gz"
    samples = {s: pt for s, pt in primary_samples(read_header(source)[1:]).items()
               if pt in set(patients)}
    cn = drop_sparse(pd.concat(list(read_matrix(source, samples)), axis=1), 0.2)
    ploidy = pd.Series(np.clip(np.round(np.nanmedian(cn.to_numpy(np.float32), axis=1)), 1, None),
                       index=cn.index)
    genes = gene_table(args.raw)
    layer = [str(n) for n in cohort["names_genomic"]]
    wanted = list(dict.fromkeys(layer + list(genome.INTEREST) + list(genome.PATHWAY_GENES)
                                + DRIVERS))
    candidates: dict[str, list[str]] = {}
    for col in cn.columns:
        sym = genes["gene"].get(col)
        if sym in wanted:
            candidates.setdefault(sym, []).append(col)
    # a symbol shared by several loci (Y_RNA names hundreds): for a model gene, the locus whose
    # calls equal the model's column; otherwise the first
    x_genomic = pd.DataFrame(cohort["x_genomic"], index=patients, columns=layer)
    has_cn = [pt for pt in cn.index if pt in x_genomic.index]
    by_symbol: dict[str, str] = {}
    for sym in wanted:
        cols = candidates.get(sym, [])
        if len(cols) > 1 and sym in layer:
            model = x_genomic.loc[has_cn, sym].to_numpy()
            score = [np.mean([genome.cn_call(c, pl) == m for c, pl, m in zip(
                cn.loc[has_cn, col], ploidy[has_cn], model, strict=True)]) for col in cols]
            by_symbol[sym] = cols[int(np.argmax(score))]
        elif cols:
            by_symbol[sym] = cols[0]
    missing = [g for g in wanted if g not in by_symbol]
    log(f"copy number: {cn.shape[0]} tumors x {cn.shape[1]} genes; {len(by_symbol)} of "
        f"{len(wanted)} wanted genes measured; missing {missing}")
    ratio = cn[[by_symbol[g] for g in by_symbol]].div(ploidy, axis=0)
    ratio.columns = list(by_symbol)
    copies = cn[[by_symbol[g] for g in by_symbol]]
    copies.columns = list(by_symbol)

    chrom_order = {f"chr{c}": i for i, c in enumerate([*map(str, range(1, 23)), "X", "Y"])}
    gene_meta = {}
    for g, col in by_symbol.items():
        calls = [genome.cn_call(c, pl) for c, pl in zip(copies[g], ploidy, strict=True)]
        calls = pd.Series(calls, dtype="float").dropna()
        gene_meta[g] = {
            "chrom": genes.at[col, "chrom"].removeprefix("chr"),
            "start_mb": round(float(genes.at[col, "chromStart"]) / 1e6, 3),
            "order": chrom_order.get(genes.at[col, "chrom"], 99) * 1e3
            + round(float(genes.at[col, "chromStart"]) / 1e6, 3),
            "ensembl": col.split(".")[0],
            "in_layer": g in layer, "interest": g in genome.INTEREST,
            "pathways": [k for k, pw in genome.PATHWAYS.items() if g in pw["genes"]],
            "cohort_calls": [round(float((calls == c).mean()), 3) for c in range(-2, 3)],
            "cohort_n": int(len(calls)),
        }

    # --- ABSOLUTE purity and ploidy --------------------------------------------------------
    table = fetch(ABSOLUTE, args.extra / "TCGA_mastercalls.abs_tables_JSedit.fixed.txt")
    absol = pd.read_csv(table, sep="\t")
    absol = absol[absol["array"].str[13:15] == "01"]  # primary tumors
    absol = absol.assign(patient=absol["array"].str[:12]).drop_duplicates("patient")
    absol = absol.set_index("patient")
    log(f"ABSOLUTE: {len(absol)} primary tumors (all TCGA); this cohort's covered: "
        f"{absol.index.isin(patients).sum()}")

    # --- mutations: burden and drivers -----------------------------------------------------
    muts = pd.read_csv(args.raw / "TCGA-BRCA.somaticmutation_wxs.tsv.gz", sep="\t",
                       usecols=["sample", "gene", "chrom", "start", "ref", "alt",
                                "Amino_Acid_Change", "effect", "dna_vaf"])
    muts = muts[muts["sample"].map(is_primary_a)].assign(patient=lambda d: d["sample"].str[:12])
    muts = muts[muts["patient"].isin(patients)]
    first = muts["effect"].astype(str).str.split(";").str[0]
    muts = muts.assign(first=first)
    counts = muts.groupby("patient").agg(
        calls=("gene", "size"),
        coding=("first", lambda s: int(s.isin(CODING).sum())),
        altering=("first", lambda s: int(s.isin(PROTEIN_ALTERING).sum())))
    counts["rate"] = counts["calls"] / genome.EXOME_MB
    rates = counts["rate"].to_numpy(float)
    log(f"burden: {len(counts)} sequenced cohort tumors; median {np.median(counts['calls']):.0f} "
        f"calls, {np.median(rates):.2f} per Mb")

    vaf = json.loads(VAF_JSON.read_text())["cases"] if VAF_JSON.exists() else {}
    out_cases, layer_check, vaf_check = {}, [0, 0], [0, 0]
    names = demo.names.get("genomic", [])
    for i in sorted(cases):
        case, pt = cases[i], patients[i]
        entry = {"log_risk": round(case.log_risk, 4), "percentile": round(case.percentile, 1)}
        if pt in cn.index:
            pl = float(ploidy[pt])
            entry["ploidy"] = pl
            entry["cn"] = {g: [None if np.isnan(c) else (int(c) if c == int(c) else float(c)),
                               None if np.isnan(r) else round(midrank(ratio[g].to_numpy(float), r))]
                           for g, c, r in zip(by_symbol, copies.loc[pt], ratio.loc[pt],
                                              strict=True)}
            x = demo.x["genomic"][case.row].numpy()  # the model's own input: the same rule?
            for j, g in enumerate(names):
                c = entry["cn"].get(g, [None])[0]
                if c is not None:
                    layer_check[1] += 1
                    layer_check[0] += int(genome.cn_call(c, pl) == int(round(float(x[j]))))
        if pt in absol.index and absol.at[pt, "call status"] == "called":
            entry["absolute"] = {"purity": float(absol.at[pt, "purity"]),
                                 "ploidy": float(absol.at[pt, "ploidy"])}
        if pt in counts.index:
            r = counts.loc[pt]
            entry["burden"] = {"calls": int(r["calls"]), "coding": int(r["coding"]),
                               "altering": int(r["altering"]), "rate": round(float(r["rate"]), 3),
                               "pct": round(midrank(rates, float(r["rate"])), 1)}
            rows = muts[(muts["patient"] == pt) & muts["gene"].isin(DRIVERS)
                        & muts["first"].isin(PROTEIN_ALTERING)]
            reads = {v["variant"]: v for v in vaf.get(str(i), {}).get("variants", [])}
            drivers = []
            for _, m in rows.iterrows():
                name = f"{m['gene']} {str(m['Amino_Acid_Change']).removeprefix('p.')}"
                d = {"variant": name, "class": genome.consequence_class(m["first"]),
                     "consequence": m["first"], "chrom": str(m["chrom"]).removeprefix("chr"),
                     "pos": int(m["start"]), "ref": m["ref"], "alt": m["alt"],
                     "dna_vaf": round(float(m["dna_vaf"]), 4)}
                if m["gene"] in entry.get("cn", {}):
                    d["copies"] = entry["cn"][m["gene"]][0]
                if name in reads:
                    vaf_check[1] += 1
                    vaf_check[0] += int(abs(reads[name]["alt"] / reads[name]["depth"]
                                            - float(m["dna_vaf"])) < 1e-3)
                drivers.append(d)
            entry["drivers"] = sorted(drivers, key=lambda d: d["variant"])
            want = sorted(m.replace(" p.", " ") for m in (case.mutations or []))
            if sorted(d["variant"] for d in drivers) != want:
                log(f"  case {i}: drivers {[d['variant'] for d in drivers]} != bundle {want}")
        out_cases[str(i)] = entry
    log(f"calls vs the bundle's copy-number input: {layer_check[0]}/{layer_check[1]} agree; "
        f"dna_vaf vs evolution_vaf.json read counts: {vaf_check[0]}/{vaf_check[1]} agree")

    result = {
        "version": f"genomics-scores 1 ({date.today().isoformat()})",
        "reference": {"cohort": "TCGA-BRCA primary tumors in the model's cohort (cohort.npz)",
                      "copy_number_tumors": int(cn.shape[0]),
                      "sequenced_tumors": int(len(counts)),
                      "absolute_tumors": int(absol.index.isin(patients).sum())},
        "checks": {"calls_vs_bundle": layer_check, "vaf_vs_read_counts": vaf_check,
                   "genes_missing": missing},
        "burden": {"exome_mb": genome.EXOME_MB,
                   "rate_quantiles": [round(float(q), 3) for q in np.quantile(rates, QUANTILES)],
                   "calls_median": float(np.median(counts["calls"])),
                   "rate_median": round(float(np.median(rates)), 3)},
        "genes": dict(sorted(gene_meta.items(), key=lambda kv: kv[1]["order"])),
        "cases": out_cases,
    }
    args.out.write_text(json.dumps(result, separators=(",", ":")) + "\n")
    log(f"-> {args.out} ({args.out.stat().st_size / 1e3:.0f} kB, {len(out_cases)} cases)")


if __name__ == "__main__":
    main()

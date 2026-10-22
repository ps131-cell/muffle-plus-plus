"""Allele fractions of the bundled TCGA cases' driver calls, for the Evolution view's clonal panel
(app/evolution_vaf.json: derived numbers only, no barcode).

python scripts/make_evolution_vaf.py --bundle outputs/demo_bundle.pt --data data/tcga_brca \
    --raw data/raw/tcga_brca

For each bundled case (Case.index -> its TCGA barcode in cohort.npz) it reads that case's
open-access masked somatic MAF from the GDC API (the "Aliquot Ensemble Somatic Variant Merging
and Masking" calls behind the Xena file the cohort was built from) for t_alt_count and t_depth of
each driver call the bundle names, checks t_alt_count / t_depth against the Xena file's dna_vaf,
and adds the gene's total copy number in that sample (ASCAT3, gene level, Xena). ASCAT purity is
not in the local data, so the panel says "allele fraction only, purity unknown". Downloads go to
data/raw/gdc_maf/ (git-ignored).
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from muffle.data.tcga import DRIVERS  # noqa: E402

GDC = "https://api.gdc.cancer.gov"
OUT = Path(__file__).resolve().parents[1] / "app" / "evolution_vaf.json"


def gdc_mafs(barcodes: list[str]) -> dict[str, list[str]]:
    """{patient barcode: [file ids]} of the open masked somatic MAFs (exome) for these cases."""
    filters = {"op": "and", "content": [
        {"op": "in", "content": {"field": "cases.submitter_id", "value": barcodes}},
        {"op": "=", "content": {"field": "data_type", "value": "Masked Somatic Mutation"}},
        {"op": "=", "content": {"field": "access", "value": "open"}}]}
    q = urllib.parse.urlencode({"filters": json.dumps(filters), "format": "JSON",
                                "fields": "file_id,cases.submitter_id", "size": "500"})
    with urllib.request.urlopen(f"{GDC}/files?{q}", timeout=60) as r:
        hits = json.load(r)["data"]["hits"]
    out: dict[str, list[str]] = {}
    for h in hits:
        out.setdefault(h["cases"][0]["submitter_id"], []).append(h["file_id"])
    return out


def read_maf(file_id: str, cache: Path) -> pd.DataFrame:
    path = cache / f"{file_id}.maf.gz"
    if not path.exists():
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(f"{GDC}/data/{file_id}", timeout=120) as r:
            path.write_bytes(r.read())
    with gzip.open(path, "rt") as f:
        text = "".join(line for line in f if not line.startswith("#"))
    return pd.read_csv(io.StringIO(text), sep="\t", dtype=str,
                       usecols=["Hugo_Symbol", "HGVSp_Short", "Tumor_Sample_Barcode", "t_depth",
                                "t_alt_count"])


def copy_numbers(raw: Path, samples: list[str]) -> pd.DataFrame:
    """Gene x sample total copy number (ASCAT3) for the driver genes, by gene symbol."""
    probes = pd.read_csv(raw / "gencode.v36.annotation.gtf.gene.probemap", sep="\t",
                         usecols=["id", "gene"])
    ids = set(probes.loc[probes["gene"].isin(DRIVERS), "id"])
    source = raw / "TCGA-BRCA.gene-level_ascat3.tsv.gz"
    header = pd.read_csv(source, sep="\t", nrows=0).columns
    keep = [header[0], *[s for s in samples if s in header]]
    cn = pd.read_csv(source, sep="\t", usecols=keep, index_col=0)
    cn = cn[cn.index.isin(ids)]
    return cn.rename(index=dict(zip(probes["id"], probes["gene"], strict=True)))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--bundle", default="outputs/demo_bundle.pt")
    p.add_argument("--data", default="data/tcga_brca")
    p.add_argument("--raw", default="data/raw/tcga_brca")
    p.add_argument("--cache", default="data/raw/gdc_maf")
    p.add_argument("--out", default=str(OUT))
    a = p.parse_args()
    raw = Path(a.raw)
    cases = torch.load(a.bundle, map_location="cpu", weights_only=True)["cases"]
    with np.load(Path(a.data) / "cohort.npz") as f:
        patients = f["patient"]
    calls = {c["index"]: [m.split(" ", 1) for m in c["mutations"] or []] for c in cases}
    barcode = {i: str(patients[i]) for i in calls}
    xena = pd.read_csv(raw / "TCGA-BRCA.somaticmutation_wxs.tsv.gz", sep="\t",
                       usecols=["sample", "gene", "Amino_Acid_Change", "dna_vaf"])
    files = gdc_mafs([b for i, b in barcode.items() if calls[i]])
    cn = copy_numbers(raw, [f"{b}-01A" for b in barcode.values()])
    out, checks = {}, []
    for i, genes in calls.items():
        if not genes:
            continue
        b = barcode[i]
        maf = pd.concat([read_maf(fid, Path(a.cache)) for fid in files.get(b, [])]
                        or [pd.DataFrame(columns=["Hugo_Symbol", "HGVSp_Short",
                                                  "Tumor_Sample_Barcode", "t_depth",
                                                  "t_alt_count"])])
        maf = maf[maf["Tumor_Sample_Barcode"].str.startswith(f"{b}-01A")]
        variants = []
        for gene, change in genes:
            hit = maf[(maf["Hugo_Symbol"] == gene) & (maf["HGVSp_Short"] == change)]
            row = {"variant": f"{gene} {change.removeprefix('p.')}"}
            if not hit.empty:
                best = hit.assign(d=hit["t_depth"].astype(int)).sort_values("d").iloc[-1]
                row.update(alt=int(best["t_alt_count"]), depth=int(best["t_depth"]))
                x = xena[(xena["sample"] == f"{b}-01A") & (xena["gene"] == gene)
                         & (xena["Amino_Acid_Change"] == change)]["dna_vaf"]
                if not x.empty:
                    checks.append(abs(row["alt"] / row["depth"] - float(x.iloc[0])))
            col = f"{b}-01A"
            if col in cn.columns and gene in cn.index:
                v = cn.loc[gene, col]
                v = float(v.iloc[0] if isinstance(v, pd.Series) else v)
                if not np.isnan(v):
                    row["copies"] = round(v, 2)
            variants.append(row)
        out[str(i)] = {"variants": variants}
    counted = sum("depth" in v for c in out.values() for v in c["variants"])
    total = sum(len(c["variants"]) for c in out.values())
    print(f"{len(out)} cases, {total} driver calls, {counted} with read counts; "
          f"largest |t_alt/t_depth - Xena dna_vaf| = {max(checks, default=0):.4f}")
    Path(a.out).write_text(json.dumps({
        "built": date.today().isoformat(),
        "source": "GDC open-access masked somatic mutation calls (exome, Aliquot Ensemble "
                  "Somatic Variant Merging and Masking), TCGA-BRCA primary tumors: the variant's "
                  "read count and the read depth per driver call; total copy number of the "
                  "gene from ASCAT3 "
                  "(gene level, UCSC Xena GDC hub)",
        "purity": None,
        "cases": out}, indent=1) + "\n", encoding="utf-8")
    print("wrote", a.out)


if __name__ == "__main__":
    main()

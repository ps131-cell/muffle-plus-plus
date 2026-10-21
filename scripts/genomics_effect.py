"""Effect snapshot of the observed variants (app/genomics_effect.json): VEP, ClinVar, AlphaMissense.

For every driver call of the bundled TCGA cases (app/genomics_cn.json: GRCh38 position and
alleles) and for the synthetic patient's variants (muffle.timeline: names only, plus any
--variant given), it asks Ensembl VEP (REST) for the consequence on the MANE Select transcript
and the ClinVar classifications of the co-located variant record, and reads the AlphaMissense
score and class of each missense change from the AlphaMissense hg38 table (Cheng et al. 2023,
doi:10.1126/science.adg7492; Zenodo record 10.5281/zenodo.10813168, predictions CC BY 4.0 per
its README and the record), checked against the score Ensembl serves. Only variant names and
positions are sent; COSMIC and HGMD identifiers are dropped (muffle.report.vep). The few numbers
kept ship with the app so it works offline; the snapshot date is shown on the page.

python scripts/genomics_effect.py --alphamissense ~/muffle-genomics/raw/AlphaMissense_hg38.tsv.gz \
    --variant "ESR1 D538G" --variant "DNMT3A R882H"
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from muffle.report import vep  # noqa: E402
from muffle.timeline import EVENTS  # noqa: E402

CN_JSON = ROOT / "app" / "genomics_cn.json"
OUT = ROOT / "app" / "genomics_effect.json"
ZENODO = "https://doi.org/10.5281/zenodo.10813168"


def alphamissense(path: Path, wanted: set[tuple[str, int, str, str]]) -> tuple[dict, dict]:
    """The table's rows for ``wanted`` (chrom without "chr", position, ref, alt), and the score
    range of each class over the whole table (its authors' cutoffs, read off the data)."""
    rows, ranges = {}, {}
    with gzip.open(path, "rt") as f:
        for line in f:
            if line.startswith("#"):
                continue
            chrom, pos, ref, alt, _, uniprot, tx, pv, score, cls = line.rstrip("\n").split("\t")
            s = float(score)
            lo, hi = ranges.get(cls, (s, s))
            ranges[cls] = (min(lo, s), max(hi, s))
            key = (chrom.removeprefix("chr"), int(pos), ref, alt)
            if key in wanted:
                rows[key] = {"score": s, "class": cls, "uniprot": uniprot, "transcript": tx,
                             "protein_variant": pv}
    return rows, ranges


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--alphamissense", type=Path, required=True)
    p.add_argument("--variant", action="append", default=[],
                   help="an extra substitution by name, e.g. 'ESR1 D538G'")
    p.add_argument("--out", type=Path, default=OUT)
    args = p.parse_args()
    log = lambda *a: print(*a, flush=True)  # noqa: E731

    cn = json.loads(CN_JSON.read_text())
    calls = {}
    for case in cn["cases"].values():
        for d in case.get("drivers", []):
            calls.setdefault(d["variant"], d)
    named = sorted({f"{g} {c}" for e in EVENTS for g, c in e.get("mutations", [])}
                   | set(args.variant))
    named = [n for n in named if n not in calls]
    log(f"{len(calls)} distinct TCGA driver calls, {len(named)} named variants: {named}")

    out: dict[str, dict] = {}
    lines = [vep.region(d["chrom"], d["pos"], d["ref"], d["alt"], v) for v, d in calls.items()]

    def regions(batch: list[str]) -> list[dict]:
        try:
            return vep.query_regions(batch, timeout=120, tries=3)
        except Exception as e:  # isolate the line Ensembl rejects
            if len(batch) == 1:
                log(f"  VEP failed for {batch[0]}: {e}")
                return []
            return [r for line in batch for r in regions([line])]

    for k in range(0, len(lines), 25):
        for r in regions(lines[k:k + 25]):
            out[r["id"].replace("_", " ")] = vep.parse(r)
    hg = {vep.hgvs_protein(n): n for n in named if vep.hgvs_protein(n)}
    for r in vep.query_hgvs(list(hg), timeout=120, tries=3) if hg else []:
        out[hg[r["input"]]] = vep.parse(r)
    log(f"VEP: {len(out)} of {len(calls) + len(named)} annotated; ClinVar records for "
        f"{sum(bool(e['clinvar']) for e in out.values())}")

    # AlphaMissense from the table, for every missense SNV (positions from VEP for named ones)
    wanted = {}
    for name, e in out.items():
        if e["consequence"] != "missense_variant":
            continue
        chrom, rest = e["position"].split(":", 1)
        pos, alleles = rest.split(" ")[:2]
        ref, alt = alleles.split("/")
        if len(ref) == 1 and len(alt) == 1:
            wanted[(chrom, int(pos), ref, alt)] = name
    rows, ranges = alphamissense(args.alphamissense, set(wanted))
    agree = 0
    for key, name in wanted.items():
        via = out[name]["alphamissense"]
        if key in rows:
            t = rows[key]
            agree += int(via is not None and abs(via["score"] - t["score"]) < 1e-3)
            out[name]["alphamissense"] = {"score": t["score"], "class": t["class"],
                                          "source": f"AlphaMissense hg38 table ({ZENODO})",
                                          "transcript": t["transcript"],
                                          "protein_variant": t["protein_variant"],
                                          "ensembl_agrees": via is not None
                                          and abs(via["score"] - t["score"]) < 1e-3}
    log(f"AlphaMissense: {len(rows)} of {len(wanted)} missense changes in the table; Ensembl's "
        f"score agrees for {agree}; class ranges {ranges}")

    try:
        release = vep.release()
    except Exception:
        release = "not read"
    result = {
        "snapshot": date.today().isoformat(),
        "ensembl_release": release,
        "sources": {
            "annotation": "Ensembl VEP REST (McLaren et al. 2016, doi:10.1186/s13059-016-0974-4), "
                          "MANE Select transcript",
            "clinvar": "ClinVar (Landrum et al. 2018, doi:10.1093/nar/gkx1153) as Ensembl serves "
                       "it with the co-located dbSNP record",
            "alphamissense": f"AlphaMissense (Cheng et al. 2023, doi:10.1126/science.adg7492), "
                             f"hg38 table, {ZENODO}; predictions CC BY 4.0",
        },
        "alphamissense_class_ranges": {k: [round(a, 4), round(b, 4)] for k, (a, b) in
                                       sorted(ranges.items())},
        "variants": dict(sorted(out.items())),
    }
    args.out.write_text(json.dumps(result, indent=1) + "\n")
    log(f"-> {args.out} ({args.out.stat().st_size / 1e3:.0f} kB)")


if __name__ == "__main__":
    main()

"""Build data/tcga_<project>/cohort.npz from open-tier TCGA data, in the synthetic format.

Target format (one row per patient, rows aligned across arrays):
    x_genomic [N, d_g]  x_rna [N, d_r]  x_methylation [N, d_m]  x_protein [N, d_p]
    x_clinical [N, d_c]  time [N] (months)  event [N] (1 = death/recurrence)
    mask [N, 5] (1 if that modality was measured, order = muffle.config.MODALITIES)
    stage [N] (for heterogeneous partitioning)
TCGA extras (stay under data/, never commit):
    tss [N]  tissue source site = barcode chars 6-7, the hospital that collected the sample
    age [N]  age at diagnosis in years, NaN if unknown (evaluation slices only; the model sees
             the z-scored, median-imputed copy in x_clinical)
    mut_genes [G], mut_status [N, G], mut_changes [N]  observed driver mutations from GDC's
             open-access somatic calls: 1 mutated, 0 sequenced without a protein-altering
             mutation, NaN not sequenced; changes as "PIK3CA p.H1047R;TP53 p.R175H" (case agent
             findings only, not a model input)
    patient [N]  12-char patient barcode
    names_<modality> [d]  feature names (gene symbols, CpG ids, RPPA targets, clinical fields)
Unmeasured modalities are all-zero rows with mask 0. Sizes d_* come from configs/default.yaml.

Sources, all open tier, from the UCSC Xena GDC hub (muffle.data.tcga.SOURCES):
    genomic      gene-level copy number (ASCAT3) -> calls in {-2..2} relative to tumour ploidy
    rna          STAR TPM -> log1p, top variance, then z-score
    methylation  450K beta values -> M-values. ~3 GB for BRCA, so it is streamed from the hub
                 and only the selected CpGs are cached under --raw
    protein      RPPA (TCPA) -> z-score. CPTAC mass spec covers only ~100 TCGA-BRCA tumours
    clinical     age, AJCC stage / T / N / M, ductal / lobular histology (median-imputed)
    survival     overall survival (OS, OS.time) from the hub's survival table

Steps:
  1. Download the files into --raw (methylation is streamed instead).
  2. Match on the 12-char patient barcode (TCGA-XX-XXXX); keep primary tumour samples (01A).
     Patients need survival, clinical data and at least one omic modality.
  3. Per modality: drop_sparse -> top_variance(k) -> transform (log_zscore / beta_to_m /
     z-score), k = configs/default.yaml sizes. Variance is ranked on the log / M scale but
     before z-scoring, which would give every feature variance 1. See muffle.data.preprocess.
  4. Survival: OS in months; event 1 = death.
  5. Partition by tissue source site (``tss``) to mimic real hospitals instead of random
     splits; that is the realistic federated split.

python scripts/prepare_tcga.py                          # TCGA-BRCA -> data/tcga_brca
python scripts/prepare_tcga.py --skip methylation       # quick build without the 3 GB stream
"""

import argparse
import functools
import shutil
from pathlib import Path

import numpy as np

from muffle.config import load_config
from muffle.data.tcga import BUILDERS, build_cohort, describe

if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--project", default="TCGA-BRCA")
    p.add_argument("--raw", type=Path, default=None, help="default: data/raw/<project>")
    p.add_argument("--out", type=Path, default=None, help="default: data/<project>")
    p.add_argument("--config", default=None)
    p.add_argument("--skip", nargs="*", default=[], choices=[*BUILDERS, "mutations"],
                   help="leave these modalities out (zeros, mask 0)")
    p.add_argument("--max-missing", type=float, default=0.2,
                   help="drop features missing in more than this fraction of measured tumours")
    args = p.parse_args()

    slug = args.project.lower().replace("-", "_")
    raw = args.raw or Path("data/raw") / slug
    out = args.out or Path("data") / slug
    log = functools.partial(print, flush=True)

    cohort = build_cohort(args.project, raw, load_config(args.config)["modalities"],
                          skip=args.skip, max_missing=args.max_missing, log=log)
    out.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(out / "cohort.npz", **cohort)
    for stale in out.glob("clients_*"):  # train_local reuses existing partitions
        shutil.rmtree(stale)
        log(f"removed stale partition {stale}")
    log(describe(cohort))
    log(f"-> {out / 'cohort.npz'}")

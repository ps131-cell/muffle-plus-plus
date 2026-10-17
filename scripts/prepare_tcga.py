"""TODO (data owner): build data/tcga_<project>/cohort.npz in the same format as the synthetic one.

Target format (one row per patient, rows aligned across arrays):
    x_genomic [N, d_g]  x_rna [N, d_r]  x_methylation [N, d_m]  x_protein [N, d_p]
    x_clinical [N, d_c]  time [N] (months)  event [N] (1 = death/recurrence)
    mask [N, 5] (1 if that modality was measured, order = muffle.config.MODALITIES)
    stage [N] (for heterogeneous partitioning)

Steps:
  1. Download open-tier files for TCGA-BRCA / TCGA-BLCA from the GDC Data Portal (gdc-client
     with a manifest) or the pre-processed UCSC Xena hubs: STAR counts, 450K beta values,
     gene-level copy number, masked somatic mutation (gene-level), clinical + survival.
  2. Match on the 12-char patient barcode (TCGA-XX-XXXX); keep primary tumor samples (01A).
  3. Per modality: drop_sparse -> transform (log_zscore / beta_to_m) -> top_variance(k)
     with k = configs/default.yaml sizes. See muffle.data.preprocess.
  4. Survival: OS from days_to_death / days_to_last_follow_up (or PFI from the TCGA-CDR table).
  5. Partition by tissue source site (barcode chars 6-7) to mimic real hospitals instead of
     random splits — that is the realistic federated split.
"""

raise SystemExit(__doc__)

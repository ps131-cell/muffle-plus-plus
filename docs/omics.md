# Expression, methylation and protein workbench

The workbench of the TCGA patient files' data layers (`docs/WORKBENCHES.md` §7): what each layer
measured, what the risk model reads from it, a PAM50 subtype call, pathway scores, and whether the
receptor measurements agree with the recorded IHC. Page: `app/workbenches/omics.py`; logic:
`src/muffle/workbench/omics.py` (tests: `tests/test_workbench_omics.py`); scores:
`scripts/omics_scores.py` → `app/omics_scores.json`.

## How the numbers are made

`scripts/omics_scores.py` runs offline, on the local TCGA-BRCA files that built the model's cohort
(UCSC Xena GDC hub: STAR TPM, ASCAT3 gene-level copy number, RPPA; `scripts/prepare_tcga.py`). It
ships only derived numbers for the 40 bundled cases: subtype calls with their correlations, set
scores and percentiles, receptor calls, and the cohort's per-feature deciles (an aggregate).
Never a patient's expression, methylation or protein vector. Each case carries the bundle's
log-risk, and the page shows the scores only when its loaded case matches, so a rebuilt cohort can
never pair them with another patient.

```
PYTHONPATH=src:<rdata> python scripts/omics_scores.py --data data/tcga_brca --raw data/raw/tcga_brca \
    --extra data/raw/omics --bundle outputs/demo_bundle.pt --out app/omics_scores.json
```

The extra public files (genefu's `pam50.rda`, the MSigDB Hallmark GMT, two cBioPortal clinical
tables, the 450K probe map) are downloaded once into `--extra`; reading the `.rda` needs the
`rdata` package. Licenses and access tiers: `docs/registry.md`.

### PAM50 intrinsic subtype [model inference, experimentally validated on this cohort]

- **Centroids:** Parker et al. 2009 ([10.1200/JCO.2008.18.1370](https://doi.org/10.1200/JCO.2008.18.1370)),
  50 genes × 5 subtypes, from genefu (`data/pam50.rda`, Artistic-2.0; Gendoo et al. 2016). Three
  centroid symbols are renamed to their GENCODE v36 names (CDCA1 → NUF2, KNTC2 → NDC80,
  ORC6L → ORC6); all 50 genes are measured.
- **Normalization:** the hub's log2(TPM + 1); each gene centered on its median over an
  **ER-balanced subset** of this cohort: every ER-negative tumor by IHC and as many ER-positive
  ones drawn at random (seed 0), 466 tumors. The reference population is this TCGA-BRCA cohort,
  not Parker's training set.
- **Call:** Spearman correlation of the tumor's 50 centered values with each centroid; the highest
  wins. The page shows every correlation and the margin from the best to the second best.
- **Validation:** against TCGA's published PAM50 calls (cBioPortal `brca_tcga_pan_can_atlas_2018`,
  column SUBTYPE; Hoadley et al., Cell 2018), on every tumor that has one.

| Centering reference | Tumors compared | Agreement | Cohen's kappa |
|---|---|---|---|
| ER-balanced subset, seed 0 (shipped) | 950 | **94.7%** | 0.92 |
| ER-balanced subset, seeds 1–4 | 950 | 94.1%, 94.6%, 94.7%, 94.2% | |
| Whole cohort (plain median centering) | 950 | 72.5% | 0.63 |

Confusion matrix of the shipped call (rows: published; columns: this call):

| published ↓ / this call → | Luminal A | Luminal B | HER2-enriched | Basal-like | Normal-like |
|---|---|---|---|---|---|
| Luminal A | 451 | 33 | 4 | 0 | 0 |
| Luminal B | 4 | 184 | 0 | 0 | 0 |
| HER2-enriched | 0 | 0 | 72 | 0 | 0 |
| Basal-like | 0 | 0 | 0 | 168 | 0 |
| Normal-like | 6 | 0 | 3 | 0 | 25 |

**How the centering was chosen, honestly.** Plain centering on the whole cohort, as first
specified, was run first: 72.5%. Most of its disagreements were published Luminal A tumors called
Normal-like (76), Luminal B (69) or HER2-enriched (35). TCGA-BRCA is about three quarters
ER-positive, unlike PAM50's training set, and centering on such a cohort shifts calls; Zhao et
al. 2015 (Breast Cancer Res, [10.1186/s13058-015-0520-4](https://doi.org/10.1186/s13058-015-0520-4))
describe exactly this and recommend centering on a subgroup with the training set's make-up. The
ER-balanced reference was chosen after seeing the first result, on the same tumors, so 94.7% is
not an independent test: it shows that the method reproduces TCGA's calls, not how it would do on
another cohort. Two candidates were compared, with no tuning beyond that choice; the other random
draws show how much the reference sample matters. Under the shipped call the main remaining
disagreement is published Luminal A called Luminal B (33 tumors), the boundary the two subtypes
share by design (proliferation). Of the 40 bundled cases, 39 have a published call and 38 agree;
6 calls are borderline (margin under 0.1).

### Pathway, proliferation and immune scores [model inference, implemented]

- **Sets:** the 50 MSigDB Hallmark sets (v2025.1.Hs; Liberzon et al. 2015,
  [10.1016/j.cels.2015.12.004](https://doi.org/10.1016/j.cels.2015.12.004), CC BY 4.0); the 11
  PAM50 proliferation genes (Parker 2009: BIRC5, CCNB1, CDC20, NUF2, CEP55, NDC80, MKI67, PTTG1,
  RRM2, TYMS, UBE2C); immune cytolytic activity, GZMA and PRF1 (Rooney et al. 2015,
  [10.1016/j.cell.2014.12.033](https://doi.org/10.1016/j.cell.2014.12.033)).
- **Method:** z-score averaging (Lee et al. 2008): each gene's log2(TPM + 1) z-scored over the
  1,059 tumors with RNA, the set's mean z-score z-scored again over the cohort. 0 is the cohort
  average; the page shows the cohort percentile on hover.
- **Not validated** as a measure of pathway activity: a score is relative to this cohort, from
  bulk RNA (tumor, stroma and immune cells together).

### Receptor consistency [observed measurements, calibrated cutoffs]

Recorded receptor status from TCGA's clinical data (GDAC Firehose 2016-01-28, cBioPortal
`brca_tcga`): ER and PR by IHC; HER2 per the ASCO/CAP guideline (Wolff et al. 2018: IHC 3+
positive, 0 or 1+ negative, 2+ settled by in situ hybridization). Each measure is compared with it
through the cutoff that best separates recorded positives from negatives in this cohort (highest
sensitivity + specificity; calibrated in-sample, not validated elsewhere):

| Receptor | Measure | Tumors | AUC | Cutoff (cohort percentile) | Sensitivity | Specificity |
|---|---|---|---|---|---|---|
| ER | ESR1 RNA | 1011 | 0.958 | 25 | 0.95 | 0.93 |
| ER | ER-alpha RPPA | 806 | 0.958 | 28 | 0.92 | 0.93 |
| PR | PGR RNA | 1008 | 0.926 | 39 | 0.84 | 0.88 |
| PR | PR RPPA | 803 | 0.843 | 47 | 0.72 | 0.84 |
| HER2 | ERBB2 RNA | 854 | 0.811 | 86 | 0.56 | 0.97 |
| HER2 | HER2 RPPA | 694 | 0.772 | 77 | 0.58 | 0.87 |
| HER2 | ERBB2 copy number (≥ 2× ploidy) | 827 | – | – | 0.57 | 0.98 |

ERBB2 copy number counts as amplified at **at least twice the tumor's ploidy** (its median gene
copy number): a placeholder, by analogy with the ASCO/CAP in situ hybridization ratio of 2.0, not
validated on ASCAT calls. RPPA against RNA (Spearman, 851 tumors): ER-alpha 0.85, PR 0.78, HER2
0.61. Each line on the page names the layer its claim comes from: RNA is not protein, RPPA
measures the whole sample's lysate, IHC the tumor cells.

### Layer cards [model inference]

Per measured layer: the normalization the model input went through (`scripts/prepare_tcga.py`),
the layer's effect on this patient's log-risk compared with a typical patient
(`muffle.explain.modality_contributions` with the cohort offsets), the ten features with the
largest gradient × input, each with its value, its cohort percentile (interpolated between the
cohort's deciles) and the Hallmark sets it belongs to (a CpG through the gene the 450K probe map
places it near), and the layer's own leave-one-hospital-out C-index (`app/results_tcga_brca.json`).
A layer that was not measured says so and what that limits. The what-if masks layers and shows
the risk percentile move.

## Placeholders

- A PAM50 call whose margin to the runner-up is under 0.1 is flagged "borderline".
- ERBB2 amplification at twice the ploidy (above).

## Known failures

- **Copy number:** on its own this layer ranks patients worse than chance on hospitals it never
  saw (C-index 0.485 ± 0.016), a sign of site and batch effects. Its card says so next to its
  contribution.
- **PAM50 depends on the reference population:** plain centering on this cohort agrees with the
  published calls on only 72.5%. A cohort with another ER mix needs its own reference.
- **HER2 by RNA or copy number is weak against the recorded status:** sensitivity 0.56 (RNA) and
  0.57 (copy number) at high specificity; the recorded status mixes IHC and in situ
  hybridization, and amplification calls from ASCAT are not ISH.
- **Feature percentiles are approximate:** interpolated between cohort deciles.
- The bundle's copy-number feature names and the rebuilt cohort's differ in order for a few genes
  with tied variance (neighbouring genes on the same segment); the percentiles are looked up by
  name.

## What it cannot see

Protein level from RNA, single cells or where in the tumor (slides), point mutations (the
genomics workbench), change over time (TCGA holds one sample per patient). A subtype from bulk RNA
is not the IHC surrogate subtype used in the clinic, and nothing here is a treatment
recommendation.

## Planned

Other signatures (recurrence-score-like, immune deconvolution) only from a validated model with a
named reference population; expression distributions per gene across the cohort; methylation of
named promoters (ESR1, BRCA1) with a validated cutoff.

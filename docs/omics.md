# Expression, methylation and protein workbench

The workbench of the TCGA patient files' data layers (`docs/WORKBENCHES.md` §7): what each layer
measured, what the risk model reads from it, a PAM50 subtype call, pathway scores, and whether the
receptor measurements agree with the recorded IHC. Page: `app/workbenches/omics.py`; logic:
`src/muffle/workbench/omics.py` (tests: `tests/test_workbench_omics.py`); scores:
`scripts/omics_scores.py` (round 1) and `scripts/omics_scores_2.py` (round 2: protein pathways,
promoter methylation, immune and stromal) → `app/omics_scores.json`.

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

## Round 2 (2026-10-21): protein pathways, promoter methylation, the immune picture

`scripts/omics_scores_2.py` adds fields to `app/omics_scores.json` (round 1's fields and the
per-case log-risk guard unchanged). It reads the local RPPA and TPM files, streams the 450K
betas from the hub once (tumors and TCGA's 97 normal breast samples; the derived numbers are
cached outside the repo) and ships derived numbers only: scores, percentiles, a gene-level mean
promoter beta, cohort quantiles and correlations.

```
PYTHONPATH=src python scripts/omics_scores_2.py --data data/tcga_brca --raw data/raw/tcga_brca \
    --extra data/raw/omics --scores app/omics_scores.json
```

### Protein pathway activity, RPPA [model inference, implemented]

- **Members:** the ten pathway scores of Akbani et al. 2014 (Nat Commun 5:3887,
  [10.1038/ncomms4887](https://doi.org/10.1038/ncomms4887)), with the antibodies and signs of
  their Supplementary Table 13 (read from the article's supplementary PDF): PI3K/AKT, TSC/mTOR,
  hormone receptor (ER-alpha, its pS118 form, PR), hormone signaling (AR, INPP4B, GATA3, BCL2),
  RTK, cell cycle, DNA damage response, RAS/MAPK, apoptosis and EMT. Negative regulators (PTEN
  and INPP4B in PI3K/AKT; BAD pS112, BCL2, BCL-xL, cIAP in apoptosis; claudin-7 and E-cadherin
  in EMT) are subtracted. Akbani's HER3PY1298 is this file's HER3_pY1289. Each score sits beside
  the genomics workbench's pathway-map group (`genome.PATHWAYS`): PI3K/AKT and TSC/mTOR beside
  PI3K / AKT / mTOR, the two hormone scores beside ER signaling, RTK beside HER2 / RTK, DNA
  damage beside TP53 and DNA repair, RAS/MAPK beside MAP kinase; apoptosis and EMT have none.
- **Method:** Akbani's score up to scale. Each antibody median-centered and divided by its
  standard deviation over the cohort's 854 RPPA tumors, the measured members' mean with the
  negative regulators' sign flipped, z-scored again over the cohort. (Akbani first averaged
  phospho-forms of one protein when they correlated above 0.85; that step is not repeated.)
  Every member is measured in at least half of the tumors, so none is left out.
- **Shown, not scored:** total AKT, p110-alpha, p85, total mTOR, S6 and p70S6K, total HER2,
  EGFR and HER3, Rb and phospho-Rb, p16, c-Myc, beta-catenin, Snail. Ki-67 is not on the array.
- **Protein versus RNA agreement** (Spearman over 851 tumors with both; 93 antibodies; median
  0.22). Highest: ER-alpha 0.85 (ESR1), BCL2 0.81, GATA3 0.79, PR 0.78 (PGR), AR 0.76, INPP4B
  0.73, cyclin B1 0.71, cyclin E1 0.68, ER-alpha pS118 0.64, HER2 0.61 (ERBB2), ZAP-70 0.60, LCK
  0.59. Weak (under 0.3, a placeholder for "weak"): 32 of 37 phospho-site antibodies, expected
  since a phosphorylation is not in the RNA (phospho-AKT S473 0.14, mTOR S2448 0.11, S6 S235/236
  −0.15), and 23 of 56 total-protein antibodies: c-Myc 0.25, RAD50, collagen VI, Snail, ATM,
  BCL-xL, RAD51, CD20 0.19, BAX, p53 0.17 (a mutant p53 accumulates as protein without more
  RNA), p110-alpha 0.14, beta-catenin, cIAP, cleaved caspase-7, total mTOR, Ku80, BRCA2, BID,
  N-cadherin, BAK, total S6, MRE11 and Granzyme B −0.24.
- **Receptors against the recorded status** (round 1, unchanged): ER-alpha RPPA AUC 0.958, HER2
  RPPA 0.772.
- **Queue:** an observed mutation in the genomics map's PI3K / AKT / mTOR genes (PIK3CA, PTEN,
  AKT1, PIK3R1) with the PI3K/AKT score from the 75th percentile (agree, trust moderate) or to
  the 25th (disagree, trust weak); both cutoffs placeholders. The variant's CIViC evidence stays
  in the genomics workbench, for clinician review.

### Promoter methylation [observed betas, placeholder calls]

- **Probes:** from the Illumina HumanMethylation450 v1.2 manifest, each gene's core promoter
  (UCSC_RefGene_Group TSS200 or 1stExon; for RASSF1 the RASSF1A transcript NM_007182, for
  CDKN2A p16INK4a NM_000077), kept where the median beta over TCGA's 97 normal breast samples is
  under 0.2 (placeholder): ESR1 13 of 29 core-promoter CpGs, PGR 11 of 12, BRCA1 12 of 15,
  RASSF1A 9 of 10, GSTP1 3 of 3, p16 1 of 1. Per tumor the mean beta over them.
- **How the rule was chosen, honestly.** The first rule required the probe to lie in the
  manifest's UCSC CpG island (TSS1500, TSS200, 5'UTR or first exon). It called BRCA1
  methylated in 696 of 762 tumors: the manifest's island lies upstream of BRCA1's core
  promoter (the NBR2 side), whose probes (cg19088651, cg08993267, ...) it calls shore, and the
  island probes are methylated in most tumors and normal tissue alike. It also averaged
  RASSF1A's and RASSF1C's promoters together. The core-promoter rule with the normal-breast
  reference replaced it after that result, on the same tumors.
- **Call:** methylated from a mean beta of 0.3 (placeholder). The gene's RNA percentile is shown
  beside it: methylated with RNA at or under the 25th percentile (placeholder) is "consistent
  with silencing", methylated with higher RNA is "not consistent". RASSF1A and p16 get no
  consistency call: the RNA layer reads the whole gene (RASSF1A with RASSF1C, p16 with p14ARF).
- **The check across the cohort** (762 tumors with both):

| Gene | CpGs kept / core promoter | Methylated | RNA percentile, methylated (median) | RNA percentile, unmethylated (median) | Spearman, beta vs RNA |
|---|---|---|---|---|---|
| ESR1 | 13 / 29 | 2 | 11 | 50 | −0.33 |
| PGR | 11 / 12 | 10 | 7 | 51 | −0.36 |
| BRCA1 | 12 / 15 | 13 | 1 | 51 | −0.24 |
| RASSF1 (RASSF1A) | 9 / 10 | 579 | 49 | 52 | −0.09 |
| GSTP1 | 3 / 3 | 222 | 24 | 63 | −0.60 |
| CDKN2A (p16) | 1 / 1 | 40 | 68 | 50 | −0.10 |

  BRCA1 methylation is rare (13 tumors, 1.7%; methylation-specific PCR found 13% of 84 unselected
  tumors, Esteller 2000) and those tumors' BRCA1 RNA sits at the 1st percentile: silencing.
  GSTP1 is methylated in 29% (Esteller 1998: about 30%), with lower RNA. RASSF1A is methylated in
  76% of tumors and p16 in 5%; their gene-level RNA does not follow, as said above.
- **Hypermethylation index** [hypothesis]: the mean beta over the 76,449 autosomal CpG-island
  promoter probes (of 89,258) whose median in normal breast is under 0.2, as a cohort
  percentile over 766 tumors. Read as a CpG island methylator phenotype in the sense of Fang et
  al. 2011 (B-CIMP, [10.1126/scitranslmed.3001875](https://doi.org/10.1126/scitranslmed.3001875));
  this mean is not their classifier and is not validated here.
- **Queue:** a methylated BRCA1 promoter (BRCA1 germline testing and a homologous-recombination
  assay are the clinical tests), and a methylated ESR1 or PGR promoter while the receptor is
  IHC positive. Trust weak (placeholder cutoffs).

### Immune and stromal picture [model inference, implemented]

- **Signatures:** ESTIMATE's 141-gene immune and stromal lists (Yoshihara et al. 2013,
  [10.1038/ncomms3612](https://doi.org/10.1038/ncomms3612), Supplementary Data 1; 140 and 136
  measured) by z-score averaging over the cohort, like the Hallmark scores; the ESTIMATE package
  (GPL-2, single-sample enrichment) is not used. Immune-cell antibodies on the array (LCK,
  ZAP-70, Granzyme B, CD20, CD4, CD45, VAV1, CD38), grouped here, not from a paper, averaged the
  same way.
- **Measured:** the immune signature against cytolytic activity (round 1) 0.87, against the
  stromal signature 0.72 (1,059 tumors), against the immune-cell antibodies 0.55 (851 tumors;
  Spearman). Granzyme B's antibody runs against its RNA (−0.24) and CD20's barely with it (0.19);
  both stay in the predeclared group and are named here.
- **Immune picture:** the RNA immune signature, the immune-cell proteins and each scored
  section's lymphocytes near the front (the slide workbench's numbers computed as its page does:
  the second lymphocyte model where it scored, else the tile head; precomputed per section with
  its method version, so a re-run section falls back to the tile head) read together. A layer
  calls "high" from the 75th percentile and "low" to the 25th (placeholders); a section calls
  "low" when under 5% of its front-band tiles are lymphocytes (the slide workbench's desert
  cutoff, placeholder) and makes no call otherwise, since not a desert is not inflamed. Agree when
  every call is the same, disagree when one is high and another low; a pathologist's stromal TILs
  read (Salgado et al. 2015) settles it. The report's tests-that-disagree list keeps
  `muffle.crosstest`'s own "slide immune versus RNA immune" rule (a desert section against
  cytolytic activity from the 75th percentile); this page names it when it fires and adds no
  second rule.

### ECM3 four-gene score [model inference, implemented; its prognosis a hypothesis]

- **What:** ECM3 is one of four extracellular-matrix expression subtypes of breast cancer
  (Triulzi et al., *PLoS One* 2013,
  [10.1371/journal.pone.0056761](https://doi.org/10.1371/journal.pone.0056761)). Its four-gene
  surrogate is the average expression of **COL1A2, COL5A2, SPARC and LAMA4**. The paper names
  the collagen gene COL1A1 in its Results, Figure 2, Figure S3 and one Discussion passage, and
  COL1A2 in its Methods (the metagene), Figure S5 and its last Discussion paragraph; its qRT-PCR
  assays list COL1A2 (Hs00164099_m1) and no COL1A1 assay, so COL1A2 is used.
- **How:** each gene's log2(TPM + 1) from TCGA-BRCA STAR TPM, z-scored over the model's cohort
  (1,059 tumors), the mean over the four (`muffle.workbench.omics.ecm3_score`); per bundled case
  the score's and each gene's cohort percentile in `app/omics_ecm3.json`
  (`scripts/omics_ecm3.py`, derived numbers only). The release bundle's RNA features hold COL1A2
  alone of the four, hence the offline script. **No cutoff:** the paper's classifier was fitted
  on its own cohorts and the four-gene score was not validated outside them; the page shows the
  file's place in the cohort, never "ECM3" or "not ECM3". A gene a file lacks is named on the
  card; a file without RNA-seq (SYNTHETIC-001) reads "not measured".
- **Hypothesis line:** ECM3 tumors had worse distant-metastasis-free survival only among grade
  III tumors (HR 3.0, 95% CI 1.3–7.0; untreated node-negative patients of two public datasets);
  Tiwari et al. 2020 (the Bhargava lab) found the ECM3 collagen signature mainly at tumor
  borders by infrared imaging (42 tumors, one centre, AUC 0.87, not validated externally).
  Shown as a lead, never a prognosis or a recommendation; a card on the page, never a queue
  item.

## Placeholders

- A PAM50 call whose margin to the runner-up is under 0.1 is flagged "borderline".
- ERBB2 amplification at twice the ploidy (above).
- Round 2: a promoter probe kept under a normal-breast median beta of 0.2; methylated from a mean
  promoter beta of 0.3; RNA low at or under the 25th percentile; protein pathway high from the
  75th, low to the 25th percentile; immune scores high from the 75th, low to the 25th; protein
  against RNA called weak under a Spearman of 0.3 (`omics.PLACEHOLDERS`).

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
- **Protein pathways:** most phospho-site antibodies and 23 of 56 total-protein antibodies agree
  weakly with their gene's RNA; a pathway score is relative to this cohort, read through the
  antibodies the array carries, and not validated as activity.
- **Promoter methylation:** calls at placeholder cutoffs on bulk DNA; the first probe rule (the
  manifest's CpG island) called BRCA1 methylated in 91% of tumors and was replaced (above).
  RASSF1A's and p16's methylation cannot be checked against their RNA here.
- **Immune picture:** the slide side can only say "desert"; the scored sections are few (5 of the
  40 cases) and their lymphocyte reads are not validated on breast by a pathologist.
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
named reference population; expression distributions per gene across the cohort; a validated
promoter-methylation cutoff (methylation-specific PCR or pyrosequencing on the same tumors);
merging phospho-forms of one protein before a pathway score, as Akbani did.

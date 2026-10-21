# Genomics workbench: the tumor's genome as a picture

The tumor-sequencing workbench (`docs/WORKBENCHES.md` §4) beyond its driver list: the
copy-number landscape with a Spot panel per gene, mutation burden and allele fractions, the
predicted effect of each variant, a curated pathway map and the variants over time. Page:
`app/workbenches/genomics.py`; logic: `src/muffle/workbench/genome.py` (the variant browser,
ladder and watchlist stay in `src/muffle/workbench/genomics.py`); Ensembl client:
`src/muffle/report/vep.py`; tests: `tests/test_workbench_genomics.py`. Built 2026-10-20 and 21.

Every finding keeps its evidence type: a copy number, a read count, a call count and a sequenced
variant are **observed**; a rate per megabase is **derived**; a copy-number call is a rule on an
observed number, each cutoff tagged definition, literature or placeholder; an expected allele
fraction, a purity, an AlphaMissense score and a "high in this cohort" are **model inference**; a
CIViC item, a ClinVar classification and a pathway grouping are **hypothesis**, for clinician
review, never a recommendation.

## How the numbers are made

Two offline scripts ship only derived numbers for the 40 bundled TCGA-BRCA cases, keyed by the
case's row in `cohort.npz`, never a barcode. Each case carries the bundle's log-risk and
percentile, and the page shows the numbers only when its loaded case matches (the omics
workbench's guard), so a rebuilt cohort never pairs them with another patient.

```
PYTHONPATH=src python scripts/genomics_scores.py --data data/tcga_brca --raw data/raw/tcga_brca \
    --extra ~/muffle-genomics/raw --bundle outputs/demo_bundle.pt --out app/genomics_cn.json
PYTHONPATH=src python scripts/genomics_effect.py \
    --alphamissense ~/muffle-genomics/raw/AlphaMissense_hg38.tsv.gz \
    --variant "ESR1 D538G" --variant "DNMT3A R882H"
```

`genomics_cn.json` (225 kB): per case the copy number of 231 genes (the model's 200 copy-number
genes, the 12 breast drivers of interest, the pathway map's genes and the 16-gene panel), each
with its cohort percentile; the ploidy estimate; ABSOLUTE purity and ploidy; the burden counts;
and each observed driver's consequence class, GRCh38 position and alleles. Per gene: position
(GENCODE v36) and the cohort's share of each call. `genomics_effect.json` (23 kB): per variant the
Ensembl VEP annotation, the ClinVar classifications and the AlphaMissense score, with the snapshot
date and the Ensembl release (116).

Checks the script runs: the calls it makes equal the model's own copy-number input for 7,993 of
7,999 gene values of the bundled cases (the rest are gene symbols that name several loci: Y_RNA
appears twice in the model's own gene list); `dna_vaf` in the Xena file equals alt / depth of the
per-case read counts (`app/evolution_vaf.json`) for 56 of 56 driver calls; every driver it finds
equals the bundle's mutation list.

## Copy-number landscape [observed copies, placeholder cutoffs]

- **Data:** ASCAT3 gene-level absolute copy number (UCSC Xena GDC hub), 1,029 tumors of the
  model's cohort.
- **Ploidy estimate:** the tumor's median gene-level copy number, rounded, at least 1: the rule
  that built the model's copy-number input (`muffle.data.tcga.copy_number_calls`). ASCAT's own
  ploidy and purity are not in the open gene-level file. ABSOLUTE's purity and ploidy (TCGA
  PanCanAtlas, `TCGA_mastercalls.abs_tables_JSedit.fixed.txt`; Carter et al. 2012,
  [10.1038/nbt.2203](https://doi.org/10.1038/nbt.2203); Taylor et al. 2018,
  [10.1016/j.ccell.2018.03.007](https://doi.org/10.1016/j.ccell.2018.03.007)) are shown beside it,
  for 40 of 40 bundled cases.
- **Calls** (`genome.cn_call`, the same rule): deep deletion = 0 copies (definition); loss = fewer
  than the ploidy, gain = more but under twice it, amplification = at least twice the ploidy (all
  three **placeholders**; amplification by analogy with the ASCO/CAP in situ hybridization ratio
  of 2.0, the omics workbench's rule). Five levels in the format of GISTIC's thresholded calls
  (Mermel et al. 2011); the cutoffs are this project's.
- **Check against HER2 status** (the omics workbench's, reused): ERBB2 at this cutoff against
  recorded HER2 status, sensitivity 0.57, specificity 0.98 in this cohort.
- **When the two ploidy estimates disagree** (one at least 1.5 times the other, a placeholder),
  the page warns and offers the calls relative to ABSOLUTE's ploidy. It fires for 7 of the 40
  bundled cases; in case 49 the median rule gives a ploidy of 1, which would make every 2-copy
  gene an amplification. ERBB2 is amplified in 6 bundled cases by the median rule and 5 by
  ABSOLUTE's ploidy (case 61 changes: 6 copies at ploidy 3, or 3.35).
- **Percentile:** copies relative to ploidy, mid-rank among the cohort's tumors (ties split, so
  equal copy numbers share a percentile).
- **Chart:** genes in genome order, evenly spaced (not to scale); default view the breast drivers
  and pathway genes, optional all 231. The model's 200 genes cluster in a few amplicons (8p11-12,
  8q24, 11q13, 17q), which is why they are not the default view.
- **Spot panel per gene:** copies, call and its cutoff with its tag, percentile, the cohort's share
  of the same call, neighbors within 10 Mb and how many share the call (a focal versus broad hint;
  segments would settle it), CIViC items for the gene's amplification, gain, loss or deletion in
  breast cancer (each marked whether its direction matches this call), the expression workbench's
  RNA and protein percentiles from the model's inputs, its pathway, the observed variants in it,
  review marks (`finding_key` kind `cn`).
- **Consistency lines:** the omics workbench's ERBB2-versus-HER2 line itself
  (`omics.receptor_lines`), a line if the two workbenches read different ERBB2 copies, and for
  amplified or deeply deleted genes their RNA percentile against the cohort median (placeholder).

## Mutation burden [observed count, derived rate]

- **Count:** every somatic call in GDC's open masked file (Xena, `somaticmutation_wxs`) for the
  tumor, with the coding and protein-altering counts beside it; 943 sequenced tumors of the
  cohort, median 44 calls.
- **Rate:** calls / 38 Mb, the exome size Chalmers et al. 2017 used for TCGA
  ([10.1186/s13073-017-0424-2](https://doi.org/10.1186/s13073-017-0424-2): "We used 38 Mb as the
  estimate of the exome size", with TCGA's somatic calls as the raw count). Cohort median 1.16
  per Mb.
- **High in this cohort:** the top decile (placeholder); 2 bundled cases.
- **10 per Mb** (KEYNOTE-158, Marabelle et al. 2020,
  [10.1016/S1470-2045(20)30445-9](https://doi.org/10.1016/S1470-2045(20)30445-9)) was defined on the
  FoundationOne CDx panel in ten non-breast cancers: named on the page, not applied. No bundled
  case reaches it.

## Allele fractions [observed reads, model-inference fit]

For each observed driver of a TCGA case: alt reads / depth from the per-case GDC MAF
(`app/evolution_vaf.json`, already shipped by the Evolution view), the Wilson 95% interval, the
gene's copies, ABSOLUTE's purity, and the clonal range: the fraction a clonal mutation would show
with one mutant copy to all of them, purity × m / (purity × copies + 2 (1 − purity)) (the
ABSOLUTE relation, Carter et al. 2012; normal cells diploid). Of the 56 driver calls, 45 sit within
their clonal range, 10 below it (possibly subclonal, or less tumor at that spot) and 1 above it.
The synthetic record states no allele fraction.

## Predicted effect [three evidence types, kept apart]

- **Detected (observed):** the call and its consequence on the MANE Select transcript (Ensembl
  VEP REST, release 116; McLaren et al. 2016,
  [10.1186/s13059-016-0974-4](https://doi.org/10.1186/s13059-016-0974-4)). Protein positions follow
  MANE and can differ from the call's own transcript by a residue (GATA3 A441Wfs*33 is
  p.Ala442TrpfsTer33 on MANE).
- **Interpreted (hypothesis):** CIViC items (as before) and ClinVar's germline clinical
  significance and somatic oncogenicity as Ensembl serves them with the co-located dbSNP record
  (Landrum et al. 2018, [10.1093/nar/gkx1153](https://doi.org/10.1093/nar/gkx1153)); 18 of 49
  variants have a ClinVar record. COSMIC and HGMD identifiers that Ensembl returns alongside are
  dropped (COSMIC is excluded from this project).
- **Predicted (model inference):** AlphaMissense (Cheng et al. 2023,
  [10.1126/science.adg7492](https://doi.org/10.1126/science.adg7492)) for missense changes only,
  read from the hg38 table (Zenodo [10.5281/zenodo.10813168](https://doi.org/10.5281/zenodo.10813168));
  Ensembl's own AlphaMissense annotation agrees for 20 of 20 changes found in the table. Its
  classes, read off the whole table: likely benign up to 0.34, likely pathogenic from 0.564. Of
  21 missense changes, 16 likely pathogenic, 2 ambiguous, 3 likely benign. PIK3CA H1047R, an
  established oncogenic hotspot (ClinVar somatic: oncogenic; CIViC level A), scores 0.538,
  ambiguous: the predictor scores pathogenicity from structure and population frequency, not
  somatic oncogenicity, which is why prediction and interpretation are never merged. "Not
  approved for any clinical use" (its authors) is on the page.
- The ladder's rung 3 ("predicted effect") now carries AlphaMissense and the VEP consequence as
  model inference when the snapshot has them; otherwise CIViC's own wording, as before.
- A variant missing from the snapshot (an imported result) is looked up live at Ensembl by name
  only ("ESR1 D538G" → `ESR1:p.Asp538Gly`), cached for a day; if Ensembl can't be reached the page
  says it has no lookup, never a guess.

## Pathway map [hypothesis, sources checked]

Seven pathways, 30 genes: ER signaling (ESR1, GATA3, FOXA1, TBX3, MYC), HER2 / RTK (ERBB2, EGFR,
FGFR1), PI3K / AKT / mTOR (PIK3CA, PTEN, AKT1, PIK3R1), cell cycle (CCND1, CDK4, CDK6, RB1,
CDKN2A), TP53 and DNA repair (TP53, MDM2, ATM, BRCA1, BRCA2, PALB2), MAP kinase (NF1, KRAS, MAP3K1,
MAP2K4), chromatin (ARID1A, KMT2C). The grouping is this workbench's curation; each pathway lists
what its sources report, each statement checked in the paper's full text (PMC), and every PMID and
DOI checked against PubMed on 2026-10-20 (`tests/test_workbench_genomics.py` re-checks them when
online):

| Source | PMID | DOI |
|---|---|---|
| Cancer Genome Atlas Network 2012, Nature 490:61-70 | 23000897 | 10.1038/nature11412 |
| Sanchez-Vega et al. 2018, Cell 173:321-337 | 29625050 | 10.1016/j.cell.2018.03.035 |
| Razavi et al. 2018, Cancer Cell 34:427-438 | 30205045 | 10.1016/j.ccell.2018.08.008 |
| Nik-Zainal et al. 2016, Nature 534:47-54 | 27135926 | 10.1038/nature17676 |
| Pereira et al. 2016, Nat Commun 7:11479 | 27161491 | 10.1038/ncomms11479 |

Each node shows this tumor's observed alteration (mutated; amplification, gain, loss or deep
deletion; not altered; not measured, which is unknown and never normal), with a ring for the copy
number of a mutated gene. Click a node for the gene's Spot panel. Per pathway: its sources and the
CIViC items (breast, accepted) that name one of its genes, strongest level first, for clinician
review; an item for a gene is not an item for this tumor's change. Arrows of signaling are not
drawn. Review marks: `finding_key` kind `pathway`.

## Variants over time [observed; blank = not looked]

One row per variant, one column per sample in time order: tumor sequencing (the record's and
imported ones, any test whose workbench is `mutations`, added with `workspace.add_version`) and
the synthetic patient's ctDNA series (`muffle.timeline.CTDNA`, #94; labeled synthetic; a file
without one says "not yet available"), with each blood variant's origin by the ctDNA monitor's own
rule (DNMT3A R882H: possible clonal hematopoiesis). A cell is "detected" with its allele fraction; "not detected"
only where the sample looked (its stated panel covered the gene, or the ctDNA assay tracked the
variant, with its detection limit); blank otherwise: not re-sequenced or not covered, never
"absent". The synthetic record names the variants its sequencing found, not its panel, so other
variants are blank in that column. Each variant links to the Evolution view's escape-route rows
for its gene (`evolution.hypothesis_set`), raised or not, with the reason.

## Patient overview

`genomics.summary()` adds a "Copy number" card (the amplified and deeply deleted breast drivers
and pathway genes, both ploidies) and a "Mutation burden" card for a TCGA file; `genomics.queue()`
adds a look-here item per amplified or deeply deleted driver or pathway gene (ERBB2
amplification weighs 2, the rest 1; trust weak when the ploidies disagree) and one for two ploidy
estimates that disagree, even when CIViC is not loaded. "Open" lands on the gene's Spot panel
(`focus={"gene": ...}`). The numbers are matched to the file by the log-risk it carries.

## Search, marks, exports

Search in plain words: "amplified", "deleted", "loss", "gain", a gene symbol, a pathway ("PI3K
pathway"), "high burden"; anything else gets "not in these views" and the workbench that could
answer. Marks: kinds `cn` (a gene) and `pathway` (a name) added to `workspace.FINDING_KINDS`.
Exports: the Markdown report gains the genome sections (with every placeholder named and the marks
on them), plus the copy-number table (CSV) and all genome findings with marks and provenance
(JSON). The method card lists every rule, predictor and cutoff with its source, tag and status.

## Placeholders

Loss, gain and amplification cutoffs; the top-decile "high burden"; the 1.5-fold ploidy
disagreement flag; the cohort median as the line for copy number against RNA.

## What it cannot see

Segments (arm-level versus focal changes), allele-specific copy number and loss of
heterozygosity, a mutation's copy count, purity within the sample (ABSOLUTE gives one number),
germline variants, genes outside the panel and the views' 231 genes, a predicted effect for
truncating, splice or in-frame changes, and anything that changed after the one TCGA sample.

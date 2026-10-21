# Tumor evolution and treatment evidence (the Evolution view)

Parts two and three of [`VISION.md`](VISION.md) for breast cancer, built on 2026-10-20: a cited
table of the escape routes a tumor is known to take after a given context, the per-patient "what
to watch next" set drawn from it, the record's events over time, clonal order from allele
fractions, and recruiting trials that mention the patient's observed genes. It opens from every
patient file's **Evolution** view (next to Report, Tests and Timeline); the genomics workbench's
resistance watchlist and the report's "Evolutionary hypotheses" line link to it.

Everything in it is evidence and hypothesis for clinician review: nothing is advice and nothing is
a regimen. Each section carries its label: the record's events are **observed**, clonal order is
**model inference** (arithmetic on allele fractions, with its assumptions stated), and every watch
item, trial and literature finding is a **hypothesis**. Status: implemented; the hypotheses are not
validated predictions (no outcome has been checked against them).

Code: `src/muffle/evolution.py` (table, hypothesis set, events, clonal order, export),
`src/muffle/report/trials.py` (ClinicalTrials.gov), `app/workbenches/evolution.py` (the view),
`scripts/make_evolution_vaf.py` and `scripts/refresh_trials.py` (the two bundled data files),
`tests/test_evolution.py`.

## What the view shows

1. **The record over time** (observed): diagnosis, treatment starts, imaging (progression and new
   sites flagged), sequencing and tumor-marker values (rises flagged by the record's own alerts) on
   the file's month axis, up to the report version being viewed. The record holds treatment starts
   only, so no stop is drawn. A TCGA file has one undated sample and says so instead of drawing an
   empty chart.
2. **What to watch next** (hypothesis): the table rows this file raises, ranked. A row is raised
   when a recorded treatment belongs to its class (letrozole is an aromatase inhibitor), when its
   gene is already observed, or, for rows without a treatment context, when its driver is observed
   or its receptor status matches. A receptor status the file does not give makes the row
   conditional ("applies if HER2-positive: not recorded in this file"); a known mismatch drops it.
   **Where the receptor status comes from** (observed): the record's own diagnosis ("HR+",
   "HER2−"); when the record has none, as in every TCGA file, the ER, PR and HER2 status the
   Clinical documents workbench (`src/muffle/workbench/documents.py`) reads in the file's
   documents: the case's TCGA-Reports pathology report, or a report imported in the session. The
   why line names the document ("hormone-receptor-positive observed in document
   TCGA-A2-A0CW.7D1C…"), and a note gives what it states. A document states hormone-receptor
   positive when it states ER or PR positive and negative when it states both negative; ER or PR
   negative alone settles neither, and an IHC score, an ISH result or "equivocal" is never turned
   into a status. When the record and a document disagree, the record's status is used and the
   document is named beside it ("in the record (document import-1 states otherwise)"); when
   documents disagree with each other, or one report states both (two specimens, or a misread),
   none is picked and the rows that need it stay conditional. These are rule matches, not a
   pathologist's read: a note gives the rules' precision on 481 held-out TCGA reports (ER 95%, PR
   93%, HER2 81% with documents rules v2). With those rules, 15 of the 38 bundled reports settle
   the hormone-receptor status and 14 the HER2 status; the other files stay conditional. Rules v1
   read case 545's report as HER2 negative and positive (its synoptic form's answers slid a row)
   and case 58's "weakly positive (2+)" as HER2-positive; v2 reads case 545 as negative and
   leaves case 58 unsettled (`docs/documents.md`).
   TCGA files record no treatment: "No treatment recorded; these hypotheses assume none." Every row
   not raised is listed with the reason. The order is a fixed rule, not a probability: two points
   for a recorded treatment of the row's class, one for an observed driver, one for a matching
   receptor status; then the most recent matching treatment; then the strength of the evidence.
   Each item shows why it is raised, the frequency its lead source reports with that source's
   cohort, the test that would detect it, when it would matter, the evidence for and against with
   PubMed links, and the CIViC items that exist for the event. A caveat that fits this file is
   marked: SYNTHETIC-001's only aromatase inhibitor was adjuvant letrozole, and Schiavon et al.
   found ESR1 mutations rarely acquired during adjuvant aromatase-inhibitor therapy.
3. **Clonal order from allele fractions** (model inference), for the TCGA cases: each driver
   call's allele fraction from the GDC open-access read counts, with a 95% Wilson interval, and its
   gene's total copy number (ASCAT3, gene level). Assuming each mutation sits on one copy of its
   gene, a tumor-cell fraction is at least copies × allele fraction whatever the purity, so two
   variants whose lower bounds sum past 100% of cells must share a lineage (the higher came first);
   otherwise they may also sit in separate subclones. Overlapping intervals cannot be ordered;
   different copy numbers at the two genes break the comparison. ASCAT purity is not in the local
   data, so the panel says "allele fraction only, purity unknown" and calls no variant clonal. The
   consistent orderings are listed as alternatives, never one tree. SYNTHETIC-001's record names
   its variant without an allele fraction, and the panel says that instead of drawing an empty
   chart.
4. **Trials that mention this patient's observed markers** (hypothesis): ClinicalTrials.gov API v2
   with the condition "breast cancer", the term "<GENE> mutation" for each observed gene, and the
   statuses recruiting or not yet recruiting (a bare gene symbol also matches the registry's
   synonyms: "ESR1" brings every estrogen-receptor trial). Only gene names leave the machine. The
   answer is cached on disk for a day; when the registry can't be reached, an older cache, then the
   bundled snapshot (`app/trials_snapshot.json`, with its date and ClinicalTrials.gov's data
   timestamp) answer, and the view says which. A trial that mentions a gene is not a match:
   eligibility is not assessed here. The registry is today's, not the report version's.
5. **Review tools**: search across the hypotheses (a gene, a drug class, a test, a source; a gene
   the table has no row for gets "nothing is said about it here"), agree / disagree / second-look
   marks and pins on each hypothesis and trial under `workspace.finding_key(pf, "evolution", event
   or "trial", PMID or NCT number)` (they join the report's review list and export), and a
   one-page Markdown export with every source.

## How the table was built

- Starting points from the brief (Razavi 2018, Bertucci 2019, Angus 2019, Lefebvre 2016,
  Schiavon 2015, Wander 2020, PADA-1, SERENA-6, Razavi 2019) and the papers their topics lead to.
  Each was looked up on PubMed through NCBI E-utilities on 2026-10-20 and its abstract read; each
  row states only what the abstract reports, with the cohort and the frequency it gives (or "not
  stated in the abstract"). `tests/test_evolution.py` checks every PMID's DOI against PubMed again
  whenever the network allows.
- Not used: the TCGA Network's 2012 abstract gives no TP53 frequency per subtype, so the TP53 row
  cites Dumay et al. and Bertheau et al.; Angus et al.'s abstract does not name its six drivers,
  so it supports only the general statement. No candidate source failed verification, so no row
  was dropped.
- Contexts use drug classes: aromatase inhibitor (letrozole, anastrozole, exemestane), SERM
  (tamoxifen, toremifene), SERD (fulvestrant, elacestrant, camizestrant, imlunestrant,
  giredestrant), CDK4/6 inhibitor (palbociclib, ribociclib, abemaciclib), PI3Kα inhibitor
  (alpelisib, inavolisib, taselisib), PARP inhibitor and platinum; "endocrine therapy" is the
  first three.
- CIViC (CC0) items are matched to each event by its molecular profile (`civic` in each row) in
  breast cancer, strongest level first; the counts below come from the nightly table of
  2026-10-19.

### Constraints the view applies

- **Drivers do not revert here.** An observed driver stays in the file; a later sample that misses
  it is read as another place, too little tumor DNA or another lineage. Juric et al. 2015 found
  primary-tumor PIK3CA mutations no longer detected at progression in 2 of 7 patients. A BRCA1/2
  reversion is a new secondary mutation, not the loss of the first (Waks et al. 2020).
- **Metastases do not regress in the record.** A recorded site stays a site the disease reached,
  even after it responds (a rule of this view, not a finding).
- **A section or one biopsy is not the tumor.** Multiregion sequencing found subclonal
  diversification with spatial patterns and subclonal targetable mutations in 13 of 50 primary
  breast cancers (Yates et al. 2015); a single biopsy is a snapshot (Gerstung et al. 2020).
- **Blood is not only tumor.** 53.2% of cell-free DNA mutations in patients with cancer had
  features of clonal hematopoiesis (Razavi et al. 2019): a ctDNA variant needs matched white-cell
  sequencing before it counts as the tumor's.
- **Order is not fixed.** PIK3CA, TP53, PTEN, BRCA2 and MYC arose early in some tumors and late in
  others (Yates et al. 2015); in triple-negative cancers TP53, PIK3CA and PTEN were usually
  clonally dominant but not always founders (Shah et al. 2012).
- **A cohort's frequency is not this patient's probability** (a rule of this view).

## The table

| # | Context | Event | Lead frequency (cohort) | Detected by |
|---|---|---|---|---|
| 1 | under aromatase inhibitor; hormone-receptor-positive | ESR1 ligand-binding-domain mutation | 36.4% (16 of 44) when the aromatase inhibitor was first given for metastatic disease (Schiavon et al. 2015) | ctDNA with matched white-cell sequencing; every 2 to 3 months in SERENA-6. Or sequencing of a progressing lesion |
| 2 | under SERD; hormone-receptor-positive | New ESR1 mutation (notably Y537S) under fulvestrant | not stated in the abstract (O'Leary et al. 2018 (PALOMA-3)) | ctDNA with matched white-cell sequencing, compared with an earlier sample |
| 3 | under SERD; hormone-receptor-positive; observed ESR1 | ESR1 F404 mutation in cis with an activating ESR1 mutation | 3 of 69 (4%) (Kingston et al. 2024) | ctDNA covering ESR1 codon 404, with matched white-cell sequencing |
| 4 | under CDK4/6 inhibitor; hormone-receptor-positive | RB1 loss-of-function mutation | 6 of 127 (4.7%) (O'Leary et al. 2018 (PALOMA-3)) | ctDNA with matched white-cell sequencing; or sequencing of a progressing lesion |
| 5 | under CDK4/6 inhibitor; hormone-receptor-positive | FAT1 loss-of-function mutation | not stated in the abstract (Li et al. 2018) | Sequencing of a progressing lesion with a panel that covers FAT1 (the TCGA driver panel in this app does not) |
| 6 | under CDK4/6 inhibitor; hormone-receptor-positive | Activating AKT1 alteration | the eight mechanisms together in 66% of resistant tumors (Wander et al. 2020) | ctDNA with matched white-cell sequencing; or sequencing of a progressing lesion |
| 7 | under CDK4/6 inhibitor or PI3Kα inhibitor; hormone-receptor-positive | PTEN loss | 25% of patients with resistance (Razavi et al. 2020) | ctDNA for PTEN mutations, with matched white-cell sequencing; a biopsy for PTEN copy loss or lost expression |
| 8 | under PARP inhibitor or platinum; observed BRCA1 or BRCA2 | BRCA1/2 reversion (a secondary mutation restoring the protein) | 60% of patients (Harvey-Jones et al. 2024) | ctDNA with matched white-cell sequencing; RAD51 foci on a biopsy for restored homologous recombination |
| 9 | under aromatase inhibitor or SERM or SERD; hormone-receptor-positive | Activating ERBB2 (HER2) mutation | 6.19% of samples (Pearson et al. 2020) | ctDNA with matched white-cell sequencing; or sequencing of a progressing lesion |
| 10 | under aromatase inhibitor or SERM or SERD; hormone-receptor-positive | NF1 loss-of-function mutation | 8.10% of samples (Pearson et al. 2020) | ctDNA with matched white-cell sequencing; or sequencing of a progressing lesion |
| 11 | under aromatase inhibitor or SERM or SERD; hormone-receptor-positive | FGFR pathway alteration (FGFR1, FGFR2 or FGF3 amplification; FGFR2 mutation) | 24 of 60 (40%) after resistance; 12 of the 24 acquired or enriched (Mao et al. 2020) | Sequencing of a progressing lesion (or ctDNA) that reports amplifications and FGFR2 mutations |
| 12 | under aromatase inhibitor or SERM or SERD; hormone-receptor-positive | ESR1 fusion (a rearrangement that loses the ligand-binding domain) | at least 1% of metastatic breast cancers (a lower bound), at least 10 times enriched in ctDNA (Hartmaier et al. 2018) | Sequencing able to call rearrangements (the authors used mate-pair, RNA and targeted DNA sequencing); a test for ESR1 point mutations alone does not report them |
| 13 | under aromatase inhibitor or SERM or SERD; hormone-receptor-positive | ARID1A inactivating mutation | 'high frequency' (no rate in the abstract) (Xu et al. 2020) | ctDNA with matched white-cell sequencing; or sequencing of a progressing lesion |
| 14 | hormone-receptor-positive | Loss of ER positivity in a metastasis (receptor conversion) | 22.5% (95% CI 16.4 to 30.0%) (Schrijver et al. 2018) | IHC for ER (and PR, HER2) on a biopsy of a new or progressing lesion |
| 15 | any breast cancer | HER2 status change in a metastasis (gain or loss) | negative to positive 9.5% (95% CI 7.4 to 12.1%); positive to negative 21.3% (14.3 to 30.5%) (Schrijver et al. 2018) | IHC and in situ hybridization for HER2 on a biopsy of a new lesion |
| 16 | hormone-receptor-positive, HER2-negative | Drivers mutated more often in metastatic than in early HR-positive, HER2-negative disease | ESR1 mutated or amplified in 27 HR-positive, HER2-negative metastatic cancers (19%) (Lefebvre et al. 2016) | ctDNA with matched white-cell sequencing; or a biopsy of a metastasis with a panel covering these genes |
| 17 | observed TP53 | TP53 mutation: frequent in basal-like and HER2-amplified tumors | luminal 26%, basal 88% (Dumay et al. 2013) | IHC for ER, PR and HER2, or an expression subtype from a validated model, to place the tumor |
| 18 | HER2-positive; observed PIK3CA | PIK3CA mutation in HER2-positive disease: fewer complete responses to HER2-targeted therapy | 23% of HER2-positive tumors (Majewski et al. 2015) | HER2 status by IHC and in situ hybridization, which decides whether this row applies; the PIK3CA mutation itself is already observed by tumor sequencing |

### 1. ESR1 ligand-binding-domain mutation
- **Context:** under aromatase inhibitor; hormone-receptor-positive · row `esr1-ai` · strongest evidence: randomized trials
- **Detected by:** ctDNA with matched white-cell sequencing; every 2 to 3 months in SERENA-6. Or sequencing of a progressing lesion
- **When it would matter:** During aromatase-inhibitor therapy for metastatic disease, before progression: the setting in which PADA-1 and SERENA-6 looked for it
- **What the sources report:**
  - ESR1 mutations were found only in ER-positive patients previously exposed to an aromatase inhibitor, and were commonly selected by therapy for metastatic disease. Cohort: 171 women with advanced breast cancer; ctDNA by digital PCR; frequency: 36.4% (16 of 44) when the aromatase inhibitor was first given for metastatic disease. Schiavon et al. 2015, *Sci Transl Med* ([PMID 26560360](https://pubmed.ncbi.nlm.nih.gov/26560360/))
  - Plasma ESR1 mutations were associated with acquired resistance to a prior aromatase inhibitor. Cohort: baseline plasma of two phase 3 trials (SoFEA, PALOMA-3); frequency: 39.1% (63 of 161) in SoFEA; 25.3% (91 of 360) in PALOMA-3. Fribbens et al. 2016, *J Clin Oncol* ([PMID 27269946](https://pubmed.ncbi.nlm.nih.gov/27269946/))
  - Ligand-binding-domain mutations (Y537S, Y537N, D538G) drove ER-dependent transcription without hormone and reduced the efficacy of ER antagonists. Cohort: two cohorts of metastatic ER-positive tumors; frequency: 14 of 80. Toy et al. 2013, *Nat Genet* ([PMID 24185512](https://pubmed.ncbi.nlm.nih.gov/24185512/))
  - Activating ligand-binding-domain mutations, all in patients treated with anti-estrogens and estrogen deprivation. Cohort: 11 patients with ER-positive metastatic breast cancer (exome and transcriptome); frequency: 6 of 11. Robinson et al. 2013, *Nat Genet* ([PMID 24185510](https://pubmed.ncbi.nlm.nih.gov/24185510/))
  - A rising ESR1 mutation in blood during first-line aromatase inhibitor plus palbociclib; the randomized switch to fulvestrant plus palbociclib before progression gave a median PFS of 11.9 vs 5.7 months. Cohort: randomized phase 3: 1,017 monitored, 172 randomized; frequency: 279 of 1,017 (27%) developed a rising ESR1 mutation. Bidard et al. 2022 (PADA-1), *Lancet Oncol* ([PMID 36183733](https://pubmed.ncbi.nlm.nih.gov/36183733/))
  - ESR1 mutations are the most common mechanism of acquired resistance to an aromatase inhibitor plus a CDK4/6 inhibitor; found by ctDNA every 2 to 3 months, the randomized switch to camizestrant gave a median PFS of 16.0 vs 9.2 months. Cohort: randomized phase 3: 3,256 tested; frequency: 315 of 3,256 tested were eligible and randomized (not a mutation rate). Bidard et al. 2025 (SERENA-6), *N Engl J Med* ([PMID 40454637](https://pubmed.ncbi.nlm.nih.gov/40454637/))
  - ESR1 activating mutations expanded in number and allele fraction during alpelisib plus an aromatase inhibitor and were associated with resistance. Cohort: phase I/II trial, 44 evaluable patients, tumor and plasma; frequency: not stated in the abstract. Razavi et al. 2020, *Nat Cancer* ([PMID 32864625](https://pubmed.ncbi.nlm.nih.gov/32864625/))
- **Against or limits:**
  - Rarely acquired during adjuvant aromatase-inhibitor therapy: 5.8% (3 of 52) when the first exposure was adjuvant, and 0 of 32 biopsies after progression on an adjuvant aromatase inhibitor (an independent cohort). Schiavon et al. 2015, *Sci Transl Med* ([PMID 26560360](https://pubmed.ncbi.nlm.nih.gov/26560360/))
  - Monitoring and switching were studied during first-line aromatase inhibitor plus palbociclib for ER-positive, HER2-negative advanced disease; other settings are outside the trial. Bidard et al. 2022 (PADA-1), *Lancet Oncol* ([PMID 36183733](https://pubmed.ncbi.nlm.nih.gov/36183733/))
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 14: ESR1 Mutation (Elacestrant, level A, sensitivity/response); PIK3CA Mutation OR RB1 Mutation OR ESR1 Mutation (Fulvestrant,Palbociclib, level B, resistance); ESR1 D538G (Letrozole,Palbociclib, level C, sensitivity/response); ESR1 D538G (Hormone Therapy, level D, resistance) …

### 2. New ESR1 mutation (notably Y537S) under fulvestrant
- **Context:** under SERD; hormone-receptor-positive · row `esr1-serd` · strongest evidence: trial cohorts or meta-analyses
- **Detected by:** ctDNA with matched white-cell sequencing, compared with an earlier sample
- **When it would matter:** At progression on fulvestrant, with or without a CDK4/6 inhibitor; in PALOMA-3 it was common in patients progressing later and uncommon in those progressing early
- **What the sources report:**
  - Paired baseline and end-of-treatment ctDNA: new driver mutations emerged in PIK3CA and ESR1 after fulvestrant with or without palbociclib, in particular ESR1 Y537S; acquired mutations from fulvestrant are a major driver of resistance to the combination. Cohort: 195 patients with paired ctDNA; frequency: not stated in the abstract. O'Leary et al. 2018 (PALOMA-3), *Cancer Discov* ([PMID 30206110](https://pubmed.ncbi.nlm.nih.gov/30206110/))
- **Against or limits:**
  - Evolution of driver mutations was uncommon in patients progressing early on palbociclib plus fulvestrant. O'Leary et al. 2018 (PALOMA-3), *Cancer Discov* ([PMID 30206110](https://pubmed.ncbi.nlm.nih.gov/30206110/))
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 14: ESR1 Mutation (Elacestrant, level A, sensitivity/response); PIK3CA Mutation OR RB1 Mutation OR ESR1 Mutation (Fulvestrant,Palbociclib, level B, resistance); ESR1 D538G (Letrozole,Palbociclib, level C, sensitivity/response); ESR1 D538G (Hormone Therapy, level D, resistance) …

### 3. ESR1 F404 mutation in cis with an activating ESR1 mutation
- **Context:** under SERD; hormone-receptor-positive; observed ESR1 · row `esr1-f404` · strongest evidence: trial cohorts or meta-analyses
- **Detected by:** ctDNA covering ESR1 codon 404, with matched white-cell sequencing
- **When it would matter:** Under fulvestrant once an activating ESR1 mutation is present
- **What the sources report:**
  - Novel ESR1 F404 mutations (F404L, F404I, F404V) were acquired in cis with activating ESR1 mutations; compound mutants were resistant to fulvestrant in cell models. Cohort: PlasmaMATCH cohort A: fulvestrant for activating ESR1 mutations in ctDNA; 69 patients with baseline and end-of-treatment ctDNA; frequency: 3 of 69 (4%). Kingston et al. 2024, *Cancer Discov* ([PMID 37982575](https://pubmed.ncbi.nlm.nih.gov/37982575/))
- **Against or limits:** none in these abstracts
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 0

### 4. RB1 loss-of-function mutation
- **Context:** under CDK4/6 inhibitor; hormone-receptor-positive · row `rb1-cdk46` · strongest evidence: trial cohorts or meta-analyses
- **Detected by:** ctDNA with matched white-cell sequencing; or sequencing of a progressing lesion
- **When it would matter:** At progression on a CDK4/6 inhibitor (after 5, 8 and 13 months in Condorelli et al.'s three patients)
- **What the sources report:**
  - RB1 mutations emerged only in the palbociclib plus fulvestrant arm, in a minority of patients. Cohort: 195 patients with paired ctDNA; frequency: 6 of 127 (4.7%). O'Leary et al. 2018 (PALOMA-3), *Cancer Discov* ([PMID 30206110](https://pubmed.ncbi.nlm.nih.gov/30206110/))
  - Acquired RB1 mutations in ctDNA after a CDK4/6 inhibitor, absent from the specimens taken before it. Cohort: 3 patients with metastatic breast cancer; frequency: 3 patients (a case series). Condorelli et al. 2018, *Ann Oncol* ([PMID 29236940](https://pubmed.ncbi.nlm.nih.gov/29236940/))
  - Loss-of-function mutations in FAT1 and RB1 were linked to CDK4/6-inhibitor resistance. Cohort: 348 ER-positive breast cancers treated with CDK4/6 inhibitors; frequency: not stated in the abstract. Li et al. 2018, *Cancer Cell* ([PMID 30537512](https://pubmed.ncbi.nlm.nih.gov/30537512/))
  - RB1 loss was one of eight resistance mechanisms. Cohort: exome sequencing of 59 tumors exposed to CDK4/6 inhibitors; frequency: the eight mechanisms together in 66% of resistant tumors. Wander et al. 2020, *Cancer Discov* ([PMID 32404308](https://pubmed.ncbi.nlm.nih.gov/32404308/))
  - Some tumors acquired RB loss at progression. Cohort: serial biopsies and rapid autopsies, ribociclib plus letrozole; frequency: not stated in the abstract. Costa et al. 2020, *Cancer Discov* ([PMID 31594766](https://pubmed.ncbi.nlm.nih.gov/31594766/))
- **Against or limits:**
  - A minority event: 4.7% of patients on palbociclib plus fulvestrant. O'Leary et al. 2018 (PALOMA-3), *Cancer Discov* ([PMID 30206110](https://pubmed.ncbi.nlm.nih.gov/30206110/))
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 3: PIK3CA Mutation OR RB1 Mutation OR ESR1 Mutation (Fulvestrant,Palbociclib, level B, resistance); RB1 Loss-of-function (Palbociclib, level D, resistance); RB1 M695FS*26 (Palbociclib, level D, resistance)

### 5. FAT1 loss-of-function mutation
- **Context:** under CDK4/6 inhibitor; hormone-receptor-positive · row `fat1-cdk46` · strongest evidence: clinical cohorts
- **Detected by:** Sequencing of a progressing lesion with a panel that covers FAT1 (the TCGA driver panel in this app does not)
- **When it would matter:** At progression on a CDK4/6 inhibitor
- **What the sources report:**
  - FAT1 loss raised CDK6 through the Hippo pathway (YAP and TAZ), and loss-of-function FAT1 mutations were linked to CDK4/6-inhibitor resistance. Cohort: 348 ER-positive breast cancers treated with CDK4/6 inhibitors; frequency: not stated in the abstract. Li et al. 2018, *Cancer Cell* ([PMID 30537512](https://pubmed.ncbi.nlm.nih.gov/30537512/))
- **Against or limits:** none in these abstracts
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 0

### 6. Activating AKT1 alteration
- **Context:** under CDK4/6 inhibitor; hormone-receptor-positive · row `akt1-cdk46` · strongest evidence: clinical cohorts
- **Detected by:** ctDNA with matched white-cell sequencing; or sequencing of a progressing lesion
- **When it would matter:** At progression on a CDK4/6 inhibitor
- **What the sources report:**
  - Activating AKT1 alterations were among eight resistance mechanisms (with RB1 loss, activating RAS, AURKA, CCNE2, ERBB2 and FGFR2 alterations, and loss of ER expression). Cohort: exome sequencing of 59 tumors exposed to CDK4/6 inhibitors; frequency: the eight mechanisms together in 66% of resistant tumors. Wander et al. 2020, *Cancer Discov* ([PMID 32404308](https://pubmed.ncbi.nlm.nih.gov/32404308/))
  - AKT1 mutations were enriched in advanced compared with primary breast cancer. Cohort: ABC-Bio: 210 advanced breast cancer samples, 41-gene panel; frequency: 7.14% of samples. Pearson et al. 2020, *Clin Cancer Res* ([PMID 31591187](https://pubmed.ncbi.nlm.nih.gov/31591187/))
  - AKT1 was mutated more often in HR-positive, HER2-negative metastatic cancers than in early cancers (TCGA). Cohort: 617 metastatic breast cancers, 381 HR-positive and HER2-negative; frequency: not stated in the abstract. Bertucci et al. 2019, *Nature* ([PMID 31118521](https://pubmed.ncbi.nlm.nih.gov/31118521/))
- **Against or limits:**
  - AKT1, RAS and AURKA were, to the authors' knowledge, not shown before as CDK4/6-inhibitor resistance mechanisms: one study so far. Wander et al. 2020, *Cancer Discov* ([PMID 32404308](https://pubmed.ncbi.nlm.nih.gov/32404308/))
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 3: PIK3CA Mutation OR PTEN Mutation OR AKT1 Mutation (Capivasertib,Fulvestrant, level A, sensitivity/response); AKT1 E17K (Capivasertib, level C, sensitivity/response); AKT1 E17K (Akt Inhibitor MK2206, level D, sensitivity/response)

### 7. PTEN loss
- **Context:** under CDK4/6 inhibitor or PI3Kα inhibitor; hormone-receptor-positive · row `pten-loss` · strongest evidence: trial cohorts or meta-analyses
- **Detected by:** ctDNA for PTEN mutations, with matched white-cell sequencing; a biopsy for PTEN copy loss or lost expression
- **When it would matter:** At progression on a CDK4/6 inhibitor or a PI3Kα inhibitor; Costa et al. describe one event that may limit both
- **What the sources report:**
  - Loss-of-function PTEN mutations in patients with resistance to alpelisib plus an aromatase inhibitor. Cohort: phase I/II trial, 44 evaluable patients, tumor and plasma; frequency: 25% of patients with resistance. Razavi et al. 2020, *Nat Cancer* ([PMID 32864625](https://pubmed.ncbi.nlm.nih.gov/32864625/))
  - Some tumors lost PTEN expression at progression; PTEN loss promoted CDK4/6-inhibitor resistance in models, and the authors note it also causes resistance to PI3Kα inhibitors (cross-resistance). Cohort: serial biopsies and rapid autopsies, ribociclib plus letrozole; frequency: not stated in the abstract. Costa et al. 2020, *Cancer Discov* ([PMID 31594766](https://pubmed.ncbi.nlm.nih.gov/31594766/))
  - Under the PI3Kα inhibitor alpelisib (BYL719) all 14 metastatic sites of the index patient had PTEN copy loss, and refractory lesions had further, different PTEN alterations: convergent loss of PTEN. Cohort: an index patient (rapid autopsy, 14 sites) and 6 other patients on alpelisib; frequency: acquired biallelic PTEN loss in 1 of the 6 others. Juric et al. 2015, *Nature* ([PMID 25409150](https://pubmed.ncbi.nlm.nih.gov/25409150/))
- **Against or limits:**
  - A small series: seven patients. Juric et al. 2015, *Nature* ([PMID 25409150](https://pubmed.ncbi.nlm.nih.gov/25409150/))
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 23: PIK3CA Mutation OR PTEN Mutation OR AKT1 Mutation (Capivasertib,Fulvestrant, level A, sensitivity/response); PTEN Loss (Trastuzumab, level B, resistance); PTEN Loss (Everolimus, level B, sensitivity/response); PTEN Loss (Trastuzumab, level B, resistance) …

### 8. BRCA1/2 reversion (a secondary mutation restoring the protein)
- **Context:** under PARP inhibitor or platinum; observed BRCA1 or BRCA2 · row `brca-reversion` · strongest evidence: clinical cohorts
- **Detected by:** ctDNA with matched white-cell sequencing; RAD51 foci on a biopsy for restored homologous recombination
- **When it would matter:** During PARP-inhibitor or platinum therapy: in 10 of Harvey-Jones et al.'s patients the reversion was in ctDNA before clinical progression
- **What the sources report:**
  - Reversions were the most prevalent resistance; reversions seen before the next treatment were associated with a shorter time to progression. Cohort: 47 patients with BRCA1/2- or PALB2-mutant metastatic breast cancer progressing on HRD-targeted therapy; serial ctDNA; frequency: 60% of patients. Harvey-Jones et al. 2024, *Ann Oncol* ([PMID 38244928](https://pubmed.ncbi.nlm.nih.gov/38244928/))
  - After progression on a PARP inhibitor or platinum, half the patients had acquired at least one somatic reversion likely to restore BRCA1/2 protein, with RAD51 foci after resistance. Cohort: 8 patients with BRCA1/2-mutant metastatic breast cancer, biopsies before and after resistance; frequency: 4 of 8 (50%). Waks et al. 2020, *Ann Oncol* ([PMID 32245699](https://pubmed.ncbi.nlm.nih.gov/32245699/))
- **Against or limits:**
  - Non-reversion mechanisms (loss of TP53BP1, RIF1 or PAXIP1) were seen too, sometimes with a reversion. Harvey-Jones et al. 2024, *Ann Oncol* ([PMID 38244928](https://pubmed.ncbi.nlm.nih.gov/38244928/))
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 17: BRCA1 Loss-of-function (Olaparib, level A, sensitivity/response); BRCA1 Loss-of-function (Olaparib, level A, sensitivity/response); BRCA2 Loss-of-function (Olaparib, level A, sensitivity/response); BRCA2 Loss-of-function (Olaparib, level A, sensitivity/response) …

### 9. Activating ERBB2 (HER2) mutation
- **Context:** under aromatase inhibitor or SERM or SERD; hormone-receptor-positive · row `erbb2-endocrine` · strongest evidence: clinical cohorts
- **Detected by:** ctDNA with matched white-cell sequencing; or sequencing of a progressing lesion
- **When it would matter:** After resistance to endocrine therapy; Nayar et al.'s models were also resistant to palbociclib
- **What the sources report:**
  - HER2 mutations were enriched in advanced compared with primary breast cancer. Cohort: ABC-Bio: 210 advanced breast cancer samples; frequency: 6.19% of samples. Pearson et al. 2020, *Clin Cancer Res* ([PMID 31591187](https://pubmed.ncbi.nlm.nih.gov/31591187/))
  - Activating HER2 mutations in metastatic biopsies after resistance to aromatase inhibitors, tamoxifen or fulvestrant, absent from the treatment-naive primary in 4 of 5 and mutually exclusive with ESR1 mutations; resistant to tamoxifen, fulvestrant and palbociclib in cell models. Cohort: 8 patients with ER-positive metastatic breast cancer; frequency: 8 patients (no rate given). Nayar et al. 2019, *Nat Genet* ([PMID 30531871](https://pubmed.ncbi.nlm.nih.gov/30531871/))
  - Activating ERBB2 mutations were more than twice as common in endocrine-resistant tumors. Cohort: 1,918 breast cancers, 692 previously exposed to hormonal therapy; frequency: with the other MAPK and ER-regulator alterations, 22% of tumors. Razavi et al. 2018, *Cancer Cell* ([PMID 30205045](https://pubmed.ncbi.nlm.nih.gov/30205045/))
- **Against or limits:** none in these abstracts
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 17: ERBB2 Mutation (Neratinib, level B, sensitivity/response); ERBB2 SERUM LEVELS (Lapatinib, level B, sensitivity/response); ERBB2 S310F (Afatinib, level C, sensitivity/response); ERBB2 V777L (Afatinib, level C, sensitivity/response) …

### 10. NF1 loss-of-function mutation
- **Context:** under aromatase inhibitor or SERM or SERD; hormone-receptor-positive · row `nf1-endocrine` · strongest evidence: clinical cohorts
- **Detected by:** ctDNA with matched white-cell sequencing; or sequencing of a progressing lesion
- **When it would matter:** After resistance to endocrine therapy
- **What the sources report:**
  - NF1 mutations were frequently acquired in advanced disease, absent from the primary; NF1 loss caused endocrine resistance in ER-positive cell lines. Cohort: ABC-Bio: 210 advanced breast cancer samples, with matched primaries in a subset; frequency: 8.10% of samples. Pearson et al. 2020, *Clin Cancer Res* ([PMID 31591187](https://pubmed.ncbi.nlm.nih.gov/31591187/))
  - NF1 loss-of-function mutations were more than twice as common in endocrine-resistant tumors and, with the other MAPK alterations, mutually exclusive with ESR1 mutations. Cohort: 1,918 breast cancers, 692 previously exposed to hormonal therapy; frequency: with the other MAPK and ER-regulator alterations, 22% of tumors. Razavi et al. 2018, *Cancer Cell* ([PMID 30205045](https://pubmed.ncbi.nlm.nih.gov/30205045/))
  - NF1 was mutated more often in HR-positive, HER2-negative metastatic cancers than in early cancers and was associated with poor outcome. Cohort: 617 metastatic breast cancers, 381 HR-positive and HER2-negative; frequency: not stated in the abstract. Bertucci et al. 2019, *Nature* ([PMID 31118521](https://pubmed.ncbi.nlm.nih.gov/31118521/))
- **Against or limits:** none in these abstracts
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 0

### 11. FGFR pathway alteration (FGFR1, FGFR2 or FGF3 amplification; FGFR2 mutation)
- **Context:** under aromatase inhibitor or SERM or SERD; hormone-receptor-positive · row `fgfr-endocrine` · strongest evidence: clinical cohorts
- **Detected by:** Sequencing of a progressing lesion (or ctDNA) that reports amplifications and FGFR2 mutations
- **When it would matter:** After resistance to ER-directed therapy; Mao et al. saw cross-resistance to palbociclib in cell models
- **What the sources report:**
  - FGFR pathway alterations in post-resistance biopsies, half of them acquired or enriched under ER-directed therapy. Cohort: paired pre- and post-resistance biopsies from 60 patients (exome); frequency: 24 of 60 (40%) after resistance; 12 of the 24 acquired or enriched. Mao et al. 2020, *Clin Cancer Res* ([PMID 32723837](https://pubmed.ncbi.nlm.nih.gov/32723837/))
  - Activating FGFR2 alterations were among eight CDK4/6-inhibitor resistance mechanisms. Cohort: exome sequencing of 59 tumors exposed to CDK4/6 inhibitors; frequency: not stated in the abstract. Wander et al. 2020, *Cancer Discov* ([PMID 32404308](https://pubmed.ncbi.nlm.nih.gov/32404308/))
- **Against or limits:** none in these abstracts
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 18: FGF3 Amplification (Dovitinib, level B, sensitivity/response); FGFR1 Amplification (Dovitinib, level B, sensitivity/response); FGFR1 Amplification (Infigratinib, level B, resistance); FGFR1 Amplification (Lucitanib, level B, sensitivity/response) …

### 12. ESR1 fusion (a rearrangement that loses the ligand-binding domain)
- **Context:** under aromatase inhibitor or SERM or SERD; hormone-receptor-positive · row `esr1-fusion` · strongest evidence: clinical cohorts
- **Detected by:** Sequencing able to call rearrangements (the authors used mate-pair, RNA and targeted DNA sequencing); a test for ESR1 point mutations alone does not report them
- **When it would matter:** Under endocrine therapy for metastatic disease; the authors suggest the enrichment may follow more aggressive endocrine therapy after ESR1 point mutations
- **What the sources report:**
  - ESR1 rearrangements were enriched in ER-positive metastatic disease and co-occurred with ESR1 missense mutations; the fusions lack the ligand-binding domain and were ligand-independent and hyperactive in vitro. Cohort: three cohorts, including 9,542 profiled solid tumors and 254 ctDNA samples; frequency: at least 1% of metastatic breast cancers (a lower bound), at least 10 times enriched in ctDNA. Hartmaier et al. 2018, *Ann Oncol* ([PMID 29360925](https://pubmed.ncbi.nlm.nih.gov/29360925/))
- **Against or limits:** none in these abstracts
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 0

### 13. ARID1A inactivating mutation
- **Context:** under aromatase inhibitor or SERM or SERD; hormone-receptor-positive · row `arid1a-endocrine` · strongest evidence: clinical cohorts
- **Detected by:** ctDNA with matched white-cell sequencing; or sequencing of a progressing lesion
- **When it would matter:** After resistance to endocrine therapy; the mechanism was shown for ER degraders such as fulvestrant
- **What the sources report:**
  - ARID1A inactivating mutations were frequent in advanced endocrine-resistant ER-positive breast cancer; ARID1A loss caused resistance to ER degraders by a switch from ER-dependent luminal to ER-independent basal-like cells. Cohort: advanced endocrine-resistant ER-positive breast cancers and a CRISPR screen; frequency: 'high frequency' (no rate in the abstract). Xu et al. 2020, *Nat Genet* ([PMID 31932695](https://pubmed.ncbi.nlm.nih.gov/31932695/))
  - Most distant metastases had acquired driver mutations not seen in the primary, including mutations inactivating SWI-SNF. Cohort: 299 samples from 170 patients with relapsed or metastatic breast cancer; frequency: not stated in the abstract. Yates et al. 2017, *Cancer Cell* ([PMID 28810143](https://pubmed.ncbi.nlm.nih.gov/28810143/))
- **Against or limits:** none in these abstracts
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 0

### 14. Loss of ER positivity in a metastasis (receptor conversion)
- **Context:** hormone-receptor-positive · row `er-loss` · strongest evidence: trial cohorts or meta-analyses
- **Detected by:** IHC for ER (and PR, HER2) on a biopsy of a new or progressing lesion
- **When it would matter:** At relapse or at a new lesion; the meta-analysis authors encourage reassessing receptor status in metastases
- **What the sources report:**
  - ER positive-to-negative conversion between primary tumors and paired distant metastases. Cohort: meta-analysis of 39 studies; frequency: 22.5% (95% CI 16.4 to 30.0%). Schrijver et al. 2018, *J Natl Cancer Inst* ([PMID 29315431](https://pubmed.ncbi.nlm.nih.gov/29315431/))
  - Pooled ER shift from positive to negative between primary and recurrent tumors. Cohort: meta-analysis of 48 articles (4,200 tumors for ER); frequency: 24%. Aurilio et al. 2014, *Eur J Cancer* ([PMID 24269135](https://pubmed.ncbi.nlm.nih.gov/24269135/))
  - Loss of ER expression was one of eight CDK4/6-inhibitor resistance mechanisms. Cohort: exome sequencing of 59 tumors exposed to CDK4/6 inhibitors; frequency: not stated in the abstract. Wander et al. 2020, *Cancer Discov* ([PMID 32404308](https://pubmed.ncbi.nlm.nih.gov/32404308/))
- **Against or limits:**
  - Heterogeneity between the studies was high (I² 91% for ER) and most were retrospective. Aurilio et al. 2014, *Eur J Cancer* ([PMID 24269135](https://pubmed.ncbi.nlm.nih.gov/24269135/))
- **CIViC:** no molecular profile to match for this event

### 15. HER2 status change in a metastasis (gain or loss)
- **Context:** any breast cancer · row `her2-change` · strongest evidence: trial cohorts or meta-analyses
- **Detected by:** IHC and in situ hybridization for HER2 on a biopsy of a new lesion
- **When it would matter:** At relapse or at a new lesion
- **What the sources report:**
  - HER2 conversion between primary tumors and paired distant metastases. Cohort: meta-analysis of 39 studies; frequency: negative to positive 9.5% (95% CI 7.4 to 12.1%); positive to negative 21.3% (14.3 to 30.5%). Schrijver et al. 2018, *J Natl Cancer Inst* ([PMID 29315431](https://pubmed.ncbi.nlm.nih.gov/29315431/))
  - Pooled HER2 shifts between primary and recurrent tumors. Cohort: meta-analysis of 48 articles (2,987 tumors for HER2); frequency: negative to positive 5%; positive to negative 13%. Aurilio et al. 2014, *Eur J Cancer* ([PMID 24269135](https://pubmed.ncbi.nlm.nih.gov/24269135/))
- **Against or limits:**
  - Conversion rates varied widely between studies. Schrijver et al. 2018, *J Natl Cancer Inst* ([PMID 29315431](https://pubmed.ncbi.nlm.nih.gov/29315431/))
- **CIViC:** no molecular profile to match for this event

### 16. Drivers mutated more often in metastatic than in early HR-positive, HER2-negative disease
- **Context:** hormone-receptor-positive, HER2-negative · row `metastatic-drivers` · strongest evidence: clinical cohorts
- **Detected by:** ctDNA with matched white-cell sequencing; or a biopsy of a metastasis with a panel covering these genes
- **When it would matter:** Whenever a later sample is sequenced: what it may show that the first did not
- **What the sources report:**
  - Nine drivers (TP53, ESR1, GATA3, KMT2C, NCOR1, AKT1, NF1, RIC8A, RB1) were mutated more often in HR-positive, HER2-negative metastatic cancers than in early cancers (TCGA); TP53, RB1 and NF1 mutations were associated with poor outcome. Cohort: 617 metastatic breast cancers, 381 HR-positive and HER2-negative; frequency: not stated in the abstract. Bertucci et al. 2019, *Nature* ([PMID 31118521](https://pubmed.ncbi.nlm.nih.gov/31118521/))
  - ESR1 was both a driver and a metastatic gene; TSC1 and TSC2 mutations were more common in HR-positive, HER2-negative metastatic than early cancers (6% vs 0.7%). Cohort: 216 metastatic tumor-blood pairs (exome) against 772 TCGA primaries; frequency: ESR1 mutated or amplified in 27 HR-positive, HER2-negative metastatic cancers (19%). Lefebvre et al. 2016, *PLoS Med* ([PMID 28027327](https://pubmed.ncbi.nlm.nih.gov/28027327/))
  - Tumor mutational burden doubled and six known drivers were mutated more often in metastatic than in primary breast cancer. Cohort: whole genomes of metastatic biopsies from 442 patients; frequency: not stated in the abstract. Angus et al. 2019, *Nat Genet* ([PMID 31570896](https://pubmed.ncbi.nlm.nih.gov/31570896/))
  - Most distant metastases acquired drivers not seen in the primary, from a wider repertoire of cancer genes than early drivers. Cohort: 299 samples from 170 patients with relapsed or metastatic breast cancer; frequency: not stated in the abstract. Yates et al. 2017, *Cancer Cell* ([PMID 28810143](https://pubmed.ncbi.nlm.nih.gov/28810143/))
- **Against or limits:**
  - A comparison with other patients' early cancers (TCGA), not with the same patients' primaries. Bertucci et al. 2019, *Nature* ([PMID 31118521](https://pubmed.ncbi.nlm.nih.gov/31118521/))
- **CIViC:** no molecular profile to match for this event

### 17. TP53 mutation: frequent in basal-like and HER2-amplified tumors
- **Context:** observed TP53 · row `tp53-subtype` · strongest evidence: clinical cohorts
- **Detected by:** IHC for ER, PR and HER2, or an expression subtype from a validated model, to place the tumor
- **When it would matter:** At diagnosis: the subtype decides which rows of this table apply
- **What the sources report:**
  - TP53 mutation frequency differs widely between subgroups: lowest in luminal, highest in basal tumors. Cohort: 572 breast tumors; frequency: luminal 26%, basal 88%. Dumay et al. 2013, *Int J Cancer* ([PMID 22886769](https://pubmed.ncbi.nlm.nih.gov/22886769/))
  - TP53 mutations by subtype; the first important event in luminal tumors, after PTEN loss in basal-like tumors. Cohort: a review; frequency: luminal A 17%, luminal B 41%, HER2-amplified 50%, basal-like 88%. Bertheau et al. 2013, *Breast* ([PMID 24074787](https://pubmed.ncbi.nlm.nih.gov/24074787/))
  - In triple-negative cancers TP53, PIK3CA and PTEN mutations seemed clonally dominant compared with other genes. Cohort: 104 triple-negative breast cancers; frequency: not stated in the abstract. Shah et al. 2012, *Nature* ([PMID 22495314](https://pubmed.ncbi.nlm.nih.gov/22495314/))
  - TP53 mutations carried worse overall and breast-cancer-specific survival, independently in ER-positive cases. Cohort: 1,420 tumors (METABRIC); frequency: 28.3% of tumors. Silwal-Pandit et al. 2014, *Clin Cancer Res* ([PMID 24803582](https://pubmed.ncbi.nlm.nih.gov/24803582/))
- **Against or limits:**
  - In some tumors the clonal frequencies of TP53, PIK3CA and PTEN mutations were incompatible with founder status. Shah et al. 2012, *Nature* ([PMID 22495314](https://pubmed.ncbi.nlm.nih.gov/22495314/))
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 5: TP53 DNA Binding Domain Mutation (Tamoxifen, level B, resistance); TP53 R249 (Doxorubicin, level B, sensitivity/response); TP53 Mutation (Tamoxifen, level C, resistance); TP53 Mutation (Doxorubicin, level D, sensitivity/response) …

### 18. PIK3CA mutation in HER2-positive disease: fewer complete responses to HER2-targeted therapy
- **Context:** HER2-positive; observed PIK3CA · row `pik3ca-her2` · strongest evidence: trial cohorts or meta-analyses
- **Detected by:** HER2 status by IHC and in situ hybridization, which decides whether this row applies; the PIK3CA mutation itself is already observed by tumor sequencing
- **When it would matter:** Before or during neoadjuvant HER2-targeted therapy, the trials' setting
- **What the sources report:**
  - Activating PIK3CA mutations predicted fewer pathologic complete responses with neoadjuvant trastuzumab plus lapatinib (28.6% vs 53.1% in wild type). Cohort: NeoALTTO, HER2-positive early breast cancer; frequency: 23% of HER2-positive tumors. Majewski et al. 2015, *J Clin Oncol* ([PMID 25559818](https://pubmed.ncbi.nlm.nih.gov/25559818/))
  - PIK3CA mutations were associated with a lower pathologic complete response rate (19.4% vs 32.8%; OR 0.49). Cohort: 504 HER2-positive tumors from GeparQuattro, GeparQuinto and GeparSixto; frequency: 21.4% of patients. Loibl et al. 2014, *J Clin Oncol* ([PMID 25199759](https://pubmed.ncbi.nlm.nih.gov/25199759/))
- **Against or limits:**
  - Disease-free and overall survival did not differ significantly between mutant and wild type. Loibl et al. 2014, *J Clin Oncol* ([PMID 25199759](https://pubmed.ncbi.nlm.nih.gov/25199759/))
- **CIViC (accepted predictive items in breast cancer, nightly table of 2026-10-19):** 33: PIK3CA Mutation (Trastuzumab, level B, resistance); PIK3CA Mutation (Trastuzumab, level B, resistance); PIK3CA Mutation (Trastuzumab, level B, resistance); PIK3CA Mutation (Trastuzumab Emtansine, level B, resistance) …

## Limits

- The table is literature, not a model: whether a listed event occurs in a given patient has not
  been checked against outcomes, and a cohort's frequency is not this patient's probability.
- Abstracts only: what a paper shows beyond its abstract is not used, and a frequency the abstract
  does not state is shown as "not stated in the abstract".
- Clonal order uses one sample per patient, gene-level copy number and no purity; repeated samples
  over time would make it far more reliable.
- The TCGA driver panel (16 genes) does not include RB1, FAT1, BRCA1/2 or the FGFR genes, so rows
  needing them can't be raised from a TCGA file's own calls.
- A receptor status read from a report is a rule match: about 1 in 5 HER2 reads disagreed with
  TCGA's clinical fields on held-out reports, and a HER2-negative read drops the HER2-positive row
  (named in "Not raised", with its document). Recall is about 40%: many TCGA surgical reports refer
  receptor results to an earlier biopsy report that is not in the dataset.
- Trials come from the registry's own relevance order (the first 20 per gene); eligibility is not
  assessed.

## Data files

- `app/evolution_vaf.json`: the bundled TCGA cases' driver calls with alt reads, depth and the
  gene's copy number (derived numbers, keyed by case index; no barcode), from
  `python scripts/make_evolution_vaf.py --bundle outputs/demo_bundle.pt --data data/tcga_brca
  --raw data/raw/tcga_brca` (GDC API for the per-case masked MAFs; the read counts matched the
  Xena file's `dna_vaf` exactly for all 56 calls).
- `app/trials_snapshot.json`: the first page of trials per panel gene, from
  `python scripts/refresh_trials.py`; refresh it before a release.

## References

- Angus et al. 2019. The genomic landscape of metastatic breast cancer highlights changes in mutation and signature frequencies. *Nat Genet*. PMID [31570896](https://pubmed.ncbi.nlm.nih.gov/31570896/); doi:[10.1038/s41588-019-0507-7](https://doi.org/10.1038/s41588-019-0507-7)
- Aurilio et al. 2014. A meta-analysis of oestrogen receptor, progesterone receptor and human epidermal growth factor receptor 2 discordance between primary breast cancer and metastases. *Eur J Cancer*. PMID [24269135](https://pubmed.ncbi.nlm.nih.gov/24269135/); doi:[10.1016/j.ejca.2013.10.004](https://doi.org/10.1016/j.ejca.2013.10.004)
- Bertheau et al. 2013. p53 in breast cancer subtypes and new insights into response to chemotherapy. *Breast*. PMID [24074787](https://pubmed.ncbi.nlm.nih.gov/24074787/); doi:[10.1016/j.breast.2013.07.005](https://doi.org/10.1016/j.breast.2013.07.005)
- Bertucci et al. 2019. Genomic characterization of metastatic breast cancers. *Nature*. PMID [31118521](https://pubmed.ncbi.nlm.nih.gov/31118521/); doi:[10.1038/s41586-019-1056-z](https://doi.org/10.1038/s41586-019-1056-z)
- Bidard et al. 2022 (PADA-1). Switch to fulvestrant and palbociclib versus no switch in advanced breast cancer with rising ESR1 mutation during aromatase inhibitor and palbociclib therapy (PADA-1). *Lancet Oncol*. PMID [36183733](https://pubmed.ncbi.nlm.nih.gov/36183733/); doi:[10.1016/S1470-2045(22)00555-1](https://doi.org/10.1016/S1470-2045(22)00555-1)
- Bidard et al. 2025 (SERENA-6). First-Line Camizestrant for Emerging ESR1-Mutated Advanced Breast Cancer. *N Engl J Med*. PMID [40454637](https://pubmed.ncbi.nlm.nih.gov/40454637/); doi:[10.1056/NEJMoa2502929](https://doi.org/10.1056/NEJMoa2502929)
- Condorelli et al. 2018. Polyclonal RB1 mutations and acquired resistance to CDK 4/6 inhibitors in patients with metastatic breast cancer. *Ann Oncol*. PMID [29236940](https://pubmed.ncbi.nlm.nih.gov/29236940/); doi:[10.1093/annonc/mdx784](https://doi.org/10.1093/annonc/mdx784)
- Costa et al. 2020. PTEN Loss Mediates Clinical Cross-Resistance to CDK4/6 and PI3Kα Inhibitors in Breast Cancer. *Cancer Discov*. PMID [31594766](https://pubmed.ncbi.nlm.nih.gov/31594766/); doi:[10.1158/2159-8290.CD-18-0830](https://doi.org/10.1158/2159-8290.CD-18-0830)
- Dumay et al. 2013. Distinct tumor protein p53 mutants in breast cancer subgroups. *Int J Cancer*. PMID [22886769](https://pubmed.ncbi.nlm.nih.gov/22886769/); doi:[10.1002/ijc.27767](https://doi.org/10.1002/ijc.27767)
- Fribbens et al. 2016. Plasma ESR1 Mutations and the Treatment of Estrogen Receptor-Positive Advanced Breast Cancer. *J Clin Oncol*. PMID [27269946](https://pubmed.ncbi.nlm.nih.gov/27269946/); doi:[10.1200/JCO.2016.67.3061](https://doi.org/10.1200/JCO.2016.67.3061)
- Gerstung et al. 2020. The evolutionary history of 2,658 cancers. *Nature*. PMID [32025013](https://pubmed.ncbi.nlm.nih.gov/32025013/); doi:[10.1038/s41586-019-1907-7](https://doi.org/10.1038/s41586-019-1907-7)
- Hartmaier et al. 2018. Recurrent hyperactive ESR1 fusion proteins in endocrine therapy-resistant breast cancer. *Ann Oncol*. PMID [29360925](https://pubmed.ncbi.nlm.nih.gov/29360925/); doi:[10.1093/annonc/mdy025](https://doi.org/10.1093/annonc/mdy025)
- Harvey-Jones et al. 2024. Longitudinal profiling identifies co-occurring BRCA1/2 reversions, TP53BP1, RIF1 and PAXIP1 mutations in PARP inhibitor-resistant advanced breast cancer. *Ann Oncol*. PMID [38244928](https://pubmed.ncbi.nlm.nih.gov/38244928/); doi:[10.1016/j.annonc.2024.01.003](https://doi.org/10.1016/j.annonc.2024.01.003)
- Juric et al. 2015. Convergent loss of PTEN leads to clinical resistance to a PI(3)Kα inhibitor. *Nature*. PMID [25409150](https://pubmed.ncbi.nlm.nih.gov/25409150/); doi:[10.1038/nature13948](https://doi.org/10.1038/nature13948)
- Kingston et al. 2024. ESR1 F404 Mutations and Acquired Resistance to Fulvestrant in ESR1-Mutant Breast Cancer. *Cancer Discov*. PMID [37982575](https://pubmed.ncbi.nlm.nih.gov/37982575/); doi:[10.1158/2159-8290.CD-22-1387](https://doi.org/10.1158/2159-8290.CD-22-1387)
- Lefebvre et al. 2016. Mutational Profile of Metastatic Breast Cancers: A Retrospective Analysis. *PLoS Med*. PMID [28027327](https://pubmed.ncbi.nlm.nih.gov/28027327/); doi:[10.1371/journal.pmed.1002201](https://doi.org/10.1371/journal.pmed.1002201)
- Li et al. 2018. Loss of the FAT1 Tumor Suppressor Promotes Resistance to CDK4/6 Inhibitors via the Hippo Pathway. *Cancer Cell*. PMID [30537512](https://pubmed.ncbi.nlm.nih.gov/30537512/); doi:[10.1016/j.ccell.2018.11.006](https://doi.org/10.1016/j.ccell.2018.11.006)
- Loibl et al. 2014. PIK3CA mutations are associated with lower rates of pathologic complete response to anti-human epidermal growth factor receptor 2 (her2) therapy in primary HER2-overexpressing breast cancer. *J Clin Oncol*. PMID [25199759](https://pubmed.ncbi.nlm.nih.gov/25199759/); doi:[10.1200/JCO.2014.55.7876](https://doi.org/10.1200/JCO.2014.55.7876)
- Majewski et al. 2015. PIK3CA mutations are associated with decreased benefit to neoadjuvant human epidermal growth factor receptor 2-targeted therapies in breast cancer. *J Clin Oncol*. PMID [25559818](https://pubmed.ncbi.nlm.nih.gov/25559818/); doi:[10.1200/JCO.2014.55.2158](https://doi.org/10.1200/JCO.2014.55.2158)
- Mao et al. 2020. Acquired FGFR and FGF Alterations Confer Resistance to Estrogen Receptor (ER) Targeted Therapy in ER(+) Metastatic Breast Cancer. *Clin Cancer Res*. PMID [32723837](https://pubmed.ncbi.nlm.nih.gov/32723837/); doi:[10.1158/1078-0432.CCR-19-3958](https://doi.org/10.1158/1078-0432.CCR-19-3958)
- Nayar et al. 2019. Acquired HER2 mutations in ER(+) metastatic breast cancer confer resistance to estrogen receptor-directed therapies. *Nat Genet*. PMID [30531871](https://pubmed.ncbi.nlm.nih.gov/30531871/); doi:[10.1038/s41588-018-0287-5](https://doi.org/10.1038/s41588-018-0287-5)
- O'Leary et al. 2018 (PALOMA-3). The Genetic Landscape and Clonal Evolution of Breast Cancer Resistance to Palbociclib plus Fulvestrant in the PALOMA-3 Trial. *Cancer Discov*. PMID [30206110](https://pubmed.ncbi.nlm.nih.gov/30206110/); doi:[10.1158/2159-8290.CD-18-0264](https://doi.org/10.1158/2159-8290.CD-18-0264)
- Pearson et al. 2020. Inactivating NF1 Mutations Are Enriched in Advanced Breast Cancer and Contribute to Endocrine Therapy Resistance. *Clin Cancer Res*. PMID [31591187](https://pubmed.ncbi.nlm.nih.gov/31591187/); doi:[10.1158/1078-0432.CCR-18-4044](https://doi.org/10.1158/1078-0432.CCR-18-4044)
- Razavi et al. 2018. The Genomic Landscape of Endocrine-Resistant Advanced Breast Cancers. *Cancer Cell*. PMID [30205045](https://pubmed.ncbi.nlm.nih.gov/30205045/); doi:[10.1016/j.ccell.2018.08.008](https://doi.org/10.1016/j.ccell.2018.08.008)
- Razavi et al. 2019. High-intensity sequencing reveals the sources of plasma circulating cell-free DNA variants. *Nat Med*. PMID [31768066](https://pubmed.ncbi.nlm.nih.gov/31768066/); doi:[10.1038/s41591-019-0652-7](https://doi.org/10.1038/s41591-019-0652-7)
- Razavi et al. 2020. Alterations in PTEN and ESR1 promote clinical resistance to alpelisib plus aromatase inhibitors. *Nat Cancer*. PMID [32864625](https://pubmed.ncbi.nlm.nih.gov/32864625/); doi:[10.1038/s43018-020-0047-1](https://doi.org/10.1038/s43018-020-0047-1)
- Robinson et al. 2013. Activating ESR1 mutations in hormone-resistant metastatic breast cancer. *Nat Genet*. PMID [24185510](https://pubmed.ncbi.nlm.nih.gov/24185510/); doi:[10.1038/ng.2823](https://doi.org/10.1038/ng.2823)
- Schiavon et al. 2015. Analysis of ESR1 mutation in circulating tumor DNA demonstrates evolution during therapy for metastatic breast cancer. *Sci Transl Med*. PMID [26560360](https://pubmed.ncbi.nlm.nih.gov/26560360/); doi:[10.1126/scitranslmed.aac7551](https://doi.org/10.1126/scitranslmed.aac7551)
- Schrijver et al. 2018. Receptor Conversion in Distant Breast Cancer Metastases: A Systematic Review and Meta-analysis. *J Natl Cancer Inst*. PMID [29315431](https://pubmed.ncbi.nlm.nih.gov/29315431/); doi:[10.1093/jnci/djx273](https://doi.org/10.1093/jnci/djx273)
- Shah et al. 2012. The clonal and mutational evolution spectrum of primary triple-negative breast cancers. *Nature*. PMID [22495314](https://pubmed.ncbi.nlm.nih.gov/22495314/); doi:[10.1038/nature10933](https://doi.org/10.1038/nature10933)
- Silwal-Pandit et al. 2014. TP53 mutation spectrum in breast cancer is subtype specific and has distinct prognostic relevance. *Clin Cancer Res*. PMID [24803582](https://pubmed.ncbi.nlm.nih.gov/24803582/); doi:[10.1158/1078-0432.CCR-13-2943](https://doi.org/10.1158/1078-0432.CCR-13-2943)
- Toy et al. 2013. ESR1 ligand-binding domain mutations in hormone-resistant breast cancer. *Nat Genet*. PMID [24185512](https://pubmed.ncbi.nlm.nih.gov/24185512/); doi:[10.1038/ng.2822](https://doi.org/10.1038/ng.2822)
- Waks et al. 2020. Reversion and non-reversion mechanisms of resistance to PARP inhibitor or platinum chemotherapy in BRCA1/2-mutant metastatic breast cancer. *Ann Oncol*. PMID [32245699](https://pubmed.ncbi.nlm.nih.gov/32245699/); doi:[10.1016/j.annonc.2020.02.008](https://doi.org/10.1016/j.annonc.2020.02.008)
- Wander et al. 2020. The Genomic Landscape of Intrinsic and Acquired Resistance to Cyclin-Dependent Kinase 4/6 Inhibitors in Patients with Hormone Receptor-Positive Metastatic Breast Cancer. *Cancer Discov*. PMID [32404308](https://pubmed.ncbi.nlm.nih.gov/32404308/); doi:[10.1158/2159-8290.CD-19-1390](https://doi.org/10.1158/2159-8290.CD-19-1390)
- Xu et al. 2020. ARID1A determines luminal identity and therapeutic response in estrogen-receptor-positive breast cancer. *Nat Genet*. PMID [31932695](https://pubmed.ncbi.nlm.nih.gov/31932695/); doi:[10.1038/s41588-019-0554-0](https://doi.org/10.1038/s41588-019-0554-0)
- Yates et al. 2015. Subclonal diversification of primary breast cancer revealed by multiregion sequencing. *Nat Med*. PMID [26099045](https://pubmed.ncbi.nlm.nih.gov/26099045/); doi:[10.1038/nm.3886](https://doi.org/10.1038/nm.3886)
- Yates et al. 2017. Genomic Evolution of Breast Cancer Metastasis and Relapse. *Cancer Cell*. PMID [28810143](https://pubmed.ncbi.nlm.nih.gov/28810143/); doi:[10.1016/j.ccell.2017.07.005](https://doi.org/10.1016/j.ccell.2017.07.005)

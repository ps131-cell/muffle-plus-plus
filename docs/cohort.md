# Across the files: search, similar patients, where a patient sits

Status: **implemented** (2026-10-27). Code: `src/muffle/cohort.py`; on the Patients page the
**Search every file** box above the patient list, and on each report **Where this patient sits**
and **Similar patients** under the overview cards and the attention queue
(`app/streamlit_app.py`, `cohort_search` and `cohort_sections`). Tests: `tests/test_cohort.py`.

All three are lookups over what the files already hold. No model is trained or run, nothing is
a prognosis, and nothing from MSK-CHORD is compared (CLAUDE.md): the synthetic patient's
12-month risk comes from MSK-CHORD models, so it never enters a similarity or a distribution.

## What is indexed
Once per bundle (`st.cache_data`, built on the first search, about 10 to 20 s on a shared CPU for
the 41 files), for each file as of its latest report:

| Entry | From | Opens |
|---|---|---|
| File profile | stage, receptors, PAM50 call, mutated drivers, copy-number calls, risk group, RNA immune band, tests on file (`cohort.profile`) | the report |
| Finding cards | every workbench's `summary` and the report header's own cards (stage and receptors, imaging, the risk) | the card's test at its evidence |
| Attention items | the file's one queue: SOS alerts, tests that disagree (`crosstest`), every workbench's `queue` | the item's test at its pointer |
| Variants | `genomics.file_variants`, with the strongest CIViC level when CIViC loaded | the sequencing test at the variant |
| Methylation calls | `omics.methylation_lines`: each gene's promoter methylated or unmethylated | the expression workbench |
| Documented facts | `documents.facts` of the file's documents (dates left out) | the document at its sentence |
| Hypotheses | `evolution.hypothesis_set`: each event with its status in this file | the Evolution view |

Each entry keeps the finding's evidence label (observed, model inference, hypothesis: the first
the evidence text names), its workbench and a deep link (`?patient&view&test&pointer`,
docs/ux.md §3). Files an import of this session changed are read again (once per version).

## Search
- Every word must appear in **one finding** of a file, at the start of a word, case-insensitive:
  `basal` finds "Basal-like", `methylated` does not find "unmethylated". A word of three
  characters or fewer at the end of a term must be whole: `ER` is not "HER2", `stage I` is not
  "stage II".
- Phrases: a word after `level`, `stage`, `grade` or `BI-RADS` joins it (`level A`, `stage III`,
  `grade 3`); `positive`, `negative`, `methylated` and `unmethylated` join the word before them
  (`ER positive`, `ESR1 methylated`); quotes make any phrase (`"tumor size"`).
- When no finding of any file holds every word, files whose findings hold them between them are
  listed instead, and the result says so (`TP53 desert`).
- Ranking: files with more matching findings first, then the closer the words sit in the best
  one, then by evidence (observed, model inference, hypothesis). The evidence pills keep only
  findings of the labels chosen.
- Examples on the release bundle: `HER2 disagree` lists the five files whose HER2 IHC and ERBB2
  RNA disagree; `breakaway` the scored slide sections; `basal` the Basal-like calls first and,
  lower, files where only a hypothesis names basal-like tumors; `stage III PIK3CA` the stage III
  files with PIK3CA mutated or amplified; `level A` the variants with CIViC level A evidence.

Each result shows the file (synthetic labeled), its best finding with its label, workbench and
kind, the other matching findings in a popover, and **Open**, which lands on the finding in this
browser session (the review marks are kept); its help shows the deep link.

## Similar patients
`cohort.similar_patients`: the five TCGA files nearest to this one on eight fields: PAM50 subtype
(model inference), stage (recorded), receptor status (recorded IHC and ISH), mutated driver
genes, copy-number calls (observed copies, placeholder rule), risk group (the risk model's
tertile; model inference), RNA immune band (high from the 75th, low to the 25th percentile;
placeholders) and the tests on file.

- One value agrees 1 or 0; a set by the share of items in common (Jaccard; both empty agrees);
  receptors per receptor both files state. A record that states only the hormone receptors (the
  synthetic patient's "hormone-receptor positive") compares as HR, positive when ER or PR is.
- The score is the share of the eight fields on which the two agree, every field weighing the
  same (**placeholder**, not tuned on outcomes); a field either file lacks counts as not shared,
  so a sparse file is never "very similar" on one field.
- Each neighbour shows the fields shared, those that differ (both values) and those not
  compared. Candidates are the TCGA files only: the synthetic patient is never one, though its
  own report lists its nearest TCGA files on what its record states.
- Labeled "a lookup on recorded and derived fields, not a model". It says which files look alike
  on these fields; it says nothing about how either patient will do.

## Where this patient sits
`cohort.cohort_position`: for each score the file has, its percentile among the TCGA files with
that score (the share of the other files with a lower value, ties half) and a small chart of every
file's value with this patient marked. Scores: the risk model's log-risk, the mutation burden
(calls per Mb), proliferation, the ESTIMATE immune and stromal signatures, cytolytic activity, the
RPPA PI3K/AKT pathway score and the methylation index (hypothesis).

- The cohort is the 40 TCGA files of the bundle; the synthetic patient is excluded and its report
  says so (its risk is another model's, and it has no scores measured the same way).
- These percentiles are among the 40 files. The workbenches' percentiles are against the whole
  TCGA cohort (about 1,000 tumors), so the two differ; the strip says so.
- Percentiles, not a prognosis.

## Known limits
- The index is text: a finding worded differently from the query is missed, and a card listing
  genes ("none of ESR1, PGR, BRCA1 methylated") can match words it negates; the phrases and the
  closeness ranking keep those below the real matches, and the finding is always shown.
- Similarity weights are placeholders, and the eight fields are the ones every file can state;
  nothing about treatment or outcome enters.
- Forty files are a small cohort: one file moves a percentile by 2.5 points.

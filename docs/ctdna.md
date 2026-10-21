# ctDNA monitor (liquid biopsy): a labeled synthetic series and its rules

The ctDNA monitor (`app/workbenches/ctdna.py`, rules in `src/muffle/workbench/ctdna.py`) follows
tumor mutations in blood over time: the evolution story of `docs/VISION.md` part three (an ESR1
mutation emerging under an aromatase inhibitor, caught in blood). No open serial breast ctDNA
dataset with raw reads or per-sample allele fractions was found (`docs/model_survey.md` §5), so
the only series in the app is **synthetic**: written by hand for SYNTHETIC-001 and labeled
synthetic on every screen, in the report export and in the CSV. Status: implemented, not
validated (2026-10-21). No model: every call is a rule, and every rule names its source.

## The synthetic series

`muffle.timeline.CTDNA`, a constant separate from `EVENTS` so that the record, and the risk
updates row-aligned with it in `app/timeline_synthetic.json`, never change; the MSK-CHORD risk
models never saw it. Months are the record's own timeline (the record carries no calendar dates).
Variant allele fractions (VAF) in percent of cell-free DNA; "–" = not detected, below the 0.1%
detection limit (a placeholder).

| Month | PIK3CA H1047R | ESR1 D538G | DNMT3A R882H | In the record around it |
|---|---|---|---|---|
| −12 | 0.12 | – | 0.42 | adjuvant letrozole since month −33 |
| −6 | 0.35 | – | 0.45 | |
| −2 | 1.6 | 0.18 | 0.40 | CA 15-3 48 U/mL, above its limit |
| 0 | 2.4 | 0.31 | 0.47 | bone progression at −1; tumor sequencing of the bone biopsy: PIK3CA H1047R |
| 4 | 0.9 | 0.22 | 0.44 | palbociclib + fulvestrant since month 1 |
| 7 | 0.3 | 0.15 | 0.41 | imaging stable |
| 9 | 0.6 | 0.4 | 0.46 | |
| 11 | 1.9 | 1.1 | 0.43 | CA 15-3 52, rising |
| 13 | 3.2 | 2.0 | 0.45 | liver progression at 12; alpelisib added at 13 |
| 16 | 1.1 | 0.7 | 0.48 | |
| 19 | 0.4 | 0.25 | 0.44 | imaging stable |
| 24 | 0.18 | – | 0.46 | |

Three stories. PIK3CA H1047R, found in the month-0 tumor sequencing, tracks burden: up before both
progressions, down under treatment. ESR1 D538G emerges under letrozole and rises before the liver
progression; it stays below PIK3CA, as a subclone of a truncal PIK3CA mutation would. DNMT3A
R882H sits at a flat low fraction whatever the treatment: the pattern of clonal hematopoiesis.
The workspace adds one test per sample (kind "ctDNA (liquid biopsy)", workbench "ctdna") to the
first report version at or after the sample's month, so "as of" a version never shows a later
sample.

## Rules

| Rule | Definition | Source | Status |
|---|---|---|---|
| detected / not detected | VAF at or above the detection limit, 0.1% | none | placeholder |
| new | detected after samples below the limit | none | placeholder |
| rising / falling | at least 2× / at most 0.5× the previous detected VAF; otherwise stable | none | placeholder |
| cleared | below the limit at 2 consecutive samples after detection; one is "not detected, 1 of 2" | none | placeholder |
| flat whatever the treatment | highest over lowest detected VAF under 1.5, 3 or more samples | none | placeholder |
| origin | found in the tumor sequencing: tumor-matched. Not found (or its gene not on the panel) and in DNMT3A, TET2 or ASXL1: **possible clonal hematopoiesis**, kept out of the tumor picture until matched white-cell sequencing. Not found, other genes: kept, origin unconfirmed | Razavi et al. 2019 [1]; Jaiswal et al. 2014 [2] | literature |
| ESR1 under an aromatase inhibitor | a new or rising ESR1 call while letrozole, anastrozole or exemestane is recorded: the trigger PADA-1 tested and the design of SERENA-6, shown with how this record differs from the trials | PADA-1 [3]; SERENA-6 [4]; Schiavon et al. 2015 [5] | literature, evidence for clinician review |
| low shedding | a sample with no tumor-matched variant detected: a "not detected" there says little | WORKSPACE.md limits | rule |
| lead and lag | each new or rising call against the next imaging progression and the next CA 15-3 flagged above or rising | the record itself | observed order, not a lead time |

What the ESR1 rule shows on SYNTHETIC-001: at month −2 ESR1 D538G is new while letrozole is
recorded, so the rule applies, and the page lays out the differences: the trials monitored
first-line therapy for advanced disease (an aromatase inhibitor with palbociclib in PADA-1, with
a CDK4/6 inhibitor in SERENA-6), while this record's letrozole is adjuvant, and ESR1 mutations are
rarely acquired under adjuvant aromatase inhibitors (5.8% against 36.4% in the metastatic setting,
Schiavon 2015); PADA-1 randomized only patients without synchronous progression, and imaging read
progression one month later here. At months 9 and 11 ESR1 rises on palbociclib + fulvestrant: the
rule does not apply (no aromatase inhibitor), the call stands by the placeholder rule. Never a
recommendation to switch.

**A correction to the brief.** "A variant absent from the tumor sequencing may be clonal
hematopoiesis, so it is flagged and excluded" would also have excluded ESR1 D538G: ESR1 is on the
tumor panel and the month-0 bone biopsy did not find it. ESR1 is not a clonal-hematopoiesis gene,
and an acquired, subclonal resistance mutation missing from one earlier biopsy is the expected
case, not a sign of blood origin. So the exclusion needs both conditions (not in the tumor
sequencing **and** a clonal-hematopoiesis gene), and every variant, tumor-matched or not, keeps
Razavi's caveat that only matched white-cell sequencing settles origin. Clonal hematopoiesis in
other genes (TP53 among them) is therefore not flagged by the rule; the rules card lists that as
a known failure.

## The page

Overview with pointers C1…Cn (one per new, rising, falling or cleared call); allele fractions on
a log axis with the detection limit, treatment spans and imaging progressions, CA 15-3 below on
the same axis; calls per variant with origin, pattern and the rule; the ESR1 rule items; the
clonal-hematopoiesis section; lead and lag; a Spot panel per point (value, call and rule, origin,
therapy at the time, events around it, CA 15-3 at or before it, what to check by eye, the
variant's history) with buttons to the tumor sequencing in the genomics workbench and to the
Evolution view; the look-here queue; review marks (`workspace.finding_key(pf, "ctdna", variant,
month)`); what ctDNA cannot see; the rules card; Markdown and CSV exports. TCGA files hold no
blood samples, and the page says so.

## What ctDNA cannot see

- Where the disease is: ctDNA has no location; imaging does.
- A tumor that sheds little DNA: "not detected" is not "absent".
- A blood-cell variant from a tumor variant, without matched white-cell sequencing.
- Anything off the panel: other genes, copy number, fusions, expression.
- Tumor size: a VAF moves with shedding and with other cells' cell-free DNA.
- What to give: the trial evidence is for clinician review, never a recommendation.

## Sources

1. Razavi P et al. High-intensity sequencing reveals the sources of plasma circulating cell-free
   DNA variants. *Nat Med* 2019. doi:10.1038/s41591-019-0652-7 (53.2% of cfDNA mutations in
   patients with cancer, 81.6% in controls, had features of clonal hematopoiesis)
2. Jaiswal S et al. Age-related clonal hematopoiesis associated with adverse outcomes. *N Engl J
   Med* 2014. doi:10.1056/NEJMoa1408617 (most variants in DNMT3A, TET2 and ASXL1)
3. Bidard FC et al. Switch to fulvestrant and palbociclib versus no switch in advanced breast
   cancer with rising ESR1 mutation during aromatase inhibitor and palbociclib therapy (PADA-1).
   *Lancet Oncol* 2022. doi:10.1016/S1470-2045(22)00555-1
4. Bidard FC et al. First-line camizestrant for emerging ESR1-mutated advanced breast cancer
   (SERENA-6). *N Engl J Med* 2025. doi:10.1056/NEJMoa2502929
5. Schiavon G et al. Analysis of ESR1 mutation in circulating tumor DNA demonstrates evolution
   during therapy for metastatic breast cancer. *Sci Transl Med* 2015.
   doi:10.1126/scitranslmed.aac7551

PubMed records checked on 2026-10-20.

# How the app reads: page skeleton, navigation and the guide

How a pathologist who opens the app for the first time finds their way: one layout for every
workbench page, one way to move between screens, and a guide inside the app. Written
2026-10-22; the product rules (observed / model inference / hypothesis, placeholders that never
look validated, treatment content as evidence for clinician review) are in
[`WORKBENCHES.md`](WORKBENCHES.md) §1 and stay as they are. Nothing of a workbench's depth is
removed: a section that moved behind a click carries its count in its header.

## 1. One skeleton for every workbench page

Every workbench page draws the same parts in the same order, with the same headings, through
one helper (`app/workbenches/_page.py`, names in `muffle.workbench.grammar`):

| Part | What it holds | Heading |
|---|---|---|
| Title | the workbench, the patient and the test opened, and the report version when it isn't the latest: "Pathology slide workbench · Case 299 · Diagnostic H&E section(s) (GDC, open access)" | the page's subheader |
| Status chips | implemented / experimentally validated / planned, the evidence labels the page uses, "placeholder" (always orange), "synthetic" where it applies; then the page's provenance line and its honesty labels (a synthetic record, an imported result) | none |
| Overview | one paragraph, the look-here queue (the workbench's own `queue()` items, the ones the report's attention queue carries: pointer, what, evidence label, trust, review mark, the reason on hover, and "Spot" to open it in the Spot panel) and search in plain words | Overview |
| The picture | the page's main view: map, viewer, chart or table | its own name: Trends, Allele fractions over time, Variants and the tumor's genome, Slide viewer (or Tile map), Subtype and pathway scores, The record over time, Imported in this session |
| Details | every other section, collapsed, each with its count in the header ("Satellite islands (19)", "Quality control (0 of 5745 tiles excluded)") | Details |
| Spot panel | one value, variant, tile, lesion, finding or hypothesis in full, with its review mark; a one-line subtitle says what it is the first time it appears | Spot panel |
| Model and validation card | the method, its numbers, sources and known failures; long tables (every threshold, a reference table, references) in expanders inside it | Model and validation card |
| What this test cannot see | what the test cannot show, and which test could | What this test cannot see |
| Export | the downloads, "Download the <what> (<format>)"; when there is nothing to export, a line says why | Export |

Rules the helper enforces:
- **Order.** Parts come in this order; details repeat, every other part comes once. A page that
  draws a part out of order fails its tests (`MUFFLE_STRICT_PAGES=1`, set by `tests/conftest.py`);
  in front of a clinician it is drawn as asked, never broken.
- **Required parts.** Title, chips, overview, card, what the test cannot see and export are on
  every page, including the empty ones.
- **Counts.** A collapsed section carries a count (a number, or a short phrase where a number
  alone would mislead: "1 failing of 6", "not measured").
- **Secondary material in expanders.** Rules tables, reference intervals, source lists,
  constraints and confusion matrices sit in expanders inside the card or the details.
- **Empty states say what is missing and which test would provide it.** "No lab results in this
  file … A lab results file (CSV) brought in through Import tests would open this workbench";
  "No ctDNA in this file … A plasma ctDNA panel (liquid biopsy), taken again under treatment,
  would open this monitor".

Where each page's former sections went:

| Page | Picture | Details (collapsed, counted) | Spot panel |
|---|---|---|---|
| Blood and lab | Trends by panel | flagged results (one row per rule; a row opens the Spot panel), results with filters, rise confirmation (EGTM), early after a therapy change, kinetics, within-person baseline, markers against imaging, cross-analyte hypotheses, cross-marker view, quality checks, planned panels | one value, with the rules that fired and its review mark (formerly one expander per flagged result) |
| ctDNA | Allele fractions over time, CA 15-3 below | calls per variant, the ESR1 rule (PADA-1, SERENA-6), clonal hematopoiesis, against imaging and CA 15-3, every look-here item, review marks | one sample and variant, with links to genomics and Evolution |
| Genomics | Variants and the tumor's genome: one tab bar (variants, copy-number landscape, burden and allele fractions, predicted effect, pathway map) | resistance watchlist, panel coverage, review queue, over time | a variant or a gene: a click on a variant row, a gene in a chart or a pathway node opens it |
| Pathology slides | Slide viewer (or the tile map when the tiles can't be had) | direction of invasion, cells, satellite islands, risk map, quality control, every look-here pointer, and for files with several sections the sections compared and side by side (the second viewer loads only when opened) | one tile |
| Expression, methylation and protein | Subtype and pathway scores | receptor consistency, protein pathways (RPPA), promoter methylation, the immune and stromal picture, the data layers, the what-if | one finding |
| Evolution | The record over time | what to watch next (a row opens the Spot panel), the rows not raised and why, clonal order, trials | one hypothesis, with the evidence for and against and its CIViC items |
| Import tests | Imported in this session | rejected on intake, what each adapter accepts | none |

The radiology and documents pages join the skeleton after their second rounds land.

## 2. Navigation

**Breadcrumbs on every screen** (`app/navigation.py`): "Patients › Case 299 › Tests ›
Pathology slide". "Patients" goes back to the list; the file's crumb is the file picker itself
(type or pick another patient to switch files); then the view, and in Tests the test opened
(its kind, or its name where the kind says little: "CA 15-3, month 11"). The Methods and
validation page carries "Patients › Methods and validation".

**The patient header stays on screen** while the page scrolls: the breadcrumbs, the patient's
identity and diagnosis, the open SOS alerts ("SOS: 2 open", alerts no reviewer has marked yet,
as of the report version shown; "SOS: none open" otherwise), the version shown when it isn't
the latest, and the view control (Report, Tests, Timeline, Evolution, Import tests). The report
version slider sits under it.

**The way back.** After an "Open" (an attention-queue item, an overview card), the workbench
shows "← Back to the file" (the file's report, at its top) and, when it came from the queue,
"← Back to the queue, item 6 of 15", which returns to the queue on that item.

**Deep links.** The address always says what is on screen, so a link or a screenshot's address
lands on the evidence:

| Parameter | What it holds | Written by |
|---|---|---|
| `patient` | the file ("SYNTHETIC-001", "Case 299") | the file picker (bound to it) |
| `view` | Report, Tests, Timeline, Evolution or Import tests | the view control (bound to it) |
| `test` | the test open in Tests: kind, month and name, "Lab\|11\|CA 15-3" (an undated test has an empty month: "Data layer\|\|RNA-seq (STAR TPM)") | the Tests view, after every run |
| `pointer` | the finding an "Open" or a look-here "Spot" landed on: L4, T2, C14, a variant, "ER: IHC vs RNA", an Evolution row | "Open" (attention queue, overview cards), look-here "Spot" |
| `version` | the report version shown, when it isn't the latest (its index) | the version slider |

An address is applied once, when it is new to the browser session (a link opened, an address
typed or pasted): the version, the test, then the pointer, which lands the workbench on the
finding of that version's attention queue with that pointer (the lab value in the Spot panel,
the slide tile, the omics finding, the variant, the document's sentence, the Evolution row).
After that the reader moves freely and the address follows. Switching files drops the previous
file's test, pointer and version; an address the file can't answer (a test it doesn't hold, an
unknown pointer) opens the file as usual. Example:
`?patient=SYNTHETIC-001&view=Tests&test=Lab|11|CA 15-3&pointer=L4&version=11` opens the
synthetic patient's lab workbench as of month 12 with the CA 15-3 rise in the Spot panel.

**Recently opened files** (the last five of the browser session) are buttons above the patient
list.

## 3. The guide inside the app

**"?" on every screen** (`app/guide.py`), at the right end of the breadcrumb line, opens "How to
read this", a short panel in three tabs:
- **Labels**: observed, model inference, hypothesis, trust, placeholder, implemented,
  experimentally validated, planned, synthetic and SOS, one sentence each
  (`grammar.GLOSSARY`);
- **This screen**: what the screen's workbench shows and what it cannot see
  (`grammar.WORKBENCH_GUIDE`: the patient list, the report, each workbench, the Evolution view,
  imports, the timeline, Methods and validation), and the shared page layout;
- **Keys**: the attention queue's shortcuts, j next, k previous, p pin, m mark reviewed
  (Streamlit keeps r for its own rerun), u the unsure list, o open; Tab moves through the
  queue's buttons in that order.

**A first-visit walk-through** on the Patients page: four short steps (your patients; a file
opens on its latest report; every test has its workbench; read the labels), with Back, Next
and "Skip the tour"; finished or skipped, it stays away for the browser session.

**Chips explain themselves.** The status chips at the top of every workbench page and the
label row under the report's title are buttons: clicking "model inference" opens its one
sentence ("A model's or a rule's estimate from the data, with its uncertainty; not a
measurement."). A chip that names a label inherits that label's sentence ("placeholder
threshold", "subtype call: experimentally validated"). Chips inside sentences stay plain
badges; their meanings are one click away in the guide.

## 4. Wording, density and states

- **Plain clinical English.** No internal names on a screen: no file paths, module or function
  names ("finding_key", "pf", "FINDING_KINDS"), no "version index". Provenance stays: data
  source, method, model and version, in words ("precomputed offline from the open-access
  files", "Ensembl VEP, offline").
- **The report's cards** are one width (240 px) and wrap: three a row at 800 px, more on a wide
  screen. A card shows at most about 150 characters and ends in " …"; "more" opens the full
  text.
- **Numbers carry their unit**, and a hover says how they were measured (the slide's tumor
  area, front length, arcs, unsure share; the risk's percentile and model).
- **Empty states say what is missing and which test would provide it** (§1 has the workbench
  pages): "Not sequenced … Tumor sequencing (a panel or an exome, or a VCF or MAF brought in
  through Import tests) would fill this workbench".
- **Error states never show a traceback.** A view, a workbench, the patient list or the
  Methods page that fails says which part failed ("The blood and lab workbench could not be
  drawn"), that the rest of the file works, links the Methods and validation page, and names
  the error type logged for the team; the server's log keeps the traceback. The tests re-raise.

## 5. Sidebar and Patients page

- **Sidebar:** the product name and the line "Research and decision support for clinicians;
  not a diagnosis or a prescription"; **About this system** (collapsed: the model and its
  held-out C-index, the case agent, the treatment evidence, the literature search; these are
  provenance and stay); **Session**: the reviewer's initials, the live notes left, and this
  session's review marks and pins with "Download this session's marks (CSV)".
- **Patients page:** one line ("Your patient files. Open one to see its latest report, its
  tests in their workbenches and how the report changed over time."), search and filters as
  before, **Sort by** last update (an import of this session, then the record's latest month),
  risk (the TCGA files' cohort percentile; the synthetic patient's 12-month risk, another
  measure, listed after them) or open SOS; the open SOS count as the second column, "🔴 3 open"
  or "none" (the count is in words, never color alone); a Risk column; the recently opened
  files (§2).

## How it is tested

`tests/skeleton.py` reads the parts a page recorded (`st.session_state["page_parts"]`) and the
headings AppTest rendered (subheaders, "####" headings and expander labels, in page order): the
parts come in the skeleton's order, the required ones are there, and their headings appear in
that order on the rendered page. `tests/test_app.py` checks every workbench as the full app
opens it; `tests/test_pages.py` renders each page on its own in its empty state and checks that
it says what is missing and which test would provide it.
`tests/test_navigation.py` drives the whole app: the breadcrumbs and the header on the list,
in a file, in Tests and on the Methods page; an "Open" from the attention queue writing ?test,
?pointer and ?version and leading back to the queue's item; deep links reopening the lab
workbench on L4 as of month 12 and the Evolution view on its row; an address the file can't
answer; a look-here "Spot" writing the pointer and a file switch dropping it; the recently
opened files.
`tests/test_guide.py` walks the walk-through (next, back, skip, gone for the session), opens the
"?" on the list, the report, a workbench and the Methods page (each with its own "This screen"
text), clicks the report's and a workbench's chips, and checks every label's sentence.
`tests/test_states.py`: a workbench that fails (made to raise, with the tests' strict switch
off) says so in words, links the Methods page and leaves the tests table and the other views
working; the list's sort orders; the sidebar's session tally and its export; the report's
shortened cards with their full text behind "more".

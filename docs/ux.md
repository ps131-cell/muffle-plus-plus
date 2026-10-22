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

## 2. How the skeleton is tested

`tests/skeleton.py` reads the parts a page recorded (`st.session_state["page_parts"]`) and the
headings AppTest rendered (subheaders, "####" headings and expander labels, in page order): the
parts come in the skeleton's order, the required ones are there, and their headings appear in
that order on the rendered page. `tests/test_app.py` checks every workbench as the full app
opens it; `tests/test_pages.py` renders each page on its own in its empty state and checks that
it says what is missing and which test would provide it.

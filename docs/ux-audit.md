# UX audit, 2026-10-28

Two passes over the app as it was on main at 67647db (QA round 3 merged), then every finding in
three tiers with what was done about it. Screens looked at in headless Chromium at 1280 × 900
and 800 × 900 px, light, the sidebar open (as Streamlit keeps it at both widths): the Patients
page, SYNTHETIC-001's report and Tests view, Case 299's report and genomics workbench,
SYNTHETIC-001's Timeline, Methods and validation. The rules that came out of it are in
`docs/ux.md` §8; the decision in `docs/decisions.md` (2026-10-28).

## Pass 1: the design critic

- **Hierarchy.** A file's first screen is chrome. At 1280 px: breadcrumbs, the identity line,
  the views, an eight-button action row on two lines, a caption repeating the diagnosis and the
  disclaimer, a two-line yellow notice, the version slider, a 28 px report title, the chip row
  and the summary; the SOS tile, the one thing that must be seen first, starts at y ≈ 820. At
  800 px the action row takes four lines and no finding is on the first screen.
- **The trust chain is scattered.** The risk model, the driver mutations and their CIViC
  evidence are 1,000–3,000 px apart: on Case 299 the risk at y ≈ 4,400 and the CIViC items at
  y ≈ 5,300 of 6,553 px; on SYNTHETIC-001 the CIViC block at y ≈ 4,300 of 5,638. Provenance
  exists only on the cards' "Why?": the risk tiles, the variants and the CIViC lines carry no
  source, model version or evidence item id.
- **Typography.** Streamlit's default Source Sans at 16 px; a 44 px page title, 28 px
  subheaders, 36 px metric values ("0.93" set like a headline); variants, pointers, ids, money
  and counts in proportional type ("MAP3K1 S588Ffs\*3" reads as prose); inline code in green
  (#137a33, Streamlit's default code colour), so a pointer like `L4` reads as "normal".
- **Colour.** The chips are one coherent system (observed blue, inference violet, hypothesis
  orange, trust green/orange/red, placeholder always orange), but nothing codes a CIViC level
  or a variant's severity, and a risk chart's red/blue sits beside a metric's red/green delta.
- **Spacing.** 6 rem above the content, 5 rem side gutters at 1280 px (820 of a 980 px column),
  10 rem below; cards and tiles fixed at 220 px leave ~130 px empty at the right of every row;
  card text wraps at ~150 px, so cards run 300–400 px tall.
- **Generic defaults.** 40 px, 8 px-rounded bordered buttons for everything, including the
  three "Review" popovers on one CIViC block and the queue's row buttons; bordered boxes around
  everything; the federated training as a graphviz drawing of boxes; the system's status hidden
  in a closed "About this system" expander.
- **800 px.** 468 px of content: the action row four lines, cards two a row, the reports 7,900
  and 9,860 px long.

## Pass 2: a first-time, impatient user

1. **Patients.** A title, a sentence, the disclaimer, Start here, a four-step tour and a search
   box come before the list, which starts at y ≈ 1,220. Three search fields on one screen (the
   file picker, Search every file, the list's search): which finds my patient?
2. **Open SYNTHETIC-001.** "SOS: 7 open" in the header, but the SOS tile is below the fold;
   the yellow notice says "MSK-CHORD timelines" on the first screen (jargon before content).
3. **"Why 60%?"** The answer (what changed since the last version) is ~3,000 px down, under the
   attention queue and the cohort lookups.
4. **"What evidence is there for this mutation?"** Scroll past the queue, Where this patient
   sits, Similar patients, the record and the risk; the CIViC lines name no evidence item and
   say nothing on hover.
5. **Case 299's tumor-board note** without a key on the server: "Write the note with Nemotron"
   disabled, and the reason only on hover: an unmotivated control.
6. **"Is this costing money?"** Nothing on screen: the $25.50 cap and the spend live in code and
   a ledger file; the live-notes bar appears only on a server with a key.
7. **"Which hospitals trained this?"** The closed sidebar expander says "FedAvg across 3
   simulated hospitals" and one C-index; the per-site numbers are a sentence on Methods.
8. **Tests.** The launcher is clear; tiles stop at three a row with white space; "nothing
   flagged" is set as large as a finding.
9. **A workbench (genomics).** Dense but legible; the part headings (Overview, Details, Spot
   panel) are as loud as the title.
10. **Timeline.** Works; owned by the timeline session (below).
11. **Methods.** 17,900 px at 1280; the contents box helps; two 404s in the console on load.

## Findings by tier

| | Finding | What happened |
|---|---|---|
| **Critical** | | |
| C1 | The SOS tile below the fold on a laptop; no finding on the first screen at 800 px | **Done.** Top gap 6 → 4.5 rem, the identity caption without the repeated diagnosis, the synthetic notice compact, the action row's buttons 28 px and quiet (four lines → three at 800 px), a 17 px report title: the SOS tile starts at y = 629 (SYNTHETIC-001) and 409 (Case 299) at 1280 px, 784 and 564 at 800 px |
| C2 | The risk model, the mutations and their CIViC evidence 1,000–3,000 px apart | **Done.** The cockpit: three columns at 1280 px, stacked at 800 px (`docs/ux.md` §8) |
| C3 | No provenance on the risk, the variants or the CIViC items | **Done.** Hover on the risk heading (source data, method, release, each site's C-index, endpoint), on each variant (test, sample, assay, reads, VEP consequence and release, AlphaMissense, CIViC count), on each ladder rung, on each CIViC item (EID, level, direction, profile, match, disease), on each next item (source, reason, threshold); click: Open into the genomics workbench, the CIViC link, Open at each queue item |
| C4 | The case-note budget invisible | **Done.** The sidebar's status table and bar (spend on this server's ledger against the cap), the tumor-board note's status line, the Methods card "Case note service" (cap, spend, prices, how a call is refused) |
| **High impact** | | |
| H1 | Generic type and controls (16 px Source Sans, 36 px metrics, 40 px rounded buttons) | **Done.** IBM Plex Sans and Mono, 15 px base, compact headings, metrics, buttons, tabs, expanders, alerts |
| H2 | Inline code (pointers) in green | **Done.** Near-black on light grey, 14:1 |
| H3 | Variants, ids, amounts in proportional type | **Done** in the cockpit, the status table and the metric tiles (monospace); the workbench pages' own text is theirs (left) |
| H4 | Cards and tiles fixed at 220 px with an empty strip on the right | **Done.** A grid that fills the row: four a row at 1280 px, two at 800 px; card text 13 px |
| H5 | No colour code for CIViC levels or variant severity; red/blue vs red/green for risk | **Done** for levels (A–B green, C–E orange) and severity (Ensembl VEP: high red, moderate orange, low and modifier grey), on the Methods page's Colour code; risk changes in the cockpit red/blue like the charts. A metric tile's delta stays red/green (left: Streamlit's control; said in the legend) |
| H6 | Federated training's sites and C-indexes hidden | **Done.** The sidebar lists each simulated site's held-out C-index; Methods shows one status table (patients, deaths, held out, C-index, layer coverage) instead of the graphviz drawing |
| H7 | The tumor-board note's disabled buttons | **Done.** Only the buttons that can work; a status line says why the rest are not there |
| H8 | The action row loud and four lines at 800 px (QA R3-8) | **Done.** Same buttons and order, smaller, grey until hover: two lines (62 px) at 1280 and at 800 px. Under 1024 px its Methods link and How to read this are hidden: the sidebar's navigation and the breadcrumb's "?" hold them |
| H9 | Workbench part headings as loud as the title | **Done.** Small capital labels over a hairline (`_page.py`'s h4, by CSS) |
| H10 | The Patients page: three blocks and three search fields before the list | **Left** (decided in round 11, user-reviewed: Start here, the tour and Search every file stay above the list); the compact type lifts the list by ~200 px |
| **Nice to have** | | |
| N1 | The sidebar's blurb repeats the Patients page's intro | **Done.** One line and the disclaimer |
| N2 | "Review" popovers bordered on every line | **Done.** Tertiary (text) style |
| N3 | Emoji and Material icons mixed (🗂️ 📖 🗳️ in the navigation, 🔴 in the list) | **Left:** the list's "🔴 n open" is asserted by tests and named in the video |
| N4 | The chip row's chevrons read as dropdowns | **Left:** they open each label's meaning; the affordance is right |
| N5 | The version slider long and thin for 16 versions | **For the timeline session** (it owns the version selector) |
| N6 | Methods: two 404s in the console on load | **Left:** Streamlit's own `/methods/_stcore/health` and `host-config` requests (a page address's path; it retries at the root); nothing of ours |
| N7 | Bold paragraphs as headings: no heading outline for a screen reader on the report | **Left:** headings would join the Methods contents test and the anchors; after the freeze |
| N8 | A first load paints Streamlit's default layout for ~0.5–2 s before the theme sheet (a style-only `st.html` applies after the first elements) | **Left:** reruns keep it (measured); the config's fonts and colours apply from the first paint |

## Before and after, measured

Page height in px (headless Chromium, `~/muffle-ui` on 67647db, then this branch):

| Screen | 1280 px | 800 px |
|---|---|---|
| Patients | 1,933 → 1,570 | 2,404 → 1,996 |
| SYNTHETIC-001 · Report | 5,638 → 4,100 | 7,920 → 6,031 |
| Case 299 · Report | 6,553 → 4,767 | 9,862 → 7,797 |
| SYNTHETIC-001 · Tests (labs workbench) | 7,123 → 5,897 | 9,405 → 7,818 |
| Case 299 · Genomics workbench | 7,026 → 5,595 | 9,215 → 7,540 |
| SYNTHETIC-001 · Timeline | 4,009 → 3,431 | 5,092 → 4,322 |
| Methods and validation | 17,892 → 15,419 | 23,894 → 21,471 |

No exception, error box, cut text or sideways scroll on any of them, before or after; the
overlap check flags a CIViC line's wrapped link against its id (a two-line link's box, not an
overlap on screen). The report's risk model, mutations and CIViC items now sit within one
screen of each other: the cockpit spans y = 1,277–2,340 on Case 299 and 1,472–2,196 on SYNTHETIC-001 at 1280 px (stacked at 800 px: 2,033–4,040 and 2,088–3,428).

## For other owners

- **Timeline** (timeline session): N5; the version slider and Compare versions are unchanged.
- **Video and Devpost text** (`docs/video.md`, `docs/submission.md`): the sidebar's About this
  system is open by default and reads "Held-out C-index 0.728" and "Case agent live" as table
  rows; shot 3's scroll from the cards to **Attention** now passes the cockpit; shot 4's
  **Show the saved note** is still there for Case 299. Re-walk after the freeze.
- **`CLAUDE.md`** still says "freeze Oct 28"; the decision of 2026-10-28 moves it to Oct 29
  10:00 CDT.

## Round 15: workbenches (2026-10-28)

The user, after round 14: "I really don't want the app to look ugly and generic streamlit app
... but functionalities take precedence." The seven non-map workbenches (labs, ctDNA, genomics,
omics, documents, Evolution, Imports), Feedback and Methods still read as default Streamlit:
71 `st.dataframe` grids (one-line cells cut mid-word, no monospace, no chips), 26 `st.metric`
tiles (36 px values; omics' showed an up arrow beside a negative z-score), default Altair axes
with vertical gridlines, and an empty file announced in a blue alert. The pieces that replace
them are in `docs/ux.md` §8.1; done in this order, which was also the cut order:

| | Step | What happened |
|---|---|---|
| 1 | One chart theme | **Done.** `app/charts.py` `THEME` (`alt.theme.register`, Altair 6.3.0), enabled when `charts` is imported; every workbench `Page` imports it before drawing. IBM Plex Sans, muted 12–13 px labels, hairline axes, no frame, no vertical gridlines, compact legends, the validated categorical order; the per-chart `configure_axis` overrides are gone. The slide, radiology, report and Timeline charts take it too: checked before and after (the MRI kinetics chart's labels a little darker and its plot unframed; the Timeline lanes and the report unchanged in height) |
| 2 | Finding tables | **Done.** `_page.table`: no direct `st.dataframe` call is left in the nine files. Short, narrow lists (at most 25 rows, 8 columns) are `st.table` with Markdown cells: values, pointers, months, ids and variants in monospace, evidence and status as the grammar's chips, CIViC levels and VEP severities in their colours, links as their text, a sticky header and a 28 rem cap; long, wide, sortable or row-click lists stay Streamlit's grid (30 px rows, chips as coloured pills). Every row click into a Spot panel is still a grid row click |
| 3 | Number strips | **Done.** `_page.strip` replaces the metric tiles of genomics (overview, gene Spot, burden), omics (subtype call, scores, methylation index, ECM3, immune signatures, layer cards) and Feedback; omics' what-if risk percentile stays `st.metric` (its delta, in percentile points, means a change) |
| 4 | Hover provenance | **Done** on each main chart: labs' trends add where the reference interval comes from; ctDNA the rule with its status and the synthetic label; the copy-number landscape its ASCAT3 source and label; burden, allele fractions, the pathway map, the subtype bars, promoter methylation, the clonal panel and Feedback's chart their label or source; the Evolution record grows the pointed event. Tooltips are a small bordered card |
| 5 | Empty states and labels | **Done.** `_page.empty` for the no-labs, no-ctDNA, not-sequenced, no-copy-number, no-expression, no-driver and no-marks cards (a Material icon instead of an emoji); every `st.info` is drawn as a quiet card. An evidence column joined the lists that had none (caution windows, variant calls, CIViC items, allele fractions, what to watch next, clonal pairs, an import's documented facts) |
| R4-1 | Captions fade their chips (QA round 4, handed over) | **Done.** Captions at full opacity in the muted ink (#4d5260, 7.6:1): their chips and links keep their own AA colours; `tests/test_states.py` reads the rule |

**Left, on purpose:** the grid can't be monospace or hold Markdown (it draws on a canvas in the
body font), so long lists keep the sans face; the slide and radiology pages' own tables and
metrics (perf-memory's files) and the shell's report and Patients tables are their owners'; the
Imports page's typed-values editor stays `st.data_editor`.

Page height in px (headless Chromium; main at dbf9d29, then this branch):

| Screen | 1280 px | 800 px |
|---|---|---|
| SYNTHETIC-001 · labs | 5,952 → 5,928 | 7,921 → 7,897 |
| SYNTHETIC-001 · ctDNA | 5,193 → 5,160 | 6,773 → 6,740 |
| Case 299 · genomics | 5,569 → 5,432 | 7,415 → 7,238 |
| Case 299 · omics | 5,588 → 5,525 | 7,574 → 7,512 |
| Case 299 · documents | 5,324 → 5,373 | 7,101 → 7,415 |
| Case 299 · Evolution | 2,943 → 3,203 | 3,869 → 4,170 |
| SYNTHETIC-001 · Import tests | 1,741 → 1,741 | 2,252 → 2,252 |
| Feedback (no marks yet) | 1,008 → 1,012 | 1,260 → 1,262 |
| Methods and validation | 16,544 → 16,613 | 23,372 → 24,034 |
| Case 299 · slides (not changed) | 6,110 → 6,110 | 8,643 → 8,643 |
| Case 563 · radiology (not changed) | 5,249 → 5,249 | 6,867 → 6,867 |
| Feedback with two marks | 1,916 → 1,881 | 2,251 → 2,245 |

The reports (Case 299 4,781 / 7,764, SYNTHETIC-001 4,100 / 6,119) and the Timeline (3,362 /
4,053), whose charts take the theme, kept their heights.

### The round's second PR (the orchestrator's follow-up)

- **Cut cells.** A list with more than 8 columns had fallen back to the grid, which draws one line
  a row: the labs page's Rise confirmation and caution windows cut their sentences and clipped
  their last column at 1280 px. A static table now takes up to 12 columns and wraps in its
  box: sentences between words, DOIs and lists of drugs at their slashes, dots and commas,
  links where they must, field names with spaces, long words hyphenated in a narrow box; the
  4.5 rem column minimum is gone. No word breaks inside otherwise: a first version let any
  word break in a narrow box, and the screenshots (not the walk's measurements) showed a
  squeezed column print 213 tiles as "21" over "3", a push of 0.233 over three lines and arc
  A1 as "A" over "1"; letting only prose or only header labels break still split ids and short
  labels, because auto table layout shares the spare width by each column's longest line and
  starves the short ones; even a hyphen ended a line inside "CA 15-3" (now joined to its
  digits). So a table whose whole words cannot fit a narrow box scrolls inside
  its own box, its first column held and a shadow on the edge that has more; headers there are
  a size smaller (two, with 3 px padding, at eight columns or more), which brought the labs
  page's Rise confirmation and Early after a therapy change inside 457 px at 800 px. Traps on
  the way: Streamlit's Markdown container in each cell resets `overflow-wrap` and its chips are
  `nowrap`, so the rules sit on them, not on `td`; a table in
  a half-width column at 1280 px is narrow without the page being so, so the narrow rules are a
  container query on the table; and a table's minimum width is the sum of its columns' longest
  words (the 19-analyte reference table: 948 px in a 922 px box at 1280 px), so a table of nine
  columns or more takes denser type and padding at any width. Every static table was walked
  with every section and tab open, at 1280 and 800 px: twelve pages, then every patient's
  workbenches (one test each, eight files) and Evolution views, 361 table views (the list is in
  the PR), including the Sequencing › Resistance watchlist that qa-4 found 112 px too wide on
  main. None cuts a cell or reaches past the main column. At 1280 px all 181 fit their box; at
  800 px, where the open sidebar leaves a 457 px column, 24 of 180 scroll inside their box by
  7–217 px (the slides page's half-width lymphocytes table, the labs reference table, the MRI
  candidates, the CIViC and variant tables) and the page never does. Shares now show as the
  grid's "percent" preset did.
- **The slide and radiology pages** take the tables, strips, empty cards and chips around their
  maps (which are untouched): slides 12 metric tiles → 3 strips and 13 grids → finding tables
  (the Spot panel's class scores keep their bars in a grid, the confusion matrix its row labels);
  radiology 10 grids → finding tables, three empty cards.

| Screen | 1280 px | 800 px |
|---|---|---|
| Case 299 · slides (main 543c135 → branch) | 6,110 → 6,081 | 8,643 → 8,665 |
| Case 563 · radiology | 5,249 → 5,294 | 6,867 → 7,021 |
| SYNTHETIC-001 · labs | 5,928 → 5,928 | 7,897 → 7,897 |

Where a page grew, it is a static table showing text the grid had cut; a first try that put a
13-column lab history in `st.table` wrapped its rows four lines deep, hence the column limit.
No exception, error box, cut text or sideways scroll of the page on any of them.

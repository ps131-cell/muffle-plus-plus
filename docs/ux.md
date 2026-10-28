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
| The picture | the page's main view: map, viewer, chart or table | its own name: Trends, Allele fractions over time, Variants and the tumor's genome, Slide map (the slide viewer one click away), Subtype and pathway scores, The record over time, Imported in this session |
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
| Pathology slides | Slide map: the section's scan with seven views (the slide viewer one click away, down to single cells) | direction of invasion, cells, satellite islands, risk map, quality control, every look-here pointer, and for files with several sections the sections compared and side by side (the second viewer loads only when opened) | one tile |
| Expression, methylation and protein | Subtype and pathway scores | receptor consistency, protein pathways (RPPA), promoter methylation, the immune and stromal picture, the data layers, the what-if | one finding |
| Evolution | The record over time | what to watch next (a row opens the Spot panel), the rows not raised and why, clonal order, trials | one hypothesis, with the evidence for and against and its CIViC items |
| Import tests | Imported in this session | rejected on intake, what each adapter accepts | none |
| Radiology, an image study (MRI) | Viewer (series, candidate, slice, window and level, overlays) | three planes, the cine through the phases (loaded when opened), candidates, since the last study (or the change view on a public example pair, loaded when opened) | one candidate: size, volume, kinetics, how its box was chosen, the model |
| Radiology, a mammogram | Mammograms (the four views) | left and right, CC and MLO linked | none |
| Radiology, reports only | Imaging reports (each read in its words; an imported report with what its import read and set aside) | lesion table, change between reads, the change view on a public example pair (loaded when opened), against the tumor marker | one named site |
| Clinical documents | Documents (the rules' facts in yellow, the named-entity model's spans underlined in violet) | documented facts, the rules and the model side by side, the model's spans, documented versus inferred, conflicts between documents, the documents over time | one documented fact or model span: its sentence with both layers, the rule or the model and its score, the other reader's value, its review mark and pin |

The radiology page joined on 2026-10-22 after its second round, the clinical documents page with its own (#123).

## 2. Navigation

**Breadcrumbs on every screen** (`app/navigation.py`): "Patients › Case 299 › Tests ›
Pathology slide". "Patients" goes back to the list; the file's crumb is the file picker itself
(type or pick another patient to switch files); then the view, and in Tests the workbench open
(in the attention queue's short names) and the test opened (its kind, or its name where the
kind says little): "Tests › Labs › CA 15-3, month 11", "Tests › Expression › RNA-seq (STAR
TPM)", "Tests › Slides › Pathology report, month -40" (the synthetic diagnosis opens the slide
workbench on a public example region); the workbench is left out where the test already names
it ("Tests › Imaging, month 12"). The crumbs sit in the sticky header, so where the reader is
stays on screen while a workbench scrolls (2026-10-27). The Methods and validation page carries
"Patients › Methods and validation".

**The patient header stays on screen** while the page scrolls: the breadcrumbs, the patient's
identity and diagnosis, the open SOS alerts ("SOS: 2 open", alerts no reviewer has marked yet,
as of the report version shown; "SOS: none open" otherwise), the version shown when it isn't
the latest, and the view control (Report, Tests, Timeline, Evolution, Import tests). The report
version slider sits under it. It sticks below Streamlit's toolbar in windows 1024 px and wider
(about 120 px tall at 1280 px); in a narrower window it wraps onto more lines and would cover a
quarter of the screen, so there it scrolls away with the page. Streamlit 1.66 wraps the header
in a layout wrapper of its own height, so the wrapper is what sticks (`app/navigation.py`).

**The Tests launcher** (2026-10-27). Tests opens on a tile per test, grouped by kind, in rows
that wrap (220 px tiles: three a row at 1280 px, two at 800 px with the sidebar open). A tile
names the kind and the test, says what it holds (the result, "Latest: …" for a series), its
status chip and scope ("report text, no images", "example region, first version"), "imported
this session" where it applies, how many look-here items of its workbench's `queue()` open at
it ("4 items to look at (month 4, 11, 16, 24)", or "nothing flagged") and "Open". A dated
series of one test (CA 15-3 at eight months, the twelve ctDNA samples) is one tile with a pill
per month, so 29 tests fit in six tiles: a pill opens that month's test, "Open month 24" the
latest. The open test's tile says "open below" (or "month 11 open below"), and the breadcrumb
names it. Every test is also a row of **Show all n tests as a table**, collapsed under it, where
selecting a row opens it too. Deep links, the attention queue's "Open" and the overview cards'
"Open" land as before.

**The file's action row** (2026-10-27), right under the sticky header on every view (it
scrolls away with the page: two lines of buttons in the header would cover a third of a 900 px
window), each with a one-sentence tooltip: **Attention queue (n)** (n items not marked yet; it
opens the report's queue on the first of them), **Import a test**, **Compare versions** (the
Timeline's comparison; disabled, saying why, while the file has one version), **Export this
report (Markdown)** (the version shown, built when clicked), **Your marks (n)** (this file's
review marks: a link to the Feedback page, as in the sidebar, since `st.switch_page` refuses
to leave a page whose ?patient is bound to the file picker) and **How to read this** (the guide
of the screen shown). Each screen has one primary action: the queue's Open on the report, the
launcher on Tests, "Jump to this version" on the Timeline ("Back to latest" and the case note's
button are secondary). Under the queue's header a **Next step** line says what to do: "12 items
need a look: press j for the next one, or click a row's Open".

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
list, under the **pinned** files ("Pin this file" in a file's action row; for the session).

**Start here** (2026-10-27): until a file is opened in the browser session, a card above the
tour offers two files, each a button with one line on what it shows: "Open the longitudinal
example: SYNTHETIC-001" (the synthetic patient over 24 months) and "Open a case with its own
slide and sequencing: Case 299" (Case 299 holds its own H&E section, mutations and pathology
report but no scan; Cases 563 and 926 hold a scan and a slide). The tour's four steps name
these buttons, the file's action row and the Tests launcher.

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

**How to use this page** (2026-10-27, `app/workbenches/_howto.py`): one line under each
workbench's title says what the picture shows, what the look-here list is and where the Spot
panel is; it is open on the page's first visit in the browser session and folded into an
expander once the reader has been on another workbench. Under it, "Jump to" links reach the
Spot panel, the Model and validation card, What this test cannot see and Export. The
look-here items read as instructions: what to look at, why (the reason's main clauses, its
thresholds and citations on hover), the consequence in words and the pointer the Spot button
opens.

**Chips explain themselves.** The status chips at the top of every workbench page and the
label row under the report's title are buttons: clicking "model inference" opens its one
sentence ("A model's or a rule's estimate from the data, with its uncertainty; not a
measurement."). A chip that names a label inherits that label's sentence ("placeholder
threshold", "subtype call: experimentally validated"). Chips inside sentences stay plain
badges; their meanings are one click away in the guide.

**Nothing hidden behind an unlabeled click** (2026-10-27). Every button, popover, picker and
toggle of the shell (the patient list, the file, the report, the guide, the timeline, the page
helper) says in one sentence on hover what it does, and every download in the app names its
format; a test reads the code for both. The shell's expanders start with a verb and carry a
count ("Show the caveats, data sources and model versions (5)", "Show what you pinned and
reviewed: 1 pinned, 2 marked", "Show all 29 tests as a table"); the workbench pages' details
keep their "Name (count)" headers (§1), which their tests and pages share. Methods and
validation is one click from the file's action row and from every workbench's Model and
validation card; the Feedback page from "Your marks". A button that opens a view carries that
view's one icon (Timeline on "Compare versions", Import tests on every "Import a test",
Evolution on "Open the Evolution view"); the view control itself stays plain, since a control
bound to the address would put the icon into `?view` and break every link. An address whose
`?view` names no view opens the report. The queue's keys sit in a thin bar under it (`j` next ·
`k` previous · `p` pin · `m` mark reviewed · `u` unsure list · `o` open).

## 4. Wording, density and states

- **Plain clinical English.** No internal names on a screen: no file paths, module or function
  names ("finding_key", "pf", "FINDING_KINDS"), no "version index". Provenance stays: data
  source, method, model and version, in words ("precomputed offline from the open-access
  files", "Ensembl VEP, offline").
- **The report's cards** are one width (220 px since 2026-10-27, 240 before) and wrap: two a
  row at 800 px with the sidebar open (Streamlit keeps the sidebar open at 800 px, which leaves
  the page about 470 px), four at 1280 px since 2026-10-28, each row filling the page (§8). A card shows at most about
  150 characters and ends in " …"; "more" opens the full text. Since 2026-10-27 a card ends in
  a full-width **Open** naming where it lands ("Open ·
  Sequencing, month 0", "Open · Timeline"), under its **Why?**; a workbench with nothing to
  show in the file is a card of its own: why ("no ctDNA sample in this file"), what would fill
  it, and **Import a test** where Import tests takes that test (the line "Not in this file: …"
  it replaces said the same in one sentence).
- **Numbers carry their unit**, and a hover says how they were measured (the slide's tumor
  area, front length, arcs, unsure share; the risk's percentile and model).
- **Metric tiles show their values whole.** A tile's value is short and its unit sits in the
  label ("Immune signature, cohort percentile": 41st, z −0.22 under it); a row of tiles is a
  horizontal container whose tiles take their own width and wrap to a second row on a narrow
  screen, never fixed columns that cut "75th percentile" to "75th perc…". A test holds every
  `st.metric` in the app to this.
- **Empty states say what is missing and which test would provide it** (§1 has the workbench
  pages): "Not sequenced … Tumor sequencing (a panel or an exome, or a VCF or MAF brought in
  through Import tests) would fill this workbench".
- **Error states never show a traceback.** A view, a workbench, the patient list or the
  Methods page that fails says which part failed ("The blood and lab workbench could not be
  drawn"), that the rest of the file works, links the Methods and validation page, and names
  the error type logged for the team; the server's log keeps the traceback. The tests re-raise.

## 5. Sidebar and Patients page

- **Sidebar:** the product name and the line "Research and decision support for clinicians;
  not a diagnosis or a prescription"; **About this system**, open, a read-only status table
  since 2026-10-28 (§8): the risk model and its release, the held-out C-index and each
  simulated site's, the case agent (live or saved notes only), planner and writer, the
  case-note spend on this server's ledger against the hard cap (with a bar), the live notes
  left this session, the treatment evidence, the literature search, the code's version;
  **Session**: the reviewer's initials and this session's review marks and pins with
  "Download this session's marks (CSV)".
- **Patients page:** one line ("Your patient files. Open one to see its latest report, its
  tests in their workbenches and how the report changed over time."), search and filters as
  before, **Sort by** last update (an import of this session, then the record's latest month),
  risk (the TCGA files' cohort percentile; the synthetic patient's 12-month risk, another
  measure, listed after them) or open SOS; the open SOS count as the second column, "🔴 3 open"
  or "none" (the count is in words, never color alone); a Risk column; the recently opened
  files (§2).

## 6. Speed and feel

Every view and workbench was timed with `scripts/time_views.py` (AppTest on the release bundle
`demo-bundle-v2`, one script cache shared across runs as on a server), in WSL on this PC's
8-core CPU shared with other sessions (load average 6.6 to 7.3 during the runs). Main before
this work (8fa143a) and this work ran alternately, twice each; the table gives the mean of the
two rounds, and a rerun is the median of three. Seconds:

| File · screen | Open, before → after | Rerun, before → after |
|---|---|---|
| Patients (the process's cold start; a rerun) | 16.3 → 15.9 | 0.11 → 0.10 |
| SYNTHETIC-001 · Report | 0.48 → 0.58 | 0.40 → 0.40 |
| SYNTHETIC-001 · Tests, Timeline, Evolution, Import tests | 1.00 → 0.76, 0.54 → 0.54, 0.73 → 0.51, 0.10 → 0.11 | |
| SYNTHETIC-001 · Blood and lab (CA 15-3) | 0.82 → 0.77 | 0.98 → 0.82 |
| SYNTHETIC-001 · ctDNA | 0.89 → 0.82 | 0.85 → 0.79 |
| SYNTHETIC-001 · Genomics | 0.96 → 0.38 | 0.83 → 0.32 |
| SYNTHETIC-001 · Radiology | 0.29 → 0.33 | 0.17 → 0.20 |
| SYNTHETIC-001 · Clinical documents (a pathology report; a clinic note) | 1.31 → 0.96; 0.23 → 0.18 | 0.67 → 0.59; 0.21 → 0.17 |
| Case 299 · Report | 0.78 → 0.79 | 0.67 → 0.29 |
| Case 299 · Tests, Timeline, Evolution, Import tests | 1.48 → 0.50, 0.08 → 0.13, 0.24 → 0.31, 0.06 → 0.09 | |
| Case 299 · Pathology slide | 2.24 → 2.29 | 1.05 → 1.12 |
| Case 299 · Expression, methylation and protein | 0.57 → 0.66 | 0.62 → 0.57 |
| Case 299 · Clinical documents | 0.19 → 0.19 | 0.15 → 0.17 |
| Case 730 · Report | 0.57 → 0.62 | 0.57 → 0.24 |
| Case 730 · Tests, Timeline, Evolution, Import tests | 1.60 → 0.41, 0.11 → 0.11, 0.18 → 0.14, 0.08 → 0.10 | |
| Case 730 · Pathology slide | 4.35 → 2.94 | 1.53 → 1.50 |
| Methods and validation | 0.82 → 0.78 | 0.86 → 0.82 |

Faster: the TCGA files' Tests view (it opens on the genomics workbench, whose hidden tabs now
wait for a click), the genomics workbench, the TCGA report's reruns (its two charts are built
once per case), Case 730's slide workbench on first open (the comparison of its sections reads
their stored numbers). The rest is within 0.1 s either way: the breadcrumbs, the sticky header,
the "?" button and the session block are drawn on every run. The Timeline figures predate the
Timeline's lanes (#117), which landed after these runs.

What changed:
- **Lazy where it pays.** Content that is hidden runs only while it is open: the "?" panel
  (half of every rerun when it was first built), the genomics picture's tabs other than
  Variants, the lab trends' panels other than the one open, the second slide viewer of "The
  sections side by side", the radiology cine and the public example pair. The comparison of
  sections reads the other sections' stored numbers instead of analysing them again. Each
  page's look-here items are computed once per browser session, file state and version. The
  TCGA report's two charts are built once per case as Vega-Lite specs (Altair took about half
  a second to encode the cohort histogram on every rerun). Per-case folders were already read
  on demand and cached per process (a scored section, the omics scores, the genome numbers,
  the pathology reports).
- **How it was measured**: `scripts/time_views.py`. AppTest alone re-parses the 1,300-line
  shell on every run (Streamlit's "magic" pass, 0.4–0.8 s under load), which a server does once
  per process; the script shares one script cache across runs, as a server does.
- **Spinners that say what loads**: "Opening the pathology slide workbench…", "Gathering the
  report: every workbench's findings and the attention queue…", "Reading the scored section…",
  "Reading the precomputed expression, methylation and protein scores…", "Checking
  ClinicalTrials.gov…".
- **The slide viewer's first open** shows a progress bar in megabytes ("Fetching this section's
  tiles, once for this server: 12 of 40 MB", then "Checking and unpacking the tiles…"); a failed
  download is tried again after 10 minutes.
- **The Methods and validation page** opens on a contents box: every section, and every card of
  Models and Rules, as links (a test keeps it complete).
- **Phone width.** Columns stack, the breadcrumb line, the report's cards and the rows of
  metric tiles wrap, the patient list keeps its Patient column pinned, wide tables scroll inside
  themselves; the patient header scrolls away with the page (it sticks from 1024 px up).

## 7. Accessibility basics

- **Color is never the only signal**: every chip and badge carries its word (observed, trust:
  weak, placeholder threshold), the open SOS count is "🔴 3 open" or "none", the maps have
  legends, and the look-here rows name the evidence and the trust in text.
- **Contrast**: badges use Streamlit's palette (dark text on a light tint), with the orange,
  gray and green text, the primary blue and the body text darkened in `.streamlit/config.toml`
  so that badges, primary buttons and captions reach 4.5:1 (WCAG AA; a test reads the
  config); the sticky
  header is opaque with the page's own background and text colour in either theme, worked out
  in CSS (it inherits the background Streamlit's app root paints, `Canvas` where a browser
  lacks `:has()`), so changing the theme in the settings menu needs no rerun; a colour picked in
  Python from `st.context.theme` went stale after a theme change and left a black band on a
  light page.
- **Alt text** on every image (slide crops and thumbnails, an imported image's preview) and on
  the main charts (each lab trend in words, the allele fractions, the copy-number landscape,
  the pathway map, the tile map, Evolution's record over time, the clonal allele fractions,
  the risk position and the layer contributions, the Timeline's lanes and its risk over time).
- **Keyboard triage**: the attention queue's buttons come in tab order (previous, next, pin,
  mark reviewed, unsure list, open), each says its key on hover (j, k, p, m, u, o), and the
  guide's Keys tab lists them.

## 8. Type, density and the report's cockpit (2026-10-28)

The two-pass audit behind this section is `docs/ux-audit.md`.

- **Type.** IBM Plex Sans for text and IBM Plex Mono for what a reader matches character by
  character: variants (`PIK3CA H1047R`), pointers (`L4`), evidence item ids (`EID7318`), metric
  values, amounts and the status table's values (SIL OFL 1.1, served from `app/static/fonts`;
  the browser's sans-serif and monospace if a file fails). A 15 px base; headings 1.75, 1.375
  and 1.125 rem; a workbench part's heading (Overview, Details, Spot panel …) is a small
  capital label over a hairline. Inline code is near-black on light grey: Streamlit's default
  green read as "normal".
- **Density.** 1.5 rem side gutters and a small gap under the toolbar (not 5 and 6 rem); 30 px
  buttons (28 px in the file's action row) with 4 px corners; compact chips, metric tiles, tabs, expanders and alerts. The
  file's action row is quiet (grey, no border until hover): two lines at 1280 px and at
  800 px (four lines, about 180 px, before; QA R3-8). Under 1024 px its Methods and validation
  link and How to read this are hidden: the sidebar's navigation and the breadcrumb's "?" hold
  them. The report's cards and the Tests launcher's tiles keep
  their 220 px minimum and fill the row (four a row at 1280 px, two at 800 px).
- **The cockpit.** Under the summary and the cards (the SOS tile first), three columns side by
  side at 1280 px and stacked at 800 px (`app/theme.css` grids keyed containers; without the
  sheet they are 300 px columns that wrap):
  - **Risk model** (model inference): the estimate and its uncertainty as metric tiles, then
    why: each data layer's effect and the patient among the cohort (a TCGA file), or what
    changed since the last version as signed chips, red raising the risk and blue lowering it
    (the synthetic patient). Its heading's hover: source data, method, release, validation
    (each simulated site's held-out C-index), endpoint. Review mark beside it.
  - **Driver mutations · CIViC**: each observed variant once, in monospace, with its
    consequence severity (Ensembl VEP's table: high red, moderate orange, low and modifier
    grey), its allele fraction and reads where the build's read counts belong to the file, its
    strongest CIViC level (A–B green, C–E orange, none grey), the five-rung evidence ladder
    (detected, interpreted, effect, therapy, resistance; a rung is coloured by its evidence
    label when present, grey when not; every rung's lines and what would strengthen it on
    hover), up to three CIViC items with their level, therapies, significance, citation link
    and evidence item id (hover: the item's level, direction, profile, match, disease), each
    with its review mark; **Open** lands on the variant in the genomics workbench.
  - **What to look at next**: the attention queue's four strongest unmarked items (reason and
    threshold on hover, **Open** at each), what to watch next (Evolution; the test that would
    detect each on hover; **Open the Evolution view**), what would reduce uncertainty
    (expectation and source on hover). The whole queue, with its keys, follows the cockpit.
- **The record** (observed: characterization, areas of risk, missing data and what it limits)
  sits in two columns under the cohort lookups; the tests that disagree, the caveats, the
  export and the tumor-board note follow as before.
- **The case-note service** is on screen where it acts: the tumor-board note says who plans and
  writes, the live notes left, the hard cap and this server's spend, and shows only the buttons
  that can work (no disabled "Write" without a key, no "Show the saved note" without one);
  Methods has a **Case note service** card (cap, spend, prices, how the gate refuses a call).
- **Colour code**, one key on the Methods page under its contents: evidence labels, module
  status, placeholder (always orange), trust, SOS, CIViC levels, variant severity, risk change.
  Colour is never the only signal: every chip keeps its word.

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

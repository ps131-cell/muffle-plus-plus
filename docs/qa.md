# QA passes over the clinician application

Round 1 (2026-10-20, Streamlit's AppTest) first; round 2 (2026-10-22, every screen in headless
Chrome, read by eye) next; the performance pass (2026-10-27), keeping the hosted app awake, and
round 3 (2026-10-27, every screen again after the Oct 27 PRs) at the end.

## Round 1 (2026-10-20)

A walk through everything a clinician can open, with what was found, its cause and its status.
Method: Streamlit's AppTest drove the real app (`app/streamlit_app.py`) on the release bundle
`demo-bundle-v2` (40 held-out TCGA cases) and SYNTHETIC-001, in WSL on a copy of the repo on the
Linux filesystem; the browser pane checked widths and the hosted app. The walk scripts live in
the QA session's scratchpad, not in the repo: they read the real bundle, which tests don't.

### What was walked

- **Every patient file in every view:** the 41 files × Report, Tests, Timeline, Evolution and
  Import tests; SYNTHETIC-001 at all 16 report versions; every test row's workbench at the
  first, middle and latest version (labs, genomics, slides, omics, clinical record, documents,
  imaging reports); compare of the first and the latest version. 719 steps.
- **Imports of every kind** (lab CSV with a rejected row, a pathology report, a clinician note,
  a slide region PNG, a DICOM file with identifying fields) into SYNTHETIC-001 (month 27) and
  Case 299 (month 0): every view and every new test's page.
- **Every button** on SYNTHETIC-001 (all views, every test's workbench), Case 299 (own slide)
  and Case 864 (omics): 79 clicks, each checked for exceptions and for changing nothing.
- **The Methods and validation page**, the patient list with its SOS filter, an 800 px wide
  pane with the sidebar collapsed and a 375 px phone viewport.
- **Logged problems:** exceptions, Streamlit warnings (duplicate keys, deprecations, missing
  session keys), Arrow conversion fallbacks (logged by Streamlit at INFO level only), empty
  tables, views over 3 s.

After the fixes below the whole walk ran again on main (843 steps, now also catching Arrow
fallbacks): no exception, no warning, no Arrow fallback. The packages the walk imported match
`app/requirements.txt`; `openai`, `tavily-python`, `pypdf` and `pydicom` load only for live notes
and PDF or DICOM imports, and nothing it lists goes unused.

### Findings

Timings are AppTest reruns on this PC's 8-core CPU in WSL, shared with four other sessions;
the load average is quoted with each.

| # | Where | Finding | Cause | Status |
|---|---|---|---|---|
| 1 | Whole app | No exception, no Streamlit warning (duplicate widget keys, deprecated calls, missing session keys) in 719 steps over all 41 files and every view, nor in the imports and the 79 button clicks | – | nothing to fix |
| 2 | Omics workbench and clinical record (every TCGA file) | Each click took a median 3.6 s, up to 7.9 s (load average 4–10); opening a TCGA file took up to 4.3 s | torch's default thread pool (8 threads) on single-patient inference: one masked-effects pass took 1,759 ms with 8 threads and 8 ms with 1 at load average 3 | fixed (#91): `torch.set_num_threads(1)` on every run. At load average 12–16 the omics workbench went from 7.5 s to 0.4 s and a file open from 4.3 s to 0.3–0.8 s |
| 3 | Slide workbench, cases 730 and 1043 | "The sections compared" table mixed numbers and words in one column ("no front: not assessed", "desert"), so Streamlit re-typed it silently on every render | a transposed table of mixed measures | fixed (#91): shown as text. Tests now fail on any Arrow fallback (`tests/conftest.py`) and on any Python warning in the app test |
| 4 | Slide workbench | Every click re-read the section's files and re-ran the geometry: 1–2.8 s per click (load average 12–16) | no cache | fixed (#91): one cached computation per section; 0.45–1.1 s per click (load average 5–10) |
| 5 | Report, genomics workbench | Variant names lost their asterisks and italicized the text between them ("RUNX1 D96Gfs*15, TP53 R196*" read "RUNX1 D96Gfs15, TP53 R196") | variant names passed to Markdown | fixed (#90, #93): `grammar.esc` in the record list, the mutations line, the CIViC blocks, the genomics page and its review queue, the omics record list and the case note (the note keeps its own bold and italics) |
| 6 | Every workbench | "Implemented" was blue on the report, gray on the lab page, green on genomics, documents, evolution and import; "planned" gray or blue | one color map per page | fixed (#90): one map (`muffle.workbench.grammar`); a label naming a placeholder is always orange |
| 7 | Every workbench | The model card was "Rules card", "Data and method card", "Model and validation card" or an expander; what a test cannot see was "What this map cannot see", "Limits", inline, in an expander or missing; exports were named five ways and two pages had no Export heading | no shared names | fixed (#90) on genomics, slides, omics, documents, evolution and imports; the lab page's "What this test cannot see" section comes with labs-ctdna's #94 |
| 8 | Patient file at 800 px | With the sidebar collapsed, nothing in a file said "Research and decision support for clinicians; not a diagnosis or a prescription" | the line lived in the sidebar and on the home page only | fixed (#91): in every file's header |
| 9 | Patient list on a phone (375 px) | Readable, but the table scrolls sideways and the patient ID scrolls out of view | – | fixed (#91): the Patient column is pinned |
| 10 | SYNTHETIC-001's header | The warning repeated itself: "SYNTHETIC-001 is synthetic. Synthetic patient: written by hand…" | – | fixed (#91) |
| 11 | Slide workbench | "Open R1 in the Spot panel" changes nothing visible on Case 299 | R1 is also T1, the tile the Spot panel opens on | not a bug |
| 12 | Report export (Markdown file) | The same asterisks reach the downloaded `.md` file (`workspace.report_markdown`) | variant names in Markdown | open: integration-report's file |
| 13 | Clinician path wording | No hackathon, sponsor or "demo" wording on any rendered page; the words appear only in docstrings and variable names | – | nothing to fix |
| 14 | Methods and validation | Cards were missing for the breast tissue head, StarDist, the slide rules, the lab rules, the SOS order, genomics; the data sources missed BCSS, QuiltNet, StarDist, the slides, PAM50, MSigDB, cBioPortal, the probe map and the clinical matrix; there was no single list of known failures or placeholders | the page predates the workbenches | fixed (#92): a card per model and rule, the full source list, one known-failures table and every placeholder (34) read from the modules' constants; radiology's card follows when that workbench lands |
| 15 | Slide and genomics workbenches at 800 px | Metric rows of four or five cut their values ("Tumor area (…) 0.08…") | fixed-width columns | fixed (#95): the rows wrap |
| 16 | Evolution view | 3.45 s once (Case 432, load average 10–12), under 1 s otherwise | the first live ClinicalTrials.gov query for a gene; then cached for a day | accepted: the snapshot answers when the registry is slow or down |
| 17 | Hosted app after the merges | Renders the new header, the shared chips and the new Methods page without a reboot: the hot-update guard picked up the new `methods_page` module | – | checked 2026-10-21 |

### Hosted app health

Measured in WSL with AppTest from a cold process, every result folder present (eight scored
sections with their crops, `omics_scores.json`, 38 pathology reports, the trials snapshot):

| | Before (main, load average 12–16) | After #91 (load average 5–10) |
|---|---|---|
| Cold start to the rendered patient list | 11.3 s | 6.1 s |
| Patient list rerun | 0.34 s | 0.09 s |
| Opening a TCGA file | 2.9–4.5 s | 0.2–0.5 s |
| Omics workbench (RNA), first open / a click inside | 7.5 s / 8.2 s | 0.28 s / 0.25 s |
| Slide workbench (Case 730), first open / a click | 2.0 s / 1.6 s | 2.2 s / 1.1 s |
| Every view and workbench in the regression walk (843 steps) | omics and record up to 7.9 s | all under 3 s but the cold start and finding 16 |
| Peak resident memory after opening five files, their workbenches and Methods | 539 MB | 516 MB |

The two columns ran at different loads; the slide row is the one where load, not the fix,
dominates. Per-case folders are already read only when their workbench opens (slides,
omics scores); the home page reads `cases.json` and, once per process, the 38 pathology
reports (240 KB), since each file lists its documents as tests.
Streamlit Community Cloud gives 1 GB. Most of the 516 MB is shared by every session (torch, the
bundle, the caches); what each further session adds was not measured.

## Round 2: every screen in a real browser (2026-10-22)

After the week's merges (the page skeleton, navigation, the guide, the radiology, documents,
omics and genomics rounds, the Feedback page), every screen was opened in headless Chrome and
read by eye, and what a clinician does was driven by key presses and clicks.

### How

- **The app** ran from a copy of the repository in WSL on the release bundle `demo-bundle-v2`
  with no keys (the case agent offline): one server in the app's own theme, one started with
  `--theme.base dark`.
- **Playwright (Python, headless Chromium)** opened SYNTHETIC-001 and Cases 299, 926, 937, 563,
  741 and 1043 by their addresses: the patient list, Methods and validation, Feedback, every view
  (Report, Tests, Timeline, Evolution, Import tests) and every test row's workbench (all 77 rows
  at 1280 px in the light theme; one per workbench per file in the other configurations), at
  1280 and 800 px, light and dark: 330 screens before the fixes and 334 after. Each screen was
  shot whole (the window made as tall as the page, since Streamlit scrolls an inner element)
  and the shots were read by eye, piece by piece.
- **A script on every screen** listed exceptions and error boxes, text cut by an ellipsis or a
  hidden overflow, elements past the window's right edge, sideways scroll, the contrast of every
  text against the background painted under it (the WCAG ratio) and the sticky header's colours,
  and timed each screen from its address to the end of the run, with the load average.
- **Functional checks** in the browser: the attention queue's keys, review marks across
  navigation, deep links from the queue's Open buttons opened in a fresh browser, every export
  downloaded and opened, the import dialog with bad files and one import of each kind, the slide
  viewer's keys, its first download and both fallbacks, and the hosted app.

### Findings

| # | Where | Finding | Cause | Status |
|---|---|---|---|---|
| R2-1 | Every page at 800 px; the report and genomics at 1280 px | Buttons lost their labels: the queue's "P.. K", "N.. J", "M.. M", "O.. O"; each queue row's Open showed "("; every look-here Spot, every export's downloads, the genomics review buttons, the mark-and-pin rows and the case-note buttons were cut (219 cut "Open" and 100 cut "Spot" labels on 73 screens at 800 px); at 1280 px "Mark reviewed", the risk's "Re…" and the four genomics downloads | buttons in fixed-ratio `st.columns`; at 800 px Streamlit keeps the sidebar open, so the page is about 470 px wide | fixed (#128): rows that wrap (`st.container(horizontal=True)`) and `_page.line_and_action()`; a test fails any button in a column under 40% of the width. After: no cut label on 334 screens but R2-21's |
| R2-2 | MRI viewer (Cases 937, 563), mammograms (Case 926) | At 1280 px the 512 px MRI slice covered the slice slider's caption beside it and the overlay toggles read "M…"; at 800 px both pages scrolled sideways (28 and 54 px) | a fixed-size image in a 3:2 column; the mammograms in two fixed columns | fixed (#128): image and controls share a wrapping row (side by side at 1280 px), the mammograms wrap. Then at 800 px with the sidebar open the MRI still overflowed by 28 px (slices drawn at 2×, 512 px, in a 468 px column): fixed (#136), the slice is drawn at most 460 px wide; the same fix found the boxes and measure lines drawn ~25–30 px above their contours (Streamlit's default chart autosize shrank the plot under the image), now on them (Cases 937 and 563, 800 and 1280 px) |
| R2-3 | Patient list | The "Documents" filter pill and "Open SOS alerts only" were cut | fixed columns | fixed (#128) |
| R2-4 | Timeline of every TCGA file | The record-over-time chart's two or three lane labels overprinted, 8 px apart | Streamlit fits the whole chart, axis and legend included, into the spec's height | fixed (#128) |
| R2-5 | Blood and lab, ctDNA | Opening "CA 15-3, month 11" from the tests table, from a link without `?pointer` or from the Timeline showed **month 24's** value in the Spot panel under a title saying month 11; the ctDNA month-11 sample likewise | only an attention-queue Open carried a focus | fixed (#129): a dated test lands on its own value; test |
| R2-6 | Tests table, the Timeline's version table, the lab import preview | Columns of "None": Month and 12-month risk for every TCGA file, the CSV's missing intervals | nulls drawn as Streamlit draws them | fixed (#129): empty columns left out (the captions say why), "38%" or "not scored", "—" |
| R2-7 | Genomics card and evidence ladder, the case note's button | `src/muffle/data/tcga.py` and `docs/VISION.md` on the card, a column headed "value", "1. detected observed observed", a tooltip "Set NEBIUS_API_KEY for live notes." | – | fixed (#129) |
| R2-8 | The Timeline's version table | The 12-month risk (model inference) sat under an "observed" chip only | – | fixed (#129): its own chip beside the table's |
| R2-9 | Import tests, an imaging report | "New lytic lesion in the T8 vertebra." named no new site, nor "New hypodense lesion in segment 6 of the liver" | the bone words lacked vertebra and lytic; "new … lesion in <site>" allowed nothing between "new" and "lesion" | fixed (#130); negated clauses still set aside; tests |
| R2-10 | Every page | Contrast under WCAG AA (4.5:1): orange badges ("placeholder", "hypothesis", "trust: moderate") 3.19, gray badges ("SOS: none open", "planned") 3.45, green 4.497, white on the primary blue 4.42, captions and table headers 3.70 | Streamlit's default text colours on its light tints | fixed (#131): 4.69, 5.33, 4.99, 5.5 and 5.1; nothing under 4.5:1 left but disabled buttons (exempt); a test reads the config |
| R2-11 | Slide workbench with its tiles blocked in the browser | "…not available here: The section's tiles are not reachable from here.. The tile map…" | the browser's reason is a sentence of its own | fixed (#132) |
| R2-12 | Feedback, clinical documents, radiology | Repository paths on clinician screens: "docs/VISION.md, part four" (Feedback), "scripts/documents_pipeline.py" (every documents page), "Method: scripts/radiology_pipeline.py mri version 2" (the radiology page, its card and the report's imaging card) | pages that landed after #121 | fixed (#132): in words ("the offline radiology pipeline (MRI) version 2"); a test finds no path on the report, two workbenches, a public MRI study and the Feedback page. The Methods page still cites the project's docs, as #121 decided |
| R2-13 | Tests | A SyntaxWarning in `tests/test_overview.py` on every run | `"\*"` in plain strings | fixed (#132) |
| R2-14 | A dark theme (a server started with `theme.base=dark`) | Before #131: the sticky header takes the dark page's background with light text (#124 holds), but chart labels drawn in fixed dark colours are unreadable on the dark plots (treatment names on the risk-over-time chart, "record so far", "diagnosis only"). After #131: all text is dark on dark, the theme's light text colours | the app is light-only: a custom `[theme]` with `toolbarMode = "minimal"` leaves no theme menu, and an OS dark setting does not switch it (checked) | not reachable by a reader; the config says light-only and what dark would take (#133). Open: the charts' fixed label colours, before any dark theme |
| R2-15 | Slide viewer | n and p step through the pointers (T1 → T2 → T1, the Spot panel follows), but the first n lands on T1, which the Spot panel already shows, so the first press looks dead | the viewer starts with no pointer chosen | fixed (#136): the page tells the viewer which tile its Spot panel shows, so with T1 shown the first n opens T2 (checked headless: T1 → T2 → T3 → T2 → T1); test |
| R2-16 | Slide viewer on a server that cannot reach the release | The fallback works (the tile map, with the reason) but the reason names an exception class: "could not be fetched (URLError)" | `slide_viewer._download` | fixed (#136): "the section's tiles could not be downloaded from the release", then the page's "The tile map draws the same analysis…"; the exception goes to the server log; test |
| R2-17 | Report at 800 px | One finding card per row, not three as docs/ux.md §4 said | that count assumed a collapsed sidebar | docs corrected |
| R2-18 | The breadcrumb line | The guide's "?" sits mid-line at 1280 px and drops to its own line at 800 px, instead of the line's right end | the header row's stretch space | fixed (#136): the "?" slot takes only its own width, so the stretch space pushes it to the line's right end (1280 and 800 px, the Patients page and a file; on a test at 800 px the crumbs themselves wrap and the "?" ends the second line) |
| R2-19 | Import tests, lab CSV | An analyte the reference table does not know is accepted with any unit ("Ferritin 80 furlongs") | by design: unlisted analytes are kept as reported and flagged only against their own interval | not a bug; a unit list for unlisted analytes would be the next step |
| R2-20 | Attention queue keys | j, k, p, m, u and o work by key press on SYNTHETIC-001: next, previous, pin (the button turns to Unpin), mark reviewed (the row ticked, the button disabled, SOS 7 → 6 open, the sidebar's tally), the unsure list on and off, open (the workbench, with "Back to the queue, item 1 of 15", which returns to the item) | – | checked |
| R2-21 | ctDNA Spot panel at 800 px | "Open the tumor sequencing (month 0) in the genomics workbench: DNMT3A R882H is not in it" was cut | a label longer than the page | fixed (#133): the two link buttons wrap their labels |
| R2-22 | Review marks across navigation | A mark and a pin survive Tests → Timeline → Patients → Case 299 (the file picker) → SYNTHETIC-001 (recently opened): the row's ✓ and 📌, "Pinned and reviewed: 1 pinned, 1 marked", "1 review mark and 1 pin" in the sidebar; the workbench the item opens shows the same mark | – | checked |
| R2-23 | Deep links | Five `?patient&view&test&pointer` addresses taken from queue rows' Open (SYNTHETIC-001: Bone and C2; Case 299: TP53 R110del and tile T1; Case 926: CDH1 K668*; Case 937: candidate C1), opened in a fresh browser, each land on the same Spot panel and breadcrumbs as the click (4–5 s). Items without a pointer (an SOS imaging read, a risk jump) open their view without one, by design | – | checked |
| R2-24 | Exports | 24 downloads on 12 pages each give a file with the expected parts: the report (Markdown, 21 headings: summary, SOS, findings by workbench, queue, observed, inference, hypotheses, missing data, placeholders, sources, review marks), labs, ctDNA, genomics (four files), slides (findings JSON, the 5,745-tile CSV, the map PNG), omics, documents, radiology (study, lesions, reads) and Evolution; the sidebar's marks CSV; a report exported after a mark and a pin carries both | – | checked |
| R2-25 | Import dialog | Validation in words: missing columns named, an empty file refused, a non-numeric value rejected with its row, an unsigned import refused ("Enter your initials…", Add disabled), a binary "report" refused, an unannotated VCF refused, non-PASS and off-panel variants rejected with reasons, a non-image and a non-DICOM refused. One import of each of the seven kinds into SYNTHETIC-001 and into Case 299: each listed with its version, the newest opening its page; a DICOM's identifying fields not shown | – | checked |
| R2-26 | Slide viewer downloads | First open on a server without the tiles: "Fetching this section's tiles, once for this server: 1 of 13 MB … Checking and unpacking the tiles…", then the viewer (10.7 s). Tiles blocked in the browser, and a server that cannot reach the release, both fall back to the tile map with the reason | the download is server-side, so blocking the release URL in the browser alone cannot test it: a server with `MUFFLE_SLIDE_TILES` pointing nowhere did | checked |
| R2-27 | Speed | Before the fixes, 330 screens at load average 6.3–11.7 (other sessions' tests running): median 1.9–2.6 s from the address to the end of the run, the slowest a slide workbench's first open with its tile download (14.3 s, Case 926). After, 334 screens at load 0.6–10.4: median 1.5–2.0 s; over 3 s only the patient list's first open after a server restart (6.0–6.8 s, the process's caches) and some slide workbenches (2.8–4.4 s) | – | accepted |
| R2-28 | Hosted app | `curl /` answers 303 (Streamlit's sign-in handshake), then the app. `/~/+/_stcore/health` answers "ok": a public health endpoint after all, though it says the server is up, not that the script runs; the logs need the owner's Cloud sign-in. In headless Chrome: the patient list 6.0 s, Case 299's report 4.1 s, its slide viewer 5.8 s (frame loaded, no fallback), SYNTHETIC-001's L4 link on L4 in 4.7 s. After #128–#131 deployed, the new layout and theme colours were live without a reboot, with no stale module, error or traceback (the hot-update guard held) | – | checked 2026-10-22 |
| R2-29 | Wording | No hackathon, sponsor or "demo" wording on any of the 334 screens (1.5 MB of rendered text); NVIDIA FLARE and Nebius Token Factory appear only as provenance | – | checked |

### Verdict for the Oct 28 freeze

Ready to freeze, in what a clinician sees and does: every screen of seven files now draws
whole at 1280 and 800 px with no exception, error box, cut label (one wrapped since, R2-21)
or sideways scroll (the MRI's 28 px at 800 px fixed since, #136); every text but disabled buttons reaches 4.5:1;
the queue's keys, review marks, deep links, exports, imports and the slide viewer's download
and fallbacks work through a real browser; the hosted app is current and healthy. The minor items
(R2-15, R2-16, R2-18) were fixed since (#136). The checks this round could not cover: a
375 px phone (round 1 checked it; the layout has changed since), browsers other than
Chromium, a screen reader, and the hosted app's memory under several readers at once.

**Would not ship:** a dark theme, or any setting that makes the app follow the OS into dark
(R2-14), until the charts' label colours follow the theme; and any change to `config.toml`'s
text colours without `test_the_theme_passes_wcag_aa_contrast` passing. Everything on main today
can ship.

## Performance pass (2026-10-27)

Where the app spends its time and memory, what was cut without changing a single thing it
shows, and the numbers before (main at #136) and after. The identity check was repeated after
rebasing onto main at #142 (the Tests launcher, cohort search, the workbench polish).

### How it was measured

- **AppTest walk**, in WSL on a Linux copy of the repository, the release bundle
  `demo-bundle-v2`, offline (the trials from their snapshot), one process per walk: the patient
  list from a cold process; SYNTHETIC-001 and Case 299 in every view (Report, Tests, Timeline,
  Evolution, Import tests) and one test per workbench; then eight more files (Cases 601, 545,
  1043, 730, 47, 564, 926, 563) the same way: 114 screens. Times are the server's script time
  for a screen (a real browser adds about 1–1.5 s: round 2's medians were 1.5–2.0 s); resident
  memory (RSS) is psutil's, in the same process. Before and after ran alternately, four times
  each; a screen's time is its median.
- **Load**: six other sessions' tests and the slide pipeline shared the 8 cores, at load average
  11–15 throughout. At that load one walk's screen times swing by ±50% (one single pair even
  came out reversed), so only medians over the four pairs and the per-call timings below are
  worth comparing.
- **Identity**: every element of all 114 screens (text, captions, metrics, tables as their Arrow
  bytes, chart specs, images and every download's content, the radiology export's minute
  masked) was dumped and compared: identical before and after, on the old and the rebased main.
  The test suite passes unchanged (438 tests, five of them new for the memo and the digest).
- **cProfile** under the walk found the hot spots; the per-call timings come from the same
  functions called outside Streamlit.

### What took the time

- The hot-update guard hashed every source and result file on every rerun: 12–29 ms a click.
- All 41 patient files were rebuilt on every rerun, and each workbench's `summary()` and
  `queue()` were recomputed by the report (once per browser session), by the Timeline (once per
  report version) and by each workbench page (on every rerun): 25–311 ms for a report's cards
  and queue, 12–49 ms for the genomics page's queue, 160–480 ms for SYNTHETIC-001's twelve
  versions. CIViC's table was filtered again for every variant on every call (5–10 ms each).
- Charts: Altair validates each chart against the Vega-Lite schema on every rerun, a third of a
  chart-heavy screen's time (not changed here, see below).
- A section's first open on the slide workbench (0.5–2 s, its analysis; cached afterwards).
- A cold start: mostly imports (torch, pandas, Streamlit, Altair, and scipy for the slide maths,
  0.35 s at load 18). Locally Jupyter's jsonschema extras add `rfc3987-syntax`, about 2 s and
  16 MB through Altair; `app/requirements.txt` does not install it, so the hosted app does not
  pay that.
- Memory: about 390 MB of it is the libraries at startup (torch alone 200 MB). What a walk adds
  comes mostly from the slide workbench's first opens (15–63 MB a section) and the MRI screens
  (35–78 MB a study). Those are working memory while the page is drawn (image overlays, tile
  maps, chart data), which the allocator keeps for reuse: clearing the radiology caches after
  every study was opened gave back 5 MB. The app's own caches are small (the slide sections
  21.7 MB pickled for six, the precomputed files 1 MB, `st.session_state` 170 kB).

### What changed

| Change | Where |
|---|---|
| Each workbench's `summary()` and `queue()`, the cross-test rules and the evolution hypotheses are computed once per patient file and version and handed out as copies (`muffle.memo`). A file is never changed in place (an import makes a new one), so the result can stay with the file object | `src/muffle/memo.py`, a decorator on each module's functions |
| The bundle's 41 files and their cases are built once per bundle, saved notes and code version and shared by every session, instead of on every rerun | `bundle_files` in `app/streamlit_app.py` |
| CIViC items are looked up once per variant | `evidence()` in the app |
| The hot-update guard reads directory entries and stats only the matching files (same files, same skips); a script showed it still purges after a changed module and a changed result file | `muffle.hotreload.source_digest` |
| scipy loads in the background once the first screen is drawn, not before the patient list (otherwise the first TCGA report would wait for it instead) | the slide maths imports it where it runs; the app's last lines |
| The copy-number file is parsed once per version on disk, not on every call | `genome.load` |
| The radiology page's decoded MRI phases, masks and mammograms keep at most 16 entries each (an MRI study is 17–27 MB decoded plus about 10 MB of masks, and these caches never let go). A walk that opens each study once stays under that bound, so this caps the worst case (the cine and the study pairs opened on every study), not the walk's numbers | `app/workbenches/radiology.py`, decorators only |

### Before and after

Per call, the same functions outside Streamlit, with scipy loaded in both (load average
11.4–12.1; the first call, then the same call again, as a rerun or the next session makes it).
The first call gains too: within one report the cross-test rules, the evolution hypotheses and
the CIViC items are now computed once instead of two or three times.

| | Before: first / again | After: first / again |
|---|---|---|
| The hot-update check, every rerun | 25 ms | 2.2 ms |
| Rebuilding the 41 files, every rerun | 5.1 ms | none (built once) |
| SYNTHETIC-001's report: cards and queue | 65 / 45 ms | 49 / 0.27 ms |
| Case 299's report | 142 / 62 ms | 61 / 0.34 ms |
| Case 926's report | 341 / 267 ms | 205 / 0.56 ms |
| The genomics page's queue (Case 926) | 66 / 48 ms | 0.05 / 0.04 ms (the report computed it) |
| The Timeline: SYNTHETIC-001's twelve versions' cards | 416 / 277 ms | 86 / 1.1 ms |
| CIViC items for all 47 variants | 449 / 500 ms | 438 / 0.46 ms |

The AppTest walk (medians over four alternating pairs, load average 12.6–14.9):

| | Before | After |
|---|---|---|
| All 114 screens, total | 81.3 s | 76.9 s |
| Median screen | 0.47 s | 0.43 s |
| Patient list rerun | 0.28 s | 0.20 s |
| A report's rerun (two files) | 0.44 s | 0.37 s |
| Back to a report from a view (ten files, median) | 0.40 s | 0.33 s |
| Tests view (ten files, median) | 0.49 s | 0.42 s |
| Documents workbench (ten files, median / max) | 0.40 / 0.81 s | 0.35 / 0.47 s |
| Genomics workbench (nine files, median / max) | 0.46 / 0.89 s | 0.43 / 0.49 s |
| Slide workbench, a section's first open (six, median) | 1.84 s | 1.83 s |
| Imaging workbench (four studies, median) | 1.02 s | 1.02 s |
| A cold process to the drawn list (seven and eight runs, load 11–13) | median 12.5 s (9.4–13.8) | median 10.0 s (8.4–13.9) |
| RSS after the ten files, every view and workbench (four walks each) | 548–583 MB | 561–574 MB |
| RSS after all 41 files, every view and workbench | 720 MB | 699–710 MB (two walks) |
| The same, with the allocator held to two arenas (`MALLOC_ARENA_MAX=2`) | 673 MB | 674 MB |
| `st.session_state` after the ten files | 46 keys, 170 kB | 46 keys, 169 kB |

In headless Chromium (Playwright, a freshly started server each time, two runs each, load
average 9.4–11.5), from the address to the end of the run: the patient list's first open
20.6–20.8 s before and 14.7–21.9 s after; ten screens of SYNTHETIC-001 and Case 299 (report,
labs, Timeline, omics, slides, the report again) 3.5–7.2 s before and 1.6–7.6 s after. At that
load the browser's own work dominates and the two overlap; round 2 measured 1.5–2.0 s medians
at a quieter moment.

So the app's own computing per click is now small next to what Streamlit spends building the
page's elements; the screens that gained are the ones that recomputed the queue (report,
Tests, documents, genomics, the Timeline). The cold start's runs overlap too much at this load
to claim more than the 0.35 s scipy took. Memory did not move: after ten files it stays under
600 MB locally (the hosted app about 16 MB less), but a walk through all 41 files ends near
700 MB, above the 600 MB aimed for. What would bring it down is in the pages that draw the slide
sections and the MRI studies (their working memory), not in a cache; holding the allocator to
two arenas saves about 45 MB, an environment variable set when the process starts.

### Left alone, and why

- **Chart specs on the workbench pages and the Timeline.** Caching them means changing how each
  page draws its charts (pages that are being reworked today) or relying on Streamlit's
  internal Altair conversion; the report's two costly charts were already cached
  (`case_charts`).
- **The slide page's scored sections and the omics and genomics pages' copies of the
  precomputed files** stay `st.cache_data`: every rerun gets its own copy (1–7 MB pickled per
  section, 2–56 ms to unpickle). Sharing one object (`st.cache_resource`) would save that but let
  any later edit to those pages change the cached object for every session.
- **Splitting the per-case JSON files.** `omics_scores.json` (427 kB) and `genomics_cn.json`
  (225 kB) hold every case and are now parsed once per process (5–10 ms); splitting them means
  regenerating the derived files the day before the freeze. The trials snapshot (44 kB) and the
  radiology `study.json` files (6–46 kB) are small; the decoded images are what weighs, hence the
  bounded caches. Slide pyramids are never read into memory (streamed to disk, served as files).
- **Startup imports.** torch is needed for the bundle and Altair by every page module; deferring
  them would reorder imports across the shell and the pages.
- **The memory the slide and MRI pages use while drawing.** Cutting it means drawing the tile
  maps and image overlays from smaller intermediates: page code, not loading. Returning freed
  memory to the system (`malloc_trim`) gives back 5–7 MB, not worth it; two allocator arenas
  (`MALLOC_ARENA_MAX=2`) gives back about 45 MB but only when set before the process starts,
  which is the host's setting, not the app's.

## Keeping the hosted app awake (2026-10-27)

- **Sleep rule.** "All apps without traffic for 12 hours go to sleep. … To keep your app awake,
  simply visit your app." (https://docs.streamlit.io/deploy/streamlit-community-cloud/manage-your-app,
  read 2026-10-27). The docs do not say whether a plain HTTP request counts as traffic, so the
  job below uses a real browser visit.
- **What runs.** `.github/workflows/keep-awake.yml`, every 4 hours (GitHub may start a scheduled
  run some minutes late): headless Chromium opens the app's own path
  `https://cancer-intelligence-platform.streamlit.app/~/+/?embed=true`, clicks "Yes, get this app
  back up!" if the sleep page shows, and waits up to 3 minutes for the Patients page. The job
  summary says awake, woken or failed and how long it took; a failed visit fails the job. No
  secrets. It also runs on a PR that changes the workflow.
- **By hand.** `gh workflow run keep-awake.yml`, then `gh run list --workflow keep-awake.yml`
  (or Actions > keep-awake > Run workflow).
- Still open the app yourself shortly before each judging window (Oct 29, and Oct 30 before
  10:00 am PT): a scheduled run can be late, and a reboot after a merge can leave it starting.

## Round 3 (2026-10-27): after the Oct 27 PRs

Eleven PRs landed on Oct 27 (#135 to #147: the Tests launcher, the action row, cards that name
their destination, Start here and pinned files, tooltips, the breadcrumb, workbench polish,
cohort search, the performance pass, the numbers pass, the GigaPath re-score) and nobody had
walked the whole app since. This round walked every screen again on main at 9eab7b0, then
rebased on the slide port (#150) and checked the ported slide page.

### How

- **The app** ran in WSL from a copy of the branch on the release bundle `demo-bundle-v2`, no
  keys, one server, the app's light theme.
- **Every screen by its address**, each in a fresh browser session, headless Chromium
  (Playwright) at 1280 and 800 px (the sidebar open): the patient list, Methods and validation,
  Feedback, and for SYNTHETIC-001 and Cases 299, 563, 730, 926, 1043, 564 (a breast MRI not
  walked before) and 485 (five tests, no documents): every view and every test's workbench
  (123 screens per width). Each shot whole and read by eye in pieces; a script listed
  exceptions, error boxes, text cut by an ellipsis, elements past the right edge, sideways
  scroll, overlapping text, console errors and the time from the address to the end of the run.
- **Charts drawn too narrow:** a second pass scrolled each 800 px screen and measured every
  chart (the checks above can't see inside a canvas).
- **Clicks** (about 580 checks): the tour, "Search every file" (TP53, PIK3CA, CA 15-3, bone,
  HER2 disagree, ESR1 methylated, nonsense) and its Open, Start here, pinning a file, the action
  row on SYNTHETIC-001 and Case 299 (Attention queue, Import a test, Compare versions, Export,
  Your marks, Pin, Methods, How to read this), a review mark through Your marks to the Feedback
  ledger and its Open, 23 deep links with wrong or stale values, all 16 report versions of
  SYNTHETIC-001 in Report, Tests and Timeline, the Timeline's jump and back, every launcher
  tile's Open and month pill of the eight files, and the three synthetic example files imported
  into SYNTHETIC-001 and Case 299.

### Findings

| # | Severity | Screen | What was seen | What to do | Status |
|---|---|---|---|---|---|
| R3-16 | major | SYNTHETIC-001's report after importing the example sequencing file | "The report view could not be drawn": the example MAF holds PIK3CA H1047R, already in the record, so the report drew its CIViC block twice with the same mark keys (`StreamlitDuplicateElementKey`) | one CIViC block per variant | fixed; the app test now imports a variant the record holds |
| R3-7 | major | Every TCGA file's report at 800 px | The risk histogram's plot was about 30 px wide with its axis title cut ("…ed log-risk (higher = shorter expected"); the layer-contributions chart lost its axis title and legend | the two charts share a row that wraps (380 px each): side by side at 1280 px, stacked at 800 px | fixed; a test fails any chart in a fixed column of half the width or less |
| R3-15 | major | Evolution view of 27 of the 40 TCGA files | "applies if hormone-receptor-positive: not recorded in this file" beside a report showing "Recorded: ER positive, PR negative, HER2 negative" (TCGA clinical data, IHC and ISH): the view read receptor status from the diagnosis line and the documents only | read the recorded status (HR positive when ER or PR is, negative when both are; equivocal is never a status), as #99 intended ("the record's status wins") | fixed: the false "not recorded" lines are gone; 10 files drop 12 rows their recorded status rules out (two each on Cases 305 and 96) (the HER2-positive-only row on HER2-negative tumors, rows that need HR-positive on HR-negative ones); SYNTHETIC-001 and Cases 299, 563, 730, 926 and 1043 keep their rows; test |
| R3-1 | minor | Tests on SYNTHETIC-001 opened without a test in the address | The breadcrumb and the launcher said "CA 15-3, month -2" (the oldest) while the Spot panel showed month 24 | open the latest of the series, the value the Spot panel opens on | fixed; test |
| R3-10 | minor | MRI Spot panel (Cases 563, 564) at 800 px | The kinetics curve sat in a 2-of-5 column: 179 px wide, its title cut; the mark control was cut after "reviewed" | the curve and the mark under the panel's words, the curve 460 px wide with slanted labels and a short title | fixed; test |
| R3-14 | minor | Methods and validation, Feedback | Opened from a file, the browser's Back lands on the bare patient list: Streamlit drops the address's parameters on the way back | a "Back to <file>" link on both pages, to the screen left (its test, pointer and version) | fixed (the browser's own Back stays Streamlit's); checked in Chromium: back on "Tests › Labs › CA 15-3, month 11"; test |
| R3-17 | minor | A link with `?version=0` | Opened the latest report, though the app writes `?version=0` for the first version (diagnosis): a copied address reopened the wrong version | accept 0 | fixed; test |
| R3-12 | minor | Patients, "Search every file" | Two of the box's seven examples find nothing in any file ("ESR1 methylated", "washout") | examples that each find a file | fixed: "GSTP1 methylated" (5 files) and "plateau" (2); the others find 3–14 files. No test: the test bundle is not the release one |
| R3-2 | minor | Radiology, mammography (Case 926) | The search box suggested "washout · largest · C2", MRI words; a mammogram has no lesion candidates | a hint per page | fixed: "mutation · lymph node · change over time"; test |
| R3-6 | minor | Methods and validation, receptor table | "None" as HER2-by-copy-number's AUC and cutoff (R2-6's pattern) | it is a rule: "—" and "— (a rule)" | fixed; test |
| R3-9 | minor | Timeline at 800 px | The month axis's title was cut ("…diagnosis at mont"); treatment names overprint where bars sit close ("palbociclib" over "alpelisib") | the title on two lines; a name per bar would need the bar's width in pixels, which the spec doesn't know | title fixed (test); the names stay (hover names each bar) |
| R3-19 | minor | Radiology cards (MedSAM, the screening score) | The reproducibility note showed the raw shell line "22:43:52 up 59 min, 1 user, load average: …" | the load average only | fixed; test. The slide page has the same (R3-4) |
| R3-5 | low | Every TCGA report | Two headings "Where this patient sits": among the 40 TCGA files (the cohort lookup) and among all patients (the risk histogram) | rename the histogram's | fixed: "This patient's risk among all 1,064 patients"; test |
| R3-18 | low | Methods and validation | No card for the cohort lookups (Search every file, Similar patients, Where this patient sits); their placeholders were in the table already (a canvas table, which text tools can't read) | a card: lookups over the files' findings, not models; what they read; the placeholder weights; what is never compared | fixed; the app test checks the card and Similar patients' weights in the placeholder table |
| R3-13 | minor | Patients, search "bone" | The first result opens SYNTHETIC-001's imaging report at the **liver** lesion: its best finding is the "Imaging lesions" card (bone and liver), and a card opens at its own target; "New metastatic site: bone" is in the "+5" | within a file, rank first the findings whose name holds the words (`cohort.search`'s sort key) | fixed (#152): within a file the findings named by the words come first (the shortest name first), then the closest; the files' order is unchanged. On the release bundle "bone" now opens SYNTHETIC-001's imaging report of month -1 at the bone site ("New metastatic site: bone"); test |
| R3-8 | low | Every file at 800 px | The action row wraps to four rows of two buttons (about 180 px) under the header, before any content | fold Pin, Methods and How to read this into one "More" menu at narrow widths, or accept | open, for ui-cockpit (the shell) |
| R3-3 | low | Slide workbench, first open per server | 12–32 s (Case 563 31.9 s at load 4): the section's tiles download once per server | – | accepted (R2-26's download, said on screen) |
| R3-4 | minor | Slide workbench (Cases 563 and 730; after #150 Cases 299, 730 and 926) | Machine talk: "…outside the scored window were skipped (the budget for this PC's CPU)", "this PC", "load average" | plain words ("not scored", the load as in R3-19) | open, for the slide page's owner (`app/workbenches/slides.py`; no session on it on Oct 28) |
| R3-11 | low | Slide workbench at 800 px | Before #150 a 109 px chart; after #150 the map draws 468 px wide with no sideways scroll (the 151 px seen on Oct 27 is gone), but the "Zoom to the cells" label is cut | let the label wrap | open, for the slide page's owner (as R3-4) |
| R3-20 | – | Methods and validation, Feedback opened by address | Two console 404s: Streamlit's client asks `/methods/_stcore/health` and `/host-config` before the root ones | – | not a bug (Streamlit) |
| R3-21 | – | Every screen | No exception and no error box on 246 screens; no cut text, element past the edge or sideways scroll in the page's own elements at either width (inside charts: R3-7, R3-9, R3-10); every finding carries its label; the synthetic patient and the simulated hospitals are labeled; no hackathon, sponsor or demo wording in 2.3 MB of rendered text | – | checked |
| R3-22 | – | Deep links | 23 addresses with an unknown patient, view, test, month, pointer or version, a test of another file, a page with junk parameters: each opens the file (or the list) as usual, with no error; `?view=tests` (lower case) opens the report | – | checked |
| R3-23 | – | Speed | From the address to the end of the run in a fresh session (session start included), load average 1.6–10: median 4.8 s at 1280 px and 4.3 s at 800 px; over 5 s mostly at load above 4, the first screen after a restart (13.6 s) and the slide page's first open (R3-3) | – | accepted; clicks within a session were not timed |

### Not covered

The hosted app (the keep-awake job checks it), a 375 px phone, browsers other than Chromium,
a screen reader, and dark mode (the app is light-only).

## Cold-start pass (2026-10-28)

How long a new server process takes to draw its first screens on main after the Oct 27 PRs
(plotly for the slide map, #150), what was cut, and the numbers before (main at 67647db) and
after (branch `app/cold-start`), with every screen unchanged.

### How it was measured

- **Cold runs** (AppTest, WSL, Python 3.14, a venv with only `app/requirements.txt`, as the
  hosted app installs it, so no `rfc3987-syntax`): one new process per run, from interpreter
  start to the drawn patient list, then SYNTHETIC-001's report, Case 299's report, its Tests
  view and its first slide page, with RSS after each. A 3 s pause after the list stands for a
  reader looking at it before the first click. Main and the branch ran alternately.
- **Two set-ups.** *Cached*: the release bundle and CIViC's table already on disk, as on this PC
  or a warm container. *Fresh container*: an empty temporary folder and no CIViC cache, the
  network on, as the hosted app starts after it sleeps (Streamlit Community Cloud's disk resets
  on restart): the bundle (852 kB, 0.9–1.0 s from GitHub here) and CIViC's table (4.2 MB,
  1.4–1.8 s from civicdb.org here) are downloaded first.
- **Load**: the three sibling sessions shared the 8 cores, load average 0.3–8.8 over the
  measurements (each row gives its range). Per-run times swing by a second or more at load 3 and
  above, so each row is a median and its range. The fresh-container gain is larger than that
  spread; for the cached start a per-import timing in a fresh process (below) is the reliable
  number.
- **Identity**: the 114-screen AppTest walk of the performance pass (`perf_walk.py`, every
  element of every screen dumped: text, tables, chart specs, images, downloads) on main and on
  the branch: **114 screens identical** (the same snapshot hash, 9a5736188750). The test suite
  passes, with five new tests (`tests/test_cold_start.py`).
- **Where the time went** (`python -X importtime`, cProfile of the first run on main, load ~3):
  torch 4.4 s, pandas 1.4 s, Streamlit 1.3 s (it imports plotly itself), Altair 0.84 s (through
  `charts` and the workbench page modules), CIViC's table 0.2–0.3 s to parse, the bundle and
  the 41 files 0.4 s; scipy (1.8 s) already loaded in the background after the first screen,
  but the first TCGA report imported it anyway: `muffle.workbench.invasion`, read for its
  cutoffs, imported scipy at the top.

### What changed

| Change | Where |
|---|---|
| The chart and workbench page modules (`charts`, `timeline_page`, the labs, genomics, omics and Evolution pages) and Altair load on first use, not before the patient list, which draws no chart. Altair then loads in the background once the first screen is drawn, with scipy | `muffle.lazy` (a module loaded on first attribute read, looked up in `sys.modules` each time, so the hot-update guard's purge still works); the app's import block and last lines |
| In the hosted set-up (no bundle given, no checkpoint), the release bundle and CIViC's table are downloaded in background threads started before torch imports, instead of one after the other before the list. The loaders wait for a download started that way; if it fails they fetch the file themselves as before | `muffle.prefetch`; `fetch_bundle`, `civic.load_table`; the app's import block |
| The slide maths imports scipy when it runs, not when the report reads its cutoffs | `muffle.workbench.invasion` |

### Before and after

| | Main (67647db) | Branch |
|---|---|---|
| **Fresh container: process start to the drawn list** (three runs each, load 1.6–2.5) | median 10.87 s (8.71–11.34) | median 7.21 s (6.93–8.67) |
| Cached: process start to the drawn list, main alone at a quiet moment (three runs, load 0.3–0.6) | median 5.02 s (4.72–6.32) | not run at that load |
| Cached: process start to the drawn list (three runs each, load 2.5–3.4) | median 5.38 s (5.29–8.22) | median 6.16 s (5.12–6.96) |
| The same, five more runs each (load 1.8–7.2, rising) | median 9.68 s (7.72–10.08) | median 8.23 s (6.17–10.75) |
| Off the first screen's path: the page modules and Altair, timed alone in a fresh process (five runs, load 8.4–8.8) | 0.82 s (0.74–1.03), 27.6 MB | none |
| RSS when the list is drawn | 520 MB | 493 MB |
| RSS 3 s later (the background loads done) | 549 MB | 549 MB |
| SYNTHETIC-001's report, first open | 0.53 s (0.50–0.86) | 0.59 s (0.51–0.68) |
| Case 299's report, first open | 1.13 s (1.06–1.16), 578 MB | 1.00 s (0.90–1.23), 578 MB |
| Case 299's first slide page | 1.88 s (1.71–2.13), 624 MB | 2.02 s (1.99–2.53), 621 MB |
| The 114-screen walk: RSS after the start / after ten files | 534 / 793 MB | 506 / 793 MB |

So a hosted cold start draws the patient list about 3.5 s sooner: the two downloads now overlap
torch's import. With the files already on disk the gain is the 0.8 s and 28 MB of imports no
longer on the list's path; at this load the cached runs overlap too much to show it on their
own. The reports and the slide page take what they took (Altair loads in the background while
the list is read), and memory ends where it was.

### Left alone, and why

- **torch before the list.** The bundle is a torch file (`torch.load`, weights only) and the
  TCGA reports run the model; loading the list without torch means a second bundle format.
- **plotly.** Streamlit 1.66 imports it itself (`import streamlit` loads it), so the slide map
  adds nothing to the cold start.
- **Memory after ten files: 793 MB on both.** The same walk measured 548–583 MB on Oct 27, in
  another venv (Python 3.12 then, 3.14 and pandas 3.1 now), so not all of the rise is the app;
  the GigaPath slide maps, the plotly map and the MRI pages came since. As in the performance
  pass it is the pages' drawing memory, and it is above the 600 MB aimed for on a 1 GB host: for
  the slide and radiology pages' owners, and worth one walk in the hosted app's own versions.
- **The slide page's first open** (1.7–2.5 s here, more the first time a server downloads a
  section's tiles, R3-3) is its section analysis: page code, not loading.

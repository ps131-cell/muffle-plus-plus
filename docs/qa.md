# QA passes over the clinician application

Round 1 (2026-10-20, Streamlit's AppTest) first; round 2 (2026-10-22, every screen in headless
Chrome, read by eye) next; the performance pass (2026-10-27) at the end.

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

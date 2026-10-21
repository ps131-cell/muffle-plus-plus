# QA pass over the clinician application (2026-10-20)

A walk through everything a clinician can open, with what was found, its cause and its status.
Method: Streamlit's AppTest drove the real app (`app/streamlit_app.py`) on the release bundle
`demo-bundle-v2` (40 held-out TCGA cases) and SYNTHETIC-001, in WSL on a copy of the repo on the
Linux filesystem; the browser pane checked widths and the hosted app. The walk scripts live in
the QA session's scratchpad, not in the repo: they read the real bundle, which tests don't.

## What was walked

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

## Findings

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

## Hosted app health

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

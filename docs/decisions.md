# Decision log

Newest at the top. One entry per decision: date, what, why.

## 2026-10-28 — The Bhargava lab's stroma work applied as cited cards, a score and planned modules
- **What:** on the user's request ("research Rohit Bhargava's research ... read and apply
  everything you can"), four pieces on H&E and RNA, three infrared pieces as planned modules.
  Slide workbench: tissue by zone (class shares in core, front band and peritumoral zone, model
  inference; precedent Mittal 2019) and, beside the tumor–stroma ratio, a hypothesis line on
  border collagen and ECM3 (Tiwari 2020), both in the export. Omics workbench: the ECM3
  four-gene score (COL1A2, COL5A2, SPARC, LAMA4; Triulzi 2013) as a cohort percentile with no
  cutoff, its grade III prognosis a cited hypothesis, a card and never a queue item. Methods and
  validation: an evidence category (I–IV, adapted from Bhargava 2023) and an EASSI-H line (data,
  n, split, external validation, result) on every model card; a "Planned: infrared chemical
  imaging" block (stainless staining; stromal subtypes in the front band; an infrared ECM3
  score). Citations as data in `src/muffle/literature.py`; `docs/registry.md` lists the papers.
- **Gene list:** Triulzi 2013 names COL1A1 in its Results and figures 2 and S3 and COL1A2 in its
  Methods metagene, Figure S5 and its last Discussion paragraph; its qRT-PCR assay list has
  COL1A2 and no COL1A1 assay. COL1A2 is used, and `docs/omics.md` says so.
- **Data:** the release bundle's 1,000 RNA features hold COL1A2 only, so the four genes' cohort
  z-scores come from TCGA-BRCA STAR TPM through `scripts/omics_ecm3.py` (as the other omics
  scores, derived numbers only) over the model's whole cohort (1,059 tumors), the reference of
  the workbench's other percentiles, rather than the 40 bundled files.
- **Why:** the lab's stroma work bears on the invasive-front analysis, and its evidence ladder
  and reporting checklist match the app's rule that a placeholder never looks validated.
- **Rejected:** training on infrared-derived labels (no public infrared data, no weights,
  unlicensed lab code); Mittal 2019's "inertia" measure (tested for diagnosis only); any cutoff
  on the ECM3 score (fitted on its paper's cohorts; the infrared detector on 42 tumors of one
  centre).
- **Credit:** cited by authors, year, journal and DOI; MuFFLe++ is independent and neither
  reviewed nor endorsed by the laboratory or the Cancer Center at Illinois; no logos, no code.

## 2026-10-28 — Building continues past the planned Oct 28 freeze, under new gates
- **What:** on the user's word (00:20 CDT: "keep working, keep optimizing, also keep building
  ... think like a UI/UX designer ... parallel sessions"), building goes on through Oct 28
  instead of freezing. The land-whole rule stays: a PR lands whole, with CI green and its
  screenshots looked at, or not at all. New gates: UI and feature PRs merged by **Oct 29,
  10:00 CDT** (the real code freeze); after it only the final QA walk, the video re-walk of
  `docs/video.md` and submission material; the submission on **Oct 30 before 10:00 am PT**.
- **Why:** the user wants more of the product done; the briefs asked for a clinical-trust
  provenance layer, a version diff, a visible budget and federated status, and a dense
  clinical look.
- **Risks taken:** the video is recorded from an app that changes until Oct 29 morning, so
  the script is re-walked once more after the freeze; several sessions share one CPU (two
  workers each, CI is the gate). If a PR misses its gate, it is dropped whole (the cut order).

## 2026-10-28 — A clinical light theme and the report's cockpit
- **What:** the app keeps its light theme and AA colours and gets its own type: IBM Plex Sans
  for text, IBM Plex Mono for variants, pointers, ids and amounts (SIL OFL 1.1, self-hosted in
  `app/static/fonts`), a 15 px base, a compact heading scale, near-black inline code instead
  of Streamlit's green, small radii, 1.5 rem gutters, compact controls and chips
  (`.streamlit/config.toml`, `app/theme.css`). The report keeps its summary and cards (the SOS
  tile first), then three columns side by side at 1280 px, stacked at 800 px: the risk model,
  the driver mutations with their CIViC ladder, what to look at next; each finding's source,
  method, version and evidence item on hover, and its workbench or civicdb.org on click. The
  sidebar's About this system shows the system's status (release, each simulated site's
  held-out C-index, planner and writer, the case-note spend on this server's ledger against
  the hard cap, live notes left, the code's version); Methods gains a colour code, a Case note
  service card and the federated training as a status table. `docs/ux-audit.md` has the
  two-pass audit behind it, `docs/ux.md` §8 the rules.
- **Why:** on a laptop the SOS tile sat below the fold and the risk model, the mutations and
  their CIViC evidence were 1,500–3,000 px apart; Streamlit's defaults (16 px Source Sans,
  36 px metric values, 40 px rounded buttons, 5 rem gutters, green code) read as a generic
  dashboard, not a clinical instrument.
- **Rejected:** a dark "clinical terminal" theme (the charts' label colours are fixed for
  light, docs/qa.md R2-14); fonts from Google at run time (an outside request on every page);
  a family without a monospace sibling; colour as the only signal (every chip keeps its word).
- **Severity colours** come from Ensembl VEP's consequence table (HIGH red, MODERATE orange,
  LOW and MODIFIER grey); CIViC levels A–B green and C–E orange, as the genomics queue's trust.

## 2026-10-27 — The slide map and functions ported from the team's colon analyzer
- **What:** the user asked for the analyzer's map and functions ported rather than rebuilt (the
  slide workbench's tile map was "really really ugly"; "no need to redevelop, if it has already
  been coded"). The Altair tile grid is gone; the page's first picture is the analyzer's plotly
  map (the section's scan with a see-through layer, seven views, opacity slider, hover box,
  click to the Spot panel, zoom, pointers), with its search within a slide, map picture and
  report export, the Spot panel's "where it sits / why / how sure", the class highlight and
  notes, copied and adapted to breast (`docs/pathology.md` §10 lists every feature and what it
  became). The OpenSeadragon viewer stays one click away and downloads a pyramid only when
  opened. plotly 7.1.0 is a new dependency.
- **Why:** the analyzer is the team's own code and the depth standard; the port fixes the old
  map's 151 px sideways scroll at 800 px too.
- **Kept out:** the analyzer's colon-trained heads, cutoff values and colon classes; its colon
  analysis (depth hint, mucin, outer edge, nodes, phrase flags); its LLM summary; its PDF
  (Markdown instead, like the file's export).
- **Disclosure:** `docs/submission.md` now lists the adapted files instead of "no file is
  reused"; mirrored in `docs/HACKATHON.md` and `docs/registry.md`. Both hackathons' rules were
  checked again: Nebius × NVIDIA allows pre-existing work significantly updated during the
  period and disclosed; the analyzer is the team's own code.

## 2026-10-27 — Slide maps from GigaPath-Flash; a misregistration on three sections fixed
- **What:** the eight sections and the example region are re-scored with GigaPath-Flash
  (`prov-gigapath/prov-gigapath-flash`, Apache-2.0, gated click-through, run offline) under the
  BCSS head trained on its embeddings: held-out accuracy **0.919** (balanced 0.917) on the same
  3 patient-disjoint slides and 357 tiles where QuiltNet-B-32's head scored **0.877** (balanced
  0.854), the number quoted until today. Grids and windows are reused; nuclei and the second
  lymphocyte model's scores are kept where they still lie in the new front band or peritumoral
  zone and topped up on the new zones' tiles without one. Per-section numbers before and after,
  with coverage: `docs/pathology.md` §9.
- **Bug fixed:** on the three sections scored through a window (TCGA-D8-A1XF-DX1 and -DX2, case
  730; TCGA-BH-A0H5-DX1, case 563) `slide_pipeline.py run` embedded each tile, and StarDist
  counted its nuclei, from the pixels at the window-relative position instead of the window's
  place on the slide. On `main` since #87 (2026-10-20), and drawn over the real tissue by the
  viewer since #107 (2026-10-21): case 730's classes and nuclei came from tissue 3–5 mm away,
  case 563's mostly from glass (hence "no tumor found"). The thumbnail, crops and TIL scores were
  at the right place. Found by recomputing the cached texture measures at both positions (18 of
  18 sampled tiles matched the wrong one); those sections' "before" numbers are from the wrong
  tissue and their nuclei were counted again.
- **New quality rule:** a tile whose GigaPath-Flash embedding is farther than cosine 0.507 (mean
  over its 5 nearest) from all 1,052 tiles the head was trained on is "unlike training tissue"
  and not scored, like glass or pen ink. Cutoff calibrated leave-one-slide-out on the 8 training
  slides (99th percentile); it flags 1 of the 357 held-out tiles (0.3%).
- **Why:** GigaPath-Flash wins on every held-out slide, and on case 299 every new tumor tile we
  looked at is carcinoma QuiltNet called stroma. But on case 926 its head read 808 tiles of
  cautery-crushed, muscle-like margin tissue (a class neither head has; QuiltNet called it
  necrosis) as carcinoma, and the main tumor, front, arcs and risk regions sat on it. The rule
  moves case 926's main tumor back onto carcinoma; it misses about a third of that tissue, so
  small fragments remain, which the section's page and the known failures say. On case 1043
  the new head finds DX3's high-grade carcinoma, which QuiltNet called necrosis, but on DX1
  (collagen, fat and clot, little carcinoma) reads collagen as carcinoma; that page says so too.
- **Consequence:** status unchanged (*experimentally validated on held-out BCSS regions only*;
  not reviewed by a pathologist). README, the Devpost numbers appendix and the Methods card
  quote 91.9%. If the swap had missed its gate, QuiltNet would have stayed only with the
  window fix re-run on the three sections, never a pointer that leads to muscle.

## 2026-10-27 — Across the files: one search, similar patients and cohort position, as lookups
- **What:** `src/muffle/cohort.py` ([`cohort.md`](cohort.md)) indexes every file's findings
  once per bundle (the workbenches' cards and queue items, tests that disagree, documented
  facts, variants, methylation calls, hypotheses, a file profile), searched in plain words from
  a "Search every file" box on the Patients page. Each report gains "Where this patient sits"
  (percentiles among the 40 TCGA files, a small chart per score) and "Similar patients" (the
  five nearest TCGA files on eight recorded and derived fields).
- **Why:** a clinician with 41 files asks "who else has this?" and "is this patient unusual?";
  both are answerable from what the files already hold, without a new model.
- **Consequence:** labeled lookups and percentiles, never a model or a prognosis; the
  similarity's equal field weights are placeholders. The synthetic patient is outside the
  cohort and never a candidate, and its MSK-CHORD risk is never compared. Search is a text
  lookup: a differently worded finding is missed, which `cohort.md` says.

## 2026-10-27 — Final numbers pass: each figure named by what it measures; the video re-walked
- **What:** every figure in `docs/submission.md`, the README, `docs/HACKATHON.md` and the Methods
  page traced to its source (the appendix lists each). The demo model's 0.728 is described as
  what the bundle stores: the mean of the three simulated hospitals' held-out C-indexes over 213
  held-out patients (26 deaths), not "its 40 held-out cases" (the 40 files are drawn from those
  patients); 0.693 ± 0.017 stays the five-seed pooled federated result; no fusion variant is
  said to match or beat clinical-only (0.702 ± 0.004). The video script was re-walked in
  headless Chromium at 1280 px (`docs/video.md`): the second lymphocyte model is shown in the
  slide workbench's Details › Cells (it is not a viewer layer), the documents shot moved from
  Case 299 (two rule facts) to Case 563, and time travel and the Feedback page joined the shot
  list within 2:58.
- **Why:** a judge or reader should be able to reproduce each number from what it names.
- **Consequence:** the pathology figures (87.7%, QuiltNet-B-32) change only with the slide
  re-score's merged PR, or stay if its Oct 27 gate closes.

## 2026-10-22 — Learning from clinicians starts as a ledger of review marks; nothing trains on it
- **What:** a Feedback page (`app/feedback_page.py`, `src/muffle/feedback.py`,
  [`feedback.md`](feedback.md)) turns the session's review marks into a ledger: each mark with
  the model or rule behind its finding (derived from the finding key), its version and inputs,
  and the evidence label; disagreement rates per model or rule with a 95% Wilson interval; the
  disagreed findings as a queue; a JSON-lines export (`muffle-feedback/1`) and an import checked
  at the boundary. Methods and validation shows each card's "reviewed / disagreed this session"
  line; the report export gains a Feedback section.
- **Why:** VISION part four separates storing an observation, updating a research dataset and
  retraining a model, and says new data never becomes training data automatically. The first
  step can be real today without patient data leaving the browser; the others need consent,
  ethics approval and data agreements.
- **Consequence:** marks stay in the browser session and in files the clinician downloads; no
  server storage, no upload anywhere, no model or cutoff changes. A disagreement rate is one
  session's judgments, not a measured error rate, and the page says so. Re-calibration of
  placeholder cutoffs, head retraining on disagreed tiles and federated rounds are a labeled
  roadmap card. The method behind a mark is derived from its key, never read from an uploaded
  file.

## 2026-10-22 — Clinical documents round 2: a named-entity model beside the rules, scanned reports
- **What:** OpenMed's zero-shot oncology NER (Apache-2.0, 220M) reads the bundled TCGA reports
  offline with 16 breast pathology labels we define; its spans ship as derived JSON
  (`app/documents/<barcode>.ner.json`: label, offsets, score) and are drawn as a second layer
  labeled model inference, set beside the rules per document, measured on the same held-out
  reports with the same comparison, and a receptor or stage field they read differently is a
  "models disagree" queue item (weak). A PDF without a text layer is queued for the local
  pipeline, which reads it with Granite-Docling 258M (Apache-2.0) and then runs the rules and
  the NER on the text. The documents' dated facts are set on the file's axis with their
  changes; a conflict is settled only by the clinician's mark; "the record says X, the
  documents say Y" reaches the discrepancy queue where the cross-test rules did not reach.
- **Why:** the user asked for a model's reading next to the rules', measured, and for scanned
  input. The model's value is read only from the characters it marked, so its numbers are its
  own, not the rules' in disguise. Running both models offline keeps the hosted app within
  1 GB and keeps report text on the machine (CLAUDE.md).
- **Consequence:** the measurement shows the zero-shot model marks where a field is named far
  more often than its result, so the rules stay the documented reading and the model is a
  second opinion of weak trust (docs/documents.md, round 2). The page reader reads clean
  scans well and fails on dense fax-quality scans (it loops; the pipeline flags that), so a
  scanned report's text needs a person's check before import. Imported documents get the
  rules at once and the model only through the local pipeline. The documents page now follows
  the shared page skeleton (`workbenches._page`), as the 2026-10-22 skeleton entry planned.
## 2026-10-22 — The address reopens the screen; a failing part says so in words; hidden content loads when opened
- **What:** breadcrumbs, a sticky patient header and "back to the queue" after an "Open"; the
  address carries ?patient, ?view, ?test, ?pointer and ?version, written after each run and
  applied once per new address, so a link lands on the evidence (`docs/ux.md` §2). A "?" on
  every screen opens "How to read this", the Patients page opens with a four-step walk-through,
  and status chips explain themselves on a click (§3). A view or workbench that fails says which
  part failed and links the Methods page, never a traceback; the log keeps it (§4). Hidden
  content (the "?" panel, the genomics and lab tabs that aren't open, the second slide viewer,
  the radiology cine and example pair) runs only while open; each page's look-here items are
  computed once per session and version (§6).
- **Why:** a first-time reader must always know where they are, how to get back, what a label
  means, and that a broken part is one part, not the app; on a shared CPU the help panel alone
  was half of every rerun.
- **Consequence:** tests open lazy content explicitly (`at.session_state[key] = True`, or the
  tab's label); a Streamlit link that reloads the page would lose the session's marks, so every
  in-app move is a button or a page link, never a plain URL.

## 2026-10-22 — The Timeline: lanes, time travel from any point, and what each version brought
- **What:** the Timeline view becomes the file's longitudinal view (`docs/timeline.md`): an
  event chart with one lane per kind on a month axis, report versions on top; a click on any
  point opens the file as of the version that point created; a "new in this version" card; the
  risk chart with toggled overlays; the version diff with "jump to this version"; a Timeline
  section in the report export. Data in the pure `muffle.timeline_view`, the page in
  `app/timeline_page.py`; the shell keeps a two-line hook.
- **Why:** a clinician reads a cancer as a story over time; the version slider alone showed
  where you were, not what happened between versions or what each test changed.
- **Rules decided:** (1) time travel is as-of for everything except the event chart, which keeps
  the whole record visible (later entries faded) so any point can be clicked forward or back;
  (2) the record holds treatment start dates only, so a drug's bar runs to the next treatment
  entry that does not name it, or stays open: a display rule, said on the page; (3) imports get
  their own lane, signed, so the record and this session's additions never blur; (4) the PNG
  export is Streamlit's own chart toolbar button: no rendering dependency for the hosted app.
- **Consequence:** time travel sets the report version slider's session key, the same key a
  `?version=` deep link sets, so the address follows the version being viewed.

## 2026-10-22 — One page skeleton for every workbench, enforced by a shared helper
- **What:** every workbench page draws the same parts in the same order through
  `app/workbenches/_page.py`: the title (workbench · patient · test), the status chips, the
  overview (one paragraph, the workbench's look-here queue, search), the picture, the details
  (collapsed, each with its count), the Spot panel, the Model and validation card, what the
  test cannot see, the export (`docs/ux.md` §1). Applied to labs, ctDNA, genomics, slides,
  omics, evolution and imports; radiology and documents follow once their second rounds merge.
  The lab page's one expander per flagged result became the Spot panel's review mark; the
  genomics page's two gene Spot panels and its variant Spot panel became one Spot panel; the
  Evolution view's hypotheses became a table whose row opens the Spot panel.
- **Why:** each workbench grew its own order and headings in three rounds; a pathologist who
  had learned one page had to learn the next. A shared helper keeps them the same, and a
  collapsed section with its count keeps every piece of depth one click away.
- **Consequence:** the look-here list on each page is the workbench's own `queue()`, the items
  the report's attention queue carries, so a mark made on either is the same mark; a page's
  older or standing items sit in a details section. A part out of order fails the tests
  (`MUFFLE_STRICT_PAGES=1`), never the page in front of a clinician.

## 2026-10-21 — The demo model's held-out C-index is the release bundle's 0.728; a local rebuild reads 0.730
- **What:** the hosted app and the `demo-wsl` preview both load the release `demo-bundle-v2`,
  so both show held-out C-index **0.728**. The preview passes `--bundle outputs/demo_bundle.pt`,
  a copy byte-identical to the release asset (sha256 `3baccb8f258aea82…`). Without `--bundle` or
  `MUFFLE_BUNDLE`, a clone that has `outputs/tcga_fedavg.pt` and `data/tcga_brca/cohort.npz`
  rebuilds the demo from its own data (`load()` in `app/streamlit_app.py`). That rebuild uses the
  same model weights on features rebuilt from current GDC and Xena files, and reads **0.730**:
  site-2 0.670 instead of 0.665, the other two sites equal, cohort risks within 0.019.
- **Why:** the shown number must be one anyone can reproduce from the release. Bundle v2 was
  built with `--base` (PR #63) precisely so that it keeps v1's model, cases and numbers, adding
  only the observed mutations; a rebuild from re-downloaded data drifts a little.
- **Consequence:** quote 0.728 for the demo model. The README's results table is a different
  quantity, the pooled site-stratified C-index of `make experiment-tcga` (mean ± sd over 5
  seeds; FedAvg 0.693 ± 0.017); the Oct 27 numbers pass keeps both and names which is which. A
  preview that shows 0.730 was started without `--bundle`. `.claude/launch.json` is local and
  shared by sessions, so the flag lives there and in this entry, not in the repository.

## 2026-10-21 — Radiology round 2: change over time on a public example pair, three planes, five cases
- **What:** change over time on one public TCIA patient with breast MRI on two dates
  (TCGA-AR-A1AQ, 2001-11-21 and 2003-05-07, not in the bundle) as a labeled example pair: a rigid
  alignment by normalised mutual information written with scipy, a local check that marks
  "unreliable here", candidates paired by position, both dates' sizes and the change, a sum of
  diameters labeled computed. Axial, coronal and sagittal views with linked positions, a cine
  through the phases, sagittal acquisitions turned into the axial frame (MedSAM runs on the
  acquisition plane); cases 564 and 537 processed, 563 and 937 re-run (pipeline version 2) so
  every phase ships; the synthetic patient's reads get the same change view without sizes;
  mammography gets a left-right dense-pixel difference and CC/MLO linked behind the nipple.
- **Why:** the prior comparison was the workbench's biggest gap and none of the bundled patients
  has two dates; a patient outside the bundle shown as an example (the slide workbench's
  pattern) is honest about that. scipy (already installed) does a six-parameter rigid alignment
  in about two minutes on the CPU, so SimpleITK (Apache-2.0) was not added; the same code is
  tested in CI on synthetic shifted and rotated volumes. A rigid alignment cannot follow breast
  deformation between exams, so a local check says where it fails instead of hiding it.
- **Consequence:** no new dependency and no new model. Every change rule is a placeholder
  (RECIST 1.1's sum rules borrowed per candidate) and the sum is never a response call. No open,
  permissive, CPU-ready mammography detector was found, so mammograms get no lesion candidates
  and the page says so. Re-running 563 and 937 under version 2 reproduced every diameter, volume
  and kinetic value; only the craniocaudal extent of candidates with empty end slices moved
  (`docs/radiology.md` §2).

## 2026-10-21 — Slide workbench: a second opinion on lymphocytes from the WSInfer TIL model
- **What:** `scripts/slide_pipeline.py til` scores the front-band and peritumoral tiles of a
  scored section with WSInfer's TIL InceptionV4 (CC BY 4.0, TorchScript) and writes `til.json`;
  `invasion.til_disagreement` turns the head-versus-model disagreement into a queue pointer, a
  map layer, a TILs-by-zone column, a search and a comparison row (`docs/pathology.md` §8).
- **Why:** lymphocytes are the head's weakest class (held-out recall 0.74); the model reaches
  AUROC 0.955 for lymphocytes versus the rest on the head's 3 held-out BCSS slides
  with a cutoff of 0.667 calibrated on the training slides (recall
  97%, specificity 79%): the "two models
  disagree" layer the workbench design asked for, at no extra data cost.
- **Consequence:** the model was trained on TCGA, so the held-out AUROC may be optimistic and
  the page says so; a disagreement is a place to look, never a verdict; the tumor model is not
  wired in; the viewer rewrite (slide-viewer branch) owns the layer system, so the page edit is
  one layer entry and one column.

## 2026-10-21 — Slide viewer: OpenSeadragon on release-hosted Deep Zoom pyramids at 1 µm/px
- **What:** the pathology workbench draws its analysis on the patient's own section in a
  pan-and-zoom viewer (`docs/pathology.md` §7): a Streamlit component (plain JavaScript and
  OpenSeadragon 6.1.1, vendored, no build step) over Deep Zoom pyramids cut from each scan's
  own level nearest 1 µm/px, JPEG quality 80. One zip per section on the release
  `slide-tiles-v1`; the app downloads a section's zip when its viewer first opens, checks its
  SHA-256 and serves the tiles through Streamlit's static serving. Overlays are drawn on a
  canvas from a JSON the app writes next to the tiles from the same analysis the page shows;
  nuclei are drawn from the pipeline's own nucleus table, now kept in `nuclei.json`.
- **Why:** the user asked for overlays on the actual slide, at every magnification. Release
  assets keep 661 MB of tiles out of the repository and need nothing but the repository's own
  release; static serving keeps the tiles same-origin with the app, so no second site or CORS
  set-up is needed (GitHub Pages stays the fallback if Streamlit Cloud's static serving fails).
  The scan's own 4× level avoids resampling and sits at 0.99–1.01 µm/px.
- **Consequence:** four large sections are 103–175 MB instead of the 10–40 MB aimed for (H&E
  at 1 µm/px is about 20 KB per tile at quality 80; quality 70 saves only 20%), so the first
  open of those sections waits for the download. Nuclei are circles of their area, not
  outlines (the polygons were never kept); the side-by-side view links zoom by physical size
  and pan by distance but does not register the sections, and says so. The tile map remains
  as the fallback, and every overlay keeps its evidence label in the viewer's legend. Static
  serving is read when the server starts, so until a hot-updated server restarts the tiles are
  served from the component's own folder.

## 2026-10-21 — Documents rules v2: HER2 legends and answers that slid a row are not results
- **What:** the documents rules no longer read a HER2 status or IHC score from a scoring legend
  (a list of categories with their scores, "2=INDETERMINATE", "are considered borderline"), nor a
  HER2 status word that the IHC score in the same stretch argues against (positive with 0 or 1+,
  or 2+ without amplification; negative with 3+). "zero or 1+" is read as the band "0 or 1+".
- **Why:** case 545's report gave HER2 negative and positive, so the Evolution view showed HER2
  as conflicting. The "positive" was not a legend: OCR slid the synoptic form's answers one row,
  so PR's "positive" sits after "HER2/NEU:", and HER2's own answer is "zero or 1+". The same
  template does this in six dev-half reports, and real legends exist at other sites. Bundled
  case 58's "weakly positive (2+)" (FISH negative) read as HER2-positive. On the dev half, a
  positive word next to 2+ disagreed with TCGA in 6 of 7 reports.
- **Consequence:** HER2 precision on the held-out half rose from 80% to 81% (recall unchanged at
  46%; ER, PR and the other fields unchanged). The Methods page, the Evolution view's note and
  the overview cards show 81%. A document that contradicts itself ("Negative reaction ...
  (Score=3+)") now states no HER2 status, only its score. The withholding never makes a status
  from a score. Method text and FISH reference ranges are still misread (`docs/documents.md`).

## 2026-10-21 — Genomics workbench: the genome as a picture; two ploidies; AlphaMissense's license
- **What:** the genomics workbench gains, for the TCGA cases, a copy-number landscape (ASCAT3 gene
  level, the model's own call rule, placeholder cutoffs), mutation burden and allele fractions,
  predicted effect (Ensembl VEP, ClinVar via Ensembl, AlphaMissense), a curated pathway map and a
  variant table over time (`docs/genomics.md`). Purity and a second ploidy come from TCGA
  PanCanAtlas's ABSOLUTE table; when the two ploidy estimates are 1.5-fold apart or more (7 of 40
  cases) the page warns and offers calls relative to ABSOLUTE's ploidy.
- **Why:** calls must match the model's copy-number input (7,993 of 7,999 equal; the rest are
  ambiguous gene symbols), so the median-copy-number ploidy stays the default; but that rule gives
  ploidy 1 for case 49 (ABSOLUTE 1.58) and 4 for case 741 (ABSOLUTE 1.53), turning ordinary copy
  numbers into amplifications or losses, which a reader must see. ASCAT's own purity and ploidy
  are not in the open gene-level file. The burden rate uses the 38 Mb exome size Chalmers et al.
  2017 used for TCGA; KEYNOTE-158's 10 per Mb belongs to another assay and other cancers, so it is
  named and not applied.
- **License:** AlphaMissense's README and its Zenodo record (10.5281/zenodo.10813168) license the
  predictions CC BY 4.0 (read 2026-10-20); the 2023 table's own header still says "CC BY-NC-SA
  4.0". We follow the licensor's current statement, ship only the 21 scores we use, with
  attribution, and Ensembl serves the same scores (they agree for 20 of 20). If the licensor's
  statement changes, the scores can come from Ensembl alone.
- **Consequence:** the ladder's "predicted effect" rung is model inference when a prediction
  exists. PIK3CA H1047R scores "ambiguous" (0.538) while ClinVar and CIViC call it oncogenic: the
  page keeps prediction and interpretation apart and says why. The variant table's ctDNA columns read
  `timeline.CTDNA` (#94).

## 2026-10-21 — One overview per patient file: a workbench contract for summaries and queues
- **What:** every workbench module carries `summary(pf, version=None)` (a few finding cards:
  text, evidence label, source test, method and version, threshold source, trust, where it
  opens) and `queue(pf, version=None)` (look-here items with pointer, why, trust, consequence
  1–3, where it opens and the finding's key), in one shape (`workspace.card` and
  `workspace.look`, `docs/WORKBENCHES.md` §1). `muffle.overview` builds the report's header from
  the summaries and one attention queue from every queue, the SOS alerts and the cross-test
  discrepancies, ordered by consequence × trust (the placeholder weights) and de-duplicated by
  finding key, so an SOS alert and the lab workbench's flag of the same value are one item with
  one review mark. The queue replaces the report's SOS tile; the header's SOS card counts the
  alerts without a mark. Seven cross-test rules join (ERBB2 copy number against HER2, ESR1 RNA
  and ER-alpha protein against ER, PAM50 Basal-like with ER positive, a slide immune desert
  against a high immune RNA score, documents that disagree, documents against the record, an
  imported lab value against the record), each with its cited basis where one exists (PMIDs
  checked on PubMed), and three reducers (repeat IHC or ISH, a second encoder for unsure tiles,
  a re-read of a document).
- **Why:** seven workbenches landed in a week, each knowing only itself; the user's product is
  one evidence-linked picture of a patient. A shared shape lets the report, the export and the
  patient list read every workbench the same way, and lets the next workbench join by adding
  two functions (radiology, evolution and ctDNA, which landed the same day, did).
- **Consequence:** nothing new is computed for the overview: it reads what each workbench
  already decided, with its labels and threshold sources, and "open" lands on the pointer by
  setting the workbench page's own widget state. Trust and consequence per item are the rule
  author's choice, listed in the export with the placeholder weights. An SOS alert and the
  workbench finding it is about share one review key. Keyboard triage uses j, k, p, u and
  o; "mark reviewed" is m, because Streamlit reserves r (and c) for its own shortcuts.

## 2026-10-21 — Evolution view: receptor status from the file's documents when the record has none
- **What:** `evolution.context` reads the ER, PR and HER2 status the documents rules find in a
  file's documents (a TCGA case's pathology report, an imported report) when the record states
  none, as in every TCGA file. Hormone-receptor positive when a document states ER or PR positive,
  negative when both negative; no IHC score or ISH result is turned into a status. The record's
  own status wins and a disagreeing document is named beside it; documents that disagree with
  each other leave the status unknown. Each why line names the document.
- **Why:** the receptor-conditional rows were never definite for a TCGA file, though 15 of the 39
  bundled reports state the hormone-receptor status and 14 the HER2 status.
- **Consequence:** a document's HER2-negative now drops the HER2-positive row although the HER2
  rule's precision is 80% on held-out reports; the drop is listed under "Not raised" with its
  document and the precision is shown in the view, so the read can be checked.

## 2026-10-20 — Radiology workbench, first version: report text plus public TCIA studies
- **What:** Tests → Imaging opens `app/workbenches/radiology.py`. For SYNTHETIC-001 it reads the
  imaging reports as text (reads, new sites, a lesion table, "no measurements recorded", lead and
  lag against CA 15-3); its imaging tests become implemented ("report text, no images"). Three
  held-out TCGA cases with a public TCIA study (563 and 937 breast MRI, 926 mammography) get an
  imaging test that opens an image viewer on small 8-bit copies, with MedSAM contours drawn
  offline from a seed rule's top three boxes, longest diameter, volume and DCE kinetics
  (`scripts/radiology_pipeline.py`, `docs/radiology.md`); the mammogram gets a mammoscreen score
  and density per breast (Apache-2.0, re-built with timm so no remote code runs).
- **Why:** TCGA-BRCA radiology (CC BY 3.0) is the only imaging that joins the omics cohort, and
  5 of the 40 held-out cases have a study; MedSAM ViT-B is Apache-2.0, ungated and runs on this
  CPU at 12–21 s per slice, so contours can be precomputed. The best-annotated breast MRI sets and
  their nnU-Net weights are non-commercial (model survey §3).
- **Consequence:** every contour, measurement and curve type is a model inference, not validated
  on breast MRI here; the seed rule's cutoffs are placeholders and the kinetics cutoffs are
  literature values used as placeholders. No processed patient has two study dates, so prior
  comparison stays planned; 134 of the 139 TCIA patients are in the omics cohort and 20 have two
  dates, which a future bundle could include (needs a new release).

## 2026-10-20 — Tumor evolution as a cited table, ranked per file; clonal order as alternatives
- **What:** an Evolution view in every patient file (`docs/evolution.md`). Its core is a table of
  18 context → event rows (ESR1 under aromatase inhibitors; RB1, FAT1, AKT1 and PTEN under
  CDK4/6 inhibitors; PTEN under PI3Kα inhibitors; BRCA1/2 reversion; ERBB2, NF1, FGFR, ESR1
  fusions and ARID1A under endocrine therapy; receptor conversion; TP53 by subtype; PIK3CA in
  HER2-positive disease) from 37 papers, each PMID and DOI checked against PubMed, each statement
  taken from the abstract. `hypothesis_set` raises a file's rows from its recorded treatment
  classes, receptor status and observed drivers and orders them by a fixed rule. Clonal order uses
  GDC read counts and ASCAT3 copy number for the TCGA cases and lists the consistent orderings as
  alternatives. Trials come live from ClinicalTrials.gov ("<GENE> mutation", breast cancer,
  recruiting or not yet), with a bundled dated snapshot.
- **Why:** VISION parts two and three, built only from what the app holds: the knowledge is
  literature, not a model, so it can be cited and checked, and nothing claims a forecast. A
  fixed ordering rule instead of a score keeps "hypothesis" honest; the frequency shown is always a
  named cohort's. The bare gene symbol is not used as the trial query because the registry expands
  synonyms ("ESR1" returned 155 estrogen-receptor trials, "ESR1 mutation" 37).
- **Consequence:** the report's "Evolutionary hypotheses" line is no longer planned; it names the
  top three and opens the view. The GDC MAFs carry no purity, so no variant is called clonal;
  SYNTHETIC-001 has no allele fraction and says so. The snapshot needs `scripts/refresh_trials.py`
  before a release (the registry terms ask for current data with its date).

## 2026-10-20 — Omics workbench: PAM50 centered on an ER-balanced subset of the cohort
- **What:** the PAM50 call in the omics workbench centers each gene on its median over an
  ER-balanced subset of TCGA-BRCA (every ER-negative tumor by IHC and as many ER-positive, seed 0;
  466 tumors), not on the whole cohort as first specified (`docs/omics.md`).
- **Why:** plain centering agrees with TCGA's published calls on 72.5% of 950 tumors (published
  Luminal A drifts to Normal-like, Luminal B and HER2-enriched); the cohort is about three
  quarters ER-positive, which Zhao et al. 2015 show shifts calls, and their remedy (center on a
  subgroup with the training set's make-up) gives 94.7% (seeds 1–4: 94.1–94.7%).
- **Consequence:** the choice was made after seeing the first result, on the same tumors, so the
  94.7% is reported as agreement with TCGA's calls, not as an independent test; both numbers are
  on the Methods page and in `docs/omics.md`. A cohort with another ER mix needs its own
  reference.

## 2026-10-20 — Slide workbench round 2: the patient's own sections, invasion picture, cells
- **What:** `scripts/slide_pipeline.py` scores a patient's own TCGA diagnostic slide offline
  (tissue grid, a 9,000-tile budget with a tumor-centred window for larger slides, QuiltNet
  embeddings, the round-1 head, StarDist nuclei on up to 400 front-band tiles) and writes a
  small result folder; `muffle.workbench.invasion` adds the direction of invasion (front
  normals, push, 12 arcs, fingers, rose), satellite islands, breakaway candidates with the ITBCC
  counting field, stromal lymphocytes by TILs-WG zone, tumor–stroma ratio, necrosis contact,
  the risk map with cards, the queue, search and the two-section comparison; the page shows all
  of it for five bundled cases (eight slides) and the example region for the rest
  (`docs/pathology.md`).
- **Why:** the user asked for the patient's own slides and the invasion picture ("which way the
  tumor wants to expand, what parts it is targeting, arrows, breakaway cells, cell relations");
  StarDist (BSD-3-Clause, pip, CPU) is the only nucleus model that runs here without a GPU or a
  gated download, and TCGA slides are open access, so small crops may ship.
- **Consequence:** every round-2 cutoff is a placeholder (listed on the page and in
  `docs/pathology.md`), the direction of invasion is labeled a hypothesis about one section,
  StarDist is "pretrained, not validated on breast here", every flag on it says "weak until
  validated", and no pathologist has reviewed a map. Embedding at 3 tiles/s under the shared
  CPU's load means a slide takes 30–60 min; a stronger encoder behind `HF_TOKEN` changes only
  the `encoder` entry of the result files.

## 2026-10-22 — Encoder comparison on the BCSS spike: GigaPath-Flash is the open-license winner
- **What:** seven encoders measured on the spike's tiles with the same head and the same three
  held-out slides (`docs/encoders.md`): GigaPath-Flash 0.919 accuracy (0.917 balanced) against
  QuiltNet-B-32 0.877 (0.854); Hibou-B 0.880, Hibou-L 0.810, and the local-only CONCH 0.896,
  UNI2-h 0.838, GPFM 0.863. With C chosen by cross-validation on the training slides the ranking
  at the top holds (GigaPath-Flash 0.922 / 0.923). Recommendation: re-score the eight sections
  with GigaPath-Flash; the swap itself is the slide pipeline's step, not made here.
- **Why:** the only open-license encoder better than QuiltNet on every held-out slide; the paired
  gain (+4.2 points, interval +0.3 to +8.1) is just clear of zero on 357 correlated tiles.
- **Consequence:** GPFM is treated as local only: its Hugging Face tag says MIT, but its official
  repository is CC BY-NC-ND 4.0 and it is distilled from UNI and CONCH. Hibou loads into
  transformers 5's own DINOv2-with-registers class (its repo code needs transformers 4). Path
  Foundation, H-optimus-0 and Virchow wait for access; Midnight-12k for a GPU.

## 2026-10-20 — Stronger encoders one command away; CC BY-NC-ND encoders enforced local only
- **What:** `scripts/slide_spike.py` gains ten encoder entries (license, gate, preprocessing,
  pooling per model card), `HF_TOKEN` from the environment or `.env` (never printed), `--device
  auto` (CUDA, XPU, CPU), per-encoder run folders (`embed --tiles`) and `compare`, which writes the
  table in `docs/encoders.md`. A gated model without access stops with one line naming the URL.
  UNI2-h and CONCH are marked local only: `embed` and `result` refuse any path inside the
  repository for them. User checklist: `docs/model_access.md`; GPU runbook: `docs/gpu.md`.
- **Why:** the strongest permissive encoders (Hibou, GigaPath-Flash, Path Foundation, H-optimus-0,
  Virchow) are behind Hugging Face click-throughs only the account owners can do; with the
  plumbing in place each one is a single command after the click.
- **Consequence:** the workbench keeps QuiltNet-B-32 (held-out accuracy 0.877, reproduced through
  the new code) until a measured row beats it. Midnight-12k was not trained on (~3 h on this CPU);
  it waits for the GPU run with the gated models. Whether a prize-eligible entry counts as
  non-commercial research stays open (`docs/model_access.md` has the note for the organisers).

## 2026-10-19 — Slide workbench spike: a minimal breast tissue map on an open encoder
- **What:** `app/workbenches/slides.py` shows one precomputed BCSS-annotated TCGA-BRCA region
  (tissue map with hover probabilities, certainty map, quality exclusions, tumor front and
  zones, the head's measured accuracy, what a tile map cannot see). The head is a logistic
  regression on frozen tile embeddings from an ungated MIT encoder, trained on BCSS (CC0) tiles
  with a patient-disjoint held-out set (`scripts/slide_spike.py`). The hosted app runs no
  encoder; it reads the small result folder.
- **Why:** the permissive encoders the survey preferred (Path Foundation, GigaPath-Flash,
  Hibou, H-optimus-0) are gated behind a Hugging Face login, which this session cannot do;
  Midnight-12k (MIT, ungated, ViT-g) and QuiltNet-B-32 (MIT, ungated, ViT-B/32) are the open
  ones. On this PC's CPU (quiet machine) Midnight-12k embeds 0.19 tiles/s at 5.3 GB and
  QuiltNet-B-32 about 10 tiles/s at 1.2 GB; a median TCGA-BRCA slide here has ~5,500 tissue
  tiles, so QuiltNet takes ~10 min per slide and Midnight ~8 h: only the small model fits
  without a GPU. The head: 5 classes, 87.7% accuracy on 3 held-out slides (357 tiles).
- **Consequence:** the encoder's cutoffs carried from the colon analyzer stay placeholders; a
  pathologist has not reviewed the map; the go / no-go for the freeze is in the PR body
  (`app/slide-spike`). Normal breast and DCIS are not in the head: too few labeled BCSS tiles at
  this tile size.

## 2026-10-19 — The app is a clinician application, not a hackathon demo
- **What:** the app's clinician path (patient list, patient file, tests and their workbenches,
  timeline) carries no hackathon, sponsor or "demo" wording. The demo's "Federation" and "How it
  works" tabs become one "Methods and validation" page with model cards, data sources and how
  the case note is produced; provenance lines name the models and services that produced each
  result. The hackathon story stays in `README.md`, `docs/submission.md` and `docs/video.md`.
- **Why:** the user's words: "the actual app is separate from my video submission... It should
  be an application that can be used by a pathologist." Judges still see Nemotron on Token
  Factory in the provenance lines and the README, which meets the entry requirement.
- **Consequence:** the honesty labels (synthetic, simulated, observed / inference / hypothesis,
  placeholder) and the clinician-review line stay; they are not demo talk. `docs/WORKSPACE.md`
  gains a "Product framing" section and `CLAUDE.md` a rule.

## 2026-10-19 — CIViC evidence: compound profiles count, strongest level first; the hosted app downloads the table
- **What:** `civic.evidence` (#56) matches a variant inside CIViC's "OR" compound profiles
  ("PIK3CA H1047R OR PIK3CA H1047Y OR PIK3CA H1047L") and gene-level profiles ("PIK3CA
  Mutation"), never profiles joined with AND or NOT, and ranks every match by evidence level (A
  before E), then the curators' rating, then specificity (the variant, a disjunction covering it,
  the gene) before cutting to `k`. `scripts/save_demo_notes.py` passes the evidence function, so
  regenerated saved notes carry CIViC items. The hosted app (#57) loads CIViC's nightly table
  itself (CC0, ~4 MB, downloaded once per process into the git-ignored cache) behind a quiet
  fallback: if the download or the parse fails, the agent runs without the `treatment_evidence`
  tool and the sidebar says so.
- **Why:** for PIK3CA H1047R in breast cancer the old exact-match-first order showed level C and
  D items and never the level-A fulvestrant + alpelisib item, which CIViC files under the compound
  profile; the `k=3` cut also dropped the level-A gene-level items. On the hosted app the tool
  never existed, because the container has no cached table. Shipping rows inside the bundle would
  freeze the evidence at build time and tie it to the bundled cases; the download keeps one code
  path for local and hosted runs and needs no bundle format change.
- **Consequence:** `make demo-timeline` must be rerun to refresh the CIViC items in
  `app/timeline_synthetic.json` (its scores don't change), and `make demo-notes` regenerates the
  8 saved notes in the labeled format with evidence (about $0.12). Bundle v2 follows
  (`make demo-bundle`, release `demo-bundle-v2`, bump `BUNDLE_RELEASE` in `app/streamlit_app.py`).

## 2026-10-19 — Before the freeze: the workspace slice on existing data (scope B)
- **What:** by the Oct 28 freeze, the app gains the patient record from `docs/WORKSPACE.md`:
  - a patient list, a patient file with an SOS tile, tests and a report timeline;
  - lab and mutation workbenches on existing data (SYNTHETIC-001 and the held-out TCGA cases);
  - one real cross-test workflow: a sequenced driver, its CIViC evidence, and the risk update.

  Slide and scan workbenches, and test import, show as planned.
- **Why:** judges score "a complete product, not a proof of concept", and this shows the
  product loop without new models. The pathology workbench isn't first: the colon analyzer's
  tissue heads don't transfer to breast, so it waits for the model survey's shortlist.
- **Also:** the open fixes from the handoff (CIViC matching, labeled saved notes, bundle v2, the
  hosted demo) run in parallel sessions. The Windows PC runs the code in WSL2.

## 2026-10-19 — The product vision: a clinician workspace with a deep workbench per test type
- **What:** the team's full product idea is written down. `docs/VISION.md` holds the idea
  (characterize the cancer from every test, follow it in a versioned patient file, track its
  evolution, support evolution-informed treatment decisions, learn from contributed data) with
  what the evidence supports. `docs/WORKSPACE.md` specifies the app: a patient list with search,
  a patient file that opens on the latest report (summary, SOS tile, why the AI thinks so, risk
  factors and areas of risk), test import that creates a new report version, a tests browser,
  and a timeline of report versions. Every test type gets its own interactive workbench, analyzed
  tile by tile or region by region (hover for brief stats, click to expand), at the depth of the
  team's Colon Tumor Front Analyzer.
- **Treatment:** the idea of steering the tumor's evolution is recorded as an evidence-backed
  research direction. Each treatment closes the most likely escape routes until a combination can
  block the rest, and slows growth in between. The evidence: PADA-1 and SERENA-6 switched
  treatment on an emerging ESR1 mutation in blood before progression; models of combination,
  extinction and adaptive therapy support the rest. Those models favor giving drugs together over
  closing routes one at a time. The platform shows evidence and hypotheses; it never recommends
  a treatment.
- **Data from clinicians:** roadmap only. No real patient data in the hackathon; federated
  learning stays on simulated hospitals.
- **Cancer:** breast stays (2026-10-18); lymphoma was only an example. Breast also has the
  clearest precedent for the treatment idea (ESR1 mutations under aromatase inhibitors).
- **Why:** the team wants the platform, not only its first slice, written down so every session
  and the submission work from the same picture.
- **Open:** which parts of the workspace ship before the Oct 28 freeze; a survey of public
  pretrained models and datasets for each test type; whether code from the colon analyzer may be
  reused under both hackathons' rules.

## 2026-10-18 — The demo's timeline patient: hand-written, scored by the MSK-CHORD models
- **What:** the synthetic patient (`muffle.timeline`) is written by hand (stage II HR+/HER2−,
  bone recurrence, PIK3CA H1047R, a liver progression at month 12), not sampled from MSK-CHORD
  distributions, so no real patient can be reproduced. At each event from month 0 on it is scored
  by the evaluated landmark models (latest landmark at or before the event, seeds 0–4 as the
  uncertainty range) next to the diagnosis-only baseline; the change since the previous event is
  attributed one change at a time. Only these scores, aggregate metrics and CIViC items are
  committed (`app/timeline_synthetic.json`); the models stay local, since sharing a model trained
  on CC BY-NC-ND data could count as sharing adapted material.
- **Why:** it shows the vision's longitudinal profile on real-data models without hosting or
  showing any MSK-CHORD patient, and the hosted demo needs no MSK-CHORD files.
- **No MSK-CHORD-model output goes to Token Factory** (team decision, 2026-10-19): the timeline's
  risk scores, ranges and attributions come from models trained on MSK-CHORD, so they stay out
  of every LLM call, like MSK-CHORD itself. If the Nemotron agent ever narrates the timeline, it
  gets only the synthetic patient's own events (diagnosis, treatments, labs, imaging,
  sequencing), never the scores; narration is optional, and the demo does without it.

## 2026-10-18 — MuFFLe++ becomes milestone 1 of a cancer intelligence platform
- **What:** the project is reframed around the team's vision (`docs/VISION.md`): a multimodal,
  longitudinal cancer intelligence platform for one cancer. The submission presents MuFFLe++ as
  its **first milestone** for **breast cancer**, not as a federated-learning project; federation
  stays as one measured result (it replaces the "lead with federation" pitch bullet below).
- **Build before the Oct 28 freeze:** (1) every statement in the case note labeled observed /
  model inference / hypothesis; (2) observed driver mutations from GDC open-access masked MAFs
  plus CIViC (CC0) evidence for clinician review; (3) real longitudinal data: **MSK-CHORD**
  timelines, task = risk of progression or death in the next 12 months re-predicted at each new
  event, compared with baselines as the record grows; (4) a synthetic, labeled timeline patient
  in the demo; (5) `docs/registry.md`.
- **MSK-CHORD terms (CC BY-NC-ND 4.0):** local use only; publish code and aggregate results
  with attribution; never commit, host, show or send to an LLM any individual MSK-CHORD patient.
  The demo's timeline patient is synthetic, built from MSK-CHORD's structure, and labeled.
- **Why:** the team wants the project to move toward the vision; these pieces show its core
  ideas (evidence types, timelines, treatment evidence, federation) on real data within the
  deadline. Pathology/radiology encoders, evolutionary hypotheses and real institutions stay on
  the roadmap. TCGA's lymphoma cohort (~48 patients) is too small, so breast cancer stays.

## 2026-10-18 — Hosted demo runs from a 0.9 MB bundle of 40 held-out cases
- **What:** `make demo-bundle` writes `outputs/demo_bundle.pt`: the FedAvg-residual weights,
  the model inputs of 40 held-out patients (the 8 with saved notes plus a spread over the risk
  range), and derived numbers only (all 1,064 predicted risks, layer offsets, per-site
  held-out C-index, risk-group survival curves of the 213 held-out patients). It holds no
  survival times or other patient-level data. It loads with `torch.load(weights_only=True)`,
  so a downloaded file can't run code. Without the checkpoint and cohort, the app loads the
  bundle from `--bundle` / `MUFFLE_BUNDLE`, by default the release asset
  `demo-bundle-v1/demo_bundle.pt` (`GITHUB_TOKEN` lets it read a private repo's release).
  `app/requirements.txt` is the hosted install: CPU torch, no NVFlare. The app finds `muffle`
  in `src/` without a pip install. `make demo-hosted` runs it that way locally.
- **Why:** the hosting decision limits the server to weights plus derived features for a few
  dozen demo patients. Tested in a fresh environment with only `app/requirements.txt`: same
  numbers as the full-data app, a live note works, and the live-notes counter now counts down.
- **Agent:** if the planner uses up its turns before the literature step while named genes
  are available, it gets one extra turn that offers only `search_literature`. Live: case 299
  went from "no literature search was run" to 4 PMC papers.

## 2026-10-18 — Demo redesign; layer contributions measured against a typical patient
- **What:** the demo has three tabs.
  - **Case review:** the 213 held-out patients only (each hospital's validation split, which
    the federated model never trained on). It shows the risk percentile and group, where the
    patient sits among all patients, what drives the risk, a what-if that hides data layers,
    and the case agent's note with its live steps, grounding result, tool trace and a Markdown
    download.
  - **Federation:** the hospitals, the leave-one-hospital-out results (from
    `app/results_tcga_brca.json`, made by `make demo-results`), and Kaplan–Meier curves of the
    held-out risk groups up to 5 years.
  - **How it works:** the method, privacy and limits.

  Live notes are capped at `DEMO_LIVE_NOTES_PER_SESSION` (5). Eight featured patients have
  saved notes from the live agent (`make demo-notes`, all with no grounding issues), shown
  without a key or once the cap is reached. `muffle.demo` builds everything the app shows, so
  the hosted demo can later load it from a bundle instead of the data.
- **Contributions:** a layer's contribution is now its masked effect minus that layer's
  average masked effect over the cohort, so it reads "compared with a typical patient".
  Masking alone shifted every patient by a near-constant per layer (−0.08 to −0.18). That's why
  17% of high-risk patients showed every layer "lowering" risk; with the offset none do, and
  each layer's contributions average zero.
- **Agent details:** tools report whole percentiles ("75th", not "75.5th"). Publication search
  is limited to scholarly and clinical domains: a YouTube video and an antibody vendor page
  had slipped into a note. An all-letter gene symbol must match exactly ("Camp RL" the author
  and cAMP aren't CAMP). Ultra's token limit is 4,096, after a long literature list ran past
  3,000 once and the note fell back to Super.

## 2026-10-18 — Tavily literature search is live; results must name the gene and a cancer
- **What:** `TAVILY_API_KEY` is set (Tavily dev key, free tier). `tavily_search` runs one query
  per gene (at most 3 per call, so at most 3 credits) and keeps a result only if its title or
  snippet names that gene and mentions cancer. When a gene has hits that name this cancer type,
  the others are dropped. The same paper on two sites is kept once, and trial protocol PDFs
  link to their ClinicalTrials.gov study page. Clinical fields (age, stage) can't be searched.
  The planner gets up to 6 turns and one reminder if it stops before searching.
- **Why:** the first live run showed the problems: a combined query or an unnamed id
  (AC138356.2, Y_RNA) returned generic survival-rate pages; RBP1 matched a coronary artery
  disease paper; trial hits were PDFs titled "CLINICAL STUDY PROTOCOL"; and with 4 turns, one
  tool per turn, the planner never reached the search.
- **Result (live, TCGA patient 463):** VAV3 ("a poor prognostic factor in breast cancer"),
  PRAME in breast cancer (PubMed), and a pan-cancer RBP1 paper; every link passed the grounding
  check. A patient whose only features are unnamed ids gets "no literature search was run".
  Best Use of Tavily needs a runtime Tavily call: the agent makes one whenever it names genes.

## 2026-10-18 — Case agent: Super plans, Ultra writes, a grounding check verifies the note
- **What:** Nemotron 3 Super runs the tool loop (up to 4 rounds) and replies DONE. Nemotron 3
  Ultra (`NEMOTRON_WRITER_MODEL`, 3,000 max tokens including its reasoning) gets the case header
  and the tool outputs, without log-risk values or the tools' reading notes, and writes the
  note. `muffle.report.grounding.check_note` (no LLM) then looks for numbers, gene/feature names
  and URLs in the note that no tool returned. If it finds any, the writer gets one rewrite;
  whatever remains is shown under the note in the demo. If Ultra fails, returns nothing or is
  cut off at the token limit, Super writes the note. Ultra is priced at $1 / $3 per 1M tokens
  in the spending cap (price trackers; unverified on the Nebius console).
- **Why:** the Best Apps and Agents track text (Devpost, re-read today) says to "reach for
  Nemotron 3 Ultra when you need serious reasoning, and let Nano or Super handle the fast,
  everyday calls". The check makes "the note cites only tool outputs" something the demo can
  show, not just a prompt instruction.
- **Result (live, TCGA, 5 patients from the 10th to the 99th percentile, both writers on the
  same tool results):** after the prompt fixes all 10 notes passed the check with no rewrite.
  Ultra's notes are a little richer (feature scores, cohort size). A report costs about $0.01
  with Ultra (about $0.003 with Super alone) and takes 7–10 s. The first run showed what the
  fixes address: both models left the clinical layer out of Drivers, notes repeated log-risk
  values and double negatives ("lowered by −0.12"), and one Ultra note was cut off at 2,000
  tokens. This work cost $0.11 of the cap.
- **Open:** a layer's contribution is measured against the same patient with that layer masked
  out, so a high-risk patient can show every layer "lowering" risk (seen at the 70th and 90th
  percentiles). Report contributions relative to the cohort average instead (demo work, step 2).
- **Rules re-check (2026-10-18):** the Submission Period began Aug 26, so the repo is a new
  project. A project can win one Overall or Track award plus one Bonus award. Best Use of
  Tavily needs a runtime Tavily call (we have no key yet). There is a Most Valuable Feedback
  prize ($100 + swag, 10 winners), so keep a running feedback log.

## 2026-10-18 — Nemotron model, and a hard $25.50 Token Factory spending cap
- **Model:** `nvidia/nemotron-3-super-120b-a12b` (`NEMOTRON_MODEL`). Token Factory lists five
  Nemotron ids (3 Nano 30B-A3B, 3.5 Lightning, 3 Super 120B-A12B, 3 Ultra 550B, 3.5 Super VL);
  Super ran the case agent with tool calling on the first try: TCGA patients 0 and 5 gave
  `mode=agent`, 3 tool calls, ~4.8k tokens, about $0.002 per report. Ultra wasn't tried (cost).
- **Spending cap:** every live call goes through `muffle.report.budget`. It reserves the
  worst-case cost before sending (input estimated at 2 characters per token, plus the full
  `max_tokens`), swaps in the real cost from `usage` afterwards, and refuses any call that could
  take total spend past $25.50; the report then falls back to the offline template.
  `TOKEN_FACTORY_BUDGET_USD` can lower the cap but not raise it. Prices: Super at $0.30 / $0.90
  per 1M input / output tokens (price trackers; the official page needs a login); other models
  are charged a deliberately high $3 / $9 until their real price is added.
- **Why:** the Token Factory account is billed automatically once the credit runs out, and
  the team only wants to spend the $25 promo credit.
- **Limits:** the ledger (`~/.muffle/token_factory_spend.json`) only counts calls made by this
  code on this Mac; add console-playground or other usage with
  `python -m muffle.report.budget --add <USD>`. On Streamlit Community Cloud the ledger lives
  in the container and resets on restart, so give the hosted app a low
  `TOKEN_FACTORY_BUDGET_USD` secret and check the Usage tab in the Nebius console.

## 2026-10-18 — Pitch, demo model, endpoint, hosting, merging and video
- **Pitch:** lead with federation: on leave-one-site-out, FedAvg-residual matches pooled
  training (0.693 ± 0.017 vs 0.700 ± 0.012; the gap is below the ~0.01 by which identical
  FedAvg runs differ) and beats hospitals training alone (local-only 0.649 ± 0.032), and no
  patient data leaves a site. Plain FedAvg (0.680 ± 0.008) has the smallest spread of the
  multi-omic models. Say plainly that omics don't beat clinical data on BRCA overall survival
  yet (clinical-only 0.702 ± 0.004). The clinical-anchored residual model (#25) is a
  supporting point (omics only correct the clinical risk), not the headline. Don't write
  "≫ alone": the gain over local-only (+0.044) is about 1.4 local-only sd.
- **Demo model:** FedAvg-residual if its LOSO C-index on the reported seeds is at least plain
  FedAvg's and the agent's tools (risk, contributions, top genes) still work with it;
  otherwise plain FedAvg (#28). Applied: 0.693 ≥ 0.680 and the tools work, so
  `make fl-tcga` builds FedAvg-residual (λ = 0.25).
- **Endpoint:** overall survival for every reported number. PFI only as a time-boxed check
  after the submission requirements are done, and only if TCGA-CDR shows clearly more events
  than OS; if we run it, report both endpoints.
- **Hosting:** Streamlit Community Cloud. The server gets only the trained weights and derived
  features for a few dozen held-out demo patients, from a GitHub release asset (the repo bans
  `.pt`/`.npz`). The Token Factory key is a Streamlit secret, agent calls are capped per
  session, and cached reports for the demo patients are the fallback.
- **Merging:** Claude may squash-merge its own PRs once CI is green if they stay within the
  agreed plan. It still asks for PRs that change reported numbers or the pitch, touch
  submission material (README, Devpost text, video), make the repo public, or land after the
  Oct 28 freeze.
- **Video:** one person records (≤ 3 min, public YouTube, no copyrighted music), agent demo
  first: ~20 s problem, ~80 s one held-out patient (the agent's tool calls and summary),
  ~50 s results (FedAvg vs alone, clinical baseline), ~20 s stack (NVFlare, Token Factory,
  Nemotron). Claude drafts the script and shot list.
- **Why:** these are the claims the numbers support, and the cheapest path to the requirements
  in the 12 days left. The free-credit rule and the "only derived numbers" rule carry over to
  the hosted demo.

## 2026-10-18 — Clinical-anchored residual model (#25); demo model uses it
- **What:** `muffle.residual`: train the clinical anchor alone, freeze it, train the omic heads
  on top; log-risk = clinical + λ·omics with λ ∈ {0, ¼, ½, ¾, 1}. Centrally, λ is scored on 3
  inner splits that hold out whole tissue source sites; in FL (`fedavg_job --residual`, 20
  anchor rounds then 20 residual rounds) each hospital scores λ on its own held-out sites and
  shares only two pair counts per λ. `make fl-tcga` now builds the FedAvg-residual model.
- **Why:** with random-patient inner splits λ came out ≈ 0.4 and did not transfer to new
  hospitals (omic site/batch effects); site-held-out splits fixed that (tuning seeds:
  0.688 → 0.701 = clinical-only).
- **Result (LOSO, seeds 0–4):** residual 0.700 ± 0.012, FedAvg-residual 0.693 ± 0.017,
  centralized fusion 0.692 ± 0.026, FedAvg fusion 0.680 ± 0.008, local-only 0.649 ± 0.032,
  clinical-only 0.702 ± 0.004. Fusion now matches clinical-only (closes #25); it does not beat
  it. FedAvg numbers vary by ~0.01 between identical runs because NVFlare's initial global
  model is not seeded (0.668 vs 0.680 for the same config).

## 2026-10-18 — Never drop clinical in modality dropout; FedAvg gets 20 rounds on TCGA
- **What:** `model.always_keep: [clinical]` exempts clinical (every patient has it) from
  modality dropout; `fl.rounds: 20` for TCGA (default stays epochs / local_epochs). Datasets
  can now use the top-k features of a layer by asking for fewer in the config.
- **Why (LOSO, tuning seeds only):** dropping clinical 80% of the time taught the model to
  lean on the weak omic layers; keeping it lifted the fused model 0.658 → 0.684 (clinical-only
  0.701). Fewer omic features barely helped (top 32/32/16: 0.667). FedAvg at 10 rounds lagged
  centralized (0.670 vs 0.680); 20 rounds reached 0.691. Keeping each client's Adam state
  across rounds did not help and was not kept.
- **Result (LOSO, reported seeds 0–4):** FedAvg 0.668 ± 0.010, centralized 0.692 ± 0.026,
  local-only 0.649 ± 0.032, clinical-only 0.702 ± 0.004. Validation splits: 0.708 / 0.712 /
  0.665 / 0.737. FedAvg beats local-only with the smallest spread; fusion is within ~0.01
  (centralized) of clinical-only but not above it — still #25.

## 2026-10-18 — Real-data protocol for TCGA-BRCA, and what it showed
- **Protocol:** 3 FL clients built from whole tissue source sites (`data.partition: site`,
  balanced by patients: 355/355/354 patients, 68/56/24 deaths), real modality gaps only.
  Metric: site-stratified pooled C-index (pairs only within a site). Reported seeds 0–4; every
  tuning choice was made on seeds 95–99 only. Two protocols: 20% per-site validation splits,
  and leave-one-site-out (LOSO: train on two hospitals, test on all of the third), which has
  ~4× smaller error bars. FedAvg gets the same passes over the data as the baselines
  (rounds = epochs / local_epochs) and is scored with its final global model.
- **Model for TCGA (`configs/tcga_brca.yaml`):** the default model overfits within ~3 epochs
  (1,800 features, ~120 training deaths), so it is smaller and heavily regularized (hidden 64,
  latent 16, dropout 0.5, weight decay 1e-2, 20 epochs: a plateau on tuning seeds). Additive
  fusion with modality dropout 0.8 beat the concat fusion on tuning seeds (0.718 vs 0.672).
- **Result (LOSO, mean ± sd over seeds 0–4):** FedAvg 0.652 ± 0.022 ≈ centralized
  0.645 ± 0.014 > local-only 0.629 ± 0.020. Same order on the validation splits (0.674 /
  0.661 / 0.626). The federated claim holds on real hospitals.
- **But:** clinical-only (stage, age, T/N/M) scores 0.702 ± 0.004 on LOSO and beats every
  fusion variant tried; copy number alone is anti-predictive across sites (0.485), a sign of
  site/batch effects. On BRCA overall survival the omic layers do not add signal yet with this
  model. Tracked in #25; until fixed, don't claim that multi-omic fusion beats clinical data.

## 2026-10-17 — Keep the current project; make Nemotron a tool-calling case agent
- **What:** we reviewed a broader spec (`MUFFLE_SPEC`: longitudinal visits, imaging/pathology
  foundation models, Flower + DP/SecAgg, treatment rules) and kept the current NVFlare / BRCA /
  synthetic-then-TCGA project. One idea adopted: turn the Nemotron report into a case agent that
  calls our model as tools (risk, modality contributions, top genes) and Tavily, then writes the
  tumor-board summary (#21, built in #23).
- **Why:** the full spec is a multi-week build that needs GPUs and gated, often non-commercial
  models; Flower would replace NVFlare (NVIDIA's own FL SDK); paid Nebius compute is out
  (decision above). The one real risk it raised is a "superficial use" of Nemotron at stage-one
  judging; an agent that plans tool calls answers that cheaply on the free credits.
- **Consequence:** #21 is built offline against a fake client and tested live once the key
  arrives (~Oct 19). Still unverified on Devpost: model-size guidance (Nano/Super vs Ultra), a
  feedback award, and award-stacking rules.

## 2026-10-17 — TCGA-BRCA cohort: Xena GDC hub, CNV as "genomic", RPPA as "protein", OS
- **What:** `scripts/prepare_tcga.py` (logic in `muffle.data.tcga`) builds
  `data/tcga_brca/cohort.npz` from open-tier files on the UCSC Xena GDC hub, one 01A primary
  tumour per patient. genomic = gene-level copy number (ASCAT3) as calls −2..2 relative to
  tumour ploidy, not mutation calls; protein = TCGA RPPA instead of CPTAC; endpoint = overall
  survival. The 3 GB methylation file is streamed and only the selected CpGs are cached.
  Top-variance features are ranked on the log / M scale *before* z-scoring.
- **Why:** open tier needs no application. CPTAC mass spec covers only ~100 TCGA-BRCA tumours,
  RPPA ~80% of the cohort, so protein becomes a real fourth omic layer (`--skip protein` gives
  the mask-0 variant). After z-scoring every feature has variance 1, so ranking afterwards
  would pick features arbitrarily.
- **Consequence:** BRCA OS has few deaths (event rate ~0.14), so per-site C-indexes will be
  noisy; PFI from the TCGA-CDR table is the fallback endpoint. Feature selection is pooled and
  unsupervised; a real federation would agree on features with `harmonize_features`. The
  cohort stores `tss` (tissue source site) per patient for the hospital split (#3).

## 2026-10-17 — Nebius: Token Factory only, on the free hackathon credits
- **What:** our Nebius usage is the Nemotron report via Token Factory, paid for with the free
  hackathon credits (event code on the Devpost page) and nothing else. FL training stays in the
  NVFlare simulator on the Mac; the AI Cloud Serverless Job (GPU) is dropped. Host the demo on a
  free tier (Streamlit Community Cloud), not a Nebius Serverless Endpoint.
- **Why:** the team doesn't want to pay for Nebius. Token Factory alone meets "runs on Nebius"
  and "uses an NVIDIA open model"; the GPU job was the costly part and our cohorts train fine on
  a laptop.
- **Consequence:** issues #4 and #8 updated. `docs/NEBIUS.md`, the Dockerfile and `--gpu` stay
  for later if credits allow. Keep report calls short and watch the credit balance, especially
  once judges use the hosted demo (#13).

## 2026-10-17 — Score FedAvg with the final global model, over several seeds
- **What:** `make compare` scores `FL_global_model.pt` (the last round) on the same per-site
  validation splits as the baselines. Don't report `best_FL_global_model.pt`: NVFlare picks it
  with those same validation C-indexes, so it is optimistic.
- **Why:** per-site validation sets are small (26–94 patients), so a single run's per-site gaps
  of ~0.01 are noise (bootstrap 95% CIs ±0.04–0.10). Over 5 synthetic cohorts the mean C-index
  was local-only 0.737 < FedAvg 0.744 < centralized 0.749, but the per-site order held in only
  1–2 of 5 seeds.
- **Consequence:** report results as mean ± sd over seeds (or on a larger pooled test set). On
  synthetic data local-only is already close to centralized, so the "FL ≫ local-only" story
  needs smaller / more heterogeneous sites or real TCGA sites.

## 2026-10-16 — Target the Nebius × NVIDIA Global AI Hackathon (Devpost), track "Best Apps and Agents"
- **What:** add a Nemotron (Token Factory) patient report + Tavily literature lookup; run FL
  training as a Nebius Serverless Job; MIT license; repo public before submission.
- **Why:** entry rules require running on Nebius and using ≥1 NVIDIA open-source model; there is
  no healthcare track, and an app powered by Nemotron fits "Best Apps and Agents".
- **Consequence:** the plan's Oct–Dec timeline is compressed to 14 days (see `HACKATHON.md`).

## 2026-10-16 — One Mac, one GitHub account, Claude Code for local work
- Repo at `~/PycharmProjects/muffle-plus-plus`; branches + PRs with CI as the gate.

## 2026-10-16 — Start on synthetic data, simulate clients on one machine
- Develop against `scripts/make_synthetic.py` until TCGA is harmonized; run all FL clients in
  the NVFlare simulator.

## 2026-10-16 — NVFlare Recipe API
- `FedAvgRecipe` + `SimEnv` (NVFlare 2.8/2.9). The model is passed as `{class_path, args}`.

## Open questions
- [ ] First cancer: BRCA (most data) — confirm. BLCA second only if time allows.
- [x] Demo hosting: Streamlit Community Cloud (2026-10-18 entry).
- [x] Which Nemotron id on Token Factory: `nvidia/nemotron-3-super-120b-a12b` (2026-10-18 entry).

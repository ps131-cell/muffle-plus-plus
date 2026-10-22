# Clinician workspace and test workbenches

The product through which clinicians use the platform in [`VISION.md`](VISION.md): a workspace of
patient files, in which every test type has its own deep, interactive workbench. This is a design
spec written on 2026-10-19. Today's demo implements parts of it; "Status today" says which, and
what ships before the Oct 28 freeze (scope B, decided 2026-10-19). It is research and decision
support for qualified clinicians: every finding is labeled observed, model inference or
hypothesis, and treatment content is evidence for clinician review, never a recommendation.

## Product framing
The app is a clinician's application, not a hackathon demo (decision 2026-10-19). A pathologist
opens it on their patient list, opens a file on its latest report, looks at the AI's analysis of
each test from there, and sees how the report changed over time. Nothing in that path mentions
the hackathon, its sponsors or a "demo"; that story lives in `README.md`, `docs/submission.md`
and `docs/video.md`. What stays in the app, in product language:
- the product name and a short tagline, and one line "Research and decision support for
  clinicians; not a diagnosis or a prescription";
- provenance everywhere a result appears: data source, method or rule, model and version, and
  the service that produced a note ("note by Nemotron 3 Ultra on Nebius Token Factory");
- the honesty labels: synthetic patient, simulated hospitals, observed / model inference /
  hypothesis, placeholder thresholds, and each module's status;
- one page, "Methods and validation", that holds what the demo's "Federation" and "How it works"
  tabs held: model cards (the risk model with its C-index and calibration, the MSK-CHORD landmark
  models with their AUROC, the rules with their thresholds), data sources and licenses, how the
  case note is produced and checked, and federated training as the way the model was trained
  across simulated sites.

## Screens

### 1. Patients (home)
- Every patient file the clinician has, with a search bar (name or ID) and filters (cancer status,
  last update, open SOS alerts).
- Each row: patient, diagnosis summary, date of the latest report, open SOS alerts, which kinds of
  tests the file holds.
- Built 2026-10-22: a one-line explanation, sorting by last update, risk or open SOS alerts, the
  open SOS count second ("🔴 3 open"), a risk column, the recently opened files, and a
  four-step walk-through the first time the page opens ([`ux.md`](ux.md) §3, §5).

### 2. Patient file: the latest report first
The front page of a file is always the newest version of the report:
- **Summary**: two or three sentences.
- **SOS tile**: alarming findings in the newest results (a new lesion, a quickly rising tumor
  marker, a new resistance mutation), each linked to its test, marked observed or inferred, with
  the rule or model that raised it and how far to trust it.
- **Why the AI thinks so**: every statement links to its evidence (test, region or tile, model or
  rule, version). Today's version of this is the case agent's tool trace and grounding check.
- **Characterization**: type, subtype, stage, grade, receptor status and biomarkers, each labeled
  observed or inferred.
- **Mutations**: observed (which test, when), inferred (from what, how certain) or not tested.
- **Risk**: estimates with their uncertainty, the baseline they are compared with, and whether
  they are calibrated.
- **Risk factors and areas of risk**: which findings raise the risk, and where (organs, lesions,
  slide regions).
- **What changed since the last version, and why.**
- **Evolutionary hypotheses**: the likely next alterations and escape routes, each with its
  sources and the test that would detect it (the Evolution view, `docs/evolution.md`; a
  calibrated confidence per patient stays roadmap).
- **Treatment evidence for clinician review**: CIViC items with their levels, guidelines, trials,
  literature and known resistance mechanisms; never a regimen.
- **Missing data and what it limits** (e.g. "not sequenced since month 0: mutation status after
  treatment unknown").
- **Caveats, data sources and model versions.**

Three buttons lead on: **Import tests**, **Tests** and **Timeline**.

### 3. Import tests
- Any supported test type comes in through its own input adapter: slide images, scan series
  (DICOM), lab results, sequencing reports (VCF/MAF), expression data, text reports.
- Quality control on intake: format, required fields and quality. The import shows what was
  accepted or rejected and why, and never forces a result the data can't support.
- The test joins the file and a new report version is created; older versions are never
  overwritten.
- During the hackathon only public or synthetic data is imported.

### 4. Tests
- Every test in the file with its type, date, source, status (analyzed, quality issue, not
  supported yet) and a short result; filters by type and date.
- Opening a test opens its workbench.

### 5. Timeline
- Every report version from baseline to now on a real time axis, with the tests and treatments
  between versions: one lane per kind (treatments as bars, imaging reads, labs and tumor
  markers, ctDNA, sequencing, pathology and documents, clinic visits, imported tests), SOS
  alerts and progressions in red on their lanes with their evidence labels.
- Clicking any point opens the file as it was at the version that point created (time travel):
  the report, the tests and the attention queue, with a "you are viewing month X; back to
  latest" banner. A "new in this version" card says what that version brought and what changed
  in each workbench, each with "open" on its evidence.
- The risk over time, with the record beside it on demand (CA 15-3 on its own axis, ctDNA,
  treatments, imaging reads).
- Any two versions can be compared: what changed and why. Design: [`timeline.md`](timeline.md).

### Moving between screens
Built 2026-10-22 ([`ux.md`](ux.md) §1–2):
- **Breadcrumbs** head every screen ("Patients › Case 299 › Tests › Pathology slide"); the
  file's crumb is the file picker, so another patient is one pick away.
- **A sticky patient header** keeps the patient, the open SOS alerts and the views on screen
  (windows 1024 px and wider).
- **The way back**: after an "Open", "← Back to the file" and "← Back to the queue, item n of
  N".
- **Deep links**: `?patient`, `?view`, `?test`, `?pointer` and `?version` reopen exactly the
  screen on display, with the pointer in its Spot panel; "Open" and a look-here "Spot" write
  them.
- **Recently opened files** above the patient list.
- **One page skeleton** for every workbench (the clinical documents page joined with its round
  2): title, status chips, overview with the look-here queue, the picture, collapsed details
  with their counts, the Spot panel, the Model and validation card, what the test cannot see,
  export.

## Test workbenches
The depth and the quality-of-life features of each workbench, and what ships before the
freeze, are designed in [`WORKBENCHES.md`](WORKBENCHES.md).

### The depth standard
The team's Colon Tumor Front Analyzer (a separate project on colon cancer whole-slide images, in a
private repository) sets the depth every workbench must reach. It embeds every tile of a slide
with pathology foundation models (CONCH and MUSK), classifies tissue with small trained heads,
checks each tile's quality, maps the tumor and its invasive front, measures growth pattern, depth
hints, tumor-stroma ratio, necrosis, mucin and immune pattern, and raises "look here" flags with a
stated trust level. Every cutoff is tagged by source (literature, calibrated or placeholder), and
its validation and known failures are written down. Reviewers get maps, search, panels and
exports. Its tissue heads are trained on colon tissue, so breast slides need their own.

Each test type needs that same depth, built for its own data. A slide, a scan, a blood panel and
a sequencing report each get their own pipeline and viewer.

### What every workbench has
1. **A native, interactive viewer** for the test's own data: slide tiles, scan slices, lab
   trends, variant tables.
2. **Overview first, then deeper levels**: whole test, region, tile or feature, raw measurement.
3. **Hover, click, more info.** Hovering over a tile or region shows brief stats: risk level,
   model confidence, tissue type (or organ or lesion), which models say so. Clicking expands it:
   a larger view, every model output, measurements, evidence and uncertainty. "More info" opens
   the full summary for that tile, region or test. Lab values work the same way: hovering shows
   the reference interval, trend and source; clicking shows the full history and why any flag
   appeared.
4. **Quantitative measurements** with unit, method, reference population, threshold and
   validation status.
5. **Inspectable findings**: source data, model or rule, evidence, competing explanations and
   uncertainty; observed kept apart from inferred.
6. **A "look here" queue**: regions or results flagged because the risk is high, because the
   models are unsure, or because the models disagree, each labeled with the reason.
7. **Quality control**: artifacts, missing data, unfamiliar inputs, what was excluded and why.
8. **Comparison with earlier tests** of the same type, where that is technically valid.
9. **Review tools**: search and filters, pins and bookmarks, annotations, agree and disagree marks
   on findings, saved views, and exports (a report with figures, measurements, evidence, limits,
   provenance and model versions).
10. **Thresholds tagged by source** (guideline, literature, calibrated, placeholder) and a model
    card for every model.

Images are analyzed region by region, never as one opaque whole-image score: tiles for slides,
and segmented lesions, organs and slices for scans. Region-level findings can still be
aggregated into a whole-test result.

### Per test type

| Test | Viewer | Analysis | Limits to show |
|---|---|---|---|
| Pathology slides (H&E whole-slide images) | zoomable slide with tile overlays: tissue, zones, risk, flags, certainty | tissue class per tile from foundation-model embeddings and trained heads; tumor regions, front and microenvironment; flagged regions | shows no mutations directly; tile size limits what can be seen |
| Radiology (CT, MRI, PET, mammography) | slice viewer, multiplanar views, window and level, lesion contours | lesion segmentation; size, volume, density or uptake; the same lesion tracked across scans | changes must allow for protocol, scanner and alignment; shows no mutations |
| Blood and lab panels (CBC, chemistry, tumor markers) | results table, trend plots with treatments marked | reference intervals for the method, change from the patient's own baseline, rate of change; unit and method checks | out of range is not evidence of progression by itself |
| ctDNA (liquid biopsy) | variants over time with allele fractions | new or rising mutations, e.g. ESR1 | little tumor DNA gives false negatives; blood-cell (clonal hematopoiesis) variants can look like tumor variants |
| Tumor sequencing (DNA) | variant browser, allele fraction, copy number, evidence links | detection, interpretation and predicted effect kept apart; CIViC and literature evidence | one sample is one place and one time; purity and depth limit what is seen |
| RNA expression and methylation | heatmaps, ranked genes, expression distributions, pathway and subtype scores, comparisons across samples and timepoints | normalization stated; differential expression with effect sizes, uncertainty and multiple-testing correction; signatures with their reference definitions; batch, library-quality and missing-gene checks | RNA is not protein, and neither is pathway activity; subtype calls only from a validated model |
| Proteomics (RPPA, mass spectrometry) | protein tables, abundance distributions, fold changes, comparison plots | missingness and detection limits; post-translational modifications such as phosphorylation where the assay measures them; links to pathways and genomics | a DNA variant does not imply a protein level or activity; batch, normalization and multiple-testing controls |
| Single-cell sequencing | cell embedding maps, clusters, marker-gene panels, cell populations per sample | cell-type annotations with confidence, population proportions compared across samples, per-cell quality checks, candidate cell interactions | annotations and inferred interactions are model-supported interpretations, not observed identities or physical contacts |
| Clinical documents | full text with source sentences highlighted | extracted diagnoses, procedures, drugs and dates | documented kept apart from inferred; conflicting reports kept |

## Cross-test and longitudinal intelligence
The value of one record is in connecting tests across modalities and over time. Every connection
carries its source: a direct sample match, an explicit clinical record, a validated statistical
association, or a research hypothesis.
- **Unified patient timeline**: collection dates, results, treatments and later observations on
  one axis.
- **Cross-modality search**: every finding about a gene, a lesion or a documented event, across
  tests.
- **Side-by-side comparison** of two report versions: what changed and why.
- **Evidence graph**: which measurements support each higher-level interpretation.
- **Discrepancy queue**: conflicting results, mismatched sample identifiers, and disagreement
  between models.
- **Research workspace**: related findings and literature gathered for professional review, never
  presented as a diagnosis or a treatment recommendation.

## Pipeline contract
Every test type goes through the same steps:

input adapter → quality control → models and analysis → standardized findings → workbench viewer
→ versioned report and timeline

A standardized finding records: the value or label, unit, method (model or rule, its version and
thresholds), evidence type (observed, model inference or hypothesis), uncertainty, location (tile,
region, lesion, variant), source test and time, and validation status.

## Model and validation cards
| Field | What it records |
|---|---|
| Training data | dataset names, size, labels, institutions, license |
| Design | base model, fine-tuning, version, task, required inputs |
| Performance | metrics that fit the task, on patient-separated test data |
| External validity | other institutions, scanners, labs or cohorts |
| Calibration | whether probabilities match outcomes, and on which cohort |
| Robustness | staining, resolution, assay differences, missing data |
| Uncertainty | what the model can't assess; unfamiliar inputs |
| Known failures | false positives and negatives seen so far |
| Reproducibility | preprocessing, thresholds, versions, timestamps |

Training rules:
1. Train for one clearly defined task: a tissue classifier is not a staging or treatment-response
   model.
2. Prevent leakage: split by patient (tiles of one slide never on both sides); in timelines, use no
   information from after the prediction time.
3. Validate each test type on its own before fusing them; fusion must not hide a weak part.
4. Report uncertainty and failures with metrics that fit the task, not one accuracy target for
   everything.
5. Claim only what was measured on this cancer and these data: a pretrained model's benchmark is
   not evidence for our task.

## Models and datasets to survey
Names only: license, access and validation are not checked yet, and nothing here is used until it
is in [`registry.md`](registry.md). Gated models need access requests.
- **Pathology:** foundation models such as CONCH, MUSK, UNI, Virchow2, H-optimus, Prov-GigaPath
  and Hibou; breast tissue datasets such as BCSS (from TCGA-BRCA slides), BRACS and BACH;
  TCGA-BRCA diagnostic slides (GDC).
- **Radiology:** TCIA breast MRI collections (TCGA-BRCA, Duke Breast Cancer MRI), MAMA-MIA;
  mammography sets such as CBIS-DDSM and VinDr-Mammo; nnU-Net-style segmentation models.
- **Labs:** rules and method-specific reference intervals rather than a foundation model;
  MSK-CHORD tumor-marker timelines (local only) for trends.
- **Genomics and ctDNA:** CIViC (in use), ClinVar, OncoKB (needs a license); public ctDNA
  datasets still to be found.
- **Clinical text:** biomedical language models.

## Status today (2026-10-19)
The app has two pages: Patients (the workspace below) and Methods and validation (a card per
model and per rule with its status, numbers, sources and known failures; federated training;
data sources and licenses; every known failure in one table and every placeholder in another,
read from the modules' constants). A QA walk over every file, view, test, import kind and button
raised no exception or Streamlit warning; what it did find (slow views, a table Arrow re-typed,
labels drawn differently per page) and its status: [`qa.md`](qa.md).

| Spec | Today |
|---|---|
| Patients list with search | Built: SYNTHETIC-001 and the held-out TCGA cases; a search box that also matches genes (PIK3CA), subtypes (luminal), stages and workbenches; filters by PAM50 subtype, mutated gene, stage, open SOS alerts (no review mark yet) and what the file has (slides, imaging, documents); a chip per row for the workbenches that hold the patient's data (2026-10-21, `muffle.overview`, computed once per bundle); a row click opens the file; `?patient=<id>` addresses a file; on a phone the Patient column stays in view |
| Patient file and report | Built: the latest report first: a header of finding cards from every workbench's summary (open SOS alerts, stage and receptors recorded and documented side by side, PAM50 with its margin, key drivers with their best CIViC level, the slide picture, imaging lesions or a public study's headline, the risk, the top evolution hypothesis), each with "Why?" and "Open"; one attention queue (SOS alerts, tests that disagree and every workbench's look-here items, ordered by consequence × trust with placeholder weights, de-duplicated, keyboard triage j / k / p / m / u / o, "open" lands on the pointer; 2026-10-21, `docs/WORKBENCHES.md` §1–2); then the summary, observed record, risk with its model and uncertainty, why, mutations with CIViC evidence, missing data, tests that disagree with what would settle them and their cited basis, what would reduce uncertainty, sources; TCGA files keep the case agent's note with its grounding check, tool trace and evidence chain (each sentence → tool → field → value, with its match) |
| SOS tile | Built: progression, new metastatic site, tumor-marker rise (EGTM rule, unconfirmed until a second specimen), 12-month risk jump (placeholder threshold), new driver with level A or B CIViC evidence. Since 2026-10-21 the header's SOS card counts the alerts without a review mark, and the alerts sit in the report's attention queue (consequence × trust, placeholder weights), each with since when, its rule, threshold source and trust, "open" (landing on the evidence's pointer) and "mark reviewed" |
| Import tests | Built (2026-10-20, `app/workbenches/imports.py`): a button on the file's Import tests view opens a dialog with an adapter per type: lab results CSV (row-by-row checks, rejected rows with the reason), a report as text or PDF (text layer), sequencing results as an annotated VCF or a MAF (2026-10-21: protein-altering variants in the file's breast panel; rejected rows with the reason; a Sequencing test the genomics workbench reads), an imaging report as text or PDF (2026-10-21: an Imaging test with the read its clauses state, negated and hedged ones set aside), a slide region image and a DICOM file (header only; queued for the local pipeline, since the hosted app runs no models), a clinician note. Each import is signed "imported by <initials> at <time>", adds a report version and re-runs the alert rules on what arrived (marker rise; newly sequenced driver with CIViC level A/B evidence; progression on imaging and a new metastatic site, trust moderate since a text rule read them), appears in the export, and is kept for the browser session only ([`documents.md`](documents.md)). Not imported yet: expression data |
| Tests browser | Built: every test with type, month, result and workbench status, a filter by type; a selected test opens its workbench |
| Report versions and timeline | Built (2026-10-22, `app/timeline_page.py`, [`timeline.md`](timeline.md)): an event chart with one lane per kind on a month axis from the diagnosis to now (report versions on top; treatments as bars by a stated display rule, the record holding start dates only; imaging, labs and tumor markers, ctDNA (synthetic series), sequencing and omics, pathology and documents, clinic visits, imported tests), SOS alerts and progressions in red on their lanes with evidence label and trust, hover in the record's own words; a click on any point time-travels: the report, tests, attention queue and timeline re-open as of that version, with a "you are viewing month X; back to latest" banner on every view; a "new in this version" card (tests added, observed rows changed, alerts raised, treatments started, the risk move with its attribution, the workbench findings that changed between this version's and the previous one's summaries, each with Open); the 12-month risk (synthetic patient, model inference) with toggled overlays: CA 15-3 on its own axis, ctDNA allele fractions, treatments, imaging reads; every version in a table; any two versions side by side in the three evidence columns with the attribution underneath and "jump to this version". Imports appear as nodes signed "imported by <initials> at <time>". TCGA files show their one sample at month 0 with their documents' own dates and grow with imports. PNG from the chart's toolbar; the report export has a Timeline section |
| Pathology workbench | Round 3 (2026-10-21, `docs/pathology.md` §7): a pan-and-zoom slide viewer over the patient's own section (OpenSeadragon on Deep Zoom pyramids at about 1 µm/px, one zip per section on the release `slide-tiles-v1`, fetched on first open) draws every layer on the tissue: tiles by class, certainty, QC, zones, immune or risk, the front line, arcs with arrows, breakaway candidates and the counting field, islands, risk regions, pointers and, zoomed in, each counted nucleus by kind; hover stats, click to the Spot panel, jump to any pointer, region, arc, field or island, n / p through the pointers, a minimap and a scale bar; cases 730 and 1043 open their sections side by side with zoom linked by physical size (not registered, said on the page); the tile map below is the fallback when the tiles can't be had. Round 2 (2026-10-20, `docs/pathology.md`): five TCGA cases (299, 926, 1043, 730, 563) open their own diagnostic sections (eight slides scored offline by `scripts/slide_pipeline.py`; the hosted app reads derived numbers and ≤ 60 small crops per slide): tissue map with layers (tissue, certainty, QC, zones, immune, risk) and overlays (front, arrows, breakaway, pointers T1…Tn), hover stats, the direction of invasion as arrows per arc and a rose (labeled a hypothesis about this section, not a forecast), fingers and roughness, StarDist nuclei on the front band (pretrained, not validated on breast: breakaway candidates with the ITBCC 0.785 mm² counting field and the pathologist's own counter, stromal lymphocytes by TILs-WG zone, tumor–stroma ratio, necrosis contact, nuclear-area variation as a proxy), satellite islands with distance and the tissue between, a second opinion on lymphocytes from the WSInfer TIL model (held-out AUROC 0.955; disagreement with the head as a queue pointer, a viewer and map layer and a table column), a risk map with a visible points table and clickable cards (all placeholders), a Spot panel per tile with the crop and nuclei dots, search, review marks and pins (`finding_key` kind "slide"), two sections compared, the model and validation card with known failures, and JSON / CSV / PNG export; files without a scored slide show the public example region and say so; the five-class head keeps its held-out numbers (87.7% on 3 slides); not reviewed by a pathologist; opens from the pathology slide test (TCGA cases with scored sections) or the pathology report (the synthetic patient) in a patient file's Tests |
| Radiology workbench | Built (2026-10-20, round 2 on 2026-10-21; `app/workbenches/radiology.py`, method in `radiology.md`): the synthetic patient's imaging reports read as text (the read in the report's words, new sites, a lesion table across reads, "no measurements recorded", lead and lag against CA 15-3, a change view between two reads); an image viewer for five held-out TCGA cases with public TCIA studies (four breast MRIs, one mammogram): series and every phase, slice, window and level, zoom, axial, coronal and sagittal views with linked positions and the voxel shape said, a cine through the phases at the lesion, MedSAM contours from a seed rule's top three boxes on the acquisition plane with hover stats, longest diameter, volume and DCE kinetics (literature cutoffs as placeholders), the structured report's BI-RADS and receptors, review marks, search and exports; change over time on a public example pair of two dates (not a patient file): rigid alignment by mutual information, "unreliable here" where a local check finds the studies apart, lesions paired with both sizes and the change, a sum of diameters labeled computed, never a response call, protocol differences first; a mammoscreen screening score and density per breast for the mammogram, MONAI's density per view as a second opinion (both Apache-2.0, offline; a known cancer, so nothing to check them against), a left-right dense-pixel difference (placeholder) and CC and MLO linked behind the nipple. Not validated on breast MRI here; mammography lesion contours have no open detector to run |
| Clinical documents workbench | Built (2026-10-20, `app/workbenches/documents.py`): SYNTHETIC-001's record entries, the TCGA cases' pathology reports (TCGA-Reports, CC BY 4.0) and imported documents; breast pathology facts by rules, each highlighted at its source sentence; a facts table that jumps to the sentence, documented kept apart from inferred, conflicts side by side, the documents' own timeline, plain-word search, marks, pins and exports. Measured against TCGA's clinical fields on 481 held-out reports ([`documents.md`](documents.md)). Round 2 (2026-10-21): a second reading by a zero-shot named-entity model (OpenMed, Apache-2.0, run offline; its spans ship as derived JSON) drawn as a layer of model inference and set beside the rules per document, measured on the same reports, with "models disagree" in the queue; scanned PDFs queued for the local pipeline (Granite-Docling 258M, text accuracy checked on four scans); the documents over time (changes, conflicts settled only by the clinician's mark, record-versus-documents discrepancies); search across both layers and a Spot panel |
| Labs workbench | Built (`app/workbenches/labs.py`, opened from a lab test as of the report version): any analyte (2026-10-21, [`labs.md`](labs.md)): a reference table of 17 analytes plus eGFR and albumin-adjusted calcium, with adult intervals by sex from a reference laboratory, units converted at import, the lab report's own interval winning, CTCAE grades for low counts and cross-analyte hypotheses against the imaging reports; trends by panel, pointers, the spot panel with why each analyte matters, kinetics (placeholder method), the EGTM confirmation tracker, therapy windows, markers against imaging, search that names the panel it would take, flags with review marks, quality checks and exports |
| ctDNA monitor | Built (2026-10-21, `app/workbenches/ctdna.py`, [`ctdna.md`](ctdna.md)), on a labeled synthetic series for SYNTHETIC-001 only: allele fractions over time with the detection limit (placeholder), calls with their rules, the ESR1 rule (PADA-1, SERENA-6) as evidence for clinician review, the clonal-hematopoiesis flag (Razavi 2019), lead and lag against imaging and CA 15-3, Spot panel, links to genomics and Evolution, review marks, what ctDNA cannot see, rules card and exports |
| Genomics workbench | Built (`app/workbenches/genomics.py`, opened from a sequencing test; `docs/genomics.md`): provenance strip, variants with detection, interpretation and predicted effect apart, the CIViC evidence ladder with resistance items, panel coverage, the resistance watchlist, review queue and marks; for the TCGA cases the copy-number landscape (ASCAT3, placeholder cutoffs, ABSOLUTE purity and ploidy) with a Spot panel per gene, mutation burden and allele fractions with the clonal range, predicted effect (Ensembl VEP, ClinVar, AlphaMissense; snapshot), a cited pathway map; the variant table over time (blank = not looked; ctDNA columns from the synthetic series, #94) |
| Expression, methylation, protein | Built (`app/workbenches/omics.py`, opened from any data-layer test or the clinical record of a TCGA file; [`omics.md`](omics.md)): the three questions with a check-by-eye queue, the PAM50 subtype call (experimentally validated against TCGA's published calls on this cohort) with its correlations and margin, Hallmark pathway, proliferation and immune scores with hover, receptor consistency (IHC against RNA, ERBB2 copy number and RPPA, with "RNA is not protein"), a card per layer (normalization, contribution against a typical patient, strongest features with cohort percentiles and pathway membership, the layer's own C-index, the copy-number layer's known failure), what-if, a Spot panel per finding, search, marks and pins, JSON and CSV export. Round 2 (2026-10-21): ten RPPA protein pathway scores (Akbani et al. 2014) with each antibody's value, its gene's RNA, its protein-versus-RNA agreement and the genomics pathway map beside it; promoter methylation of ESR1, PGR, BRCA1, RASSF1A, GSTP1 and p16 (core-promoter CpGs unmethylated in normal breast, placeholder calls) with the RNA beside each, and a hypermethylation index (hypothesis); ESTIMATE immune and stromal signatures, the RPPA immune-cell antibodies and an immune picture read with the slide's lymphocytes by zone (agree or disagree, settled by a pathologist's TILs read); a PIK3CA-pathway mutation with high or low PI3K/AKT protein activity and a methylated BRCA1 (or ESR1 against ER IHC) promoter join the queue. Scores are precomputed offline (`scripts/omics_scores.py`, `scripts/omics_scores_2.py`); immune deconvolution and recurrence-score-like signatures planned |
| Status labels on modules | Built: every section shows its evidence labels and its status (implemented, experimentally validated, planned), in one color per label on every page (`muffle.workbench.grammar`); a placeholder is always orange; every workbench names its card "Model and validation card" and has "What this test cannot see" and "Export"; every file's header carries "Research and decision support for clinicians; not a diagnosis or a prescription" |
| Evolution view | Built (2026-10-20, `app/workbenches/evolution.py`, `docs/evolution.md`): the record's events over time; what to watch next from a cited table of 18 context → event rows (37 papers, PMIDs checked against PubMed), raised by the file's treatments, receptor status and drivers, each with evidence for and against, frequency and cohort, the detecting test and CIViC items; clonal order from GDC read counts as alternatives (TCGA cases; purity unknown); recruiting trials for the observed genes (ClinicalTrials.gov, dated snapshot offline); marks, pins, search, export. Hypotheses, not validated predictions |
| Review tools and export | Built in the patient file: agree / disagree / second-look marks with initials and time and pins on alerts, queue items, CIViC items and the risk estimate, and on the findings of every workbench (labs, genomics, slides, omics, documents, evolution) under one shared key (a mark from the report's queue is the workbench's own mark), a filterable list of them, and a one-page Markdown export per report version (every workbench's finding cards, the attention queue, tests that disagree, numbers, sources, placeholders, model versions, marks by finding kind). Marks live in the browser session |
| Learning from clinicians (feedback ledger) | Built (2026-10-22, `app/feedback_page.py`, `muffle.feedback`, [`feedback.md`](feedback.md)): every review mark of the session as a ledger (patient, finding, mark, reviewer, time, the model or rule behind the finding with its version and inputs, the evidence label) with filters; the share of findings marked disagree per model or rule with a 95% interval; the disagreed findings as a queue that opens each in its file; a per-reviewer summary; download as JSON lines (`muffle-feedback/1`) and upload checked at the boundary; each Methods card shows "N findings reviewed, M disagreed this session" and the known failures list the disagreed ones; the report export gains a Feedback section. Marks stay in the browser session and the downloaded files; nothing is sent or trained. Re-calibration, head retraining and federated rounds on the marks are planned (roadmap), behind consent, ethics approval and data agreements |

### What ships before the Oct 28 freeze (scope B, decided 2026-10-19)
Starting with the pathology workbench would reuse the most existing work, but the colon
analyzer's tissue heads were trained on colon tissue and don't transfer to breast. So the order is:
1. **The patient record:** patient list, patient file with SOS tile, tests and report timeline,
   for SYNTHETIC-001 and the held-out TCGA cases.
2. **Workbenches on existing data:** labs (tumor markers) and genomics (observed drivers with
   CIViC evidence).
3. **One real cross-test workflow:** a sequenced driver, its CIViC evidence, and the timeline's
   risk update with what changed and why.
4. **Pathology and radiology:** shown as planned, pending the model and dataset survey's
   shortlist. (Superseded: both shipped as workbenches on 2026-10-20 and 21; see the table above.)

Everything else in this spec is roadmap, and the app labels it so (`decisions.md`, 2026-10-19).

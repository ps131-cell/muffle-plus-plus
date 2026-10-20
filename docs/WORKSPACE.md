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
- **Evolutionary hypotheses** (roadmap): the likely next alterations and escape routes, with
  their confidence.
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
  between versions.
- Clicking a version opens the report as it was then. Its **Tests** button lists the tests added
  in that version, explorable the same way as current ones.
- Any two versions can be compared: what changed and why.

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
The app has two pages: Patients (the workspace below) and Methods and validation (model cards,
alert rules, how the case note is made, federated training, data sources and licenses).

| Spec | Today |
|---|---|
| Patients list with search | Built: SYNTHETIC-001 and the held-out TCGA cases, with search, an SOS filter and a row click that opens the file; `?patient=<id>` addresses a file |
| Patient file and report | Built: the latest report first (summary, SOS tile, observed record, risk with its model and uncertainty, why, mutations with CIViC evidence, missing data, tests that disagree with what would settle them, what would reduce uncertainty, sources); TCGA files keep the case agent's note with its grounding check, tool trace and evidence chain (each sentence → tool → field → value, with its match) |
| SOS tile | Built: progression, new metastatic site, tumor-marker rise (EGTM rule, unconfirmed until a second specimen), 12-month risk jump (placeholder threshold), new driver with level A or B CIViC evidence. A triage queue (this version first, then earlier), ordered by consequence × trust (placeholder weights); each alert says since when, its rule, threshold source and trust, with "open the test" (lands on the evidence), "mark reviewed" and next / previous |
| Import tests | Planned, and shown as planned |
| Tests browser | Built: every test with type, month, result and workbench status, a filter by type; a selected test opens its workbench |
| Report versions and timeline | Built for SYNTHETIC-001: a version slider re-opens the report, tests and timeline as they were; the risk timeline marks treatments; any two versions compare side by side in the three evidence columns (added, removed, changed) with the attribution underneath. TCGA files have one version |
| Pathology workbench | Round 2 (2026-10-20, `docs/pathology.md`): three TCGA cases (299, 926, 1043) open their own diagnostic sections (four slides scored offline by `scripts/slide_pipeline.py`; two more cases are being scored for a follow-up; the hosted app reads derived numbers and ≤ 60 small crops per slide): tissue map with layers (tissue, certainty, QC, zones, immune, risk) and overlays (front, arrows, breakaway, pointers T1…Tn), hover stats, the direction of invasion as arrows per arc and a rose (labeled a hypothesis about this section, not a forecast), fingers and roughness, StarDist nuclei on the front band (pretrained, not validated on breast: breakaway candidates with the ITBCC 0.785 mm² counting field and the pathologist's own counter, stromal lymphocytes by TILs-WG zone, tumor–stroma ratio, necrosis contact, nuclear-area variation as a proxy), satellite islands with distance and the tissue between, a risk map with a visible points table and clickable cards (all placeholders), a Spot panel per tile with the crop and nuclei dots, search, review marks and pins (`finding_key` kind "slide"), two sections compared, the model and validation card with known failures, and JSON / CSV / PNG export; files without a scored slide show the public example region and say so; the five-class head keeps its held-out numbers (87.7% on 3 slides); not reviewed by a pathologist; opens from the pathology slide test (TCGA cases with scored sections) or the pathology report (the synthetic patient) in a patient file's Tests |
| Radiology workbench | Planned; imaging reports show as text |
| Labs workbench | Built (`app/workbenches/labs.py`, opened from a lab test as of the report version): pointers, trends with the baseline band and treatment spans, the spot panel, kinetics (placeholder method), the EGTM confirmation tracker, therapy windows, markers against imaging, search, flags with review marks, quality checks and exports |
| Genomics workbench | Built (`app/workbenches/genomics.py`, opened from a sequencing test): provenance strip, variants with detection, interpretation and predicted effect apart, the CIViC evidence ladder with resistance items, panel coverage, the resistance watchlist, review queue and marks; ctDNA planned |
| Expression, methylation, protein | Basic: each layer's effect on the risk and its strongest features; distributions, pathway and subtype scores planned |
| Status labels on modules | Built: every section shows its evidence labels and its status (implemented, experimentally validated, planned) |
| Review tools and export | Built in the patient file: agree / disagree / second-look marks with initials and time and pins on alerts, CIViC items and the risk estimate, a filterable list of them, and a one-page Markdown export per report version (numbers, sources, placeholders, model versions, marks). Marks live in the browser session |

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
   shortlist.

Everything else in this spec is roadmap, and the app labels it so (`decisions.md`, 2026-10-19).

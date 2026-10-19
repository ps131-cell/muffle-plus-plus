# Clinician workspace and test workbenches

The product through which clinicians use the platform in [`VISION.md`](VISION.md): a workspace of
patient files, in which every test type has its own deep, interactive workbench. This is a design
spec written on 2026-10-19. Today's demo implements parts of it (see "Status today"), and which
further parts ship before the Oct 28 freeze is still open. It is research and decision support
for qualified clinicians: every finding is labeled observed, model inference or hypothesis, and
treatment content is evidence for clinician review, never a recommendation.

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
| RNA, methylation, protein | heatmaps, ranked features, pathway and subtype scores | normalization stated; signatures with their reference definitions | RNA is not protein, and neither is pathway activity |
| Clinical documents | full text with source sentences highlighted | extracted diagnoses, procedures, drugs and dates | documented kept apart from inferred; conflicting reports kept |

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
| Spec | Today |
|---|---|
| Patients list with search | Not built; Case review has a selector over held-out TCGA patients |
| Patient file and report | Partly: Case review shows risk, layer contributions, a what-if for missing layers, and the case agent's labeled note with its grounding check and tool trace |
| SOS tile | Not built |
| Import tests | Not built |
| Tests browser | Not built; the timeline tab has an event log |
| Report versions and timeline | Partly: the synthetic patient's timeline re-scores the risk at each event and says what changed and why |
| Pathology workbench | Not built for breast; the colon analyzer is a separate project |
| Radiology workbench | Not built |
| Labs workbench | Partly: the synthetic patient's CA 15-3 and CEA values in its timeline |
| Genomics workbench | Partly: observed driver mutations (TCGA) with CIViC evidence, whose matching misses compound profiles |
| Expression, methylation, protein | Used by the risk model; per-layer top features only |
| Status labels on modules | Not built |

Open: which of these ship before the Oct 28 freeze, and the model and dataset survey above
(`decisions.md`, 2026-10-19).

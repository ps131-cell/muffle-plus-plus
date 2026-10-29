# MuFFLe++: a breast cancer intelligence platform, milestone 1

A breast cancer changes over time, and the evidence about one patient is scattered across
slides, scans, reports, sequencing, blood tests and hospitals that can't pool their data.
MuFFLe++ is a clinician application that keeps that evidence in one patient file: it opens on
an overview of what every test says, each test opens a workbench built for its own data, and the
report keeps a version for every new result. Every finding is labeled **observed** (measured or
recorded), **model inference** (a prediction, with its uncertainty) or **hypothesis**
(literature and evidence leads); every module says whether it is implemented, experimentally
validated or planned; every threshold names its source, and an unvalidated one is marked
**placeholder**. It is research and decision support for clinicians, not a diagnosis or a
prescription.

It is milestone 1 of a multimodal, longitudinal cancer intelligence platform
([`docs/VISION.md`](docs/VISION.md)), built for the Nebius × NVIDIA Global AI Hackathon: an
**NVIDIA Nemotron** case agent on **Nebius Token Factory** writes each tumor-board note, and the
risk model is trained across simulated hospitals with **NVIDIA FLARE**.

**Live app:** https://cancer-intelligence-platform.streamlit.app (Streamlit Community Cloud, no
login). It holds 40 held-out TCGA-BRCA patients, each assigned to one of three **simulated**
hospitals, and SYNTHETIC-001, a **synthetic** patient written by hand.

## For reviewers: a five-minute path
If the app was asleep, the first load can take a minute (Streamlit wakes it); after that each
link below opens its screen directly, in the order of the demo video.

1. [Patients](https://cancer-intelligence-platform.streamlit.app/): the worklist. Look at the
   cohort strip (41 files, risk groups, the three simulated hospitals with their held-out
   C-indexes), then type PIK3CA in the search box (12 of 41 files).
2. [Case 299, the report](https://cancer-intelligence-platform.streamlit.app/?patient=Case%20299&view=Report):
   the cockpit (risk model, driver mutations with their CIViC ladder, what to look at next) and
   one attention queue; hover a finding for its source, press J and O to walk the queue.
3. [Case 299, its slide map](https://cancer-intelligence-platform.streamlit.app/?patient=Case%20299&view=Tests&test=Pathology%20slide%7C%7CDiagnostic%20H%26E%20section%28s%29%20%28GDC%2C%20open%20access%29&pointer=T1):
   the patient's own H&E section with the tissue map on top; switch the view buttons (Tissue,
   Zones, Risk), search "lymphocytes at the border", then Zoom to the cells.
4. [Case 299, genomics](https://cancer-intelligence-platform.streamlit.app/?patient=Case%20299&view=Tests&test=Mutation%20panel%7C%7CSomatic%20mutations%2C%2016%20breast%20cancer%20drivers%20%28exome%20sequencing%29):
   each variant's evidence on its own rung (detected, interpreted, predicted), the copy-number
   landscape and the pathway map.
5. [Case 937, the breast MRI scan map](https://cancer-intelligence-platform.streamlit.app/?patient=Case%20937&view=Tests&test=Imaging%7C%7CBreast%20MRI%20%28dynamic%20contrast-enhanced%29%2C%20public%20TCIA%20study%20%282000-08-24%29&pointer=C1):
   MedSAM contours on the study's own image; switch Lesion, Kinetics and Enhancement and step
   through the slices.
6. [SYNTHETIC-001, CA 15-3](https://cancer-intelligence-platform.streamlit.app/?patient=SYNTHETIC-001&view=Tests&test=Lab%7C11%7CCA%2015-3&pointer=L4):
   a synthetic patient; the marker's rise at month 11, unconfirmed until a second specimen
   (the EGTM rule).
7. [SYNTHETIC-001, the Timeline at month 12](https://cancer-intelligence-platform.streamlit.app/?patient=SYNTHETIC-001&view=Timeline&version=11):
   the file as it stood at month 12 and the version diff: the risk jumps from 37% to 88%, beyond
   the five models' spread, and the findings that changed are listed.
8. [Methods and validation](https://cancer-intelligence-platform.streamlit.app/methods): a card
   per model with its evidence category and known failures, the federated training across
   simulated hospitals (NVIDIA FLARE), and every placeholder in one table.

## What is in the app
- **Patients:** a **Start here** card (the longitudinal example SYNTHETIC-001, and Case 299 with
  its own slide and sequencing); pinned and recently opened files; search by patient, gene,
  subtype, stage or workbench; filters by subtype, gene, stage, open alerts and what the file
  holds; **Search every file**, a plain-words search across every file's findings (cards,
  attention items, variants, documented facts, hypotheses) that opens the finding; a four-step
  walk-through on the first visit and a "?" guide on every screen.
- **Patient file:** an action row on every view (Attention queue, Import a test, Compare
  versions, Export this report, Your marks, Pin this file, Methods and validation, How to read
  this); finding cards from every workbench with **Why?** and an **Open** that names where it
  lands; one attention queue (alerts, tests that disagree, every workbench's look-here items)
  with keyboard triage, review marks and a **Next step** line; a cockpit of three columns (the
  risk model with its uncertainty, the driver mutations with their CIViC evidence ladder for
  clinician review, what to look at next), each finding's source, method and version on hover;
  **Where this patient sits**
  (percentiles among the 40 TCGA files) and **Similar patients** (the five nearest TCGA files on
  eight recorded and derived fields), both lookups over what the files hold, not a model
  ([`docs/cohort.md`](docs/cohort.md)); a one-page export. **Tests** opens on a launcher: a tile
  per test with what it holds and its look-here count, a dated series as one tile with a pill
  per month. Breadcrumbs name the open workbench ("Tests › Labs › CA 15-3, month 11") under a
  sticky patient header; the address (`?patient`, `?view`, `?test`, `?pointer`, `?version`)
  reopens the same screen and finding ([`docs/ux.md`](docs/ux.md)).
- **Case note:** Nemotron 3 Super plans and calls our tools, Nemotron 3 Ultra writes, a
  plain-code grounding check verifies every number, gene and link (TCGA files).
- **Timeline** ([`docs/timeline.md`](docs/timeline.md)): every test, treatment, alert and report
  version on one month axis, a lane per kind, each version marked by its risk shift; **time
  travel**: click any point or a row of the versions table to open the file as it stood at that
  version; **compare two versions**: the risk delta against the five models' spread, then the
  findings, tests, attention items and note sentences that changed (a difference between two
  snapshots, not a forecast).
- **Feedback** ([`docs/feedback.md`](docs/feedback.md)): every review mark as a ledger record
  with the model or rule behind its finding, disagreement rates per model or rule with a 95%
  interval, the disagreed findings as a queue, export and import. Marks stay in the browser
  session; nothing is trained on them.
- **Import tests:** lab CSVs, reports (text, PDF), VCF / MAF, imaging reports, slide images,
  DICOM headers, notes; public or synthetic data only.
- **Methods and validation:** a card per model and rule with its evidence category and an
  EASSI-H reporting line, federated training, data sources, every known failure and every
  placeholder, and planned modules (infrared chemical imaging) marked planned and cited.
- **Look:** a clinical light theme (IBM Plex Sans and Mono, compact controls, AA colours; colour
  is never the only signal); the sidebar's **About this system** shows the release, each
  simulated site's held-out C-index, the models, the case-note spend against the cap and the
  code's version.

| Workbench | What it does | Status |
|---|---|---|
| Pathology ([`docs/pathology.md`](docs/pathology.md)) | a slide map on the patient's own section (5 cases, 8 sections): seven views, search inside the slide, a section report, and a pan-and-zoom viewer to single nuclei one click away; tissue map from a BCSS-trained head on GigaPath-Flash (tiles unlike its training tissue not scored); invasive front and direction of invasion; tissue by zone; StarDist nuclei, breakaway candidates, TILs by zone; a WSInfer second opinion on lymphocytes | implemented; head measured on held-out slides (91.9%); not reviewed by a pathologist; carried-over cutoffs are placeholders |
| Expression, methylation, protein ([`docs/omics.md`](docs/omics.md)) | PAM50, Hallmark and RPPA pathway scores, promoter methylation, immune and stromal picture, the ECM3 four-gene stroma score (a cohort percentile, no cutoff; Triulzi 2013), receptor consistency | PAM50 experimentally validated against TCGA's published calls (94.7% of 950 tumors, κ 0.92; the ER-balanced centering was chosen after seeing the first result, 72.5%, so not an independent test); receptor levels against recorded IHC: ER AUC 0.958, PR 0.926, HER2 0.811 (RNA), cutoffs calibrated in-sample; the rest implemented, methylation cutoffs placeholders |
| Genomics ([`docs/genomics.md`](docs/genomics.md)) | variants with detection, interpretation and predicted effect apart (VEP, ClinVar, AlphaMissense); CIViC ladder; copy-number landscape with ABSOLUTE purity and ploidy; burden; pathway map; variants over time | implemented; copy-number cutoffs placeholders |
| Radiology ([`docs/radiology.md`](docs/radiology.md)) | report reading; a scan map on the study's own image for 5 TCIA cases (lesion, kinetics, enhancement, change and density layers, a slice slider, search, click to the Spot panel) with MedSAM contours and kinetics; mammoscreen and MONAI density; change over time on a labeled public example pair | implemented; not validated on breast imaging here; kinetic cutoffs placeholders |
| Clinical documents ([`docs/documents.md`](docs/documents.md)) | breast pathology facts by rules, each at its source sentence; an open oncology named-entity model's reading beside the rules (model inference); conflicts side by side; scanned PDFs read to text in the local pipeline | implemented; rules measured on 481 held-out TCGA reports (precision 81–98% on 9 of 10 fields, recall 6–82%); the model mostly marks where a field is named, not its result (recall 0–11%), so it stays a second opinion |
| Labs ([`docs/labs.md`](docs/labs.md)) | any analyte with reference intervals from the Mayo Clinic Laboratories catalog (the lab report's own interval wins), CTCAE grades, kinetics, EGTM rise confirmation | implemented, rules only, not validated on a cohort |
| ctDNA monitor ([`docs/ctdna.md`](docs/ctdna.md)) | allele fractions over time, the ESR1 rule, clonal hematopoiesis flag | implemented on a **synthetic** series only |
| Evolution ([`docs/evolution.md`](docs/evolution.md)) | what to watch next from a cited table (18 rows, 37 papers), clonal order as alternatives, ClinicalTrials.gov matching | implemented; hypotheses for clinician review, not validated predictions |

```
 Hospital A ─┐  encoders: genomic · RNA · methylation · protein · clinical
 Hospital B ─┼▶ masked late fusion ─▶ DeepSurv (Cox) head ─▶ risk
 Hospital C ─┘  weights only ─▶ NVFlare server (FedAvg) ─▶ global model
                                              │
     risk + drivers + CIViC + literature ─────┴─▶ Nemotron (Token Factory) ─▶ case note
```

Sites missing a data type still participate: that encoder is masked out (MuFFLe-style), and the
model is trained with modality dropout so it stays calibrated when layers are missing.

## Quick start (macOS or Linux, Python 3.10–3.13; on Windows, use WSL)

```bash
git clone https://github.com/ps131-cell/muffle-plus-plus.git && cd muffle-plus-plus
make setup      # .venv + PyTorch + NVFlare + deps (make setup PY=python3.12 if python3 is too old)
make test       # unit tests
make local      # synthetic data -> centralized + local-only baselines, saves outputs/centralized.pt
make fl         # FedAvg across 3 simulated hospitals (NVFlare simulator)
make compare    # per-site C-index table: centralized vs local-only vs the final FedAvg model
make tcga       # real data: open-tier TCGA-BRCA -> data/tcga_brca/cohort.npz
make experiment-tcga   # hospital clients: centralized vs local-only vs FedAvg, 5 seeds + LOSO
make fl-tcga    # the demo model: clinical-anchored residual FedAvg -> outputs/tcga_fedavg.pt
cp .env.example .env   # add NEBIUS_API_KEY (Token Factory) and optionally TAVILY_API_KEY
make demo       # Streamlit app: risk groups + Nemotron-written patient report (synthetic)
make demo-tcga  # the same app on TCGA-BRCA with the FedAvg model and real gene names
.venv/bin/streamlit run app/streamlit_app.py   # no local data: loads the release demo-bundle-v2, as hosted
```

## Hackathon: how NVIDIA and Nebius are used
- **NVIDIA FLARE** — federated training (`jobs/fedavg_job.py`, `src/muffle/fl/client.py`).
- **NVIDIA Nemotron via Nebius Token Factory** — milestone 1 of the platform's orchestration
  layer: a tool-calling **case agent** (`src/muffle/report/nemotron.py`) coordinates our models
  and evidence sources into an **evidence-linked note** for one patient. It keeps what was
  **observed** apart from what a model **inferred** and what is only a **hypothesis**, says
  which data is missing, and is written for clinician review, never as a diagnosis or a
  prescription. Three steps:
  1. **Nemotron 3 Super gathers the evidence:** it decides which tools to call
     (OpenAI-compatible tool calling). The tools run locally
     (`src/muffle/report/case_tools.py`) and label what they return:
     - `observed_findings` (*observed*): data layers measured and missing, recorded stage, age
       band
     - `predict_risk` (*model inference*): risk, cohort percentile and risk group from the
       federated model
     - `modality_contributions` (*model inference*): how much each data layer raises or lowers
       the risk compared with a typical patient (`muffle.explain`)
     - `top_features` (*model inference*): top genes/features of a layer by gradient × input
     - `search_literature` (*hypothesis*): Tavily search for papers or clinical trials on up to
       3 named genes, as leads to review (only offered when real gene names and
       `TAVILY_API_KEY` are available)
  2. **Nemotron 3 Ultra writes the note** from the tool outputs (Summary, Observed, Model
     inferences, Hypotheses and evidence, Caveats), each bullet labeled [Observed],
     [Model inference] or [Hypothesis].
  3. **A grounding check** (`src/muffle/report/grounding.py`, plain code, no LLM) flags any
     number, gene or link in the note that no tool returned, so every claim traces back to its
     source. Ultra gets one rewrite; anything left is shown with the note.

  Limits per note: up to 6 planner turns (plus one search-only turn if it stops before the
  literature step), 900 tokens per planner turn, 4,096 for Ultra (its reasoning counts) and 3
  Tavily queries. If Ultra fails or is cut off, Super writes the note. Every call goes through
  a hard $25.50 spending cap (`src/muffle/report/budget.py`; `TOKEN_FACTORY_BUDGET_USD` can
  lower it: $3.00 on the hosted app). Only derived numbers and gene names are sent, never raw
  omics. The app shows each step live, the grounding result and the tool trace. The hosted app
  runs the agent live: five live notes per browser session (`DEMO_LIVE_NOTES_PER_SESSION`),
  "Case agent: live" in its sidebar; its spend ledger lives on the container and starts again
  when Streamlit restarts it, which the per-session limit and the lowered cap bound. Nine saved
  notes ship in the release. Without `NEBIUS_API_KEY` the same tools run in a fixed order and a
  template writes the note. Try one TCGA case from the terminal (after `make tcga` and `make fl-tcga`):
  `make agent-tcga PATIENT=0`.
  In the app, every note names its models and Token Factory, and the Methods page's case-note
  card shows how a note is made and checked.
- **Nebius AI Cloud** — not used in the submission: Nebius usage is Token Factory only, and FL
  runs in the NVFlare simulator. `docs/NEBIUS.md` keeps untested notes for a Serverless Job.
- **Tavily** — the agent's literature and clinical-trial search on the genes behind a patient's
  risk: one query per gene; a result is kept only if it names the gene and a cancer;
  publications come from scholarly and clinical sites; trial hits link to their
  ClinicalTrials.gov page.

Requirements checklist and day-by-day plan: [`docs/HACKATHON.md`](docs/HACKATHON.md).

## Results (TCGA-BRCA, overall survival)
Two different numbers are quoted (decisions 2026-10-21). The **demo model** in the app (release
`demo-bundle-v2`) scores a held-out **C-index of 0.728**: the mean of the three simulated
hospitals' C-indexes on their held-out patients (213 patients, 26 deaths; site-1 0.705, site-2
0.665, site-3 0.815); the app's 40 TCGA files are drawn from those held-out patients. A local
rebuild from re-downloaded data reads 0.730. The table below is the protocol result:
1,064 patients, 148 deaths, split into 3 simulated hospitals made of whole tissue source sites.
Leave one site out: train on two hospitals, test on every patient of the third. Pooled
site-stratified C-index, mean ± sd over 5 seeds (`make experiment-tcga`):

| model | C-index |
|---|---|
| **FedAvg, clinical-anchored residual** (NVFlare, other two hospitals, no data shared) | **0.693 ± 0.017** |
| FedAvg, plain multi-omic fusion | 0.680 ± 0.008 |
| Centralized, clinical-anchored residual (their data pooled) | 0.700 ± 0.012 |
| Centralized, plain fusion | 0.692 ± 0.026 |
| Local-only (one other hospital's own model) | 0.649 ± 0.032 |
| Clinical data only (stage, age, T/N/M), centralized | 0.702 ± 0.004 |

Federated training beats any single hospital's model and comes within ~0.01 of pooling the
data, without moving any patient data. In the clinical-anchored residual model the omic
layers may only correct the clinical risk, weighted by how well that correction transfers to
hospitals it wasn't trained at. **No fusion variant beats clinical data alone** (stage, age,
T/N/M: 0.702 ± 0.004): the pooled residual comes within 0.002 of it (0.700), the federated one
within 0.01 (0.693), plain fusion falls further short. On this endpoint the omics don't (yet)
add signal beyond clinical data. Calibration and per-slice checks:
[`docs/calibration.md`](docs/calibration.md).

## Layout

| Path | What lives there |
|---|---|
| `src/muffle/data/` | synthetic generator, preprocessing, hospital partitioning, `Dataset` |
| `src/muffle/models/` | per-modality encoders, masked fusion, Cox head |
| `src/muffle/losses.py`, `metrics.py`, `engine.py` | Cox loss, C-index, train/eval loops |
| `src/muffle/experiment.py` | repeated-seed comparison, single-modality baselines, leave-one-site-out |
| `configs/` | `default.yaml` (synthetic), `tcga_brca.yaml` (real data; inherits the default) |
| `src/muffle/fl/client.py` | NVFlare Client API script that runs at each site |
| `src/muffle/explain.py`, `report/` | per-patient drivers + Nemotron case agent and its tools |
| `src/muffle/workspace.py`, `overview.py`, `crosstest.py`, `timeline.py` | patient files and report versions, the overview and attention queue, cross-test rules, the synthetic patient |
| `src/muffle/workbench/` | each workbench's logic (labs, ctDNA, genomics, slides, omics, documents, radiology) |
| `jobs/fedavg_job.py` | FedAvgRecipe job, run in the NVFlare simulator |
| `app/streamlit_app.py`, `app/methods_page.py` | the clinician app and its Methods and validation page |
| `app/workbenches/` | each workbench's page and its precomputed results |
| `scripts/` | data prep and offline pipelines: TCGA-BRCA (`prepare_tcga.py`), slides, radiology, omics and genomics scores, documents, trials |
| `docs/` | vision, workspace spec, a method note per workbench, registry, decisions log, hackathon checklist |
| `data/`, `outputs/`, `workspaces/` | **git-ignored** — never commit patient data or checkpoints |

## Data, models and licenses
Every dataset, model and service, with its license, access tier and what leaves the machine, is
in [`docs/registry.md`](docs/registry.md). In short:
- **Data:** TCGA-BRCA open access (GDC / UCSC Xena: omics, masked somatic mutations, copy
  number, diagnostic slides), BCSS (CC0), TCGA-Reports (CC BY 4.0), TCIA breast imaging (CC BY
  3.0), CIViC (CC0), ClinicalTrials.gov, Ensembl VEP and ClinVar, AlphaMissense (CC BY 4.0).
- **Models in the app** (open licenses, precomputed offline; the hosted app runs no model):
  GigaPath-Flash (Apache-2.0), StarDist (BSD-3-Clause), WSInfer TIL (CC BY 4.0), MedSAM, mammoscreen,
  MONAI breast density and the OpenMed oncology named-entity model (Apache-2.0), and NVIDIA
  Nemotron 3 Super and Ultra on Token Factory.
- **Local only:** MSK-CHORD (Jee et al., *Nature* 2024; CC BY-NC-ND 4.0) and the timeline models
  trained on it, and encoders with non-commercial or no-derivatives terms (UNI2-h, CONCH,
  SPIDER-breast): used on our machine; only code and aggregate results are published, never a
  patient, a model or an output, and nothing from them goes to an LLM.

No patient-level data is stored in this repository. Simulated hospitals, the synthetic patient
and its synthetic ctDNA series are labeled as such everywhere.

## Status and roadmap
Milestone 1 (submission Oct 30 2026, 10:00 am PT; freeze Oct 29, 10:00 CDT):
- [x] TCGA-BRCA multi-omic survival model with missing-layer masks; federated training with
      NVIDIA FLARE across simulated hospitals; baselines, leave-one-hospital-out, calibration
- [x] Nemotron case agent on Token Factory with tools, CIViC evidence, Tavily literature, a
      grounding check and a spending cap
- [x] Patient timeline: risk re-estimated as results arrive (MSK-CHORD, aggregate results), shown
      on a synthetic patient
- [x] Clinician app: patient list, overview and attention queue, eight workbenches, import,
      timeline, Methods and validation; hosted on Streamlit Community Cloud
- [x] Registry of datasets, models and services (`docs/registry.md`)
- [x] Navigation and clarity: one page skeleton per workbench, breadcrumbs, deep links, the
      guide and first-visit walk-through ([`docs/ux.md`](docs/ux.md))
- [x] Documents round 2: an open named-entity model's reading beside the rules, measured;
      scanned PDFs in the local pipeline
- [x] Timeline round 2: lanes on a month axis and time travel
- [x] Feedback page: the ledger of review marks (nothing trains on it)
- [x] Encoder comparison on held-out BCSS slides ([`docs/encoders.md`](docs/encoders.md)):
      GigaPath-Flash 0.919 against QuiltNet-B-32 0.877; the eight sections re-scored with it
      (2026-10-27, [`docs/pathology.md`](docs/pathology.md) §9)
- [x] QA round 2 in headless Chrome: 334 screens, 29 findings; the last minor ones fixed on
      2026-10-27 ([`docs/qa.md`](docs/qa.md))
- [x] Every function one click away (2026-10-27): the Tests launcher, the file's action row and
      Next step line, cards whose Open names its destination, Start here and pinned files, a
      tooltip on every control, the breadcrumb naming the open workbench, a how-to line on
      every workbench
- [x] Search across every file, similar patients and cohort position, as lookups
      ([`docs/cohort.md`](docs/cohort.md))
- [x] Performance pass ([`docs/qa.md`](docs/qa.md)): each workbench's summary and queue computed
      once per file and version; a report shown again costs under 0.6 ms instead of 45–267 ms,
      the 114-screen walk runs 5% faster; a memory pass (2026-10-28): a ten-file walk ends at
      612 MB instead of 673–701 MB, under the hosted app's 690 MB
- [x] Round 14 (2026-10-28): the Timeline's version diff, the report's cockpit and a clinical
      light theme, the radiology scan map, the Bhargava lab's stroma work as cited cards and
      planned modules, a faster first screen
- [ ] Video (`docs/video.md`); Devpost form (`docs/submission.md`); submit by Oct 30, 10:00 am PT

Beyond the hackathon ([`docs/VISION.md`](docs/VISION.md)): review by pathologists and
radiologists and calibrated cutoffs in place of placeholders; stronger encoders on a GPU;
inferred mutation status with calibrated uncertainty; evolutionary hypotheses from repeated
sequencing and real serial ctDNA; real contributing institutions, with consent, ethics approval
and data agreements first.

## License
MIT — see [LICENSE](LICENSE).

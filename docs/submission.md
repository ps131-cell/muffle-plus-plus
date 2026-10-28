# MuFFLe++: Devpost submission

The final text for the Devpost form, in the form's order: the project's fields, the story
(Inspiration → What's next), Built with, the links, then the hackathon's own questions (how
NVIDIA and Nebius are used, feedback, testing, data and licenses, prior work). Final numbers pass
2026-10-27, brought up to `main` at 1c2a7d1 the same evening (the slide re-score, the Tests
launcher and action row, cohort search, the performance pass, the slide map port) and at
dbf9d29 on Oct 28 (the version diff, the report's cockpit and clinical theme, the radiology scan
map, the Bhargava lab's stroma work): every figure is listed with its source in the
**Numbers** appendix, and the **Submission checklist** at the end is what is left
to fill on Oct 29.

| Field | Value |
|---|---|
| Project name | MuFFLe++ |
| Elevator pitch | A breast cancer patient file that keeps every test's evidence, labeled observed, inferred or hypothesis, and updates as the record grows; written up by an NVIDIA Nemotron agent on Nebius Token Factory, from a model trained across simulated hospitals with NVIDIA FLARE. |
| Track | Best Apps and Agents (and the Best Use of Tavily bonus) |
| Team | a team of two (names in the checklist at the end) |
| Try it out | https://cancer-intelligence-platform.streamlit.app (Streamlit Community Cloud; no login) · https://github.com/ps131-cell/muffle-plus-plus (MIT) |
| Video | the YouTube URL from the checklist (≤ 3 min) |
| New or existing? | New: the repository was created on Oct 17, 2026, after the Submission Period opened (Aug 26). The slide workbench builds on the team's earlier colon project: its design, and since Oct 27 its slide map, search and export code adapted to breast (files listed); see the prior-work disclosure under **Data, licenses and prior work**. |

---

## Inspiration

A breast cancer changes over time, and the evidence about one patient is scattered: a stage
recorded at diagnosis, a pathology report, slides, a breast MRI, a sequencing panel, expression
and methylation profiles, tumor markers, the treatments given and when. Each test has its own
specialist and its own software, and no hospital has enough patients to learn from alone. A
clinician needs that evidence in one place, with what was measured kept apart from what a model
guessed and what is only a lead from the literature.

Our long-term goal (`docs/VISION.md`) is a multimodal, longitudinal cancer intelligence platform:
it connects specialized models, public datasets and each patient's record over time into one
evidence-linked picture of the disease, and learns across institutions without pooling patient
data. It is research and decision support for clinicians, never a diagnosis or a prescription.
MuFFLe++ is its first milestone, for breast cancer.

## What it does

MuFFLe++ is a clinician application. It opens on a patient list; a patient file opens on an
overview of what every test says; each test opens a workbench built for its own data; a timeline
keeps every version of the report. Every finding carries one of three labels: **observed**
(measured or recorded), **model inference** (a prediction, with its uncertainty) or
**hypothesis** (literature and evidence leads). Every module says whether it is implemented,
experimentally validated or planned, and every threshold names its source; a value nobody has
validated is marked **placeholder** in orange.

**The files.** SYNTHETIC-001, a **synthetic** patient we wrote by hand (not a real person, not
taken from any dataset), carries a 40-month record: diagnosis, adjuvant therapy, a bone
recurrence, tumor sequencing (PIK3CA H1047R), CDK4/6 therapy, a liver progression and alpelisib.
The other 40 files are real, public TCGA-BRCA patients the risk model never trained on, each
assigned to one of three **simulated** hospitals.

**Patients.** A **Start here** card opens the longitudinal example (SYNTHETIC-001) or a case
with its own slide and sequencing (Case 299); pinned and recently opened files sit above the
list. Search by patient, gene (PIK3CA), subtype, stage or workbench; filter by PAM50 subtype,
mutated gene, stage, open alerts and what the file holds (slides, imaging, documents). **Search
every file** looks through every file's findings at once (cards, attention items, variants,
documented facts, methylation calls, hypotheses) in plain words, such as "HER2 disagree" or
"stage III PIK3CA", and opens the finding; it is a text lookup, not a model. A four-step
walk-through on the first visit, a "?" guide and a tooltip on every control say how to read it;
breadcrumbs name the open workbench ("Tests › Labs › CA 15-3, month 11") under a sticky patient
header, and the address (`?patient&view&test&pointer&version`) reopens the same screen on the
same finding, so a link lands on the evidence.

**The patient file.** It opens on finding cards from every workbench (receptors recorded and
documented side by side, PAM50 subtype, drivers with their best CIViC level, the slide picture,
imaging lesions, the risk, the top evolution hypothesis). Each card has **Why?** (source test,
method and version, threshold source, trust) and an **Open** that names where it lands
("Open · Sequencing, month 0") inside its workbench. One attention queue gathers alerts, tests
that disagree (seven cross-test rules, such as ERBB2 copy number against HER2 status, each with
its cited basis) and every workbench's "look here" items, ordered by consequence × trust, with
keyboard triage, review marks and a **Next step** line. An action row on every view holds what a
file can do: Attention queue, Import a test, Compare versions, Export this report, Your marks,
Pin this file, Methods and validation, How to read this. **Where this patient sits** places the
patient's scores among the 40 TCGA files, and **Similar patients** lists the five nearest TCGA
files on eight recorded and derived fields (equal weights, marked placeholder): lookups over
what the files hold, never a prognosis. **Tests** opens on a launcher, a tile per test with what
it holds and its look-here count (a dated series is one tile with a pill per month). Every
report exports as one page. Between the cards and the queue, the report's cockpit sets three
columns side by side: the risk model, the driver mutations with their CIViC evidence ladder, and
what to look at next; every finding there shows its source, method, version and evidence item on
hover and opens its workbench (or civicdb.org) on click. The app has its own clinical light
theme (IBM Plex Sans and Mono, compact controls, AA colours, every chip keeping its word so colour
is never the only signal), and the sidebar's **About this system** shows the system's status: the
release, each simulated site's held-out C-index, the planner and writer models, the case-note
spend against the hard cap, and the code's version.

**Eight workbenches**, each with its own viewer, measurements, look-here queue, quality checks,
"what this test cannot see", a model and validation card, and export:
- **Pathology** (five TCGA cases, eight of their own diagnostic sections): a slide map on the
  patient's own scan, a see-through colour layer in seven views (tissue, zones, risk, flags,
  certainty, quality, immune), with search inside the slide in plain words, a section report
  and a pan-and-zoom viewer down to single nuclei one click away; a tissue map from a breast
  tissue head trained on BCSS on a frozen open encoder (GigaPath-Flash; tiles unlike its
  training tissue are not scored); the invasive front, its zones and the direction of invasion
  per arc (a hypothesis about the section); StarDist nuclei, breakaway (budding) candidates in
  the ITBCC counting field and lymphocytes by TILs zone; a second opinion on lymphocytes from the
  WSInfer TIL model, whose disagreements with the head go to the queue. Seven tile encoders were
  compared with the same head on the same held-out slides (accuracy: GigaPath-Flash 0.919,
  QuiltNet-B-32 0.877), and the sections were re-scored with the winner.
- **Expression, methylation and protein** (TCGA cases): PAM50 subtype with its margin, Hallmark
  pathway scores, ten RPPA protein pathways, promoter methylation of six genes, an immune and
  stromal picture read against the slide's lymphocytes, and receptor consistency (IHC against
  RNA, copy number and protein).
- **Genomics:** variants with detection, interpretation and predicted effect kept apart (Ensembl
  VEP, ClinVar, AlphaMissense), the CIViC evidence ladder with resistance items, the copy-number
  landscape with ABSOLUTE purity and ploidy, mutation burden and allele fractions, a cited
  pathway map and variants over time.
- **Radiology:** the synthetic patient's imaging reports read as text; for five TCGA cases with
  public TCIA studies, a scan map on the study's own image (see-through layers: lesions with
  their MedSAM contours, kinetics by curve type, enhancement, change, density; a slice slider
  inside the map; search in plain words; click a square for its full story), with a cine, MedSAM
  contours of rule-seeded candidates, size, volume and contrast kinetics; mammography with
  mammoscreen and MONAI density; change over time on a labeled public example pair (none of the
  bundled patients has two study dates).
- **Clinical documents:** pathology reports (TCGA-Reports) and imported documents; breast
  pathology facts read by rules and shown at their source sentence, documented kept apart from
  inferred, conflicts side by side; an open oncology named-entity model's reading drawn as a
  second layer (model inference) and set beside the rules field by field, measured on the same
  held-out reports. It mostly marks where a field is named ("ESTROGEN", "MARGINS") rather than
  its result, so the rules stay the documented reading and the model is a second opinion.
  Scanned PDFs are read to text by a page model in the local pipeline.
- **Labs:** any analyte, with adult reference intervals cited from the Mayo Clinic Laboratories
  test catalog, the lab report's own interval winning, CTCAE grades, marker kinetics and the
  EGTM confirmation rule for tumor-marker rises.
- **ctDNA monitor:** allele fractions over time, the ESR1 rule (PADA-1, SERENA-6) as evidence
  for review and a clonal hematopoiesis flag, on a **synthetic** series for SYNTHETIC-001 only
  (no open serial breast ctDNA data exists).
- **Evolution:** what to watch next from a cited table of 18 context → escape-route rows (37
  papers, every PMID checked), clonal order from allele fractions shown as alternatives, and
  recruiting trials for the patient's observed genes from ClinicalTrials.gov. Hypotheses for
  clinician review, never a regimen.

**Import tests:** lab CSVs, reports as text or PDF, VCF and MAF sequencing results, imaging
reports, slide images and DICOM files (header only), clinician notes. Each import is checked row
by row, adds a report version and re-runs the alert rules. Only public or synthetic data is
imported.

**Timeline:** the record on one month axis, a lane per kind (report versions, treatments,
imaging, labs, ctDNA, sequencing, pathology, clinic visits, imports), SOS alerts marked where they
were raised; each report version is marked by how the risk moved since the one before. **Time
travel:** click any point, or a row of the versions table (newest first), and the whole file
opens as it stood at the report version that point created. **Compare two versions** comes first
on the page: the risk delta as a chip, red or green only when it goes beyond the spread of the
five models (otherwise "within the model's uncertainty"), why the risk moved one change at a time,
then the findings, tests, attention items and note sentences that were added, changed or removed,
each opening its evidence as of its version. A delta is the difference between two snapshots of
the record, not a forecast, and the page says so.

**Feedback:** every review mark (agree, disagree, second look, reviewed) becomes a ledger
record naming the model or rule behind its finding, with its version and evidence label; the
page shows disagreement rates per model or rule with a 95% interval, the disagreed findings as a
queue, and exports and imports the ledger. Marks stay in the browser session and nothing is
trained on them: learning from clinicians needs consent, ethics approval and data agreements
first, so retraining is a labeled roadmap card.

**The case note (Nemotron on Nebius Token Factory).** For a TCGA file, a case agent writes a
tumor-board note: **Nemotron 3 Super** plans and calls our tools (what was recorded, the risk and
percentile, each data layer's effect, top features, CIViC evidence for the observed drivers, a
Tavily literature search); **Nemotron 3 Ultra** writes the note, each bullet labeled observed,
model inference or hypothesis; a plain-code grounding check flags any number, gene or link no
tool returned, and the evidence chain ties each sentence to its tool, field and value. Nine notes
are saved in the hosted app; a few live notes run per session.

**Learning across hospitals (NVIDIA FLARE).** The risk model is trained across three simulated
hospitals (TCGA-BRCA tissue source sites) without moving patient data: each site trains locally
and only weights travel, with NVIDIA FLARE's FedAvg. A hospital that never measured a data layer
still takes part (the layer is masked).

**Methods and validation:** a card per model and rule with its status, numbers, sources and
known failures; federated training; data sources and licenses; every known failure in one table
and every placeholder in another.

Only derived numbers (risk, percentile, contributions) and gene and mutation names go to Token
Factory and Tavily: never a patient's omics values, and nothing from MSK-CHORD (neither its data
nor the output of a model trained on it, which includes SYNTHETIC-001's risk scores).

## How we built it

- **Risk model (PyTorch):** an encoder per data layer (copy number, RNA, methylation, protein,
  clinical), masked additive fusion and a Cox (DeepSurv) head, trained with modality dropout that
  never drops clinical data. Clinical-anchored residual: the model learns a clinical risk first;
  the omic layers may correct it by an amount chosen on hospitals it wasn't trained at.
- **Federated training:** NVIDIA FLARE's `FedAvgRecipe` in the simulator, three simulated
  hospitals of 355, 355 and 354 patients; leave one hospital out, five reported seeds, tuning on
  five other seeds, always against clinical-only, one-hospital and pooled baselines.
- **Case agent:** OpenAI-compatible tool calling to Nemotron 3 Super and Ultra on Nebius Token
  Factory; the tools run our models locally; every call goes through a hard spending cap that
  reserves its worst-case cost first. Without a key the same tools run in order and a template
  writes the note.
- **Patient timeline:** gradient boosting trained on MSK-CHORD (5,368 breast cancer patients;
  CC BY-NC-ND 4.0, local only) re-predicts the 12-month risk of progression or death at each new
  event; it scores the synthetic patient.
- **Workbench pipelines** run offline (in WSL on a Windows PC, CPU only) and ship derived numbers
  and small images; the hosted app runs no model. Slides: OpenSlide tiling at 0.5 µm/px,
  GigaPath-Flash embeddings, a logistic tissue head trained on BCSS, StarDist, WSInfer TIL, Deep
  Zoom pyramids served from a GitHub release to an OpenSeadragon viewer. Radiology: TCIA
  downloads, a seed rule, MedSAM box prompts, kinetics, a rigid alignment by mutual information
  written with SciPy. Omics: PAM50 centroids (genefu), MSigDB Hallmark, RPPA pathways (Akbani et
  al. 2014), ESTIMATE gene lists. Genomics: ASCAT3, ABSOLUTE, Ensembl VEP, AlphaMissense.
  Documents: regular expressions and an open zero-shot oncology named-entity model, both
  measured against TCGA's clinical fields; a page model reads scans to text. Evolution: a
  hand-curated table with PubMed-checked citations and ClinicalTrials.gov API v2.
- **App:** Streamlit and Altair on Streamlit Community Cloud, from a small release bundle (model
  weights and 40 held-out cases' processed inputs) plus the slide tiles on a second release. The
  41 files are built once per bundle, and each workbench's summary and queue once per file and
  version (a report shown again costs under 0.6 ms instead of 45–267 ms; whole screens about 5%
  faster; memory unchanged, about 700 MB after a walk through all 41 files). Search across the
  files is a plain index of their findings, built on the first search.

**Models and their licenses.** Used in the app (open licenses, results precomputed offline):
GigaPath-Flash (Apache-2.0), StarDist 2D_versatile_he (BSD-3-Clause), WSInfer TIL InceptionV4 (CC BY
4.0), MedSAM ViT-B (Apache-2.0), mammoscreen (Apache-2.0), MONAI breast density (Apache-2.0),
AlphaMissense predictions (CC BY 4.0), OpenMed ZeroShot NER Oncology 220M (Apache-2.0; its
spans ship for the bundled reports), Granite-Docling 258M (Apache-2.0; scans, local pipeline
only), our own breast tissue head (trained on BCSS, CC0) and
risk model (MIT, TCGA open data), and NVIDIA Nemotron 3 Super and Ultra (NVIDIA open model
license) on Token Factory. **Local only:** models with non-commercial or no-derivatives terms
(UNI2-h and CONCH, CC BY-NC-ND 4.0; GPFM, whose official repository is CC BY-NC-ND 4.0;
SPIDER-breast, CC BY-NC 4.0; PanNuke-trained cell models)
and the MSK-CHORD timeline models may be measured on our machine, but nothing from them enters
the repository, the hosted app, a release or an LLM call (enforced in code for UNI2-h and CONCH).
Every dataset, model and service, with its license and what leaves the machine:
`docs/registry.md`.

## Challenges we ran into

- **Omics underperformed clinical data.** Copy number alone ranked patients worse than chance
  across hospitals (0.485), a sign of site and batch effects. The clinical-anchored residual,
  with its weight chosen on held-out hospitals, closed most of the gap to clinical-only (pooled
  0.700, federated 0.693, against 0.702); no fusion variant beats clinical data alone.
- **Agent reliability.** Notes dropped the clinical layer, Ultra's reasoning ran past the token
  limit, the planner stopped before the literature step. Fixes: the grounding check with one
  rewrite, Super writing the note when Ultra is cut off, one reminder turn.
- **Pathology without a GPU.** Whole-slide encoders run at a fraction of a tile per second on a
  CPU. We scored the slides' regions of interest with a small open encoder (QuiltNet-B-32 first,
  then GigaPath-Flash, Prov-GigaPath distilled to a ViT-S/16), kept the viewer's tiles on a
  release (661 MB that never enter the repository) and wrote down every cutoff carried over from
  colon tissue as a placeholder.
- **A better encoder brought a new failure.** GigaPath-Flash raised the tissue head from 87.7%
  to 91.9% on the held-out slides, but on one section it read cautery-crushed margin tissue, a
  class neither head was trained on, as carcinoma. Tiles unlike anything the head was trained on
  are now left unscored (a cutoff calibrated on the training slides, flagging 0.3% of held-out
  tiles), and what that rule misses is a stated known failure on that section's page. The
  re-score also found that three sections scored through a window had been read from the wrong
  part of the slide (tissue 3–5 mm away, or glass) while the viewer drew them over the right
  part; they are now read at their place.
- **Licenses that change the design.** The strongest pathology encoders are CC BY-NC-ND; we kept
  them local only and built on MIT and Apache-2.0 models. AlphaMissense's table header and its
  README disagree; we follow the licensor's current statement and ship only the 21 scores we use.
  MSK-CHORD allows local research but no redistribution, so its models and their outputs stay
  local and the timeline patient is synthetic.
- **Records are incomplete and messy.** A patient with no mutation call may not have been
  sequenced (unknown, not wild type). OCR in pathology reports slid a form's answers one row, so
  a HER2 "positive" belonged to PR; the rules now refuse a status that the report's own IHC score
  argues against.
- **Two patients for change over time.** None of the bundled patients has imaging on two dates,
  so change over time runs on a public example pair, labeled as such, with a local check that
  says where the alignment fails.

## Accomplishments that we're proud of

- A clinician's path from a patient list to the evidence: an overview with one attention queue,
  and eight workbenches each at the depth of a specialist's tool, not a summary widget.
- Honest labels everywhere: observed, model inference, hypothesis, synthetic, simulated,
  placeholder; a Methods page that lists every known failure and every placeholder.
- Measured where we could: PAM50 agrees with TCGA's published calls on 94.7% of 950 tumors (κ
  0.92; the centering was chosen after a first run, so not an independent test); the tissue head
  reaches 91.9% held-out accuracy on three patient-disjoint slides; the second-opinion lymphocyte
  model reaches AUROC 0.955 on those slides (an upper bound: it was trained on TCGA); when a
  report states a fact, the document rules read it right 91–98% of the time for seven of ten
  fields on 481 held-out reports. The numbers appendix lists each with its caveat.
- Federated training across simulated hospitals comes within 0.01 of pooling the data (0.693 ±
  0.017 against 0.700 ± 0.012, pooled site-stratified C-index over five seeds) and beats one
  hospital alone (0.649 ± 0.032), with the clinical-only baseline (0.702 ± 0.004) reported even
  though it wins. The app's demo model scores a held-out C-index of 0.728 (a different
  quantity: one trained model, the mean over the three hospitals' held-out patients).
- A QA walk of 334 screens in a headless browser at two widths, with 29 findings fixed or
  listed before the freeze.
- Every claim in a case note traces to a tool call, and the app shows the chain.

## What we learned

- A fair split matters more than a clever model: whole held-out hospitals took away the omics'
  apparent edge.
- Small and large Nemotron models work well together: Super for quick structured tool calls,
  Ultra for the written synthesis; and an LLM in medicine needs a check that doesn't trust it.
- A placeholder that looks validated is worse than a missing feature, so the app colors every
  placeholder and lists them in one place.
- Depth per test beats breadth: a clinician trusts a tissue map they can zoom into and check, not
  a score.

## What's next for MuFFLe++

- A pathologist's and a radiologist's review of the scored slides and studies, and calibrated
  cutoffs in place of the placeholders.
- Stronger pathology encoders on a GPU (open-license ones in the app), and validation of
  StarDist and MedSAM on breast.
- Inferred mutation status with calibrated uncertainty, and evolutionary hypotheses from
  repeated sequencing and real serial ctDNA.
- Learning from clinicians' review marks, the Feedback page's roadmap: re-calibrating
  placeholder cutoffs against disagreed findings and retraining the slide head on tiles a
  pathologist confirms, validated on held-out patients before use.
- Real contributing institutions with consent, ethics approval and data agreements first, and
  secure aggregation or differential privacy in the federation.

## Built with

Python, PyTorch, NVIDIA FLARE, NVIDIA Nemotron 3 Super, NVIDIA Nemotron 3 Ultra, Nebius Token
Factory, Tavily, Streamlit, Altair, OpenSeadragon, OpenSlide, scikit-learn, SciPy, Playwright
(QA); models: GigaPath-Flash, StarDist, WSInfer TIL, MedSAM, mammoscreen, MONAI breast density,
OpenMed ZeroShot NER Oncology, Granite-Docling; data: TCGA-BRCA (GDC open access), BCSS,
TCGA-Reports, TCIA, CIViC, ClinicalTrials.gov, Ensembl VEP, AlphaMissense, MSK-CHORD (local
only).

## Try it out

- App: https://cancer-intelligence-platform.streamlit.app (no login)
- Code: https://github.com/ps131-cell/muffle-plus-plus (MIT)
- Video: the YouTube URL (submission checklist)

## How we used NVIDIA and Nebius

- **NVIDIA Nemotron on Nebius Token Factory:** every case note is one tool-calling conversation
  with Nemotron 3 Super and one or two Nemotron 3 Ultra calls (the note, and a rewrite if the
  grounding check finds something), following the track's advice to use Ultra for reasoning and
  Super for fast calls. The app names the models and Token Factory on every note and in the
  sidebar's **About this system**; nine notes are saved in the release, and a few live notes run
  per session on the hosted app, within a hard $25.50 cap.
- **NVIDIA FLARE:** federated training with the Recipe API (`FedAvgRecipe`, `SimEnv`) across
  three simulated hospitals; the sidebar and the Methods page show it, and the README's results
  table compares it with pooling and with one hospital alone.
- **Tavily:** literature and clinical-trial search on the genes behind a patient's risk; only
  gene names and the cancer type are sent.
- **Nebius AI Cloud:** not used (see feedback).

## Feedback on Nebius Token Factory, AI Cloud and NVIDIA tools

Each item: what happened, why it mattered, and a suggestion.

### Nebius Token Factory

1. **Out-of-credit errors are hard to read.** Before our promo credit was applied, every chat
   call returned HTTP 402 "exhausted your budget" while `models.list()` kept working, so it
   first looked like a key or model problem. *Suggestion:* say "no credit on this account"
   explicitly, link to the billing page, and show the balance (including trial credit) next to
   the API keys.
2. **No hard spending limit.** The account is billed automatically once the credit runs out,
   and there is no per-key or per-project cap. For a hackathon on free credits, and for a
   public demo that judges use for weeks, that's a real risk; we wrote our own ledger that
   reserves each call's worst-case cost. *Suggestion:* per-key hard caps, prepaid-only mode,
   and spend alerts.
3. **Prices are behind a login.** We had to take Nemotron 3 Super's and Ultra's prices from
   third-party trackers to budget. *Suggestion:* a public price page, and prices in the
   `/models` response, so code can budget itself.
4. **Inconsistent model ids.** The same family appears as
   `nvidia/NVIDIA-Nemotron-3-Nano-30B-A3B`, `nvidia/nemotron-3-super-120b-a12b`,
   `nvidia/Nemotron-3-Ultra-550b-a55b` and `nvidia/Nemotron-3_5-Lightning`. *Suggestion:* one
   lowercase scheme, or case-insensitive ids and aliases.
5. **Reasoning length is hard to bound.** Ultra's reasoning counts as output: one note was cut
   off mid-sentence at a 2,000-token limit, and with a long literature list another ran past
   3,000. `reasoning_content` and `usage.completion_tokens_details.reasoning_tokens` made this
   visible, and `chat_template_kwargs: {"enable_thinking": false}` works. *Suggestion:* a
   reasoning budget parameter (or effort levels), and a finish reason that says the reasoning
   used up the limit.
6. **What worked well:** OpenAI-compatible tool calling on Nemotron 3 Super worked on the first
   try, calls were fast (a full note took 7–10 s before we added literature search), and the
   costs were tiny (about $0.01 a note).

### Nemotron models (agent behaviour)

7. **Super calls tools one at a time unless told to batch,** and sometimes stops before the
   last useful tool; with a few turns allowed, it ran out before the literature search. Asking
   it to batch the first calls and giving it one reminder fixed it. *Suggestion:* document
   prompting patterns for parallel tool calls and "finish the plan" behaviour.
8. **Instruction sensitivity:** "clinical data is not an omic layer" made both Super and Ultra
   drop the clinical layer from the Drivers section entirely, until we wrote "every layer,
   clinical included". A note on negative instructions in the model cards would help.

### NVIDIA FLARE

9. **The Recipe API was the easy part:** `FedAvgRecipe` with `SimEnv` ran three clients on a
   Mac's CPU with little code.
10. **The initial global model isn't seeded,** so identical FedAvg runs differ by about 0.01
    C-index (0.668 vs 0.680 for the same config), which is as large as the effects we wanted to
    measure. *Suggestion:* a seed option for the initial model in the recipes.

### Nebius AI Cloud

11. **We didn't use it,** although running federated training as Serverless Jobs on GPUs was in
    our plan. With automatic billing and no hard cap, we couldn't be sure we'd stay within the
    free credits. *Suggestion:* a credits-only mode or per-project hard limit would let
    hackathon teams use Serverless Jobs and Endpoints without that risk.

### Tavily

12. **Search needed filtering for a clinical audience.** A query with several gene names
    returned generic survival-rate pages; a gene symbol that's also a word or a surname (CAMP)
    matched unrelated text; clinical-trial results were protocol PDFs rather than study pages.
    `include_domains` made the biggest difference. *Suggestion:* a scholarly / biomedical
    search mode.

## Testing instructions

- Open the demo URL; no login. A scheduled visit every four hours keeps it awake; if Streamlit
  shows its sleep page anyway, click to wake it: the container restarts, which can take a minute
  or two, then the patient list draws in a few seconds. A four-step walk-through opens on the
  first visit (**Skip the tour** closes it); the
  "?" on every screen explains it.
- **Patients** is the home page. **Start here** opens the two files that show the most. Search
  **PIK3CA**, or switch on **Open SOS alerts only**; click a row to open a file. **Search every
  file** finds findings across all files ("HER2 disagree", "stage III PIK3CA"). The address
  reopens what is on screen: `?patient=<id>&view=<view>`, plus `&test=`, `&pointer=` and
  `&version=` inside a file.
- **Case 299** (`?patient=Case%20299`): the overview cards (click **Why?**, or **Open ·** to land
  on the evidence), the attention queue (J / K to move, M to mark reviewed, O to open), the saved
  case note (**Show the saved note**), and **Similar patients** further down. In **Tests**, the
  slide tile's **Open** opens the slide map (try the view buttons, or search "lymphocytes at
  the border"; **Slide viewer** above it zooms to single cells, and its first open downloads the
  section's tiles), and the mutation panel tile's opens the genomics workbench.
- **Case 937** (`?patient=Case%20937&view=Tests`): the RNA-seq tile for PAM50, pathways and
  methylation; the breast MRI tile for the MRI viewer and the public example pair.
- **Case 563** (`?patient=Case%20563&view=Tests`): the pathology report tile for the rules'
  facts and the named-entity model beside them.
- **SYNTHETIC-001** (`?patient=SYNTHETIC-001`): synthetic. In **Tests**, the CA 15-3 tile (a pill
  per month) and the synthetic ctDNA monitor; **Evolution** for what to watch next and trials;
  **Timeline**: click any point to open the file as it was then, and compare two versions.
- **Methods and validation** (`/methods`) and **Feedback** (`/feedback`, after marking a finding)
  need no input.
- Locally: `make setup`, then `.venv/bin/streamlit run app/streamlit_app.py`; it downloads the
  release bundle. Add `NEBIUS_API_KEY` and `TAVILY_API_KEY` to `.env` for live notes.

## Data, licenses and prior work

**Prior work disclosure.** The slide workbench builds on the team's own Colon Tumor Front
Analyzer, built for the Ashby Prize Hackathon (Oct 17–18, 2026), which sets the depth we aimed
for in every workbench. Its design grammar (224 px tiles at 0.5 µm/px, a small head on frozen
embeddings, smoothing, tumor mask → front → core, front band and peritumoral zones, an "unsure
here" cutoff, quality rules, cutoffs tagged by source) was re-implemented for breast in this
repository. On Oct 27 we also ported the analyzer's slide map and app functions, copying its code
and adapting it to breast: `src/muffle/workbench/tile_map.py` (from its `app/tile_map.py`),
`src/muffle/workbench/slide_search.py` (from `app/search.py`),
`src/muffle/workbench/slide_export.py` (from `app/export.py`), and the map, Spot-panel and
class-highlight code in `app/workbenches/slides.py` (from `app/page_slide.py`, `app/report.py` and
`app/view_slide.py`); each adapted file names its source in its first line. Not used: the
analyzer's colon-trained heads, their cutoff values and its colon classes. The breast tissue head
(trained on BCSS, CC0, tiles from public TCGA-BRCA slides), the GigaPath-Flash re-score, the
invasion analysis on breast sections and every result shown were made during this hackathon;
every cutoff carried over from colon slides is marked placeholder. We checked both hackathons'
rules: the Nebius × NVIDIA rules allow pre-existing work that is significantly updated during
the submission period and disclosed; the analyzer is the team's own code, and the Ashby Prize
Hackathon's published terms set no intellectual-property or exclusivity conditions.

- TCGA-BRCA open-access data (GDC, UCSC Xena GDC hub): multi-omic data, masked somatic mutations,
  ASCAT3 copy number, diagnostic slides. The results here are in whole or part based upon data
  generated by the TCGA Research Network: https://www.cancer.gov/tcga. TCGA PanCanAtlas ABSOLUTE
  purity and ploidy (Carter et al. 2012; Taylor et al. 2018).
- BCSS (Amgad et al., *Bioinformatics* 2019; CC0): tissue labels for the slide head.
- TCGA-Reports (Kefeli and Tatonetti, *Patterns* 2024; CC BY 4.0): pathology report text.
- TCGA-BRCA radiology on The Cancer Imaging Archive (Lingle et al. 2016; CC BY 3.0).
- CIViC (CC0), ClinicalTrials.gov (U.S. National Library of Medicine), Ensembl VEP and ClinVar,
  AlphaMissense (Cheng et al., *Science* 2023; CC BY 4.0), PAM50 centroids (Parker et al. 2009, via
  genefu), MSigDB Hallmark (CC BY 4.0), RPPA pathways (Akbani et al. 2014), ESTIMATE gene lists
  (Yoshihara et al. 2013); lab intervals cited from Mayo Clinic Laboratories' catalog.
- MSK-CHORD (Jee et al., *Nature* 2024; CC BY-NC-ND 4.0): used locally for the timeline models.
  We publish code and aggregate results with attribution, and nothing else from it.
- The stroma and ECM3 content (tissue by zone on the slide workbench, the ECM3 four-gene score on
  the omics workbench, the evidence categories and the planned infrared modules on Methods and
  validation) is adapted from published work of the Chemical Imaging and Structures Laboratory
  (R. Bhargava, University of Illinois Urbana-Champaign) and of Triulzi et al. 2013, with
  citations; MuFFLe++ is independent and neither reviewed nor endorsed by the laboratory or the
  Cancer Center at Illinois.
- **What is synthetic or simulated:** SYNTHETIC-001 (written by hand; not a real person, not taken
  from any dataset), its ctDNA series, its 12-month risks (scored by the local MSK-CHORD models),
  and the three hospitals (TCGA tissue source sites grouped into NVFlare simulator clients; no
  real site took part). Each is labeled as such on screen, in the video and in this text. The 40
  TCGA files are real, public, de-identified TCGA-BRCA patients. No data from clinicians enters
  the project.
- Research and decision support for clinicians, not a diagnosis and not a treatment
  recommendation; treatment content is evidence with its source, for clinician review.

---

## Numbers (appendix, checked 2026-10-27)

Every figure quoted in this text, the README, `docs/HACKATHON.md`, the video or the Methods and
validation page, with what it was measured on and where. Two documents that quote different
quantities name each. If a source changes, change the figure everywhere it is quoted.

**Risk model and federated training (TCGA-BRCA, overall survival)**

| Figure | Value | Measured on | Source |
|---|---|---|---|
| Demo model, held-out C-index | **0.728** | the model in release `demo-bundle-v2`: the mean of the three simulated hospitals' C-indexes on their held-out patients (site-1 0.705, site-2 0.665, site-3 0.815; 213 patients, 26 deaths); the app's 40 TCGA files are drawn from these patients. A local rebuild from re-downloaded GDC and Xena files reads 0.730 | `docs/decisions.md` 2026-10-21; the bundle's stored `c_index` (read 2026-10-27); Methods and validation; sidebar › About this system |
| FedAvg, clinical-anchored residual | **0.693 ± 0.017** | a different quantity from 0.728: leave one simulated hospital out, train on two, test on every patient of the third; pooled site-stratified C-index, mean ± sd over seeds 0–4 (`make experiment-tcga`) | README results table; `app/results_tcga_brca.json` |
| Pooled data, residual · FedAvg plain fusion · pooled plain fusion | 0.700 ± 0.012 · 0.680 ± 0.008 · 0.692 ± 0.026 | as above | `app/results_tcga_brca.json` |
| One hospital alone | 0.649 ± 0.032 | as above | `app/results_tcga_brca.json` |
| Clinical data only (stage, age, T/N/M) | **0.702 ± 0.004** | as above; no fusion variant beats it, so we never claim the omics beat clinical data | `app/results_tcga_brca.json`; decisions 2026-10-18 |
| One omic layer alone | RNA 0.610 ± 0.033, methylation 0.599 ± 0.012, protein 0.574 ± 0.020, copy number **0.485 ± 0.016** (worse than chance: site and batch effects) | as above | `app/results_tcga_brca.json`; `docs/omics.md` |
| Calibration, 3-year death risk per risk quintile | mean absolute error 0.019–0.027 across the three models (FedAvg residual 0.021); integrated Brier 0.095–0.098 against 0.101 for no model | every patient scored by a model trained without their hospital, seed 0 | `docs/calibration.md`; Methods and validation |
| Cohort | 1,064 patients, 148 deaths; hospitals of 355, 355, 354 | TCGA-BRCA | `docs/calibration.md`; the bundle |
| Copy-number calls equal to the model's input | 7,993 of 7,999 genes | the bundled cases | `docs/genomics.md` |

**Patient timeline (MSK-CHORD; aggregate results only)**

| Figure | Value | Measured on | Source |
|---|---|---|---|
| Landmark AUROC, record so far vs diagnosis only | 0.880 ± 0.003 vs 0.663 ± 0.010 at sequencing; 0.931 ± 0.014 vs 0.706 ± 0.031 at 24 months | 5,368 patients, patient-level 80/20 splits, seeds 0–4 | `docs/longitudinal.md`; `app/timeline_synthetic.json` |
| SYNTHETIC-001's 12-month risk | 38% at month 0; 37% → 88% (81–93%) at month 12; 60% (54–66%) at month 24 | scored by the MSK-CHORD models; an illustration, not a validation | `app/timeline_synthetic.json` |

**Expression, methylation and protein**

| Figure | Value | Measured on | Source |
|---|---|---|---|
| PAM50 agreement with TCGA's published calls | **94.7%** (Cohen's κ 0.92); other ER-positive draws 94.1–94.7%; 72.5% (κ 0.63) with plain whole-cohort centering | 950 tumors; the ER-balanced centering was chosen after seeing the first result, on the same tumors, so not an independent test; 38 of the 39 bundled cases with a published call agree | `docs/omics.md`; `app/omics_scores.json` |
| Receptor levels against recorded status (AUC) | ER: RNA 0.958, RPPA 0.958 · PR: RNA 0.926, RPPA 0.843 · HER2: RNA 0.811 (sensitivity 0.56, specificity 0.97), RPPA 0.772, ERBB2 copy number ≥ 2× ploidy sensitivity 0.57, specificity 0.98 | 694–1,011 tumors per measure; cutoffs maximise sensitivity + specificity in-sample (calibrated here, not validated elsewhere) | `docs/omics.md`; `app/omics_scores.json` |

**Pathology slides**

| Figure | Value | Measured on | Source |
|---|---|---|---|
| Breast tissue head, held-out accuracy | **91.9%** (balanced 91.7%); lymphocyte recall 0.90 | 357 tiles on 3 patient-disjoint BCSS slides, GigaPath-Flash embeddings (QuiltNet-B-32, the encoder until 2026-10-26: 87.7%, balanced 85.4%, on the same tiles) | `docs/pathology.md` §9; `app/workbenches/slides_example/summary.json` |
| "Unlike training tissue" quality rule (slides) | cutoff **0.507**, mean cosine distance to the 5 nearest of the head's 1,052 training tiles; calibrated leave-one-slide-out (99th percentile); flags 1 of the 357 held-out tiles (0.3%) | the head's 8 training and 3 held-out BCSS slides | `docs/pathology.md` §9; decisions 2026-10-27 |
| Encoder comparison (same head, same held-out slides) | GigaPath-Flash **0.919** (balanced 0.917) against QuiltNet-B-32 **0.877** (0.854): +4.2 points, 95% interval +0.3 to +8.1; Hibou-B 0.880, Hibou-L 0.810; local only: CONCH 0.896, UNI2-h 0.838, GPFM 0.863 | 357 held-out tiles (correlated) | `docs/encoders.md`; decisions 2026-10-22 |
| WSInfer TIL second opinion, lymphocytes vs rest | **AUROC 0.955**; cutoff **0.667**, calibrated on the 8 training slides (Youden's J; training AUROC 0.971) and applied unchanged: recall 97%, specificity 79%, accuracy 83% | the head's 3 held-out BCSS slides (357 tiles); the model was trained on TCGA, so an upper bound, not an independent validation | `docs/pathology.md` §8; decisions 2026-10-21 |
| Second opinion on Case 299's section | disagrees with the head on 52 of 1,980 scored tiles (3%); 43 of 1,500 before the GigaPath-Flash re-score | front-band and peritumoral tiles of the re-scored map | `docs/pathology.md` §9; the slide workbench, Details › Cells (video shot 5, walked 2026-10-27 on 9eab7b0 and again on 1c2a7d1) |
| WSInfer screening check | tumor vs rest AUROC 0.921, lymphocytes vs rest 0.980 | 516 BCSS-labelled tiles from 11 TCGA-BRCA slides | `docs/model_access.md` |

**Clinical documents** (481 held-out TCGA-BRCA reports against TCGA's clinical fields; precision
= right / extracted, recall = right / patients with a TCGA value; `docs/documents.md`,
`app/documents/validation.json`)

| Field | Rules: precision | Rules: recall | Named-entity model: extracted | Model: precision | Model: recall |
|---|---|---|---|---|---|
| ER status | 95% | 42% | 2 | 50% | 0% |
| PR status | 93% | 41% | 0 | – | 0% |
| HER2 status | 81% | 46% | 12 | 67% | 2% |
| pT category | 96% | 53% | 54 | 96% | 11% |
| pN category | 96% | 51% | 0 | – | 0% |
| Stage group | 96% | 6% | 0 | – | 0% |
| Histologic type | 98% | 82% | 14 | 100% | 3% |
| Margins | 91% | 44% | 3 | 67% | 0% |
| Lymph nodes examined | 63% | 30% | 6 | 0% | 0% |
| Lymph nodes positive | 81% | 35% | 6 | 0% | 0% |

The model mostly marks where a field is named, not what it says: of its 12,693 spans on the
held-out reports, 12,458 name a field without a result ("ESTROGEN", "MARGINS"). So the rules are
the documented reading and the model is a second opinion of weak trust. Recall is bounded by what
a report states (receptors are often in an earlier biopsy report not in the dataset).

**Labs, genomics, evolution, radiology**

| Figure | Value | Measured on | Source |
|---|---|---|---|
| Lab reference intervals | adult reference values from the Mayo Clinic Laboratories test catalog, each with its test ID; the lab report's own interval wins when imported with the value | — (rules, not validated on a cohort) | `docs/labs.md` |
| AlphaMissense | 21 observed missense changes scored; Ensembl's own annotation agrees for 20 of 20 | the bundled cases | `docs/genomics.md` |
| Ploidy estimates 1.5-fold apart | 7 of 40 cases | median rule vs ABSOLUTE | `docs/genomics.md`; decisions 2026-10-21 |
| Evolution table | 18 rows, 37 papers, every PMID checked against PubMed | — | `docs/evolution.md` |
| Radiology, Case 937 candidate C1 | 26.2 mm, 7.43 mL (6.26–8.67), medium initial enhancement (72%), plateau (+2%) | MedSAM contour; placeholder kinetic cutoffs; not validated on breast MRI | `docs/radiology.md` §2 |
| Rigid alignment (change over time) | a known 3° rotation and 4, −3, 5 mm shift recovered within 1.5 mm (synthetic test); on the public pair NMI 1.124 → 1.156, six starts converged within 0.7° and 1 mm, tissue masks' Dice 0.69 → 0.76; 99 of 112 blocks "unreliable here" (the breasts deform) | TCGA-AR-A1AQ, 2001 and 2003 (not in the bundle) | `docs/radiology.md` §3 |
| mammoscreen card AUROC | 0.945 (the authors', on RSNA 2023 held-out splits; not measured here) | — | `docs/registry.md` |
| MONAI breast density | accuracy 0.96 as the bundle's metadata states, test set not described; not measured here | — | `docs/radiology.md`; Methods and validation |

**Case agent and quality**

| Figure | Value | Measured on | Source |
|---|---|---|---|
| Saved notes | 9, all written by Nemotron 3 Ultra after Super's tool calls, 0 grounding issues; 9,401–23,474 tokens each | release `demo-bundle-v2` | `app/saved_notes.json`; decisions 2026-10-18 |
| Spend | about $0.01 a note at 8k–16k tokens (decisions 2026-10-18); the local ledger reads $0.82 of the $25.50 cap (125 calls, its last entry 2026-10-19; $0.48 of it recorded by hand for calls made outside this code). The hosted app's live notes count on its own ledger | Token Factory | the local ledger `~/.muffle/token_factory_spend.json`; the cap in `src/muffle/report/budget.py` |
| QA round 2 | 334 screens (330 before the fixes) of seven files at 1280 and 800 px, light and dark, in headless Chromium; 29 findings; R2-15, R2-16, R2-18 and the MRI's overflow at 800 px fixed on 2026-10-27 (#136) | 2026-10-22 | `docs/qa.md` |
| Performance pass | a report shown again: 0.27–0.56 ms instead of 45–267 ms (SYNTHETIC-001, Cases 299 and 926); the 114-screen AppTest walk 81.3 s → 76.9 s (5% faster, median screen 0.47 → 0.43 s); memory after all 41 files 720 → 699–710 MB | AppTest walks in WSL at load average 11–15, medians over four alternating pairs; every element of all 114 screens identical before and after | `docs/qa.md` (Performance pass, 2026-10-27) |

**Across the files** (lookups, not models; `docs/cohort.md`)

| Figure | Value | Measured on | Source |
|---|---|---|---|
| Similar patients | the 5 nearest TCGA files on 8 fields (PAM50 subtype, stage, receptor status, mutated drivers, copy-number calls, risk group, RNA immune band, tests on file), equal weights marked placeholder | the 40 TCGA files; the synthetic patient is never a candidate and its MSK-CHORD risk never compared | `docs/cohort.md`; decisions 2026-10-27 |
| Where this patient sits | percentiles among the 40 TCGA files for risk, mutation burden and five expression and protein scores | as above | `docs/cohort.md` |
| Search every file, "HER2 disagree" | 5 files whose HER2 IHC and ERBB2 RNA or copy number disagree | the release bundle's 41 files | `docs/cohort.md`; video shot 2 (walked 2026-10-27) |

## Submission checklist (fill on Oct 29)

**Your clicks on Oct 29, in this order** (after the 10:00 CDT freeze and the last walk of
`docs/video.md`):

1. **Reboot the hosted app:** share.streamlit.io → the app's ⋮ menu → **Reboot app**; wait until
   https://cancer-intelligence-platform.streamlit.app draws the patient list.
2. **Check About this system** (open in the sidebar): the **Code** row shows `main`'s short hash
   (the first seven characters of the latest commit on GitHub's `main`), **Held-out C-index
   0.728**, and **Case agent: saved notes only**. If the hash is older, reboot again. The hosted
   app keeps no Token Factory key: the spend ledger on the Streamlit container resets on every
   reboot, so a key there would not be held to the $25.50 cap. The live case agent needs a key
   and a persistent ledger (a local run, Testing instructions); the hosted app shows the nine
   saved notes.
3. **Record** the take from `docs/video.md` on the hosted app, then **upload it to YouTube as
   public**, with the title, description, tags and thumbnail in `docs/youtube.md`.
4. **Paste the video link into README.md**: one line under **Live app**
   (`**Video:** https://youtu.be/…`), as a one-line PR, merged on your word; also into the
   checklist below.
5. **Fill the Devpost form** from this file (the list below), save it as a draft, re-read it on
   the page; then put the Devpost link into the YouTube description's placeholder.
6. **Protect `main`:** GitHub → Settings → Branches → a rule for `main`: require a pull request,
   require the `tests` check, no force pushes.
7. **Submit** on Devpost before **Oct 30, 10:00 am PT** (12:00 pm Central); then open the public
   project page and check its links.

- [ ] **Video URL** (YouTube, public, ≤ 3:00): `______________________`; also in README.md
- [ ] **Repository URL:** https://github.com/ps131-cell/muffle-plus-plus (public, MIT in About)
- [ ] **Hosted app URL:** https://cancer-intelligence-platform.streamlit.app (rebooted after the
      freeze; About this system: Held-out C-index 0.728, Case agent: saved notes only)
- [ ] **Team members** (Devpost accounts, each invited and accepted): `______________________`
- [ ] **Track:** Best Apps and Agents; tick the Best Use of Tavily bonus if the form asks
- [ ] **Tags / Built with:** Python, PyTorch, NVIDIA FLARE, NVIDIA Nemotron, Nebius Token Factory,
      Tavily, Streamlit, Altair, OpenSeadragon, scikit-learn, SciPy
- [ ] **Story fields** pasted from this file (Inspiration … What's next), then How we used NVIDIA
      and Nebius, Feedback, Testing instructions, and Data, licenses and prior work
- [ ] **Prior-work disclosure** kept word for word
- [ ] **Images:** two or three screenshots (Patients, a patient overview, the slide map) from
      the hosted app; no MSK-CHORD patient; the synthetic and simulated labels visible
- [ ] Re-read the Devpost rules page; submit before **Oct 30, 10:00 am PT** (12:00 pm Central)

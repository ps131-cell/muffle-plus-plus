# Registry: datasets, models and services

Part five of `docs/VISION.md`: every resource MuFFLe++ uses, with its license, access tier, where
it is used and what leaves this machine. Rule (CLAUDE.md): check a new source's license and access
tier and add it here **before** using it.

## Datasets

| Dataset | Used for | Access tier | License / terms | Code | What is published |
|---|---|---|---|---|---|
| **TCGA-BRCA** multi-omic data (copy number ASCAT3, STAR TPM RNA, 450K methylation, RPPA protein, clinical, overall survival) via the UCSC Xena GDC hub | survival model, federated training across simulated hospitals (tissue source sites), case review | open (no dbGaP authorization) | NIH GDC open-access data; cite the TCGA Research Network | `scripts/prepare_tcga.py`, `muffle.data.tcga` | trained model weights and 40 held-out patients' processed features in the release `demo-bundle-v1`; aggregate results; saved case notes (derived numbers, gene names) |
| **GDC masked somatic mutations** for TCGA-BRCA (`TCGA-BRCA.somaticmutation_wxs.tsv.gz`, Xena GDC hub) | observed driver mutations (ESR1, PIK3CA, TP53, ...) in the case note; not a model input | open (masked calls, germline filtered) | as TCGA above | `muffle.data.tcga.driver_mutations` | gene and protein-change names per demo case |
| **CIViC** nightly clinical evidence summaries | treatment evidence for observed variants, "for clinician review" | open download | **CC0**; each item keeps its citation and CIViC link | `muffle.report.civic` | evidence items (therapy, level, citation, link) in notes and `app/timeline_synthetic.json` |
| **MSK-CHORD** (`msk_chord_2024`, Jee et al., *Nature* 2024; cBioPortal datahub) breast cancer timelines | risk of progression or death in the next 12 months, re-predicted as the record grows; scores the demo's synthetic patient | open download | **CC BY-NC-ND 4.0**: non-commercial, no derivatives shared; attribution | `scripts/prepare_msk_chord.py`, `muffle.longitudinal`, `muffle.timeline` | **local only.** Aggregate metrics (`docs/longitudinal.md`) and the synthetic patient's scores. Never an individual patient, never the trained models, and nothing from it (data or model outputs) to Token Factory or Tavily |
| **Synthetic cohort** (`scripts/make_synthetic.py`) | development and tests | generated | MIT (this repo) | `muffle.data.synthetic` | code only |
| **Synthetic timeline patient** SYNTHETIC-001 (hand-written) | the demo's patient timeline | generated | MIT (this repo) | `muffle.timeline` | its record and scores, labeled synthetic |

## Models

| Model | Role | Access | License / terms | Inputs it receives |
|---|---|---|---|---|
| **MuFFLe++ fusion survival model** (trained here) | multi-omic risk with missing-layer masks; clinical anchor + omic residual, FedAvg with NVIDIA FLARE | weights in the release `demo-bundle-v1` | MIT (code); trained on TCGA open data | one patient's processed omics and clinical features |
| **MSK-CHORD landmark models** (gradient boosting, trained here, 5 seeds × 4 landmarks) | 12-month progression-or-death risk; baseline (diagnosis only) vs record so far | **local only, not published** | trained on CC BY-NC-ND data, so not shared | a record's timeline features |
| **NVIDIA Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b`) | case agent planner: calls the tools | Nebius Token Factory API | NVIDIA open model license (see the model card); Token Factory terms | derived numbers (risk, percentile, contributions), gene and mutation names, CIViC items, Tavily results |
| **NVIDIA Nemotron 3 Ultra** (`nvidia/Nemotron-3-Ultra-550b-a55b`) | case agent writer | Nebius Token Factory API | as above | the planner's tool outputs |

Every Token Factory call goes through `muffle.report.budget` (hard spending cap).

## Services

| Service | Role | Terms | What is sent |
|---|---|---|---|
| Nebius Token Factory | hosts the Nemotron models (OpenAI-compatible API) | Nebius terms; hackathon credits | see Models above; never raw omics, nothing from MSK-CHORD |
| Tavily | literature and clinical-trial search for the case note | Tavily API terms | one query per gene with the cancer type |
| Streamlit Community Cloud | hosts the demo | Streamlit terms | the public repo and the demo bundle |

## Software

NVIDIA FLARE ≥ 2.8 (Apache-2.0) · PyTorch (BSD-3-Clause) · scikit-learn (BSD-3-Clause) ·
scikit-survival (GPL-3.0; metrics only, not redistributed) · pandas, NumPy (BSD-3-Clause) ·
Streamlit (Apache-2.0) · Altair (BSD-3-Clause) · openai-python (Apache-2.0) · tavily-python (MIT).

## Candidates, not used

Not checked yet; check license, access tier, compute and validation before adding any of them
(VISION part five):
- TCGA diagnostic slides (GDC) with a pathology foundation model as an image encoder.
- CPTAC breast proteomics (only ~100 TCGA-BRCA tumors overlap; RPPA is used instead).
- Other longitudinal breast cohorts with repeated sequencing, for evolutionary hypotheses.

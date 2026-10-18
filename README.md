# MuFFLe++ — toward a cancer intelligence platform (breast cancer)

Cancer changes over time, and the evidence about one patient is scattered across tests, visits
and hospitals that can't pool their data. Our long-term goal ([`docs/VISION.md`](docs/VISION.md))
is a **multimodal, longitudinal cancer intelligence platform**: it connects specialized models,
public datasets and each patient's record over time into one evidence-linked picture of the
disease, keeps what was **observed** apart from what a model **inferred** and what is only a
**hypothesis**, and learns across institutions without centralizing patient data. It is research
support for clinicians, not a diagnosis or a prescription.

**MuFFLe++ is milestone 1** of that platform, for breast cancer:
- **Evidence-linked patient profile.** A multi-omic survival model (copy number, RNA,
  methylation, protein, clinical) gives a risk estimate that copes with missing tests; an
  **NVIDIA Nemotron** case agent on **Nebius Token Factory** calls our models as tools and writes
  a tumor-board note with literature from **Tavily**. *In progress:* every statement labeled
  observed / inferred / hypothesis; observed driver mutations with **CIViC** treatment evidence
  for clinician review.
- **Patient timeline** *(in progress)*. Risk is re-estimated as new results arrive (treatments,
  tumor markers, sequencing), measured on real MSK-CHORD timelines (aggregate results only) and
  shown in the demo on a clearly labeled synthetic patient.
- **Learning across hospitals.** One survival model is trained **across simulated hospitals
  without moving any patient data**: each site trains locally and only model weights are
  aggregated with **NVIDIA FLARE** (FedAvg).

```
 Hospital A ─┐  encoders: genomic · RNA · methylation · protein · clinical
 Hospital B ─┼▶ masked late fusion ─▶ DeepSurv (Cox) head ─▶ risk
 Hospital C ─┘  weights only ─▶ NVFlare server (FedAvg) ─▶ global model
                                              │
                    patient risk + drivers ───┴─▶ Nemotron (Token Factory) ─▶ report
```

Sites missing a data type still participate: that encoder is masked out (MuFFLe-style), and the
model is trained with modality dropout so it stays calibrated when layers are missing.

## Quick start (macOS or Linux, Python 3.10–3.13)

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
```

## Hackathon: how NVIDIA and Nebius are used
- **NVIDIA FLARE** — federated training (`jobs/fedavg_job.py`, `src/muffle/fl/client.py`).
- **NVIDIA Nemotron via Nebius Token Factory** — a tool-calling **case agent**
  (`src/muffle/report/nemotron.py`). For the selected patient, Nemotron decides which of our
  tools to call (OpenAI-compatible tool calling), then writes the tumor-board note (Summary,
  Drivers, Caveats, Literature) citing only tool outputs. The tools run locally
  (`src/muffle/report/case_tools.py`):
  - `predict_risk`: log-risk, cohort percentile and risk group from the federated model
  - `modality_contributions`: how much each data layer moves the risk (`muffle.explain`)
  - `top_features`: top genes/features of a layer by gradient × input
  - `search_literature`: Tavily search for papers or clinical trials on those genes (only
    offered when real gene names and `TAVILY_API_KEY` are available)

  The demo shows the tool-call trace next to the report. Each report is capped at 4 tool
  rounds and 900 tokens per completion (free hackathon credits). Only derived numbers and
  gene names are sent, never raw omics. Without `NEBIUS_API_KEY` the same tools run in a
  fixed order and an offline template writes the report. Try one case from the terminal:
  `.venv/bin/python -m muffle.report.nemotron --agent --patient 0`.
- **Nebius AI Cloud** — not used in the submission: Nebius usage is Token Factory only, and FL
  runs in the NVFlare simulator. `docs/NEBIUS.md` keeps untested notes for a Serverless Job.
- **Tavily** — the agent's literature and clinical-trial search on the top prognostic genes.

Requirements checklist and day-by-day plan: [`docs/HACKATHON.md`](docs/HACKATHON.md).

## Results so far (TCGA-BRCA, overall survival)
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
hospitals it wasn't trained at; it matches clinical stage and age alone, while plain fusion
fell short. On this endpoint the omics don't (yet) add signal beyond clinical data.

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
| `jobs/fedavg_job.py` | FedAvgRecipe job, run in the NVFlare simulator |
| `app/streamlit_app.py` | demo UI |
| `scripts/` | data prep: synthetic cohort, open-tier TCGA-BRCA (`prepare_tcga.py`) |
| `docs/` | plan PDFs, hackathon checklist, decisions log, Nebius notes |
| `data/`, `outputs/`, `workspaces/` | **git-ignored** — never commit patient data or checkpoints |

## Data and licenses
| Source | Used for | Terms |
|---|---|---|
| TCGA-BRCA via the GDC / UCSC Xena GDC hub | multi-omic cohort, overall survival | open tier |
| GDC masked somatic mutation files | observed driver mutations *(in progress)* | open access |
| [CIViC](https://civicdb.org) | treatment evidence for observed variants *(in progress)* | CC0 |
| [MSK-CHORD](https://www.cbioportal.org/study/summary?id=msk_chord_2024) (Jee et al., Nature 2024) | real patient timelines for the risk-update evaluation *(in progress)* | CC BY-NC-ND 4.0: used locally; only code and aggregate results are published |

No patient-level data is stored in this repository. Simulated hospitals and the demo's synthetic
timeline patient are labeled as simulated. Full list with access tiers: `docs/registry.md`.

## Roadmap
Milestone 1 (hackathon, Oct 30 2026):
- [x] Repo, CI, TCGA-BRCA multi-omic cohort, survival model with missing-layer masking
- [x] Federated training across simulated hospitals, baselines, leave-one-site-out, calibration
- [x] Nemotron case agent with tools, Tavily literature, spending cap
- [ ] Observed / inferred / hypothesis labels in the case note
- [ ] Observed driver mutations + CIViC evidence
- [ ] Patient timeline: risk re-estimated as results arrive (MSK-CHORD, aggregate results)
- [ ] Synthetic timeline patient in the demo; hosted demo; video; submit by Oct 30, 10 am PT

Beyond the hackathon (see [`docs/VISION.md`](docs/VISION.md)): pathology and radiology
encoders, inferred mutation status with calibrated uncertainty, evolutionary hypotheses from
repeated sequencing, resistance and treatment-strategy research, real contributing institutions
with privacy techniques.

## License
MIT — see [LICENSE](LICENSE).

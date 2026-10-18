# MuFFLe++ — Federated Multi-Omic Cancer Prognosis

Hospitals can't pool patients' genomic data, so prognosis models stay small and site-specific.
MuFFLe++ trains one survival model **across hospitals without moving any patient data**: each
site trains locally on its own omics + clinical records and only model weights are aggregated
with **NVIDIA FLARE** (FedAvg). An **NVIDIA Nemotron** model on **Nebius Token
Factory** then turns each prediction into a clinician-readable report, with literature found
via **Tavily**.

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

## Roadmap
- [x] Repo, CI, synthetic data, model, FedAvg simulation, Nemotron report, demo app
- [x] TCGA-BRCA download + harmonization (`scripts/prepare_tcga.py`)
- [x] Baselines vs FL on real data; leave-one-site-out validation (`make experiment-tcga`)
- [ ] ~~FL training as a Nebius Serverless Job~~ (cut: Token Factory only, on free credits)
- [ ] Host the demo; record the video; submit by Oct 30, 10 am PT
- [ ] Stretch: evaluate FedProx (`--prox-mu` is implemented, not yet evaluated), BLCA,
  DP / secure aggregation

## License
MIT — see [LICENSE](LICENSE).

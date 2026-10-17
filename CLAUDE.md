# Notes for Claude sessions working in this repo

Project: MuFFLe++, federated multi-omic cancer survival prediction (NVIDIA FLARE + PyTorch) with
a Nemotron-written report (Nebius Token Factory). Entry for the Nebius × NVIDIA Global AI
Hackathon — **deadline Fri Oct 30 2026, 10:00 am PT**. Requirements + plan: `docs/HACKATHON.md`.
Original research plan: `docs/plan/`. Decisions: `docs/decisions.md`.

Team: two people sharing one Mac and one GitHub account. Repo: `~/PycharmProjects/muffle-plus-plus`.

## Commands
`make setup` · `make test` · `make local` · `make fl` · `make demo` (all use `.venv`).

## Rules
- Work on a branch `<area>/<topic>`, open a PR with `gh pr create`; never commit to `main`.
- Run `make test` (and `make lint`) before committing; CI must pass.
- Commit style: `<area>: <change>`; areas data/model/fl/eval/app/infra/docs.
- Never commit `data/`, `outputs/`, `workspaces/`, any `.csv/.npz/.pt`, or `.env`. The repo will
  be public.
- Never print or log API keys; read them from `.env` via environment variables.
- NVFlare ≥ 2.8 Recipe API (`FedAvgRecipe` + `SimEnv`) — check the installed version's docs
  before changing `jobs/fedavg_job.py`; don't reintroduce the old `FedAvgJob` API.
- Data format every loader must produce: docstring of `scripts/prepare_tcga.py`.
- The model must accept missing modalities via the mask; keep `tests/test_model.py` passing.
- Cox loss is computed over a whole batch — don't use tiny batches or per-sample losses.
- Only derived numbers (risk, contributions, gene names) may go to Token Factory — never raw
  patient-level omics.
- Prefer finishing hackathon requirements over stretch goals; record scope changes in
  `docs/decisions.md`.

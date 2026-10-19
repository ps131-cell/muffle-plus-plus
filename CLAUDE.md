# Notes for Claude sessions working in this repo

Project: MuFFLe++, **milestone 1 of a multimodal, longitudinal cancer intelligence platform**
for breast cancer (vision and milestone map: `docs/VISION.md`). Milestone 1 = an evidence-linked
patient profile (multi-omic risk model, observed driver mutations, CIViC evidence, literature)
that updates along a patient timeline, written up by a Nemotron case agent on Nebius Token
Factory, plus federated training across simulated hospitals with NVIDIA FLARE. Entry for the
Nebius × NVIDIA Global AI Hackathon — **deadline Fri Oct 30 2026, 10:00 am PT; freeze Oct 28**.
Requirements + plan: `docs/HACKATHON.md`. Decisions: `docs/decisions.md`. Datasets and models:
`docs/registry.md`. Original research plan: `docs/plan/`.

Team: two people sharing one Mac and one GitHub account. Repo: `~/PycharmProjects/muffle-plus-plus`.
Several Claude sessions may work here at once: use your own branch (and a git worktree if the
main folder is on someone else's branch); never switch the main folder's branch from under
another session.

## Commands
`make setup` · `make test` · `make lint` · `make tcga` · `make experiment-tcga` ·
`make calibration-tcga` · `make msk-chord` · `make experiment-msk` ·
`make demo-timeline` · `make fl-tcga` · `make agent-tcga` · `make demo-tcga` (all use `.venv`).

## Rules
- Work on a branch `<area>/<topic>`, open a PR with `gh pr create`; never commit to `main`.
- Run `make test` (and `make lint`) before committing; CI must pass.
- Commit style: `<area>: <change>`; areas data/model/fl/eval/app/infra/docs.
- Merging: squash-merge your own PR once CI is green if it stays within the agreed plan. Ask
  first for PRs that change reported numbers or the pitch, touch submission material (README,
  Devpost text, video), make the repo public, or land after the Oct 28 freeze.
- Never commit `data/`, `outputs/`, `workspaces/`, any `.csv/.npz/.pt`, or `.env`. The repo will
  be public.
- Never print or log API keys; read them from `.env` via environment variables.
- Every Token Factory call goes through `src/muffle/report/budget.py` (hard $25.50 cap). Never
  raise the cap or route around it; ask the user.
- Only derived numbers (risk, contributions, gene and mutation names) may go to Token Factory or
  Tavily — never raw patient-level omics, and nothing at all from MSK-CHORD.

## Science rules (from the vision)
- Label every finding the system shows as **observed** (measured: recorded stage, a sequenced
  mutation), **model inference** (a prediction, with its uncertainty) or **hypothesis**
  (literature leads, evolutionary pathways). Never present an inference as an observation.
- Simulated hospitals, synthetic patients and simulated arrival orders are always labeled as
  such in code output, the demo and docs.
- Treatment content is evidence with a source, "for clinician review" — never a recommendation.
- Records are incomplete by design: every component must work when a data layer or test is
  missing (the model takes a mask; keep `tests/test_model.py` passing).
- Report against clear baselines (clinical-only, one hospital alone, pooled training). Tune on
  seeds 95–99 only; report seeds 0–4.

## Data rules
- TCGA-BRCA (open tier, GDC / UCSC Xena) is the multi-omic cohort; format in the docstring of
  `scripts/prepare_tcga.py`. Mutations only from GDC's open-access masked somatic files.
- **MSK-CHORD (CC BY-NC-ND 4.0) is local-only:** download it, train and evaluate on it, publish
  code and aggregate results with attribution. Never commit, upload, host or show individual
  MSK-CHORD patients (not in the demo, the video, issues or LLM calls). The demo's timeline
  patient is synthetic and labeled.
- CIViC content is CC0; cite the evidence item. Check every new source's license and access tier
  and add it to `docs/registry.md` before using it.

## Technical notes
- NVFlare ≥ 2.8 Recipe API (`FedAvgRecipe` + `SimEnv`) — check the installed version's docs
  before changing `jobs/fedavg_job.py`; don't reintroduce the old `FedAvgJob` API.
- Cox loss is computed over a whole batch — don't use tiny batches or per-sample losses.
- Prefer finishing hackathon requirements over stretch goals; record scope changes in
  `docs/decisions.md`.

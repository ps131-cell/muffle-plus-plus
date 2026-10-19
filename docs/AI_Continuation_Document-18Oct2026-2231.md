# PROJECT CONTINUATION DOCUMENT
## Sunday 18 October 2026, 22:31 CDT (Monday 19 October 2026, 03:31 UTC)

Handoff for a fresh AI session on **MuFFLe++**. It records the state of the project at the
time above, what was checked in this session, and the reasoning behind earlier decisions.
It does not repeat the rules in `CLAUDE.md`; read that file too.

Confidence markers used throughout: ✅ **HIGH** (checked in this session) · ⚠️ **MEDIUM**
(from repo docs, git history or earlier sessions' notes, not re-checked) · ❓ **LOW**
(inferred or uncertain; verify before relying on it).

---

### 1. PROJECT IDENTITY

- **Project name:** MuFFLe++ (repo `ps131-cell/muffle-plus-plus`, public). Hosted demo is at
  `cancer-intelligence-platform.streamlit.app`. Streamlit's profanity filter rejects any
  subdomain containing "muff", so the demo can't use the project name.
- **What this project is:** Milestone 1 of a planned **multimodal, longitudinal cancer
  intelligence platform** for **breast cancer**. It is research and clinical decision support
  for qualified clinicians and researchers, never a diagnosis or a prescription. For one patient
  it builds an evidence-linked profile with four parts:
  - a multi-omic survival risk model that copes with missing data layers;
  - observed driver mutations;
  - CIViC treatment evidence "for clinician review";
  - literature leads.

  A tool-calling NVIDIA Nemotron case agent on Nebius Token Factory writes this profile up as a
  tumor-board note. The model is trained with NVIDIA FLARE federated learning across simulated
  hospitals. Risk updates along a patient timeline are evaluated on MSK-CHORD (local only) and
  demoed on a synthetic, labeled patient.
- **Primary objective (established):** submit a working entry to the **Nebius × NVIDIA Global
  AI Hackathon (Devpost)** in the **Best Apps and Agents** track (plus the Best Use of Tavily
  bonus).
  - **Deadline:** Fri **Oct 30 2026, 10:00 am PT**. **Freeze:** Oct 28.
  - **Hard requirements:** the table in `docs/HACKATHON.md`. Stage one of judging is pass/fail
    on real use of Token Factory and Nemotron.
  - **Judging criteria:** four, equally weighted: technological implementation, design, impact,
    and quality of the idea.
- **Strategic intent:** `docs/VISION.md` describes the long-term platform. It connects
  specialized models, public datasets and each patient's record over time into one
  evidence-linked picture. It keeps **observed** findings apart from **model inferences** and
  **hypotheses**, and learns across institutions without centralizing data. The hackathon
  build is the first, rigorously evaluated slice. The VISION table "Milestone 1 delivers vs
  Roadmap" defines the scope boundary.
- **Current product direction:**
  - **Milestone-1 parts** (decision 2026-10-18 in `docs/decisions.md`):
    1. evidence labels in the note (done, #43);
    2. observed driver mutations and CIViC evidence (done, #46);
    3. MSK-CHORD 12-month risk updates (done, #48);
    4. a synthetic timeline patient in the demo (PR #49, open, merge conflict);
    5. `docs/registry.md` (not started).
  - **Roadmap, not in scope for the hackathon:** pathology and radiology encoders, inferred
    mutation status, evolutionary hypotheses, real institutions, differential privacy and
    secure aggregation.
  - **Requested, not started, not scheduled:** a large "pathologist workspace". It was requested
    by the user in an earlier session and recorded only in Claude's auto-memory. See §4.
- **Hard constraints:** all are in `CLAUDE.md` (Rules, Science rules, Data rules, Technical
  notes). The most consequential:
  - **Spending cap:** every Token Factory call goes through `src/muffle/report/budget.py`, with
    a hard **$25.50** cap. Never raise it or route around it.
  - **What may leave the machine:** only derived numbers and gene names go to Token Factory or
    Tavily.
  - **MSK-CHORD:** CC BY-NC-ND 4.0. Local only and aggregates only. No MSK-CHORD patient may
    reach git, the demo, the video, issues or an LLM.
  - **Evidence labels:** every finding is labeled observed / model inference / hypothesis.
  - **Simulation labels:** anything simulated is labeled as simulated.
  - **Never commit** `data/`, `outputs/`, `workspaces/`, `.csv/.tsv/.npz/.pt` files or `.env`.
  - **Workflow:** branch, then PR, then green CI. Seeds 95–99 are for tuning; report seeds 0–4.
- **Project memory files:**
  - `/Users/prakharsuryansh/PycharmProjects/muffle-plus-plus/CLAUDE.md` is checked in and is the
    authoritative project instruction file. It is identical on local `main` and `origin/main`.
  - `AGENTS.md`, `.cursor/rules`, `.github/copilot-instructions.md`: **none found** (✅
    checked).
  - Claude Code auto-memory, outside the repo:
    `/Users/prakharsuryansh/.claude/projects/-Users-prakharsuryansh-PycharmProjects-muffle-plus-plus/memory/`
    (`MEMORY.md` plus 12 notes). These hold history and resume points not recorded in the repo.
    The newest resume notes are `resume-point-hosting.md` and `resume-point-milestone1.md`.
- **Other authoritative documentation** (read as needed):
  - `docs/VISION.md`: the vision and the milestone map.
  - `docs/HACKATHON.md`: requirements, day plan, scope cuts, and the video outline.
  - `docs/decisions.md`: the decision log, newest first, with numbers and reasons. This is the
    main record of *why*.
  - `docs/longitudinal.md`: MSK-CHORD aggregate results. `docs/calibration.md`: calibration and
    fairness.
  - `docs/NEBIUS.md`: untested notes on a Serverless Job, which is not used.
    `docs/CLAUDE_CODE_KICKOFF.md`: the original kickoff.
  - `docs/plan/*.pdf`: the original research plan.
  - `SETUP.md`, `CONTRIBUTING.md`, `.github/pull_request_template.md`, `README.md`.
  - GitHub issues #4–#16 are the hackathon requirements and plan, all still open (✅ listed).

---

### 2. WHAT EXISTS RIGHT NOW

**Repo state** (✅ all checked with git and `gh` in this session):
- **Main checkout:** `/Users/prakharsuryansh/PycharmProjects/muffle-plus-plus`, branch `main`
  at `1a65189` ("data: observed driver mutations (GDC open access) and CIViC treatment evidence
  for the agent (#46)").
  - It is **behind `origin/main` by 2 commits**: `c389248` (#48, MSK-CHORD timelines) and
    `619058e` (#50, Streamlit secrets → env).
  - Only untracked item: `.claude/` (`launch.json` with preview configs, and `worktrees/`).
    **Never commit `.claude/`.**
- **`origin/main`:** `619058e`, "app: read Streamlit Cloud secrets into the environment at
  startup (#50)".
  - The single remote is `origin` → `https://github.com/ps131-cell/muffle-plus-plus.git`.
  - The repo is public. Its homepage is the hosted demo URL.
  - `main` is protected: the `tests` check is required, admins included, with no force pushes
    (⚠️ from memory notes). A local `.git/hooks/pre-push` also refuses pushes to `main`.
- **Git worktrees** (all clean, ✅):
  | Path | Branch | State |
  |---|---|---|
  | `.claude/worktrees/vision` | `app/synthetic-timeline` | PR #49, open, **conflicts with main** |
  | `.claude/worktrees/submission` | `docs/submission` | PR #42, open, CI green, waiting for the user's review |
  | `.claude/worktrees/video` | `docs/video-script` | PR #47, open, CI green, waiting for the user's review |
  | `.claude/worktrees/secrets` | `docs/continuation-handoff` | **this handoff**. The worktree was reused after #50 merged. |
  | `.claude/worktrees/eager-ardinghelli-4c9eb3` | `docs/review-decisions` | Leftover; the remote branch is gone. |
- **Stale local branches:** these were squash-merged and their remotes are deleted:
  `app/evidence-labels`, `docs/vision-milestone-1`, `data/driver-mutations-civic`,
  `data/msk-chord-risk-updates`, `app/streamlit-secrets`, `claude/eager-ardinghelli-4c9eb3`.
  They are safe to prune, but ask first.
- **Open PRs** (✅): #49 (merge state DIRTY, CI green on its head), #47 (CLEAN, green), #42
  (CLEAN, green). No others.
- **Release:** `demo-bundle-v1` (`demo_bundle.pt`, ~850 KB, 40 held-out cases). The hosted app
  downloads it.

**Does it run right now?**
- ✅ **Tests on `origin/main` (619058e):** **81 passed** in 10.2 s. They ran in the worktree
  with `PYTHONPATH=src ../../../.venv/bin/python -m pytest -q`, using the main `.venv`
  (Python 3.12; torch 2.14.1, nvflare 2.9.0, streamlit 1.66.0).
- ✅ **Lint:** `ruff check src tests scripts app jobs`: all checks passed. Note that
  `ruff format --check` would reformat 37 files. Formatting is **not** a CI gate, so don't run
  `ruff format` repo-wide (see §5).
- ✅ **Local demo:** the `demo-tcga` preview (port 8501) **was failing** with "Port 8501 is not
  available".
  - Cause: a stale Streamlit process from about 41 minutes earlier, started through the Claude
    app's helper with the same command. No running session owned it.
  - Fix: stopped it with SIGTERM, restarted with `preview_start demo-tcga`, and confirmed the
    Case review tab renders with no console errors.
  - It serves the **main folder's code at `1a65189`**, so it lacks #48 and #50.
- ✅ **Hosted demo** (`https://cancer-intelligence-platform.streamlit.app/~/+/`) loads.
  - It shows "Held-out patient (40 of the 213 …)" (bundle v1).
  - It shows **"Live notes are off here"**, so `NEBIUS_API_KEY` and `TAVILY_API_KEY` are not
    set (or not seen) in the Streamlit secrets. Only saved notes are shown.
- Not run this session: `make tcga`, `make fl-tcga`, experiments, live agent calls, and the CI
  workflow on a new commit (pending the push below).
- ✅ **Token Factory ledger** (`python -m muffle.report.budget`): **$0.4632 of $25.50** spent,
  286 calls (Super $0.1287, Ultra $0.3245, recorded outside this code $0.01).

**What is built and working** (merged to `origin/main`). The files are present ✅; behavior is
⚠️ unless noted:
- **TCGA-BRCA multi-omic cohort** (#24, `scripts/prepare_tcga.py`, `muffle.data.tcga`):
  1,064 patients and 5 layers (copy number as "genomic", RNA, methylation, RPPA protein,
  clinical) with masks. The endpoint is overall survival. It also holds per-patient tissue
  source site and driver mutations (#46: 943/1,064 sequenced; "not sequenced" ≠ wild type).
- **Model** `muffle.models.fusion.MuffleNet`: per-layer MLP encoders, masked additive late
  fusion, and a DeepSurv (Cox) head. Modality dropout of 0.8 never drops clinical. Optional
  clinical-anchored residual (`muffle.residual`, λ ∈ {0, ¼, ½, ¾, 1}). The TCGA config is
  `configs/tcga_brca.yaml`.
- **Federated learning:**
  - `jobs/fedavg_job.py` uses the NVFlare ≥ 2.8 Recipe API (`FedAvgRecipe` + `SimEnv`);
    clients are in `src/muffle/fl/client.py`.
  - There are 3 simulated hospitals made of whole tissue source sites.
  - `make fl-tcga` builds FedAvg-residual (λ = 0.25) → `outputs/tcga_fedavg.pt`.
  - CI runs a 2-client, 2-round FL smoke test.
- **Experiments** (`python -m muffle.experiment`):
  - Per-site validation splits and leave-one-site-out (LOSO).
  - Methods: centralized, local-only, FedAvg, residual, FedAvg-residual, clinical-only.
  - Reported results (LOSO, seeds 0–4): FedAvg-residual 0.693 ± 0.017; centralized residual
    0.700 ± 0.012; centralized fusion 0.692 ± 0.026; FedAvg fusion 0.680 ± 0.008; local-only
    0.649 ± 0.032; **clinical-only 0.702 ± 0.004**. These are in the README and
    `docs/decisions.md`.
- **Calibration and fairness** (#31, `muffle.calibration`, `docs/calibration.md`).
- **Case agent** (`src/muffle/report/nemotron.py`, `case_tools.py`, `grounding.py`,
  `civic.py`, `budget.py`):
  - **Planning:** Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`) plans tool calls, with
    up to 6 turns plus one search-only turn.
  - **Writing:** Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`, 4,096 max tokens)
    writes the note.
  - **Checking:** `grounding.check_note` (no LLM) flags numbers, genes and URLs that no tool
    returned, and allows one rewrite.
  - **Note sections:** Summary / Observed / Model inferences / Hypotheses and evidence /
    Caveats, with labels on every bullet (#43).
  - **Tools:** `observed_findings`, `predict_risk`, `modality_contributions` (measured against
    a typical patient, #38), `top_features`, `search_literature` (Tavily), and the
    observed-mutations and CIViC `treatment_evidence` tools (#46).
  - **Fallbacks:** any API error (402, 401, 429, 5xx, timeout) falls back to an offline
    template note (#34).
- **Demo** (`app/streamlit_app.py`, `app/charts.py`, `muffle.demo`):
  - Three tabs: Case review (213 held-out patients), Federation, How it works.
  - Live notes are capped per session (`DEMO_LIVE_NOTES_PER_SESSION`, default 5).
  - 8 saved notes are in `app/saved_notes.json`; the results JSON is
    `app/results_tcga_brca.json`.
  - Hosted mode loads the bundle (`load_bundle` / `fetch_bundle`, `torch.load(weights_only=True)`).
  - `secrets_to_env()` copies Streamlit secrets into the environment (#50).
  - The hospitals are labeled "simulated" (#44).
- **MSK-CHORD risk updates** (#48, `muffle.longitudinal`, `scripts/prepare_msk_chord.py`,
  `make msk-chord`, `make experiment-msk`, `docs/longitudinal.md`):
  - Landmarks at 0, 6, 12 and 24 months.
  - Outcome: progression or death in the next 12 months.
  - Model: `HistGradientBoostingClassifier`, record-so-far vs diagnosis-only.
  - Record-so-far AUROC is 0.880 → 0.931, vs 0.66–0.71 for diagnosis-only (aggregates only).

**What is partially built:**
- **Synthetic timeline patient, PR #49** (branch `app/synthetic-timeline`, worktree
  `.claude/worktrees/vision`):
  - Adds `src/muffle/timeline.py`, `scripts/make_timeline_patient.py`,
    `app/timeline_synthetic.json` and `tests/test_timeline.py`.
  - Adds a new first demo tab "Patient timeline (synthetic)", plus `docs/longitudinal.md` and
    `docs/decisions.md` sections. The PR body says 84 tests passed.
  - ✅ **It conflicts with `origin/main` in `app/streamlit_app.py`.** There is one conflict
    hunk, probably next to #50's `secrets_to_env` and/or #48's changes (❓ which lines).
- **Hosted demo:**
  - Live agent off (✅).
  - Bundle v1 has no mutation fields, so the hosted case review shows "not sequenced" and no
    CIViC (⚠️ memory note).
  - The 8 saved notes predate #43, so they lack the [Observed] / [Model inference] /
    [Hypothesis] labels (⚠️ memory note).
- **Submission drafts:** `docs/submission.md` (#42, with a Token Factory / NVIDIA feedback log
  and 9 "IN PROGRESS" markers) and `docs/video.md` (#47, case 661 with PIK3CA H1047R + CIViC;
  backup case 710). Both await the user's review (⚠️).
- **README** (✅ read): it still marks evidence labels, mutations + CIViC and the patient
  timeline as *(in progress)* and leaves those roadmap boxes unchecked, although #43, #46 and
  #48 are merged. The README is submission material, so ask before editing it.
- **`docs/HACKATHON.md`:** every requirement checkbox is still `[ ]` (✅).

**What is broken or blocked:**
- ✅ **`docs/registry.md` does not exist** on `origin/main`. Yet `CLAUDE.md`, `README.md`,
  `docs/VISION.md` and `docs/HACKATHON.md` all point to it, and `CLAUDE.md` says to add every
  new source there.
  - An earlier side session titled "Dataset and model registry (docs/registry.md)" exists but
    left no branch or PR (✅ no such branch locally or on `origin`).
- ✅ PR #49 is not mergeable until the conflict is resolved.
- ✅ **Hosted live notes are blocked on the user**, who must add `NEBIUS_API_KEY` and
  `TAVILY_API_KEY` in the Streamlit app's Settings → Secrets, at root level with exact names.
  Claude must not type keys. The hosted secrets already hold `TOKEN_FACTORY_BUDGET_USD = "3"`
  and `DEMO_LIVE_NOTES_PER_SESSION = "5"` (⚠️ memory note).
- **Environment limits** (✅ checked):
  - About 3.2 GiB of disk is free (99% used).
  - The user's Claude plan was at 93% of its 5-hour window and 87% of its weekly window at
    handoff time.
  - The Mac is an M1 with 8 GB of RAM (⚠️ memory note).

**What has NOT been started yet:**
- `docs/registry.md`: datasets and models with license, access tier, and used or not.
- **Freeze to-dos** (⚠️ memory note):
  - regenerate the saved notes (`make demo-notes`);
  - build bundle v2 with mutations and the CIViC rows its cases need (`make demo-bundle`);
  - publish release `demo-bundle-v2` and update `BUNDLE_URL` in `app/streamlit_app.py`
    (currently `…/releases/download/demo-bundle-v1/demo_bundle.pt`).
- **Final submission work:** README for judges with the final numbers and URL, recording the
  video, the Devpost text, and the submission itself (issues #6, #7, #12–#15).
- **Nemotron narration of the synthetic timeline:** blocked on a team decision (see §4).
- **The pathologist workspace request** (§4): not started.

**Current user experience** (✅ local and hosted, as rendered this session):
1. A visitor opens the demo. The header is "MuFFLe++ · federated tumor-board assistant", and
   the subtitle mentions 3 simulated hospitals.
2. **Case review:** pick a held-out patient (★ marks those with a saved note). The tab shows:
   - risk percentile, risk group, simulated hospital and data layers present;
   - a histogram of where the patient sits;
   - a bar chart of each layer's contribution vs a typical patient;
   - a "What if a data layer were missing?" expander.
3. **Tumor-board note:** "Write the note with Nemotron" (live: planner steps, grounding
   result, tool trace and a Markdown download) or "Show the saved note". Hosted, live notes are
   off, so only saved notes appear.
4. **Federation tab:** the simulated hospitals, LOSO results, and Kaplan–Meier curves of the
   held-out risk groups. **How it works:** the method, privacy and limits.
5. The experience stops there. There is no timeline tab on `main` yet (#49), no patient
   upload, and no imaging.

**Data and state:**
- **Local data** (git-ignored):
  - `data/raw/{tcga_brca,civic,msk_chord}`, `data/tcga_brca/cohort.npz` (format in the
    `scripts/prepare_tcga.py` docstring), `data/synthetic/`; 749 MB in all.
  - `outputs/`: `tcga_fedavg.pt` (the demo model), `demo_bundle.pt`,
    `experiments/tcga_brca_3clients.json`, `experiments/tcga_brca_residual.json`,
    `msk_chord/` (local only), `calibration/`.
  - `workspaces/`: the NVFlare simulator workspaces, 471 MB.
- **Committed derived artifacts:** `app/results_tcga_brca.json`, `app/saved_notes.json`, and
  `app/timeline_synthetic.json` (only on #49: the synthetic patient, aggregates and CIViC).
- **Spend ledger:** `~/.muffle/token_factory_spend.json`. It is local to this Mac, and the
  hosted ledger resets on every container restart.
- **Bundle contents:** model weights, the inputs of 40 held-out cases, 1,064 cohort risks,
  layer offsets, feature names, per-site C-index and KM curves. It holds no survival times.

---

### 3. ARCHITECTURE & TECHNICAL MAP

**Tech stack:**
- **Language and runtime:** Python. Locally 3.12.14, installed via `uv` in `~/.local/bin`
  because the system `python3` is 3.9.4. CI uses 3.11, and the README supports 3.10–3.13.
- **ML:** PyTorch (CPU on the hosted app); NVIDIA FLARE 2.9.0 (requirement `>=2.8,<3.0`);
  numpy, pandas, scikit-learn (HistGradientBoosting, metrics), lifelines, scikit-survival,
  PyYAML.
- **App:** Streamlit + Altair.
- **LLM and search:** `openai` SDK against Nebius Token Factory (OpenAI-compatible) for
  Nemotron; `tavily-python`; `python-dotenv`.
- **Tooling:** ruff, pytest, GitHub Actions, and `gh` (in `~/.local/bin`; there is no
  Homebrew).
- **Hosting:** Streamlit Community Cloud, plus GitHub Releases for the bundle.

**Key files and folders:**
| Path | Role |
|---|---|
| `src/muffle/data/{tcga,dataset,partition,preprocess,synthetic}.py` | Cohort building, `MultiOmicDataset`, site partitioning, z-scoring and feature selection, synthetic cohorts |
| `src/muffle/models/fusion.py` | `MLPEncoder`, `MuffleNet` (mask-aware fusion + Cox head) |
| `src/muffle/losses.py`, `metrics.py`, `engine.py` | Cox partial-likelihood loss (whole batch), C-index (site-stratified), train/eval loops |
| `src/muffle/residual.py` | Clinical-anchored residual, two-stage training, federated λ selection |
| `src/muffle/train_local.py` | Centralized and local-only training, checkpoints, `heldout_c_index` |
| `src/muffle/experiment.py` | Repeated-seed and LOSO experiment runner |
| `src/muffle/calibration.py` | Breslow, KM, calibration tables, cross-site fairness slices |
| `src/muffle/explain.py` | `masked_effects`, `cohort_offsets`, `modality_contributions`, `top_features`, percentiles and groups |
| `src/muffle/report/nemotron.py` | Case agent loop (`run_case_agent`), writer, offline template, Tavily search, CLI |
| `src/muffle/report/case_tools.py` | `CaseTools`: the tool schemas and implementations, each labeled with an evidence type |
| `src/muffle/report/grounding.py` | `check_note`: a no-LLM check that every number, gene and URL is in the tool outputs |
| `src/muffle/report/budget.py` | `BudgetedClient`, `Ledger`, `HARD_CAP_USD = 25.50`, `PRICES_PER_M` |
| `src/muffle/report/civic.py` | CIViC nightly TSV loader and evidence lookup |
| `src/muffle/demo.py` | `build_demo`, `Case`, `Site`, `Demo`, `save_bundle`, `load_bundle`, `fetch_bundle` |
| `src/muffle/longitudinal.py` | MSK-CHORD landmark task and evaluation (local data only) |
| `src/muffle/fl/client.py`, `jobs/fedavg_job.py` | NVFlare client script and the Recipe-API job (`--residual`, `--save`) |
| `app/streamlit_app.py`, `app/charts.py`, `app/requirements.txt` | The demo app; the slim hosted install (CPU torch, no NVFlare) |
| `scripts/` | `prepare_tcga.py`, `prepare_msk_chord.py`, `make_synthetic.py`, `make_demo_bundle.py`, `save_demo_notes.py`, `export_results.py` |
| `configs/default.yaml`, `configs/tcga_brca.yaml` | Model, training, FL and data config (TCGA overrides the defaults) |
| `tests/` | 16 test modules. Live APIs are faked. `test_model.py` guards missing-layer handling. |

**How the system works end to end:**
1. **Build the cohort.** `make tcga` runs `scripts/prepare_tcga.py`, which downloads open-tier
   files from the UCSC Xena GDC hub and the GDC open masked MAF. It keeps one primary tumor per
   patient, ranks top-variance features before z-scoring, and writes
   `data/tcga_brca/cohort.npz` (x per layer, masks, time, event, tissue source site, clinical
   fields, mutations).
2. **Split into hospitals.** `muffle.data.partition` groups whole tissue source sites into 3
   simulated hospitals (355/355/354 patients), each with a 20% validation split.
3. **Train federated.** `make fl-tcga` runs `jobs/fedavg_job.py --residual`, with NVFlare
   `SimEnv` and 3 clients:
   - phase 1 trains the clinical anchor for 20 FedAvg rounds;
   - phase 2 trains the omic residual for 20 rounds;
   - λ is picked from per-client held-out-site pair counts.

   The result is `outputs/tcga_fedavg.pt`.
4. **Evaluate.** `python -m muffle.experiment … --loso` produces `outputs/experiments/*.json`.
   `make demo-results` turns them into `app/results_tcga_brca.json`.
5. **Explain a case.** `muffle.explain` computes the risk, the cohort percentile and group,
   per-layer contributions (masked effect minus that layer's cohort-average masked effect), and
   top features (gradient × input).
6. **Run the agent.** `run_case_agent`:
   - Super, through `BudgetedClient`, calls the `CaseTools`, all local except Tavily.
   - Ultra gets the case header and tool outputs (minus log-risk values and reading notes) and
     writes the labeled note.
   - `check_note` checks it; on findings the writer gets one rewrite, and anything left is
     shown under the note.
   - On any failure or budget refusal, the offline template note is used, with the reason.
7. **Show the demo.** `app/streamlit_app.py` first calls `secrets_to_env()`.
   - With `--ckpt` and `--data` it uses `build_demo` on the full data.
   - Otherwise it calls `load_bundle(--bundle | MUFFLE_BUNDLE | BUNDLE_URL)`.
   - It renders the tabs and caps live notes per session.
8. **Evaluate longitudinally (local only).** `make msk-chord` then `make experiment-msk`
   (`muffle.longitudinal`) produce `outputs/msk_chord/risk_updates.json`, written up as
   aggregate tables in `docs/longitudinal.md`. On #49, `make demo-timeline` scores the
   hand-written synthetic patient with these models and writes `app/timeline_synthetic.json`.
   The models themselves never leave the machine.

**AI and model architecture:**
- **Implemented:** the survival model and FL above, and the two-model agent with the grounding
  check.
- **Decided, not built:** Nano isn't used.
- **Planned (VISION roadmap):** pretrained pathology and radiology encoders, inferred mutation
  status, more specialized models "added only when they measurably help".
- **Evaluation:** site-stratified C-index; LOSO with ~4× smaller error bars than the validation
  splits; mean ± sd over seeds 0–4; tuning on seeds 95–99 only.

**Commands that matter** (run from the repo root; all use `.venv`):
```
make setup PY=python3.12     # system python3 is 3.9, too old
make test                    # pytest -q
make lint                    # ruff check src tests jobs scripts app  (the CI lint gate)
make tcga                    # build data/tcga_brca (needs network; large methylation stream)
make fl-tcga                 # FedAvg-residual demo model -> outputs/tcga_fedavg.pt
make experiment-tcga         # repeated-seed + LOSO experiments
make calibration-tcga
make agent-tcga PATIENT=0    # one live (or offline) note from the terminal
make demo-tcga               # full-data demo on :8501 (or preview_start name "demo-tcga")
make demo-notes / demo-results / demo-bundle / demo-hosted
make msk-chord / experiment-msk          # local only
.venv/bin/python -m muffle.report.budget  # spend so far; --add USD records outside usage
# In a worktree (the main .venv has muffle installed editable from the MAIN folder's src):
PYTHONPATH=src ../../../.venv/bin/python -m pytest -q
```
**CI** (`.github/workflows/ci.yml`) runs on Python 3.11, in this order: CPU torch install,
then `ruff check`, then `pytest -q`, then synthetic data, a 2-client / 2-round FL job and the
offline agent on its model.

**Configuration and environment:**
- **Environment variables** (names only; values live in the git-ignored `.env`; template in
  `.env.example`):
  - Token Factory: `NEBIUS_API_KEY`, `TOKEN_FACTORY_BASE_URL`, `NEMOTRON_MODEL`,
    `NEMOTRON_WRITER_MODEL`, `TOKEN_FACTORY_BUDGET_USD` (can only lower the cap).
  - Search: `TAVILY_API_KEY`.
  - Demo: `DEMO_LIVE_NOTES_PER_SESSION`, `MUFFLE_BUNDLE`, and `GITHUB_TOKEN` (only for a
    private release).
  - Paths: `DATA_DIR`, `OUTPUT_DIR`.
  - The `NEBIUS_BUCKET` / `AWS_*` variables are unused.
- **Preview configs:** `.claude/launch.json` (local, untracked) defines three:
  - `demo-tcga` on :8501;
  - `demo-hosted` on :8502, which points at an old scratchpad venv that is probably gone;
  - `demo-vision` on :8503, which runs the demo from `.claude/worktrees/vision`.
- **Local vs hosted:** hosted uses `app/requirements.txt` (no NVFlare), the bundle and not the
  data, Streamlit secrets, and a ledger that resets on restart.

**Naming and coding conventions:**
- **Branches:** `<area>/<topic>`. **Commits:** `<area>: <change>`, with areas
  data/model/fl/eval/app/infra/docs.
- **Merging:** squash-merge, with the PR number in the title.
- **Commit email:** `git config user.email` in the repo is the GitHub noreply address.
- **Decision log:** `docs/decisions.md` entries are "date — title" with What / Why /
  Result / Consequence bullets.
- **Documentation and UI text:** plain, specific prose with numbers and their uncertainty.
- **Tests:** they use fakes for Token Factory and Tavily, with no network calls and no real
  data.
- **Tool outputs:** they carry `evidence_type`. Contribution keys are named
  `log_risk_added_by_layer`; the old name `delta_log_risk_when_removed` read backwards and was
  removed.

**Security and privacy boundaries:**
- See `CLAUDE.md`.
- **Sources of truth for privacy and security mechanisms:**
  - **Budget:** `budget.py` enforces the cap. It reserves the worst case before sending.
  - **What leaves the machine:** `nemotron.py` and `case_tools.py` define what goes to Token
    Factory and Tavily: derived numbers and gene names only.
  - **Bundle safety:** the bundle loads with `weights_only=True`, so a tampered release can't
    run code.
- **The Tavily dev key was once pasted into a chat.** Suggest the user regenerate it (⚠️ memory
  note). Keys must never be printed or typed by Claude.

---

### 4. RECENT WORK — WHAT JUST HAPPENED (HIGH PRIORITY)

**This session** (✅, about 22:23–22:45 CDT, Oct 18):
1. The user asked for this continuation document and resume prompt.
2. Inspected the git state, branches, worktrees, PRs, issues, releases and memory notes, and
   read `docs/HACKATHON.md`, `docs/VISION.md`, `docs/decisions.md`, `docs/longitudinal.md`,
   the README sections, the CI config and the Makefile.
3. **Interrupt from the user:** the `demo-tcga` preview failed with "Port 8501 is not
   available".
   - Diagnosed it with `lsof`: a stale Streamlit process with the same command, about 41
     minutes old, started through the Claude app's helper. No running session owned it.
   - Stopped it (SIGTERM) and restarted via `preview_start demo-tcga`. Verified the page text
     and that there were no console errors.
   - **Decision:** stop the orphan instead of changing the port, because the preview config and
     docs assume 8501 and the orphan was the same app.
4. Checked the hosted demo: it loads, but live notes are off.
5. Ran the tests and lint on `origin/main` in a worktree: 81 passed, `ruff check` clean.
6. Found that `docs/registry.md` is missing and that #49 conflicts with main.
7. Created branch `docs/continuation-handoff` from `origin/main` in the existing worktree
   `.claude/worktrees/secrets`, with the upstream unset so a plain push can't target `main`.
   - **Why reuse this worktree:** disk is nearly full, its branch #50 was already merged, and
     the main folder must not switch branches (`CLAUDE.md`).
   - **Why `docs/`:** it is the repo's established documentation folder.
   - Wrote this file there. The commit, push and PR are recorded in the git history, not here.

**Earlier work, most recent first** (⚠️ from git log, `docs/decisions.md` and memory notes):
- **Oct 19, ~03:00 UTC:** deployed on Streamlit Cloud. #50 makes Streamlit secrets visible as
  environment variables. Live mode on the hosted app was never confirmed, and is now confirmed
  off.
- **#48:** MSK-CHORD timelines and risk updates (local only).
- **#46:** observed driver mutations (GDC open, masked) and the CIViC tool.
- **#45:** README agent section.
- **#44:** "simulated" labels for the hospitals.
- **#43:** evidence labels in the note.
- **#41:** reframed the project as **milestone 1 of the cancer intelligence platform**, which
  replaced the earlier "lead with federation" pitch. The user chose this.
  - The user also chose:
    - breast cancer;
    - MSK-CHORD local-only;
    - 12-month progression-or-death re-predicted at each event;
    - a synthetic demo patient.
  - **Why:** to move toward the team's vision while staying within the deadline.
- **#39 and #40:** hosted bundle and slim requirements; the repo made public after a pre-public
  audit; `main` protected.
- **#36–#38:** Super plans and Ultra writes (the Devpost track text says to use Ultra for
  serious reasoning), the grounding check, live Tavily with relevance filters, and the demo
  redesign with contributions measured against a typical patient.
- **#32–#34:** the $25.50 cap (the account auto-charges a card once credit runs out), and
  percentile wording and offline fallback fixes.
- **#29 (residual model):** the omics only correct the clinical risk. λ is picked on
  site-held-out inner splits, which brought fusion level with clinical-only, though not above
  it.
- **#27:** never drop clinical in modality dropout; 20 FL rounds.
- **#26:** the hospital split, repeated seeds and LOSO.
- **#24:** the TCGA loader.
- **#23:** the agent was first built offline.
- **#19–#22:** the hackathon framing.
- **#1:** the scaffold.

**Decisions and why** (the full reasoning is in `docs/decisions.md`; these are the ones most
likely to be undone by mistake):
- **Clinical-only beats every fusion variant** on BRCA overall survival (0.702). The pitch and
  docs must say so plainly, and must not claim that omics add signal. Don't write "≫ alone":
  the gain over local-only (+0.044) is only about 1.4 local-only standard deviations.
- **Contributions are measured against a typical patient (cohort offsets).** Masking alone
  shifted every patient by a near-constant per layer (−0.08 to −0.18), so 17% of high-risk
  patients showed every layer "lowering" risk.
- **FedAvg is scored with the final global model,** not `best_FL_global_model.pt`, because
  NVFlare selects the "best" model on the same validation splits, which makes it optimistic.
- **λ is picked on whole-site inner splits,** not random-patient ones. Random splits gave
  λ ≈ 0.4, which didn't transfer to new hospitals because of site and batch effects.
- **Additive fusion with dropout 0.8, clinical always kept:** additive beat concat (0.718 vs
  0.672 on tuning seeds); dropping clinical hurt (0.658 vs 0.684).
- **Hosting gets only weights plus derived data for 40 cases.** The bundle lives in a release
  because the repo bans `.pt`.
- **Nebius usage is Token Factory only, on free credits.** The Serverless Job was cut over
  cost; FL runs in the NVFlare simulator.
- **Keep NVFlare; reject the broader `MUFFLE_SPEC`** (Flower, DP/SecAgg, gated foundation
  models). It was a multi-week, GPU-heavy build, and Flower would replace NVIDIA's own FL
  SDK.
- **The endpoint is overall survival.** PFI is only a time-boxed check after the requirements
  are done, and only if TCGA-CDR shows clearly more events.

**Rejected approaches and dead ends** (⚠️ from decisions.md and memory notes; "conditional"
means they could be revisited):
- A Nebius AI Cloud Serverless Job for FL (cost; conditional on credits).
- Concat fusion.
- Dropping clinical in modality dropout.
- Keeping Adam state across FL rounds (no gain).
- Fewer omic features (top 32/32/16 gave 0.667; barely helped).
- CPTAC protein: it covers only ~100 tumors, so RPPA is used instead.
- Ranking features after z-scoring (arbitrary picks once every variance is 1).
- Lymphoma as the cancer: TCGA has only ~48 patients.
- **Tavily failures:**
  - combined multi-gene queries and unnamed ids (AC138356.2, Y_RNA) returned generic pages;
  - a 4-turn planner never reached the search;
  - non-scholarly domains (YouTube, a vendor page) slipped in.
- **Writer limits:** Ultra at 2,000 or 3,000 max tokens got cut off; the limit is now 4,096.
- Streamlit subdomains containing "muff" are rejected by its filter.
- **Toolchain:** Homebrew (needs a sudo prompt the user couldn't answer) and interactive
  terminal prompts. The user can't type into the Terminal panel; use background tasks and give
  codes in chat.
- **Branch protection on a private free repo** returned 403. The local hook was the stand-in
  until the repo went public.

**Discussed but NOT yet implemented:**
- **Nemotron narrating the synthetic timeline** (*blocked: team decision*). The scores come
  from MSK-CHORD-trained models, and the rule forbids sending anything from MSK-CHORD to Token
  Factory. Does a synthetic patient's score count? PR #49's decision entry raises the question.
- **`docs/registry.md`** (*approved, part of the 2026-10-18 plan; not started*).
- **Bundle v2, release `demo-bundle-v2`, regenerated saved notes** (*approved freeze to-dos;
  not started*).
- **README update for judges and the final numbers; Devpost text (#42); video (#47)**
  (*drafts in progress; need the user's review*).
- **A separate Token Factory key for the hosted demo; regenerating the Tavily key**
  (*suggested to the user; their account actions*).
- **Pathologist workspace** (*requested by the user in an earlier session, not started,
  not reconciled with the hackathon plan*). The request:
  - a patient list with search;
  - a patient file with the latest report first (summary, why, risk factors, areas of risk, an
    SOS tile for alarming findings);
  - Import test, Tests and Timeline views;
  - tile overlays on slides and scans (hover shows tile stats, click expands, uncertain or
    high-risk regions flagged);
  - "use the best public pretrained models".

  **Earlier license research (⚠️ from memory):**
  - Permissive: H-optimus-0, Prov-GigaPath, Hibou, kaiko midnight, QuiltNet,
    TMEsegBreastTCGA, TIAToolbox BCSS.
  - Non-commercial or no-derivatives: UNI/UNI2-h, CONCH, TITAN, Virchow2, H-optimus-1.

  **Blockers:** 8 GB RAM, a nearly full disk, an HF token for gated models, and the deadline.
  Treat it as roadmap unless the user re-prioritizes it.
- **The PFI endpoint** (*conditional*).

**Current work in progress:** this handoff (branch `docs/continuation-handoff`). The last
product work before it was #49 (the synthetic timeline). It is complete, but it needs a rebase
or merge onto `origin/main` to resolve the `app/streamlit_app.py` conflict.

**Open threads:**
- Whether the timeline may be narrated by Nemotron.
- Whether and when to merge #42 and #47; both need the user's OK as submission material.
- Whether the user has added the API keys to Streamlit secrets.
- Whether to prune the stale branches and worktrees (ask).
- Whether the pathologist workspace fits before the freeze.
- Official Nemotron Super and Ultra prices: the current ones come from price trackers and are
  unverified on the Nebius console.

**Likely next steps** (recommended order; ⚠️ the user hasn't approved this order this
session):
1. **Resolve the #49 conflict.** In `.claude/worktrees/vision`, run `git fetch` and
   `git merge origin/main` (or rebase), then fix `app/streamlit_app.py`. Keep #50's
   `secrets_to_env()` and the new timeline tab. Run the tests with `PYTHONPATH=src`, then push.
   On green CI it may be squash-merged as an in-plan app PR. Unblocks: the demo timeline tab.
2. **Write `docs/registry.md`.** It is referenced in 4 places and required by `CLAUDE.md`'s
   data rules. Cover TCGA-BRCA via Xena/GDC, GDC masked MAF, CIViC (CC0), MSK-CHORD
   (CC BY-NC-ND 4.0), the Nemotron models and Tavily: license, access tier, and used or not.
   Low risk, in plan.
3. **Ask the user to add `NEBIUS_API_KEY` and `TAVILY_API_KEY` to the Streamlit secrets,**
   then verify that the hosted sidebar says live and make one capped live note.
4. **Freeze to-dos:** `make demo-notes` (labeled notes), bundle v2 with mutations and CIViC, the
   `demo-bundle-v2` release, `BUNDLE_URL`. These change what judges see, so confirm first.
5. **README "(in progress)" markers and roadmap boxes; `docs/HACKATHON.md` checkboxes.** Needs
   the user's OK for the README.
6. **The user's review of #42 and #47;** then the video and submission (Oct 28–30).
7. **Housekeeping (ask first):** fast-forward the main folder's `main`
   (`git pull --ff-only`); prune merged local branches and the leftover worktree.

**Promote to project memory** (candidates for `CLAUDE.md`; not applied, since `CLAUDE.md`
changes go through a PR and these are small):
- In a git worktree, test with `PYTHONPATH=src`. The shared `.venv` has `muffle` installed
  editable from the main folder, so otherwise you test main's code.
- The CI lint gate is `ruff check` only. `ruff format` would reformat 37 files, so don't run it
  repo-wide.
- Before `preview_start demo-tcga`, a stale Streamlit may hold :8501. Check with
  `lsof -nP -iTCP:8501 -sTCP:LISTEN`.
- `docs/registry.md` is referenced but missing. Create it rather than removing the references.

---

### 5. WHAT COULD GO WRONG

**Known bugs and issues:**
- **PR #49 merge conflict** (✅). Reproduce: run `git merge-tree` on the merge base,
  `origin/main` and `app/synthetic-timeline`; it shows one conflict in `app/streamlit_app.py`.
- **Hosted live notes are off** (✅). Visit `/~/+/` and the sidebar or note area says "Live
  notes are off here". Expected after the keys are set: a "Write the note with Nemotron" note,
  capped at 5 per session.
- **Stale README markers** (✅).
- **Missing `docs/registry.md`** (✅).
- **Saved notes predate the evidence labels; bundle v1 lacks mutations** (⚠️).
- **FedAvg C-index varies by about 0.01 between identical runs,** because NVFlare's initial
  global model isn't seeded. Compare means over seeds, never single runs (⚠️).
- **Agent quirk** (⚠️ older observation): the Summary sometimes repeats the instruction about
  percentiles, or calls clinical an "omic" layer. Re-run `make agent-tcga` on a few patients
  before recording.

**Edge cases to watch for:**
- **Missing data layers:** every component takes a mask, and methylation covers ~72% and
  protein ~80% of patients. "Not sequenced" is not wild type.
- **Feature names:** zero-score or unnamed features (e.g. AC124067.4) are dropped from notes
  and searches. An all-letter gene symbol must match exactly (CAMP vs cAMP vs an author
  "Camp RL").
- **Agent fallbacks:**
  - a planner that runs out of turns gets one search-only turn;
  - if Ultra is cut off or fails, Super writes the note;
  - a 402 means out of credit, and the offline note is used.
- **Small numbers of deaths:** the event rate is ~0.14, so per-site C-indexes are noisy
  (bootstrap CI ±0.04–0.10). The Cox loss needs whole batches, never tiny ones.
- **MSK-CHORD landmark populations differ,** so compare models within a landmark. Its labels
  come from NLP of radiology reports, and some features reflect care intensity.

**Technical debt and shortcuts:**
- Feature selection is pooled and unsupervised. A real federation would use
  `harmonize_features`.
- `Dockerfile`, `docs/NEBIUS.md` and `--gpu` are untested leftovers.
- The `NEBIUS_BUCKET` / `AWS_*` variables are unused.
- The `demo-hosted` launch config points at a deleted scratch venv.
- Format drift (37 files).
- Prices in `budget.py` come from trackers. Unknown models are deliberately charged a high
  $3 / $9 per 1M tokens.

**Architectural risks:**
- Token Factory credits and availability.
- Tavily free-tier credits: at most 3 per note.
- Streamlit Cloud: sleeping apps, resource limits, and the ledger reset.
- The demo depends on the GitHub release asset URL.
- NVFlare API changes: stay on the Recipe API; don't reintroduce `FedAvgJob`.

**Security and privacy risks:**
- **MSK-CHORD files** live in `data/raw/msk_chord` and `outputs/msk_chord`. They are
  git-ignored, but JSON isn't ignored by extension, so check that any new `app/*.json` holds
  only synthetic or aggregate data.
- **Keys** live in `.env` and Streamlit secrets only.
- **Older commits** carry a personal (non-noreply) email; the user chose not to rewrite
  history.
- **This document** contains local absolute paths, including the macOS username, by design so
  the resume prompt works. It contains no keys, emails or patient data.

**Assumptions that may be wrong:**
- ❓ That the #49 conflict is small. It is one hunk, but its contents weren't inspected.
- ❓ That nobody else is working in the main folder. No session was running at handoff, but the
  team is two people on one Mac.
- ❓ That the hosted secrets are exactly `TOKEN_FACTORY_BUDGET_USD = "3"` and
  `DEMO_LIVE_NOTES_PER_SESSION = "5"`. This comes from a memory note.
- ❓ Model ids, prices and Devpost rules (re-read Oct 18). Re-check them before submitting.
- ⚠️ The local `main` is behind `origin/main`. Anything run from the main folder (including the
  :8501 demo) lacks #48 and #50.

**Regression risks:**
- `tests/test_model.py` (masks); `cohort.npz` arrays must stay byte-identical when fields are
  added.
- Contribution semantics (cohort offsets) and key names.
- The grounding check, the budget cap, the evidence labels and the "simulated" labels.
- Bundle backward compatibility: v1 must still load; mutations default to None.
- `weights_only=True` loading.
- The seed protocol: tuning on seeds 95–99, reporting seeds 0–4.

**Operational risks:**
- About 3 GB of disk is free, and an app worktree with its own environment needs about
  5.4 GB. Reuse the existing worktrees.
- The user's Claude usage is near its limits. Work sequentially, with no parallel sessions, and
  stop at a clean point at about 85%.
- `gh`, `uv` and `python3.12` are in `~/.local/bin`, which isn't on the interactive zsh PATH.
- The pre-push hook and branch protection reject direct pushes to `main`. That is expected.

---

### 6. HOW TO THINK ABOUT THIS PROJECT

1. **Core philosophy:**
   - *Honest, evidence-linked decision support built from small, validated pieces.* Every
     claim is labeled observed / inference / hypothesis.
   - Every number comes with its baseline and uncertainty, measured with the seed protocol, and
     uncomfortable results are stated (clinical-only wins).
   - Every note claim traces to a tool output (the grounding check).
   - Data rights decide what can be shown or sent.
   - Architecturally: a mask-aware multimodal model trained federatedly, wrapped by a
     tool-calling agent whose tools are the model's own explanations.

   This was chosen because the team's vision is a trustworthy clinical platform, and the
   judges value a complete, credible product over a proof of concept.
2. **Most likely newcomer mistakes:**
   - overstating results ("omics improve prediction", "FL ≫ local");
   - showing or sending MSK-CHORD-derived material;
   - unlabeled inferences or simulated sites;
   - raising or bypassing the budget cap;
   - testing the wrong code in a worktree (no `PYTHONPATH=src`);
   - switching the main folder's branch;
   - merging submission-material PRs without asking.
3. **Intentionally preserved design (looks refactorable, isn't):**
   - the separate planner and writer models plus a no-LLM grounding check (track guidance and
     verifiability);
   - the offline template fallback (the demo must never traceback);
   - the cohort-offset contributions;
   - final-model FedAvg scoring;
   - site-held-out λ selection;
   - the weights-only bundle;
   - NVFlare over Flower;
   - Token Factory only.
4. **Product vs implementation:** the essentials are the evidence-linked, labeled profile that
   updates over time, with clear "for clinician review" framing and visible provenance. The
   timeline tab (#49) and live hosted notes are the biggest gaps between intent and what a
   judge sees today.
5. **How to judge progress:**
   - CI green, with `make test` and `make lint` passing;
   - the hosted URL shows a live, grounded, labeled note;
   - the timeline tab works hosted;
   - the registry exists;
   - the README and HACKATHON checkboxes match reality;
   - reported numbers are unchanged unless a deliberate, documented rerun.
6. **Tradeoffs:**
   - **Accepted:** the simulator instead of real sites; overall survival only; laptop-scale
     models; aggregates-only MSK-CHORD; a 40-case hosted bundle; free-credit-only spending.
   - **Unresolved:** timeline narration; the pathologist workspace; PFI.
   - **Not permanent:** the Nebius Serverless Job, the omics-vs-clinical result (could change
     with a better model or endpoint), and the hosted case count.

---

### 7. DO NOT TOUCH LIST

- Do NOT refactor stable, working systems without being asked. Don't redesign the
  architecture unless instructed.
- Preserve naming conventions, data contracts (the `cohort.npz` format, bundle fields, tool
  output keys, `evidence_type`) and the established tradeoffs above.
- Ask before adding frameworks, libraries, services or infrastructure.
- Never overwrite or discard others' changes or worktrees. Never switch the main folder's
  branch. Use a worktree.
- Never raise, bypass or reset the $25.50 cap or the ledger. Never print, log or type keys.
- Never commit `data/`, `outputs/`, `workspaces/`, `.claude/`, `.env`, or `.csv/.tsv/.npz/.pt`
  files. Never commit, host, show or send any MSK-CHORD patient or MSK-CHORD-trained model.
- Never change reported numbers, the pitch, the README, the Devpost text or the video, make
  repo-visibility changes, or merge after the Oct 28 freeze without asking the user.
- Don't reintroduce NVFlare's old `FedAvgJob` API. Don't use tiny batches or per-sample Cox
  losses.
- Keep `tests/test_model.py` passing; keep missing-layer handling everywhere.
- Don't run `ruff format` repo-wide. Don't force-push or rewrite history.
- Don't claim verification, merges or deployment without evidence. Don't implement proposed
  features (the pathologist workspace, timeline narration) as if they were approved.

---

### 8. CONFIDENCE & FRESHNESS

| Area | Confidence | Basis |
|---|---|---|
| Repo, branch, commits, worktrees, PRs, issues, release | ✅ HIGH | `git` / `gh` output this session |
| Tests and lint on `origin/main` | ✅ HIGH | 81 passed, `ruff check` clean, this session |
| Local and hosted demo render; hosted live off | ✅ HIGH | Browser checks this session |
| `docs/registry.md` missing; #49 conflict | ✅ HIGH | `git ls-tree` / `git merge-tree` |
| Spend $0.4632 / $25.50 | ✅ HIGH | `muffle.report.budget` this session (local ledger only) |
| Results numbers (C-index, AUROC) | ⚠️ MEDIUM | README, decisions and docs; not rerun |
| Agent behavior live (Super, Ultra, Tavily) | ⚠️ MEDIUM | Decisions log and memory notes; no live call this session |
| Bundle v1 lacking mutations; saved notes unlabeled | ⚠️ MEDIUM | Memory notes |
| Hosted secret names and values | ❓ LOW | Memory note; can't be read from here |
| Size and content of the #49 conflict | ❓ LOW | Only the file and hunk count are known |
| Model prices; Devpost rules current | ❓ LOW | Price trackers; rules re-read Oct 18 |
| Pathologist workspace scope and priority | ❓ LOW | One earlier request, not reconciled with the plan |

Handoff timestamp: **2026-10-18 22:31 CDT**. Re-check the repo state, open PRs, the hosted app,
dependency versions, credits and the Devpost rules whenever this document is reused. Newer
source code, user instructions and `CLAUDE.md` override this document.

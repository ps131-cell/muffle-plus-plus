# PROJECT CONTINUATION DOCUMENT
## Monday 19 October 2026, 01:05 CDT (06:05 UTC)

Handoff for a fresh AI session (or a teammate on another Claude or GitHub account) on
**MuFFLe++**. It replaces `docs/AI_Continuation_Document-18Oct2026-2231.md`, which was written
three hours earlier from leaner reading and has since gone stale: #49 and #52 merged, #53 opened,
and the hosted demo broke. This version was built from a full re-read of every doc, source file,
script, test, config and memory note, plus fresh test runs and browser checks of both demos.

It does not repeat the rules in `CLAUDE.md`; read that file as well. Appendix A explains how to
recover everything that exists only on this Mac. Appendix B is the resume prompt.

**Confidence markers:**
- ✅ **HIGH:** checked in this session (commands run, files read, pages loaded).
- ⚠️ **MEDIUM:** from repo docs, git history or earlier sessions' notes; not re-checked.
- ❓ **LOW:** inferred or uncertain; verify before relying on it.

---

### 1. PROJECT IDENTITY

**Project name:** MuFFLe++.
- Repo: `ps131-cell/muffle-plus-plus` (public, MIT).
- Hosted demo: `https://cancer-intelligence-platform.streamlit.app`. Streamlit's profanity filter
  rejects any subdomain containing "muff", so the demo can't use the project name.
- The Python package is `muffle` (`src/muffle`, version 0.1.0).

**What this project is:**
- **The bigger picture:** milestone 1 of a planned *multimodal, longitudinal cancer intelligence
  platform* for **breast cancer**. It is research and clinical decision support for qualified
  clinicians and researchers, never a diagnosis or a prescription.
- **What milestone 1 delivers:** an *evidence-linked patient profile*:
  - a multi-omic survival-risk model that copes with missing data layers;
  - observed driver mutations;
  - CIViC treatment evidence, "for clinician review";
  - literature leads.
- **How it is produced:**
  - A tool-calling **NVIDIA Nemotron** case agent on **Nebius Token Factory** writes the profile
    up as a tumor-board note.
  - The risk model is trained with **NVIDIA FLARE** federated learning across three simulated
    hospitals.
  - Risk updates along a patient timeline are evaluated on MSK-CHORD (local only) and shown on a
    hand-written, labeled synthetic patient.

**Primary objective (established):** a winning entry to the **Nebius × NVIDIA Global AI Hackathon
(Devpost)**.
- **Track and bonus:** "Best Apps and Agents", plus the "Best Use of Tavily" bonus ($3k; it needs
  a working runtime Tavily call).
- **Deadline:** **Fri Oct 30 2026, 10:00 am PT**. **Freeze:** Oct 28.
- **Hard requirements:** the table in `docs/HACKATHON.md`.
- **Judging:** stage one is pass/fail on real use of Token Factory and Nemotron. Stage two weighs
  four criteria equally: technological implementation, design ("a complete product, not a proof of
  concept"), potential impact, and quality of the idea. Judges may judge from the video and text
  alone.
- **Prizes:** a project can win one Overall or Track award plus one Bonus award. A "Most Valuable
  Feedback" prize also exists ($100 + swag, 10 winners), which is why `docs/submission.md` (PR #42)
  carries a feedback log.

**Strategic intent:** `docs/VISION.md`.
- **The platform:** connects specialized models, public datasets and each patient's record over
  time into one evidence-linked picture.
- **Core rule:** it keeps *observed* findings apart from *model inferences* and *hypotheses*.
- **Data:** it learns across institutions without centralizing data.
- **Scope boundary:** the hackathon build is the first, rigorously evaluated slice. The VISION
  table "Milestone 1 delivers vs Roadmap" is the scope boundary.
- **The pitch** (decision 2026-10-18): the platform's milestone 1, *not* a federated-learning
  project. Federation is one measured result.

**Current product direction:**
- **Milestone-1 pieces:**
  1. evidence labels in the note: done (#43);
  2. observed driver mutations and CIViC evidence: done (#46);
  3. MSK-CHORD 12-month risk updates: done (#48);
  4. synthetic timeline patient in the demo: done (#49);
  5. `docs/registry.md`: done (#52).

  All are merged (✅ git log).
- **What remains is product and submission work:**
  - the hosted demo (currently broken, see §2);
  - the freeze to-dos (labeled saved notes, bundle v2 with mutations and CIViC);
  - the README for judges;
  - the Devpost text;
  - the video;
  - the submission itself.
- **Roadmap, explicitly not hackathon scope:** pathology and radiology encoders, inferred mutation
  status, evolutionary hypotheses, resistance and treatment-strategy research, real institutions,
  differential privacy and secure aggregation.
- **Requested by the user but unscheduled:** a "pathologist workspace" UI (§4).

**Hard constraints:** all live in `CLAUDE.md` (Rules, Science rules, Data rules, Technical notes).
The ones with the biggest consequences:
- **Spending cap:** every Token Factory call goes through `src/muffle/report/budget.py`, with a
  hard **$25.50** cap. Never raise it or route around it.
- **What may be sent out:** only derived numbers and gene or mutation names may go to Token Factory
  or Tavily. Never raw omics, and **nothing from MSK-CHORD, including outputs of models trained on
  it**: the synthetic patient's timeline scores are excluded too (team decision 2026-10-19).
- **MSK-CHORD:** licensed CC BY-NC-ND 4.0, so it is **local only**. Publish only code and aggregate
  results. Never commit, host, show or send any MSK-CHORD patient or any MSK-CHORD-trained model.
- **Labels:**
  - every finding is labeled observed / model inference / hypothesis;
  - simulated hospitals and synthetic patients are labeled as such;
  - treatment content is "evidence for clinician review", never a recommendation.
- **Incomplete records:** every component must work when a layer is missing (masks;
  `tests/test_model.py`).
- **Never commit** `data/`, `outputs/`, `workspaces/`, `.csv/.tsv/.npz/.pt` files or `.env`.
- **Workflow and protocol:** branch `<area>/<topic>`, then a PR, then green CI. Tune on seeds
  95–99; report seeds 0–4.

**Project memory files:**
- `/Users/prakharsuryansh/PycharmProjects/muffle-plus-plus/CLAUDE.md`: the authoritative
  instruction file, checked in (✅ read in full this session).
- `AGENTS.md`, `.cursor/rules`, `.github/copilot-instructions.md`: **none found** (✅).
- Claude Code auto-memory (outside the repo, this Mac only):
  `/Users/prakharsuryansh/.claude/projects/-Users-prakharsuryansh-PycharmProjects-muffle-plus-plus/memory/`.
  It holds `MEMORY.md` plus 12 notes, all re-read this session. Their durable content is folded
  into this document so nothing depends on that folder (see Appendix A).

**Other authoritative documentation:**
| File | What it is |
|---|---|
| `docs/VISION.md` | Vision, guiding principles, milestone map |
| `docs/HACKATHON.md` | Requirements table (all boxes still `[ ]`), day plan, scope cuts, video outline |
| `docs/decisions.md` | Decision log, newest first: **the main record of why** (305 lines) |
| `docs/registry.md` | Every dataset, model and service: license, access tier, what is published (#52) |
| `docs/longitudinal.md` | MSK-CHORD task, aggregate results, synthetic-patient section, caveats |
| `docs/calibration.md` | Cross-site calibration and fairness tables (seed 0) |
| `docs/NEBIUS.md` | Untested Serverless Job notes; not used in the submission |
| `docs/CLAUDE_CODE_KICKOFF.md` | The original bootstrap prompt (historical) |
| `docs/plan/*.pdf` | Original research plan and project options |
| `SETUP.md`, `CONTRIBUTING.md` | Setup and how the team works. **Partly stale**, see §5. |
| `README.md` | Public front page; stale "(in progress)" markers fixed by open PR #53 |
| GitHub issues #4–#10, #12–#16 | Hackathon plan and requirement issues, all open |

---

### 2. WHAT EXISTS RIGHT NOW

#### Repository state (✅ all from `git`/`gh` this session)

**Main checkout:** `/Users/prakharsuryansh/PycharmProjects/muffle-plus-plus`, branch `main` at
**`9b6508f`**.
- I fast-forwarded it this session from `1a65189` with `git merge --ff-only origin/main`. There
  were no local changes and no branch switch.
- It now equals `origin/main`. The only untracked item is `.claude/`: `launch.json` and the
  `worktrees/` folder. Never commit it.

**`origin/main`:** `9b6508f`, "docs: registry of datasets, models and services with license,
access tier and what is published (#52)". The previous commits, newest first:

| Commit | PR | Change |
|---|---|---|
| `14b8f2a` | #49 | synthetic timeline patient whose 12-month risk is re-predicted at each event |
| `619058e` | #50 | read Streamlit Cloud secrets into the environment at startup |
| `c389248` | #48 | MSK-CHORD timelines and 12-month risk updates (local only) |
| `1a65189` | #46 | observed driver mutations (GDC open access) and CIViC treatment evidence |
| `cf5042c` | #45 | README agent section in the vision's terms |
| `4373e95` | #44 | hospitals labeled as simulated |
| `10a6658` | #43 | evidence labels in the case note |
| `6c27861` | #41 | the platform reframe |
| `ccccdc1` | #40 | spending-cap wording before going public |
| `85abc5a` | #39 | hosted bundle |
| `410ddc6` | #38 | demo redesign |
| `3518c3b` | #37 | Tavily |
| `3e9c23a` | #36 | Super/Ultra and the grounding check |

The full list goes back to `c3f1f50` (scaffold) via #1 and #19–#35.

**Remote:** `origin` → `https://github.com/ps131-cell/muffle-plus-plus.git` (no credentials in the
URL).

**Repository settings:**
- **Visibility and metadata:** public, MIT, homepage = the demo URL, 12 topics, created
  2026-10-17.
- **Merging:** auto-merge is **not allowed** (`allow_auto_merge: false`), and
  `delete_branch_on_merge` is false.
- **Collaborators:** the only one is `ps131-cell`.
- **Protection on `main`:** the required check is `tests`, admins are enforced, force pushes and
  deletions are blocked, and no review is required.
- **Local hook:** `.git/hooks/pre-push` also refuses any push to `refs/heads/main`.

**Worktrees** (all clean, ✅ `git status` in each):
| Path | Branch | Purpose / state |
|---|---|---|
| `.claude/worktrees/secrets` | `docs/continuation-handoff` | This handoff, PR #51 |
| `.claude/worktrees/vision` | `docs/readme-status` | PR #53 (README status). The milestone-1 session's working tree. |
| `.claude/worktrees/submission` | `docs/submission` | PR #42 (Devpost text draft) |
| `.claude/worktrees/video` | `docs/video-script` | PR #47 (video script draft) |
| `.claude/worktrees/eager-ardinghelli-4c9eb3` | `docs/review-decisions` | Leftover; merged as #30 |

**Local branches with no live upstream:** each one's tip equals the head of a **merged** PR, so
nothing is lost (✅ checked with `gh pr list --head`):
- `app/evidence-labels` = #43
- `data/driver-mutations-civic` = #46
- `data/msk-chord-risk-updates` = #48
- `docs/review-decisions` = #30
- `docs/vision-milestone-1` = #41
- `app/streamlit-secrets` = #50 (its remote branch still exists)
- `claude/eager-ardinghelli-4c9eb3` = `f64d19d`, which is an ancestor of `main`

**Unpushed commits:** none anywhere except this handoff branch, which is pushed in this session's
final step.

**Tags and releases:**
- `demo-bundle-v1` (tag on `ccccdc1`), release "Demo bundle v1": `demo_bundle.pt` (~850 KB, 40
  held-out cases). The hosted app downloads it, and the public download needs no token.

**Open PRs** (✅): all are mergeable (CLEAN) with the `tests` check green.
| PR | Branch | What | Merge rule |
|---|---|---|---|
| #53 | `docs/readme-status` | README roadmap boxes, data table and feature bullets match what is built; removes every "(in progress)" | README is submission material, so the **user reviews; don't self-merge** |
| #51 | `docs/continuation-handoff` | This handoff document (replaces the 18 Oct version) | Ask the user: an internal doc in a public, judged repo |
| #47 | `docs/video-script` | `docs/video.md`: script and shot list. Case 661 (PIK3CA H1047R + CIViC), backup case 710, still has an IN PROGRESS slot for the timeline | Submission material: user review |
| #42 | `docs/submission` | `docs/submission.md`: Devpost form text, 12-item feedback log, **9 IN PROGRESS markers** that can now mostly be resolved, since every milestone-1 piece is built | Submission material: user review |

**Open issues** (✅):
- #4 (Oct 22–24 plan), #5 (Oct 25–27 plan), #6 (freeze, video, public), #7 (submit).
- #8 (runs on Nebius), #9 (NVIDIA open model), #10 (track fit).
- #12 (README), #13 (demo URL through Dec 15), #14 (video), #15 (text + feedback), #16 (data
  terms; its title still mentions CHIMERA, which is not used).
- Several are de facto done: #8 and #9 (live agent), #12 partly.

#### Build and runtime status (✅ run this session on `9b6508f`)
- **Tests:** `make test` → **84 passed** in 12.5 s (Python 3.12.14 `.venv`).
- **Lint:** `make lint` (`ruff check src tests jobs scripts app`, the CI gate) → all checks
  passed.
- **Formatting:** `ruff format --check` would reformat **39 files**. This is *not* a CI gate. Don't
  format repo-wide (it would bury real diffs).
- **CI smoke test, reproduced locally** in a scratch folder, keys blanked so nothing could be
  spent:
  1. `make_synthetic --n-patients 300`.
  2. `jobs/fedavg_job.py --n-clients 2 --rounds 2 --local-epochs 1 --save …`: NVFlare 2.9.0 ran,
     ~20 s, and saved the model. `run.get_status()` prints `None`, which is normal.
  3. `python -m muffle.report.nemotron --agent …` → `mode=offline`, with the full tool trace and no
     ledger written.
- **CI on GitHub** (`.github/workflows/ci.yml`): Python 3.11 runs CPU torch, `ruff check`,
  `pytest -q` and the same smoke test. PR #51's previous push passed in 1m19s.
- **Local demo:** `preview_start demo-tcga` (port 8501) on the new code.
  - **All four tabs render, with 0 exceptions and no console errors.**
  - Patient timeline (synthetic): month-24 risk 60% (range 54–66%), diagnosis-only 33%, AUROC 0.93.
  - Case review lists 213 held-out patients.
  - Federation shows "213 held-out patients, 26 deaths".
  - Sidebar: held-out C-index **0.728**, case agent **live** (keys in `.env`), Tavily on.
  - Earlier this session :8501 was blocked by an orphaned Streamlit process; it was stopped and
    the preview restarted.
- **Hosted demo is BROKEN** (✅ loaded twice this session):
  - `https://cancer-intelligence-platform.streamlit.app/~/+/` renders the header and the timeline
    metrics, then fails with:
    ```
    AttributeError … File "/mount/src/muffle-plus-plus/app/streamlit_app.py", line 182
        st.altair_chart(charts.risk_timeline(updates[: i + 1], events, u["month"]), …
    ```
  - Because Streamlit stops the script at an uncaught exception, **the Case review, Federation and
    How it works tabs don't render at all.**
  - The sidebar says the case agent is "offline (no key)" and literature is "off (no Tavily key)".
  - Cause: see §5, "Known bugs".
- **Token Factory ledger** (`python -m muffle.report.budget`, ✅): **$0.4632 of $25.50** spent,
  286 calls:
  - Super $0.1287;
  - Ultra $0.3245;
  - recorded outside this code $0.01.
- **Not run this session:**
  - `make tcga`, `make fl-tcga`, `make experiment-tcga` (~1 h), `make calibration-tcga`,
    `make experiment-msk`, `make demo-timeline`, `make demo-bundle`;
  - any live Nemotron or Tavily call (deliberately, to save credit).

#### Implemented and working (merged; files ✅ read; behavior ⚠️ unless marked)
- **TCGA-BRCA cohort**
  - Built by `scripts/prepare_tcga.py` (logic in `muffle.data.tcga`) from open-tier UCSC Xena GDC
    hub files.
  - 1,064 patients and 148 deaths. Overall survival in months; one 01A primary tumor per patient.
  - Layers and sizes: copy number as "genomic" calls −2..2 relative to ploidy (200), STAR TPM RNA
    (1,000), 450K methylation as M-values (500, streamed and cached), RPPA protein (100), and
    clinical (8: age, stage, T, N, M1 flag, ductal, lobular, stage_unknown).
  - Top-variance features are ranked *before* z-scoring.
  - Per-patient `tss` (hospital code), `age`, `patient` barcode.
  - `mut_genes` / `mut_status` / `mut_changes`: a 16-gene driver panel from GDC's *masked*
    open-access WXS calls, 943/1,064 sequenced. NaN means not sequenced, never wild type.
- **Model** (`muffle.models.fusion.MuffleNet`):
  - Per-layer MLP encoders (LayerNorm, so plain FedAvg works) and a mask-aware fusion.
  - TCGA uses `fusion: additive`: one Cox head per layer, summed over present layers, plus a
    learned offset per missing layer.
  - Modality dropout of 0.8 that never drops `always_keep: [clinical]`.
  - Optional `residual_scale` (λ) for the clinical-anchored residual model (`muffle.residual`):
    train the clinical anchor first, freeze it, train the omic heads on top, then pick
    λ ∈ {0, ¼, ½, ¾, 1} on **site-held-out** inner splits.
- **Federated learning** (`jobs/fedavg_job.py`, `src/muffle/fl/client.py`):
  - NVFlare Recipe API: `FedAvgRecipe` + `SimEnv`.
  - 3 simulated hospitals made of whole tissue source sites (355/355/354 patients; 68/56/24
    deaths).
  - `make fl-tcga` runs 20 anchor + 20 residual rounds. λ is chosen by federated evaluation, in
    which each client shares only two pair counts per λ. The result is
    `outputs/tcga_fedavg.pt` (λ = 0.25).
- **Experiments** (`python -m muffle.experiment`):
  - Per-site validation splits and leave-one-site-out (LOSO); methods centralized, local-only,
    FedAvg, single-modality, residual and FedAvg-residual.
  - **Reported LOSO results, seeds 0–4** (site-stratified pooled C-index, from
    `app/results_tcga_brca.json`, ✅ read):
    | Method | C-index |
    |---|---|
    | FedAvg-residual | 0.693 ± 0.017 |
    | FedAvg | 0.680 ± 0.008 |
    | Pooled residual | 0.700 ± 0.012 |
    | Pooled fusion | 0.692 ± 0.026 |
    | One hospital alone | 0.649 ± 0.032 |
    | **Clinical only** | **0.702 ± 0.004** |
    | RNA only | 0.610 |
    | Methylation only | 0.599 |
    | Protein only | 0.574 |
    | Copy number only | **0.485** (below chance: site/batch effects) |
- **Calibration and fairness** (`muffle.calibration`, `docs/calibration.md`, seed 0):
  - Calibrated within about 2 points at 3 years.
  - The Brier score barely beats Kaplan–Meier, so the product talks in percentiles and groups.
  - Weaker for patients under 50 and within stage II.
- **Case agent** (`src/muffle/report/`):
  - **Plan:** Nemotron 3 Super (`nvidia/nemotron-3-super-120b-a12b`) plans tool calls. It gets up
    to 6 turns and 4 calls per turn at 900 tokens each, a one-time search reminder, and one extra
    search-only turn.
  - **Write:** Nemotron 3 Ultra (`nvidia/Nemotron-3-Ultra-550b-a55b`, 4,096 max tokens) writes the
    note. A cut-off or failed Ultra reply falls back to Super.
  - **Check:** `grounding.check_note` (no LLM) flags numbers, gene-like tokens and URLs that no
    tool returned. It allows one rewrite and shows anything left.
  - **Fallbacks:** any API error (400, 401, 402, 403, 429, 5xx, timeout) or a budget refusal
    produces the offline template note, with the reason.
  - **Tools** (`case_tools.CaseTools`; each result carries an `evidence_type`):
    | Tool | Evidence type | Returns |
    |---|---|---|
    | `observed_findings` | observed | layers measured and missing, recorded stage, age band, sequenced drivers |
    | `predict_risk` | model inference | log-risk, whole percentile, tertile group, the C-index as uncertainty |
    | `modality_contributions` | model inference | per layer, vs a typical patient (cohort offsets) |
    | `top_features` | model inference | gradient × input; zero scores dropped |
    | `treatment_evidence` | hypothesis | CIViC; only when an evidence function is passed and the patient has sequenced drivers |
    | `search_literature` | hypothesis | Tavily, one query per gene, at most 3; only genes `top_features` returned; scholarly-domain allowlist; result must name the gene and a cancer |
  - **Note format:** Summary / Observed / Model inferences / Hypotheses and evidence / Caveats, with
    every bullet labeled.
  - **Unit tests:** 23 agent tests, 7 budget tests and 3 grounding tests, all with fakes (✅).
- **Spending cap** (`budget.py`):
  - Reserves the worst case before sending: input estimated at 2 characters per token, plus the
    full `max_tokens`.
  - Settles to the real cost afterwards, under a file lock. The ledger is
    `~/.muffle/token_factory_spend.json`, overridable with `MUFFLE_SPEND_LEDGER`.
  - Prices: Super $0.30/$0.90 and Ultra $1/$3 per 1M tokens. Unknown models are charged
    $3/$9.
  - `TOKEN_FACTORY_BUDGET_USD` can only lower the cap.
- **Demo app** (`app/streamlit_app.py`, `app/charts.py`, `muffle.demo`). Four tabs:
  1. **Patient timeline (synthetic):** from `app/timeline_synthetic.json`.
  2. **Case review:** the 213 held-out patients, or the bundle's 40.
  3. **Federation.**
  4. **How it works.**
  - Live notes are capped per session (`DEMO_LIVE_NOTES_PER_SESSION`, default 5). The 8 saved
    notes show without a key.
  - Hosted mode loads the release bundle with `torch.load(weights_only=True)`.
  - `secrets_to_env()` copies Streamlit secrets into the environment.
- **MSK-CHORD longitudinal evaluation** (`muffle.longitudinal`, `scripts/prepare_msk_chord.py`,
  `docs/longitudinal.md`):
  - 5,368 breast patients, with time 0 at the first tumor sequencing.
  - Landmarks at 0, 6, 12 and 24 months; outcome: progression (NLP-derived) or death in the next
    12 months.
  - Model: `HistGradientBoostingClassifier(max_depth=3)`, untuned, record-so-far vs
    diagnosis-only, seeds 0–4.
  - AUROC 0.880 / 0.912 / 0.928 / 0.931 vs 0.663–0.706 for diagnosis-only; Brier roughly halved.
- **Synthetic timeline patient** (`muffle.timeline`, `scripts/make_timeline_patient.py`,
  `make demo-timeline`):
  - SYNTHETIC-001 is hand-written: 16 events from diagnosis at month −40 to month 24, with
    PIK3CA H1047R at month 0 and a liver progression at month 12.
  - At each event from month 0 it is scored by that landmark's five seed models (mean and range)
    next to the diagnosis-only baseline.
  - Changes are attributed one feature group at a time, plus "month-L model takes over" and
    "interactions".
  - Only this synthetic patient's scores, the aggregate metrics and 3 CIViC items are committed.
    The models stay local.
  - ✅ scores read from the JSON:
    | Month | Risk |
    |---|---|
    | 0 | 38% |
    | 1 | 52% |
    | 4 | 50% |
    | 7 | 24% |
    | 11 | 37% |
    | 12 | 88% |
    | 13 | 78% |
    | 16 | 62% |
    | 19 | 46% |
    | 24 | 60% |
- **Registry** (`docs/registry.md`): datasets, models, services, software licenses, and
  candidates not used (✅ read).

#### Partially implemented
- **Hosted demo:**
  - broken (above);
  - live agent off because the keys aren't in the Streamlit secrets;
  - bundle v1 predates #46, so hosted cases have `mutations=None` ("not sequenced");
  - **no CIViC on the hosted app at all:** the app sets
    `EVIDENCE = civic.evidence if civic.load_table(download=False) is not None else None`, and the
    hosted container has no cached CIViC TSV.
- **Saved notes** (`app/saved_notes.json`, ✅ inspected):
  - 8 notes (cases 47, 299, 545, 563, 564, 601, 730, 1043), all from 2026-10-18 and all written by
    Ultra with 0 grounding issues.
  - **All are in the old format:** sections Summary / Drivers / Caveats / Literature, **no
    [Observed] / [Model inference] / [Hypothesis] labels**, and no `observed_findings` or CIViC
    tools.
- **`scripts/save_demo_notes.py`** calls `demo.tools(case, search)` **without an `evidence`
  function**. Regenerating notes with `make demo-notes` would therefore still produce notes with
  no CIViC evidence. `_agent_cli` (`make agent-tcga`) does pass `civic.evidence`.
- **App text lagging behind the code:**
  - The "How it works" tab says Ultra writes "(Summary, Drivers, Caveats, Literature)", which is
    stale.
  - It says nothing about the timeline, CIViC or the evidence labels.
  - The page title and header still read "federated tumor-board assistant", the pre-platform
    framing.
- **README:** still has "(in progress)" markers and unchecked roadmap boxes on `main`. PR #53
  fixes this and waits for the user.
- **`docs/HACKATHON.md`:** every requirement box is still `[ ]`.
- **#42 and #47:** the IN PROGRESS markers predate #49 and #52; the parts they mark are now built.

#### Broken or blocked
1. **Hosted demo crash** (✅): an `AttributeError` at `charts.risk_timeline`. Most tabs are
   unusable for judges. See §5 for the cause and fixes.
2. **CIViC lookup misses the strongest evidence** (✅ reproduced against the cached CIViC TSV).
   - `civic.evidence("PIK3CA", "H1047R")` returns only the level C item (fulvestrant +
     everolimus) and level D items (izorlisib, pictilisib).
   - It misses **level A fulvestrant + alpelisib**, which CIViC files under the compound profile
     "PIK3CA H1047R OR PIK3CA H1047Y OR PIK3CA H1047L".
   - It also misses the level-A gene-level "PIK3CA Mutation" item, which is cut by `k=3` because
     exact-variant matches are listed first.
   - This is what the demo's timeline tab and the planned video case 661 show.
3. **Hosted live agent:** blocked on the user adding `NEBIUS_API_KEY` and `TAVILY_API_KEY` in
   Streamlit Cloud → app → Settings → Secrets (root level, exact names). Claude must not type keys.
   The secrets already hold `TOKEN_FACTORY_BUDGET_USD = "3"` and
   `DEMO_LIVE_NOTES_PER_SESSION = "5"` (⚠️ memory note).
4. **Environment limits:**
   - About 4.1 GiB of disk free (98% used, ✅).
   - An M1 Mac with 8 GB of RAM (⚠️).
   - The Claude plan is at 90% of its weekly limit (resets 2026-10-20 12:00 UTC), with extra
     usage enabled ($10.60 of $40 spent); the 5-hour window was at 21% (✅ `get_usage`).

#### Not started
- **Freeze to-dos:**
  - fix the CIViC matching, pass `civic.evidence` in `save_demo_notes.py`, run `make demo-notes`
    (8 labeled notes, about $0.12);
  - `make demo-bundle` with mutations, plus CIViC for the hosted app (ship the needed rows, or
    allow the CC0 download);
  - publish release `demo-bundle-v2` and point `BUNDLE_URL` in `app/streamlit_app.py` at it (it
    still reads `…/demo-bundle-v1/demo_bundle.pt`).
- **Final submission work:**
  - the README for judges (after #53) with the final numbers and URL;
  - resolve #42's and #47's IN PROGRESS markers;
  - record the video (≤ 3 min, public YouTube);
  - the Devpost submission (issues #6, #7, #12–#15).
- **Timeline narration by Nemotron:** optional and **not planned**. If ever built, it may use only
  the synthetic events, never the scores (decision 2026-10-19).
- **The pathologist workspace** (§4).
- **The PFI endpoint:** only a time-boxed check, after the submission requirements are done.

#### Current user experience (✅ local; hosted noted)
- **Patient timeline (synthetic):**
  - A yellow "SYNTHETIC-001 is synthetic" banner.
  - A slider over the record ("month −40 · Diagnosis" … "month 24 · Clinic visit"). The latest
    observed event is shown.
  - Metrics: 12-month risk with its change in points, the range over the 5 models, the
    diagnosis-only baseline, and the model's AUROC.
  - A risk-over-time chart with a band, and a dashed line for diagnosis only.
  - **Observed** list (diagnosis, drivers, sequenced-not-found genes, metastatic sites,
    progressions, CA 15-3, CEA, ECOG, treatments).
  - **Model inference · what changed and why**: a sentence plus a points bar chart.
  - **Hypotheses and evidence · for clinician review**: CIViC items with citation links.
  - An event-log expander.
  - Hosted, this tab crashes at the chart.
- **Case review:**
  - Pick a held-out patient (★ = saved note). The tab shows the risk percentile, group, simulated
    hospital and layers present; a histogram of the cohort with the patient marked; and per-layer
    contributions vs a typical patient.
  - A "what if a layer were missing" expander re-scores with layers hidden.
  - **Tumor-board note:** "Write the note with Nemotron" streams the agent's steps, then shows the
    note, the grounding result, a Markdown download and an expandable tool trace. "Show the saved
    note" shows the stored one instead.
- **Federation:** a Graphviz diagram of 3 simulated hospitals and the FLARE server; a per-site
  table with data-coverage bars; the LOSO results chart with three plain-language bullets;
  single-layer results; KM curves of held-out risk groups to 5 years; the per-site C-index.
- **How it works:** the method, privacy and limits. Its section list is stale.
- **The experience stops at** demo depth. There is no patient upload or search, no imaging, and no
  real timeline for TCGA patients.

#### Data and state
- **Cohort file** `data/tcga_brca/cohort.npz`: keys `x_<layer>`, `names_<layer>`, `mask[N,5]`
  (order genomic, rna, methylation, protein, clinical), `time`, `event`, `stage`, `tss`, `age`,
  `patient`, `mut_genes`, `mut_status`, `mut_changes`. Full format in the docstring of
  `scripts/prepare_tcga.py`.
- **Site files:** `data/tcga_brca/clients_3_site_nogaps/site-{1,2,3}.npz`. `site_files` reuses
  these when present; `prepare_tcga.py` deletes stale `clients_*` folders.
- **Configs:**
  - `configs/default.yaml` (synthetic): sizes 200/1000/500/100/8; concat fusion; modality dropout
    0.15; 40 epochs; 2 local epochs; `val_fraction` 0.2; seed 0.
  - `configs/tcga_brca.yaml` overrides it with `base: default.yaml`: hidden 64, latent 16, head
    16, dropout 0.5, additive fusion, modality dropout 0.8, `always_keep [clinical]`, weight decay
    1e-2, 20 epochs, `fl.rounds` 20, `partition: site`, `simulate_gaps: false`.
- **Checkpoints:** a dict `{"model": state_dict, "config": cfg}`. A raw NVFlare
  `FL_global_model.pt` has no config.
- **Demo bundle** (`BUNDLE_FORMAT = ("muffle-demo-bundle", 1)`):
  - weights and cfg;
  - for 40 cases: inputs `x`, `mask`, and `Case` dicts (index, site, log_risk, percentile, group,
    age, stage, layers, missing, mutations);
  - 1,064 cohort risks, offsets, feature names, per-site C-index, sites, KM curves, held-out
    counts.
  - It holds no survival times.
- **Committed derived files:**
  - `app/results_tcga_brca.json` (aggregates);
  - `app/saved_notes.json` (notes and traces: derived numbers, gene names, links);
  - `app/timeline_synthetic.json` (synthetic only).
- **Spend ledger:** `~/.muffle/token_factory_spend.json`.

---

### 3. ARCHITECTURE & TECHNICAL MAP

#### Technology stack
- **Python:** 3.12.14 locally, via `uv` in `~/.local/bin`. The system `python3` is 3.9.4, which is
  too old. CI uses 3.11; ruff targets py310.
- **Installed versions** (✅ `.venv`): torch 2.14.1, nvflare 2.9.0, numpy 2.5.4, pandas 2.3.3,
  scikit-learn 1.9.1, scikit-survival 0.28.0, lifelines 0.30.3, streamlit 1.66.0, altair 6.3.0,
  openai 3.34.0, tavily-python 0.8.5, pytest 9.1.1, ruff 0.17.1.
- **Hosted install** (`app/requirements.txt`): CPU torch 2.14.1, streamlit 1.66.0, altair, numpy,
  pandas, pyyaml, openai, tavily-python, python-dotenv. **No NVFlare.**
- **AI services:** Nebius Token Factory (OpenAI-compatible, base URL
  `https://api.tokenfactory.nebius.com/v1`); Nemotron 3 Super (planner) and Nemotron 3 Ultra
  (writer); Tavily search.
- **Hosting:** Streamlit Community Cloud (Python 3.12), plus GitHub Releases for the bundle.
- **Tooling:** GitHub Actions, `gh` CLI (in `~/.local/bin`; there is no Homebrew), ruff, pytest,
  nbstripout.

#### Repository structure
| Path | Responsibility |
|---|---|
| `src/muffle/config.py` | `MODALITIES` order (genomic, rna, methylation, protein, clinical); `load_config` with `base:` merge; `DATA_DEFAULTS` |
| `src/muffle/data/tcga.py` | Xena download/stream, 01A selection, per-layer transforms, clinical parsing, `driver_mutations`, `assemble_cohort`, `build_cohort` |
| `src/muffle/data/dataset.py` | `MultiOmicDataset` (keeps the first d features), `split_positions`, `feature_names` |
| `src/muffle/data/partition.py` | `split_by_group` (whole sites, balanced), stage-skew/iid modes, `partition_cohort` → `site-k.npz` |
| `src/muffle/data/preprocess.py`, `synthetic.py` | z-score, M-values, top variance, `harmonize_features` (unused); synthetic cohort |
| `src/muffle/models/fusion.py` | `MLPEncoder`, `MuffleNet` (concat or additive fusion, modality dropout, `always_keep`, `residual_scale`) |
| `src/muffle/losses.py`, `metrics.py`, `engine.py` | Cox partial likelihood (whole batch, Breslow ties), Harrell C and site-stratified C, `train_epochs` (AdamW, clip 5, optional FedProx), full-set `evaluate` |
| `src/muffle/residual.py` | `MaskedView`, `inner_split` (whole sites), `two_stage`, `fit_residual`, `federated_lambda` |
| `src/muffle/train_local.py` | `site_files`/`client_dir`, `heldout_c_index`, `fit`, `load_model`, the centralized/local CLI |
| `src/muffle/experiment.py` | Seeds, LOSO, runs the NVFlare job as a subprocess, `summarize` → `outputs/experiments/*.json` |
| `src/muffle/calibration.py` | Cross-site predictions, Breslow, time-dependent AUC/Brier, calibration and slice tables |
| `src/muffle/explain.py` | `masked_effects`, `cohort_offsets`, `modality_contributions`, `top_features`, percentile, tertile group |
| `src/muffle/report/nemotron.py` | Agent loop, writer, rewrite, offline template, `tavily_search`, CLI (`--agent`, `--list-models`) |
| `src/muffle/report/case_tools.py` | `CaseTools` tool specs and implementations, `observed_facts`, `age_band`, `parse_arguments` |
| `src/muffle/report/grounding.py` | `check_note`, `describe` |
| `src/muffle/report/budget.py` | `HARD_CAP_USD`, `PRICES_PER_M`, `Ledger`, `BudgetedClient`, CLI |
| `src/muffle/report/civic.py` | CIViC nightly TSV loader (cached in `data/raw/civic/`) and `evidence()` |
| `src/muffle/demo.py` | `Case`, `Site`, `Demo`, `build_demo`, `pick_cases`, `subset`, `save/load/fetch_bundle`, KM curves |
| `src/muffle/longitudinal.py` | MSK-CHORD `load`, `features`, `landmark`, `evaluate(keep_models=)`, `markdown` |
| `src/muffle/timeline.py` | SYNTHETIC-001 `EVENTS`, `tables`, `observed`, `build`, `_attribute`, `summary` |
| `src/muffle/fl/client.py` | NVFlare Client API script: evaluate the global model on local val, train, send weights; `--residual-from` two-phase |
| `jobs/fedavg_job.py` | `FedAvgRecipe` + `SimEnv`; `--residual` doubles the rounds; `--save` picks λ and stores the cfg |
| `app/streamlit_app.py`, `app/charts.py` | UI; Altair charts (`risk_position`, `contributions`, `results`, `survival_by_group`, `risk_timeline`) |
| `scripts/` | `prepare_tcga.py`, `prepare_msk_chord.py`, `make_synthetic.py`, `export_results.py`, `make_demo_bundle.py`, `save_demo_notes.py`, `make_timeline_patient.py` |
| `tests/` | 15 modules and 84 tests; `conftest.py` redirects the spend ledger to tmp and clears `TOKEN_FACTORY_BUDGET_USD` |
| `.github/` | CI, PR template, task issue template, CODEOWNERS (placeholder owners) |
| `.streamlit/config.toml` | Theme, headless, no usage stats |
| `Dockerfile`, `docs/NEBIUS.md` | GPU image and Serverless Job notes; untested, not in the submission |

#### End-to-end execution flow
1. **Cohort.** `make tcga` → `prepare_tcga.py` → `tcga.build_cohort`:
   - download survival, clinical, gene map, copy number, RNA, protein and mutations into
     `data/raw/tcga_brca`;
   - stream methylation (about 3 GB), caching only the top 500 CpGs as a `.pkl`;
   - per layer: drop sparse features, select top variance, transform;
   - assemble patients with survival, clinical data and ≥ 1 omic layer → `cohort.npz`.
2. **Hospitals.** `site_files` partitions by `tss` into 3 clients, with real modality gaps:
   methylation covers about 72% of patients, protein about 80%.
3. **Federated training.** `make fl-tcga` → `fedavg_job.py --residual`:
   - NVFlare `SimEnv` runs 3 client threads. Each round a client evaluates the global model on its
     validation split, trains `local_epochs` (anchor-only before round 20, residual after, with the
     anchor frozen) and sends weights.
   - FedAvg aggregates them.
   - After 40 rounds `--save` runs `federated_lambda` and writes `outputs/tcga_fedavg.pt` with the
     cfg (`residual_scale` 0.25).
4. **Evaluation.**
   - `python -m muffle.experiment … --loso` → `outputs/experiments/*.json`; `make demo-results` →
     `app/results_tcga_brca.json`.
   - `make calibration-tcga` → `outputs/calibration/` (tables copied into `docs/calibration.md`).
5. **Demo build.** `build_demo` loads the checkpoint and site files, scores every patient (the
   cohort risks), keeps each site's validation split (213 patients), and computes cohort offsets,
   per-site held-out C-index and KM curves. `make demo-bundle` subsets it to 40 cases → bundle →
   GitHub release.
6. **Agent.** `run_case_agent(CaseTools)`:
   1. Super gets the case header and tool specs, and calls tools until it replies DONE, with turn
      caps and the search reminder.
   2. If `predict_risk` never ran, the fixed plan is appended.
   3. `_write`: the writer gets the case header and the tool outputs, minus `note`, `log_risk` and
      `cohort_median_log_risk`.
   4. `check_note`, then one rewrite if there are issues.
   5. The result is a `CaseReport` (text, trace, mode, models, tokens, notes, issues, revised).
   6. Every completion goes through `BudgetedClient`.
7. **App.**
   1. `secrets_to_env()`, then `load()` (full data if the checkpoint and cohort exist, else the
      bundle).
   2. `LIVE` = `NEBIUS_API_KEY` set; `SEARCH` = `TAVILY_API_KEY` set; `EVIDENCE` = CIViC TSV
      cached.
   3. Render the four tabs; live notes are counted per session.
8. **Longitudinal (local only).**
   - `make msk-chord` (47 MB tarball → `data/raw/msk_chord/extract/msk_chord_2024`), then
     `make experiment-msk` → `outputs/msk_chord/risk_updates.{json,md}`.
   - `make demo-timeline` refits the landmark models (`keep_models=True`), scores SYNTHETIC-001
     and writes `app/timeline_synthetic.json`, with CIViC from the cached TSV.

#### AI and model architecture
- **Implemented:** above. Design choices worth knowing:
  - the planner never writes;
  - the writer never sees log-risk, whose sign misled earlier notes;
  - the grounding check is deterministic code, so "every claim traces to a tool" can be shown in
    the UI;
  - the tools refuse searches on genes that `top_features` didn't return;
  - clinical features can't be searched.
- **Model selection:** follows the track text, which says to use Ultra for serious reasoning and
  Nano or Super for fast everyday calls. Five Nemotron ids are available on the key: 3 Nano
  30B-A3B, 3 Super 120B-A12B, 3 Ultra 550B, 3.5 Lightning, 3.5 Super VL (⚠️ Oct 18 listing).
- **Cost per note:** about $0.01 with Ultra (about $0.003 with Super alone), 7–10 s (⚠️ decisions
  log).
- **Not implemented / planned:** Nano; narration of the timeline; inferred mutation status;
  imaging encoders.

#### External dependencies and configuration
- **Environment variables** (names only):
  | Variable | Purpose |
  |---|---|
  | `NEBIUS_API_KEY` | Live agent |
  | `TOKEN_FACTORY_BASE_URL` | Default URL above |
  | `NEMOTRON_MODEL` | Planner; default Super |
  | `NEMOTRON_WRITER_MODEL` | Writer; default Ultra. **Not in `.env.example`.** |
  | `TOKEN_FACTORY_BUDGET_USD` | Lower the cap |
  | `MUFFLE_SPEND_LEDGER` | Ledger path |
  | `TAVILY_API_KEY` | Literature search |
  | `DEMO_LIVE_NOTES_PER_SESSION` | Per-session live cap |
  | `MUFFLE_BUNDLE` | Bundle path or URL |
  | `GITHUB_TOKEN` | Only for a private release |
  | `DATA_DIR`, `OUTPUT_DIR` | Declared but unused |
  | `NEBIUS_BUCKET`, `AWS_*` | Unused |
- **Where values live:**
  - Locally: `.env` (git-ignored). It currently sets `NEBIUS_API_KEY`, `TOKEN_FACTORY_BASE_URL`,
    `NEMOTRON_MODEL`, `TAVILY_API_KEY` and the unused ones (✅ names only).
  - Hosted: Streamlit Cloud secrets, top-level keys.
- **External data endpoints:**
  - UCSC Xena GDC hub (`https://gdc-hub.s3.us-east-1.amazonaws.com/download/…`);
  - cBioPortal datahub (`https://datahub.assets.cbioportal.org/msk_chord_2024.tar.gz`);
  - CIViC nightly TSV (`https://civicdb.org/downloads/nightly/nightly-ClinicalEvidenceSummaries.tsv`);
  - the GitHub release asset.

#### Commands that matter
```bash
make setup PY=python3.12          # .venv (pip torch on macOS) + requirements-dev + editable muffle
make test                         # pytest -q  (84 tests, ~13 s)
make lint                         # ruff check src tests jobs scripts app  (CI gate)
make tcga                         # data/tcga_brca/cohort.npz (~0.4 GB download + ~3 GB stream)
make fl-tcga                      # FedAvg-residual demo model -> outputs/tcga_fedavg.pt
make experiment-tcga              # 5 seeds + LOSO (README says ~15 min; residual runs took ~1 h)
make calibration-tcga             # ~8 min
make agent-tcga PATIENT=661       # one case note in the terminal (live if NEBIUS_API_KEY is set; spends credit)
make demo-tcga                    # full-data demo :8501  (or preview_start name "demo-tcga")
make demo-notes                   # LIVE agent on 8 cases -> app/saved_notes.json (~$0.12; see §5 CIViC gap)
make demo-results                 # app/results_tcga_brca.json from outputs/experiments
make demo-bundle                  # outputs/demo_bundle.pt (40 cases)
make demo-hosted                  # run the app from the bundle only
make msk-chord && make experiment-msk && make demo-timeline   # local-only MSK-CHORD pipeline
.venv/bin/python -m muffle.report.budget [--add USD]          # spend status / record outside spend
gh release upload demo-bundle-v1 outputs/demo_bundle.pt --clobber   # documented; prefer a new tag v2
# in a worktree, test the worktree's code (the .venv's editable install points at the main folder):
PYTHONPATH=src ../../../.venv/bin/python -m pytest -q
```

#### Configuration and environment differences
| | Local | Hosted |
|---|---|---|
| Data | Full data (213 held-out cases) | Bundle (40 cases), no NVFlare |
| Ledger | Persistent in `~/.muffle` | Resets on every container restart, hence the low `TOKEN_FACTORY_BUDGET_USD = 3` there |
| CIViC table | Cached | Absent |
| Mutations | In the data | Absent from bundle v1 |
| Secrets | `.env` | Streamlit secrets |

#### Naming and coding conventions
- **Branches:** `<area>/<topic>`. **Commits:** `<area>: <change>`, with areas
  data/model/fl/eval/app/infra/docs.
- **Merging:** squash-merge; the PR number lands in the title. Trailers:
  `Co-Authored-By: Claude …` on commits, "🤖 Generated with Claude Code" in PR bodies.
- **Commit email:** the repo-local `git config user.email` is the GitHub noreply address.
- **Code style:** line length 100; ruff lint rules E, F, B; type hints; `from __future__ import
  annotations`.
- **Docstrings** explain *why*, with numbers.
- **Tool outputs:** `evidence_type` on every result. Contribution key `log_risk_added_by_layer`;
  the old `delta_log_risk_when_removed` read backwards and was removed.
- **Decision log entries:** "date — title" with What / Why / Result / Consequence.
- **Prose:** plain, specific, with numbers and their uncertainty; never "≫".
- **Tests:** fakes for Token Factory and Tavily, tiny synthetic cohorts, no network, no real
  data.

#### Security and privacy boundaries
- **Trust boundary:** this Mac (raw TCGA and MSK-CHORD data, checkpoints, `.env`) vs everything
  sent out:
  - Token Factory: derived numbers and names only, built by `case_tools`;
  - Tavily: gene + "breast cancer" query strings;
  - GitHub: code, aggregate JSON, the release bundle with 40 cases' processed TCGA open-tier
    features;
  - Streamlit Cloud: the public repo plus the bundle.
- **Bundle safety:** the bundle loads with `weights_only=True`, so a tampered release can't run
  code. Local checkpoints use `weights_only=False`, which is fine because they are only trusted
  local files.
- **Error messages:** `unavailable()` reports only the HTTP status or error type, never the
  request (which carries the key).
- **Tavily key:** it was once pasted into a chat. Suggest the user regenerate it (⚠️).
- **Older commits** carry a personal (non-noreply) email; the user chose not to rewrite history.

---

### 4. RECENT WORK AND DECISION HISTORY

#### This session (✅), Oct 18 22:23 → Oct 19 ~01:10 CDT
1. **First pass** (user request: a continuation document plus a resume prompt):
   - inspected the repo and wrote `docs/AI_Continuation_Document-18Oct2026-2231.md`;
   - opened PR #51 (CI passed).
2. **User interrupt:** the `demo-tcga` preview failed with "Port 8501 is not available".
   - Found an orphaned Streamlit process with the same command, started about 41 minutes earlier
     through the Claude app's helper and owned by no running session.
   - Stopped it with SIGTERM and restarted the preview.
   - **Decision:** stop the orphan rather than change the port, since every config assumes 8501.
3. **Second pass** (user request: redo the document in depth, re-read everything, make sure
   everything is on GitHub):
   - Re-fetched and found that #49 and #52 had merged and #53 was open, all from the "Milestone 1
     resume" session.
   - Re-read every memory note, doc, source file, script, test and config.
   - Verified that every local branch is either pushed or identical to a merged PR head.
   - Fast-forwarded the main folder to `9b6508f`.
   - Ran tests (84 pass), lint (clean), and the CI smoke test offline (pass).
   - Checked both demos: local healthy, **hosted broken**.
   - Found the CIViC matching gap, the CIViC gap in `save_demo_notes.py`, and the stale "How it
     works" text.
   - Replaced the 18 Oct document with this one.
4. **No product code was changed in this session.** I deliberately didn't fix the bugs above:
   the request was a handoff, and fixes to what judges see (demo, notes) need the user's go-ahead
   on priority.

#### Earlier sessions, most recent first (⚠️ git log, `docs/decisions.md`, memory notes)
- **Oct 19, ~05:45 UTC ("Milestone 1 resume" session):**
  - merged #49 (timeline) and #52 (registry);
  - opened #53 (README status; "don't merge, the user is reviewing");
  - the user decided that MSK-CHORD-model outputs never go to Token Factory (decisions.md +
    `CLAUDE.md`).
- **Oct 19, ~03:00 UTC:** deployed on Streamlit Cloud. #50 made the secrets readable. Live mode
  was never confirmed, and is confirmed off now.
- **Oct 18–19:**
  - #48 MSK-CHORD; #46 mutations + CIViC; #45 README agent section; #44 simulated labels; #43
    evidence labels.
  - **#41: the platform reframe**, chosen by the user: breast cancer; MSK-CHORD local-only; a
    12-month progression-or-death task re-predicted at each event; a synthetic demo patient. It
    replaced the "lead with federation" pitch.
- **Oct 18:**
  - #39 and #40: the hosted bundle and slim requirements. The repo went public after a pre-public
    audit (no secrets or data in history, issues or PRs), and `main` was protected (#17, #11
    closed).
  - #36–#38: Super/Ultra and grounding; live Tavily; the demo redesign with cohort offsets.
  - #32–#34: the cap; percentile wording; the offline fallback.
  - #31: calibration.
  - #29: the residual model (closes #25).
  - #27: always keep clinical; 20 FL rounds.
  - #26: hospital split and LOSO.
- **Oct 16–17:**
  - #24: TCGA loader. #23: agent built offline. #19: held-out C-index in the demo (#18).
  - #20, #22: scope decisions.
  - #1: local bring-up. Scaffold `c3f1f50`.

#### Decisions and rationale
Full text in `docs/decisions.md`. These are the ones most likely to be undone by mistake:
| Decision | Why | Alternatives rejected |
|---|---|---|
| **Pitch = platform milestone 1**; federation is one result | The team's vision; judges reward a complete product | "Lead with federation" (old pitch) |
| **State plainly that clinical-only wins** (0.702 vs 0.693/0.700) on BRCA overall survival; never write "≫ alone" (+0.044 over local-only is ~1.4 local-only sd) | Honesty; the numbers support only "FL ≈ pooled, beats alone" | Claiming the omics add signal |
| **Additive fusion; clinical never dropped; modality dropout 0.8** | Tuning seeds: additive 0.718 vs concat 0.672; keeping clinical 0.684 vs 0.658 | Concat; dropping clinical |
| **Clinical-anchored residual, λ picked on whole-site inner splits** (federated: pair counts only) | Random-patient splits gave λ ≈ 0.4, which didn't transfer to new hospitals (batch effects) | Plain fusion; patient-level inner splits |
| **FedAvg scored with the final global model** | NVFlare picks `best_FL_global_model.pt` on the same validation splits, so it is optimistic | "Best" model |
| **Report mean ± sd over seeds; LOSO as the headline** | Per-site validation sets are small (26–94); LOSO has ~4× smaller error bars | Single runs |
| **Contributions vs a typical patient** (cohort offsets) | Masking shifted everyone −0.08 to −0.18; 17% of high-risk patients showed every layer "lowering" risk | Raw masked effect |
| **Super plans, Ultra writes, deterministic grounding check** | Track guidance; verifiability shown in the UI | One model; LLM-judged grounding |
| **Hard $25.50 cap with worst-case reservation** | The account auto-charges a card when credit runs out; free credits only | Trusting the console |
| **Token Factory only; FL in the simulator** | No paid Nebius compute | Serverless Job (conditional on credits) |
| **NVFlare, not Flower; reject the broad `MUFFLE_SPEC`** | NVIDIA's own FL SDK; the spec was weeks of GPU work with gated models | Flower + DP/SecAgg, foundation models |
| **Hosted = weights + 40 cases, release asset, `weights_only` load** | Minimal patient-level exposure; the repo bans `.pt` | Hosting the cohort; Nebius endpoint |
| **MSK-CHORD local, aggregates only; its model outputs never go to an LLM** | CC BY-NC-ND; sharing models or outputs could count as adapted material | Narrating timeline scores |
| **Breast cancer** | TCGA-BRCA has ~1,060 multi-omic patients vs ~48 for lymphoma; MSK-CHORD adds ~5,400 timelines | Lymphoma |
| **Overall survival endpoint; PFI only as a check later** | Every number on one endpoint | PFI (conditional) |
| **RPPA as the protein layer** | CPTAC covers only ~100 tumors | CPTAC |

#### Rejected approaches and dead ends
Decisions log and memory notes, ⚠️. "Conditional" means it could be revisited.
- **Training:**
  - keeping each client's Adam state across rounds: no gain;
  - fewer omic features (top 32/32/16 gave 0.667);
  - 10 FL rounds (0.670 vs 0.691 at 20).
- **Features:** ranking variance after z-scoring is meaningless, since every variance is then 1.
- **Agent:**
  - log-risk sign wording, and the `delta_log_risk_when_removed` name, read backwards;
  - zero-score junk features (e.g. AC124067.4) in notes;
  - Ultra cut off at 2,000 or 3,000 tokens (now 4,096).
- **Tavily:**
  - combined multi-gene queries and unnamed ids returned generic pages;
  - a 4-turn planner never reached the search;
  - a YouTube video and a vendor page slipped in, hence the domain allowlist;
  - author names and cAMP matched all-letter symbols, hence exact matching.
- **Infrastructure:**
  - GitHub branch protection on a private free repo returned 403 (resolved by going public);
  - Homebrew needed a sudo password the user couldn't enter;
  - interactive terminal prompts stall: use background tasks and give codes in chat;
  - a Streamlit subdomain containing "muff" is rejected;
  - new app worktrees with their own environment need about 5.4 GB and failed on this disk.

#### Discussed, not implemented
| Item | Status |
|---|---|
| Hosted demo fix (reboot, and/or a code guard; §5) | **Needed now**, not started |
| CIViC matching fix (compound `OR` profiles, level-sorted gene-level items) | Found this session, not started |
| `save_demo_notes.py` passing `civic.evidence`; regenerate the 8 notes in the labeled format | Approved freeze to-do; not started |
| Bundle v2 with mutations + CIViC for the hosted app; `demo-bundle-v2` release; `BUNDLE_URL` | Approved freeze to-do; not started |
| "How it works" text and app header in the platform framing; timeline and CIViC mentioned | Found this session; app text is user-visible, so confirm |
| README (#53), Devpost text (#42), video (#47) | Drafts; need the user's review; markers to resolve |
| Keys in Streamlit secrets; a separate demo key; regenerate the Tavily key | User actions |
| Timeline narration by Nemotron | Decided: optional, not planned; only synthetic events, never scores |
| Pathologist workspace | Requested by the user in an earlier session; **not started, not scheduled, not reconciled with the deadline** |
| PFI endpoint | Conditional, after the requirements |

**The pathologist workspace request, in detail** (memory note, ⚠️):
1. A patient list with search as the landing page.
2. A patient file with the latest report first: summary, why, risk factors, areas of risk, and an
   SOS tile for alarming findings.
3. Buttons: Import test (adds to the file and advances the report), Tests (all results), Timeline
   (each report version on a real timeline, with its tests).
4. Tile overlays on slides and scans: hover shows tile stats (risk, confidence, tissue type,
   models); click expands; uncertain or high-risk regions are flagged.
5. "Use the best public pretrained models."

**Earlier model and data license research:**
- Permissive: H-optimus-0, Prov-GigaPath, Hibou-B/L (gated-auto), kaiko midnight, QuiltNet,
  TMEsegBreastTCGA; TIAToolbox BCSS (CC0 weights); MONAI breast density (Apache).
- Non-commercial or no-derivatives: UNI/UNI2-h, CONCH, TITAN, Virchow2, H-optimus-1; MAMA-MIA
  nnU-Net, ODELIA MST.
- Data: TCIA TCGA-BRCA MRI (~139 patients, 88 GB, CC BY 3.0); GDC slides (~1 GB each).

**Blockers for the workspace:** 8 GB of RAM, a nearly full disk, an HF token for gated models,
and the deadline.

#### Current work in progress
This handoff (PR #51) is the only work in flight in this session. Nothing is half-edited in any
worktree. **The most urgent product item is the broken hosted demo.**

#### Open threads
- Whether to merge #53, #42 and #47, and in what final wording. Submission material needs the
  user's OK.
- Whether to merge #51 at all (an internal doc in a public, judged repo) or keep it on its
  branch.
- Whether the hosted crash is a stale-module problem (fixed by a reboot) or something else
  (❓ until the reboot is tried).
- Whether to ship the CIViC TSV rows in bundle v2 or let the hosted app download the CC0 TSV
  (~4 MB) at startup.
- Real Nemotron prices on the Nebius console. The current ones come from price trackers.
- Whether the pathologist workspace fits before the freeze. **Recommendation: no**, keep it as
  roadmap.

#### Likely next steps
In recommended order; none of these is approved yet except where noted.
1. **Restore the hosted demo** (judges may try it any time).
   - (a) The user reboots the app in Streamlit Cloud (Manage app → Reboot app) and checks that all
     four tabs render.
   - (b) If it recurs after the next push, add a guard in `app/streamlit_app.py` so hot updates
     can't leave a stale `charts` module, e.g. `importlib.reload(charts)` after import.
   - (c) While in Settings → Secrets, the user adds `NEBIUS_API_KEY` and `TAVILY_API_KEY`. Then
     check that the sidebar says "live" and write one capped live note.
2. **Fix CIViC matching** (`src/muffle/report/civic.py`):
   - match profiles where the variant is one `OR` alternative (never inside `AND`);
   - rank across exact, compound and gene-level matches by evidence level;
   - add a test that PIK3CA H1047R returns level-A alpelisib + fulvestrant.

   Then rerun `make demo-timeline`; the JSON's CIViC items change, but none of its scores do. An
   in-plan bug fix, but it changes what the demo shows, so tell the user.
3. **Freeze to-dos:**
   - pass `civic.evidence` in `save_demo_notes.py`;
   - `make demo-notes` (live, about $0.12);
   - `make demo-bundle`, and decide how CIViC reaches the hosted app;
   - new release `demo-bundle-v2` and a `BUNDLE_URL` bump.

   Confirm with the user first: this changes what judges see.
4. **App text:** update "How it works" (note sections, timeline, CIViC, evidence labels). Consider
   a platform-framed header. Confirm the wording with the user.
5. **Submission material:**
   - the user reviews #53;
   - resolve #42's 9 markers and #47's timeline slot now that everything is built;
   - tick the `docs/HACKATHON.md` boxes;
   - re-check the Devpost rules page in the built-in browser (WebFetch gets a 403).
6. **Video and submission:** run `make agent-tcga PATIENT=661` (and 710) before recording to check
   note quality. Then record, upload to YouTube, freeze on Oct 28, submit by Oct 30, 10:00 PT.
7. **Housekeeping** (ask first):
   - remove the leftover worktree `eager-ardinghelli-4c9eb3`;
   - prune the merged local branches and the remote `app/streamlit-secrets` branch;
   - consider deleting `outputs/investigate_all.json` and `outputs/tcga_brca_centralized.pt`
     (old artifacts);
   - add the newer variables to `.env.example`;
   - fix the stale lines in SETUP.md and CONTRIBUTING.md;
   - fill in or remove the CODEOWNERS placeholders.

#### Promote to project memory
These are candidates for `CLAUDE.md`, which I haven't edited: `CLAUDE.md` changes go through
their own PR and the user's attention.
- In a git worktree, run tests with `PYTHONPATH=src`. The shared `.venv` has `muffle` installed
  editable from the main folder, so otherwise you test main's code.
- The CI lint gate is `ruff check` only. Don't run `ruff format` repo-wide (39 files would
  change).
- After pushing app changes that touch `app/charts.py` (or any module next to the entry point),
  reload the hosted app and check every tab. Streamlit Cloud can keep the old module.
- Before `preview_start demo-tcga`, check for a stale server with
  `lsof -nP -iTCP:8501 -sTCP:LISTEN`.
- CIViC: one evidence item can cover several variants ("X OR Y"). Match variants inside compound
  profiles.

---

### 5. WHAT COULD GO WRONG

#### Known bugs and failures
1. **Hosted demo crash** (✅ observed twice).
   - *Steps:* open `https://cancer-intelligence-platform.streamlit.app/~/+/`.
   - *Observed:* an `AttributeError` at `app/streamlit_app.py:182` (`charts.risk_timeline`).
     Nothing after the timeline metrics renders.
   - *Expected:* four working tabs.
   - *Likely cause* (❓): Streamlit Cloud hot-updated the app to #49's `streamlit_app.py` but kept
     the old `charts` module (from before #49, without `risk_timeline`) in `sys.modules`. The same
     commit runs fine in a fresh local process (✅).
   - *Fix:* reboot the app. If it recurs, reload `charts` explicitly. If a reboot doesn't help,
     read the logs in Manage app.
2. **CIViC lookup misses compound profiles and truncates stronger gene-level evidence** (✅
   reproduced).
   - *Observed:* for PIK3CA H1047R in breast cancer: C (fulvestrant + everolimus), D (izorlisib),
     D (pictilisib).
   - *Expected:* level-A fulvestrant + alpelisib first.
   - *Location:* `civic.evidence`, which only does an exact `molecular_profile == f"{gene}
     {variant}"` match plus gene-level, then `out[:k]` with exact matches first.
3. **Saved notes unlabeled; `save_demo_notes.py` passes no CIViC** (✅ inspected).
4. **"How it works" lists the old note sections** (✅ read in `app/streamlit_app.py`).
5. **The hosted app can never show CIViC** (✅ code): `EVIDENCE` needs a cached TSV, and bundle v1
   has no mutations.
6. **FedAvg nondeterminism** (⚠️): identical runs differ by about 0.01, because NVFlare's initial
   global model isn't seeded (0.668 vs 0.680 for the same config). Compare means over seeds.
7. **Agent quirk** (⚠️ older): the Summary sometimes restates the percentile instruction or calls
   clinical an "omic" layer.

#### Important edge cases
- **Missing data:**
  - Missing layers are masked, never imputed as "normal".
  - A patient with only one layer gets undefined contributions; the tool says so.
  - "Not sequenced" (NaN) ≠ "none of the panel mutated" ([]) ≠ a list of changes.
- **Stage:** an unknown stage is median-imputed in `stage`, with `stage_unknown = 1`. The demo
  shows "not recorded" by checking `stage_unknown`, so don't read `stage` alone.
- **Agent:**
  - The planner may skip `predict_risk`; then the fixed plan is appended.
  - Tool calling can be rejected with HTTP 400 on turn 1; then the fixed plan plus the writer run.
  - A writer reply cut off at 4,096 tokens counts as no text.
- **Grounding check:** integers below 10 without a suffix are skipped. TNM codes and HER2 are
  allowed. Signs are ignored; a percent can quote a fraction.
- **Survival data:** few deaths (event rate about 0.14; site-3 has only 24), so per-site and
  per-slice C-indexes are noisy (slices with ≤ 15 deaths are noise). The Cox loss needs whole
  batches; `drop_last` keeps small sites training.
- **MSK-CHORD:**
  - Landmark populations differ, so switching to a later landmark's model can move the risk by
    itself (+24 points at month 24 in the demo, shown separately).
  - Labels are NLP-derived; features partly reflect care intensity.
- **Site files:** `site_files` reuses existing `clients_*` partitions if the count matches. A
  rebuilt cohort with stale partitions would mismatch; `build_demo` raises "doesn't match the
  cohort split".

#### Technical debt
- Feature selection is pooled and unsupervised, i.e. not federated; `harmonize_features` is
  unused.
- Untested leftovers: the Dockerfile, `docs/NEBIUS.md`, `--gpu`, the S3 variables.
- CODEOWNERS has `@OWNER_A/@OWNER_B` placeholders.
- `.env.example` lacks `NEMOTRON_WRITER_MODEL`, `DEMO_LIVE_NOTES_PER_SESSION`, `MUFFLE_BUNDLE`
  and `MUFFLE_SPEND_LEDGER`.
- SETUP.md and CONTRIBUTING.md still say the pre-push hook stands in "until the repo is public".
  SETUP.md also mentions CHIMERA and Homebrew.
- Format drift: 39 files. `.vscode/settings.json` formats on save with ruff, so editing in VS Code
  reformats whole files.
- Prices in `budget.py` come from trackers.
- `streamlit_app.py` (430 lines) has no tests; neither do `save_demo_notes.py`,
  `make_demo_bundle.py`, `secrets_to_env` or `export_results.py`.
- The `demo-hosted` preview config points at a deleted scratch venv.

#### Architectural risks
- **External services:** Token Factory credit and availability; Tavily free-tier credits (at most
  3 per note).
- **Streamlit Cloud:** sleeping apps, hot-update module staleness, a ledger reset on restart.
- **Bundle hosting:** the demo depends on the GitHub release URL.
- **NVFlare:** API churn; stay on the Recipe API.
- **Data sources:** CIViC nightly-file schema changes (column names are hard-coded); Xena hub file
  names.

#### Security and privacy risks
- **Local-only data:** MSK-CHORD files live in `data/raw/msk_chord` and `outputs/msk_chord`.
  `/data/` and `/outputs/` are ignored, but `.json` isn't ignored by extension. Check that any new
  `app/*.json` holds only synthetic or aggregate data.
- **What reaches Token Factory:** tool outputs only. Never add MSK-CHORD-derived values to
  `CaseTools`.
- **Keys:** only in `.env` and the Streamlit secrets; never in commands, logs or chat.
- **This document** contains local absolute paths, including the macOS username, so the resume
  prompt works. It contains no keys, emails or patient data.

#### Assumptions that may be wrong
- ❓ The hosted crash is a stale module; reboot to confirm.
- ❓ The hosted secret names and values (from a memory note).
- ❓ Model prices, model ids and the Devpost rules (re-read Oct 18).
- ❓ Nobody else is working in the main folder. No session was running at handoff, but two people
  share this Mac.
- ⚠️ The Makefile's "~15 min" for `make experiment-tcga` predates the residual methods. A full
  run with `fedavg_residual` took about 1 h.

#### Regression risks
- `tests/test_model.py` (masks, dropout, `always_keep`, additive sum).
- `cohort.npz` arrays must stay byte-identical when fields are added.
- Contribution semantics and key names; evidence labels; "simulated" and "synthetic" labels.
- The grounding check; the budget cap and ledger locking.
- Bundle format v1 compatibility (cases without `mutations` must still load).
- The `weights_only` load.
- The seed protocol.
- The site split: `split_by_group` is deterministic, so changing it changes every number.

#### Operational risks
- **Disk:** about 4 GB free; reuse the existing worktrees.
- **Claude usage:** 90% of the weekly limit. Work sequentially; no parallel sessions or subagents
  unless the user asks; stop at a clean point.
- **Toolchain:** `gh`, `uv` and `python3.12` live in `~/.local/bin`, which isn't on the
  interactive zsh PATH.
- **Pushes:** the pre-push hook and branch protection reject direct pushes to `main`. That's
  expected.
- **Hosted ledger:** it can't see local spend. The cap there is the low secret, plus the Nebius
  console.

---

### 6. HOW TO THINK ABOUT THIS PROJECT

1. **Core design philosophy.**
   - *Honest, evidence-linked decision support, built from small validated parts.*
     - Every claim is labeled observed / inference / hypothesis.
     - Every number comes with its baseline and uncertainty, measured under a fixed seed protocol.
     - Uncomfortable results are stated (clinical-only wins).
     - Every note claim traces to a tool output, checked by deterministic code.
     - Data rights decide what can be shown or sent.
   - *Architecturally:* a mask-aware multimodal survival model trained federatedly, wrapped by an
     agent whose tools are the model's own explanations, plus a separately evaluated longitudinal
     layer.
   - *Why:* the vision is a clinical tool that must be trustworthy, and judges reward a complete,
     credible product.
2. **Most likely newcomer mistakes:**
   - overstating results;
   - sending or showing anything MSK-CHORD-derived;
   - unlabeled inferences or simulated sites;
   - touching the budget cap;
   - testing main's code from a worktree;
   - switching the main folder's branch;
   - merging submission PRs without asking;
   - running `ruff format` on everything;
   - assuming the hosted demo works because the local one does.
3. **Intentionally preserved design** (looks refactorable, isn't):
   - the planner/writer split and the no-LLM grounding check;
   - the offline template fallback (the demo must never show a traceback from the agent);
   - cohort-offset contributions;
   - final-model FedAvg scoring;
   - site-held-out λ;
   - additive fusion with clinical always kept;
   - the weights-only bundle;
   - NVFlare over Flower;
   - Token Factory only;
   - the hand-written (not sampled) synthetic patient;
   - aggregates-only MSK-CHORD.
4. **Product vs implementation.** The essentials are a labeled, evidence-linked profile that
   updates over time, with "for clinician review" framing and visible provenance (tool trace,
   grounding result, sources). Today's gaps against that intent are a hosted demo that works, live
   hosted notes, labeled saved notes, and correct, strongest-first CIViC evidence.
5. **How to judge progress:**
   - CI green; `make test` and `make lint` pass;
   - the hosted URL renders all four tabs and writes a live, grounded, labeled note;
   - CIViC shows level-A evidence where it exists;
   - saved notes are in the labeled format;
   - README, HACKATHON and the submission text match reality;
   - reported numbers are unchanged unless a deliberate, documented rerun.
6. **Guiding tradeoffs:**
   - **Accepted:** the simulator instead of real sites; overall survival only; laptop-scale
     models; aggregates-only MSK-CHORD; a 40-case hosted bundle; free credits only; the omics not
     beating clinical data.
   - **Unresolved:** the pathologist workspace; PFI; how CIViC reaches the hosted app.
   - **Not permanent:** the Nebius Serverless Job, the omics-vs-clinical result (a better model or
     endpoint could change it), and the hosted case count.

---

### 7. DO NOT TOUCH LIST

- Do not refactor stable, working systems or redesign the architecture without a clear reason or
  request.
- Preserve naming, interfaces and data contracts: the `cohort.npz` keys, bundle format v1 fields,
  tool names and output keys, `evidence_type`, `CaseReport` fields (`saved_notes.json` round-trips
  through them), and the site naming `site-k`.
- Respect the documented decisions and tradeoffs (§4) unless new evidence justifies
  reconsidering them. Record any change in `docs/decisions.md`.
- Ask before adding frameworks, libraries, services or infrastructure.
- Never overwrite or discard other sessions' or the user's changes or worktrees. Never switch the
  main folder's branch; use a worktree.
- Never raise, bypass or reset the $25.50 cap or the ledger. Never print, log or type API keys.
  Billing and secrets are the user's actions.
- Never commit `data/`, `outputs/`, `workspaces/`, `.claude/`, `.env`, or `.csv/.tsv/.npz/.pt`
  files.
- Never commit, host, show or send any MSK-CHORD patient, MSK-CHORD-trained model or its outputs
  (the timeline scores included) to an LLM.
- Ask before changing reported numbers, the pitch, the README, the Devpost text or the video,
  before changing repo visibility, and before merging after the Oct 28 freeze. Don't self-merge
  #53, #42 or #47.
- Don't reintroduce NVFlare's old `FedAvgJob` API. Don't use tiny batches or per-sample Cox
  losses.
- Keep `tests/test_model.py` passing, and keep missing-layer handling everywhere.
- Don't run `ruff format` repo-wide. Don't force-push or rewrite history.
- Don't claim verification, merges or deployments without evidence. Don't build proposed features
  (the pathologist workspace, timeline narration) as if they were approved.

---

### 8. CONFIDENCE AND FRESHNESS

| Area | Confidence | Basis |
|---|---|---|
| Git state, branches, worktrees, PRs, issues, settings, protection | ✅ HIGH | `git` / `gh` this session |
| Everything is on GitHub except local-only files (Appendix A) | ✅ HIGH | Branch-by-branch check against merged PR heads; clean worktrees |
| Tests 84 pass; lint clean; smoke test passes | ✅ HIGH | Run this session |
| Local demo healthy (all tabs, live) | ✅ HIGH | Browser this session |
| Hosted demo crashes; live off | ✅ HIGH | Browser this session (twice) |
| Cause of the hosted crash | ❓ LOW | Inference; confirm by rebooting |
| CIViC gap; saved-note format; `save_demo_notes` gap; stale How-it-works text | ✅ HIGH | Reproduced or read this session |
| Spend $0.4632 / $25.50 | ✅ HIGH | Ledger this session (this Mac only) |
| Reported numbers (C-index, AUROC, calibration) | ⚠️ MEDIUM | Committed JSON and docs; not rerun |
| Live agent behavior and cost | ⚠️ MEDIUM | Decisions log; no live call this session |
| Hosted secrets content; model prices; Devpost rules | ❓ LOW | Memory notes, price trackers, Oct 18 reading |
| Pathologist workspace scope and priority | ❓ LOW | One earlier request; not reconciled with the plan |

**Handoff timestamp: 2026-10-19 01:05 CDT (06:05 UTC).** Re-check all of these when reusing this
document:
- the repo state, open PRs and the hosted app;
- dependency versions, credits and Claude usage;
- the Devpost rules.

Newer source code, user instructions and `CLAUDE.md` always override this document.

---

### Appendix A: what lives only on this Mac, and how to recover it

Everything in git is on GitHub (✅ §2). The following is deliberately **not** in git, either
because of the data rules or because it is machine state. If you move to another machine or
account, this is how to get each piece back.

| Item | Where | Recovery |
|---|---|---|
| TCGA raw files + cohort | `data/raw/tcga_brca` (342 MB), `data/tcga_brca` | `make tcga` (downloads open-tier files; streams methylation) |
| CIViC TSV (CC0) | `data/raw/civic/` (4 MB) | Downloaded automatically by `civic.load_table()` |
| MSK-CHORD | `data/raw/msk_chord` (377 MB) | `make msk-chord` (public cBioPortal tarball). **Never upload it anywhere.** |
| Synthetic data | `data/synthetic` | `make synth` |
| Demo model `outputs/tcga_fedavg.pt` | local | Its weights + cfg are inside the public release bundle `demo-bundle-v1`; or retrain with `make fl-tcga` (results differ by ~0.01: NVFlare seeding) |
| Experiment JSONs | `outputs/experiments/tcga_brca_{3clients,residual}.json` | The aggregates are committed (`app/results_tcga_brca.json`, README, decisions); full rerun `make experiment-tcga` (~1 h) |
| Calibration and MSK results | `outputs/calibration`, `outputs/msk_chord` | Tables committed in `docs/calibration.md` and `docs/longitudinal.md`; rerun the make targets |
| NVFlare workspaces | `workspaces/` (471 MB) | Scratch; regenerated by runs |
| **Spend ledger** | `~/.muffle/token_factory_spend.json` ($0.4632 spent at handoff) | **On a new machine, record past spend first:** `python -m muffle.report.budget --add 0.4632` (plus anything spent since; check the Nebius console Usage tab), or the cap would let $25.50 be spent again |
| Secrets | `.env` (local), Streamlit Cloud secrets | The user re-enters them from the Nebius and Tavily consoles; names in §3 |
| Preview configs | `.claude/launch.json` (untracked) | `demo-tcga`: `.venv/bin/streamlit run app/streamlit_app.py --server.port 8501 -- --ckpt outputs/tcga_fedavg.pt --data data/tcga_brca` (port 8501). Optional `demo-vision` (port 8503, runs from a worktree) and `demo-hosted` (port 8502, `--bundle outputs/demo_bundle.pt`, needs a venv from `app/requirements.txt`) |
| Claude auto-memory | `~/.claude/projects/-Users-prakharsuryansh-PycharmProjects-muffle-plus-plus/memory/` | Its durable content is folded into this document. Notes covered: toolchain, protection, interactive steps, Token Factory and Tavily, resume points, self-merge rule, agent-quality history, Devpost rules, hosting, usage limits, milestone 1 |
| Git worktrees | `.claude/worktrees/*` | All clean and pushed; recreate with `git worktree add` if needed |

**Switching GitHub accounts:** the repo belongs to `ps131-cell`, the only collaborator. Another
account needs to be added as a collaborator (Settings → Collaborators) or receive a transfer.
Either is the user's action. The Streamlit Cloud app is linked to the `ps131-cell` GitHub
account, under the user's Google login.

**Optional extra backup** (needs the user's OK; it publishes files): upload the aggregate
experiment JSONs as assets of a new GitHub release. They contain no patient data, but the
`outputs/` rule bars committing them.

### Appendix B: resume prompt

```
You are resuming work on MuFFLe++, a hackathon project (Nebius × NVIDIA Global AI Hackathon on Devpost; deadline Fri Oct 30 2026, 10:00 am PT; freeze Oct 28). The repository is /Users/prakharsuryansh/PycharmProjects/muffle-plus-plus (GitHub: ps131-cell/muffle-plus-plus). A previous Claude session wrote a detailed continuation document for you.

1. Read the entire continuation document before taking any action:
   /Users/prakharsuryansh/PycharmProjects/muffle-plus-plus/.claude/worktrees/secrets/docs/AI_Continuation_Document-19Oct2026-0105.md
   If that path no longer exists (the worktree was removed, or PR #51 was merged), use docs/AI_Continuation_Document-19Oct2026-0105.md in the main checkout after updating main, or run: git -C /Users/prakharsuryansh/PycharmProjects/muffle-plus-plus show origin/docs/continuation-handoff:docs/AI_Continuation_Document-19Oct2026-0105.md (on GitHub: https://github.com/ps131-cell/muffle-plus-plus/blob/docs/continuation-handoff/docs/AI_Continuation_Document-19Oct2026-0105.md).
2. Read the project instruction file /Users/prakharsuryansh/PycharmProjects/muffle-plus-plus/CLAUDE.md (authoritative; there is no AGENTS.md or .cursor/rules) and, if it exists on this machine, the Claude auto-memory index /Users/prakharsuryansh/.claude/projects/-Users-prakharsuryansh-PycharmProjects-muffle-plus-plus/memory/MEMORY.md. Read the other repository docs the document names as you need them (docs/decisions.md, docs/HACKATHON.md, docs/VISION.md, docs/registry.md).
3. Ground yourself in the actual project state before trusting the document. In the main checkout, run git status, git log -5, git branch --show-current, git fetch origin and git worktree list, and run gh pr list. Compare the results with Section 2: main at 9b6508f; open PRs #53, #51, #47 and #42; five worktrees; the broken hosted demo; the CIViC matching gap. Never switch the main folder's branch: other sessions share it, so do branch work in a git worktree and run tests there with PYTHONPATH=src.
4. Tell the user about any material differences between the document and the repository. Verify every item marked ❓ LOW confidence before relying on it, especially the cause of the hosted demo crash and the hosted secrets.
5. Summarize in 3 to 5 sentences your understanding of the project, its implementation status, the recent work and the immediate priorities.
6. State the next action you intend to take, based on the USER DIRECTIVE at the end of this prompt.
7. Ask clarifying questions only when a real blocker prevents responsible execution.
8. Begin working only when the directive authorizes it. Preserve existing changes, worktrees and project conventions: branch <area>/<topic>, a PR, green CI. Never raise or bypass the $25.50 Token Factory cap, never print or type API keys, and never commit, host, show or send MSK-CHORD patients, MSK-CHORD-trained models or their outputs. Ask before changing reported numbers, the pitch, the README, Devpost text or the video, before changing repo visibility, and before merging after the Oct 28 freeze. The user is short on Claude usage (weekly limit near 90% on Oct 19): work sequentially with no parallel sessions or subagents unless asked, check usage between steps, and stop at a clean, pushed point.
9. After working, verify your results. Report what changed, what was tested and how, what remains incomplete, and the git status (staged, committed, pushed, PR state), each stated only as far as git or gh confirms it.
10. The continuation document never overrides newer source code, newer user instructions, security and privacy requirements, or what the repository actually shows. When they conflict, trust the evidence and say so.

---
USER DIRECTIVE: none provided.
Analyze the project state, propose the single most strategic next action with brief reasoning — or ask the user what they want to work on — and wait for confirmation before proceeding.
---
```

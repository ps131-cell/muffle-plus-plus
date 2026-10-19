# Decision log

Newest at the top. One entry per decision: date, what, why.

## 2026-10-19 — Before the freeze: the workspace slice on existing data (scope B)
- **What:** by the Oct 28 freeze, the app gains the patient record from `docs/WORKSPACE.md`:
  - a patient list, a patient file with an SOS tile, tests and a report timeline;
  - lab and mutation workbenches on existing data (SYNTHETIC-001 and the held-out TCGA cases);
  - one real cross-test workflow: a sequenced driver, its CIViC evidence, and the risk update.

  Slide and scan workbenches, and test import, show as planned.
- **Why:** judges score "a complete product, not a proof of concept", and this shows the
  product loop without new models. The pathology workbench isn't first: the colon analyzer's
  tissue heads don't transfer to breast, so it waits for the model survey's shortlist.
- **Also:** the open fixes from the handoff (CIViC matching, labeled saved notes, bundle v2, the
  hosted demo) run in parallel sessions. The Windows PC runs the code in WSL2.

## 2026-10-19 — The product vision: a clinician workspace with a deep workbench per test type
- **What:** the team's full product idea is written down. `docs/VISION.md` holds the idea
  (characterize the cancer from every test, follow it in a versioned patient file, track its
  evolution, support evolution-informed treatment decisions, learn from contributed data) with
  what the evidence supports. `docs/WORKSPACE.md` specifies the app: a patient list with search,
  a patient file that opens on the latest report (summary, SOS tile, why the AI thinks so, risk
  factors and areas of risk), test import that creates a new report version, a tests browser,
  and a timeline of report versions. Every test type gets its own interactive workbench, analyzed
  tile by tile or region by region (hover for brief stats, click to expand), at the depth of the
  team's Colon Tumor Front Analyzer.
- **Treatment:** the idea of steering the tumor's evolution is recorded as an evidence-backed
  research direction. Each treatment closes the most likely escape routes until a combination can
  block the rest, and slows growth in between. The evidence: PADA-1 and SERENA-6 switched
  treatment on an emerging ESR1 mutation in blood before progression; models of combination,
  extinction and adaptive therapy support the rest. Those models favor giving drugs together over
  closing routes one at a time. The platform shows evidence and hypotheses; it never recommends
  a treatment.
- **Data from clinicians:** roadmap only. No real patient data in the hackathon; federated
  learning stays on simulated hospitals.
- **Cancer:** breast stays (2026-10-18); lymphoma was only an example. Breast also has the
  clearest precedent for the treatment idea (ESR1 mutations under aromatase inhibitors).
- **Why:** the team wants the platform, not only its first slice, written down so every session
  and the submission work from the same picture.
- **Open:** which parts of the workspace ship before the Oct 28 freeze; a survey of public
  pretrained models and datasets for each test type; whether code from the colon analyzer may be
  reused under both hackathons' rules.

## 2026-10-18 — The demo's timeline patient: hand-written, scored by the MSK-CHORD models
- **What:** the synthetic patient (`muffle.timeline`) is written by hand (stage II HR+/HER2−,
  bone recurrence, PIK3CA H1047R, a liver progression at month 12), not sampled from MSK-CHORD
  distributions, so no real patient can be reproduced. At each event from month 0 on it is scored
  by the evaluated landmark models (latest landmark at or before the event, seeds 0–4 as the
  uncertainty range) next to the diagnosis-only baseline; the change since the previous event is
  attributed one change at a time. Only these scores, aggregate metrics and CIViC items are
  committed (`app/timeline_synthetic.json`); the models stay local, since sharing a model trained
  on CC BY-NC-ND data could count as sharing adapted material.
- **Why:** it shows the vision's longitudinal profile on real-data models without hosting or
  showing any MSK-CHORD patient, and the hosted demo needs no MSK-CHORD files.
- **No MSK-CHORD-model output goes to Token Factory** (team decision, 2026-10-19): the timeline's
  risk scores, ranges and attributions come from models trained on MSK-CHORD, so they stay out
  of every LLM call, like MSK-CHORD itself. If the Nemotron agent ever narrates the timeline, it
  gets only the synthetic patient's own events (diagnosis, treatments, labs, imaging,
  sequencing), never the scores; narration is optional, and the demo does without it.

## 2026-10-18 — MuFFLe++ becomes milestone 1 of a cancer intelligence platform
- **What:** the project is reframed around the team's vision (`docs/VISION.md`): a multimodal,
  longitudinal cancer intelligence platform for one cancer. The submission presents MuFFLe++ as
  its **first milestone** for **breast cancer**, not as a federated-learning project; federation
  stays as one measured result (it replaces the "lead with federation" pitch bullet below).
- **Build before the Oct 28 freeze:** (1) every statement in the case note labeled observed /
  model inference / hypothesis; (2) observed driver mutations from GDC open-access masked MAFs
  plus CIViC (CC0) evidence for clinician review; (3) real longitudinal data: **MSK-CHORD**
  timelines, task = risk of progression or death in the next 12 months re-predicted at each new
  event, compared with baselines as the record grows; (4) a synthetic, labeled timeline patient
  in the demo; (5) `docs/registry.md`.
- **MSK-CHORD terms (CC BY-NC-ND 4.0):** local use only; publish code and aggregate results
  with attribution; never commit, host, show or send to an LLM any individual MSK-CHORD patient.
  The demo's timeline patient is synthetic, built from MSK-CHORD's structure, and labeled.
- **Why:** the team wants the project to move toward the vision; these pieces show its core
  ideas (evidence types, timelines, treatment evidence, federation) on real data within the
  deadline. Pathology/radiology encoders, evolutionary hypotheses and real institutions stay on
  the roadmap. TCGA's lymphoma cohort (~48 patients) is too small, so breast cancer stays.

## 2026-10-18 — Hosted demo runs from a 0.9 MB bundle of 40 held-out cases
- **What:** `make demo-bundle` writes `outputs/demo_bundle.pt`: the FedAvg-residual weights,
  the model inputs of 40 held-out patients (the 8 with saved notes plus a spread over the risk
  range), and derived numbers only (all 1,064 predicted risks, layer offsets, per-site
  held-out C-index, risk-group survival curves of the 213 held-out patients). It holds no
  survival times or other patient-level data. It loads with `torch.load(weights_only=True)`,
  so a downloaded file can't run code. Without the checkpoint and cohort, the app loads the
  bundle from `--bundle` / `MUFFLE_BUNDLE`, by default the release asset
  `demo-bundle-v1/demo_bundle.pt` (`GITHUB_TOKEN` lets it read a private repo's release).
  `app/requirements.txt` is the hosted install: CPU torch, no NVFlare. The app finds `muffle`
  in `src/` without a pip install. `make demo-hosted` runs it that way locally.
- **Why:** the hosting decision limits the server to weights plus derived features for a few
  dozen demo patients. Tested in a fresh environment with only `app/requirements.txt`: same
  numbers as the full-data app, a live note works, and the live-notes counter now counts down.
- **Agent:** if the planner uses up its turns before the literature step while named genes
  are available, it gets one extra turn that offers only `search_literature`. Live: case 299
  went from "no literature search was run" to 4 PMC papers.

## 2026-10-18 — Demo redesign; layer contributions measured against a typical patient
- **What:** the demo has three tabs.
  - **Case review:** the 213 held-out patients only (each hospital's validation split, which
    the federated model never trained on). It shows the risk percentile and group, where the
    patient sits among all patients, what drives the risk, a what-if that hides data layers,
    and the case agent's note with its live steps, grounding result, tool trace and a Markdown
    download.
  - **Federation:** the hospitals, the leave-one-hospital-out results (from
    `app/results_tcga_brca.json`, made by `make demo-results`), and Kaplan–Meier curves of the
    held-out risk groups up to 5 years.
  - **How it works:** the method, privacy and limits.

  Live notes are capped at `DEMO_LIVE_NOTES_PER_SESSION` (5). Eight featured patients have
  saved notes from the live agent (`make demo-notes`, all with no grounding issues), shown
  without a key or once the cap is reached. `muffle.demo` builds everything the app shows, so
  the hosted demo can later load it from a bundle instead of the data.
- **Contributions:** a layer's contribution is now its masked effect minus that layer's
  average masked effect over the cohort, so it reads "compared with a typical patient".
  Masking alone shifted every patient by a near-constant per layer (−0.08 to −0.18). That's why
  17% of high-risk patients showed every layer "lowering" risk; with the offset none do, and
  each layer's contributions average zero.
- **Agent details:** tools report whole percentiles ("75th", not "75.5th"). Publication search
  is limited to scholarly and clinical domains: a YouTube video and an antibody vendor page
  had slipped into a note. An all-letter gene symbol must match exactly ("Camp RL" the author
  and cAMP aren't CAMP). Ultra's token limit is 4,096, after a long literature list ran past
  3,000 once and the note fell back to Super.

## 2026-10-18 — Tavily literature search is live; results must name the gene and a cancer
- **What:** `TAVILY_API_KEY` is set (Tavily dev key, free tier). `tavily_search` runs one query
  per gene (at most 3 per call, so at most 3 credits) and keeps a result only if its title or
  snippet names that gene and mentions cancer. When a gene has hits that name this cancer type,
  the others are dropped. The same paper on two sites is kept once, and trial protocol PDFs
  link to their ClinicalTrials.gov study page. Clinical fields (age, stage) can't be searched.
  The planner gets up to 6 turns and one reminder if it stops before searching.
- **Why:** the first live run showed the problems: a combined query or an unnamed id
  (AC138356.2, Y_RNA) returned generic survival-rate pages; RBP1 matched a coronary artery
  disease paper; trial hits were PDFs titled "CLINICAL STUDY PROTOCOL"; and with 4 turns, one
  tool per turn, the planner never reached the search.
- **Result (live, TCGA patient 463):** VAV3 ("a poor prognostic factor in breast cancer"),
  PRAME in breast cancer (PubMed), and a pan-cancer RBP1 paper; every link passed the grounding
  check. A patient whose only features are unnamed ids gets "no literature search was run".
  Best Use of Tavily needs a runtime Tavily call: the agent makes one whenever it names genes.

## 2026-10-18 — Case agent: Super plans, Ultra writes, a grounding check verifies the note
- **What:** Nemotron 3 Super runs the tool loop (up to 4 rounds) and replies DONE. Nemotron 3
  Ultra (`NEMOTRON_WRITER_MODEL`, 3,000 max tokens including its reasoning) gets the case header
  and the tool outputs, without log-risk values or the tools' reading notes, and writes the
  note. `muffle.report.grounding.check_note` (no LLM) then looks for numbers, gene/feature names
  and URLs in the note that no tool returned. If it finds any, the writer gets one rewrite;
  whatever remains is shown under the note in the demo. If Ultra fails, returns nothing or is
  cut off at the token limit, Super writes the note. Ultra is priced at $1 / $3 per 1M tokens
  in the spending cap (price trackers; unverified on the Nebius console).
- **Why:** the Best Apps and Agents track text (Devpost, re-read today) says to "reach for
  Nemotron 3 Ultra when you need serious reasoning, and let Nano or Super handle the fast,
  everyday calls". The check makes "the note cites only tool outputs" something the demo can
  show, not just a prompt instruction.
- **Result (live, TCGA, 5 patients from the 10th to the 99th percentile, both writers on the
  same tool results):** after the prompt fixes all 10 notes passed the check with no rewrite.
  Ultra's notes are a little richer (feature scores, cohort size). A report costs about $0.01
  with Ultra (about $0.003 with Super alone) and takes 7–10 s. The first run showed what the
  fixes address: both models left the clinical layer out of Drivers, notes repeated log-risk
  values and double negatives ("lowered by −0.12"), and one Ultra note was cut off at 2,000
  tokens. This work cost $0.11 of the cap.
- **Open:** a layer's contribution is measured against the same patient with that layer masked
  out, so a high-risk patient can show every layer "lowering" risk (seen at the 70th and 90th
  percentiles). Report contributions relative to the cohort average instead (demo work, step 2).
- **Rules re-check (2026-10-18):** the Submission Period began Aug 26, so the repo is a new
  project. A project can win one Overall or Track award plus one Bonus award. Best Use of
  Tavily needs a runtime Tavily call (we have no key yet). There is a Most Valuable Feedback
  prize ($100 + swag, 10 winners), so keep a running feedback log.

## 2026-10-18 — Nemotron model, and a hard $25.50 Token Factory spending cap
- **Model:** `nvidia/nemotron-3-super-120b-a12b` (`NEMOTRON_MODEL`). Token Factory lists five
  Nemotron ids (3 Nano 30B-A3B, 3.5 Lightning, 3 Super 120B-A12B, 3 Ultra 550B, 3.5 Super VL);
  Super ran the case agent with tool calling on the first try: TCGA patients 0 and 5 gave
  `mode=agent`, 3 tool calls, ~4.8k tokens, about $0.002 per report. Ultra wasn't tried (cost).
- **Spending cap:** every live call goes through `muffle.report.budget`. It reserves the
  worst-case cost before sending (input estimated at 2 characters per token, plus the full
  `max_tokens`), swaps in the real cost from `usage` afterwards, and refuses any call that could
  take total spend past $25.50; the report then falls back to the offline template.
  `TOKEN_FACTORY_BUDGET_USD` can lower the cap but not raise it. Prices: Super at $0.30 / $0.90
  per 1M input / output tokens (price trackers; the official page needs a login); other models
  are charged a deliberately high $3 / $9 until their real price is added.
- **Why:** the Token Factory account is billed automatically once the credit runs out, and
  the team only wants to spend the $25 promo credit.
- **Limits:** the ledger (`~/.muffle/token_factory_spend.json`) only counts calls made by this
  code on this Mac; add console-playground or other usage with
  `python -m muffle.report.budget --add <USD>`. On Streamlit Community Cloud the ledger lives
  in the container and resets on restart, so give the hosted app a low
  `TOKEN_FACTORY_BUDGET_USD` secret and check the Usage tab in the Nebius console.

## 2026-10-18 — Pitch, demo model, endpoint, hosting, merging and video
- **Pitch:** lead with federation: on leave-one-site-out, FedAvg-residual matches pooled
  training (0.693 ± 0.017 vs 0.700 ± 0.012; the gap is below the ~0.01 by which identical
  FedAvg runs differ) and beats hospitals training alone (local-only 0.649 ± 0.032), and no
  patient data leaves a site. Plain FedAvg (0.680 ± 0.008) has the smallest spread of the
  multi-omic models. Say plainly that omics don't beat clinical data on BRCA overall survival
  yet (clinical-only 0.702 ± 0.004). The clinical-anchored residual model (#25) is a
  supporting point (omics only correct the clinical risk), not the headline. Don't write
  "≫ alone": the gain over local-only (+0.044) is about 1.4 local-only sd.
- **Demo model:** FedAvg-residual if its LOSO C-index on the reported seeds is at least plain
  FedAvg's and the agent's tools (risk, contributions, top genes) still work with it;
  otherwise plain FedAvg (#28). Applied: 0.693 ≥ 0.680 and the tools work, so
  `make fl-tcga` builds FedAvg-residual (λ = 0.25).
- **Endpoint:** overall survival for every reported number. PFI only as a time-boxed check
  after the submission requirements are done, and only if TCGA-CDR shows clearly more events
  than OS; if we run it, report both endpoints.
- **Hosting:** Streamlit Community Cloud. The server gets only the trained weights and derived
  features for a few dozen held-out demo patients, from a GitHub release asset (the repo bans
  `.pt`/`.npz`). The Token Factory key is a Streamlit secret, agent calls are capped per
  session, and cached reports for the demo patients are the fallback.
- **Merging:** Claude may squash-merge its own PRs once CI is green if they stay within the
  agreed plan. It still asks for PRs that change reported numbers or the pitch, touch
  submission material (README, Devpost text, video), make the repo public, or land after the
  Oct 28 freeze.
- **Video:** one person records (≤ 3 min, public YouTube, no copyrighted music), agent demo
  first: ~20 s problem, ~80 s one held-out patient (the agent's tool calls and summary),
  ~50 s results (FedAvg vs alone, clinical baseline), ~20 s stack (NVFlare, Token Factory,
  Nemotron). Claude drafts the script and shot list.
- **Why:** these are the claims the numbers support, and the cheapest path to the requirements
  in the 12 days left. The free-credit rule and the "only derived numbers" rule carry over to
  the hosted demo.

## 2026-10-18 — Clinical-anchored residual model (#25); demo model uses it
- **What:** `muffle.residual`: train the clinical anchor alone, freeze it, train the omic heads
  on top; log-risk = clinical + λ·omics with λ ∈ {0, ¼, ½, ¾, 1}. Centrally, λ is scored on 3
  inner splits that hold out whole tissue source sites; in FL (`fedavg_job --residual`, 20
  anchor rounds then 20 residual rounds) each hospital scores λ on its own held-out sites and
  shares only two pair counts per λ. `make fl-tcga` now builds the FedAvg-residual model.
- **Why:** with random-patient inner splits λ came out ≈ 0.4 and did not transfer to new
  hospitals (omic site/batch effects); site-held-out splits fixed that (tuning seeds:
  0.688 → 0.701 = clinical-only).
- **Result (LOSO, seeds 0–4):** residual 0.700 ± 0.012, FedAvg-residual 0.693 ± 0.017,
  centralized fusion 0.692 ± 0.026, FedAvg fusion 0.680 ± 0.008, local-only 0.649 ± 0.032,
  clinical-only 0.702 ± 0.004. Fusion now matches clinical-only (closes #25); it does not beat
  it. FedAvg numbers vary by ~0.01 between identical runs because NVFlare's initial global
  model is not seeded (0.668 vs 0.680 for the same config).

## 2026-10-18 — Never drop clinical in modality dropout; FedAvg gets 20 rounds on TCGA
- **What:** `model.always_keep: [clinical]` exempts clinical (every patient has it) from
  modality dropout; `fl.rounds: 20` for TCGA (default stays epochs / local_epochs). Datasets
  can now use the top-k features of a layer by asking for fewer in the config.
- **Why (LOSO, tuning seeds only):** dropping clinical 80% of the time taught the model to
  lean on the weak omic layers; keeping it lifted the fused model 0.658 → 0.684 (clinical-only
  0.701). Fewer omic features barely helped (top 32/32/16: 0.667). FedAvg at 10 rounds lagged
  centralized (0.670 vs 0.680); 20 rounds reached 0.691. Keeping each client's Adam state
  across rounds did not help and was not kept.
- **Result (LOSO, reported seeds 0–4):** FedAvg 0.668 ± 0.010, centralized 0.692 ± 0.026,
  local-only 0.649 ± 0.032, clinical-only 0.702 ± 0.004. Validation splits: 0.708 / 0.712 /
  0.665 / 0.737. FedAvg beats local-only with the smallest spread; fusion is within ~0.01
  (centralized) of clinical-only but not above it — still #25.

## 2026-10-18 — Real-data protocol for TCGA-BRCA, and what it showed
- **Protocol:** 3 FL clients built from whole tissue source sites (`data.partition: site`,
  balanced by patients: 355/355/354 patients, 68/56/24 deaths), real modality gaps only.
  Metric: site-stratified pooled C-index (pairs only within a site). Reported seeds 0–4; every
  tuning choice was made on seeds 95–99 only. Two protocols: 20% per-site validation splits,
  and leave-one-site-out (LOSO: train on two hospitals, test on all of the third), which has
  ~4× smaller error bars. FedAvg gets the same passes over the data as the baselines
  (rounds = epochs / local_epochs) and is scored with its final global model.
- **Model for TCGA (`configs/tcga_brca.yaml`):** the default model overfits within ~3 epochs
  (1,800 features, ~120 training deaths), so it is smaller and heavily regularized (hidden 64,
  latent 16, dropout 0.5, weight decay 1e-2, 20 epochs: a plateau on tuning seeds). Additive
  fusion with modality dropout 0.8 beat the concat fusion on tuning seeds (0.718 vs 0.672).
- **Result (LOSO, mean ± sd over seeds 0–4):** FedAvg 0.652 ± 0.022 ≈ centralized
  0.645 ± 0.014 > local-only 0.629 ± 0.020. Same order on the validation splits (0.674 /
  0.661 / 0.626). The federated claim holds on real hospitals.
- **But:** clinical-only (stage, age, T/N/M) scores 0.702 ± 0.004 on LOSO and beats every
  fusion variant tried; copy number alone is anti-predictive across sites (0.485), a sign of
  site/batch effects. On BRCA overall survival the omic layers do not add signal yet with this
  model. Tracked in #25; until fixed, don't claim that multi-omic fusion beats clinical data.

## 2026-10-17 — Keep the current project; make Nemotron a tool-calling case agent
- **What:** we reviewed a broader spec (`MUFFLE_SPEC`: longitudinal visits, imaging/pathology
  foundation models, Flower + DP/SecAgg, treatment rules) and kept the current NVFlare / BRCA /
  synthetic-then-TCGA project. One idea adopted: turn the Nemotron report into a case agent that
  calls our model as tools (risk, modality contributions, top genes) and Tavily, then writes the
  tumor-board summary (#21, built in #23).
- **Why:** the full spec is a multi-week build that needs GPUs and gated, often non-commercial
  models; Flower would replace NVFlare (NVIDIA's own FL SDK); paid Nebius compute is out
  (decision above). The one real risk it raised is a "superficial use" of Nemotron at stage-one
  judging; an agent that plans tool calls answers that cheaply on the free credits.
- **Consequence:** #21 is built offline against a fake client and tested live once the key
  arrives (~Oct 19). Still unverified on Devpost: model-size guidance (Nano/Super vs Ultra), a
  feedback award, and award-stacking rules.

## 2026-10-17 — TCGA-BRCA cohort: Xena GDC hub, CNV as "genomic", RPPA as "protein", OS
- **What:** `scripts/prepare_tcga.py` (logic in `muffle.data.tcga`) builds
  `data/tcga_brca/cohort.npz` from open-tier files on the UCSC Xena GDC hub, one 01A primary
  tumour per patient. genomic = gene-level copy number (ASCAT3) as calls −2..2 relative to
  tumour ploidy, not mutation calls; protein = TCGA RPPA instead of CPTAC; endpoint = overall
  survival. The 3 GB methylation file is streamed and only the selected CpGs are cached.
  Top-variance features are ranked on the log / M scale *before* z-scoring.
- **Why:** open tier needs no application. CPTAC mass spec covers only ~100 TCGA-BRCA tumours,
  RPPA ~80% of the cohort, so protein becomes a real fourth omic layer (`--skip protein` gives
  the mask-0 variant). After z-scoring every feature has variance 1, so ranking afterwards
  would pick features arbitrarily.
- **Consequence:** BRCA OS has few deaths (event rate ~0.14), so per-site C-indexes will be
  noisy; PFI from the TCGA-CDR table is the fallback endpoint. Feature selection is pooled and
  unsupervised; a real federation would agree on features with `harmonize_features`. The
  cohort stores `tss` (tissue source site) per patient for the hospital split (#3).

## 2026-10-17 — Nebius: Token Factory only, on the free hackathon credits
- **What:** our Nebius usage is the Nemotron report via Token Factory, paid for with the free
  hackathon credits (event code on the Devpost page) and nothing else. FL training stays in the
  NVFlare simulator on the Mac; the AI Cloud Serverless Job (GPU) is dropped. Host the demo on a
  free tier (Streamlit Community Cloud), not a Nebius Serverless Endpoint.
- **Why:** the team doesn't want to pay for Nebius. Token Factory alone meets "runs on Nebius"
  and "uses an NVIDIA open model"; the GPU job was the costly part and our cohorts train fine on
  a laptop.
- **Consequence:** issues #4 and #8 updated. `docs/NEBIUS.md`, the Dockerfile and `--gpu` stay
  for later if credits allow. Keep report calls short and watch the credit balance, especially
  once judges use the hosted demo (#13).

## 2026-10-17 — Score FedAvg with the final global model, over several seeds
- **What:** `make compare` scores `FL_global_model.pt` (the last round) on the same per-site
  validation splits as the baselines. Don't report `best_FL_global_model.pt`: NVFlare picks it
  with those same validation C-indexes, so it is optimistic.
- **Why:** per-site validation sets are small (26–94 patients), so a single run's per-site gaps
  of ~0.01 are noise (bootstrap 95% CIs ±0.04–0.10). Over 5 synthetic cohorts the mean C-index
  was local-only 0.737 < FedAvg 0.744 < centralized 0.749, but the per-site order held in only
  1–2 of 5 seeds.
- **Consequence:** report results as mean ± sd over seeds (or on a larger pooled test set). On
  synthetic data local-only is already close to centralized, so the "FL ≫ local-only" story
  needs smaller / more heterogeneous sites or real TCGA sites.

## 2026-10-16 — Target the Nebius × NVIDIA Global AI Hackathon (Devpost), track "Best Apps and Agents"
- **What:** add a Nemotron (Token Factory) patient report + Tavily literature lookup; run FL
  training as a Nebius Serverless Job; MIT license; repo public before submission.
- **Why:** entry rules require running on Nebius and using ≥1 NVIDIA open-source model; there is
  no healthcare track, and an app powered by Nemotron fits "Best Apps and Agents".
- **Consequence:** the plan's Oct–Dec timeline is compressed to 14 days (see `HACKATHON.md`).

## 2026-10-16 — One Mac, one GitHub account, Claude Code for local work
- Repo at `~/PycharmProjects/muffle-plus-plus`; branches + PRs with CI as the gate.

## 2026-10-16 — Start on synthetic data, simulate clients on one machine
- Develop against `scripts/make_synthetic.py` until TCGA is harmonized; run all FL clients in
  the NVFlare simulator.

## 2026-10-16 — NVFlare Recipe API
- `FedAvgRecipe` + `SimEnv` (NVFlare 2.8/2.9). The model is passed as `{class_path, args}`.

## Open questions
- [ ] First cancer: BRCA (most data) — confirm. BLCA second only if time allows.
- [x] Demo hosting: Streamlit Community Cloud (2026-10-18 entry).
- [x] Which Nemotron id on Token Factory: `nvidia/nemotron-3-super-120b-a12b` (2026-10-18 entry).

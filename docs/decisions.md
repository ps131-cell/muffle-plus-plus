# Decision log

Newest at the top. One entry per decision: date, what, why.

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
- [ ] Demo hosting: Streamlit Community Cloud vs Nebius Serverless Endpoint.
- [ ] Which Nemotron id on Token Factory (run `--list-models`).

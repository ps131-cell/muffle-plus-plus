# Decision log

Newest at the top. One entry per decision: date, what, why.

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

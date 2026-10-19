# Hackathon target: Nebius × NVIDIA Global AI Hackathon (Devpost)

Researched 2026-10-16 from nebiusglobalaihackathon.devpost.com and its rules page.
Re-check the Devpost page before submitting — rules can be updated.

- **Deadline: Fri Oct 30, 2026, 10:00 am Pacific (12:00 pm Central).**
- Online; teams allowed; pre-existing work allowed if significantly updated during the period.
- Judging Dec 1–15; four equally weighted criteria: Technological Implementation, Design
  (a complete product, not a proof of concept), Potential Impact, Quality of the Idea.
  Stage one is pass/fail on whether the required platform + model are actually used.

## Hard requirements → how MuFFLe++ meets them

| Requirement | Our answer | Status |
|---|---|---|
| Runs on Nebius Token Factory **or** AI Cloud (Serverless Jobs / Endpoints / DevPods) | Nemotron report calls Token Factory at runtime, on the free hackathon credits (FL stays in the NVFlare simulator; Serverless Job cut — see decisions 2026-10-17) | Done: the case agent calls Nemotron 3 Super and Ultra on Token Factory at runtime (decisions 2026-10-18) |
| Uses ≥1 NVIDIA open-source model (e.g. Nemotron) | `src/muffle/report/nemotron.py` writes the prognosis report with Nemotron | Done: Nemotron 3 Super and Ultra |
| Fits a track | **Best Apps and Agents** (an app people would use, powered by Nemotron on Token Factory) | Done |
| Public repo, OSI license visible in the About section | MIT `LICENSE` | Done: public, MIT (checked with `gh repo view` on 2026-10-19) |
| README: setup/run + how NVIDIA models, Token Factory, other Nebius tools are used | README "Hackathon" section | In progress: PR #53 open; final numbers and URL on Oct 27 |
| Working demo URL, free to test through Dec 15 | Streamlit app hosted on a free tier (Streamlit Community Cloud) | Hosted at https://cancer-intelligence-platform.streamlit.app; the live case agent waits for the keys in the Streamlit secrets (user action); bundle v2 pending |
| Public YouTube video ≤ 3 min, no copyrighted music | Script below | Script drafted (PR #47); not recorded |
| Text description + feedback on Token Factory / AI Cloud / NVIDIA tools | Draft in `docs/submission.md` | Drafted (PR #42) |
| Third-party data used under its terms | TCGA open tier; GDC masked somatic mutations (open); CIViC (CC0); MSK-CHORD (CC BY-NC-ND 4.0) used locally with only aggregate results published, never shown in the demo or video (`docs/registry.md`) | Done (`docs/registry.md`) |

Bonus: **Best Use of Tavily** ($3k) — the report's literature lookup uses Tavily.
Credits: event code on the Devpost page (Token Factory) + Nebius Builders Program.

## Plan (Oct 16 → Oct 30)

Done Oct 16–18: TCGA-BRCA cohort, hospital split, FedAvg vs local-only vs pooled with
leave-one-site-out, clinical-anchored residual model, calibration and fairness checks, live
Nemotron case agent with Tavily and a spending cap, demo redesign. Since Oct 18 the project is
milestone 1 of the cancer intelligence platform (`docs/VISION.md`, decisions 2026-10-18):

| Days | Platform work (milestone 1) | Product / submission |
|---|---|---|
| Oct 18–19 | **Done.** Vision in the docs; evidence labels in the case note (#43) | — |
| Oct 19–21 | **Done.** Observed driver mutations from GDC open MAFs and CIViC treatment evidence for clinician review (#46) | **Done.** `docs/registry.md` (#52) |
| Oct 21–24 | **Done.** MSK-CHORD timelines (local only), 12-month risk re-predicted at each new event, measured against baselines as the record grows (#48) | — |
| Oct 24–26 | **Done.** Synthetic timeline patient (labeled) in the demo: the profile updates with each result and records what changed and why (#49) | **Done.** Demo hosted on Streamlit Community Cloud on Oct 19 (#50) |
| Oct 27 | Final numbers into README and decisions | Description + feedback draft |
| Oct 28 | **Freeze** | Record + upload video, make the repo public, protect `main` |
| Oct 30 | — | **Submit before 10 am PT** |

Open scope decisions: a survey of pretrained models and datasets per test type (`docs/model_survey.md`,
in progress) and the clinician workspace (`docs/WORKSPACE.md`, PR #54).

Scope cuts if behind (in order): the synthetic patient's richness (fewer event types), CIViC
beyond the top drivers, registry depth, FedProx / DP / BLCA (not planned).
Already cut (2026-10-17): FL as a Nebius Serverless Job — Nebius usage is Token Factory only, on free credits.

## 3-minute video outline (platform framing, decisions 2026-10-18)
1. 0:00 (~20 s) Problem: a cancer changes over time, and the evidence about one patient is
   scattered across tests, visits and hospitals that can't pool data.
2. 0:20 (~80 s) Demo first: a **synthetic** (labeled) patient timeline; as new results arrive
   the profile updates, separating observed findings (stage, sequenced drivers), model
   inferences (risk now vs before, which data layers drove it) and hypotheses (literature,
   CIViC evidence for clinician review), and the Nemotron case agent says what changed and why.
3. 1:40 (~50 s) Results: risk estimates on real MSK-CHORD timelines as records grow (aggregate);
   FedAvg across hospitals beats any hospital alone without moving data; honest clinical
   baseline.
4. 2:30 (~20 s) Stack and roadmap: NVIDIA FLARE, Nemotron on Nebius Token Factory, Tavily,
   CIViC; next, pathology and radiology encoders and real contributing institutions.

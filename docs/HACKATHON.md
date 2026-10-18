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
| Runs on Nebius Token Factory **or** AI Cloud (Serverless Jobs / Endpoints / DevPods) | Nemotron report calls Token Factory at runtime, on the free hackathon credits (FL stays in the NVFlare simulator; Serverless Job cut — see decisions 2026-10-17) | [ ] |
| Uses ≥1 NVIDIA open-source model (e.g. Nemotron) | `src/muffle/report/nemotron.py` writes the prognosis report with Nemotron | [ ] |
| Fits a track | **Best Apps and Agents** (an app people would use, powered by Nemotron on Token Factory) | [ ] |
| Public repo, OSI license visible in the About section | MIT `LICENSE`; make the repo public before submitting | [ ] |
| README: setup/run + how NVIDIA models, Token Factory, other Nebius tools are used | README "Hackathon" section | [ ] |
| Working demo URL, free to test through Dec 15 | Streamlit app hosted on a free tier (Streamlit Community Cloud) | [ ] |
| Public YouTube video ≤ 3 min, no copyrighted music | Script below | [ ] |
| Text description + feedback on Token Factory / AI Cloud / NVIDIA tools | Draft in `docs/submission.md` | [ ] |
| Third-party data used under its terms | TCGA open tier; CHIMERA is CC BY-NC-SA (non-commercial OK) | [ ] |

Bonus: **Best Use of Tavily** ($3k) — the report's literature lookup uses Tavily.
Credits: event code on the Devpost page (Token Factory) + Nebius Builders Program.

## 14-day plan (Oct 16 → Oct 30)

| Days | Data / modeling | FL / platform / product |
|---|---|---|
| Oct 16–18 | TCGA-BRCA download + `prepare_tcga.py` (RNA, CNV, methylation, clinical, OS) | Env on Mac, CI green, Nebius account + credits, Token Factory key, list Nemotron ids |
| Oct 19–21 | Single-modality baselines; split sites by tissue-source-site | FL sim on real data; FedAvg vs local-only vs centralized table |
| Oct 22–24 | Multi-modal fusion, modality gaps, leave-one-site-out | ~~Run FL as Nebius Serverless Job on GPU~~ (cut); Nemotron report + Tavily |
| Oct 25–27 | Calibration/fairness quick checks; pick final model | Streamlit polish, host demo, README hackathon section |
| Oct 28–29 | Freeze results, figures | Record + upload video, write description + feedback, make repo public |
| Oct 30 | — | **Submit before 10 am PT** |

Scope cuts if behind (in order): proteomics, DP/secure aggregation, BLCA second cancer, FedProx.
Already cut (2026-10-17): FL as a Nebius Serverless Job — Nebius usage is Token Factory only, on free credits.

## 3-minute video outline (agreed 2026-10-18, see decisions.md)
1. 0:00 (~20 s) Problem: hospitals can't pool patients' genomic data; models stay small.
2. 0:20 (~80 s) Demo first: one held-out patient → the Nemotron case agent's tool calls
   (risk, which data layers drove it, top genes, literature) → its tumor-board summary.
3. 1:40 (~50 s) Results: FedAvg beats every hospital training alone without moving data;
   honest clinical baseline (omics don't beat stage and age on overall survival yet).
4. 2:30 (~20 s) Stack: NVIDIA FLARE, Nemotron on Nebius Token Factory, Tavily.

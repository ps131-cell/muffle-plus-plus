# Hackathon target: Nebius × NVIDIA Global AI Hackathon (Devpost)

Researched 2026-10-16 from nebiusglobalaihackathon.devpost.com and its rules page.
Re-check the Devpost page before submitting — rules can be updated.

- **Deadline: Fri Oct 30, 2026, 10:00 am Pacific (12:00 pm Central).**
- Online; teams allowed; pre-existing work allowed if significantly updated during the period.
- Judging Dec 1–15; four equally weighted criteria: Technological Implementation, Design
  (a complete product, not a proof of concept), Potential Impact, Quality of the Idea.
  Stage one is pass/fail on whether the required platform + model are actually used.

## Hard requirements → how MuFFLe++ meets them (status 2026-10-22)

| Requirement | Our answer | Status |
|---|---|---|
| Runs on Nebius Token Factory **or** AI Cloud (Serverless Jobs / Endpoints / DevPods) | The case agent calls Nemotron on Token Factory at runtime, on the free hackathon credits, through a hard $25.50 cap (`src/muffle/report/nemotron.py`, `budget.py`); FL stays in the NVFlare simulator (Serverless Job cut, decisions 2026-10-17) | **Met**: every TCGA file's case note; the app names Token Factory on each note |
| Uses ≥1 NVIDIA open-source model (e.g. Nemotron) | Nemotron 3 Super plans and calls tools; Nemotron 3 Ultra writes the note | **Met** (decisions 2026-10-18) |
| NVIDIA tools (not required; part of the story) | NVIDIA FLARE `FedAvgRecipe` trains the risk model across three simulated hospitals (`jobs/fedavg_job.py`) | **Met**: shown in the app's sidebar and Methods page |
| Fits a track | **Best Apps and Agents** (a clinician app powered by a Nemotron agent on Token Factory) | **Met** |
| Public repo, OSI license visible in the About section | MIT `LICENSE` | **Met** (public, MIT; checked 2026-10-19) |
| README: setup/run + how NVIDIA models, Token Factory, other Nebius tools are used | README "Quick start" and "Hackathon: how NVIDIA and Nebius are used" | **Met** (rewritten 2026-10-22); add the video link at submission |
| Working demo URL, free to test through Dec 15 | https://cancer-intelligence-platform.streamlit.app (Streamlit Community Cloud, no login; release `demo-bundle-v2`) | **Met**; reboot after the freeze and check the sidebar says live |
| Public YouTube video ≤ 3 min, no copyrighted music | Script and shot list in `docs/video.md` (2:58) | **Pending**: record after the running sessions land (re-check list in `docs/video.md`) |
| Text description + feedback on Token Factory / AI Cloud / NVIDIA tools | `docs/submission.md` (Devpost sections, feedback, numbers appendix) | **Pending**: drafted 2026-10-22; numbers check Oct 27; paste into Devpost |
| Third-party data used under its terms | Every source with its license and what is published: `docs/registry.md`; MSK-CHORD (CC BY-NC-ND 4.0) local only, aggregate results only, never in the app, the video or an LLM call | **Met** |
| Pre-existing work disclosed | The slide workbench follows the team's colon tumor-front analyzer's design; disclosure in `docs/submission.md` (Data) and `docs/registry.md` | **Met** in the text; keep it in the Devpost form |

Bonus: **Best Use of Tavily** ($3k) — the report's literature lookup uses Tavily.
Credits: event code on the Devpost page (Token Factory) + Nebius Builders Program.

## Plan (Oct 16 → Oct 30)

Done Oct 16–21: TCGA-BRCA cohort, simulated hospitals, FedAvg vs local-only vs pooled with
leave-one-site-out, calibration; the Nemotron case agent with Tavily, CIViC and a spending cap;
observed driver mutations; MSK-CHORD timelines and the synthetic timeline patient; the hosted
app; the registry; the clinician app (decisions 2026-10-19) with eight workbenches, import, the
overview and attention queue, cross-test rules, the timeline and the Methods page.

| Days | Product | Submission |
|---|---|---|
| Oct 22–26 | Running sessions land: navigation and clarity, documents round 2, timeline round 2, clinician feedback ledger, encoder comparison. Nothing new starts after Oct 26 | Submission materials rewritten (Oct 22); record a first take of the video early from `docs/video.md` |
| Oct 27 | Final numbers pass: each figure in `docs/submission.md`'s numbers appendix checked against its source; README and decisions agree | Re-walk the video's re-check shots; final Devpost text |
| **Oct 28** | **Freeze**: `main` protected; only fixes to submission material after this, with the user's OK | Record and upload the video (public); reboot the hosted app and check it |
| Oct 29 | — | Fill the Devpost form from `docs/submission.md`; video and demo links in the README |
| **Oct 30** | — | **Submit before 10:00 am PT** (12:00 pm Central); re-check the Devpost page's rules first |

Scope cuts if behind (in order): drop a running session's feature rather than land it half-done;
drop the video shots it would have needed (`docs/video.md` "30-second fallback cuts").
Already cut (2026-10-17): FL as a Nebius Serverless Job; Nebius usage is Token Factory only, on
free credits.

## 3-minute video
The script and shot list are in [`video.md`](video.md) (rewritten 2026-10-22): it walks the
clinician path in the app (Patients → a file's overview → workbenches → Evolution → Timeline →
Methods and validation) and says Nemotron on Token Factory and NVIDIA FLARE where the app shows
them. The earlier platform-framing outline (decisions 2026-10-18) is superseded by the clinician
framing (decisions 2026-10-19).

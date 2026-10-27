# Hackathon target: Nebius × NVIDIA Global AI Hackathon (Devpost)

Researched 2026-10-16 from nebiusglobalaihackathon.devpost.com and its rules page.
Re-check the Devpost page before submitting — rules can be updated.

- **Deadline: Fri Oct 30, 2026, 10:00 am Pacific (12:00 pm Central).**
- Online; teams allowed; pre-existing work allowed if significantly updated during the period.
- Judging Dec 1–15; four equally weighted criteria: Technological Implementation, Design
  (a complete product, not a proof of concept), Potential Impact, Quality of the Idea.
  Stage one is pass/fail on whether the required platform + model are actually used.

## Hard requirements → how MuFFLe++ meets them (status 2026-10-27)

| Requirement | Our answer | Status, and where to see it |
|---|---|---|
| Runs on Nebius Token Factory **or** AI Cloud (Serverless Jobs / Endpoints / DevPods) | The case agent calls Nemotron on Token Factory at runtime, on the free hackathon credits, through a hard $25.50 cap (`src/muffle/report/nemotron.py`, `budget.py`); FL stays in the NVFlare simulator (Serverless Job cut, decisions 2026-10-17) | **Met**: every TCGA file's **Tumor-board note** names Nemotron and Token Factory; sidebar › About this system says "Case agent · live"; video shot 4 |
| Uses ≥1 NVIDIA open-source model (e.g. Nemotron) | Nemotron 3 Super plans and calls tools; Nemotron 3 Ultra writes the note | **Met** (decisions 2026-10-18): nine saved notes in release `demo-bundle-v2`, live notes on the hosted app; video shot 4 |
| NVIDIA tools (not required; part of the story) | NVIDIA FLARE `FedAvgRecipe` trains the risk model across three simulated hospitals (`jobs/fedavg_job.py`) | **Met**: Methods and validation › Federated training across simulated hospitals; README results table; video shot 12 |
| Fits a track | **Best Apps and Agents** (a clinician app powered by a Nemotron agent on Token Factory); bonus **Best Use of Tavily** | **Met**: `docs/submission.md` (Track) |
| Public repo, OSI license visible in the About section | MIT `LICENSE` | **Met**: https://github.com/ps131-cell/muffle-plus-plus (public, MIT; checked 2026-10-19) |
| README: setup/run + how NVIDIA models, Token Factory, other Nebius tools are used | README "Quick start" and "Hackathon: how NVIDIA and Nebius are used" | **Met**: README (status and numbers checked 2026-10-27); add the video link on Oct 28 |
| Working demo URL, free to test through Dec 15 | https://cancer-intelligence-platform.streamlit.app (Streamlit Community Cloud, no login; release `demo-bundle-v2`) | **Met**; reboot after the freeze (Oct 28) and check About this system (0.728, live) |
| Public YouTube video ≤ 3 min, no copyrighted music | Script, recording checklist and shot list in `docs/video.md` (2:58), every shot re-checked on Oct 27 | **Pending**: record Oct 27–28, upload public |
| Text description + feedback on Token Factory / AI Cloud / NVIDIA tools | `docs/submission.md`: the Devpost sections in the form's order, feedback, numbers appendix, submission checklist | **Ready** (numbers pass 2026-10-27); paste into Devpost on Oct 29 |
| Third-party data used under its terms | Every source with its license and what is published: `docs/registry.md`; MSK-CHORD (CC BY-NC-ND 4.0) local only, aggregate results only, never in the app, the video or an LLM call | **Met**: `docs/registry.md`; Methods and validation › Data sources and licenses |
| Pre-existing work disclosed | The slide workbench follows the team's colon tumor-front analyzer's design; disclosure in `docs/submission.md` (Data, licenses and prior work) and `docs/registry.md` | **Met** in the text; keep it in the Devpost form |

Bonus: **Best Use of Tavily** ($3k) — the report's literature lookup uses Tavily.
Credits: event code on the Devpost page (Token Factory) + Nebius Builders Program.

## Plan (Oct 16 → Oct 30)

Done Oct 16–21: TCGA-BRCA cohort, simulated hospitals, FedAvg vs local-only vs pooled with
leave-one-site-out, calibration; the Nemotron case agent with Tavily, CIViC and a spending cap;
observed driver mutations; MSK-CHORD timelines and the synthetic timeline patient; the hosted
app; the registry; the clinician app (decisions 2026-10-19) with eight workbenches, import, the
overview and attention queue, cross-test rules, the timeline and the Methods page. Done Oct
22–26: navigation and clarity, documents round 2, timeline round 2 with time travel, the
Feedback page, the encoder comparison, QA round 2 (334 screens, 29 findings; minor ones left
listed in `docs/qa.md`).

| Day | Product | Submission |
|---|---|---|
| **Oct 27** | Last merges: the GigaPath-Flash re-score of the eight slide sections if it passes its gate (merged and checked by 18:00 Chicago; otherwise QuiltNet-B-32 stays), the minor QA fixes and the UI round started that day (workbench launcher tiles, workbench polish, search across files, speed), each whole with CI green or not at all. Final numbers pass: every figure in `docs/submission.md`'s appendix against its source (done 2026-10-27) | Video re-check shots walked (done); re-walk the shots the day's UI work touches (`docs/video.md`), then record |
| **Oct 28** | **Freeze**: protect `main` (branch protection: PRs only, CI required, no force pushes); after this only fixes to submission material, with the user's OK. Reboot the hosted app from the Streamlit dashboard, open it, check About this system (Held-out C-index 0.728, Case agent live), open one slide section and one saved note | Upload the video to YouTube as public; add its link to the README and `docs/submission.md` |
| Oct 29 | — | Fill the Devpost form from `docs/submission.md` (its submission checklist: video URL, repo URL, app URL, team members, tags); save as draft; re-read it once on the page |
| **Oct 30** | — | Re-check the Devpost page's rules, then **submit before 10:00 am PT** (12:00 pm Central); after submitting, open the public project page and check the links |

Scope cuts if behind (in order): drop a running session's feature rather than land it half-done;
drop the video shots it would have needed (`docs/video.md` "30-second fallback cuts").
Already cut (2026-10-17): FL as a Nebius Serverless Job; Nebius usage is Token Factory only, on
free credits.

## 3-minute video
The script, recording checklist and shot list are in [`video.md`](video.md) (re-checked
2026-10-27 in a headless browser at 1280 px): it walks the clinician path in the app (Patients →
a file's overview → workbenches → Evolution → Timeline with time travel → Methods and
validation → Feedback) and says Nemotron on Token Factory and NVIDIA FLARE where the app shows
them. The earlier platform-framing outline (decisions 2026-10-18) is superseded by the clinician
framing (decisions 2026-10-19).

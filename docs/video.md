# Demo video: script and shot list

Rewritten 2026-10-22 against `main` at b164264, for recording as early as possible. The screen
shows the clinician application as a clinician would walk it: Patients → a patient file's
overview → its tests and workbenches → Evolution → Timeline → Methods and validation
(`docs/WORKSPACE.md`). The hackathon story (Nemotron on Nebius Token Factory, NVIDIA FLARE) is
said in the voice-over only where the app itself shows that provenance: the case note's
"written on Nebius Token Factory" line, the sidebar and the Methods page's federated training
section. Every number said comes from a method note, the registry or a decisions entry (source
in the shot's row); if the page shows something else, say what the page shows and fix this file.

## Devpost rules for the video
- **3:00 at most** (judges may stop there); this script runs 2:58.
- Public on YouTube; link in the README and the Devpost form.
- Shows the project working, and how Nebius Token Factory and NVIDIA Nemotron are used (shot 4).
- No copyrighted music (none, or a CC0 track); say product names, show no third-party logos.
- Never an individual MSK-CHORD patient. The synthetic patient, the synthetic ctDNA series and
  the simulated hospitals stay labeled on screen and in the voice-over.

## Screens still changing: re-check before recording
Sessions running on 2026-10-22 will change these screens. Re-walk each marked shot on the hosted
app after they land and update the clicks and words here.

| Running work | Shots it touches | What to re-check |
|---|---|---|
| Navigation and clarity (page skeleton, breadcrumbs, guide) | all, most of all 1–3 | where the search, filters, view switch and "← All patients" sit; whether a test still opens by selecting its row; whether `?view=` still works |
| Documents round 2 (an open oncology NER model next to the rules) | 9 | the facts table's columns and labels; say "rules" or "rules and a named-entity model" as the page does |
| Timeline round 2 (horizontal timeline, time travel) | 11 | the clicks for opening a past version and comparing two |
| Clinician feedback ledger | 3, 11, 12 | whether review marks now show a ledger somewhere a shot passes through |
| Encoder comparison (may replace QuiltNet-B-32) | 5, 12 | the tissue head's encoder name and its held-out accuracy (87.7% today) |

## Before recording
- [ ] Freeze done (Oct 28) or the screens above re-checked. Hosted app
      (https://cancer-intelligence-platform.streamlit.app) woken and rebooted from the Streamlit
      dashboard; it loads the release `demo-bundle-v2`, so the sidebar's **Held-out C-index**
      reads **0.728** (decisions 2026-10-21). If it reads 0.730 you are on a local rebuild:
      record the hosted app or start it with `--bundle`.
- [ ] Sidebar says the case agent is **live** (the Token Factory key is in the Streamlit
      secrets). Never show the secrets page, `.env` or a terminal.
- [ ] Open every slide section used in shot 5 once before recording: the first open of a section
      downloads its tile zip from the release `slide-tiles-v1` (13–175 MB) and waits.
- [ ] 1920×1080, light theme, browser zoom 110%, bookmarks bar hidden, one tab.
- [ ] Walk the shot list once with the URLs below and note anything that differs.

## URLs
Base `https://cancer-intelligence-platform.streamlit.app`. A file's address is
`?patient=<id>`; its view is `&view=Report|Tests|Timeline|Evolution|Import%20tests` (both are
bound to the URL in `app/streamlit_app.py`). A workbench opens by selecting its test row in
**Tests**; it has no URL of its own.

| Screen | URL | Then |
|---|---|---|
| Patients | `/` | — |
| Case 299, overview | `/?patient=Case%20299&view=Report` | — |
| Case 299, slide viewer | `/?patient=Case%20299&view=Tests` | select the pathology slide row |
| Case 299, genomics | `/?patient=Case%20299&view=Tests` | select the sequencing row |
| Case 937, omics | `/?patient=Case%20937&view=Tests` | select an expression (RNA) row |
| Case 937, radiology | `/?patient=Case%20937&view=Tests` | select the imaging row |
| Case 299, documents | `/?patient=Case%20299&view=Tests` | select the pathology report row (fallback: Case 545) |
| SYNTHETIC-001, labs and ctDNA | `/?patient=SYNTHETIC-001&view=Tests` | select the CA 15-3 row, then the ctDNA row |
| SYNTHETIC-001, Evolution | `/?patient=SYNTHETIC-001&view=Evolution` | — |
| SYNTHETIC-001, Timeline | `/?patient=SYNTHETIC-001&view=Timeline` | — |
| Methods and validation | `/methods` | — |

## Shot list and script (2:58; about 360 words of voice-over)

"On screen" names the label the viewer sees, so the words never claim more than the label.
Labels: **observed**, **model inference**, **hypothesis**, **synthetic**, **simulated**,
**placeholder**; module status: implemented, experimentally validated, planned.

| # | Time | On screen (clicks) | Label on screen | Voice-over | Number's source |
|---|---|---|---|---|---|
| 1 | 0:00–0:10 (10 s) | **Patients** (`/`): title, the line "Research and decision support for clinicians; not a diagnosis or a prescription", the list. *Re-check (navigation).* | synthetic (SYNTHETIC-001's Kind column), simulated (each TCGA row's hospital) | "A breast cancer changes over time, and its evidence is scattered across tests. This is one clinician's patient list." | — |
| 2 | 0:10–0:20 (10 s) | Type **PIK3CA** in the search; then clear it, set **Stage** III and switch on **Open SOS alerts only**. *Re-check (navigation).* | model inference (the PAM50 column's help), observed (mutated genes) | "Search by gene, subtype or stage, or show only files with an alert nobody has reviewed. These are public TCGA patients the model never trained on." | — |
| 3 | 0:20–0:38 (18 s) | Open **Case 299** (`/?patient=Case%20299&view=Report`): the finding cards. Click one card's **Why?** popover (source test, method and version, threshold source, trust). Then the **Attention** queue: press **J** until the slide pointer T1, then **Open** (or **O**): it lands on that pointer in the slide workbench. *Re-check (navigation, feedback ledger).* | each card's own label: observed (stage, receptors), model inference (risk, PAM50), hypothesis (top evolution item); trust badges; placeholder weights on the queue order | "A file opens on an overview: one card per workbench, each labeled observed, inferred or hypothesis. Why? names the test, the method and the threshold's source. One queue gathers everything that needs a look; Open lands on the evidence." | — |
| 4 | 0:38–0:48 (10 s) | Back to Report, scroll to **Tumor-board note** → **Show the saved note**: labeled bullets, the green grounding check, the line naming Nemotron 3 Super and Ultra on Nebius Token Factory; open the evidence chain for one sentence. | observed / model inference / hypothesis per bullet | "The case note: Nemotron 3 Super gathers the evidence and Nemotron 3 Ultra writes it, on Nebius Token Factory. A plain-code check ties every number and gene to a tool." | `docs/decisions.md` 2026-10-18 (case agent) |
| 5 | 0:48–1:10 (22 s) | **Tests** → pathology slide: the patient's own section in the viewer. Zoom to the front; the arrows per arc; a breakaway candidate in its counting field; click a tile → **Spot panel** with the counted nuclei; switch on the second-opinion lymphocyte layer. *Re-check (encoder comparison).* | model inference (tissue map, nuclei, TIL model), hypothesis (direction of invasion), placeholder (cutoffs carried over from colon) | "The patient's own slide. A tissue head on an open pathology encoder maps tumor, stroma and lymphocytes; arrows show where the front invades, a hypothesis about this section. Zoom in to the counted nuclei. A second model checks the lymphocytes and flags where the two disagree." | `docs/pathology.md` §7–8 |
| 6 | 1:10–1:22 (12 s) | **Tests** → sequencing: **The tumor's genome**: the copy-number landscape; open a pathway in **Pathway map**; one variant's **Predicted** rung beside **Detected** and **Interpreted**. | observed (variants, copy numbers), placeholder (copy-number cutoffs), model inference (predicted effect), hypothesis (CIViC) | "The genome: copy number across the chromosomes, the altered pathways, and each variant's predicted effect kept apart from what was detected and how it is interpreted." | `docs/genomics.md` |
| 7 | 1:22–1:34 (12 s) | Case 937 **Tests** → an expression row: **PAM50 intrinsic subtype** (Luminal A, its margin, the validation line); **Protein pathway activity (RPPA)**: one pathway; **Promoter methylation**: the ESR1 row. | model inference (PAM50, pathways), experimentally validated (PAM50 status), observed + placeholder cutoffs (methylation) | "Another patient's expression, protein and methylation. The subtype call agrees with TCGA's published calls 94.7 percent of the time on this cohort. A protein pathway, and a promoter methylation call with its cutoff marked placeholder." | `docs/omics.md` (94.7%, 950 tumors) |
| 8 | 1:34–1:52 (18 s) | Case 937 **Tests** → imaging: the DCE-MRI **Viewer**, the **Candidates** with MedSAM contours, candidate C1's kinetics; then **Since the last study** → the expander **Change over time on a public example pair**: both dates' sizes and the change. | model inference (candidates, contours, kinetics), placeholder (kinetic cutoffs), "public example, not a patient file" on the pair | "This patient's breast MRI: candidates contoured by MedSAM, each with size, volume and contrast kinetics; the cutoffs are literature values, marked placeholder. None of these patients has two dates, so change over time runs on a labeled public example pair." | `docs/radiology.md` §2–3 |
| 9 | 1:52–2:02 (10 s) | Case 299 **Tests** → pathology report: the **Documented facts** table; click a fact and it jumps to its sentence, boxed. *Re-check (documents round 2).* | documented (blue), model inference (inferred elsewhere) | "The pathology report: each fact read by rules, shown at its sentence; ER is right 95 percent of the time it is read on held-out reports." | `docs/documents.md` (481 held-out, ER precision 95%) |
| 10 | 2:02–2:22 (20 s) | `/?patient=SYNTHETIC-001&view=Tests`: the yellow synthetic banner stays in frame. CA 15-3 row → labs: the trend against its reference interval, the month-11 rise and **Rise confirmation (EGTM)**. Then the ctDNA row: **Allele fractions over time**, ESR1 emerging. Then **Evolution**: **What to watch next**, one row's sources, **Trials that mention this patient's observed markers**. | synthetic (patient and ctDNA series), observed (lab values), placeholder (ctDNA detection limit), hypothesis (watch list, trials) | "A synthetic patient, written by hand. CA 15-3 rises at month 11, unconfirmed until a second specimen. A synthetic ctDNA series shows ESR1 emerging. Evolution lists what to watch next, each with its papers, and trials for the patient's markers: evidence for review, never a regimen." | `docs/labs.md`, `docs/ctdna.md`, `docs/evolution.md` |
| 11 | 2:22–2:32 (10 s) | **Timeline**: the risk at each version with treatments marked; compare month 11 with month 12 (added, removed, changed). *Re-check (timeline round 2).* | synthetic, model inference (risk) | "Every report version is kept. Month 12 against month 11: the liver progression, and why the risk moved." | `app/timeline_synthetic.json` |
| 12 | 2:32–2:50 (18 s) | `/methods`: a model card's status chip, then **Federated training across simulated hospitals** (the diagram and the leave-one-hospital-out table), then **Every placeholder in the app**. | simulated (hospitals), experimentally validated / implemented / placeholder chips | "Methods and validation: a card per model and rule, with what it gets wrong. The risk model was trained with NVIDIA FLARE across three simulated hospitals; only weights moved. It scores 0.728 on held-out patients, and every placeholder is listed." | `docs/decisions.md` 2026-10-21 (0.728) |
| 13 | 2:50–2:58 (8 s) | End card: repo URL and app URL. | — | "Research support for clinicians, not a diagnosis. Built on NVIDIA FLARE and Nemotron on Nebius Token Factory." | — |

Notes for the edit:
- Shot 10: never crop out the synthetic banner; say "synthetic" in the voice-over as written.
- Shot 12: "0.728" is the demo model's held-out C-index (release `demo-bundle-v2`). Do not say
  0.693 here: that is the README's five-seed pooled federated result, a different quantity. Do
  not say the omics beat clinical data (clinical-only scores 0.702 ± 0.004 on the same split).
- Shot 4: if a live note is shown instead of the saved one, caption the wait "sped up" and say
  "live". The case agent never reads SYNTHETIC-001: its scores come from MSK-CHORD models.
- Shot 8: say "public example pair": it is not Case 937's own change over time.

## 30-second fallback cuts
If the take runs long, cut in this order (each saves the time shown; together about 30 s):
1. Shot 9, documents (10 s): drop it; shot 3's cards already show documented receptors.
2. Shot 2's second half (5 s): show the gene search only.
3. Shot 6, genomics (to 6 s): copy-number landscape only, no pathway or predicted effect.
4. Shot 8's change-over-time half (7 s): candidates and kinetics only.
5. Shot 11, timeline (to 8 s): the comparison only.

Never cut shot 4 (Nemotron on Token Factory), shot 12's FLARE sentence, or a synthetic or
simulated label.

## After recording
- [ ] Length ≤ 2:58; captions readable at 720p.
- [ ] Nothing secret on screen (keys, `.env`, terminal); no MSK-CHORD patient; the synthetic,
      simulated and placeholder labels visible where they appear.
- [ ] Upload to YouTube as **public**; add the link to the README and `docs/submission.md`.

# Demo video: script and shot list

Re-checked 2026-10-27 against `main` after #134 (navigation and clarity, documents round 2,
timeline round 2, the Feedback page, QA round 2): every shot below was opened by its address in
headless Chromium at 1280 px on the release bundle `demo-bundle-v2`, its clicks were driven, and
the labels and numbers here are the ones the screen shows. The screen shows the clinician
application as a clinician would walk it: Patients → a patient file's overview → its tests and
workbenches → Evolution → Timeline → Methods and validation → Feedback (`docs/WORKSPACE.md`). The
hackathon story (Nemotron on Nebius Token Factory, NVIDIA FLARE) is said in the voice-over only
where the app itself shows that provenance: the case note's "on Nebius Token Factory" line, the
sidebar's **About this system** and the Methods page's federated training section. Every number
said comes from a method note, the registry or a decisions entry (source in the shot's row); if
the page shows something else, say what the page shows and fix this file.

## Screens still changing on Oct 27: re-walk these after they land
UI work started on Oct 27 may move clicks this script names. Before recording, re-open the shots
in the right-hand column on the hosted app after the freeze and update the clicks here.

| Work landing on Oct 27 | Shots it touches | What to re-check |
|---|---|---|
| Workbench launcher tiles on Tests; an action row on the file header; clickable overview cards; "where am I" in the sticky header | 3, 5–10 | how a test's workbench opens (today: select its row in **Tests**); where **Why?** and **Open** sit |
| Workbench polish (how-to lines, quick actions, documents jump-to-sentence) | 6, 7, 9, 10 | the tab and section names quoted below |
| Search across every file's findings; "Similar patients" on the report | 2, 3 | the search box's placeholder and what a PIK3CA search lists |
| Slide re-score with GigaPath-Flash (gate: Oct 27, 18:00 Chicago) | 5, 12 | the tissue head's encoder name and held-out accuracy (91.9% with GigaPath-Flash since the re-score; 87.7% with QuiltNet-B-32 before); every slide map changed, cases 730 and 563 now at the right place on the slide; case 926 shows a known-failure warning |
| Minor QA fixes (R2-15, R2-16, R2-18, the MRI at 800 px) | 3, 5, 8 | the breadcrumb's "?", the viewer's first **n** |

## Recording checklist (do these first)
- [ ] **Screen:** 1920×1080, browser zoom 110% (or 1280×720 at 100%: then collapse the sidebar
      with « on every shot but 1 and 12, since at 720 px tall the sidebar and the page header
      leave little of the page in view). One window, one tab, bookmarks bar hidden, no
      notifications.
- [ ] **Browser:** Chrome or Edge (Chromium; the QA rounds checked only Chromium), a fresh
      window or profile, so the patient list's four-step walk-through appears once: click
      **Skip the tour** before recording, so shot 1 starts on the list.
- [ ] **Theme:** light. The app is light-only (`.streamlit/config.toml`); nothing to set, but do
      not use a browser dark-mode extension.
- [ ] **Hosted app** (https://cancer-intelligence-platform.streamlit.app) rebooted from the
      Streamlit dashboard after the freeze and woken: open **About this system** in the sidebar:
      **Held-out C-index · 0.728** (release `demo-bundle-v2`; 0.730 means a local rebuild: record
      the hosted app, or start a local one with `--bundle`) and **Case agent · live**. Close the
      expander again. Never show the secrets page, `.env` or a terminal.
- [ ] **Sidebar:** open for shot 1 (it shows Patients, Methods and validation, Feedback), then
      either way. Type reviewer initials in **Session › Reviewer initials** before shot 3 (your
      own, e.g. `PS`): the queue's **M** (mark reviewed) in shot 3 is what the Feedback page
      shows in shot 12b.
- [ ] **Slide tiles:** open the shot 5 address once before recording: the first open of a section
      on a fresh server downloads its tiles from the release `slide-tiles-v1` (13–175 MB) and
      waits.
- [ ] **No music** (or a CC0 track). Say product names; show no third-party logos.
- [ ] **Import (optional shot, see the fallback list):** have `lab_results_example.csv` ready:
      the import dialog's **Example CSV** button downloads it (synthetic values at month 25:
      CA 15-3 44 U/mL, CEA, liver and bone labs). Import only public or synthetic data.
- [ ] Walk the shot list once with the URLs below, then record.

## Devpost rules for the video
- **3:00 at most** (judges may stop there); this script runs 2:58.
- Public on YouTube; link in the README and the Devpost form.
- Shows the project working, and how Nebius Token Factory and NVIDIA Nemotron are used (shot 4).
- Never an individual MSK-CHORD patient. The synthetic patient, the synthetic ctDNA series and
  the simulated hospitals stay labeled on screen and in the voice-over.

## URLs
Base `https://cancer-intelligence-platform.streamlit.app`. The address reopens a screen
(`docs/ux.md` §2): `?patient=<id>&view=Report|Tests|Timeline|Evolution|Import%20tests`, plus
`&test=<kind>|<month>|<name>` for the workbench open in Tests, `&pointer=<id>` for the finding
the Spot panel lands on and `&version=<index>` for a past report version. Paste them as written:
the slide test's name holds "&" (`H%26E`), so its address must stay encoded. In the take itself,
click as the shot says; the addresses are for rehearsal and for re-takes of one shot.

| Shot | Screen | Address (after the base) |
|---|---|---|
| 1–2 | Patients | `/` |
| 3–4 | Case 299, overview | `/?patient=Case%20299&view=Report` |
| 5 | Case 299, slide workbench on T1 | `/?patient=Case%20299&view=Tests&test=Pathology%20slide%7C%7CDiagnostic%20H%26E%20section%28s%29%20%28GDC%2C%20open%20access%29&pointer=T1` |
| 6 | Case 299, genomics | `/?patient=Case%20299&view=Tests&test=Mutation%20panel%7C%7CSomatic%20mutations%2C%2016%20breast%20cancer%20drivers%20%28exome%20sequencing%29` |
| 7 | Case 937, expression, methylation, protein | `/?patient=Case%20937&view=Tests&test=Data%20layer%7C%7CRNA-seq%20%28STAR%20TPM%29` |
| 8 | Case 937, breast MRI on C1 | `/?patient=Case%20937&view=Tests&test=Imaging%7C%7CBreast%20MRI%20%28dynamic%20contrast-enhanced%29%2C%20public%20TCIA%20study%20%282000-08-24%29&pointer=C1` |
| 9 | Case 563, pathology report | `/?patient=Case%20563&view=Tests&test=Document%7C%7CPathology%20report%20%28TCGA-Reports%29` |
| 10 | SYNTHETIC-001, CA 15-3 on L4 | `/?patient=SYNTHETIC-001&view=Tests&test=Lab%7C11%7CCA%2015-3&pointer=L4` |
| 10 | SYNTHETIC-001, ctDNA monitor | `/?patient=SYNTHETIC-001&view=Tests&test=ctDNA%20%28liquid%20biopsy%29%7C11%7CctDNA%20panel%20%28synthetic%20series%29` |
| 10 | SYNTHETIC-001, Evolution | `/?patient=SYNTHETIC-001&view=Evolution` |
| 11 | SYNTHETIC-001, Timeline (latest; `&version=11` = as of month 12) | `/?patient=SYNTHETIC-001&view=Timeline` |
| 12 | Methods and validation | `/methods` |
| 12b | Feedback | `/feedback` |

## Shot list and script (2:58; about 350 words of voice-over)

"On screen" names the label the viewer sees, so the words never claim more than the label.
Labels: **observed**, **model inference**, **hypothesis**, **documented**, **synthetic**,
**simulated**, **placeholder**; module status: implemented, experimentally validated, planned.
Re-checked: what the 1280 px walk on Oct 27 showed for the shot.

| # | Time | On screen (clicks) | Label on screen | Voice-over | Number's source · re-checked |
|---|---|---|---|---|---|
| 1 | 0:00–0:08 (8 s) | **Patients** (`/`), tour already skipped: the title, the line "Research and decision support for clinicians; not a diagnosis or a prescription.", the list (41 files) with the sidebar's Patients, Methods and validation, Feedback. | synthetic (SYNTHETIC-001's Kind "Synthetic (written by hand)"), simulated (each TCGA row's "simulated site-n") | "A breast cancer changes over time, and its evidence is scattered across tests. This is one clinician's patient list." | — · list, disclaimer and Kind column as written |
| 2 | 0:08–0:16 (8 s) | Type **PIK3CA** in the search box ("Search a patient, a gene (PIK3CA), …"); clear it and switch on **Open SOS alerts only**. | observed (mutated genes), model inference (PAM50 column) | "Search by gene, subtype or stage, or show only files with an alert nobody has reviewed. These are public TCGA patients the model never trained on." | — · search and toggle work; the Stage filter (I, II, III, not recorded) is there if time allows |
| 3 | 0:16–0:34 (18 s) | **Case 299** (click its row): the finding cards; the **PAM50 subtype** card's **Why?** (source test, method and version, threshold, trust, evidence). Scroll to **Attention · 18 items**; press **J** seven times to **8/18 · T1 Risk level 3 region (R1)**; **M** (mark reviewed); **O**: the slide workbench opens on T1 with "← Back to the queue, item 8 of 18". | each card's own label: observed (stage and receptors), model inference (PAM50, risk), hypothesis (evolution); trust chips; "placeholder weights" on the queue order | "A file opens on an overview: one card per workbench, each labeled observed, inferred or hypothesis. Why? names the test, the method and the threshold's source. One queue gathers everything that needs a look; a mark is signed; Open lands on the evidence." | — · Why? popover, J×7 → 8/18 T1, O → `&pointer=T1` and the back link |
| 4 | 0:34–0:44 (10 s) | **← Back to the queue**, scroll to **Tumor-board note** → **Show the saved note**: bullets tagged [Observed], [Model inference], [Hypothesis]; "Grounding check: every number, gene and link in this note comes from the tool outputs."; open **Evidence chain: 42 links from 16 sentences**; the line "Nemotron 3 Super chose these tool calls; Nemotron 3 Ultra wrote the note, on Nebius Token Factory". | observed / model inference / hypothesis per bullet | "The case note: Nemotron 3 Super gathers the evidence and Nemotron 3 Ultra writes it, on Nebius Token Factory. A plain-code check ties every number and gene to a tool." | `docs/decisions.md` 2026-10-18 (case agent) · saved note of 2026-10-19, 20,526 tokens |
| 5 | 0:44–1:06 (22 s) | Back in the slide workbench (the shot 3 address): the patient's own section in the **Slide viewer**; zoom to the front, the arrows per arc, the breakaway counting field; click a tile → **Spot panel**; open **Details › Cells: breakaway candidates, lymphocytes, stroma and necrosis**: **Second opinion**: the WSInfer TIL model scored 1,500 tiles and disagrees with the head on 43 (3%); held-out AUROC 0.955. | model inference (tissue map, nuclei, second model), hypothesis (direction of invasion), placeholder (cutoffs carried over from colon) | "The patient's own slide. A tissue head on an open pathology encoder maps tumor, stroma and lymphocytes; arrows show where the front invades, a hypothesis about this section. Zoom in to the counted nuclei. A second model checks the lymphocytes; where the two disagree, the tile goes to the queue." | `docs/pathology.md` §7–8 · the second opinion is in Details › Cells, not a viewer layer (the viewer colours tissue, certainty, QC, zones, lymphocyte-like nuclei and risk) |
| 6 | 1:06–1:18 (12 s) | **Tests** → the mutation panel row: **Variants and the tumor's genome** → **Copy-number landscape** (MYC, CCND1 amplified), then **Pathway map**; click TP53 R110del: the Spot panel's rungs **Detected** (observed), **Interpreted** (hypothesis, CIViC level C), **Predicted** (model inference: none for a deletion; AlphaMissense scores missense changes only). | observed (variants, copy numbers), placeholder (copy-number cutoffs), hypothesis (CIViC), model inference (predicted effect) | "The genome: copy number across the chromosomes, the altered pathways, and each variant's evidence on its own rung: what was detected, how it is interpreted, what a model predicts." | `docs/genomics.md` · tabs and rungs as named |
| 7 | 1:18–1:28 (10 s) | Case 937 (the shot 7 address): **PAM50 intrinsic subtype**: Luminal A, margin 0.31, the line "agrees with TCGA's published PAM50 calls for 94.7% of 950 tumors (Cohen's kappa 0.92)"; **Protein pathway activity (RPPA)**; **Promoter methylation**: the ESR1 row. | model inference + experimentally validated (PAM50), model inference (pathways), observed + placeholder cutoffs (methylation) | "Another patient's expression, protein and methylation. The subtype call agrees with TCGA's published calls 94.7 percent of the time on this cohort. A protein pathway, and a methylation call with its cutoff marked placeholder." | `docs/omics.md` (94.7%, κ 0.92, 950 tumors; ER-balanced centering chosen after a first run) |
| 8 | 1:28–1:46 (18 s) | Case 937 → the imaging row: the DCE-MRI **Viewer**, **Candidates (3)** with MedSAM contours, C1 in the Spot panel (26.2 mm, 7.43 mL, medium initial enhancement, plateau); then **Change over time on a public example pair (another TCGA-BRCA patient, not this patient)**: both dates' sizes and the change. | model inference (candidates, contours, kinetics), placeholder (kinetic cutoffs), "not this patient" on the pair | "This patient's breast MRI: candidates contoured by MedSAM, each with size, volume and contrast kinetics; the cutoffs are literature values, marked placeholder. None of these patients has two dates, so change over time runs on a labeled public example pair." | `docs/radiology.md` §2–3 · "Since the last study (one study date)" says why |
| 9 | 1:46–1:56 (10 s) | **Case 563** → the pathology report row: yellow facts (documented) and violet underlines (the named-entity model); open **Details › Documented facts (23)**, click the ER fact: it jumps to its sentence; open **The rules and the model, side by side**. | documented (the rules), model inference (the model's spans) | "The pathology report: each fact read by rules and shown at its sentence. Where a report states ER, the rules read it right 95 percent of the time on held-out reports; an oncology language model reads beside them, as a second opinion." | `docs/documents.md` (481 held-out; ER precision 95%; the model mostly marks field names) · Case 299's report holds only 2 facts, so this shot moved to Case 563 |
| 10 | 1:56–2:16 (20 s) | SYNTHETIC-001 (the CA 15-3 address): the yellow synthetic banner stays in frame. The trend against its reference interval, L4's unconfirmed rise at month 11, **Details › Rise confirmation, EGTM (1)**. Then the ctDNA row: **Allele fractions over time**, ESR1 D538G new at month −2. Then **Evolution**: **What to watch next (14)**, one row's papers, **Trials that mention this patient's observed markers (20)**. | synthetic (patient and ctDNA series), observed (lab values), placeholder (ctDNA thresholds), hypothesis (watch list, trials) | "A synthetic patient, written by hand. CA 15-3 rises at month 11, unconfirmed until a second specimen. A synthetic ctDNA series shows ESR1 emerging under an aromatase inhibitor. Evolution lists what to watch next, each with its papers, and trials for the patient's markers: evidence for review, never a regimen." | `docs/labs.md`, `docs/ctdna.md`, `docs/evolution.md` (18 rows, 37 papers) |
| 11 | 2:16–2:28 (12 s) | **Timeline**: the lanes on the month axis, red ▼ alerts; **time travel**: click the month-12 imaging point: the whole file opens as of month 12 ("You are viewing month 12 … Later entries are not in it."), **New in this version**: new liver lesions, 12-month risk 37% → 88%; then **Compare two versions** month 11 against month 12. | synthetic, observed (the record), model inference (risk) | "Every test lands on one timeline. Click any point and the file opens as it stood then: at month 12 the liver progression arrives and the risk jumps. Any two versions compare side by side, with why the risk moved." | `docs/timeline.md`; `app/timeline_synthetic.json` (37% → 88%) · `&version=11` reproduces the click |
| 12 | 2:28–2:44 (16 s) | `/methods`: a model card's status chip, then **Federated training across simulated hospitals** (the diagram and the hospitals table), then **Every placeholder in the app**. | simulated (hospitals), experimentally validated / implemented / placeholder chips | "Methods and validation: a card per model and rule, with what it gets wrong. The risk model was trained with NVIDIA FLARE across three simulated hospitals; only weights moved. It scores a C-index of 0.728 on held-out patients, and every placeholder is listed." | `docs/decisions.md` 2026-10-21 (0.728) · the card: "C-index 0.728, the mean over hospitals (site-1 0.705, site-2 0.665, site-3 0.815)" |
| 12b | 2:44–2:50 (6 s) | **Feedback** (sidebar): the shot 3 mark as a ledger record with the rule behind it, and **What a training round would do with them** (planned). | implemented (the ledger), planned (training) | "Every review mark is kept with the model behind it. Nothing trains on it yet: that needs consent and ethics approval first." | `docs/feedback.md` |
| 13 | 2:50–2:58 (8 s) | End card: repo URL and app URL. | — | "Research support for clinicians, not a diagnosis. Built on NVIDIA FLARE and Nemotron on Nebius Token Factory." | — |

Notes for the edit:
- Shot 10: never crop out the synthetic banner; say "synthetic" in the voice-over as written.
- Shot 12: "0.728" is the demo model's held-out C-index (release `demo-bundle-v2`): the mean of
  the three simulated hospitals' held-out C-indexes, 213 held-out patients. Do not say 0.693
  here: that is the README's five-seed pooled federated result, a different quantity. Do not
  say the omics beat clinical data (clinical-only scores 0.702 ± 0.004 on the same split as
  0.693).
- Shot 4: if a live note is shown instead of the saved one, caption the wait "sped up" and say
  "live". The case agent never reads SYNTHETIC-001: its scores come from MSK-CHORD models.
- Shot 8: say "public example pair": it is not Case 937's own change over time.
- Shot 9: say "a second opinion": the model mostly marks where a field is named, not its value.
- Shot 12b: if no mark was made in shot 3, the page reads "No marks yet": show the roadmap card
  only and drop "kept with the model behind it".

## 30-second fallback cuts
If the take runs long, cut in this order (each saves the time shown; together about 30 s):
1. Shot 9, documents (10 s): drop it; shot 3's cards already show documented receptors.
2. Shot 12b, Feedback (6 s): drop it; keep "a mark is signed" in shot 3.
3. Shot 2's second half (4 s): show the gene search only.
4. Shot 6, genomics (to 6 s): copy-number landscape only, no pathway or rungs.
5. Shot 8's change-over-time half (6 s): candidates and kinetics only.

Optional swap if there is time to spare or shot 9 is cut: **Import** (10 s) on SYNTHETIC-001:
**Import tests** → **Lab results (CSV)** → `lab_results_example.csv`, signed with the reviewer
initials: rows checked one by one, a new report version, the marker-rise alert re-run (label:
"imported by <initials>", kept for this browser session only).

Never cut shot 4 (Nemotron on Token Factory), shot 12's FLARE sentence, shot 11's time travel, or
a synthetic or simulated label.

## After recording
- [ ] Length ≤ 2:58; captions readable at 720p.
- [ ] Nothing secret on screen (keys, `.env`, terminal); no MSK-CHORD patient; the synthetic,
      simulated and placeholder labels visible where they appear.
- [ ] Upload to YouTube as **public**; add the link to the README and `docs/submission.md`.

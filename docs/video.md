# Demo video — script and shot list (draft)

Follows the platform-framing outline in `docs/HACKATHON.md` ("3-minute video outline"). Record on
Oct 27–28, after the freeze checklist below. Numbers come from `app/timeline_synthetic.json`
(synthetic patient) and `docs/longitudinal.md` (MSK-CHORD aggregate); re-check them against
those files if either is regenerated.

## Devpost rules for the video
- **3:00 at most** (judges may stop there); this script runs 2:58.
- Public on YouTube; link in the README and the Devpost form.
- Shows the project working, and how Nebius Token Factory and NVIDIA Nemotron are used (the live
  agent steps in segments 4–5).
- No copyrighted music, and no third-party logos or trademarks shown without permission: no
  music (or a CC0 track); say product names, don't show logos.
- Never shows an individual MSK-CHORD patient. Simulated hospitals and the synthetic timeline
  patient stay labeled as such on screen and in the voice-over.

## Before recording
- [ ] Freeze done: saved notes regenerated in the evidence-labeled format (`make demo-notes`),
      demo bundle rebuilt with mutations (`make demo-bundle`, then a new release), numbers final.
- [ ] Regenerate the saved notes and **bundle v2** on the Mac, after the CIViC matching fix is
      merged, so case 661 shows level-A evidence for PIK3CA H1047R.
- [ ] Run `make agent-tcga PATIENT=661` once and read the note: labels correct, grounding check
      green, no recommendation wording. Fix the prompt, not the video, if it is off.
- [ ] Hosted app (https://cancer-intelligence-platform.streamlit.app): wake it and reboot it from
      the Streamlit dashboard; check all four tabs (Patient timeline (synthetic), Case review,
      Federation, How it works) load without errors.
- [ ] Confirm the Token Factory and Tavily keys are in the Streamlit secrets: the sidebar must say
      **live**, not "offline (no key)". Never show the secrets page or `.env` on screen.
- [ ] Record the local app (`make demo-tcga`) or the hosted URL, at 1920×1080, light theme,
      browser zoom 110%, bookmarks bar hidden, no other tabs, no terminal or `.env` on screen.
- [ ] Write one live note before recording, so the model is loaded and you know the timing. In
      the edit, speed up the agent's 20–30 s wait and caption it "sped up".
- [ ] Case review patient: **case 661**: 99th percentile, stage III, methylation not measured,
      sequenced PIK3CA p.H1047R and TP53 p.N131Tfs*39, so the note shows observed drivers and
      CIViC evidence. Backup: case 710 (PIK3CA p.E545K, all layers measured).
- [ ] Timeline tab: check the yellow synthetic banner is in frame whenever SYNTHETIC-001 shows.

## Script (about 290 words of voice-over; 2:58 total)

Word rates in brackets are voice-over words per minute for that segment (target 80–126).

| Time | On screen | Voice-over |
|---|---|---|
| **0:00–0:20** Problem [~111 wpm] | App title and header | "A breast cancer changes over time, and the evidence about one patient is scattered: a stage, a sequencing report, markers, treatments, across hospitals that can't pool data. MuFFLe++ follows a patient over time without moving patient data." |
| **0:20–1:05** Synthetic timeline [~100 wpm] | First tab *Patient timeline (synthetic)*; the yellow banner says the patient is synthetic. Drag the slider from diagnosis (month −40) to the sequencing event (month 0): risk 38%, range across 5 models, next to the diagnosis-only baseline 44%. Jump to the month-12 liver progression: 88%. Show *what changed and why*, the observed list, then the CIViC items. End at month 24. | "This patient, SYNTHETIC-001, is made up and labeled. At sequencing, the model predicts the twelve-month risk of progression or death: 38 percent, against 44 for diagnosis alone, with the range across five models. At month twelve, new liver lesions: 88 percent, and the page shows why, mostly progression history. Observed facts are listed apart from inference, and CIViC evidence, with its level and citation, is for clinician review. By month 24 it is 60 percent." |
| **1:05–1:16** Real cohort case [~120 wpm] | Case review → select case 661; point at the 99th percentile and the drivers chart; briefly open *What if a data layer were missing?* | "Now a real, held-out TCGA patient: 99th percentile of risk. Methylation was never measured, so the model masks it and still scores." |
| **1:16–1:38** The agent [~93 wpm] | Click *Write the note with Nemotron*; the live steps scroll (sped up), the sidebar shows live | "Nemotron 3 Super, on Nebius Token Factory, chooses which tools to call: observed findings, risk, CIViC evidence for the sequenced mutations, and a Tavily literature search. Nemotron 3 Ultra then writes the tumor-board note." |
| **1:38–1:56** The note [~100 wpm] | Scroll the note: [Observed] PIK3CA H1047R, [Model inference] risk, [Hypothesis] CIViC and literature; the green grounding check; open one tool call | "Every line is labeled observed, model inference or hypothesis. Treatment evidence is for clinician review, never a recommendation. A plain-code check confirms every number and gene came from a tool." |
| **1:56–2:11** MSK-CHORD result [~112 wpm] | A slide or the aggregate table from `docs/longitudinal.md` only: AUROC by landmark, record so far vs diagnosis only. No individual patient. | "On 5,368 real MSK-CHORD breast cancer timelines, the record so far gives AUROC 0.88 at sequencing and 0.93 two years later, against 0.66 to 0.71 from diagnosis alone." |
| **2:11–2:35** Federation [~95 wpm] | Federation tab: the diagram of simulated hospitals, then the results chart | "Separately, three simulated hospitals train one model with NVIDIA FLARE; only weights move. On an unseen hospital it scores 0.693, near pooled training at 0.700, above one hospital alone at 0.649. Plainly: stage and age alone score 0.702." |
| **2:35–2:52** Stack and next [~88 wpm] | How it works tab | "Built with NVIDIA FLARE, Nemotron on Nebius Token Factory, Tavily and CIViC. Next: pathology, radiology, and real institutions. Research support for clinicians, not a diagnosis." |
| **2:52–2:58** End card | Text: the repo URL and the demo URL | — |

Notes for the edit:
- Segment 2 is the hero: hold the banner on screen throughout; it is the only place a
  longitudinal profile is shown, so say "synthetic" in the voice-over (done above) and never cut
  to a crop without the banner.
- The MSK-CHORD figures are the CC BY-NC-ND aggregate results only; credit "Jee et al., Nature
  2024" in a caption.
- If a segment runs long, cut the month-24 sentence in segment 2 first, then the *missing
  layer* clause in segment 3.

## After recording
- [ ] Length ≤ 2:58; captions readable at 720p.
- [ ] Nothing secret on screen (keys, `.env`, terminal); no MSK-CHORD patient; "simulated" and
      "synthetic" labels visible where those appear.
- [ ] Upload to YouTube as **public**; add the link to the README and `docs/submission.md`.

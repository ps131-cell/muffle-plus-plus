# Demo video — script and shot list (draft)

Follows the platform-framing outline in `docs/HACKATHON.md` (decisions 2026-10-18). Record on
Oct 27–28, after the freeze checklist below. **IN PROGRESS** marks parts that depend on
features still being built; replace or drop them before recording.

## Devpost rules for the video
- **3:00 at most** (judges may stop there); aim for 2:50.
- Public on YouTube; link in the README and the Devpost form.
- Shows the project working, and how Nebius Token Factory and NVIDIA Nemotron are used.
- No copyrighted music, and no third-party logos or trademarks shown without permission: no
  music (or a CC0 track); say product names, don't show logos.
- Never shows an individual MSK-CHORD patient. Simulated hospitals and the synthetic timeline
  patient stay labeled as such on screen.

## Before recording
- [ ] Freeze done: saved notes regenerated in the evidence-labeled format (`make demo-notes`),
      demo bundle rebuilt with mutations (`make demo-bundle`, then a new release), numbers final.
- [ ] Record the local app (`make demo-tcga`) or the hosted URL, at 1920×1080, light theme,
      browser zoom 110%, bookmarks bar hidden, no other tabs, no terminal or `.env` on screen.
- [ ] Open the app once and write one live note before recording, so the model is loaded and you
      know the timing. In the edit, speed up the agent's 20–30 s wait and caption it "sped up".
- [ ] Patient: **case 661**: 99th percentile, stage III, methylation not measured, sequenced
      PIK3CA p.H1047R and TP53 p.N131Tfs*39, so the note shows observed drivers and CIViC
      evidence. Backup: case 710 (PIK3CA p.E545K, all layers measured).

## Script (about 290 words of voice-over; slower where the screen does the talking)

| Time | On screen | Voice-over |
|---|---|---|
| **0:00–0:20** Problem | App title and header | "A breast cancer changes over time, and the evidence about one patient is scattered: a stage at diagnosis, a sequencing panel, expression profiles, treatments. Hospitals can't pool it. MuFFLe++ is the first milestone of a platform that brings it together without moving patient data." |
| **0:20–0:35** One patient | Case review → select case 661; point at the risk percentile, the histogram and the drivers chart | "Here's a patient the model never trained on: the 99th percentile of predicted risk. Clinical stage raises it most. Methylation was never measured; the model simply masks the missing layer." |
| **0:35–0:45** Missing tests | Open *What if a data layer were missing?*, hide RNA expression | "If a hospital hasn't run a test, the same model still scores the patient, and you can see how much that test mattered." |
| **0:45–1:20** The agent | Click *Write the note with Nemotron*; the live steps scroll (sped up) | "Now the case agent. Nemotron 3 Super, on Nebius Token Factory, decides which of our tools to call: what was observed, the risk, which data layers drove it, the top genes, CIViC treatment evidence for the sequenced mutations, and a Tavily literature search. Nemotron 3 Ultra then writes the tumor-board note." |
| **1:20–1:40** The note | Scroll the note: [Observed] PIK3CA H1047R, [Model inference] risk, [Hypothesis] CIViC and literature; the green grounding check; open one tool call | "Every line is labeled observed, model inference or hypothesis, and treatment evidence is for clinician review, never a recommendation. A plain-code check confirms that every number, gene and link came from a tool, and every call is here to inspect." |
| **1:40–2:30** Results | Federation tab: the diagram of simulated hospitals, then the results chart | "Underneath, three simulated hospitals train one survival model with NVIDIA FLARE; only model weights move. On a hospital it never saw, the federated model scores 0.693, close to pooling everyone's data at 0.700, and better than one hospital alone at 0.649. And we say it plainly: stage and age alone score 0.702. On overall survival, omics don't add signal yet, so the model anchors on clinical data." |
| **2:30–2:50** Stack and next | How it works tab | "Built with NVIDIA FLARE, Nemotron 3 Super and Ultra on Nebius Token Factory, Tavily and CIViC. Next: pathology and radiology, and real institutions contributing data under proper governance. MuFFLe++ is research support for clinicians, not a diagnosis." |
| **2:50–2:58** End card | Text: the repo URL and the demo URL | — |

### IN PROGRESS: the timeline segment
When the synthetic timeline patient is in the demo, replace 0:20–0:45 with it: step through
the timeline (a treatment, a tumor marker, a sequencing report); the profile updates and the
agent says what changed and why, with **SYNTHETIC PATIENT** visible on screen. Keep 0:45–1:40
on the agent's note.

### IN PROGRESS: the MSK-CHORD result
If the timeline evaluation is done, add one sentence to 1:40–2:30 with its aggregate result
(12-month risk re-estimated at each new event, against baselines), and shorten the federation
sentence to fit. Show only the aggregate chart or table, never an individual MSK-CHORD patient.

## After recording
- [ ] Length ≤ 2:58; captions readable at 720p.
- [ ] Nothing secret on screen (keys, `.env`, terminal); no MSK-CHORD patient; "simulated" and
      "synthetic" labels visible where those appear.
- [ ] Upload to YouTube as **public**; add the link to the README and `docs/submission.md`.

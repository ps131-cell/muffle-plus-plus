# Demo video — script and shot list (draft)

Follows the platform-framing outline in `docs/HACKATHON.md` ("3-minute video outline"). Record on
Oct 27–28, after the freeze checklist below. The hackathon framing lives in the voice-over (this
document is the video); what is shown on screen is the clinician application: Patients → a
patient file → Tests → Timeline → Methods and validation (`docs/WORKSPACE.md`). Numbers come from
`app/timeline_synthetic.json` (synthetic patient), `app/results_tcga_brca.json` (federation) and
`docs/longitudinal.md` (MSK-CHORD aggregate); re-check them against those files if any is
regenerated.

## Devpost rules for the video
- **3:00 at most** (judges may stop there); this script runs 2:58.
- Public on YouTube; link in the README and the Devpost form.
- Shows the project working, and how Nebius Token Factory and NVIDIA Nemotron are used (the case
  agent and its saved note in segments 6–7).
- No copyrighted music, and no third-party logos or trademarks shown without permission: no
  music (or a CC0 track); say product names, don't show logos.
- Never shows an individual MSK-CHORD patient. Simulated hospitals and the synthetic patient stay
  labeled as such on screen and in the voice-over.

## Before recording
- [ ] Freeze done: numbers final (federation, MSK-CHORD aggregate, SYNTHETIC-001's scores).
- [ ] Hosted app (https://cancer-intelligence-platform.streamlit.app): wake it and reboot it from
      the Streamlit dashboard. It runs **bundle v2** (release `demo-bundle-v2`): the 40 held-out
      cases with their sequenced driver mutations, and 9 saved notes written by Nemotron 3 Ultra,
      labeled, with 0 grounding issues. No regeneration step is needed. Check that the Patients
      list, a patient file (SYNTHETIC-001 and Case 926), Tests, Timeline and Methods and
      validation (sidebar link) all load without errors.
- [ ] Confirm the Token Factory and Tavily keys are in the Streamlit secrets: the sidebar must say
      **live**, not "offline (no key)". Never show the secrets page or `.env` on screen.
- [ ] Record the hosted URL (or the local app, `make demo-tcga`), at 1920×1080, light theme,
      browser zoom 110%, bookmarks bar hidden, no other tabs, no terminal or `.env` on screen.
- [ ] SYNTHETIC-001 (`?patient=SYNTHETIC-001`): the yellow "SYNTHETIC-001 is synthetic" banner
      must be in frame whenever the file shows. Open it on its latest report (month 24), then
      move the **Report version** slider to month 11 and month 12; check the SOS tile at each
      (month 11: CA 15-3 rise 30 → 52 U/mL, "unconfirmed until a second specimen"; month 12:
      imaging progression and the new liver site).
- [ ] **Case 299** (`?patient=Case 299`): 99th percentile, stage III, methylation not measured,
      with a saved note carrying CIViC evidence. Read its Report once: the voice-over in segment
      6 says "ninety-ninth percentile" and "methylation never measured"; change it to match
      what the page shows if either differs.
- [ ] **Case 926** (`?patient=Case 926`): sequenced PIK3CA H1047R; the CIViC block shows level A
      items (fulvestrant + alpelisib; fulvestrant + palbociclib + inavolisib), and the saved note
      shows labeled bullets and the green grounding check ("every number, gene and link in this
      note comes from the tool outputs"). Read the saved note once: labels correct, no
      recommendation wording. Fix the prompt, not the video, if it is off.
- [ ] Optional: a **live** note. Click **Write the note with Nemotron** on a case the day before
      so the model is loaded and you know the timing (about 20–30 s; 5 live notes per session).
      If you show it on camera, speed up the wait, caption it "sped up", and say "live" in the
      voice-over; otherwise show the saved note and say "saved" (the script does).
- [ ] Federation and MSK-CHORD figures on **Methods and validation** match the voice-over (0.693,
      0.700, 0.649, 0.702; AUROC 0.88 and 0.93 against 0.66–0.71).

## Script (about 335 words of voice-over; 2:58 total)

Word rates in brackets are voice-over words per minute for that segment (target 80–126).

| Time | On screen | Voice-over |
|---|---|---|
| **0:00–0:18** 1. Problem [~117 wpm] | The Patients page: title "MuFFLe++", the line "Research and decision support for clinicians; not a diagnosis or a prescription", the patient list under it | "A breast cancer changes over time, and its evidence is scattered across tests and hospitals. MuFFLe++, milestone one of a cancer intelligence platform, keeps it in one patient file that updates as the record grows." |
| **0:18–0:31** 2. Patients [~120 wpm] | The list: SYNTHETIC-001 first (Kind: "Synthetic (written by hand)"), then TCGA-BRCA cases "simulated" by hospital. Switch on **Only files with SOS alerts**. | "The home screen is the patient list. SYNTHETIC-001 is made up and labeled; the rest are TCGA patients in simulated hospitals. Filter to files with SOS alerts." |
| **0:31–1:02** 3. A file and its SOS tile [~112 wpm] | Click SYNTHETIC-001: the file opens on its latest report (month 24), the yellow synthetic banner in frame. Move **Report version** back to month 11: the SOS tile shows the CA 15-3 rise, with its rule and threshold source. Then month 12: imaging progression, the new liver site, risk 88% (range 81–93%). Point at the *Observed* and *Model inference* tags. | "A file opens on its latest report. At month 11, the SOS tile flags a CA 15-3 rise from 30 to 52, with its rule, its threshold source, and a note: unconfirmed until a second specimen. At month 12, imaging reads progression, new liver lesions, and the risk jumps to 88 percent. Observed and inferred are labeled apart." |
| **1:02–1:19** 4. Tests and the lab workbench [~120 wpm] | **Tests**: the table by type; select the CA 15-3 lab to open the lab workbench: trend, reference limit, treatment lines. Hover the month-11 value (change from previous, from lowest, rate per month, source). | "Tests lists every test by type. The lab workbench plots CA 15-3 against its reference limit and the treatment starts; hover a value for its change from the previous one and from the lowest." |
| **1:19–1:29** 5. Timeline [~90 wpm] | **Timeline**: the risk at each version with treatment starts marked; in **Compare two versions** set From = month 7, To = month 12. | "The timeline keeps every report version. Compare any two to see what changed, and why." |
| **1:29–1:42** 6. A real case [~111 wpm] | Back to the list, open Case 299 (the "← All patients" button). Report: 99th percentile, the risk group, **Missing data and what it limits**: methylation not measured. | "Now a real, held-out TCGA patient, at the ninety-ninth percentile. Methylation was never measured, so the model masks it, and the file says so." |
| **1:42–2:12** 7. Evidence and the note [~106 wpm] | Open Case 926. **Mutations** block: PIK3CA H1047R (Observed) and its CIViC level A items (Hypothesis, "for clinician review"). Scroll to **Tumor-board note** → **Show the saved note**: the labeled bullets, the green grounding check, then open one tool call in the trace. | "Case 926 has a sequenced PIK3CA H1047R, observed. CIViC lists level A evidence for clinician review, never a recommendation. Nemotron 3 Super chose the tools; Nemotron 3 Ultra, on Nebius Token Factory, wrote this saved note. Every bullet is labeled, and a plain-code check confirms every number and gene came from a tool." |
| **2:12–2:47** 8. Methods and validation [~123 wpm] | **Methods and validation** (sidebar): the leave-one-hospital-out chart with the clinical-only bar visible, then the diagram of simulated hospitals, then the MSK-CHORD landmark table (aggregate rows only; credit "Jee et al., Nature 2024" in a caption). | "Methods and validation shows how each result holds up. Three simulated hospitals train one model with NVIDIA FLARE; only weights move. On an unseen hospital it scores 0.693, near pooled training at 0.700, above one hospital alone at 0.649. Plainly, stage and age alone score 0.702. On 5,368 real MSK-CHORD timelines, the risk over time reaches AUROC 0.88 at sequencing and 0.93 two years later, against 0.66 to 0.71 from diagnosis alone." |
| **2:47–2:58** 9. Close [~104 wpm] | End card: the repo URL and the demo URL | "Built with NVIDIA FLARE, Nemotron on Nebius Token Factory, Tavily and CIViC. Research support for clinicians, not a diagnosis." |

Notes for the edit:
- Segment 3 is the hero: hold the synthetic banner on screen throughout; SYNTHETIC-001 is the only
  longitudinal profile, so the voice-over says "made up and labeled" in segment 2 and the banner
  stays in frame in segments 3–5. Never cut to a crop without the banner.
- Segment 3 shows a CA 15-3 flag and the imaging progression as the SOS tile reports them; the
  risk-jump alert beside them carries a "placeholder threshold" badge, which stays visible.
- Segment 8 states the clinical-only baseline (0.702) plainly. Do not say the omics beat clinical
  data. The MSK-CHORD figures are the CC BY-NC-ND aggregate results only; no individual patient.
- If a segment runs long, cut the sentence about hovering in segment 4 first, then segment 5, then
  the *Methylation was never measured* clause in segment 6.

## After recording
- [ ] Length ≤ 2:58; captions readable at 720p.
- [ ] Nothing secret on screen (keys, `.env`, terminal); no MSK-CHORD patient; "simulated" and
      "synthetic" labels visible where those appear.
- [ ] Upload to YouTube as **public**; add the link to the README and `docs/submission.md`.

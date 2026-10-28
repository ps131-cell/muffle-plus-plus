# YouTube upload: title, description, tags, thumbnail

What to paste when the video recorded from [`video.md`](video.md) is uploaded (public, no
copyrighted music). If a fallback cut from `video.md` is used, move the chapter times to match
the take before pasting. Fill the one placeholder (the Devpost link) once the entry is saved.

## Title (93 characters)

```
MuFFLe++: an evidence-linked breast cancer patient file with Nemotron agents and NVIDIA FLARE
```

## Description

```
MuFFLe++ keeps the evidence about one breast cancer patient in one file: every test opens a
workbench built for its own data (slides, MRI, sequencing, expression, pathology reports,
labs, ctDNA), and every finding is labeled observed, model inference or hypothesis. A
Nemotron case agent on Nebius Token Factory writes the tumor-board note from our tools' outputs,
checked by a plain-code grounding check; the risk model was trained across three simulated
hospitals with NVIDIA FLARE (held-out C-index 0.728). Research and decision support for
clinicians, not a diagnosis or a treatment recommendation.

Try it: https://cancer-intelligence-platform.streamlit.app (no login; the first load can take a minute if the app was asleep)
Code (MIT): https://github.com/ps131-cell/muffle-plus-plus
Devpost entry: <DEVPOST LINK>

What is synthetic or simulated: SYNTHETIC-001 is a synthetic patient written by hand (not a real person, not taken from any dataset), with a synthetic ctDNA series; the three hospitals are simulated (TCGA tissue source sites as NVIDIA FLARE simulator clients). The 40 TCGA files are real, public, de-identified TCGA-BRCA patients.

Data and licenses: TCGA-BRCA open access (GDC, UCSC Xena), BCSS (CC0), TCGA-Reports (CC BY 4.0), TCGA-BRCA radiology on TCIA (CC BY 3.0), CIViC (CC0), ClinicalTrials.gov, Ensembl VEP and ClinVar, AlphaMissense (CC BY 4.0); MSK-CHORD (CC BY-NC-ND 4.0) is used locally only, and only aggregate results are published. Every source and model with its license: docs/registry.md in the repository.

The stroma and ECM3 content (tissue by zone on the slide workbench, the ECM3 four-gene score on the omics workbench, the evidence categories and the planned infrared modules on Methods and validation) is adapted from published work of the Chemical Imaging and Structures Laboratory (R. Bhargava, University of Illinois Urbana-Champaign) and of Triulzi et al. 2013, with citations; MuFFLe++ is independent and neither reviewed nor endorsed by the laboratory or the Cancer Center at Illinois.

Chapters
0:00 Patients and search across every file
0:18 A patient file: the overview, the queue, the case note
0:46 The patient's own slide
1:06 Genomics
1:18 Expression, protein and methylation
1:28 Breast MRI on its own images
1:46 The pathology report
1:56 Labs, ctDNA and evolution (synthetic patient)
2:16 The Timeline: time travel and the version diff
2:28 Methods and validation, feedback
```

The chapters follow `video.md`'s shot timings, grouped so that each chapter lasts at least 10 s
(YouTube's minimum): shots 1–2, 3–4, 5, 6, 7, 8, 9, 10, 11, then 12, 12b and the end card.

## Tags

```
breast cancer, oncology, clinical decision support, digital pathology, radiology, genomics, NVIDIA Nemotron, Nebius Token Factory, NVIDIA FLARE, federated learning, AI agents, Streamlit, TCGA, explainable AI
```

## Thumbnail

A 1280×720 PNG of Case 299's report cockpit (the risk model, the driver mutations with their
CIViC ladder, what to look at next), taken in headless Chromium at 1280×720 with the sidebar
folded on `main` at 75c6ddc. It is not in the repository (`docs/` holds no images); it is in
the WSL clone at `~/muffle-video/video/thumbnail.png`. Re-take it from the hosted app after the
freeze if the cockpit changes. It shows a public TCGA case only; no MSK-CHORD patient, no
logos.

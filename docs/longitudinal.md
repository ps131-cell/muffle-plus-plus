# Risk updates along real patient timelines (MSK-CHORD, breast cancer)

Milestone 1, part two of `docs/VISION.md`: does the risk estimate get better as a patient's record
grows? `make msk-chord` then `make experiment-msk` (`muffle.longitudinal`, ~1 min).

**Data.** MSK-CHORD (Jee et al., *Nature* 2024; cBioPortal study `msk_chord_2024`), 5,368 breast
cancer patients with timelines of treatments, NLP-derived progression from radiology reports,
metastatic sites, CA 15-3 / CEA values, ECOG, sequencing and survival. **License CC BY-NC-ND 4.0:
used locally only; this repository contains code and the aggregate results below, never any
individual patient.** The demo's timeline patient is synthetic.

**Task.** Time 0 is each patient's first tumor sequencing (diagnosis is earlier; survival is
counted from time 0). At landmarks 0, 6, 12 and 24 months, every patient still alive is scored for
**progression or death in the next 12 months**, using only what was recorded up to the landmark.
Patients followed for less than the landmark + 12 months without an event are left out of that
landmark.

**Models.** The same learner (gradient boosting, depth 3, library defaults, nothing tuned) on the
same patients, two feature sets:
- *baseline*: what is known at diagnosis — stage, hormone-receptor and HER2 status;
- *record so far*: the baseline plus the timeline up to the landmark — treatments by type and the
  number of distinct agents, prior progressions and time since the last one, metastatic sites,
  latest CA 15-3 / CEA and their change over 6 months, latest ECOG, sequenced drivers (ESR1,
  PIK3CA, TP53, ERBB2, AKT1, CDH1, GATA3, PTEN).

Patient-level splits (80 / 20), seeds 0–4; mean ± sd.

## Results

| landmark (months after sequencing) | patients | event rate | baseline AUROC | record-so-far AUROC | baseline Brier | record-so-far Brier |
|---|---|---|---|---|---|---|
| 0 | 5137 | 0.44 | 0.663 ± 0.010 | 0.880 ± 0.003 | 0.226 ± 0.003 | 0.140 ± 0.002 |
| 6 | 4610 | 0.42 | 0.665 ± 0.010 | 0.912 ± 0.009 | 0.224 ± 0.003 | 0.118 ± 0.008 |
| 12 | 4051 | 0.40 | 0.672 ± 0.014 | 0.928 ± 0.007 | 0.221 ± 0.005 | 0.103 ± 0.007 |
| 24 | 3105 | 0.34 | 0.706 ± 0.031 | 0.931 ± 0.014 | 0.194 ± 0.007 | 0.096 ± 0.009 |

The record-so-far model is far better than diagnosis-only at every landmark (AUROC 0.88–0.93 vs
0.66–0.71, Brier roughly halved), and it improves as the record grows (0.880 at sequencing →
0.931 two years later).

## Caveats
- **Labels come from NLP of radiology reports** (MSK-CHORD's progression annotations), not from
  adjudicated RECIST reads.
- **Some features reflect care, not only biology**: the number of tumor-marker tests and
  treatments partly measures how closely a patient is followed. A recent progression strongly
  predicts the next one; that is real signal, but it is also why the task is easier than
  predicting a first event.
- **One institution, no external validation**, patients sequenced at MSK (enriched for advanced
  disease: 44% have an event within 12 months of sequencing). Landmark populations differ, so
  compare the two models within a landmark rather than across landmarks.
- Nothing was tuned; better models are possible, and so is overfitting to MSK's practice.

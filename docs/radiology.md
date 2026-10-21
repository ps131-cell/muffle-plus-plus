# Radiology workbench: method, cutoffs and known failures

The radiology workbench (`app/workbenches/radiology.py`, logic in
`src/muffle/workbench/radiology.py`, offline pipeline `scripts/radiology_pipeline.py`) has two
pages, chosen by what a patient file holds. Design: [`WORKBENCHES.md`](WORKBENCHES.md) §6.
Written 2026-10-20. Nothing here is a diagnosis; every candidate, contour and measurement is a
**model inference**, and the cutoffs below say where they come from.

## 1. Imaging reports as text (SYNTHETIC-001)

The synthetic record holds imaging reports, not images (months -1, 7, 12 and 19, plus the month-24
clinic note "Imaging stable"). The page reads each one:

- **One rule with the import.** Reports are read by the imaging-report rule of the import
  (`muffle.imports.imaging_read`, [`documents.md`](documents.md)): the text is split into
  clauses (sentences, semicolons, "but", "however", "although", "except"), and a mention with a
  negation before it ("no", "not", "without", "negative for", "free of", "resolved"…) or after it
  ("not seen", "absent", "excluded"…), or in a hedged clause ("possible", "suspicious",
  "cannot be excluded", "likely", "?"…), is set aside. "No evidence of disease progression" states
  no read and "No new liver lesions" names no site.
- **The read**, from the report's own words, the first stated read in this order wins:
  progression ("progression", "progressive disease", "progressed", "progressing"), response
  ("partial" or "complete response", "responding", "decrease in size", "smaller"), stable
  ("stable", "unchanged", "no change"); else "not stated". Each also matches "read as …", the
  record's and an imported report's one-line wording ("read as response"). The record's own
  progression flag wins over the words if they ever disagree, and the page says so. **Observed.**
- **New sites**, from "new *site* lesions / metastases / nodules / mass(es) / foci" and "new
  lesions in the *site*", cross-checked against the record's `sites` field; a disagreement is
  shown. The site words are the import's distant sites (bone, osseous, liver, hepatic, lung,
  pulmonary, brain, pleura, adrenal, peritoneum…) **plus** the local and regional ones (lymph
  node, nodal, skin, chest wall, breast), on purpose: the lesion table tracks every site a report
  names new, while the import's "new metastatic site" alert counts distant sites only.
- **Lesion table**: one row per named site, one column per read. A cell is "new" where the site
  is first named, "named" where it is named again, and otherwise "not named; overall read: …".
  An overall "stable disease" is never shown as "stable" for a site the report does not name.
- **Measurements**: the record holds none, so the page says "no measurements recorded" and
  computes no RECIST sum.
- **Against the tumor marker**: each read against the last CA 15-3 result before it, with the
  labs workbench's own rule (`muffle.workbench.labs.lead_lag` on these reads): the marker rose
  at month 11, one month before the month-12 progression. An observed order of events in this
  record, not a validated lead time.

Review marks use `workspace.finding_key(pf, "imaging", "report", month, "read")` for a read and
`(…, "report", first month, site)` for a site.

The page reads the file's own record (`radiology.file_events`, i.e. `workspace.record_events`
up to the report version's month): the synthetic record's events and every imported imaging
report, which reaches the page as the read its import found. A TCGA file with an imported report
reads only that report, never the synthetic record. A site an imported report names new is
trust **moderate** in the queue and the summary card, as its "new metastatic site" alert is: the
import's text rule read it (the event carries `"imported": True`). The record's own reports stay
trust strong.

## 2. Public images (TCGA-BRCA radiology on TCIA)

**Data.** The TCGA-BRCA radiology collection on The Cancer Imaging Archive (139 patients, MR and
mammography; CC BY 3.0; doi:[10.7937/K9/TCIA.2016.AB2NAZRP](https://doi.org/10.7937/K9/TCIA.2016.AB2NAZRP)),
read through the public NBIA REST API (no login). The app's 40 held-out TCGA cases were mapped
to barcodes through `cohort.npz` (`Case.index` is the row; all 40 rows' clinical features match
the bundle). Five of them have a TCIA study: cases 537, 563, 564, 926 and 937. Three are
processed:

| Case | Barcode | Study | What ships |
|---|---|---|---|
| 563 | TCGA-BH-A0H5 | GE Signa Excite 1.5 T, VIBRANT multiphase, 5 phases ~80 s apart, 512² × 90 slices, 0.57 mm, 2 mm slices | pre, early, delayed, subtraction; 3 candidates |
| 937 | TCGA-EW-A1P3 | Siemens Sonata 1.5 T, pre / 1 / 2 / 6 min series, 384² × 208 slices, 0.89 mm, 0.9 mm slices | the same, every second slice |
| 926 | TCGA-EW-A1J2 | Lorad Selenia mammography, R/L CC and MLO, 0.07 mm | the four views |

Each study's DICOM structured report gives the BI-RADS category (6, known biopsy-proven
malignancy, in all five), the pathology and the receptors, shown as **observed**; it records no
lesion size or position, so no reader measurement exists to compare with. The report also states
race and health status, which the pipeline drops.

**What ships** (`app/workbenches/radiology_results/<barcode>/`, under 5 MB each: 2.6, 2.7 and
0.13 MB): 8-bit copies, one JPEG strip per phase (quality 80), at most 256 px wide and 128
slices, cropped to 30 mm behind the search region's posterior limit (the heart and lungs are cut
off); mammograms at 512 px (0.46 mm per pixel; 256 px would be a thumbnail where nothing can be
read). `study.json` holds the geometry, phases, report facts, candidates with per-slice contours,
boxes and measurements, and the run's provenance; `index.json` maps cohort rows to studies for
the patient files. These are derived copies, not the diagnostic originals, and say so.

### Pipeline (MRI)

1. Phases: a multiphase series is split by `TriggerTime` (GE: 0, 80, 160, 240, 321 s from the
   first phase's start; the injection time is not in the headers); separate series take their
   times from the series descriptions (Siemens: nominal 1, 2 and 6 minutes after contrast).
2. Display orientation: axial, anterior at the top, the patient's right on the image's left
   (from `ImageOrientationPatient`); slices sorted along the slice normal.
3. Subtraction: first post-contrast minus pre-contrast.
4. **Breast region** (where candidates are searched): the skin surface per column (first row
   above 20% of the volume's 99th percentile after light smoothing), the intermammary cleft (the
   deepest skin row between the two breasts, median over slices), and the region inside the body,
   at least 3 mm under the skin and anterior to the cleft plus 10 mm.
5. **Seed rule**: the smoothed subtraction above the region's 99.5th percentile, opened with a
   1.5 mm ellipsoid (so vessels thinner than about 3 mm come off a mass), grouped in 3D. Left
   out: groups under 30 mm³, vessel-like groups (longest over second axis of the voxel spread
   above 3), plate-like groups (second over shortest above 3) and groups that reach the region's
   posterior limit. The rest are ranked by summed enhancement; the top three are C1–C3.
6. **MedSAM** (ViT-B, `wanglab/medsam-vit-base` at revision `de8488b`, Apache-2.0) on every
   slice of each candidate, on the subtraction slice, with the authors' recipe
   (`MedSAM_Inference.py`): per-slice 0.5–99.5 percentile window, cubic resize to 1024², [0, 1]
   scaling, box prompt, sigmoid above 0.5 upsampled bilinearly. The box is the seed's extent on
   that slice plus 15% (at least 2 pixels). Only mask pieces touching the seed are kept. A slice
   is **unsure** when the mask is empty or larger than 1.5 × its box.
7. **Measurements** on the contours: longest in-plane diameter (between pixel centres, ± one
   pixel) on the slices where the contour stayed inside its box; craniocaudal extent (slices ×
   spacing); volume (voxels × pixel spacing² × slice spacing from the positions) with a range
   from moving the contour one pixel in and out, and the volume without the unsure slices.
8. **Kinetics**: the mean signal inside the 3D contour per phase. Initial phase = the strongest
   post-contrast phase within 2 minutes (else the first); initial enhancement % over
   pre-contrast: slow below 50%, medium 50–100%, fast above 100%. Delayed = the last phase, %
   change from the initial peak: persistent above +10%, plateau within ±10%, washout below −10%;
   curve types I / II / III.

Re-segmenting with a moved box needs this pipeline; the hosted app runs no model.

### Cutoffs and their sources

| Cutoff | Value | Source |
|---|---|---|
| Initial window | 2 min | literature, placeholder until calibrated (ACR BI-RADS MRI lexicon, 5th ed., 2013; full text not checked here) |
| Slow / fast initial enhancement | 50% / 100% | literature, placeholder until calibrated (the usual values) |
| Delayed plateau band | ±10% | literature, placeholder until calibrated; curve types from Kuhl et al., *Radiology* 1999, doi:[10.1148/radiology.211.1.r99ap38101](https://doi.org/10.1148/radiology.211.1.r99ap38101) |
| Seed percentile | 99.5th | placeholder |
| Seed opening | 1.5 mm | placeholder |
| Minimum candidate | 30 mm³ | placeholder |
| Vessel-like / plate-like | axis ratios above 3 | placeholder |
| Chest-wall margin | cleft + 10 mm | placeholder |
| Skin | 3 mm | placeholder |
| Near the chest wall (look-here flag) | 5 mm from the limit | placeholder |
| Box padding, mask threshold | 15%, 0.5 | design (the latter from the authors' code) |
| Dense pixels (mammography) | Otsu inside the breast | placeholder; a pixel share, not a BI-RADS density category |

For context the page quotes Kuhl et al. 1999 (266 lesions): type III curves in 57% of cancers
and 6% of benign lesions, type I in 9% and 83%. Evidence about curve types, not a diagnosis.

### Results (model inference, not validated here)

| Case | Candidate | Side | Longest diameter | Volume (one-pixel range) | Kinetics | Unsure slices |
|---|---|---|---|---|---|---|
| 937 | C1 | right | 26.2 mm | 7.43 mL (6.26–8.67) | medium (72%), plateau (+2%) | 2 of 24 (the end slices) |
| 937 | C2 | left | 15.8 mm | 0.87 mL (0.64–1.12) | slow (47%), plateau (+9%) | 3 of 9 |
| 937 | C3 | right | 18.9 mm | 1.22 mL (0.93–1.54) | slow (27%), plateau (+3%) | 8 of 9 |
| 563 | C1 | right | 18.8 mm | 2.49 mL (2.08–2.93) | fast (114%), plateau (+3%) | 0 of 10 |
| 563 | C2 | left | 20.0 mm | 1.83 mL (1.47–2.21) | fast (101%), washout (−17%) | 2 of 11 |
| 563 | C3 | right | 19.8 mm | 0.99 mL (0.78–1.22) | medium (90%), plateau (+7%) | 0 of 6 |

Checked by eye on contact sheets: in both studies C1 is a compact enhancing mass in the right
breast and MedSAM's contour follows it on every central slice. 937-C3 is a curvilinear vessel
segment (MedSAM overshoots its narrow box on 8 of 9 slices, and the page flags it). 563-C2 is a
strip along the chest wall just in front of the heart, 3 mm from the search limit, and washes
out as vessels do; the page flags it as near the chest wall. Mammography (926): dense-pixel share
26–32% per view (27% on the CC views).

### Mammography (case 926)

The four views at 512 px with window and level, the structured report (BI-RADS 6, invasive
lobular carcinoma, ER+ / PR+ / HER2−), the dense-pixel share (placeholder rule) and a **screening
score from mammoscreen** (`ianpan/mammoscreen`, revision `b619a88`, Apache-2.0): an ensemble of
three EfficientNetV2-S nets (2048×1024, 1920×1280, 1536×1536) that averages the CC and MLO views
of a breast and returns a cancer score and BI-RADS density A–D. The architecture is re-built from
the model's published code with timm and the pinned weights are loaded strictly (every key
matched), so no remote code runs. Two departures from the authors' recipe, said on the page: the
views are cropped to the breast's bounding box from the threshold mask instead of the authors'
crop model, and padding is constant zero.

Result (model inference, not validated here): right breast **0.42** (the three nets 0.47, 0.37,
0.42), left **0.005** (0.002, 0.002, 0.010); density **C**, heterogeneously dense, in both (93%
and 98%). On its own held-out data the card puts 98%, 94% and 91% sensitivity at 0.0072, 0.0127
and 0.0184. The score is uncalibrated, and this study is a known biopsy-proven cancer whose
structured report does not record the side, so the score cannot be checked against the record
and adds nothing to the diagnosis; it shows what the model would say on a screening exam. It
also moves with the crop: a first run whose breast mask was taken on the 8-bit image instead of
the VOI-LUT values gave right 0.37 and left 0.006. 143 CPU seconds for the four views in the
pipeline run (4 threads, load 8.6); the first run took 537 s at load 8–12 plus 131 s to fetch
the weights.

**A second density opinion** comes from MONAI's breast density bundle
(`MONAI/breast_density_classification`, revision `eb746b7`, Apache-2.0 per the repo's LICENSE
file): InceptionV3 fine-tuned on Mayo Clinic mammograms (Gupta et al., arXiv:2202.08238,
preprint). Its network is re-built from torchvision the way the bundle's `TorchVisionFCModel`
builds it (with the ImageNet input transform the pretrained constructor switches on) and the
pinned weights are loaded strictly, so MONAI itself is not needed; each whole view is scaled to
[0, 1], resized to 299×299 and given a sigmoid per class, as in the bundle. Result (model
inference, not validated here): left CC and MLO **C**, right MLO **C**, right CC **D** (it sits
between the two there: C 0.83, D 0.90). mammoscreen says C for both breasts, so the two agree
except on the right CC view; two models agreeing is not a validation. The bundle's metadata
states accuracy 0.96 without describing its test set and calls the model "an example, not to be
used for diagnostic purposes". 78 CPU seconds including the weights download (load 21).

**Timings** (WSL, 8 shared cores, 4 threads, `nice -n 10`): MedSAM's image encoder took 21 s per
1024² slice on a quiet machine (load 0.3, random input) and a median 12–17 s per slice in the
runs (load 7–15 from other sessions); case 937 took 468 s for 32 slices, case 563 164 s for 13.
The decoder takes under a second per box. Downloads: about 530 MB in 2 minutes.

## 3. Known failures and limits

- **Where it looks**: lesions behind the cleft-plus-10-mm line (deep, at the chest wall, in the
  axilla or the axillary tail) are never proposed; non-mass enhancement and vessel-like or
  plate-like shapes are left out by the shape rules; foci under ~4 mm vanish in the opening.
- **What it ranks**: brightness × size, so a large background-enhancing area could outrank a
  small cancer; three candidates are shown for that reason, never one verdict.
- **The contour**: MedSAM is not validated on breast MRI here; its published validation is on
  the paper's own tasks, and this checkpoint (uploaded May 2023) may predate the paper's final
  model. A narrow box makes it overshoot (flagged unsure).
- **Kinetics**: the mean inside a contour mixes enhancing and non-enhancing parts; GE phase times
  are relative to the first phase, not the injection; Siemens times are nominal.
- **Display**: 8-bit copies, so window and level act on an already-windowed image; slices are
  downsampled (1.1–1.3 mm per shown pixel) and, for case 937, every second slice is shown.
- **Prior comparison**: each processed patient has one study date, so the page says no prior
  exists. 20 of the TCIA patients have two dates (several MRI pairs months apart, e.g.
  TCGA-AR-A1AQ 2001-11 / 2003-05); none is in the current held-out bundle. A comparison would
  align by slice index only, say "registration not done" and flag protocol differences first.
- **Mammography**: no contours (no seed rule for mammograms); the pectoral muscle counts as dense
  on MLO views; the screening score runs on crops from a threshold mask rather than the authors'
  crop model, is uncalibrated, and has nothing in this record to be checked against.

## 4. Reproducing

```
python scripts/radiology_pipeline.py fetch TCGA-EW-A1P3:10,11,14,22 TCGA-BH-A0H5:4 TCGA-EW-A1J2:1,2,3,4
python scripts/radiology_pipeline.py mri --barcode TCGA-EW-A1P3 --index 937 --series 10,11,14,22
python scripts/radiology_pipeline.py mri --barcode TCGA-BH-A0H5 --index 563 --series 4
python scripts/radiology_pipeline.py mammo --barcode TCGA-EW-A1J2 --index 926 --series 1,2,3,4 --screen
python scripts/radiology_pipeline.py index
```

Needs `pydicom`, `scikit-image`, `transformers`, `timm` and CPU `torch` (not in the app's
requirements; `timm` from PyPI pulls a CUDA `torchvision`, so reinstall the CPU build of the
matching version); the DICOM files stay in `~/muffle-radiology/dicom`, outside the repo.

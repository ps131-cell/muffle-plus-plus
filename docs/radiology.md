# Radiology workbench: method, cutoffs and known failures

The radiology workbench (`app/workbenches/radiology.py`, logic in
`src/muffle/workbench/radiology.py`, offline pipeline `scripts/radiology_pipeline.py`) has two
pages, chosen by what a patient file holds. Design: [`WORKBENCHES.md`](WORKBENCHES.md) §6.
Written 2026-10-20; round 2 (change over time on a public example pair, three planes and a cine,
five bundled cases, mammography geometry) 2026-10-21, §§3–5; round 3 (the scan map: layers,
hover, click, search and export on the study's own images) 2026-10-28, §8. Nothing here is a
diagnosis; every candidate, contour and measurement is a **model inference**, and the cutoffs
below say where they come from.

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
the bundle). Five of them have a TCIA study: cases 537, 563, 564, 926 and 937. All five are
processed (537 and 564 in round 2; 563 and 937 re-run under pipeline version 2, which ships every
phase):

| Case | Barcode | Study | What ships |
|---|---|---|---|
| 563 | TCGA-BH-A0H5 | GE Signa Excite 1.5 T, VIBRANT multiphase, 5 phases ~80 s apart, 512² × 90 slices, 0.57 mm, 2 mm slices | all five phases and the subtraction; 3 candidates |
| 937 | TCGA-EW-A1P3 | Siemens Sonata 1.5 T, pre / 1 / 2 / 6 min series, 384² × 208 slices, 0.89 mm, 0.9 mm slices | the same, every second slice |
| 564 | TCGA-BH-A0H6 | GE Signa Excite 1.5 T, VIBRANT multiphase, 5 phases ~61 s apart, 512² × 68 slices, 0.59 mm, 2 mm slices | all five phases and the subtraction; 3 candidates |
| 537 | TCGA-BH-A0DE | GE Signa Excite 1.5 T, VIBRANT multiphase, 5 phases ~89 s apart, 512² × 76 slices, 0.57 mm, 2 mm slices | the same (the sagittal pre and post series are not used) |
| 926 | TCGA-EW-A1J2 | Lorad Selenia mammography, R/L CC and MLO, 0.07 mm | the four views |

Each study's DICOM structured report gives the BI-RADS category (6, known biopsy-proven
malignancy, in all five), the pathology and the receptors, shown as **observed**; it records no
lesion size or position, so no reader measurement exists to compare with. The report also states
race and health status, which the pipeline drops.

**What ships** (`app/workbenches/radiology_results/<barcode>/`, under 5 MB each: 563 3.98, 564
3.16, 537 3.34, 937 3.32 and 926 0.13 MB; the example pair 2.3 and 2.2 MB in
`radiology_example/`, so no release asset is needed): 8-bit copies, one JPEG strip per phase
(quality 80; every phase since version 2), at most 256 px wide and 128
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
| Margin band (the map's Lesion view) | 3 mm outside the contour | placeholder |
| Map square | about 4.5 mm (4 shown pixels at 1.13 mm, 3 at 1.3 mm, 10 on a mammogram) | design: about the smallest candidate the seed rule keeps (30 mm³, a 4 mm sphere) |

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
| 564 | C1 | right | 15.5 mm | 1.01 mL (0.81–1.22) | medium (55%), persistent (+19%) | 1 of 5 |
| 564 | C2 | right | 10.9 mm | 0.12 mL (0.09–0.15) | medium (69%), persistent (+20%) | 2 of 3 |
| 564 | C3 | right | 8.3 mm | 0.07 mL (0.05–0.09) | medium (89%), persistent (+31%) | 2 of 3 |
| 537 | C1 | left | 23.9 mm | 2.25 mL (1.96–2.55) | slow (32%), persistent (+36%) | 6 of 6 |
| 537 | C2 | left | 5.2 mm | 1.79 mL (1.49–2.11) | slow (25%), persistent (+27%) | 6 of 7 |
| 537 | C3 | right | 15.6 mm | 0.71 mL (0.56–0.87) | medium (53%), persistent (+12%) | 0 of 5 |

Cases 563 and 937, re-run under version 2, reproduce every diameter, volume and kinetic value above; only the craniocaudal extent moved where a candidate has empty end slices, since it now counts the slices that hold a contour (563-C2 22 → 18 mm, 937-C2 8.1 → 7.2 mm, 937-C3 8.1 → 6.3 mm).

Checked by eye on contact sheets: in 563 and 937 C1 is a compact enhancing mass in the right
breast and MedSAM's contour follows it on every central slice; in 564 C1 is a compact enhancing
mass in the right breast too, with C2 and C3 small enhancing foci deeper in (C3 flagged 1 mm from
the search limit). In 537 C1 is a spiculated mass in the left breast that keeps enhancing through
the delayed phase; MedSAM's contour covers it but runs past 1.5 times the small seed box on all
six slices, so every slice is flagged unsure and its diameter rests on unsure contours only. C2
lies beside it (6 of 7 slices unsure; its 5.2 mm diameter comes from the one sure slice while its
1.79 mL volume holds the overshoot), and C3 sits at the chest wall (flagged). 937-C3 is a curvilinear vessel
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
The decoder takes under a second per box. Downloads: about 530 MB in 2 minutes. Round 2 (same
machine, load 8–21 from other sessions' runs): a median 46 s per slice for 563's 13 slices (load
17–20), 56 s for 564's 7 (load 18), 53 s for 537's 18 (load 21), 28 s for 937's 32 (load 10–12); the example pair's
26 and 36 s (load 8 and 12). Downloads for round 2: about 300 MB in under 2 minutes.

## 3. Change over time on real images (round 2): a public example pair

**Why an example.** None of the five bundled TCGA cases has two study dates. Of the 20 TCIA
TCGA-BRCA patients that do, most pair an MRI with a biopsy a few days later, a mammogram, or a
different protocol; TCGA-AR-A1AQ has the same protocol on both dates, 18 months apart: GE SIGNA
EXCITE on 2001-11-21 and SIGNA HDx on 2003-05-07, 1.5 T, bilateral sagittal VIBRANT, four phases,
3 mm slices. The patient is in the omics cohort but not in the app's bundle, so the pair is shown
as a **public example, not a patient file** (the slide workbench's example region is the model):
inside every MRI study's "Since the last study" section and the synthetic patient's report page,
labeled so, and as its own file only on the workbench's standalone page. Its omics and record are
not used. Its structured reports are the same patient-level report on both dates (BI-RADS 6,
infiltrating ductal carcinoma, ER−, PR−), so they say nothing about the change.

**Sagittal acquisitions** (pipeline version 2). The phases are the same 116 (112) positions
acquired four times, numbered in order; they are split by instance number, and each phase's start
comes from `AcquisitionTime` (2001: 0, 210, 397, 598 s; 2003: 0, 168, 306, 401 s; each phase takes
minutes, and the injection time is not in the headers). The volume is turned into the display
frame (axial, anterior up, the patient's right on the left: 0.86 × 0.86 mm in the sagittal plane,
3 mm across), the breast region and the seed rule run there with that spacing, and **MedSAM runs
on the sagittal acquisition slices**, the sharpest plane; the longest diameter is measured on them
too. The shipped axial copy is resampled to square 1.3–1.4 mm pixels, so detail across the 3 mm
slices is interpolated. An axial acquisition takes the same path with nothing turned.

**Alignment.** `muffle.workbench.radiology.register`: the earlier study's pre-contrast volume onto
the later one's, rigid (three rotations and three shifts about the later body's centre of mass),
maximising normalised mutual information (Studholme et al. 1999) over a fixed random sample of
200,000 voxels of the shipped crop (the breasts and the air before them), with Powell's method on
4 mm, then 2 mm voxels, started from the two bodies' centres of mass. scipy only; SimpleITK
(Apache-2.0) was not needed. Tested on a synthetic textured volume moved by a known 3° rotation
and a 4, −3, 5 mm shift with different, anisotropic voxels on both sides: recovered within 1.5 mm.
On the pair: rotations −3.0°, 3.3°, −1.3°, shifts −15.4, 1.9, 16.5 mm, normalised mutual
information 1.124 at the start and 1.156 aligned (2 mm voxels), 117 and 200 CPU seconds in two
runs at load 13 and 17. It is not a local optimum: six starts up to 6° and 15 mm away converged
within 0.7° and 1 mm (4 mm voxels, NMI 1.168 each), and the tissue masks' overlap rose from Dice
0.69 at the start to 0.76.

**Where it is unreliable.** A rigid alignment cannot follow the breast's own deformation between
exams. `local_residual` asks, at each later candidate and on 30 mm blocks of the breasts, which
shift of up to 10 mm (4 mm, then 2 mm steps) best matches the later study to the aligned earlier
one by normalised cross-correlation (40 mm cubes at candidates, 30 mm on the grid). Above 5 mm, a
best correlation under 0.5, or a best shift at the search's edge, the place is **unreliable
here** (placeholders): the comparison tints those blocks red on both views and every row and
sentence carries the mark. On the pair, **99 of 112 blocks are unreliable**: the best local
shift is 3–15 mm (median about 10 mm, often at the search's edge), so the breasts deformed
between the exams far more than a rigid alignment can take up, and the comparison says so at
almost every place. Of the later candidates, C2 (left breast) is within 4.9 mm; C1 and C3 are at
least 10 and 13 mm off. The check took 4 s for the three candidates and 54 s for the blocks
(coarse-to-fine search, load 20; the exhaustive search of the first run took 30 s for the
candidates and gave the same shifts).

**Pairing and change.** Each later candidate's centroid (moved by its local shift) is mapped into
the earlier frame and paired with the nearest earlier candidate within 15 mm (placeholder). Per
pair: the longest diameter and volume on both dates and the change; **grew** when the diameter
rose ≥ 20% and ≥ 5 mm, **shrank** when it fell ≥ 30% (RECIST 1.1's rules for a sum of diameters,
Eisenhauer et al. 2009, borrowed per candidate as placeholders), each by more than twice the
pixel; whether the one-pixel volume ranges overlap. A **sum of longest diameters** takes the
paired candidates of at least 10 mm on the earlier date, at most two (RECIST 1.1's measurable size
and per-organ limit, the breasts as one organ): labeled computed, never a response call, because
the candidates are a model's, not a reader's target lesions. Unpaired candidates are said to be
"not proposed" on the other date, never gone or new. Protocol and scanner differences are listed
before any of it (here: the scanner, the recorded contrast agent, TR and TE, the pixel size and
the phase times; kinetics are not compared across dates).

Results (model inference, not validated here):

| Date | Candidate | Side | Longest diameter | Volume (one-pixel range) | Kinetics | Unsure slices |
|---|---|---|---|---|---|---|
| 2001-11-21 | C1 | right | 25.6 mm | 6.93 mL (5.40–8.57) | fast (123%), plateau (+2%) | 0 of 12 |
| 2001-11-21 | C2 | right | 17.9 mm | 1.89 mL (1.32–2.51) | medium (87%), persistent (+19%) | 0 of 6 |
| 2001-11-21 | C3 | right | 9.6 mm | 0.35 mL (0.18–0.54) | medium (99.9%), persistent (+17%) | 2 of 3 |
| 2003-05-07 | C1 | right | 22.7 mm | 2.19 mL (1.37–3.09) | slow (48%), persistent (+26%) | 1 of 8 |
| 2003-05-07 | C2 | left | 19.9 mm | 3.17 mL (2.19–4.24) | slow (42%), persistent (+25%) | 3 of 8 |
| 2003-05-07 | C3 | left | 17.0 mm | 1.65 mL (1.13–2.23) | slow (31%), persistent (+19%) | 1 of 6 |

The kinetics use the first post-contrast phase, which starts 210 s (2001) and 168 s (2003) after
the pre-contrast one and lasts minutes, so the 2-minute initial window is not met on either date
and the two are not comparable. MedSAM ran on 12 and 22 sagittal slices, a median 26 and 36 CPU
seconds each (4 threads, load 8 and 12); shipped 2.3 and 2.2 MB, `pair.json` 40 kB.

Checked by eye: 2001-C1 is a rim-enhancing mass in the right breast with a dark centre, and
MedSAM's contour follows the rim; 2003-C1 is a smaller, irregular enhancing area at the same place
after alignment (10.8 mm apart, the local shift included); 2001-C2 sits beside C1; 2003-C3 is the
left nipple, which enhances. **Paired**: C1 → C1, longest diameter 25.6 → 22.7 mm (−2.9 mm,
−11%), within the placeholder rules; volume 6.93 → 2.19 mL, the one-pixel ranges do not overlap;
alignment unreliable there (at least 10 mm left over). The computed sum is that pair alone, 25.6
→ 22.7 mm (−11%); 2001-C2 (17.9 mm) is left out, not proposed on the later date. Unpaired: 2003-C2
and C3, 2001-C2 and C3. The page says all of it in these words, and says no more: the record here
holds no treatment and no reader's measurement, so neither the cause of the change nor whether
the two contours are the same lesion can be checked.

The synthetic patient's reports get the same change view without sizes (`report_change`): per
named site, what the earlier and the later read say, and "no measurements recorded", so no change
in size and no sum. `summary()` gives a file with a study pair an "Imaging change" card (model
inference, trust weak) and `queue()` an item per candidate that grew (consequence 3) or shrank
(2) beyond the placeholder rules, or whose alignment is unreliable (1), each with its source and
the rule; the look-here line, the Spot panel ("Change over time") and the exports (the change
table as CSV, the alignment and rows in the JSON) carry the same. No bundled file has two dates,
so these appear on the example only.

## 4. Three planes and the cine (round 2)

Every MRI study opens in axial, coronal and sagittal views of the shipped copy with linked
positions: the viewer's slice and a row and a column, each drawn as a line on the other two views;
picking a candidate moves all three to it. Coronal and sagittal are resliced (`reslice`) from the
axial copy at square pixels, linearly for the image and nearest for the contours, which are the
axial contours stacked into a mask (`candidate_mask`, even-odd so a hole stays a hole); the head is
at the top, the patient's right on the left (coronal) and anterior on the left (sagittal). The
voxel shape is said under the views (`anisotropy`): for example 2 mm between shown slices against
1.2 mm pixels for case 563, 1.7–1.9 mm against 1.3 mm for the example pair. The craniocaudal
extent and the longest-diameter slice are carried over as marks. Tested on a volume with 3 mm
slices and 1 mm pixels: a voxel lands on the right row and column of both reslices. A cine plays
every shipped phase at the slice (zoomed on the chosen candidate, its contour drawn); pipeline
version 2 ships the phases between the early and the delayed one, so the series list has every
phase too.

## 5. Mammography: left and right, CC and MLO (round 2)

- **Lesion detector: none.** The registry's open mammography models give a score per breast
  (mammoscreen), a density (MONAI) or a risk (Mirai); detectors trained on VinDr-Mammo carry its
  restricted licence, Mammo-FM and Mammo-CLIP are non-commercial, and a web check on 2026-10-21
  found classifiers and code-only detectors with no licensed weights. So mammograms get no lesion
  candidates, the page says so, and the density opinions stay.
- **Left-right difference** (`asymmetry`): the right minus the left dense-pixel share per view,
  asymmetric above 10 points (placeholder); case 926: CC −2.2 points (26% / 28%), MLO +2.7 (32% /
  29%), neither asymmetric. A map (`asymmetry_map`) crops each breast to its outline, turns the
  chest wall to the left, resamples both to one grid and thresholds them with one Otsu threshold:
  red where only the right is dense, blue where only the left is (case 926 CC: 8% and 9% of the
  grid). It ignores compression, positioning and breast size; not a BI-RADS asymmetry finding.
- **CC and MLO linked** (`breast_outline`, `nipple_band`): the nipple is the breast's point
  farthest from the chest-wall edge; the same band behind it (a distance and ±10 mm) is outlined
  and enlarged on both views of a breast, since a lesion's distance from the nipple is about the
  same on both. The distance runs along the image rows, which on the MLO view is at an angle to
  the pectoral muscle: geometry for looking, not a registration of the two views.

## 6. Known failures and limits

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
- **Prior comparison**: each bundled patient has one study date, so its page says no prior
  exists and shows the change view on the public example pair, labeled as another patient.
- **Change over time** (§3): the alignment is rigid and cannot follow the breast's deformation
  between exams; the local check marks where it fails, but a wrong pairing can still fall within
  the 15 mm match distance. Pairing uses each date's own top three candidates, so a lesion
  outside one date's top three is unpaired, not gone. Phase timing differs between the dates
  (and phases take minutes on this protocol), so kinetics are not compared across dates. The
  growth rules are RECIST's sum rules borrowed per candidate (placeholders) and the sum is not a
  response call.
- **Reconstructions** (§4): coronal and sagittal views, and the axial view of a sagittal
  acquisition, interpolate between slices 1.7–3 mm apart.
- **Mammography**: no contours (no open detector, §5); the pectoral muscle counts as dense on MLO
  views; the screening score runs on crops from a threshold mask rather than the authors' crop
  model, is uncalibrated, and has nothing in this record to be checked against; the left-right
  map ignores compression and positioning.

## 7. Reproducing

```
python scripts/radiology_pipeline.py fetch TCGA-EW-A1P3:10,11,14,22 TCGA-BH-A0H5:4 TCGA-EW-A1J2:1,2,3,4
python scripts/radiology_pipeline.py fetch TCGA-BH-A0H6:4 TCGA-BH-A0DE:5 \
    TCGA-AR-A1AQ@2001-11-21:8 TCGA-AR-A1AQ@2003-05-07:8
python scripts/radiology_pipeline.py mri --barcode TCGA-EW-A1P3 --index 937 --series 10,11,14,22
python scripts/radiology_pipeline.py mri --barcode TCGA-BH-A0H5 --index 563 --series 4
python scripts/radiology_pipeline.py mri --barcode TCGA-BH-A0H6 --index 564 --series 4
python scripts/radiology_pipeline.py mri --barcode TCGA-BH-A0DE --index 537 --series 5
python scripts/radiology_pipeline.py mammo --barcode TCGA-EW-A1J2 --index 926 --series 1,2,3,4 --screen
for d in 2001-11-21 2003-05-07; do
  python scripts/radiology_pipeline.py mri --barcode TCGA-AR-A1AQ --date $d --series 8 \
      --out app/workbenches/radiology_example --example --keep ~/muffle-radiology2/work
done
python scripts/radiology_pipeline.py pair --earlier TCGA-AR-A1AQ_2001-11-21 --later TCGA-AR-A1AQ_2003-05-07
python scripts/radiology_pipeline.py index
```

Needs `pydicom`, `scikit-image`, `transformers`, `timm` and CPU `torch` (not in the app's
requirements; `timm` from PyPI pulls a CUDA `torchvision`, so reinstall the CPU build of the
matching version); the DICOM files and the pair's full-resolution volumes (`--keep`) stay outside
the repo (`~/muffle-radiology/dicom`, `~/muffle-radiology2`).

## 8. The scan map (round 3)

Every study opens on a **scan map**: the study's own image underneath (an MRI phase at one slice,
or one mammography view) and see-through colour layers on top, the slide workbench's map
(`src/muffle/workbench/tile_map.py`, adapted from the team's Colon Tumor Front Analyzer) built for
a scan (`src/muffle/workbench/radiology_map.py`, search in `radiology_search.py`, exports in
`radiology_export.py`; they import the slide map's colours, sizes and helpers). As there, the view
buttons and the opacity slider live inside the chart, so they act in the browser without a rerun
and keep the zoom. It replaces the Altair viewer and its Mask, Box, Measure and Zoom switches;
the four mammograms side by side stay in Details.

**Views** (buttons inside the map; every colour is a model inference or a rule on one):

| View | What is coloured | Evidence and source |
|---|---|---|
| Lesion | each candidate's MedSAM contour filled in its colour, a lighter margin band up to 3 mm outside it, the seed box (dashed) and the longest diameter on the slice (yellow); a dotted outline where the contour is unsure | model inference; band width a placeholder |
| Kinetics | each contour filled by its delayed curve type: persistent (type I, blue), plateau (II, amber), washout (III, red) | the pipeline's contour mean on the original data; cutoffs ±10% and 50/100% wash-in: literature, placeholder until calibrated |
| Enhancement | the subtraction copy as a heat layer in three display bins (25–50%, 50–75%, 75–100% of the study's brightest, its 99.9th percentile in the breast region) | the shipped copy; display bins, not cutoffs |
| Change | on the later study of a pair: both dates' contours (purple), the later contour only (larger now, paired), the aligned earlier contour only (smaller now, paired), a contour proposed on one date only, and the alignment's unreliable blocks (red tint) | model contours after a rigid alignment: a comparison of two dates, not a forecast; a contour on one date only is "later date only" / "earlier date only", never new or gone (§3) |
| Density (mammograms) | the dense pixels (Otsu inside the breast on the shipped copy) and the breast tinted in MONAI's class colour for the view, the outline and the nipple | dense pixels: placeholder rule (27–34% per view on the copy against 26–32% on the originals); MONAI's class: model inference, one per view, not a BI-RADS assessment |
| Search | the squares that match a search, darker the stronger, from 15% | model inference or a rule on one |

The dashed line on every MRI view is the seed rule's search limit (the intermammary cleft plus
10 mm, a placeholder): lesions behind it are never proposed.

**Why kinetics are not drawn per pixel.** The shipped copies are 8-bit with one window shared by
every phase, and the window's lower end is not stored; the brightest 0.2% of the early phase are
clipped at 255, which is where a lesion is. Recovering the window from the pipeline's own contour
means fits only roughly (a linear fit over the 12–15 phase means per study, R² 0.95–0.996), and
up to 55% of a contour's early-phase pixels are clipped (case 563 C1). A per-pixel curve map from
the copies would look like a finding and be noise, so the Kinetics view colours whole contours
by the measured curve, and a square outside the contours shows its brightness per phase on the
copy as a shape only, with its clipped share.

**Slices.** Streamlit gives a chart a new identity whenever its figure changes, which drops the
browser's zoom; so the map carries the chosen slice and the 7 on each side as plotly frames, and
the **Slice** slider inside the map steps through them in the browser with the zoom kept (the
view buttons and the opacity slider still apply). **Go to slice** above the map jumps further and
shows the whole slice again; so do the Candidate control, a pointer on another slice and a search
spot, each zoomed on its target. One window weighs 1.0–1.2 MB (15 slices: the image as a JPEG,
the overlays as one-pixel-per-pixel PNGs, the hover numbers as int16 typed arrays, one hover
template per kind of square); it is built in about 1–2 s the first time and kept for reruns.

**Hover.** A fixed-size box per square of about 4.5 mm (every box has the same lines; a
fixed-width rule keeps its width): what the square is (inside a contour, its margin band, breast
tissue, behind the search limit), the candidate's size, wash-in and curve, the subtraction's
brightness, the distance to the nipple (3D, approximate: the breast's most anterior skin point on
the copy), to the nearest skin in the slice, to the search limit, and the square's place; mammogram
squares: the dense-pixel share, MONAI's and mammoscreen's density, mammoscreen's score for the
breast, the distance to the nipple and to the chest-wall edge. "Model inference" on every box.

**Click.** A click opens the square in the Spot panel, on whichever slice of the window it was
clicked: the pre-contrast, early and subtraction copies around it at the copy's own resolution
(enlarged without smoothing), where it is, why it has its colour, how sure (for a contour: unsure
or not on that slice, the distance of the delayed change from the nearest cutoff, the one-pixel
volume range), what to check by eye (the margin in the band, the internal enhancement, the curve
on the original series), the brightness curve on the copy outside contours, and a review mark;
inside a contour the candidate's full story follows (its mark is the candidate's). A pointer
opens its candidate.

**Pointers.** The look-here queue's candidates (C1–C3) are drawn at their box on the slice in
their own colour, and on other slices in grey with the slice they are on ("C3 · slice 45"); their
hover box carries the look-here reasons. A search replaces them with its spots Q1…Q5.

**Search inside the scan.** Known words only: a candidate (lesion, mass, enhancing lesion, C2,
largest), a curve (washout, plateau, persistent, fast, type III), the margin band (spiculated,
margin: the map cannot judge a shape, it marks where to look), the chest wall (tissue within
5 mm in front of the search limit), unsure contours, change (on a pair; one date says so), dense
(mammograms). Scores are per square across the whole study, so each spot names its slice or view;
the map colours the matches on the slice shown, and Colour by match and Clear sit under it. What a
map cannot see gets an honest answer with the test that can: calcifications (not visible at the
shipped 0.46 mm, nor on MRI), lymph nodes (the seed rule never looks in the axilla), histology,
receptor status, grade, mutations, distant metastases, whether an area is cancer, a BI-RADS
assessment.

**Export.** The map picture of a view at the shown slice or view (PNG: the image with the layer,
the contours and pointers, a title, the colour key and a footer that no BI-RADS assessment or
diagnosis is made), and the study report in Markdown: what was imaged (observed), the overview,
the measurements or density opinions with their evidence labels, the look-here pointers with the
reviewer's marks and square marks, the change over time, every cutoff with its source, the known
failures. The JSON and CSV downloads stay.

**Labels.** The contour and every class are model inferences; the kinetics cutoffs are literature
values used as placeholders; the margin band is a placeholder and the square size a design
choice; the dense-pixel rule is a placeholder; the example pair is public example data of
another patient and says so; the only BI-RADS category shown is the study's own structured report
(BI-RADS 6, observed) and the map makes no assessment.

| Feature (the slide map's, PR #150) | Radiology map | Status |
|---|---|---|
| The image underneath, see-through layers | MRI phase or mammogram; Lesion, Kinetics, Enhancement, Change, Density | implemented |
| Opacity slider and view buttons inside the chart | the same, plus the Slice slider (frames) | implemented |
| Fixed-size hover box | per 4.5 mm square, with distances | implemented |
| Click opens the Spot panel | the square on any slice of the window, its candidate | implemented |
| Pointers | C1–C3 on and off the slice; Q1…Q5 while searching | implemented |
| Zoom, drag, Whole section | scroll, drag, Whole image; kept across views and window slices | implemented |
| Legend with sources | per view, cutoffs tagged | implemented |
| Class highlight | not needed: three candidates, each in its own colour | not built |
| Search inside the image, Q1…Q5, colour by match, clear | the same, across slices and views | implemented |
| Map picture (PNG) per view | at the shown slice or view | implemented |
| Report (Markdown) | the study report | implemented |
| Slide viewer one click away | not applicable (the copy is the map's image; the originals stay at TCIA) | not built |

**Memory and speed.** Fresh servers, one headless walk of every imaging file's radiology page
(cases 563, 937, 564, 537, 926 and SYNTHETIC-001's reports) after a slide page, so plotly is loaded
on both sides as in use: main (1c07626) 435 MB at the first screen and 613 MB after the walk, this
branch 436 and 616 MB. An MRI page took 4.3–5.4 s against 3.1–4.3 s with the Altair viewer (the
window's first build); a window's figure is kept for reruns (three kept) and its slices' map data
in a shared cache of 16. Each slice map stores its hover wordings once (an int16 index per square):
storing them per square had cost about 50 MB over the same walk.

**Where the Change view shows.** On the later study of a file that holds two dates (no bundled
file does; the public example pair opened as a file on the workbench's standalone page), and in
every MRI page's "Change over time on a public example pair" section, where the example's later
study opens on the map in the Change view above the side-by-side panes, labeled another
patient's public data, with hover only (no Spot panel, no mark).

**Not built, and limits.** Coronal and sagittal stay in Three planes (the map is axial). The
square's curve outside the contours is the copy's brightness, not a measurement. Pairs of
mammogram dates and lesion candidates on mammograms do not exist here (§5). A jump with Go to
slice, the Candidate control, a pointer on another slice or a search spot rebuilds the map and
shows its target's own zoom, not the one the reader had.

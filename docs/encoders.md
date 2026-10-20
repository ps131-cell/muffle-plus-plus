# Pretrained models per workbench: what is measured, what waits for access

Written 2026-10-20. Part 1 compares the pathology tile encoders on the slide spike's tiles; part 2
says which model each other workbench should use and what access it needs. Licenses and status
also sit in [`registry.md`](registry.md); the click-throughs are in
[`model_access.md`](model_access.md); a GPU run of everything is in [`gpu.md`](gpu.md).

## 1. Pathology tile encoders on the BCSS spike

**Task.** The slide spike's tiles (`scripts/slide_spike.py tiles`): 2,214 tiles of 224 px at
0.5 µm/px from BCSS-annotated regions of 11 TCGA-BRCA diagnostic slides (one per patient). Each
encoder embeds every tile; a logistic-regression head (C = 0.1, class-balanced) learns five BCSS
classes from the pure, quality-passed tiles of 8 slides (1,052 tiles) and is scored on 3
patient-disjoint held-out slides (357 tiles: TCGA-C8-A26X, TCGA-C8-A26Y, TCGA-EW-A1OV). Per-class
columns are recall on the held-out tiles. Same tiles, same split and same head for every encoder,
so the rows compare encoders and nothing else.

**How far to trust it.** Three held-out slides and 11 necrosis tiles: differences of a few points
are noise. Path Foundation and Midnight-12k were pretrained on TCGA slides (no labels), so these
held-out slides are not unseen by them. A row is *experimentally validated on held-out BCSS
regions only*; no pathologist has reviewed any map.

**Speed.** Tiles per second on this PC's CPU (Intel Core Ultra 9 288V, WSL2, 8 cores shared with
other sessions), under `nice -n 10`, with the thread count and the 1-minute load average at the
start of the run. Minutes per slide extrapolate to a 15,000-tile whole slide at the measured rate.

| Encoder | License | Gate | Params (M) | Tiles/s measured (device, threads, 1-min load) | Min per 15k-tile slide | Held-out accuracy (balanced) | tumor | stroma | lymphocytes | necrosis | fat |
|---|---|---|---|---|---|---|---|---|---|---|---|
| `kaiko-ai/midnight` | MIT | none | 1,137 | 0.194 (cpu, 8 threads, load quiet, 24-tile timing from the 2026-10-19 spike) | 1,289 | not run (CPU too slow) | – | – | – | – | – |
| `wisdomik/QuiltNet-B-32` | MIT | none | 88 | 5.146 (cpu, 2 threads, load 0.91 → 13.83) | 49 | 0.877 (0.854) | 0.89 | 0.92 | 0.74 | 0.73 | 1.00 |
| `google/path-foundation` | HAI-DEF terms | click-through (instant) | 22 | pending access | – | pending access | – | – | – | – | – |
| `prov-gigapath/prov-gigapath-flash` | Apache-2.0 | contact info (instant) | 22 | pending access | – | pending access | – | – | – | – | – |
| `histai/hibou-b` | Apache-2.0 | contact info (instant) | 86 | pending access | – | pending access | – | – | – | – | – |
| `histai/hibou-L` | Apache-2.0 | contact info (instant) | 304 | pending access | – | pending access | – | – | – | – | – |
| `bioptimus/H-optimus-0` | Apache-2.0 | contact info (instant) | 1,100 | pending access | – | pending access | – | – | – | – | – |
| `paige-ai/Virchow` | Apache-2.0 (+ card terms) | institutional email (approval) | 632 | pending access | – | pending access | – | – | – | – | – |
| `MahmoodLab/UNI2-h` | CC BY-NC-ND 4.0, **local only** | institutional email (approval) | 681 | pending access | – | pending access | – | – | – | – | – |
| `MahmoodLab/CONCH` | CC BY-NC-ND 4.0, **local only** | institutional email (approval) | 90 | pending access | – | pending access | – | – | – | – | – |

To fill a pending row (in WSL, from the clone, `~/muffle-encoders/.venv` active; the token line is only needed if `HF_TOKEN` is not in `.env`):

- `kaiko-ai/midnight`:
  `python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/midnight --model kaiko-ai/midnight && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/midnight --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `google/path-foundation`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/path-foundation --model google/path-foundation && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/path-foundation --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `prov-gigapath/prov-gigapath-flash`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/prov-gigapath-flash --model prov-gigapath/prov-gigapath-flash && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/prov-gigapath-flash --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `histai/hibou-b`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/hibou-b --model histai/hibou-b && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/hibou-b --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `histai/hibou-L`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/hibou-L --model histai/hibou-L && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/hibou-L --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `bioptimus/H-optimus-0`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/H-optimus-0 --model bioptimus/H-optimus-0 && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/H-optimus-0 --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `paige-ai/Virchow`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/Virchow --model paige-ai/Virchow && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/Virchow --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `MahmoodLab/UNI2-h`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/UNI2-h --model MahmoodLab/UNI2-h && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/UNI2-h --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `MahmoodLab/CONCH`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/CONCH --model MahmoodLab/CONCH && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/CONCH --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`

**Reading the table.**
- QuiltNet-B-32 (MIT, ungated) is what the slide workbench uses today. Measured here at 2 threads
  while other sessions pushed the load from 0.9 to 13.8; the spike measured ~10 tiles/s on a quiet
  machine at 6 threads (`decisions.md`, 2026-10-19), so ~25 min per 15k-tile slide is the
  realistic CPU figure, ~49 min the loaded one.
- Midnight-12k (MIT, ungated, ViT-g) was timed only (24 tiles, quiet machine, 8 threads): 0.19
  tiles/s is ~21 h per 15k-tile slide, and ~3 h for the 2,214 spike tiles, more than the hour this
  comparison allowed. Its accuracy waits for the GPU run.
- The other eight wait for a Hugging Face click-through. Which one to try first: **Hibou-B**
  (Apache-2.0, ViT-B: the strongest open encoder that still embeds a slide on this CPU in about an
  hour, by the survey's arithmetic) and **GigaPath-Flash** (Apache-2.0, ViT-S: minutes per slide). Path Foundation is the
  other ViT-S, under Google's HAI-DEF terms. The ViT-L/H/g models (Hibou-L, Virchow, UNI2-h,
  H-optimus-0, Midnight) belong on the GPU. **UNI2-h and CONCH are local only**
  (CC BY-NC-ND 4.0): their numbers may appear here as aggregates, nothing else they produce may
  leave the machine, and `embed` / `result` refuse paths inside the repository for them.
- **Swapping the encoder in the workbench** is one command once a row beats QuiltNet: train its
  head as above, then `python scripts/slide_spike.py result --work <run> --slide TCGA-C8-A26X-DX1
  --out app/workbenches/slides_example` (open-license encoders only). The result folder records
  the encoder's name, license and gate, which the workbench shows in its provenance line.

## 2. Models for the other workbenches

Verdicts from the cards and license texts, read 2026-10-20; nothing below was run. Compute figures
are estimates.

**Lesion contours (radiology).** *MedSAM* (`wanglab/medsam-vit-base`, the same weights as
`flaviagiammarino/medsam-vit-base`) is SAM ViT-B fine-tuned on 1.09M medical image–mask pairs
across 15 modalities: a box drawn by the clinician becomes a lesion contour and an area, which
the radiology workbench can show per lesion as model inference. Apache-2.0, ungated: **usable
now**. ViT-B on a 1024 px input is roughly a second or two per image on this CPU (estimate); the
mask decoder is instant once the image is encoded. *MedSAM2* (`wanglab/MedSAM2`) extends this to
volumes and video (SAM 2.1 based, with CT-lesion and MRI liver-lesion checkpoints), which is what
a 3D breast MRI or staging CT contour needs. CC BY-SA 4.0: **usable now**, with attribution; if
we ever share modified weights they must carry the same license (masks are outputs, not weights).
GPU preferred for volumes; the repo also ships an "efficient" CPU variant trained for RECIST
lesions.

**General promptable segmentation.** *SAM 3* (`facebook/sam3`, 0.86B parameters) adds text
prompts ("tumor", "lymph node") on natural images; it is not tuned on medical images, so it would
be a second opinion behind MedSAM. Its SAM License grants royalty-free use, modification and
redistribution (with the license attached) and excludes trade-controlled and military uses; a
research clinician app is allowed. The gate is **manual review** (name, date of birth, country,
affiliation, job title): **pending click-through**. GPU. *SAM 2.1* (`facebook/sam2.1-hiera-large`,
224M) is Apache-2.0 and ungated: **usable now** if a general model is wanted without the wait.

**Report extraction (clinical documents).** *MedGemma 1.5 4B* (`google/medgemma-1.5-4b-it`) is the
strongest local option found: it reads report text and lab-report images and the card reports
lab-report extraction macro-F1 of 71–91 on its own datasets, with outputs "preliminary". It would
extract receptors, stage, drugs and dates with the quoted source sentence, **locally only** (raw
report text never goes to Token Factory). HAI-DEF terms, instant click-through: **pending
click-through**. 4.3B parameters, ~8.6 GB in bf16; CPU works for a handful of reports at minutes
each (estimate), a GPU for a batch. *OpenMed NER OncologyDetect* (278M, xlm-roberta-base) tags
cancer, organ, tissue and gene entities (BioNLP 2013 CG; card F1 0.79) to highlight source
sentences; it does not read a diagnosis. Apache-2.0, ungated, CPU: **usable now**.

**Mammography.** *mammoscreen* (`ianpan/mammoscreen`) is an ensemble of three EfficientNetV2-S
nets (61M) giving a cancer likelihood and breast density from CC and MLO views; the card reports
AUROC 0.945 on held-out RSNA 2023 challenge data and recommends the companion crop model
`ianpan/mammo-crop`. Both Apache-2.0, ungated, with repo code (pin `b619a889` and `bec2e302`):
**usable now**. CPU is fine for a few exams at 2048 × 1024 (estimate). The RSNA training data's
terms were not retrieved. *Mirai* (MIT, GitHub) gives a 5-year risk from the four standard
screening views (C-index 0.76–0.81 in three external cohorts): **usable now**, but only for
patients with a complete four-view exam, which none of the open sets guarantees.

**Breast MRI.** *Pillar0-BreastMRI* (`YalaLab/Pillar0-BreastMRI`, 94M, 3D Atlas encoder aligned
with radiology reports) gives exam embeddings for linear probes (authors' internal mean AUROC 82.9
over 35 report findings; preprint). ECL-2.0, gate asks name and organization: **pending
click-through**. It loads code from its repo; CPU speed for a volume is unknown, a GPU is safer.
No breast MRI pipeline exists yet, so this is access-only for now.

**Nuclei in H&E (slide workbench).** *StarDist* `2D_versatile_he` (BSD-3-Clause code; weights
trained on MoNuSeg 2018 and TNBC, the latter CC BY 4.0) segments nuclei on CPU in seconds per tile:
**usable now**, but check MoNuSeg's terms before publishing masks made with it. *CellViT* (code
"Apache 2.0 with Commons Clause"; checkpoints trained on PanNuke, CC BY-NC-SA 4.0) and *HoVer-Net*
(code MIT; its README says the PanNuke weights are CC BY-NC-SA 4.0) also type the nuclei
(neoplastic, inflammatory, connective, dead, epithelial), which StarDist does not, but their
weights are non-commercial: **local only**. CellViT-SAM-H wants a 24 GB GPU.

**Plumbing.** *LazySlide* (MIT, `pip install lazyslide`) does tissue detection, tiling and calls to
30+ pathology encoders with each one's license listed; it is the alternative to growing
`slide_spike.py` if the whole-slide pipeline needs more than our tiler. **Usable now**.

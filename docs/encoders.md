# Pretrained models per workbench: what is measured, what waits for access

Written 2026-10-20, encoder runs 2026-10-21/22. Part 1 compares the pathology tile encoders on the
slide spike's tiles; part 2 says which model each other workbench should use and what access it
needs. Licenses and status also sit in [`registry.md`](registry.md); the click-throughs are in
[`model_access.md`](model_access.md); a GPU run of everything is in [`gpu.md`](gpu.md).

## 1. Pathology tile encoders on the BCSS spike

**Task.** The slide spike's tiles (`scripts/slide_spike.py tiles`): 2,214 tiles of 224 px at
0.5 µm/px from BCSS-annotated regions of 11 TCGA-BRCA diagnostic slides (one per patient). A
logistic-regression head (C = 0.1, class-balanced) learns five BCSS classes from the pure,
quality-passed tiles of 8 slides (1,052 tiles) and is scored on 3 patient-disjoint held-out slides
(357 tiles: TCGA-C8-A26X, TCGA-C8-A26Y, TCGA-EW-A1OV). Per-class columns are recall on the
held-out tiles. Same tiles, same split, same head for every encoder, so the rows compare encoders
and nothing else. QuiltNet-B-32 and GigaPath-Flash embedded all 2,214 tiles; the slower encoders
embedded only the 1,409 tiles the head uses (`embed --labeled-only`), which changes nothing in the
head or its score.

**How far to trust it.** Three held-out slides, 357 tiles, 11 of them necrosis: a difference of a
few points is within noise (the paired test below says how much). Encoders that saw TCGA slides
in pretraining (column "TCGA in pretraining"; no labels involved) have seen these held-out slides
or slides like them. A row is *experimentally validated on held-out BCSS regions only*; no
pathologist has reviewed any map.

**Speed.** Tiles per second on this PC's CPU (Intel Core Ultra 9 288V, WSL2, 8 cores shared with
three other sessions building at the same time), under `nice -n 10`, with the thread count and
the 1-minute load average at the start and end of the run. Minutes per slide extrapolate to a
15,000-tile whole slide at that rate; on a quiet machine every rate is roughly 2–3× higher (the
spike measured QuiltNet at ~10 tiles/s quiet against 5.1 here). GigaPath-Flash's rate is the
median over the 5 slides embedded after a restart.

| Encoder | License | Gate | Params (M) | TCGA in pretraining | Tiles/s measured (device, threads, 1-min load) | Min per 15k-tile slide | Held-out accuracy (balanced), C = 0.1 | tumor | stroma | lymphocytes | necrosis | fat | Held-out accuracy (balanced), C chosen by CV on training slides |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `kaiko-ai/midnight` | MIT | none | 1,137 | yes (TCGA only) | 0.194 (cpu, 8 threads, load quiet, 24-tile timing from the 2026-10-19 spike) | 1,289 | not run | – | – | – | – | – | – |
| `wisdomik/QuiltNet-B-32` | MIT | none | 88 | not listed (Quilt-1M: videos, papers, social media) | 5.146 (cpu, 2 threads, load 0.91 → 13.83) | 49 | 0.877 (0.854) | 0.89 | 0.92 | 0.74 | 0.73 | 1.00 | 0.866 (0.886), C = 0.003 |
| `google/path-foundation` | HAI-DEF terms | click-through (instant) | 22 | yes (TCGA only) | not run | – | not run | – | – | – | – | – | – |
| `prov-gigapath/prov-gigapath-flash` | Apache-2.0 | contact info (instant) | 22 | not stated (distilled from Prov-GigaPath: Providence slides) | 3.024 (cpu, 4 threads, load 12.16 → 11.18) | 83 | 0.919 (0.917) | 1.00 | 0.87 | 0.90 | 0.82 | 1.00 | 0.922 (0.923), C = 0.01 |
| `histai/hibou-b` | Apache-2.0 | contact info (instant) | 86 | not listed (private HistAI set) | 0.521 (cpu, 4 threads, load 14.45 → 11.79) | 480 | 0.880 (0.849) | 0.94 | 0.80 | 0.96 | 0.55 | 1.00 | 0.871 (0.849), C = 0.003 |
| `histai/hibou-L` | Apache-2.0 | contact info (instant) | 304 | not listed (private HistAI set) | 0.405 (cpu, 4 threads, load 11.15 → 7.69) | 617 | 0.810 (0.849) | 0.96 | 0.62 | 0.94 | 0.73 | 1.00 | 0.807 (0.807), C = 0.01 |
| `bioptimus/H-optimus-0` | Apache-2.0 | contact info (instant) | 1,100 | not listed (proprietary 500k slides) | not run | – | not run | – | – | – | – | – | – |
| `paige-ai/Virchow` | Apache-2.0 (+ card terms) | institutional email (approval) | 632 | no (MSKCC slides) | not run | – | not run | – | – | – | – | – | – |
| `MahmoodLab/UNI2-h` | CC BY-NC-ND 4.0, **local only** | institutional email (approval) | 681 | no (Mass General Brigham) | 0.181 (cpu, 4 threads, load 7.09 → 4.28) | 1,381 | 0.838 (0.793) | 0.71 | 0.91 | 0.88 | 0.64 | 0.83 | 0.832 (0.788), C = 0.003 |
| `MahmoodLab/CONCH` | CC BY-NC-ND 4.0, **local only** | institutional email (approval) | 90 | no (card: no large public slide sets such as TCGA) | 0.266 (cpu, 4 threads, load 5.96 → 14.45) | 940 | 0.896 (0.844) | 0.98 | 0.88 | 0.85 | 0.55 | 0.97 | 0.888 (0.912), C = 0.01 |
| `majiabo/GPFM` | CC BY-NC-ND 4.0 (repository; HF tag says MIT), **local only** | none | 304 | not confirmed (72,000 public slides; source list not read) | 0.623 (cpu, 4 threads, load 4.61 → 7.38) | 401 | 0.863 (0.824) | 0.92 | 0.82 | 0.89 | 0.55 | 0.94 | 0.885 (0.872), C = 0.01 |

To fill a row that was not run (in WSL, from the clone, `~/muffle-encoders/.venv` active; `HF_TOKEN` read from `.env`; add `--labeled-only` for the slow models and `train --cv` for the CV column):

- `kaiko-ai/midnight`:
  `python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/midnight --model kaiko-ai/midnight && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/midnight --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `google/path-foundation`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/path-foundation --model google/path-foundation && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/path-foundation --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `bioptimus/H-optimus-0`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/H-optimus-0 --model bioptimus/H-optimus-0 && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/H-optimus-0 --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`
- `paige-ai/Virchow`:
  `HF_TOKEN=… python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work ~/muffle-encoders/runs/Virchow --model paige-ai/Virchow && python scripts/slide_spike.py train --work ~/muffle-encoders/runs/Virchow --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1`

**Local only.** UNI2-h, CONCH and GPFM are CC BY-NC-ND 4.0 (GPFM: its official repository; its
Hugging Face tag says MIT, but it is distilled from UNI, CONCH and Phikon, whose terms count models
trained on their outputs as derivatives). Their embeddings, heads and maps stay in
`~/muffle-encoders` on this machine; only the aggregate numbers above are reported, and
`embed` / `result` refuse any path inside the repository for them. None of them can replace
QuiltNet in the app.

**Paired check against QuiltNet-B-32** (same 357 held-out tiles; `~/muffle-encoders/paired.py`).
Difference in accuracy, tile bootstrap 95% interval, tiles right only with this encoder / only with
QuiltNet, exact McNemar p. Tiles from one slide are correlated, so the interval and p are
optimistic; read them as "is there a signal at all".

| Encoder | Accuracy minus QuiltNet | 95% interval | Right only here / only QuiltNet | McNemar p |
|---|---|---|---|---|
| GigaPath-Flash | +0.042 | +0.003 to +0.081 | 33 / 18 | 0.049 |
| CONCH (local only) | +0.020 | −0.017 to +0.056 | 25 / 18 | 0.36 |
| Hibou-B | +0.003 | −0.039 to +0.042 | 27 / 26 | 1 |
| GPFM (local only) | −0.014 | −0.056 to +0.028 | 26 / 31 | 0.6 |
| UNI2-h (local only) | −0.039 | −0.081 to +0.003 | 22 / 36 | 0.087 |
| Hibou-L | −0.067 | −0.115 to −0.020 | 27 / 51 | 0.009 |

Per held-out slide (TCGA-C8-A26X / -A26Y / EW-A1OV): QuiltNet 0.839 / 0.926 / 0.880;
GigaPath-Flash 0.931 / 0.926 / 0.912; Hibou-B 0.885 / 0.870 / 0.880; Hibou-L 0.805 / 0.870 / 0.796; CONCH 0.816 / 0.907 / 0.926; UNI2-h 0.874 / 0.852 / 0.819; GPFM 0.851 / 0.833 / 0.875. GigaPath-Flash is the only encoder at least as good as QuiltNet on all three slides.

**Hibou.** Its repository's model code needs transformers 4 internals, so the pinned weights are
loaded strictly into transformers 5's own `Dinov2WithRegistersModel` (embeddings, register
placement, SwiGLU and pooler checked line by line against Hibou's code). Hibou-L scoring below
Hibou-B is unexpected for the larger model (its stroma recall drops to 0.62); the card's
preprocessing was used as stated, and the result is reported as measured.

**Not run.** Path Foundation, H-optimus-0 and Virchow: access not granted yet
([`model_access.md`](model_access.md)). Midnight-12k: ViT-g, ~2 h even for the 1,409 head tiles at
the spike's quiet-machine rate and far longer under this load; it belongs in the GPU run.

**Head setting.** Every row uses the head the spike used (C = 0.1, fixed before any of these
encoders was run). Because one C can suit one embedding size better than another, the last column
repeats the fit with C chosen per encoder by leave-one-training-slide-out balanced accuracy on the 8
training slides only (`train --cv`; the held-out slides are untouched). The ranking at the top does
not change: GigaPath-Flash stays first on both accuracy and balanced accuracy; QuiltNet's balanced
accuracy rises to 0.886 with a smaller C, CONCH's to 0.912. UNI2-h stays low under either setting,
which is at odds with its published benchmarks; on three slides and five coarse classes that may
say more about this task than about the encoder, and it is reported as measured.

**Recommendation.** Replace QuiltNet-B-32 with **GigaPath-Flash** (`prov-gigapath/prov-gigapath-flash`,
Apache-2.0) for re-scoring the eight sections. On the held-out slides it raises accuracy from 0.877
to 0.919 (+4.2 points) and balanced accuracy from 0.854 to 0.917 (+6.3), and with C chosen by
cross-validation from 0.866 / 0.886 to 0.922 / 0.923; it is better or equal on each of the three
held-out slides, and the paired test puts the gain just clear of zero (interval +0.3 to +8.1 points,
optimistic because tiles are correlated). The gain is in tumor (0.89 → 1.00), lymphocytes
(0.74 → 0.90) and necrosis (0.73 → 0.82, 11 tiles), with stroma slightly lower (0.92 → 0.87). It is
the only open-license encoder that wins; CONCH, UNI2-h and GPFM are local only in any case. Its
card, like QuiltNet's, puts any deployed use out of scope, so the hosted app keeps showing
precomputed results and runs no encoder. Cost: ViT-S/16 is slower per tile than QuiltNet's
ViT-B/32 on this CPU (3.0 tiles/s at 4 threads under load ~12, ~50 min for a 9,000-tile section
budget), so re-scoring eight sections is an overnight CPU job or minutes on the GPU
([`gpu.md`](gpu.md)). Status after the swap: *experimentally validated on held-out BCSS regions
only*, as before.

**Swapping the encoder in the workbench** is one command per section once the head is trained:
`python scripts/slide_pipeline.py run --slide <svs> --work <new folder> --model <id> --out
app/workbenches/slides_results/<slide>`, with `head.json` and `head_metrics.json` copied from
`~/muffle-encoders/runs/<encoder>/` into the new work folder. Use a **new** work folder per
encoder: `run` reuses a cached `embeddings.npy`, and one encoder's head cannot read another's
embeddings. `python scripts/slide_spike.py result --work <run> ...` does the same for the
spike's example region. Open-license encoders only; the result folders record the encoder's
name, license and gate, which the workbench shows in its provenance line.

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

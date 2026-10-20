# Model and dataset survey for the clinician workspace (breast cancer)

A survey of public pretrained models and datasets for each test type in [`WORKSPACE.md`](WORKSPACE.md),
written 2026-10-19. It answers the open item in `decisions.md` (2026-10-19) and informs which
workbenches ship before the Oct 28 freeze. **Nothing here is used until it is in
[`registry.md`](registry.md)** (CLAUDE.md). Draft registry rows for the recommended slice are in
section 12. The ranked shortlist is section 9 and the access requests are section 10.

## How this was made, and how far to trust it

- **Read-only.** Model cards, dataset pages, papers and API metadata were read on 2026-10-19.
  No model or dataset was downloaded, run or requested.
- **License** means what the source page says: for Hugging Face models, the `license` /
  `license_name` fields of `huggingface.co/api/models/<id>` plus the card text; for datasets, the
  dataset page, the DataCite/Crossref record or the paper's data statement. "Not retrieved" means
  the page could not be read in this session (JavaScript-only site, bot wall), which is not the
  same as "no license".
- **DOIs** were checked against Crossref, DataCite or PubMed. Items with only an arXiv ID are
  preprints and say so.
- **Validation** columns repeat what the authors report on their own cohorts. Under WORKSPACE.md
  training rule 5 none of it is evidence for our task. Independent benchmarks are marked.
- **Compute** is spec-sheet reading and arithmetic, not a benchmark on this PC (section 1).
- Tags: **[NC]** non-commercial only · **[ND]** no derivatives · **[GATED]** access request or
  click-through · **[CONTROLLED]** data use agreement or committee · **[RESTRICTED]** license terms bar
  redistribution, sharing or patient-care use · **[LOCAL]** must stay on this machine (project rule).

## 0. Findings in brief

1. **The strongest pathology encoders are CC BY-NC-ND 4.0 and gated:** UNI2-h, CONCH, Virchow2,
   H-optimus-1, MUSK, TITAN. Virchow2, UNI2-h, CONCH, TITAN and MUSK want an institutional email
   (the Mahmood Lab pages say @gmail/@hotmail/@qq requests are denied); H-optimus-1 and MUSK are
   manual review. In the one independent benchmark found, CONCH ranked first of 19 encoders and
   Virchow2 was close.
2. **Pathology encoders with open licenses exist:** Path Foundation (under Google's terms
   of use), the Apache-2.0 models GigaPath-Flash, Hibou-L, H-optimus-0 and Virchow v1, and
   Midnight-12k (MIT, ungated). Only the two ViT-S models (Path Foundation, GigaPath-Flash) are
   cheap enough to embed whole slides on this PC's CPU; Hibou-B (ViT-B, Apache-2.0) is about an hour
   per slide.
3. **No breast-specific pathology encoder with released weights was found.** BRAVE (arXiv
   2605.08207, 101,638 breast slides) links no code or weights.
4. **Breast pathology data you can ship:** BCSS (CC0; tissue-region labels on TCGA-BRCA slides),
   Camelyon (CC0; lymph-node metastasis annotations), CPTAC-BRCA slides (CC BY 4.0; images without
   tissue labels). TIGER annotations are NC; BACH and HEROHE are ND; BRACS states no terms.
5. **Radiology:** TCGA-BRCA MRI (139 patients, CC BY 3.0) is the only imaging that joins our
   multi-omic cohort. The best-annotated breast MRI sets are NC (Duke, MAMA-MIA with its nnU-Net
   weights). Permissive pretrained models: Pillar0-BreastMRI (ECL-2.0, preprint), Mirai (MIT),
   mammoscreen (Apache-2.0).
6. **CT/PET staging has nothing breast-specific.** autoPET covers lymphoma, melanoma and lung.
   Generic tools: TotalSegmentator (Apache-2.0, runs on CPU), ULS23 baseline (CC BY 4.0), NVIDIA
   models (GPU only; the CT+MR weights are non-commercial).
7. **Labs need rules, not a model:** EGTM (a rise of at least 25% over the previous value, confirmed
   within a month) and ASCO 2007 (adjunct only), plus EuBIVAS biological variation. The only cancer
   lab timelines are in MSK-CHORD, which is local-only.
8. **ctDNA: no public pretrained model and no open, labeled, serial breast ctDNA data with raw reads
   were found** (web search; GEO and EGA were not searched directly). The evidence is PADA-1, SERENA-6 and the clonal-hematopoiesis paper. A labeled
   synthetic series with these rules is the honest option.
9. **Tumor DNA:** CIViC (CC0), AlphaMissense predictions (CC BY 4.0), VEP (Apache-2.0) and ClinVar
   (attribution asked) can ship. OncoKB forbids redistribution, sharing with third parties and
   patient-care use. COSMIC is free for academic use only.
10. **RNA, methylation, protein:** PAM50 via genefu (Artistic-2.0) or BreastSubtypeR (GPL-3);
    MSigDB Hallmark (CC BY 4.0). The RNA and methylation foundation models found (BulkFormer,
    CpGPT, MIT) show no breast validation on their cards.
11. **Clinical text:** TCGA-Reports (CC BY 4.0) plus local small models. Project rule: raw report
    text must not go to Token Factory. Published breast report extraction (F1 above 95% at document
    level) used a large hosted model.

## 1. Compute basis for "runs on this PC?"

This PC: Intel Core Ultra 9 288V (4 P-cores + 4 E-cores), 32 GB shared LPDDR5X, Arc 140V iGPU
(8 Xe2 cores, "up to 67 TOPS" in press specs), no CUDA. PyTorch's XPU page lists Core Ultra Mobile
Processors (Series 2) with Arc Graphics, codename Lunar Lake, among its validated client hardware
on Windows 11, Ubuntu and WSL2 Ubuntu (docs.pytorch.org, 2.14). Not tested here. Treat CPU as the baseline.

Cost of one 224-px tile (2 × parameters × tokens, my arithmetic) and a planning guess of
0.2–0.5 TFLOP/s sustained on the CPU (an assumption, not a measurement). A 20× diagnostic slide
usually has 10,000–50,000 tissue tiles; 20,000 is used below. **Embed 200 tiles with the chosen
model before committing to it.**

| Encoder class | Examples in this survey | GFLOP / tile | Est. tiles/s on CPU | 20k-tile slide on CPU |
|---|---|---|---|---|
| ViT-S/16 | Path Foundation, GigaPath-Flash tile encoder | ~9 | 22–55 | 6–15 min |
| ViT-B/16 | Hibou-B, CONCH vision tower (its input size is not stated on the card) | ~35 | 6–14 | 25–60 min |
| ViT-L/16 | Hibou-L, UNI, Phikon-v2 | ~120 | 1.7–4 | 1.3–3.3 h |
| ViT-H/14 | Virchow, Virchow2, UNI2-h | ~330 | 0.6–1.5 | 3.7–9 h |
| ViT-g/14 | H-optimus-0/1, Prov-GigaPath tile encoder, Midnight | ~590 | 0.34–0.85 | 6.5–16 h |

So on this PC: ViT-S and ViT-B models can embed whole slides; ViT-L is overnight; ViT-H and ViT-g
need a GPU (or a tile subsample of a few thousand tiles for a demo slide). Streamlit Community Cloud
will not run any of them, so demo slides need precomputed features shipped as a release asset (as
`demo-bundle-v1` does), not committed.

## 2. Pathology: H&E whole-slide images

| Candidate | What it does | License (as stated; where) | Access | Compute; this PC? | Published validation | Plugs into the workbench as |
|---|---|---|---|---|---|---|
| **Encoder.** [Path Foundation](https://huggingface.co/google/path-foundation) | ViT-S tile encoder for H&E, 384-d, 224-px patches at 5×, 10× or 20× | `health-ai-developer-foundations`: "governed by the Health AI Developer Foundations terms of use" (card, API). [Terms](https://developers.google.com/health-ai-developer-foundations/terms): fine-tuned weights may be shared if the §3.2 use restrictions are passed on; commercial use not addressed; "Clinical Use" includes use in a research study | **[GATED]**, click-through, instant (API `auto`) | ~22M params (community table), ~9 GFLOP/tile; est. 6–15 min per 20k tiles. **Yes** | arXiv:2310.13259 (preprint). Card: linear-probe AUC 93% (CI 92.9–93.8) on a task suite. Trained on TCGA only (60M patches), so TCGA-BRCA slides were seen in pretraining. "Limited set of scanners and countries" | Default local tile embedder; logistic heads trained on BCSS classes give the tile class overlay (model inference) |
| **Encoder.** [GigaPath-Flash](https://huggingface.co/prov-gigapath/prov-gigapath-flash) | ViT-S/16 tile encoder (22M, 384-d) + 12-layer LongNet slide encoder (21M, 384-d), distilled from Prov-GigaPath | `apache-2.0` (card, API); abstract: "open-weight, Apache-2.0-licensed family" | **[GATED]**, contact-info click-through (API `auto`) | ViT-S. **Yes** | arXiv:2607.18218 (preprint, 20 Jul 2026, not peer reviewed). Card gives no numbers | Slide-level embedding (similar-slide search, slide flags) and a second cheap tile encoder for a "models disagree" queue |
| **Encoder.** [Hibou-L](https://huggingface.co/histai/hibou-L) | DINOv2-style ViT-L with registers, 0.3B params; needs `trust_remote_code=True` (runs repo code) | `apache-2.0` (card, API) | **[GATED]**, contact-info click-through (API `auto`) | ViT-L; est. 1.3–3.3 h per slide on CPU. **Overnight only**; try the iGPU | arXiv:2406.05074 (preprint). Trained on a 1.2B-image private set | Stronger second encoder for the same heads, precomputed for 2–3 demo slides |
| **Encoder.** [H-optimus-0](https://huggingface.co/bioptimus/H-optimus-0) | 1.1B ViT-g/14, 224 px at 0.5 µm/px, 1536-d | `apache-2.0`: "released under the Apache-2.0 license" (card, API) | **[GATED]**, contact-info click-through (API `auto`) | ViT-g. **No** on CPU; GPU precompute | None published (software citation only). Card: not reviewed or approved by any regulator; needs independent validation | High-capacity encoder if GPU time exists |
| **Encoder.** [Prov-GigaPath](https://huggingface.co/prov-gigapath/prov-gigapath) | ViT-g/14 tile encoder (1536-d) + LongNet slide encoder | `apache-2.0` tag, but the card limits use: "intended to be used solely for (I) future research on pathology foundation models", "not intended to be used in clinical care", "Any deployed use case of the model --- commercial or otherwise --- is out of scope". A hosted demo that runs the model may count as deployed | **[GATED]**, contact-info click-through (API `auto`) | ViT-g. **No** on CPU (slide encoder is light) | Nature 2024, [10.1038/s41586-024-07441-w](https://doi.org/10.1038/s41586-024-07441-w): 26 tasks (9 cancer subtyping incl. BRCA IDC vs ILC, 17 pathomics); pretrained on 171,189 slides from >30,000 patients | Slide encoder for slide-level scores; offline use only |
| **Encoder.** [Midnight-12k](https://huggingface.co/kaiko-ai/midnight) | DINOv2 ViT-g (card: 1B params), 224 px, trained on TCGA only (12k slides) | `mit` (card, API). The 92k variants are proprietary/gated | open, ungated | ViT-g. **No** on CPU | arXiv:2504.05186 (preprint); eva and HEST benchmarks. TCGA-only pretraining overlaps TCGA-BRCA evaluation slides | The only ungated MIT encoder; offline precompute |
| **Encoder.** [Virchow (v1)](https://huggingface.co/paige-ai/Virchow) | ViT-H/14, 632M, 1280-d, 1.5M MSKCC slides | `apache-2.0`: "released under the Apache License, Version 2.0" (card, API). Card: "not intended for use in medical diagnosis, treatment, or prevention of disease of real patients" | **[GATED]**, contact info + institutional email (card); API `auto` | ViT-H. **No** on CPU | Nat Med 2024, [10.1038/s41591-024-03141-0](https://doi.org/10.1038/s41591-024-03141-0) | Open-license alternative to Virchow2 (GPU) |
| **Encoder.** [UNI2-h](https://huggingface.co/MahmoodLab/UNI2-h) | ViT-H/14, 681M, 1536-d, 224 px; >200M tiles from >300k H&E and IHC slides (card also says >350k), Mass General Brigham | `cc-by-nc-nd-4.0`: "may only be used for non-commercial, academic research purposes" **[NC][ND]**; "agree not to distribute, publish or reproduce a copy of the model" | **[GATED]**: institutional email must match the HF primary email; "@gmail/@hotmail/@qq ... will be denied" (gate form); API `auto` | ViT-H. **No** on CPU | UNI (v1) Nat Med 2024, [10.1038/s41591-024-02857-3](https://doi.org/10.1038/s41591-024-02857-3); the UNI2-h card cites the same paper, no separate UNI2 paper | Reference encoder, local only |
| **Encoder.** [CONCH](https://huggingface.co/MahmoodLab/CONCH) and [CONCH v1.5](https://huggingface.co/MahmoodLab/conchv1_5) | Vision (ViT-B/16, 90M) + text (110M) encoders, 1.17M image-caption pairs; zero-shot tile classification, retrieval, MI-Zero slide classification. The public release omits the captioning decoder | `cc-by-nc-nd-4.0`: "released under the CC-BY-NC-ND 4.0 license" **[NC][ND]**. The v1.5 gate text defines derivatives to include "datasets created from" the model | **[GATED]**, same institutional-email terms; API `auto` | ViT-B class; input size not stated on card or README, so measure. Likely CPU-feasible for a few slides | Nat Med 2024, [10.1038/s41591-024-02856-4](https://doi.org/10.1038/s41591-024-02856-4). **Independent benchmark** (Neidlinger et al., [10.1038/s41551-025-01516-3](https://doi.org/10.1038/s41551-025-01516-3)): CONCH best overall of 19 encoders on 13 cohorts incl. breast; Virchow2 close; CONCH+Virchow2 ensemble best in 55% of tasks | Zero-shot text queries for the "look here" queue; second opinion; the colon analyzer already uses it; local only |
| **Encoder.** [Virchow2](https://huggingface.co/paige-ai/Virchow2) | ViT-H/14, 632M, 1280-d, 3.1M MSKCC slides | `cc-by-nc-nd-4.0` **[NC][ND]**. "Requests from commercial entities would be rejected by default"; derivatives "include models trained on outputs from the Virchow2 Model or datasets created from the Virchow2 Model" | **[GATED]**, institutional email; API `auto` | ViT-H. **No** on CPU | arXiv:2408.00738 (preprint); close second in the Neidlinger benchmark | Local second opinion only |
| **Encoders.** [H-optimus-1](https://huggingface.co/bioptimus/H-optimus-1), [MUSK](https://huggingface.co/xiangjx/musk), [TITAN](https://huggingface.co/MahmoodLab/TITAN) (and [Prism](https://huggingface.co/paige-ai/Prism)) | H-optimus-1: 1.1B ViT-g, >1M slides. MUSK: vision-language, 0.7B, 384 px. TITAN: slide encoder (0.2B) on CONCH v1.5 patch features, 335,645 slides, report generation (preview) | All `cc-by-nc-nd-4.0` **[NC][ND]** (cards, API). H-optimus-1: "may only be used for non-commercial, academic research purposes" | **[GATED]**; H-optimus-1 and MUSK **manual review**, TITAN `auto`; TITAN and MUSK want an institutional email (not stated on the H-optimus-1 page) | H-optimus-1 and MUSK are large (No on CPU); TITAN needs CONCH v1.5 features | H-optimus-1: AACR 2026 abstract only, [10.1158/1538-7445.AM2026-LB174](https://doi.org/10.1158/1538-7445.AM2026-LB174). MUSK: Nature 2025, [10.1038/s41586-024-08378-w](https://doi.org/10.1038/s41586-024-08378-w). TITAN: Nat Med 2025, [10.1038/s41591-025-03982-3](https://doi.org/10.1038/s41591-025-03982-3) | Not for the public demo. MUSK/TITAN only to mirror the colon analyzer |
| **Data.** [TCGA-BRCA slides (GDC)](https://portal.gdc.cancer.gov/projects/TCGA-BRCA) | 3,112 SVS files for 1,098 cases: 1,133 diagnostic, 1,979 tissue slides (GDC release 46.0, 10 Aug 2026), all `open`. Same TCGA-BRCA project as our omics (join on case ID) | No license text. GDC docs: "Some data in the GDC is open access, which means that no authentication or authorization is necessary to access it"; terms are "determined by the GDC's Data Access Policies". Cite the TCGA Research Network | open | Slide sizes not checked | n/a | Demo slides (2–3 held-out patients); join to risk-model output by case ID |
| **Data.** [BCSS](https://github.com/PathologyDataScience/BCSS) | Region-level tissue segmentations (class codes in `meta/gtruth_codes.tsv`) on 151 TCGA breast cancer slides, drawn by 25 crowd participants | "licensed under a CC0 1.0 Universal (CC0 1.0) license"; code MIT (README) | open (Google Drive, script) | Small | Bioinformatics 2019, [10.1093/bioinformatics/btz083](https://doi.org/10.1093/bioinformatics/btz083) | Training labels for the breast tissue heads (the counterpart of NCT-CRC-HE-100K / STARC-9). Split by patient; keep demo patients out |
| **Data.** [CPTAC-BRCA slides (TCIA)](https://www.cancerimagingarchive.net/collection/cptac-brca/) | 134 subjects, histopathology SVS, 113 GB | CC BY 4.0 (collection page, DataCite) | open | 113 GB download | DOI [10.7937/TCIA.CAEM-YS80](https://doi.org/10.7937/TCIA.CAEM-YS80) | Second cohort from other institutions to see how the tissue heads behave (class mix, uncertainty); it has no tissue labels, so no accuracy |
| **Data.** [TIGER](https://tiger.grand-challenge.org/Data/) | 195 annotated-ROI slides (151 TCGA-BRCA, 26 RUMC, 18 Jules Bordet), 93 tumor-bulk slides, 82 TIL-score slides; HER2+ and triple-negative | "All training data annotations (for TCGA-BRCA, RUMC, and JB slides) are released under a CC BY-NC 4.0 license" **[NC]** | open (AWS CLI, no sign-in) | Large | No dataset DOI on page | Tumor/stroma/TIL regions for a local-only check |
| **Data.** [BACH](https://iciar2018-challenge.grand-challenge.org/Dataset/) and [HEROHE](https://ecdp2020.grand-challenge.org/) | BACH: 400 microscopy images in 4 classes plus slides with region labels. HEROHE: HER2 status from H&E | BACH: "publicly available under the CC BY-NC-ND license" (3.0 link). HEROHE: "Attribution-NonCommercial-NoDerivs 3.0 Unported" **[NC][ND]**. Both: notify the organisers of publications | BACH: request form. HEROHE: download page not read | Small | BACH [10.1016/j.media.2019.05.010](https://doi.org/10.1016/j.media.2019.05.010); HEROHE [10.3390/jimaging8080213](https://doi.org/10.3390/jimaging8080213) | Local benchmarks only |
| **Tool.** [HistoQC](https://github.com/choosehappy/HistoQC) | Slide-level quality control for digital pathology | BSD-3-Clause-Clear (repo page) | open | CPU | JCO Clin Cancer Inform 2019, [10.1200/CCI.18.00157](https://doi.org/10.1200/CCI.18.00157) | Slide QC before tiling (what was excluded and why) |
| **Tool.** [GrandQC](https://github.com/cpath-ukk/grandqc) | Tissue detection + artifact segmentation (folds, dark spots/foreign objects, pen marks, bubbles/edges, out-of-focus) at 5×/7×/10× | "Creative Commons Attribution-NonCommercial-ShareAlike 4.0 International License" **[NC]** (README) | open (weights on Zenodo 14041538, 14507273) | Stated speed 27–45 s per slide; hardware not stated | Nat Commun 2024, [10.1038/s41467-024-54769-y](https://doi.org/10.1038/s41467-024-54769-y) | Per-tile artifact map for local work; use HistoQC in anything published |
| **Tool.** [LazySlide](https://github.com/rendeirolab/LazySlide) | Python framework: tissue detection, tiling, features from 30+ pathology models, zero-shot, artifact QC; its docs list each model's license (they agree with this survey where they overlap) | "released under the MIT License" (README) | open (`pip install lazyslide`; Windows supported) | CPU or GPU | Nat Methods 2026, [10.1038/s41592-026-03044-7](https://doi.org/10.1038/s41592-026-03044-7) | Plumbing for tiling and encoder calls instead of writing our own |

**Also checked (pathology).** Phikon-v2 `other` = "Owkin non-commercial licence" **[NC]**, ungated,
ViT-L, trained on TCGA, CPTAC and GTEx, arXiv:2409.09173. OpenPath: `apache-2.0`, ViT-g/14, public
data only, but a single-author card with no paper ("in preparation") and 17 downloads: unproven.
OpenMidnight (Sophont): `apache-2.0`, gated `auto`, 0 downloads listed. [Hibou-B](https://huggingface.co/histai/hibou-b):
`apache-2.0`, gated `auto`, ViT-B (86M and 768-d per a community table), same paper as Hibou-L: a
CPU-feasible Apache-2.0 encoder one size above ViT-S. CHIEF: AGPL-3.0 per
LazySlide's list, repo not opened. Datasets: BRACS (547 slides, 4,539 ROIs, 189 patients; **no terms
stated** on its site); BCNB (1,058 core-biopsy slides with ER/PR/HER2/Ki67/ALN labels; no license on
its page, a library listing says non-commercial; [10.3389/fonc.2021.759007](https://doi.org/10.3389/fonc.2021.759007));
ACROBAT (750/100/300 cases, H&E with ER/PR/HER2/Ki67 IHC; no license or DOI on its page); NuCLS
(>220,000 nuclei on TCGA breast slides; sources disagree: CC0 on a mirror, CC BY 4.0 on the paper
record; [10.1093/gigascience/giac037](https://doi.org/10.1093/gigascience/giac037)); Camelyon16/17
(sentinel-node metastases; "CC0", open S3 bucket, [AWS Open Data](https://registry.opendata.aws/camelyon/)).

**What the colon analyzer's parts become for breast**

| Colon analyzer part | Breast counterpart | Gap |
|---|---|---|
| CONCH + MUSK embeddings | Path Foundation / GigaPath-Flash / Hibou-L (open) or CONCH (local, NC-ND) | No open-license equivalent of MUSK found; CONCH access needs an institutional email |
| NCT-CRC-HE-100K / STARC-9 tissue heads | Heads trained on BCSS (CC0) | BCSS is 151 regions, so coarse classes only; no 100k-tile breast set found |
| Tile quality check | HistoQC (BSD), GrandQC (NC) | none |
| Tumor front, growth pattern, mucin | none found for breast | Needs the team's own definitions; mark "planned" |
| Source-tagged cutoffs | Same practice | Every cutoff starts as "placeholder" until calibrated |

**Notes for the plug-in.** (1) Findings from heads on embeddings are *model inference*, never
observed. (2) Four encoders were pretrained on TCGA slides (Path Foundation, Midnight-12k, Phikon-v2,
OpenPath), so held-out TCGA-BRCA slides are not independent of pretraining; labels were not used,
but say so on the model card. (3) The Virchow2 and CONCH v1.5 gate texts define derivatives to
include "models trained on outputs" and "datasets created from" the model, and CC BY-NC-ND bars
sharing adapted material: treat heads and embeddings made with those models as derivatives and do
not publish them. (4) Two encoders that disagree on a tile is a
natural "look here" reason (WORKSPACE.md item 6).

## 3. Radiology: breast MRI, mammography, CT/PET

| Candidate | What it does | License (as stated; where) | Access | Compute; this PC? | Published validation | Plugs into the workbench as |
|---|---|---|---|---|---|---|
| **MRI data.** [TCGA-BRCA radiology (TCIA)](https://www.cancerimagingarchive.net/collection/tcga-brca/) | 139 subjects, MR + mammography, 88 GB; matched to TCGA by patient ID; baseline studies are pre-surgical | CC BY 3.0 (collection page, DataCite) | open (NBIA Data Retriever) | DICOM handling only | DOI [10.7937/K9/TCIA.2016.AB2NAZRP](https://doi.org/10.7937/K9/TCIA.2016.AB2NAZRP) | The only imaging that joins our TCGA-BRCA omics: one demo patient with MRI + omics |
| **MRI data + model.** [MAMA-MIA](https://doi.org/10.7303/syn60868042) | 1,506 pre-treatment DCE-MRI cases from I-SPY1, I-SPY2, NACT-Pilot, Duke with expert primary-tumor segmentations; 21 clinical variables (pCR, subtype, survival). Baseline nnU-Net weights included | Paper: "available online in the MAMA-MIA Synapse repository under CC-BY-NC license at the level of the most restrictive primary dataset (Duke-Breast-Cancer-MRI)" **[NC]**; the article itself is CC BY-NC-ND 4.0 | Synapse repository (login and terms not read) | nnU-Net 3D on CPU: minutes per case (assumption). GPU preferred | Sci Data 2025, [10.1038/s41597-025-04707-4](https://doi.org/10.1038/s41597-025-04707-4): 5-fold validation Dice 0.762 ± 0.211 | Primary-tumor contour and volume for 2–3 cases (model inference) |
| **MRI data.** [Duke-Breast-Cancer-MRI (TCIA)](https://www.cancerimagingarchive.net/collection/duke-breast-cancer-mri/) | 922 subjects, 5,161 series, 369 GB; clinical, 3D segmentations, 529 radiomic features, lesion boxes | CC BY-NC 4.0 **[NC]** (page, DataCite) | open | Large | Saha 2018 Br J Cancer [10.1038/s41416-018-0185-8](https://doi.org/10.1038/s41416-018-0185-8); TCIA [10.7937/TCIA.e3sv-re93](https://doi.org/10.7937/TCIA.e3sv-re93) | Local-only; already inside MAMA-MIA |
| **MRI data.** [I-SPY2 (TCIA)](https://www.cancerimagingarchive.net/collection/ispy2/) | 719 subjects (985 with ACRIN 6698), DCE-MRI with FTV masks; 1.75 TB image download | CC BY 4.0 (page, DataCite) | open | Very large | npj Breast Cancer 2020, [10.1038/s41523-020-00203-7](https://doi.org/10.1038/s41523-020-00203-7); TCIA [10.7937/TCIA.D8Z0-9T85](https://doi.org/10.7937/TCIA.D8Z0-9T85) | The only large breast MRI set with response data under CC BY; too big for the freeze |
| **MRI model.** [Pillar0-BreastMRI](https://huggingface.co/YalaLab/Pillar0-BreastMRI) | Volumetric MRI encoder (94.1M params), exam embeddings; evaluated mostly by linear probing. Sister models for chest and abdomen CT | `ecl-2.0` (card header, API); license text not on the card (ECL-2.0 is an Apache-derived license, my reading) | **[GATED]**, contact-info click-through (API `auto`) | 3D encoder; CPU speed unknown | arXiv:2511.17803 (preprint): trained on 11,543 breast MRIs among others; authors' internal mean AUROC 82.9 on breast-MRI findings | Exam-level embedding or finding scores (model inference); unproven outside the authors' centre |
| **MRI/CT tools.** [nnU-Net](https://github.com/MIC-DKFZ/nnUNet), [MedSAM](https://github.com/bowang-lab/MedSAM) / [MedSAM2](https://huggingface.co/wanglab/MedSAM2) | nnU-Net: self-configuring segmentation framework. MedSAM: promptable segmentation | nnU-Net: Apache-2.0 (repo). MedSAM code: Apache-2.0; checkpoint license not stated in the repo; the MedSAM2 weights on HF are `cc-by-sa-4.0` (share-alike) | open | Neither repo page states CPU support; MedSAM's page describes training on A100 nodes | nnU-Net Nat Methods 2021 [10.1038/s41592-020-01008-z](https://doi.org/10.1038/s41592-020-01008-z) (23 public datasets); MedSAM Nat Commun 2024 [10.1038/s41467-024-44824-z](https://doi.org/10.1038/s41467-024-44824-z) | Contour tool and training framework |
| **Mammo data.** [CMMD (TCIA)](https://www.cancerimagingarchive.net/collection/cmmd/) | 1,775 patients, 5,202 images, 23 GB; benign/malignant biopsy labels; molecular subtype for 749 | CC BY 4.0 (page, DataCite) | open | Small | TCIA [10.7937/tcia.eqde-4b16](https://doi.org/10.7937/tcia.eqde-4b16) | Demo images and a subtype check; Chinese cohort, so domain shift |
| **Mammo data.** [CBIS-DDSM (TCIA)](https://www.cancerimagingarchive.net/collection/cbis-ddsm/) | ~1,566 participants, 10,239 images, 164 GB; film-digitised; ROI masks, pathology for training cases | CC BY 3.0 (page, DataCite) | open | Moderate | Sci Data 2017, [10.1038/sdata.2017.177](https://doi.org/10.1038/sdata.2017.177) | Demo images with lesion contours |
| **Mammo data.** [VinDr-Mammo (PhysioNet)](https://physionet.org/content/vindr-mammo/1.0.0/) | 5,000 four-view exams with BI-RADS, density, lesion boxes | "PhysioNet Restricted Health Data License 1.5.0"; "Only registered users who sign the specified data use agreement can access the files" | **[CONTROLLED]** account + DUA | n/a | Sci Data 2023, [10.1038/s41597-023-02100-7](https://doi.org/10.1038/s41597-023-02100-7); data [10.13026/br2v-7517](https://doi.org/10.13026/br2v-7517) | Skip for the freeze; cannot be shown in a public demo |
| **Mammo model.** [mammoscreen](https://huggingface.co/ianpan/mammoscreen) | Ensemble of three EfficientNetV2-S nets (61M) for cancer score and breast density from CC + MLO views; needs a separate crop model | `apache-2.0` (card, API) | open, ungated | ~61M params at 2048×1024 and similar; CPU feasible for a few images (estimate) | No paper. Card: AUROC 0.945 on a 10% held-out split of the RSNA 2023 challenge data (three repeats); trained on CBIS-DDSM then RSNA | Cancer-likelihood + density per exam (model inference). Terms of the RSNA training data were not retrieved |
| **Mammo model.** [Mirai](https://github.com/reginabarzilaygroup/Mirai) | Five-year breast cancer risk from four standard views | "The trained model and all code are released under the MIT license" (README) | open (weights via the Docker image / snapshot files) | CPU inference not ruled out; needs all four "For Presentation" views from Hologic-like devices | Sci Transl Med 2021, [10.1126/scitranslmed.aba4373](https://doi.org/10.1126/scitranslmed.aba4373): C-index 0.76 (MGH), 0.81 (Karolinska), 0.79 (Chang Gung) | Risk score per patient (model inference) if four-view exams are available; none of the open sets guarantees that |
| **Mammo models.** [Mammo-FM](https://huggingface.co/batmanLab/Mammo-FM), [Mammo-CLIP](https://github.com/batmanlab/Mammo-CLIP) | Mammography foundation model (140,677 patients, 821,326 mammograms, four US sites); CLIP-style model | Mammo-FM: "Custom Academic License for Model Weights" (based on CC BY-NC 4.0): "solely for non-commercial academic research"; "Redistribution of the Model weights ... is not permitted"; serving "an API, SaaS platform, web service" not permitted; "Any use by industry, including internal research" needs permission **[NC]**. Mammo-CLIP: CC BY-NC-SA 4.0 (README) **[NC]** | open, ungated | CUDA 11.8 stack stated for Mammo-CLIP | Mammo-FM arXiv:2512.00198 (preprint); Mammo-CLIP MICCAI 2024 pp. 632–642 (no DOI on page) | Local research only; not in a hosted demo |
| **CT/PET.** [TotalSegmentator](https://github.com/wasserth/TotalSegmentator) | 117 CT and 50 MRI structures (organs, bones, vessels) | Code Apache-2.0. Weights: "Openly available for any usage (Apache-2.0 license)" for `total`, `total_mr`, `body` and most subtasks; some subtasks (e.g. heart chambers, tissue types) need a license, free for non-commercial use | open | **Yes**: CPU supported; README cites ~70 s on CPU for a large CT with fastest settings | Radiology: AI 2023, [10.1148/ryai.230024](https://doi.org/10.1148/ryai.230024); trained on 1,228 CT / 616 MR subjects | Organ map to place a lesion (liver, lung, bone) in staging CT; not a lesion finder |
| **CT lesions.** [ULS23 baseline](https://github.com/DIAGNijmegen/uls23) | nnU-Net-based 3D universal lesion segmentation in CT (bone, lung, liver, kidney, mediastinal, pancreas...) | Weights on Zenodo: "Creative Commons Attribution 4.0 International" ([record 10665106](https://zenodo.org/records/10665106)); the GitHub repo states no license | open | 8.4 GB archive; GPU preferred | Med Image Anal 2025, [10.1016/j.media.2025.103525](https://doi.org/10.1016/j.media.2025.103525): Dice 0.703 ± 0.240 on the challenge test set | Lesion contour for staging CT (model inference); not breast-specific |
| **PET data.** [FDG-PET-CT-Lesions / autoPET (TCIA)](https://www.cancerimagingarchive.net/collection/fdg-pet-ct-lesions/) and [ACRIN-FLT-Breast](https://www.cancerimagingarchive.net/collection/acrin-flt-breast/) | autoPET: 900 patients with lesion masks; **lymphoma, melanoma, lung only, no breast**. ACRIN-FLT-Breast: 83 breast subjects, FDG/FLT PET/CT | autoPET: CC BY 4.0 for defaced images; non-defaced under "NIH Controlled Data Access Policy". ACRIN-FLT-Breast: CC BY 3.0 | open (defaced) | 838 GB / 74 GB | autoPET Sci Data 2022, [10.1038/s41597-022-01718-3](https://doi.org/10.1038/s41597-022-01718-3); ACRIN-FLT-Breast [10.7937/K9/TCIA.2017.ol20zmxg](https://doi.org/10.7937/K9/TCIA.2017.ol20zmxg) | No breast PET model found; "planned" |
| **GPU models.** [NV-Segment-CT / -CTMR](https://huggingface.co/nvidia/NV-Segment-CTMR), [NV-Reason-CT](https://huggingface.co/nvidia/NV-Reason-CT) | VISTA3D-based segmentation: NV-Segment-CT (label indices 0–132, incl. tumor and lesion classes) and NV-Segment-CTMR (CT + MR, "up to 345+" classes); NV-Reason-CT is a 4.7B chest/abdomen CT vision-language model | NV-Segment-CT weights: NVIDIA Open Model License. NV-Segment-CTMR weights: "NVIDIA OneWay Non-Commercial License for academic research purposes" **[NC]**; code Apache-2.0. NV-Reason-CT: "OpenMDW-1.1" (text not retrieved), "research and educational purposes only" | open, ungated | NVIDIA GPU only (Ampere/Hopper/Lovelace); **No** here | VISTA3D arXiv:2406.05285; NV-Reason-CT arXiv:2609.27511 (preprints): CT-RATE macro-AUROC 0.871 (authors) | Run on rented GPU if the NVIDIA stack is wanted for CT; not for the freeze |

**Also checked (radiology).** Duke Breast Cancer Screening DBT: CC BY-NC 4.0 **[NC]**, 5,060
subjects, 1.63 TB, [10.7937/E4WT-CD02](https://doi.org/10.7937/E4WT-CD02). EMBED (Emory): "Custom
License", AWS resource "S3 Bucket [Controlled Access]", request via data.hitilab.com; the open release is 20% of
the 2D data, [10.1148/ryai.220047](https://doi.org/10.1148/ryai.220047) **[CONTROLLED]**. BreastDCEDL
(2,070 patients from I-SPY1/2 and Duke with pCR labels, arXiv:2506.12190): license and hosting not
stated on its page. BreastMR-FM: "code soon", no weights. INbreast (115 cases, [10.1016/j.acra.2011.09.014](https://doi.org/10.1016/j.acra.2011.09.014)):
access terms not found. RSNA 2023 mammography challenge data on Kaggle: rules page not retrievable.
MedGemma 1.5 4B (section 8) lists 3D CT/MRI input but scores 61.1 (CT) and 64.7 (MRI) macro accuracy on
its own datasets, so it is not a radiology candidate.

**Notes for the plug-in.** Findings are per lesion, slice or exam, never one score for the whole
scan (WORKSPACE.md). Comparison across scans needs protocol, scanner and alignment checks. None of
these models reads mutations from an image.

## 4. Blood and lab panels, including tumor markers

No foundation model fits; this workbench is rules, reference data and a trend engine. Reference
intervals must come from the lab's own assay (package insert or the lab); no open library of
method-specific intervals was found.

| Candidate | What it does | License (as stated; where) | Access | Compute; this PC? | Published validation | Plugs into the workbench as |
|---|---|---|---|---|---|---|
| **Rule source.** [EGTM breast recommendations](https://www.egtm.eu/about-tumor-markers/breast-cancer) | Panel of one MUC-1 marker (e.g. CA 15-3) + CEA. Follow-up of asymptomatic women: "every 2–4 months (according to the risk of recurrence) during the initial 5 years after diagnosis, then every 6 months during the next 3 years and at yearly intervals thereafter". Therapy monitoring: before every chemotherapy course, and at least every 3 months on hormone therapy. A significant change is "at least a 25% increase over the previous value – with the second value above the reference interval", confirmed with a second specimen within a month; confirmed falls of "more than 50%" are "consistent with tumor response". Changing the method during serial monitoring "must be undertaken with considerable care". Not for screening | Web page text by the EGTM panel (Molina, Barak, Duffy et al.); no license given. Cite, do not copy | open | none | The page's first reference is Molina 2005 (Tumour Biol). The updated guideline is Duffy et al., Eur J Cancer 2017, [10.1016/j.ejca.2017.01.017](https://doi.org/10.1016/j.ejca.2017.01.017); I did not read it, so I cannot say the page's thresholds appear in it | Trend flags with threshold source "literature (EGTM web recommendations)"; the method-change warning maps to the unit and method checks |
| **Rule source.** ASCO 2007 tumor marker update (PMID 17954709) | Markers may be adjuncts; data insufficient to use CA 15-3, CA 27.29 or CEA alone to monitor response (wording from a search-indexed summary; the paper was not opened) | Paper copyright. Cite | open abstract | none | J Clin Oncol 2007, [10.1200/JCO.2007.14.2364](https://doi.org/10.1200/JCO.2007.14.2364). **Old: check for a newer ASCO guideline before showing it as current** | The "out of range is not evidence of progression by itself" caveat in the workbench |
| **Reference data.** EuBIVAS tumor-marker biological variation | Within- and between-subject variation of CA 15-3, CEA, CA 125, CA 19-9, CYFRA 21-1, AFP, HE4 from weekly samples over 10 weeks in 91 healthy adults; supports a reference change value (standard formula RCV = √2 · z · √(CVA² + CVI²)) | Subscription article, not open access (Europe PMC). The numeric CVI values were not read | paywalled | none | Clin Chem Lab Med 2022, [10.1515/cclm-2021-0283](https://doi.org/10.1515/cclm-2021-0283). Healthy volunteers, not cancer patients | Patient-baseline change threshold, tagged "literature, healthy volunteers, placeholder" until the assay's analytical CV is known |
| **Data.** MSK-CHORD tumor markers (CA 15-3, CEA timelines) | Real longitudinal markers | CC BY-NC-ND 4.0 per `registry.md` (not re-checked) **[NC][ND][LOCAL]** | open download | n/a | Nature 2024, [10.1038/s41586-024-08167-5](https://doi.org/10.1038/s41586-024-08167-5) | Aggregate trend statistics only; never shown per patient |
| **Generator.** [Synthea](https://github.com/synthetichealth/synthea) | Synthetic patients with conditions, labs, medications; has a `breast_cancer.json` module; FHIR/CSV output | Apache-2.0 (README) | open | CPU | Not a clinical dataset | Background labs (CBC, chemistry) for the synthetic timeline patient, labeled synthetic |
| **Data.** [MIMIC-IV](https://physionet.org/content/mimiciv/3.1/) | ICU/hospital EHR incl. `labevents` (364,627 patients); not cancer-specific | "PhysioNet Credentialed Health Data License 1.5.0"; credentialing, CITI training, signed DUA | **[CONTROLLED]** | n/a | Sci Data 2023, [10.1038/s41597-022-01899-x](https://doi.org/10.1038/s41597-022-01899-x); data [10.13026/kpb9-mt58](https://doi.org/10.13026/kpb9-mt58) | Not recommended: cannot be shown, not cancer-specific |
| **Model.** [CLMBR-T-base](https://huggingface.co/StanfordShahLab/clmbr-t-base) | EHR foundation model | `cc-by-nc-4.0` **[NC]** (API) | **[GATED]**, manual review | n/a | Not read | Not recommended |

LOINC/UCUM would normalise units and method codes; the LOINC license page returned HTTP 403 and
was not read, so check it before adding LOINC to the registry.

## 5. ctDNA (liquid biopsy)

| Candidate | What it does | License (as stated; where) | Access | Compute; this PC? | Published validation | Plugs into the workbench as |
|---|---|---|---|---|---|---|
| **Rule source.** PADA-1 and SERENA-6 | Randomised trials that switched therapy on a rising or emerging ESR1 mutation in blood without progression. PADA-1: 1,017 monitored, 279 with rising ESR1, 172 randomised; PFS 11.9 vs 5.7 months. SERENA-6: 3,256 tested, 315 randomised; PFS 16.0 vs 9.2 months; ctDNA every 2–3 months | Paper copyright. No open patient-level data found | open abstracts | none | PADA-1 Lancet Oncol 2022, [10.1016/S1470-2045(22)00555-1](https://doi.org/10.1016/S1470-2045(22)00555-1). SERENA-6 NEJM 2025, [10.1056/NEJMoa2502929](https://doi.org/10.1056/NEJMoa2502929) | Defines the "new or rising ESR1" flag; the switch evidence is shown for clinician review, never as a recommendation |
| **Rule source.** Razavi et al. 2019 | In 124 patients with metastatic cancer, "the vast majority of cfDNA mutations (81.6% in controls and 53.2% in patients with cancer) had features consistent with clonal hematopoiesis" | Paper copyright (PMC full text exists) | open | none | Nat Med 2019, [10.1038/s41591-019-0652-7](https://doi.org/10.1038/s41591-019-0652-7) | Caveat on every ctDNA variant: needs matched white-cell sequencing before it counts as tumor-derived |
| **Method.** MSK-ACCESS paired-normal calling | Paired normal sequencing to remove blood-derived variants | Paper copyright | open abstract | none | Nat Commun 2021, [10.1038/s41467-021-24109-5](https://doi.org/10.1038/s41467-021-24109-5) | Design reference for the clonal-hematopoiesis flag |
| **Tool.** [ichorCNA](https://github.com/broadinstitute/ichorCNA) | Tumor fraction and copy-number from ~0.1× low-pass whole-genome cfDNA (hidden Markov model) | GPL-3.0 (README: "Copyright (C) 2017 Broad Institute") | open | R; needs aligned reads, which we do not have | Nat Commun 2017, [10.1038/s41467-017-00965-y](https://doi.org/10.1038/s41467-017-00965-y) | Only if raw low-pass reads are ever imported |
| **Tool.** [FinaleToolkit](https://github.com/epifluidlab/FinaleToolkit) and [FinaleDB](http://finaledb.research.cchmc.org/) | Fragmentation features (length, end motifs, windowed protection, DELFI-style) from BAM/CRAM/fragment files; FinaleDB holds 2,579 paired-end cfDNA WGS datasets across 23 conditions, collected from GEO, EGA and dbGaP | Toolkit: "This project falls under an MIT license". FinaleDB article CC BY-NC 4.0; **database terms not stated**; some source data are controlled | toolkit open; database not read (TLS error on fetch) | CPU | Toolkit Bioinformatics Advances, [10.1093/bioadv/vbaf236](https://doi.org/10.1093/bioadv/vbaf236); FinaleDB Bioinformatics 2020, [10.1093/bioinformatics/btaa999](https://doi.org/10.1093/bioinformatics/btaa999) | Research option for fragmentomics; no breast-cancer ctDNA workflow in scope |
| **Dataset search.** Public serial breast ctDNA with raw reads | A web search for serial breast ctDNA datasets on GEO, EGA or Zenodo returned only papers (IRIS, dPCR-SEQ and others); GEO and EGA were not searched directly | n/a | none found | n/a | n/a | Nothing to import |
| **Synthetic generator (to write).** | Labeled synthetic variant-allele-fraction series for the demo patient: ESR1 emerging under an aromatase inhibitor, a clonal-hematopoiesis variant, a dropout | MIT (this repo) | n/a | CPU | None. Unit tests only | The ctDNA workbench; every point labeled synthetic |

Limits to show (WORKSPACE.md): low tumor shedding gives false negatives; blood-cell variants can
look like tumor variants.

## 6. Tumor DNA sequencing

| Candidate | What it does | License (as stated; where) | Access | Compute; this PC? | Published validation | Plugs into the workbench as |
|---|---|---|---|---|---|---|
| **Data.** TCGA-BRCA masked somatic mutations (GDC) | 992 open MAF files, "Aliquot Ensemble Somatic Variant Merging and Masking" (release 46.0) | No license text; GDC open access "no authentication or authorization is necessary". Already in `registry.md` | open | CPU | TCGA Network, Nature 2012, [10.1038/nature11412](https://doi.org/10.1038/nature11412) | Observed variants (already used) |
| **Evidence.** [CIViC](https://docs.civicdb.org/en/latest/about/faq.html) | Community-curated clinical evidence for variants | Content "released under the Creative Commons Public Domain Dedication (CC0 1.0 Universal)"; code MIT | open (API, nightly releases) | CPU | Nat Genet 2017, [10.1038/ng.3774](https://doi.org/10.1038/ng.3774) | Evidence links "for clinician review" (already used); fix compound-profile matching |
| **Evidence.** [OncoKB](https://www.oncokb.org/terms) (data v7.6, 30 Sep 2026) | Curated actionability levels | Free only for "use for research in an academic setting"; "outside of scientific publication, you may not otherwise redistribute or share the Content with any third party"; a license is needed for "research use in a commercial setting", "use for patient services" and "generation of reports in a hospital or other patient care setting" **[RESTRICTED]** | open with registration/token | n/a | Chakravarty 2017 [10.1200/PO.17.00011](https://doi.org/10.1200/PO.17.00011); Suehnholz 2024 [10.1158/2159-8290.CD-23-0467](https://doi.org/10.1158/2159-8290.CD-23-0467) | **Do not use**: a public demo or a Token Factory call would be redistribution or sharing with a third party |
| **Evidence.** [COSMIC](http://www.cosmickb.org/licensing/) | Somatic mutation catalogue, cancer gene census | "COSMIC data is free for the academic community" (not-for-profit R&D); commercial product, "patient service or in clinical reporting" and for-profit R&D need a commercial licence | registration with organisational email | n/a | n/a | Not needed; skip |
| **Predictor.** [AlphaMissense](https://github.com/google-deepmind/alphamissense) | Precomputed pathogenicity scores for all human missense variants | Predictions "licensed under the Creative Commons Attribution 4.0 International License (CC BY 4.0)"; code Apache-2.0; weights not released. "Has not been validated for, and is not approved for, any clinical use" | open (Google Cloud Storage) | Large table; lookup only | Science 2023, [10.1126/science.adg7492](https://doi.org/10.1126/science.adg7492) | "Predicted effect" column kept apart from detection and interpretation (model inference) |
| **Annotation.** [Ensembl VEP](https://github.com/Ensembl/ensembl-vep) | Consequence, transcript and protein-change annotation | Apache-2.0 (README) | open | CPU | Genome Biol 2016, [10.1186/s13059-016-0974-4](https://doi.org/10.1186/s13059-016-0974-4) | Normalises variants to transcript + protein change |
| **Annotation.** [ClinVar](https://www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/) | Variant classifications with submitter evidence | No license statement; "we ask that you provide attribution to ClinVar as a data source in publications and websites" | open | CPU | Nucleic Acids Res 2018, [10.1093/nar/gkx1153](https://doi.org/10.1093/nar/gkx1153) | Germline/somatic classification link |
| **Data.** [AACR GENIE](https://aacrprojectgenie.org/data/) (release 20.0-public, July 2026) incl. BPC | Multi-centre tumor sequencing; BPC adds real-world clinical data | "Users will need to create an account for either site and agree to the terms of access"; license text not on the landing page | account + terms (Synapse or cBioPortal) | Large | Cancer Discov 2017, [10.1158/2159-8290.CD-17-0151](https://doi.org/10.1158/2159-8290.CD-17-0151) | External cohort for mutation frequencies; breast counts not read |
| **Data.** METABRIC | 997 discovery + 995 validation breast tumours with copy number and expression; EGA study [EGAS00000000083](https://ega-archive.org/studies/EGAS00000000083); cBioPortal copy | cBioPortal [datahub](https://github.com/cBioPortal/datahub): "The data are available under the ODC Open Database License (ODbL)"; study-level terms for METABRIC not stated; EGA page does not state the access type | cBioPortal copy open; raw data via EGA | CPU | Nature 2012, [10.1038/nature10983](https://doi.org/10.1038/nature10983) | External validation of subtype and mutation frequencies |
| **Data.** MSK-CHORD | Real timelines with MSK-IMPACT sequencing | CC BY-NC-ND 4.0 per `registry.md` **[NC][ND][LOCAL]** | open download | n/a | Nature 2024, [10.1038/s41586-024-08167-5](https://doi.org/10.1038/s41586-024-08167-5) | Aggregate results only (project rule) |

No pretrained model is needed for detection: the test already returns calls. The work is
interpretation and keeping detection, interpretation and predicted effect apart. Evolutionary
hypotheses stay on the roadmap (needs repeated sequencing).

## 7. RNA, methylation and protein

| Candidate | What it does | License (as stated; where) | Access | Compute; this PC? | Published validation | Plugs into the workbench as |
|---|---|---|---|---|---|---|
| **Data.** TCGA-BRCA via GDC | RNA STAR counts (1,231 files), 450K/27K methylation (895 + 343 files), RPPA protein (919 files), all `open` (release 46.0) | No license text (see section 2). Already in `registry.md` | open | CPU | Nature 2012, [10.1038/nature11412](https://doi.org/10.1038/nature11412) | Existing risk-model inputs; heatmaps and ranked features |
| **Subtyping.** [genefu](https://bioconductor.org/packages/genefu) | R/Bioconductor: PAM50 and other published breast signatures, intrinsic-subtype calls | "Artistic-2.0" (Bioconductor 3.23, v2.44.0) | open | R; CPU, seconds | Bioinformatics 2015, [10.1093/bioinformatics/btv693](https://doi.org/10.1093/bioinformatics/btv693); PAM50 origin JCO 2009 [10.1200/JCO.2008.18.1370](https://doi.org/10.1200/JCO.2008.18.1370) | PAM50 subtype per patient (model inference); validate against TCGA's published calls |
| **Subtyping.** [BreastSubtypeR](https://bioconductor.org/packages/BreastSubtypeR) | Harmonises several nearest-centroid and single-sample intrinsic-subtype classifiers with a cohort-aware mode | "GPL-3" (Bioconductor 3.23, v1.4.1) | open | R; CPU | No paper DOI on the page | Cross-check of genefu; copyleft, so call it as a separate process |
| **Signatures.** [MSigDB Hallmark](https://www.gsea-msigdb.org/gsea/msigdb_license_terms.jsp) | 50 curated pathway gene sets for pathway scores | "subject to the terms and conditions of the Creative Commons Attribution 4.0 International License" (v6.0–v7.5.1 and v2022.1 onwards); KEGG and BioCarta sets need acknowledgment of the original copyright | open | CPU | Cell Syst 2015, [10.1016/j.cels.2015.12.004](https://doi.org/10.1016/j.cels.2015.12.004) | Pathway scores with the definition shown |
| **Data.** CPTAC-BRCA proteogenomics | Breast tumour proteomics and phosphoproteomics | Terms on the Proteomic Data Commons were not retrieved (JavaScript site) | access not checked (Proteomic Data Commons) | CPU | Krug et al., Cell 2020, [10.1016/j.cell.2020.10.036](https://doi.org/10.1016/j.cell.2020.10.036) | Protein check for the ~100 overlapping tumours; RNA is not protein |
| **Data.** SCAN-B [GSE96058](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE96058) | RNA-seq of 3,273 breast cancers (GEO "cohort 3273") with the paper's ER/PgR/HER2/Ki67/grade classifiers | No license shown on the GEO record; public repository | open | CPU | JCO Precis Oncol 2018 (PMID 32913985, DOI not retrieved) | External validation of RNA-derived receptor status |
| **Data.** I-SPY2 [GSE194040](https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE194040) | Pre-treatment expression for 987 patients across 10 neoadjuvant arms with HR, HER2, MammaPrint and pCR; companion GSE196093 has RPPA for 736 | No license shown on the GEO record; public repository | open | CPU | Cancer Cell 2022, [10.1016/j.ccell.2022.05.005](https://doi.org/10.1016/j.ccell.2022.05.005) | Response-linked expression for a later "treatment evidence" check |
| **Model.** [BulkFormer](https://huggingface.co/zhfanrui/BulkFormer-147M) | Bulk-transcriptome foundation model (37M–147M params), 20,010 genes from raw counts; sample embeddings | `mit` (card, API) | open, ungated | CPU-feasible for small inputs (estimate) | Cell Syst 2026, [10.1016/j.cels.2026.101657](https://doi.org/10.1016/j.cels.2026.101657). Card lists no training-data counts and no breast task | Sample embedding; experimental, no breast validation seen |
| **Model.** [CpGPT](https://huggingface.co/lucascamillomd/cpgpt-models) | DNA-methylation foundation model (2.5M and 101M params) | `mit` (card, API) | open, ungated | CPU for the small model (estimate) | bioRxiv [10.1101/2024.10.24.619766](https://doi.org/10.1101/2024.10.24.619766) (preprint); card lists no tasks or data | Experimental; no breast validation seen |

**Also checked.** Geneformer (Apache-2.0) and scGPT (MIT) are single-cell models, not suited to bulk
TCGA RNA. Methylation-based breast classifiers and CIBERSORTx-type deconvolution were not verified.
Limits to show: normalization stated; "RNA is not protein, and neither is pathway activity".

## 8. Clinical text

| Candidate | What it does | License (as stated; where) | Access | Compute; this PC? | Published validation | Plugs into the workbench as |
|---|---|---|---|---|---|---|
| **Data.** [TCGA-Reports](https://data.mendeley.com/datasets/hyg5xkznpx/1) | 9,523 OCR'd, cleaned TCGA pathology reports across 32 cancer types | CC BY 4.0 (Mendeley record, DataCite) | open | small | Patterns 2024, [10.1016/j.patter.2024.100933](https://doi.org/10.1016/j.patter.2024.100933); data [10.17632/hyg5xkznpx.1](https://doi.org/10.17632/hyg5xkznpx.1) | Test documents; check extraction against TCGA's clinical receptor and stage fields |
| **Model.** [OpenMed-NER-OncologyDetect](https://huggingface.co/OpenMed/OpenMed-NER-OncologyDetect-BigMed-278M) | Entity tagger (cancer, organ, tissue, gene, ...) on xlm-roberta-base, trained on BioNLP 2013 CG; 278M params | `apache-2.0` (card, API) | open | **Yes** (CPU) | arXiv:2508.01630 (preprint); card F1 0.79 on BIONLP2013_CG. Tags entities, does not read diagnoses | Source-sentence highlighting |
| **Model.** [Clinical ModernBERT](https://huggingface.co/Simonlee711/Clinical_ModernBERT) | 8,192-token encoder (0.1B), pretrained on PubMed, MIMIC-IV notes and code descriptions | `mit` (card, API) | open | **Yes** (CPU) | arXiv:2504.03964 (preprint); card reports masked-token accuracy only | Base for section/sentence classifiers if we label data |
| **Model.** [Bio_ClinicalBERT](https://huggingface.co/emilyalsentzer/Bio_ClinicalBERT), [GatorTron-base](https://huggingface.co/UFNLP/gatortron-base) | Clinical encoders (110M; 345M with 512-token input) from MIMIC-III and University of Florida notes | Bio_ClinicalBERT `mit`; GatorTron-base `apache-2.0` (cards, API) | open | **Yes** (CPU) | ACL 2019 [10.18653/v1/W19-1909](https://doi.org/10.18653/v1/W19-1909); npj Digit Med 2022 [10.1038/s41746-022-00742-2](https://doi.org/10.1038/s41746-022-00742-2) | Alternatives to the above; older |
| **Model.** [MedGemma 1.5 4B](https://huggingface.co/google/medgemma-1.5-4b-it) | Multimodal 4B model (text, 2D images, CT/MRI volumes, pathology patches, lab-report extraction) | `health-ai-developer-foundations` ([terms](https://developers.google.com/health-ai-developer-foundations/terms); see Path Foundation) | **[GATED]**, click-through (API `auto`) | ~8 GB in bf16; quantised builds linked on the card. CPU slow but feasible for a few reports | MedGemma 1.5 Technical Report, arXiv:2604.05081 (preprint, tag on the card). Card: lab-report extraction macro-F1 91.0 and 71.0 on two EHR datasets, 85.0 on lab PNGs; outputs "preliminary and require independent verification" | Local schema extraction (receptors, stage, drugs, dates) with quoted source sentences |
| **Model.** [gpt-oss-20b](https://huggingface.co/openai/gpt-oss-20b) | 21B-parameter (3.6B active) reasoning model | Apache-2.0 (card) | open | "run within 16GB of memory" (MXFP4); CPU slow | arXiv:2508.10925 (model card); no medical results on the card | Local extraction alternative; slow here |
| **Model.** [Nemotron-3-Nano-4B](https://huggingface.co/nvidia/NVIDIA-Nemotron-3-Nano-4B-BF16) | 3.97B text model, 262K context, tool calling | NVIDIA Nemotron Open Model License; card: "ready for commercial use" | open, ungated | 4B; hardware list is NVIDIA GPUs, CPU not stated | arXiv:2512.20848 (Nemotron 3 Nano report, cited on the card). Not tested on clinical text | NVIDIA-stack option for local extraction |

Published breast report extraction, for scale: Mistral Large pipeline, ER/PR/HER2 F1 above 95% at
document level and 87–90% at patient level (JCO Clin Cancer Inform 2026,
[10.1200/CCI-25-00133](https://doi.org/10.1200/CCI-25-00133)); classical classifiers on bilingual
registry reports, F1 0.89–0.92 (Front Digit Health 2021,
[10.3389/fdgth.2021.692077](https://doi.org/10.3389/fdgth.2021.692077)). The local small models above
are untested on this task. **Project rule:** only derived numbers go to Token Factory, so report text
is processed locally. Limits to show: documented kept apart from inferred; conflicting reports kept.

## 9. Ranked shortlist for the Oct 28 freeze

Ranked by value for the demo times certainty it can be finished with open licenses, divided by
effort. Effort is my estimate in person-days (two people, nine days to the freeze). Whether any of it
ships is your decision.

| Rank | Slice | Built from (license) | Why it fits | Effort | Main risk | Needs from you |
|---|---|---|---|---|---|---|
| 1 | **Tumor-marker and lab trends** | EGTM and ASCO rules (cited), EuBIVAS variation if readable, the synthetic timeline patient | No model, no compute, no access; implements "thresholds tagged by source" and "out of range is not progression" | 1.5–2 | EuBIVAS values are healthy-volunteer and paywalled; tag "placeholder". EGTM alone is enough | none |
| 2 | **Pathology tile workbench on 2–3 TCGA-BRCA slides** | GDC slides (open), Path Foundation or GigaPath-Flash (local encoder), optional Hibou-L (precomputed second opinion), BCSS tissue heads (CC0), HistoQC (BSD), LazySlide (MIT) | The depth-standard workbench with a matching open dataset; two encoders disagreeing feeds the "look here" queue | 5–6 | BCSS is 151 regions (coarse classes only); TCGA-pretrained encoders overlap the test slides; CPU time; tile-to-mask alignment; keep demo patients out of head training | HF click-throughs (section 10, group A) |
| 3 | **Genomics uplift** | TCGA MAF (open), CIViC (CC0), AlphaMissense (CC BY 4.0), VEP (Apache-2.0), ClinVar links | Extends what exists; fixes compound-profile matching; keeps detection, interpretation and predicted effect apart | 1.5–2 | Large AlphaMissense table; transcript mapping; "not approved for any clinical use" | none (OncoKB excluded) |
| 4 | **ctDNA monitor on a synthetic series** | PADA-1/SERENA-6 rules, Razavi clonal-hematopoiesis caveat, a generator we write | Nothing open exists; this is the ESR1 story in VISION part three | 1–1.5 | All synthetic: label every point; no validation beyond unit tests | none |
| 5 | **RNA subtype and pathway scores** | TCGA RNA (open), genefu (Artistic-2.0), MSigDB Hallmark (CC BY 4.0) | Measurable: agreement with TCGA's published subtype calls | 1.5–2 | R inside a Python app: precompute offline; normalization (counts vs TPM) | none |
| 6 | **Clinical documents with source sentences** | TCGA-Reports (CC BY 4.0), rules, a local small model (Nemotron-3-Nano-4B, MedGemma 1.5 4B or gpt-oss-20b), OpenMed NER for highlights | Measurable against TCGA's clinical fields | 2.5–3 | Local LLM speed on CPU; OCR noise; no raw text to Token Factory | HF click-through if MedGemma |
| 7 | **Mammography viewer with a screening score** | CMMD (CC BY 4.0) or CBIS-DDSM (CC BY 3.0) images, mammoscreen (Apache-2.0); Mirai (MIT) only with four-view exams | Second imaging type; cheap model | 3–4 | DICOM windowing, crop model, viewer; domain shift; RSNA training-data terms unread | none |
| 8 | **Breast MRI tumor contour** | TCGA-BRCA MRI (CC BY 3.0) + MAMA-MIA nnU-Net weights (CC-BY-NC) or nnU-Net trained by us (Apache-2.0) | Joins the TCGA cohort | 4–6 | NC weights; DCE series handling; CPU minutes per case; viewer | Synapse account |
| 9 | **CT/PET staging** | TotalSegmentator organ maps only | Nothing breast-specific exists | 0 | Do not claim lesion finding | none; mark "planned" |

**Cut line.** Ranks 1–4 (about 9–11 person-days) give four test types built only from open-license
or synthetic components; add 5 and 6 if time remains; show 7–9 as "planned" with their status labels. If you want one deep
workbench only, take rank 2. Every output keeps its label: observed (the recorded values and calls),
model inference (heads, scores, extraction) or hypothesis (nothing in this slice). A head or score
is "implemented" until it is tested on held-out patients (held-out BCSS regions for pathology;
published TCGA calls for PAM50; TCGA clinical fields for text). CPTAC-BRCA slides only show how a
pathology head behaves on a second cohort; for labeled accuracy on another institution's slides, the
TIGER regions from Radboud and Jules Bordet are the option found (NC, local only).

**If CONCH access arrives.** Add it as a local-only second encoder (best independent benchmark
rank). Do not publish its heads, embeddings or outputs, and keep it out of the hosted demo.

## 10. Access requests

Group A: needed for ranks 2 and 6 (ranks 1, 3, 4 and 5 need no request); each is approved on
accepting the terms (HF gating mode `auto`).

| # | Resource | Where | What you do | Notes |
|---|---|---|---|---|
| A1 | Path Foundation | [huggingface.co/google/path-foundation](https://huggingface.co/google/path-foundation) | Log in, accept the Health AI Developer Foundations terms | Terms pass restrictions on to anyone you share fine-tuned weights with |
| A2 | GigaPath-Flash | [huggingface.co/prov-gigapath/prov-gigapath-flash](https://huggingface.co/prov-gigapath/prov-gigapath-flash) | Log in, share contact information | Apache-2.0 |
| A3 | Hibou-L | [huggingface.co/histai/hibou-L](https://huggingface.co/histai/hibou-L) | Log in, share contact information | Apache-2.0; loads repo code |
| A4 | MedGemma 1.5 4B (only if rank 6 uses it) | [huggingface.co/google/medgemma-1.5-4b-it](https://huggingface.co/google/medgemma-1.5-4b-it) | Accept the same HAI-DEF terms | |

Group B: optional strong models. Use an institutional email as the HF primary email: the UNI2-h,
CONCH, TITAN and MUSK pages say personal addresses (@gmail/@hotmail/@qq) are denied or that an
official email must be the primary one, and Virchow and Virchow2 say the email must match an
institutional address.

| # | Resource | Where | What the form asks | Notes |
|---|---|---|---|---|
| B1 | CONCH (v1 and v1.5) | [huggingface.co/MahmoodLab/CONCH](https://huggingface.co/MahmoodLab/CONCH) | Form not read; the card requires registration, agreement to the terms and an institutional primary email | CC BY-NC-ND 4.0; best independent benchmark rank; the colon analyzer already uses it |
| B2 | UNI2-h | [huggingface.co/MahmoodLab/UNI2-h](https://huggingface.co/MahmoodLab/UNI2-h) | Its form (read via the API): full name, affiliation (no abbreviations), affiliation type, official institutional email matching the HF primary email, intended research use, and three agreements (all terms; non-commercial academic use only; no distribution) | ViT-H: needs a GPU. The other Mahmood Lab forms are probably similar |
| B3 | Virchow2 | [huggingface.co/paige-ai/Virchow2](https://huggingface.co/paige-ai/Virchow2) | Contact information, institutional email | Commercial entities rejected by default |
| B4 | Virchow v1, H-optimus-0, Prov-GigaPath | their HF pages (section 2) | Contact information (Virchow also an institutional email) | Apache-2.0; ViT-H/ViT-g, GPU needed |
| B5 | H-optimus-1, MUSK | [bioptimus/H-optimus-1](https://huggingface.co/bioptimus/H-optimus-1), [xiangjx/musk](https://huggingface.co/xiangjx/musk) | Manual review; institutional email | Slowest to answer; low priority |
| B6 | Pillar0-BreastMRI | [huggingface.co/YalaLab/Pillar0-BreastMRI](https://huggingface.co/YalaLab/Pillar0-BreastMRI) | Contact information | Only if rank 8 goes ahead |

Group C: datasets and accounts, only if the slice needs them.

| # | Resource | Where | What you do | Needed for |
|---|---|---|---|---|
| C1 | Synapse account | synapse.org | Register, accept the MAMA-MIA and GENIE terms | Rank 8; GENIE comparison |
| C2 | PhysioNet account + signed DUA | physionet.org/content/vindr-mammo | Register, sign the Restricted Health Data DUA | VinDr-Mammo (skip for the freeze) |
| C3 | BACH | iciar2018-challenge.grand-challenge.org/Dataset | Request form; notify organisers of any publication | Local benchmark only |
| C4 | EMBED | data.hitilab.com (Emory) | Controlled-access request | Not for the freeze |
| C5 | COSMIC, OncoKB | cosmickb.org, oncokb.org | Academic registration | **Not recommended** (restrictions in section 11) |

Open with no request: GDC (TCGA-BRCA slides, MAF, RNA, methylation, RPPA), TCIA public collections,
CIViC, AlphaMissense predictions, ClinVar, VEP, BCSS, TIGER (AWS), Camelyon (AWS), TCGA-Reports,
cBioPortal datahub, Mirai, mammoscreen, TotalSegmentator, nnU-Net.

**Also ask the organisers or a lawyer:** whether a Nebius × NVIDIA hackathon entry that can win a
prize counts as "non-commercial, academic research" for the CC BY-NC-ND models and NC datasets. I
could not settle that from the licenses.

## 11. License traps for a public repo and demo

1. **NC-ND models and derivatives.** UNI2-h, CONCH, Virchow2, H-optimus-1, MUSK and TITAN bar
   redistribution of the model. The Virchow2 and CONCH v1.5 gate texts also bar commercial use of
   "derivatives", defined to include models trained on the model's outputs and datasets created from
   it, and CC BY-NC-ND bars sharing adapted material. Treat heads and embeddings as derivatives: do
   not commit or release them; report aggregate results only.
2. **Hackathon prize versus "non-commercial".** Unresolved (section 10).
3. **OncoKB.** No redistribution or sharing "with any third party"; a public demo or a Token Factory
   call is both. No patient-care use.
4. **Prov-GigaPath.** `apache-2.0` tag, but the card calls "any deployed use case" out of scope.
5. **Mammo-FM.** No hosting through an API or web service; no use by industry, even internal.
6. **Datasets that are NC or ND.** Duke MRI and DBT, MAMA-MIA (and its weights), TIGER annotations,
   GrandQC weights, BACH, HEROHE, MSK-CHORD. Treat as local-only until the NC question (section 10)
   is settled; MSK-CHORD stays local regardless, and individual MSK-CHORD patients are never shown.
7. **Google HAI-DEF terms** (Path Foundation, MedGemma): pass the use restrictions on to anyone
   who receives fine-tuned weights, and note the "Clinical Use" definition covers research studies on
   patients; our data are public or synthetic.
8. **Share-alike and copyleft.** MedSAM2 weights `cc-by-sa-4.0`; ichorCNA and BreastSubtypeR GPL-3;
   CHIEF AGPL-3.0 (per LazySlide's list). Call GPL tools as separate processes from the MIT code.
9. **Pretraining overlap.** Encoders trained on TCGA (Path Foundation, Midnight-12k, Phikon-v2,
   OpenPath) have seen the held-out TCGA-BRCA slides without labels. Disclose it on the model card.
10. **`trust_remote_code`.** Hibou-L runs code from its repo; pin the revision.

## 12. Draft registry rows

For the recommended slice (ranks 1–6), in the format of `registry.md`. Not yet added there.

| Dataset | Used for | Access tier | License / terms | Code | What is published |
|---|---|---|---|---|---|
| **TCGA-BRCA diagnostic slides** (GDC, release 46.0) | pathology workbench demo slides | open | GDC open access; cite the TCGA Research Network | planned | tile features for 2–3 held-out patients in a release asset |
| **BCSS** (Amgad et al. 2019) | tissue-class heads | open | CC0 1.0; cite 10.1093/bioinformatics/btz083 | planned | head weights and aggregate metrics |
| **CPTAC-BRCA slides** (TCIA) | second-cohort behaviour check of the heads | open | CC BY 4.0; cite 10.7937/TCIA.CAEM-YS80 | planned | aggregate metrics |
| **TCGA-Reports** (Kefeli, Tatonetti 2024) | clinical-document workbench | open | CC BY 4.0; cite 10.17632/hyg5xkznpx.1 | planned | extraction metrics; quoted sentences for demo cases |
| **AlphaMissense predictions** | predicted-effect column | open | CC BY 4.0; not approved for clinical use | planned | scores for observed variants of demo cases |

| Model | Role | Access | License / terms | Inputs it receives |
|---|---|---|---|---|
| **Path Foundation** (Google) | local tile encoder | HF click-through | Health AI Developer Foundations terms | H&E tiles, locally |
| **GigaPath-Flash** | second tile encoder, slide embedding | HF click-through | Apache-2.0 | H&E tiles, locally |
| **Hibou-L** | optional precomputed second opinion | HF click-through | Apache-2.0 | H&E tiles, on a GPU or overnight |
| **HistoQC** | slide quality control | open | BSD-3-Clause-Clear | slides, locally |
| **genefu** (PAM50) | RNA subtype | open | Artistic-2.0 | TCGA RNA, locally |
| **Local text model** (one of Nemotron-3-Nano-4B, MedGemma 1.5 4B, gpt-oss-20b) | report extraction | per model | NVIDIA Nemotron Open Model License / HAI-DEF terms / Apache-2.0 | report text, locally only; never sent to Token Factory |

## 13. Not verified, or dropped

- **Pages that could not be read:** LOINC license (403), Proteomic Data Commons policy (JavaScript site),
  Kaggle RSNA mammography rules, EFLM Biological Variation Database, FinaleDB site (TLS error),
  numeric EuBIVAS values (paywalled), INbreast access terms.
- **No license on the page read:** BRACS, BCNB (a library listing says non-commercial), ACROBAT,
  BreastDCEDL, GEO records (SCAN-B, I-SPY2), the ULS23 GitHub repo (its Zenodo weights are CC BY 4.0).
- **Conflicting sources:** NuCLS license (CC0 on a mirror, CC BY 4.0 on the paper record).
- **Dropped for lack of weights or code:** BRAVE (breast pathology model), BreastMR-FM,
  Longitudinal 3D foundation modeling for I-SPY2 (arXiv 2608.09991, not opened).
- **Summaries:** card and page text was read through a fetch tool that summarises pages. License tags
  were cross-checked against the Hugging Face API; licenses for non-Hugging Face items rest on the
  page text and, for TCIA, PhysioNet, Zenodo and Mendeley, on DataCite records.
- **Not tested:** nothing was run, so every compute figure in section 1 is arithmetic. Hardware
  and framework support (PyTorch XPU on this iGPU, WSL2 pass-through) is from documentation only.

# Registry: datasets, models and services

Part five of `docs/VISION.md`: every resource MuFFLe++ uses, with its license, access tier, where
it is used and what leaves this machine. Rule (CLAUDE.md): check a new source's license and access
tier and add it here **before** using it.

## Datasets

| Dataset | Used for | Access tier | License / terms | Code | What is published |
|---|---|---|---|---|---|
| **TCGA-BRCA** multi-omic data (copy number ASCAT3, STAR TPM RNA, 450K methylation, RPPA protein, clinical, overall survival) via the UCSC Xena GDC hub | survival model, federated training across simulated hospitals (tissue source sites), case review | open (no dbGaP authorization) | NIH GDC open-access data; cite the TCGA Research Network | `scripts/prepare_tcga.py`, `muffle.data.tcga` | trained model weights and 40 held-out patients' processed features and their sequenced driver mutations in the release `demo-bundle-v2`; aggregate results; the 9 saved case notes (derived numbers, gene names) |
| **GDC masked somatic mutations** for TCGA-BRCA (`TCGA-BRCA.somaticmutation_wxs.tsv.gz`, Xena GDC hub) | observed driver mutations (ESR1, PIK3CA, TP53, ...) in the case note; not a model input | open (masked calls, germline filtered) | as TCGA above | `muffle.data.tcga.driver_mutations` | gene and protein-change names per demo case, in the release `demo-bundle-v2` |
| **GDC per-case masked somatic MAFs** (GDC API, "Aliquot Ensemble Somatic Variant Merging and Masking", the same calls) and **ASCAT3 gene-level copy number** (Xena GDC hub) | read counts (`t_alt_count`, `t_depth`) and the gene's copy number for the bundled cases' driver calls: clonal order in the Evolution view | open (GDC open access, no login) | as TCGA above | `scripts/make_evolution_vaf.py` | `app/evolution_vaf.json`: alt reads, depth and copy number per driver call of the 40 bundled cases, keyed by case index (no barcode) |
| **CIViC** nightly clinical evidence summaries | treatment evidence for observed variants, "for clinician review" | open download | **CC0**; each item keeps its citation and CIViC link | `muffle.report.civic` | evidence items (therapy, level, citation, link) in notes and `app/timeline_synthetic.json` |
| **MSK-CHORD** (`msk_chord_2024`, Jee et al., *Nature* 2024; cBioPortal datahub) breast cancer timelines | risk of progression or death in the next 12 months, re-predicted as the record grows; scores the demo's synthetic patient | open download | **CC BY-NC-ND 4.0**: non-commercial, no derivatives shared; attribution | `scripts/prepare_msk_chord.py`, `muffle.longitudinal`, `muffle.timeline` | **local only.** Aggregate metrics (`docs/longitudinal.md`) and the synthetic patient's scores. Never an individual patient, never the trained models, and nothing from it (data or model outputs) to Token Factory or Tavily |
| **TCGA-BRCA diagnostic slides** (`.svs`, GDC files endpoint, data type "Slide Image", experimental strategy "Diagnostic Slide") | the pathology slide workbench: tiles of BCSS-annotated regions for the tissue head, one example region, and the patient's own sections for bundled cases (five cases, eight slides shipped; `docs/pathology.md`) | open (GDC open-access slide images, no dbGaP, no token) | NIH GDC open-access data; cite the TCGA Research Network | `scripts/slide_spike.py`, `scripts/slide_pipeline.py`, `scripts/slide_pyramid.py` | per slide: a thumbnail of the scored region, per-tile class scores and quality verdicts, per-tile nuclei counts and each counted nucleus's centroid, area and solidity, ≤ 60 crops of 224 px (`app/workbenches/slides_results/<slide>/`, under 3 MB per section); and, for the slide viewer, JPEG Deep Zoom pyramids of the eight scored sections at about 1 µm/px (quality 80, no slide label; one zip per section, 13–175 MB, on the release `slide-tiles-v1`, credited to the TCGA Research Network; `docs/pathology.md` §7), never in the repository; never embeddings, never nucleus masks |
| **BCSS** (Breast Cancer Semantic Segmentation; Amgad et al., *Bioinformatics* 2019, [10.1093/bioinformatics/btz083](https://doi.org/10.1093/bioinformatics/btz083)) region masks on 151 TCGA-BRCA slides | labels for the tissue head (tumor, stroma, lymphocytes, necrosis, fat); patient-disjoint evaluation | open (masks from figshare links in the repo's `meta/roiBounds.csv`; no account) | **CC0 1.0**; the authors ask for a citation | `scripts/slide_spike.py tiles` | aggregate accuracy per class; the head's weights (if published) |
| **PAM50 centroids** (Parker et al., *J Clin Oncol* 2009, [10.1200/JCO.2008.18.1370](https://doi.org/10.1200/JCO.2008.18.1370)) from the **genefu** package (`data/pam50.rda`, commit 9c9b66d; Gendoo et al., *Bioinformatics* 2016) | the subtype call in the omics workbench (50 genes x 5 centroids) | open (GitHub / Bioconductor) | **Artistic-2.0** (genefu); cite Parker 2009 and genefu | `scripts/omics_scores.py` | each bundled case's call and its five correlations in `app/omics_scores.json`; the centroid table itself is not copied into the repo |
| **MSigDB Hallmark gene sets** v2025.1.Hs (Liberzon et al., *Cell Syst* 2015, [10.1016/j.cels.2015.12.004](https://doi.org/10.1016/j.cels.2015.12.004)) | pathway scores in the omics workbench | open download (no account) | **CC BY 4.0**; attribution | `scripts/omics_scores.py` | set names and sizes, set membership of the genes the model reads, per-case set scores |
| **TCGA published PAM50 calls and receptor IHC** via cBioPortal: `brca_tcga_pan_can_atlas_2018` (SUBTYPE; Hoadley et al., *Cell* 2018) and `brca_tcga` (Firehose 2016-01-28: ER_STATUS_BY_IHC, PR_STATUS_BY_IHC, IHC_HER2, HER2_FISH_STATUS) | validating the subtype call; receptor consistency against recorded IHC | open (cBioPortal public API) | TCGA open-access clinical data; cite TCGA and cBioPortal | `scripts/omics_scores.py` | agreement numbers and the confusion matrix (aggregate); per bundled case its published call and recorded ER / PR / HER2 status, as with the stage already shown |
| **HM450 probe map** (`HM450.hg38.manifest.gencode.v36.probeMap`, UCSC Xena GDC hub) | the gene a methylation CpG lies near, in the omics Spot panel | open | as TCGA above | `scripts/omics_scores.py` | CpG → gene names for the 500 CpGs the model reads |
| **TCGA-Reports** (Kefeli and Tatonetti, *Patterns* 2024, [10.1016/j.patter.2024.100933](https://doi.org/10.1016/j.patter.2024.100933); Mendeley Data [10.17632/hyg5xkznpx.1](https://doi.org/10.17632/hyg5xkznpx.1)): 9,523 OCR'd, cleaned TCGA pathology reports as text, keyed by barcode | the bundled TCGA cases' pathology reports in the clinical documents workbench; measuring the extraction rules on the 1,005 TCGA-BRCA reports | open download (`TCGA_Reports.csv.zip`, 11 MB) | **CC BY 4.0**: attribution, shown with each report and on the Methods page | `scripts/prepare_documents.py`, `muffle.workbench.documents` | the 38 bundled cases' report text (`app/documents/<barcode>.json`, 240 KB) with attribution; aggregate precision and recall (`app/documents/validation.json`, `docs/documents.md`) |
| **TCGA-BRCA clinical matrix** (UCSC Xena TCGA hub, `TCGA.BRCA.sampleMap/BRCA_clinicalMatrix`): receptor status, pT, pN, stage, histology, margins, node counts | the reference the extraction is measured against | open (TCGA open-access clinical data) | as TCGA above | `scripts/prepare_documents.py` (read locally) | counts only; no patient-level field |
| **TCGA-BRCA radiology** (The Cancer Imaging Archive; Lingle et al. 2016, [10.7937/K9/TCIA.2016.AB2NAZRP](https://doi.org/10.7937/K9/TCIA.2016.AB2NAZRP)): breast MRI and mammography of 139 TCGA-BRCA patients, with DICOM structured reports | the radiology workbench's image viewer: three held-out TCGA cases with a public study (563 and 937 MRI, 926 mammography) | open (public NBIA REST API, no login) | **CC BY 3.0**: attribution, redistribution allowed | `scripts/radiology_pipeline.py`, `muffle.workbench.radiology` | 8-bit downsampled copies (≤ 256 px MR slices, 512 px mammograms) and derived contours and measurements in `app/workbenches/radiology_results/`, attributed on the page; never the DICOM originals |
| **Synthetic cohort** (`scripts/make_synthetic.py`) | development and tests | generated | MIT (this repo) | `muffle.data.synthetic` | code only |
| **Synthetic timeline patient** SYNTHETIC-001 (hand-written) | the demo's patient timeline | generated | MIT (this repo) | `muffle.timeline` | its record and scores, labeled synthetic |
| **Synthetic ctDNA series** for SYNTHETIC-001 (hand-written, `muffle.timeline.CTDNA`): 12 plasma samples, VAF of PIK3CA H1047R, ESR1 D538G, DNMT3A R882H | the ctDNA monitor (`docs/ctdna.md`); no open serial breast ctDNA data exists (`docs/model_survey.md` §5) | generated | MIT (this repo) | `muffle.timeline`, `muffle.workbench.ctdna` | the series itself, labeled synthetic on every screen and export; never scored by the risk models |
| **Lab reference intervals**: Mayo Clinic Laboratories test catalog, adult reference values of 15 tests (CA153, C2729, CEA, ALP, ALT, AST, GGT, BILIT, RFAMA for calcium, phosphorus and albumin, LD, CRTS1, CBC), read 2026-10-20 | the lab workbench's reference table (`docs/labs.md`), used only when the lab report gives no interval | open web pages (mayocliniclabs.com) | © Mayo Foundation; numbers cited with the test ID and catalog page, no text copied | `muffle.workbench.labs_reference` | the interval numbers with their source line |
| **Grading and equations**: NCI CTCAE v5.0 (2017; U.S. government work); 2021 CKD-EPI creatinine equation (Inker et al., NEJM 2021, doi:10.1056/NEJMoa2102953); albumin-adjusted calcium (Payne et al., BMJ 1973, doi:10.1136/bmj.4.5893.643) | low-count grades, eGFR and adjusted calcium in the lab workbench | open publications | CTCAE public domain; papers cited, equations reimplemented | `muffle.workbench.labs_reference` | grades and calculated values, labeled with their source |

## Models

| Model | Role | Access | License / terms | Inputs it receives |
|---|---|---|---|---|
| **MuFFLe++ fusion survival model** (trained here) | multi-omic risk with missing-layer masks; clinical anchor + omic residual, FedAvg with NVIDIA FLARE | weights in the release `demo-bundle-v2` | MIT (code); trained on TCGA open data | one patient's processed omics and clinical features |
| **MSK-CHORD landmark models** (gradient boosting, trained here, 5 seeds × 4 landmarks) | 12-month progression-or-death risk; baseline (diagnosis only) vs record so far | **local only, not published** | trained on CC BY-NC-ND data, so not shared | a record's timeline features |
| **Midnight-12k** (`kaiko-ai/midnight`; Karasikov et al., arXiv:2504.05186, preprint) | pathology tile encoder, ViT-g/14 DINOv2, trained on 12k public TCGA slides | Hugging Face, **ungated** | **MIT** (card and API); note TCGA-BRCA slides were in its pretraining | 224 px H&E tiles, locally; measured on this PC's CPU (`docs/decisions.md` 2026-10-19): too slow for a whole slide without a GPU |
| **QuiltNet-B-32** (`wisdomik/QuiltNet-B-32`; Ikezogwo et al., NeurIPS 2023, arXiv:2306.11207) | pathology tile encoder used for the spike's tissue head: CLIP ViT-B/32 trained on Quilt-1M (histopathology video frames) | Hugging Face, **ungated** | **MIT** (card and API). Card: research output; "any deployed use case ... is out of scope", so the hosted app shows precomputed results only and runs no encoder | 224 px H&E tiles, locally |
| **MedSAM** ViT-B (`wanglab/medsam-vit-base`, revision `de8488b`; Ma et al., *Nat Commun* 2024, [10.1038/s41467-024-44824-z](https://doi.org/10.1038/s41467-024-44824-z)) | lesion contours in the radiology workbench from a box prompt (the seed rule's box), precomputed offline; not validated on breast MRI here | Hugging Face, **ungated** | **Apache-2.0** (card and API) | one MR slice and a box, locally (about 12–21 CPU seconds per slice); the hosted app runs no model |
| **mammoscreen** (`ianpan/mammoscreen`, revision `b619a88`; no paper; the card reports AUROC 0.945 on 10% held-out splits of the RSNA 2023 screening data) | screening score and BI-RADS density per breast for the radiology workbench's mammography study, precomputed offline; not validated here | Hugging Face, **ungated**; the published architecture re-built with timm and the weights loaded strictly, so no remote code runs | **Apache-2.0** (card and API); trained on CBIS-DDSM, then RSNA 2023 (the RSNA data terms not retrieved) | one study's CC and MLO views per breast, locally (2–9 CPU minutes for four views on the shared CPU); the hosted app runs no model |
| **Breast tissue head** (logistic regression on frozen tile embeddings, trained here) | tile class probabilities in the slide workbench | weights in `scripts/slide_spike.py train` output (local; small JSON) | MIT (code); trained on BCSS (CC0) tiles from TCGA open slides | one tile's embedding |
| **StarDist 2D_versatile_he** (Schmidt et al., MICCAI 2018, [10.1007/978-3-030-00934-2_30](https://doi.org/10.1007/978-3-030-00934-2_30); Weigert et al., WACV 2020; `pip install stardist`, pretrained weights fetched by the package) | nucleus segmentation on front-band tiles for the slide workbench's cell level (breakaway candidates, lymphocyte-like nuclei, nuclear-area variation) | pip, pretrained weights from the StarDist GitHub release, no account | **BSD-3-Clause** (code and weights); pretrained on H&E from other organs, **not validated on breast here** (the page says so on every flag) | 448 px H&E tiles at the slide's native resolution, locally in WSL (TensorFlow CPU); nothing of it in the app |
| **NVIDIA Nemotron 3 Super** (`nvidia/nemotron-3-super-120b-a12b`) | case agent planner: calls the tools | Nebius Token Factory API | NVIDIA open model license (see the model card); Token Factory terms | derived numbers (risk, percentile, contributions), gene and mutation names, CIViC items, Tavily results |
| **NVIDIA Nemotron 3 Ultra** (`nvidia/Nemotron-3-Ultra-550b-a55b`) | case agent writer | Nebius Token Factory API | as above | the planner's tool outputs |

Every Token Factory call goes through `muffle.report.budget` (hard spending cap).

### Candidate models by workbench (status 2026-10-20)

Checked from the model cards, gate forms and licenses, not by running them (except where a
measurement is cited). Status: **usable now** (open, may run offline today) · **pending
click-through** (allowed once the account owner accepts the terms; [`model_access.md`](model_access.md))
· **local only** (non-commercial or no-derivatives terms: never in the repo, the hosted app, a
release, Token Factory or Tavily; aggregate numbers only) · **excluded** (not to be used). Speed,
accuracy and the per-model paragraphs: [`encoders.md`](encoders.md). None of these runs in the
hosted app.

| Model | Workbench / role | Status | Access | License / terms | Inputs it receives |
|---|---|---|---|---|---|
| **Path Foundation** (`google/path-foundation`, TF SavedModel) | slides: tile encoder (ViT-S, 384-d) | pending click-through | HF, HAI-DEF terms, instant | Health AI Developer Foundations terms; pass use restrictions on with any fine-tuned weights; trained on TCGA | 224 px H&E tiles, offline |
| **GigaPath-Flash** (`prov-gigapath/prov-gigapath-flash`) | slides: tile encoder (ViT-S, 384-d) and slide encoder | pending click-through | HF, contact info, instant | Apache-2.0; card: research only, "any deployed use case ... is out of scope", not for clinical care | 224 px H&E tiles, offline |
| **Hibou-B**, **Hibou-L** (`histai/hibou-b`, `histai/hibou-L`) | slides: tile encoders (ViT-B 768-d; ViT-L 1024-d) | pending click-through | HF, contact info, instant; repo code pinned to a revision | Apache-2.0 | 224 px H&E tiles, offline |
| **H-optimus-0** (`bioptimus/H-optimus-0`) | slides: tile encoder (ViT-g, 1536-d) | pending click-through | HF, form (name, affiliation, email, use-case), instant | Apache-2.0; gate: not reviewed by any regulator, independent validation needed | 224 px tiles at 0.5 µm/px, GPU |
| **Virchow** v1 (`paige-ai/Virchow`) | slides: tile encoder (ViT-H, 2560-d) | pending click-through (institutional email) | HF, primary email must be institutional | Apache-2.0 plus card terms: not for diagnosis or treatment of real patients | 224 px tiles, GPU |
| **UNI2-h** (`MahmoodLab/UNI2-h`) | slides: reference encoder (ViT-H, 1536-d) | **local only** (after click-through, institutional email) | HF, institutional primary email | CC BY-NC-ND 4.0; derivatives include models trained on its outputs; no distribution | 224 px tiles, GPU; results never under `app/` (code-enforced) |
| **CONCH** (`MahmoodLab/CONCH`) | slides: vision-language encoder (ViT-B/16 at 448 px, 512-d), zero-shot queries | **local only** (after click-through, institutional email) | HF, institutional primary email | CC BY-NC-ND 4.0, same terms as UNI2-h | 448 px tiles, offline |
| **LazySlide** (rendeirolab) | slides: tiling, tissue detection, encoder calls (plumbing) | usable now | PyPI, open | MIT | slides, offline |
| **StarDist** `2D_versatile_he` | slides: nuclei segmentation in H&E | usable now (check MoNuSeg terms before publishing masks) | PyPI + GitHub release, open | code BSD-3-Clause; weights trained on MoNuSeg 2018 (terms not re-checked) and TNBC (CC BY 4.0, Zenodo 1175282) | H&E tiles, offline CPU |
| **CellViT** / CellViT++ (TIO-IKIM) | slides: nuclei segmentation and typing | **local only** | Google Drive checkpoints, open | code "Apache 2.0 with Commons Clause"; checkpoints trained on PanNuke (CC BY-NC-SA 4.0); CellViT-SAM-H needs a 24 GB GPU | H&E tiles, GPU |
| **HoVer-Net** (vqdang) | slides: nuclei segmentation and typing | **local only** (PanNuke weights); other checkpoints not used | Google Drive checkpoints, open | code MIT; README: PanNuke-derived weights CC BY-NC-SA 4.0 | H&E tiles, GPU preferred |
| **MedSAM** (`wanglab/medsam-vit-base`; mirror `flaviagiammarino/medsam-vit-base`) | radiology: promptable lesion contour (box prompt) | usable now | HF, ungated | Apache-2.0 (card and API) | one 2D image + a box, offline CPU |
| **MedSAM2** (`wanglab/MedSAM2`) | radiology: 3D / video lesion segmentation | usable now (share-alike) | HF, ungated | CC BY-SA 4.0: attribution; modified weights shared under the same license | volumes + a prompt, offline (GPU preferred) |
| **SAM 3** (`facebook/sam3`) | radiology / slides: text- and box-prompted segmentation (general images) | pending click-through (manual review) | HF, manual: name, date of birth, country, affiliation, job title | SAM License: royalty-free use, modification and redistribution with the license attached; trade-control and military-use exclusions; acknowledge SAM in publications. A research app is allowed | images, offline GPU |
| **SAM 2.1** (`facebook/sam2.1-hiera-large`) | radiology: general promptable segmentation | usable now | HF, ungated | Apache-2.0 | images, offline |
| **MedGemma 1.5 4B** (`google/medgemma-1.5-4b-it`) | documents: local extraction of receptors, stage, drugs, dates from report text | pending click-through | HF, HAI-DEF terms, instant | Health AI Developer Foundations terms; card: outputs preliminary, need independent verification | report text, **locally only** (never Token Factory) |
| **OpenMed NER OncologyDetect** (`OpenMed/OpenMed-NER-OncologyDetect-BigMed-278M`) | documents: highlight cancer, organ, gene entities in source sentences | usable now | HF, ungated | Apache-2.0 | report text, locally only, CPU |
| **mammoscreen** (`ianpan/mammoscreen`) + crop model `ianpan/mammo-crop` | mammography: cancer likelihood and density per exam | usable now | HF, ungated; repo code (pin revisions `b619a889`, `bec2e302`) | Apache-2.0 (both); trained on CBIS-DDSM and RSNA 2023 (RSNA terms not retrieved) | CC + MLO images, offline CPU |
| **Mirai** (reginabarzilaygroup) | mammography: 5-year risk | usable now (needs four standard views) | GitHub, open | MIT (model and code) | four-view screening exam, offline |
| **Pillar0-BreastMRI** (`YalaLab/Pillar0-BreastMRI`) | MRI: exam embeddings | pending click-through | HF, name and organization, instant; repo code | ECL-2.0; preprint, authors' internal evaluation only | breast MRI volumes, offline (GPU preferred) |

## Services

| Service | Role | Terms | What is sent |
|---|---|---|---|
| Nebius Token Factory | hosts the Nemotron models (OpenAI-compatible API) | Nebius terms; hackathon credits | see Models above; never raw omics, nothing from MSK-CHORD |
| Tavily | literature and clinical-trial search for the case note | Tavily API terms | one query per gene with the cancer type |
| ClinicalTrials.gov API v2 (U.S. National Library of Medicine; no key) | recruiting or not yet recruiting breast cancer trials that mention a patient's observed genes, in the Evolution view; snapshot `app/trials_snapshot.json` (`scripts/refresh_trials.py`) for when it can't be reached | the site's Terms and Conditions (read 2026-10-20): free to all; attribute ClinicalTrials.gov, keep the data current, show the date the data were processed, state modifications; no proprietary claim; some records may carry third parties' copyright | the condition "breast cancer", the term "<GENE> mutation" and the status filter; never anything from a patient's record |
| PubMed through NCBI E-utilities | checking every citation of the evolution table (`docs/evolution.md`; also in `tests/test_evolution.py`) | NLM terms; abstracts are cited, not copied | PMIDs only |
| Streamlit Community Cloud | hosts the demo | Streamlit terms | the public repo and the demo bundle; the slide tile zips it downloads from the release on first use and serves from `app/static/`; files a user imports stay in that browser session's memory and are never written to disk |

## Code reused from the team's other project

The Colon Tumor Front Analyzer (the team's entry to the Ashby Prize Hackathon 2026, a private
repository with no license file: the team holds the copyright) is the depth standard for the
workbenches. The slide workbench re-implements its grammar (224 px tiles at 0.5 µm/px, a small
head on frozen embeddings, 3×3 smoothing, tumor mask → front → core / front band / peritumoral
zones, an "unsure here" cutoff, glass / ink / blur texture rules with cutoffs tagged by source)
in this repository's own code; no file, model weight or colon-trained head is copied. The cutoffs
it carried over are tagged **placeholder** because they were set on colon slides. Rules check
(2026-10-19): the Ashby pages publish eligibility, dates and judging criteria and no
intellectual-property or exclusivity terms; the Devpost rules require the submission to be the
entrant's own work and allow open-source components the entrant may use. The Devpost text must
disclose the reuse (CLAUDE.md).

## Software

NVIDIA FLARE ≥ 2.8 (Apache-2.0) · PyTorch (BSD-3-Clause) · scikit-learn (BSD-3-Clause) ·
scikit-survival (GPL-3.0; metrics only, not redistributed) · pandas, NumPy (BSD-3-Clause) ·
Streamlit (Apache-2.0) · Altair (BSD-3-Clause) · openai-python (Apache-2.0) · tavily-python (MIT) ·
SciPy (BSD-3-Clause) · pypdf (BSD-3-Clause; text layer of an imported PDF) · pydicom (MIT;
header of an imported DICOM file, pixels not read; and the radiology pipeline) · Pillow
(MIT-CMU; checks an imported image and draws the radiology overlays, already a Streamlit
dependency) · OpenSeadragon 6.1.1 (BSD-3-Clause; vendored in
`app/workbenches/slide_viewer_frontend/` with its license; the slide viewer, run in the browser)
· for the slide and radiology pipelines only (not in the app): OpenSlide (LGPL-2.1, via
`openslide-bin`; also cuts the slide viewer's Deep Zoom tiles), scikit-image (BSD-3-Clause),
Transformers (Apache-2.0), TensorFlow CPU (Apache-2.0), StarDist and CSBDeep (BSD-3-Clause), timm
(Apache-2.0) · for `scripts/omics_scores.py` only (not in the app): rdata (MIT), to read genefu's
`.rda` file.

## Candidates, not used

Not checked yet; check license, access tier, compute and validation before adding any of them
(VISION part five):
- CPTAC breast proteomics (only ~100 TCGA-BRCA tumors overlap; RPPA is used instead).
- Other longitudinal breast cohorts with repeated sequencing, for evolutionary hypotheses.

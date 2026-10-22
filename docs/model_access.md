# Model access: what you click, and what to run afterwards

Checklist for the people who own the Hugging Face (HF) accounts. Written 2026-10-20 from the model
cards and gate forms (read through the HF API; forms behind a login were read from the API's
`extra_gated_fields`). Licenses and what each model may be used for: [`registry.md`](registry.md);
measured speed and accuracy: [`encoders.md`](encoders.md); a GPU run: [`gpu.md`](gpu.md).

Nothing here changes the hosted app. It runs no encoder; encoders run offline (WSL CPU now, a GPU
later) and the app reads small precomputed result folders.

## Your remaining clicks (2026-10-21)

Logged in as `psuryansh` (its primary email is the verified university address these gates
require), open each link, fill in what the line says and submit. Approval is instant unless the
line says *manual review*. Answers to reuse, the same ones the forms already sent used:
- full name; affiliation **University of Illinois Urbana-Champaign**; type **Academia**; email:
  the account's primary email; Bioptimus' main use-case **Models benchmarking on various tasks**;
  newsletter boxes left empty;
- research use, where a form asks (it stays true only while the model stays local):

> Non-commercial academic research at the University of Illinois Urbana-Champaign: benchmarking pathology foundation models as frozen tile encoders for breast-cancer tissue classification on public TCGA-BRCA diagnostic slides with BCSS (CC0) region labels, compared with open-license encoders, in an open-source research prototype. The model runs only on our local machine; we will not redistribute the model, its embeddings or its outputs; no clinical use and no decisions about patients; only aggregate results are reported, with attribution.

1. <https://huggingface.co/google/path-foundation>: "Acknowledge license" (HAI-DEF terms). Slides: ViT-S tile encoder.
2. <https://huggingface.co/google/medgemma-1.5-4b-it>: "Acknowledge license". Documents: local extraction.
3. <https://huggingface.co/google/medsiglip-448>: "Acknowledge license". Radiology and pathology zero-shot image–text queries.
4. <https://huggingface.co/histai/cellvit-hibou-l>: agree. Nuclei segmentation and typing; CC BY-NC-SA 4.0, **local only**.
5. <https://huggingface.co/MahmoodLab/madeleine>: agree. Slide encoder pretrained on breast H&E with IHC; MIT, but it reads CONCH features, so **local only** in practice.
6. <https://huggingface.co/microsoft/BiomedParse>: agree. Text-prompted segmentation; CC BY-NC-SA 4.0, **local only**.
7. <https://huggingface.co/bioptimus/H-optimus-0>: name, type, affiliation, email, main use-case. ViT-g tile encoder, Apache-2.0.
8. <https://huggingface.co/MahmoodLab/UNI>: name, affiliation, type, email, research use, three boxes. ViT-L encoder; **local only**.
9. <https://huggingface.co/MahmoodLab/conchv1_5>: the same form. TITAN's patch encoder; **local only**.
10. <https://huggingface.co/MahmoodLab/TITAN>: the same form. Slide embeddings; **local only**.
11. <https://huggingface.co/MahmoodLab/CONCH-Z>: the same form. Zero-shot CONCH, released 2026-10-14; **local only**.
12. <https://huggingface.co/paige-ai/Virchow>: name, email, agree. ViT-H encoder, Apache-2.0 plus card terms.
13. <https://huggingface.co/paige-ai/Virchow2>: name, email, agree. **Local only**.
14. <https://huggingface.co/paige-ai/Prism>: name, email, agree. Slide embeddings and text on Virchow tiles; **local only**.
15. <https://huggingface.co/YalaLab/Pillar0-BreastMRI>: name, organization. Breast MRI exam embeddings.
16. <https://huggingface.co/bioptimus/H-optimus-1>: form, research use, three boxes; *manual review*. ViT-g; **local only**.
17. <https://huggingface.co/bioptimus/H0-mini>: the same; *manual review*. A ViT-B distilled from H-optimus-0 that runs on this CPU; **local only**.
18. <https://huggingface.co/paige-ai/Prism2>: name, email, agree; *manual review*. **Local only**.
19. <https://huggingface.co/paige-ai/Prism2-survival>: the same; *manual review*. Survival from the slide, a comparison for the risk model; **local only**.
20. <https://huggingface.co/owkin/histoplus>: agree; *manual review*. Cell detection and typing (Owkin license, not read).
21. Optional: <https://huggingface.co/facebook/sam3>: name, date of birth, country, affiliation, job title; *manual review*. SAM 2.1 and MedSAM are open already.

Then do step 0 (the token) and tell any session: the delegation session has the model-access
session run `E1` for every granted encoder.

**Already granted** ([Gated Repositories](https://huggingface.co/settings/gated-repos)): Hibou-B,
Hibou-L, GigaPath-Flash, Prov-GigaPath, UNI2-h and SPIDER-breast (2026-10-21), and CONCH, MUSK,
PathGen-CLIP and the PathGen dataset (2026-10-14). None refused. A session sent the first six and
then the permission check stopped its automated form submissions (accepting license terms for
someone is theirs to do), which is why the list above is yours. Midnight-92k has no public repo,
so there is nothing to request.

**Open models found on 2026-10-21 (no request).** Licenses from the cards and the HF API.

| Model | License | What it would do here | Checked here |
|---|---|---|---|
| WSInfer breast tumor ResNet34 ([`kaczmarj/breast-tumor-resnet34.tcga-brca`](https://huggingface.co/kaczmarj/breast-tumor-resnet34.tcga-brca); Le et al., *Am J Pathol* 2020, PMID 32277893) | CC BY 4.0: its maps may be shown with attribution | slides: tumor vs other per 350 px tile at 0.25 µm/px | screening check (2026-10-21, not in the repo): tumor vs rest AUROC 0.921 on 516 BCSS-labelled tiles from 11 TCGA-BRCA slides (QC-passed, pure labels, at most 120 per class; the centre 87.5 µm of each 224 px tile at 0.5 µm/px). At its own 0.5 cutoff the balanced accuracy is 0.788, because stroma, fat and necrosis average 0.38–0.42: the cutoff needs calibrating. 1.2 tiles/s at 2 threads on the loaded CPU. Trained on TCGA-BRCA, so these slides may overlap its training |
| WSInfer TIL InceptionV4 ([`kaczmarj/pancancer-lymphocytes-inceptionv4.tcga`](https://huggingface.co/kaczmarj/pancancer-lymphocytes-inceptionv4.tcga); Abousamra et al., *Front Oncol* 2022, [10.3389/fonc.2021.806603](https://doi.org/10.3389/fonc.2021.806603)) | CC BY 4.0 | slides: lymphocyte-rich vs other per 50 µm patch, a TIL map | the same check: lymphocytes vs rest AUROC 0.980 (the centre 50 µm of each tile); lymphocyte tiles average 0.96, stroma 0.30, the rest at most 0.05. 0.5 tiles/s. Trained on TCGA (23 cancer types) |
| KEEP ([`Astaxanthin/KEEP`](https://huggingface.co/Astaxanthin/KEEP); *Cancer Cell* 2026) | MIT | slides: zero-shot vision–language queries (ViT-L), an open alternative to CONCH; repo code, pin the revision | not run |
| MONAI breast density ([`MONAI/breast_density_classification`](https://huggingface.co/MONAI/breast_density_classification); Mayo Clinic, arXiv:2202.08238) | Apache-2.0 | radiology: BI-RADS density A–D from a 299 px mammogram (InceptionV3) | not run |
| OpenMed zero-shot oncology NER ([`OpenMed/OpenMed-ZeroShot-NER-Oncology-Base-220M`](https://huggingface.co/OpenMed/OpenMed-ZeroShot-NER-Oncology-Base-220M)) | Apache-2.0 | documents: entity labels you name, such as "ER status" or "HER2 score" | run (2026-10-21, documents round 2): offline on the 38 bundled and 495 held-out TCGA-BRCA reports with 16 breast pathology labels; spans ship for the bundled reports. Mostly marks where a field is named (98% of spans hold no result); where it gives a value, pT 96% and histologic type 100% precision, recall 0–11% ([`documents.md`](documents.md)) |
| Granite-Docling 258M ([`ibm-granite/granite-docling-258M`](https://huggingface.co/ibm-granite/granite-docling-258M)) | Apache-2.0 | Import tests: a scanned or PDF report to structured text | run (2026-10-21, documents round 2): the local pipeline's page reader for scanned PDFs; 98–99% character accuracy on two synthetic scans, 8–52% on two real fax-quality TCGA report scans where it loops (flagged) ([`documents.md`](documents.md)) |
| MedCPT ([`ncbi/MedCPT-Cross-Encoder`](https://huggingface.co/ncbi/MedCPT-Cross-Encoder) and its query and article encoders) | public domain (NCBI) | literature: rank the PubMed and Tavily hits a case note cites | not run |
| ESM-1b ([`facebook/esm1b_t33_650M_UR50S`](https://huggingface.co/facebook/esm1b_t33_650M_UR50S)); Evo 2 ([`arcinstitute/evo2_7b`](https://huggingface.co/arcinstitute/evo2_7b)) | MIT; Apache-2.0 | genomics: a second missense effect score next to AlphaMissense; Evo 2 needs an NVIDIA GPU | not run |

Not used: TIA Centre's checkpoints (no license on most cards), the Camelyon and metastasis models
(lymph nodes, and most are NC), community breast classifiers with no paper or validation, and
BoostDM (driver prediction per tumor type; no license found in its documentation).

## 0. Once: a token where the scripts can read it

1. Log in at <https://huggingface.co/login> with the account that will hold the access.
2. Make a **read** token at <https://huggingface.co/settings/tokens> (New token → Type: Read).
3. In WSL, add one line to the `.env` of each clone that runs encoders (the file is git-ignored;
   never commit it, never paste the token into a chat, an issue or a commit):
   ```bash
   echo 'HF_TOKEN=hf_...' >> ~/muffle-plus-plus/.env
   ```
   `scripts/slide_spike.py` reads `HF_TOKEN` from the environment or that `.env` and never prints
   it. The hosted app (Streamlit secrets) does **not** need it: it downloads no model.
4. Check what the token can open (prints one line per model, no token):
   ```bash
   for m in google/path-foundation prov-gigapath/prov-gigapath-flash histai/hibou-b histai/hibou-L bioptimus/H-optimus-0 paige-ai/Virchow MahmoodLab/UNI2-h MahmoodLab/CONCH google/medgemma-1.5-4b-it YalaLab/Pillar0-BreastMRI facebook/sam3; do ~/muffle-encoders/.venv/bin/python -c "import sys; from dotenv import load_dotenv; load_dotenv('$HOME/muffle-plus-plus/.env'); from huggingface_hub import auth_check; auth_check(sys.argv[1]); print('granted', sys.argv[1])" $m 2>/dev/null || echo "not yet  $m"; done
   ```

## 1. Click-throughs that work with a personal email (instant)

Gate mode `auto` on all of these: access is granted as soon as the form is sent.

| # | Model | URL | What the form asks | Then run |
|---|---|---|---|---|
| 1 | **Hibou-B** (Apache-2.0; ViT-B, the strongest open encoder that still runs on this CPU) | <https://huggingface.co/histai/hibou-b> | Share contact information (HF username and email); no extra fields | `E1` below with `histai/hibou-b` |
| 2 | **GigaPath-Flash** (Apache-2.0; ViT-S, fastest) | <https://huggingface.co/prov-gigapath/prov-gigapath-flash> | Share contact information; no extra fields | `E1` with `prov-gigapath/prov-gigapath-flash` |
| 3 | **Path Foundation** (Google HAI-DEF terms; ViT-S) | <https://huggingface.co/google/path-foundation> | "Acknowledge license": agree to the [Health AI Developer Foundations terms](https://developers.google.com/health-ai-developer-foundations/terms) | `~/muffle-encoders/.venv/bin/python -m pip install tensorflow-cpu`, then `E1` with `google/path-foundation` |
| 4 | **Hibou-L** (Apache-2.0; ViT-L, overnight on CPU) | <https://huggingface.co/histai/hibou-L> | Share contact information; no extra fields | `E1` with `histai/hibou-L` (or the GPU run) |
| 5 | **H-optimus-0** (Apache-2.0; ViT-g, GPU only) | <https://huggingface.co/bioptimus/H-optimus-0> | Full name, type of affiliation, current affiliation, "current and official institutional email", main use-case (pick "Models benchmarking on various tasks"), optional newsletter box. Approval is automatic; give your university email if you have one | GPU run ([`gpu.md`](gpu.md)) |
| 6 | **MedGemma 1.5 4B** (HAI-DEF terms; local report extraction) | <https://huggingface.co/google/medgemma-1.5-4b-it> | "Acknowledge license", the same HAI-DEF terms as 3 | Access check only (step 0.4); no extraction pipeline yet |
| 7 | **Pillar0-BreastMRI** (ECL-2.0; MRI exam embeddings) | <https://huggingface.co/YalaLab/Pillar0-BreastMRI> | Name, organization | Access check only; no MRI pipeline yet |

`E1`, the one command per encoder (in WSL, from the clone; about 2,200 tiles, CPU minutes in
[`encoders.md`](encoders.md)):

```bash
cd ~/muffle-plus-plus && git pull
M=histai/hibou-b; R=~/muffle-encoders/runs/${M##*/}
OMP_NUM_THREADS=4 nice -n 10 ~/muffle-encoders/.venv/bin/python scripts/slide_spike.py embed --tiles ~/muffle-encoders/work --work $R --model $M --threads 4 && ~/muffle-encoders/.venv/bin/python scripts/slide_spike.py train --work $R --test TCGA-C8-A26X-DX1 TCGA-C8-A26Y-DX1 TCGA-EW-A1OV-DX1
~/muffle-encoders/.venv/bin/python scripts/slide_spike.py compare --runs ~/muffle-encoders/runs   # the table for docs/encoders.md
```

Without access the first command stops with one line naming the URL to click and `HF_TOKEN`.

## 2. Institutional email required (approval by the model's owners)

These pages say the HF account's **primary** email must be an institutional address; the Mahmood
Lab forms say "@gmail/@hotmail/@qq email domains will be denied". Before applying:
1. <https://huggingface.co/settings/account> → add the university email → confirm the link it sends.
2. Make that address the **primary** email on the same page.
3. Then fill the form below with the same address.

| # | Model | URL | What the form asks | Local only? |
|---|---|---|---|---|
| 8 | **UNI2-h** (CC BY-NC-ND 4.0; ViT-H) | <https://huggingface.co/MahmoodLab/UNI2-h> | Full name; affiliation (no abbreviations); type of affiliation (Academia / Industry / Other); official institutional email matching the HF primary email; intended research use; three boxes: all terms, non-commercial academic use only, no distribution | **Yes** |
| 9 | **CONCH** (CC BY-NC-ND 4.0; ViT-B, 448 px; best rank in the one independent benchmark) | <https://huggingface.co/MahmoodLab/CONCH> | Same fields as UNI2-h | **Yes** |
| 10 | **Virchow** (v1; Apache-2.0 plus card terms; ViT-H) | <https://huggingface.co/paige-ai/Virchow> | First and last name; institutional email matching the HF primary email; agree to the license and terms | No (Apache-2.0), but the card says not for diagnosis of real patients |
| 11 | Virchow2 (CC BY-NC-ND 4.0) | <https://huggingface.co/paige-ai/Virchow2> | Same as Virchow | **Yes** (not in ENCODERS yet) |
| 12 | TITAN (CC BY-NC-ND 4.0; slide encoder on CONCH v1.5) | <https://huggingface.co/MahmoodLab/TITAN> | Same fields as UNI2-h | **Yes** (not in ENCODERS yet) |
| 13 | MUSK (CC BY-NC-ND 4.0; **manual review**) | <https://huggingface.co/xiangjx/musk> | Full name, affiliation, type, official (work) email matching the HF primary email, intended use, three boxes | **Yes** (not in ENCODERS yet) |

Commands afterwards: UNI2-h and Virchow are ViT-H, so run them on the GPU ([`gpu.md`](gpu.md)).
CONCH first needs its package: `~/muffle-encoders/.venv/bin/python -m pip install
git+https://github.com/Mahmoodlab/CONCH.git`, then `E1` with `MahmoodLab/CONCH`.

**What local only means (UNI2-h, CONCH, Virchow2, TITAN, MUSK).** CC BY-NC-ND 4.0 and the gate
texts: non-commercial academic research only, no redistribution of the model, and derivatives
"include models trained on outputs from" the model "or datasets created from" it. So their
embeddings, the heads trained on them and the maps they make stay on the machine that made them:
never in the repo, a release asset, the hosted app, a Token Factory or Tavily call, the video or an
issue. Only aggregate numbers (an accuracy in a table) are reported. The code enforces the
repository part: `embed` and `result` refuse any path inside the repository for these models.

## 3. Other workbenches (no command yet; access only)

| # | Model | URL | Step |
|---|---|---|---|
| 14 | SAM 3 (SAM License; promptable segmentation) | <https://huggingface.co/facebook/sam3> | **Manual review**: first and last name, date of birth, country, affiliation, job title, accept the SAM License and Meta's privacy policy. Optional: SAM 2.1 (`facebook/sam2.1-hiera-large`, Apache-2.0) and MedSAM need no request |
| 15 | MAMA-MIA (breast MRI tumour masks and nnU-Net weights; CC BY-NC) | <https://www.synapse.org/> → register, accept the MAMA-MIA terms | Local only (NC); only if the MRI workbench is built |

Open with no request: MedSAM (`wanglab/medsam-vit-base`), MedSAM2 (`wanglab/MedSAM2`, CC BY-SA 4.0),
SAM 2.1, mammoscreen (`ianpan/mammoscreen`), Mirai (GitHub), OpenMed NER, StarDist, LazySlide,
Midnight-12k, QuiltNet-B-32, and GPFM (`majiabo/GPFM`, ungated but **local only**: its repository
is CC BY-NC-ND 4.0 and it is distilled from UNI and CONCH). Details per model: [`registry.md`](registry.md).

## 4. The open legal question

The survey could not settle whether a hackathon entry that can win a prize counts as
"non-commercial, academic research" under CC BY-NC-ND 4.0 (UNI2-h, CONCH, Virchow2, TITAN, MUSK)
and the NC datasets. Until someone with authority answers, those models stay local only and
nothing they produce is shown in the entry. A note you can send to the organisers (or the
university's research office):

> Our entry uses public breast-cancer data and, locally, pathology models released under CC BY-NC-ND 4.0 "for non-commercial, academic research purposes"; we never redistribute the models or their outputs. Does a prize-eligible hackathon submission count as non-commercial academic research under those terms, or should we keep these models out of the entry entirely?

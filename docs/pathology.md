# Pathology slide workbench: what the pipeline computes and what it cannot

Round 2 of the slide workbench (2026-10-20): the patient's own diagnostic sections, the
direction of invasion, cell-level counts and the risk map. Design: `WORKBENCHES.md` §5. Code:
`scripts/slide_pipeline.py` (offline, WSL), `src/muffle/workbench/slides.py` (tiles, front,
zones, quality: round 1), `src/muffle/workbench/invasion.py` (round 2), the page
`app/workbenches/slides.py`. Results the app reads: `app/workbenches/slides_results/<slide>/`.

Nothing on this page is a diagnosis. Every tile class and every nucleus is a **model
inference**; the front, zones, arcs, islands, counting field and points are **geometry and
rules on those inferences**; the direction of invasion is a **hypothesis** about this section:
a 2D snapshot of where the tumor is invading in this cut, never a forecast. Nothing has been
reviewed by a pathologist.

## 1. Which slides

The bundled TCGA-BRCA cases map to patient barcodes through `cohort.npz` (`patient`, the
12-character barcode; `muffle.demo.Case.index` is the row). Diagnostic slides (data type
"Slide Image", experimental strategy "Diagnostic Slide") come from the GDC files endpoint, open
access, no token. Scored on 2026-10-20 (cohort index → sections):

| Case | Patient | Sections | Why this case | Status |
|---|---|---|---|---|
| 299 | TCGA-AN-A0AS | DX1 | in the video; saved case note | shipped |
| 926 | TCGA-EW-A1J2 | DX1 | in the video; saved case note | shipped |
| 1043 | TCGA-PL-A8LZ | DX1, DX2, DX3 | saved case note; three small sections, compared on the page | shipped |
| 730 | TCGA-D8-A1XF | DX1, DX2 | saved case note; two large sections to compare | shipped |
| 563 | TCGA-BH-A0H5 | DX1 | saved case note | shipped (until 2026-10-27 mapped from the wrong place and read "no tumor"; §9) |

The other saved-note cases (47, 545, 564, 601) have one DX1 slide each on the GDC and can be
added with the same command. `cases.json` names only folders that are complete. TCGA slides are open-access public data, so 224 px tile crops of
the queue tiles may be shipped; embeddings never are.

## 2. The pipeline, step by step

1. **Tissue mask and grid.** Saturation > 12 on a 4096 px thumbnail (placeholder, the colon
   analyzer's rule); a 224 px tile at 0.5 µm/px (448 base px on a 40× slide) is tissue when at
   least half its pixels are (design).
2. **Budget.** Up to 9,000 tissue tiles are scored in full. Larger slides get a coarse pass
   (every 3rd row and column) through the same encoder and head; the largest tumor piece of
   that pass centres a square window holding at most 9,000 tissue tiles, which is then scored
   in full. The summary says how many tiles were skipped; the page shows a warning. Tumor
   outside the window is not in the map.
3. **Embedding and classes.** GigaPath-Flash (`prov-gigapath/prov-gigapath-flash`, Prov-GigaPath's
   tile encoder distilled to a ViT-S/16, 384-d, Apache-2.0, gated by a contact-information
   click-through) on CPU since 2026-10-27, batches of 32 streamed from the slide, no tile stack
   in memory; a BCSS head (logistic regression, C = 0.1; 5 classes: invasive carcinoma, stroma,
   lymphocytes, necrosis, fat) trained on its embeddings of the spike's tiles gives the
   probabilities; the round-1 quality rules (glass, pen ink, blur; placeholders) exclude tiles.
   Until 2026-10-26 the encoder was QuiltNet-B-32 (CLIP ViT-B/32, MIT, ungated); §9 has the
   swap and what it changed. A re-run with another encoder (`--model`, a work folder holding that
   encoder's head) changes `encoder` in `summary.json`, the probabilities and everything drawn
   from them; grid, window, nuclei and the second lymphocyte model's scores are cached and
   reused, and the nuclei summaries are recounted against the new map on the tiles StarDist ran
   on (`nuclei_ran.csv`).
4. **Map geometry** (round 1): 3×3 smoothing, tumor = smoothed P(invasive) ≥ 0.5, small holes
   filled, the largest piece is the main tumor, front = main-tumor tiles with a non-tumor
   tissue neighbour, zones by distance (core > 500 µm inside; front band ± 500 µm; peritumoral
   0.5–2 mm outside).
5. **Direction of invasion** (round 2, `invasion.front_normals`, `arcs`, `rose`): the outward
   normal of each front tile is minus the gradient of the main mask blurred by 2 tiles; its
   **push** is the mean smoothed P(invasive) over the 3 tiles beyond the front along that
   normal (0 = sharp edge, near 0.5 = tumor fading into the tissue). The front is cut into 12
   arcs of 30° around the main tumor's centroid; per arc: push-weighted mean direction, mean
   push, **roughness** = share of its tiles in **fingers** (main-tumor tiles that a morphological
   opening of radius 2 tiles removes), pattern (infiltrative at roughness ≥ 0.3, placeholder),
   and what it faces (class shares of the non-tumor tiles touching it). Arrows on the map, one
   per arc, length by push; a rose of the normals weighted by push.
6. **Cells** (`scripts/slide_pipeline.py run_stardist`, `invasion.nuclei_summary`): StarDist
   `2D_versatile_he` on up to 400 tiles per slide at the slide's native resolution (448 px,
   0.25 µm/px; a 20× slide would be upsampled ×2), front tiles first, then the band outside
   the front by distance, then the rest of the front band, then the peritumoral zone. Per
   nucleus: centroid, area (µm²), solidity. Rules, all placeholders: lymphocyte-like = area ≤
   45 µm² and solidity ≥ 0.9; tumor candidate = not lymphocyte-like, area ≥ 40 µm², in a tile
   with raw P(invasive) ≥ 0.5; **breakaway (budding) candidate** = a single-linkage cluster
   (link 20 µm) of up to 4 such nuclei (ITBCC 2016: a bud is ≤ 4 cells) in a front-band tile
   outside the main tumor with raw P(invasive) ≥ 0.3; **counting field** = the ITBCC 0.785 mm²
   field (radius 0.5 mm, 4.46 tiles) placed where the candidates within it are most numerous,
   with the share of the field that was actually counted; a counter for the pathologist's own
   count; tumor-contacting lymphocytes = lymphocyte-like nuclei within 50 µm of a tumor
   candidate; **stromal TILs by zone** in the International TILs Working Group's zones (core,
   front band, peritumoral) as lymphocyte-class tile shares and lymphocyte-like nuclei per mm²
   of stroma-or-lymphocyte tiles: a count proxy, not the WG's area-percentage method; immune
   pattern desert / excluded / inflamed on placeholder cutoffs; **tumor–stroma ratio** as a
   tile count in the tumor and its front band (stroma-high above 50%, the literature's cutoff
   from colorectal cancer, applied here as literature only); **necrosis contact** (necrosis
   tiles touching tumor); **nuclear-area variation** (coefficient of variation of non-lymphocyte
   nuclear area per tile, ≥ 5 nuclei): a proxy only, never a grade.
7. **Satellite islands** (`invasion.satellite_islands`): every tumor piece other than the main
   one with its size, the distance between the nearest tiles, and the classes on the straight
   line between them.
8. **Risk map** (`invasion.risk_map`): a tile collects a feature's points when the feature lies
   within 1 mm: infiltrative arc 2, breakaway candidates 2, faces fat 1, satellite island 1,
   necrosis contact 1, immune-poor front 1 (all placeholders; not an outcome model). Level 2 at
   3 points, level 3 at 5; each region at level 2 or more is a card that opens the Spot panel.
9. **Queue and pointers** (`invasion.look_here`): T1…Tn shared by the overview, the map and the
   Spot panel: risk cards, the counting field, the roughest infiltrative arc, the farthest
   islands, the densest unsure spot; each with its evidence type, status and what to check by
   eye.
10. **Output** (`write_result`): `tiles.json` (row, col, quality verdict, class probabilities),
    `nuclei.json` (per-tile counts for the counted tiles; every counted nucleus's centroid,
    area and solidity, packed per tile, for the viewer's cell layer: `slide_pipeline.py cells`
    adds them from a run's cached nucleus table without re-running anything), `summary.json`
    (everything above plus the head card, timings and the uptime they were measured under),
    `thumbnail.jpg` (the scored region) and `crops/` (≤ 60 JPEG crops of 224 px: the queue,
    the field, the cards, the roughest front tiles, breakaway and unsure tiles). No embeddings,
    no nucleus masks, no tile stack; under 3 MB per section (the largest, TCGA-AN-A0AS-DX1,
    1.9 MB).

## 3. Every cutoff and its source

Round-1 cutoffs (smoothing, tumor probability, zones, quality rules, unsure) are in
`muffle.workbench.slides.CUTOFFS`; round-2 cutoffs in `muffle.workbench.invasion.CUTOFFS`. Both
tables are on the page under "Every cutoff and its source". Tags: **design** (a choice that
defines a measurement, not a claim), **literature** (ITBCC 2016 / Lugli et al. 2017 for the
bud size and the 0.785 mm² field; van Pelt et al. 2018 / Mesker et al. 2007 for the
tumor–stroma ratio; the TILs Working Group for the zones), **placeholder** (chosen by eye or
carried over from the colon analyzer and not checked on breast slides). Placeholders in round 2:
finger radius, infiltrative arc roughness, tumor-nucleus probability and area, breakaway tile
probability, lymphocyte-like size and solidity, cluster link distance, lymphocyte proximity,
immune-desert and immune-excluded shares, risk points and levels. A placeholder never looks
validated on the page.

## 4. Validation and honesty

- The tissue head's held-out numbers (`docs/encoders.md`, same protocol for every encoder: 8
  BCSS training slides, 1,052 tiles; 3 patient-disjoint held-out slides, 357 tiles; C = 0.1):
  accuracy 91.9%, balanced 91.7%; recall tumor 1.00, stroma 0.87, lymphocytes 0.90, necrosis
  0.82 (11 tiles), fat 1.00 (per class on the page). QuiltNet-B-32's head scored 87.7% (balanced
  85.4%) on the same tiles; the paired gain is +4.2 points (tile bootstrap interval +0.3 to
  +8.1, optimistic because tiles of one slide are correlated). Caveats: three held-out slides
  and five coarse classes are a small test; GigaPath-Flash's card does not say what its
  distillation saw, so whether TCGA-BRCA slides (the held-out ones included) were in its
  pretraining is unknown. `summary.json` says whether the patient's own slide was among the
  head's training or held-out slides.
- StarDist 2D_versatile_he is **pretrained, not validated on breast here**: nuclei counts are
  model inferences without a measured error. Every flag built on them says "weak until
  validated".
- The direction of invasion is labeled a hypothesis on the page and in the export.
- Two sections of one patient are compared side by side with "why a section is one section":
  each is one plane through the block; differences between sections are not change over time.
- "What this map cannot see" names, with the test that can: Nottingham grade, receptors,
  mutations, margins and specimen type, lymphovascular invasion, what happens next.

## 5. Timings (this PC's CPU, WSL, shared by six sessions)

The QuiltNet-B-32 runs of 2026-10-20, superseded by §9 (the three window sections' maps and
nuclei in this table came from the wrong place on the slide). Measured under the load average
quoted (`uptime`), 4 threads, `nice -n 10`:

| Slide | Tissue tiles | Scored | Mode | Embedding | Nuclei | Tumor mm² | Front mm | Infiltrative arcs | Breakaway in field | Islands | Unsure | Folder MB |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| TCGA-AN-A0AS-DX1 | 5,745 | 5,745 | whole slide | 34 min at 3.09 tiles/s (load average 10.9 8.6 7.1) | 400 tiles, 0.41 s each (load average 3.0 7.4 9.8) | 15.69 | 24.08 | 6/12 | 41 | 19 | 27% | 1.08 |
| TCGA-EW-A1J2-DX1 | 6,270 | 6,270 | whole slide | 8 min at 16.13 tiles/s (load average 2.5 7.0 9.6) | 400 tiles, 0.41 s each (load average 8.2 6.1 7.5) | 2.83 | 2.58 | 5/12 | 33 | 26 | 30% | 0.96 |
| TCGA-PL-A8LZ-DX1 | 1,378 | 1,378 | whole slide | 7 min at 3.98 tiles/s (load average 4.7 7.5 6.7) | 300 tiles, 1.2 s each (load average 11.5 9.5 6.9) | 0.08 | 0.22 | 0/2 | 32 | 3 | 30% | 0.33 |
| TCGA-PL-A8LZ-DX2 | 3,107 | 3,107 | whole slide | 10 min at 5.73 tiles/s (load average 12.2 13.0 11.2) | 0 tiles, ? s each () | 0.0 | 0.0 | 0/0 | None | 0 | 17% | 0.26 |
| TCGA-PL-A8LZ-DX3 | 4,146 | 4,146 | whole slide | 8 min at 10.22 tiles/s (load average 5.8 9.6 9.4) | 400 tiles, 0.31 s each (load average 4.6 7.5 8.6) | 0.75 | 1.23 | 0/10 | 147 | 14 | 54% | 0.66 |
| TCGA-D8-A1XF-DX1 | 12,164 | 8,866 | tumor-centred window | 9 min at 20.96 tiles/s (load average 3.1 4.9 7.9) | 400 tiles, 0.35 s each (load average 4.4 4.6 7.3) | 22.08 | 23.07 | 3/12 | 28 | 30 | 20% | 1.35 |
| TCGA-D8-A1XF-DX2 | 19,475 | 8,971 | tumor-centred window | 18 min at 17.31 tiles/s (load average 4.9 4.7 5.6) | 400 tiles, 0.33 s each (load average 4.0 4.3 5.3) | 13.94 | 6.72 | 1/12 | 64 | 40 | 23% | 1.22 |
| TCGA-BH-A0H5-DX1 | 19,635 | 8,923 | window centred on the tissue (coarse pass found no tumor) | 10 min at 19.69 tiles/s (load average 3.6 3.9 4.4) | not run (no front) | 0.0 | 0.0 | 0/0 | None | 0 | 10% | 0.69 |

The encoder ran between 3 and 21 tiles/s depending on the other sessions' load (the spike
measured ~10 tiles/s on a quiet machine with 8 threads); StarDist 0.3–1.2 s per 448 px tile at
4 threads. TCGA-PL-A8LZ-DX1's embedding time is taken from its first run's log (421 s). The WSL clock
jumped once during the first run (11:30 → 13:01), so `nuclei_meta.json` for TCGA-PL-A8LZ-DX1 was
corrected from the log. The three window slides scored a 9k-tile window centred on the largest tumor
piece of a coarse pass (every third tile); TCGA-BH-A0H5-DX1's coarse pass found no tumor, so its
window was centred on the tissue, nuclei were not run and the page says no front.

## 6. Known failures

The page lists them (`invasion.KNOWN_FAILURES`): normal breast and DCIS are not in the head;
tile borders cut nests into false buds; StarDist over-segments dense lymphocyte sheets and
misses pale nuclei; the lymphocyte-like rule is size and shape only; a scored window omits
tumor outside it; placeholder quality rules leave holes in the mask; normals are unstable on a
front thinner than two tiles. Seen on the scored slides (2026-10-27, GigaPath-Flash, §9):
TCGA-PL-A8LZ-DX1 (a 17 mm² section of collagen, fat and blood clot with little carcinoma) reads
several hundred collagen and loose-stroma tiles as carcinoma in small pieces, with most of the
map unsure; under QuiltNet-B-32 it read 81% necrosis. TCGA-EW-A1J2-DX1 keeps small fragments on
cautery-crushed margin tissue. Both pages carry the note in plain words.

## 7. The slide viewer

Round 3 (2026-10-21): the page draws the analysis on the patient's own section and moves the
way a pathologist moves through a slide, from the whole section to a region, a tile and its
nuclei. Code: `app/workbenches/slide_viewer.py` (download, overlay file, component call), the
component in `app/workbenches/slide_viewer_frontend/` (OpenSeadragon 6.1.1, BSD-3-Clause,
vendored with its license, and plain JavaScript that speaks Streamlit's component protocol; no
build step), the geometry in `muffle.workbench.viewer`, the tiles from `scripts/slide_pyramid.py`.

- **Tiles.** `slide_pyramid.py build` cuts a Deep Zoom (DZI) pyramid from the scan's own level
  nearest 1 µm per pixel (the 4× level of these 40× scans: 0.99–1.01 µm/px, so nothing is
  resampled beyond OpenSlide's own pyramid) and every halving below it: JPEG quality 80, tiles
  of 254 px with a 1 px overlap (256 px files); a bare-glass tile (grey-level standard deviation
  under 2.5; tissue, fat included, sits far above) is written flat in its mean colour. OpenSlide's
  level sizes are checked against the DZI convention (`viewer.dz_levels`) before a tile is
  written. `slide_pyramid.py manifest` records each section's size, µm per pixel, levels, tile
  count and zip SHA-256 in `app/workbenches/slides_results/pyramids.json`. No separate 2.5 µm/px
  overview image is made: the pyramid's own lower levels are the overview and the minimap.
- **Hosting.** One zip per section on the release
  [`slide-tiles-v1`](https://github.com/ps131-cell/muffle-plus-plus/releases/tag/slide-tiles-v1)
  of this repository, never in the repository itself. The first time a section's viewer opens,
  the app streams its zip to disk, checks the SHA-256, unzips it into `app/static/slides/<slide>/`
  (git-ignored; `app/static/.gitkeep` keeps the folder) and Streamlit serves it at
  `/app/static/…` (`enableStaticServing = true` in `.streamlit/config.toml`). The analysis layers
  are written next to the tiles as one JSON file named by its content hash, from the same
  `invasion.analyze_slide` result the page shows. Streamlit reads `enableStaticServing` when the
  server starts, so a server that has not restarted since (a hot-updated deployment) or runs
  without the config unpacks into the component's own folder
  (`slide_viewer_frontend/static/slides/`, git-ignored), which Streamlit serves with the
  component. A failed download is retried after 10 minutes.
  `MUFFLE_SLIDE_TILES` points at another folder of zips (`file:///…` for local work) or switches
  downloads off (`off`; the tests do).
- **Sizes** (built 2026-10-20 in WSL, three processes at `nice -n 10`, the load average at the
  start in brackets):

  | Section | Top level (px) | µm/px | Tiles (glass) | Zip MB | Built in |
  |---|---|---|---|---|---|
  | TCGA-AN-A0AS-DX1 | 14,756 × 10,985 | 0.992 | 3,494 (1,524) | 41.9 | 154 s (11.2) |
  | TCGA-EW-A1J2-DX1 | 29,446 × 21,801 | 0.994 | 13,346 (5,340) | 103.1 | 376 s (13.5) |
  | TCGA-PL-A8LZ-DX1 | 19,920 × 5,025 | 1.011 | 2,134 (1,126) | 13.2 | 111 s (10.9) |
  | TCGA-PL-A8LZ-DX2 | 19,920 × 7,251 | 1.010 | 3,115 (1,505) | 24.5 | 33 s (11.5) |
  | TCGA-PL-A8LZ-DX3 | 29,382 × 8,718 | 1.010 | 5,483 (3,541) | 36.5 | 207 s (11.8) |
  | TCGA-D8-A1XF-DX1 | 19,516 × 19,891 | 0.987 | 8,190 (2,212) | 109.0 | 383 s (11.1) |
  | TCGA-D8-A1XF-DX2 | 23,904 × 21,747 | 1.011 | 10,952 (2,682) | 157.3 | 305 s (4.3) |
  | TCGA-BH-A0H5-DX1 | 34,565 × 22,194 | 1.002 | 16,146 (3,623) | 175.4 | 309 s (3.8) |

  661 MB in all. Four sections fit the 10–40 MB first aimed for; the four with 100–245 mm² of
  tissue do not, because H&E at 1 µm/px costs about 20 KB per 256 px tile at quality 80
  (measured on 60 tissue tiles of TCGA-D8-A1XF-DX1: 13.4 KB at quality 60, 15.9 at 70, 19.9 at
  80; WebP saved 9%). Only the 2 µm/px level would bring them under 40 MB, and it no longer
  shows nuclei, so the sections stay at 1 µm/px and each is fetched only when its viewer opens.
- **What is drawn**, in the pyramid's pixels (a grid tile of 112 µm is 111–114 pyramid px):
  tiles coloured by tissue class, certainty, quality control, zones, lymphocyte-like nuclei or
  risk level (translucent, opacity adjustable, or off to see the tissue alone); the front line
  (the sides of main-tumor tiles that face non-tumor tissue); the arcs as arrows (length by
  push, red infiltrative, dark pushing); breakaway candidates and the dashed 0.785 mm² counting
  field; island and risk-region outlines; pointers T1…Tn; the scored window, dashed, with
  "not analysed" outside it; and, from about 0.5 screen pixels per µm, every nucleus StarDist
  found on the counted tiles as a circle of its own area (not its outline: the pipeline keeps
  centroid, area and solidity, not the polygon), coloured by the page's rules: lymphocyte-like,
  tumor candidate, member of a breakaway cluster, other. A scale bar, a minimap and a legend that
  carries the evidence labels (classes are model inferences; the front, zones, arcs, islands,
  field and points are rules on them; the arrows are a hypothesis about this section; the nuclei
  are pretrained StarDist, not validated on breast here).
- **Interaction.** Hover shows a tile's class and top score, certainty, zone and distance to the
  front, nuclei counts and risk points, or the nucleus, arrow or pointer under the cursor. A
  click opens the tile in the Spot panel. "Jump to" (pointers, risk regions, arcs, the counting
  field, islands) and the n / p keys fly the viewer and move the Spot panel; the risk cards and
  the Spot panel's own pick fly the viewer. The sections of one patient (cases 730 and 1043)
  open side by side with zoom linked by physical size (the same µm per screen pixel in each) and
  pan by the same distance; the page says whether their scales match (TCGA-D8-A1XF-DX1 and DX2
  differ by 2.4%) and that the sections are not registered, so linked pan does not line up
  anatomy.
- **Fallback.** Without the pyramid (offline, download failed, static serving off, or a browser
  that cannot load the tiles, which the viewer reports back), the page says why and shows the
  tile map and the picture of the scored region.
- **Adding a section.** Score it (`slide_pipeline.py run`, then `cells` if needed and `index`),
  then `slide_pyramid.py build --slide X.svs --out OUT`, `slide_pyramid.py manifest --out OUT
  --into app/workbenches/slides_results/pyramids.json`, and `gh release upload slide-tiles-v1
  OUT/<slide>.zip` (`--clobber` for a rebuilt section; a server that already unzipped the old
  one keeps it until it restarts).

## 8. Second opinion on lymphocytes (2026-10-21)

The tissue head's weakest class was lymphocytes (held-out recall 0.74 on QuiltNet-B-32; 0.90 on
GigaPath-Flash since 2026-10-27), so the WSInfer TIL model
(`kaczmarj/pancancer-lymphocytes-inceptionv4.tcga`; Abousamra et al., *Front Oncol* 2022,
[10.3389/fonc.2021.806603](https://doi.org/10.3389/fonc.2021.806603); CC BY 4.0; TorchScript,
`torch.jit.load`) gives a second reading of the same tiles: the centre 50 µm (100 px at 0.5
µm/px) of a tile, resized to 299 px, normalized with mean and std 'half' (the better of the two
candidate normalizations on the held-out slides; 'imagenet' gave AUROC 0.945),
softmax over its two classes.

- **Measured** (`scripts/slide_pipeline.py til-measure`, on the spike's BCSS tiles): on the
  head's 3 held-out, patient-disjoint slides (TCGA-C8-A26X-DX1, TCGA-C8-A26Y-DX1, TCGA-EW-A1OV-DX1;
  357 usable labelled tiles) lymphocytes versus the rest **AUROC
  0.955**; mean probability per BCSS class on those tiles: tumor 0.04, stroma 0.39, lymphocytes 0.97, necrosis 0.08, fat 0.08. Cutoff
  **0.667**, calibrated on the 8 training slides (1052 tiles, Youden's
  J; training-slide AUROC 0.971) and applied unchanged: held-out recall
  97%, specificity 79%, accuracy
  83%. Caveat: the model was trained on TCGA slides of 23 cancer types, so the
  held-out BCSS slides (all TCGA-BRCA) may have been in its training set; the AUROC is an upper
  bound, not an independent validation.
- **On a patient's section** (`slide_pipeline.py til`): up to 1,500 usable front-band tiles
  (nearest the front first) then peritumoral tiles are scored and written to `til.json` (tile id
  → probability, the cutoff and its source, the held-out numbers); nothing else leaves the
  machine. `invasion.til_disagreement` compares the head's label (lymphocytes or not) with the
  second model at the cutoff on the scored tiles: counts, share, Cohen's kappa, and the
  disagreeing tiles, which get a "models disagree" pointer at their densest spot in the look-here
  queue, a map layer ("lymphocytes (second model)", disagreement in orange and red), a column in
  the stromal-lymphocytes-by-zone table, a search ("where do the models disagree"), a row in the
  two-section comparison and an entry in the export. Every number is a model inference; a
  disagreement is a place to look, never a verdict on which model is right.
- **Per section** (2026-10-21; a disagreement is a place to look, not a verdict; kappa near zero means the two readings barely overlap, and most disagreements are the second model calling lymphocytes where the head reads stroma, consistent with its 0.39 mean on stroma tiles):

| Section | Tiles scored | Per tile (2 threads) | Front band: head lymphocyte share | Front band: second model | Disagree | Head only / model only | Kappa |
|---|---|---|---|---|---|---|---|
| TCGA-AN-A0AS-DX1 | 1500 | 0.34 s (load average 4.5 7.7 8.1) | 0% | 3% | 43 (3%) | 0 / 43 | 0.0 |
| TCGA-BH-A0H5-DX1 | 0 | 0.0 s (load average 6.4 5.0 6.1) | — | — | 0 (—) | 0 / 0 | — |
| TCGA-D8-A1XF-DX1 | 1500 | 0.35 s (load average 3.8 6.1 7.2) | 2% | 6% | 114 (8%) | 28 / 86 | -0.029 |
| TCGA-D8-A1XF-DX2 | 1500 | 0.29 s (load average 6.8 5.0 6.2) | 0% | 4% | 60 (4%) | 12 / 48 | -0.013 |
| TCGA-EW-A1J2-DX1 | 771 | 0.27 s (load average 7.1 6.4 7.4) | 0% | 2% | 8 (1%) | 0 / 8 | 0.0 |
| TCGA-PL-A8LZ-DX1 | 368 | 0.22 s (load average 3.6 4.4 5.8) | 0% | 0% | 0 (0%) | 0 / 0 | — |
| TCGA-PL-A8LZ-DX2 | 0 | 0.0 s (load average 3.3 4.3 5.8) | — | — | 0 (—) | 0 / 0 | — |
| TCGA-PL-A8LZ-DX3 | 899 | 0.23 s (load average 3.0 3.6 5.2) | 0% | 2% | 68 (8%) | 0 / 68 | 0.026 |

- Not done: the WSInfer tumor model (AUROC 0.921, balanced accuracy 0.788 at its cutoff in the
  screening check) is not wired in.

## 9. Re-score with GigaPath-Flash (2026-10-27)

**What changed.** Every section and the example region now come from GigaPath-Flash embeddings
(`prov-gigapath/prov-gigapath-flash`: Prov-GigaPath's tile encoder distilled to a ViT-S/16,
384-d; Apache-2.0; gated by a contact-information click-through the team's account has passed;
its card puts clinical and deployed use out of scope, so it runs offline and the hosted app reads
precomputed results). The head is the comparison's (`docs/encoders.md`): logistic regression,
C = 0.1, the same 5 BCSS classes, the same 224 px tiles at 0.5 µm/px, the same 8 training slides
(1,052 tiles) and 3 patient-disjoint held-out slides (357 tiles): accuracy **0.919** (balanced
0.917) against QuiltNet-B-32's 0.877 (0.854). Whether TCGA-BRCA slides were among the
distillation's pretraining data is not stated on its card. Method version 0.3 in `summary.json`
(the geometry rules are unchanged).

**A misregistration fixed.** On the three sections scored through a window (TCGA-D8-A1XF-DX1
and -DX2, TCGA-BH-A0H5-DX1) the pipeline embedded each tile, and StarDist counted its nuclei,
from the pixels at the window-relative position, not at the window's place on the slide (the
thumbnail, crops and TIL scores were right). On `main` since 2026-10-20 (#87); the viewer has
drawn those maps over the real tissue since 2026-10-21. Recomputing the cached texture measures
at both positions matched the wrong one on 18 of 18 sampled tiles. Their "before" numbers below
are therefore from the wrong tissue (case 563's mostly from glass, hence "no tumor found"), and
their nuclei were counted again at the right place.

**A new quality rule: "unlike training tissue", not scored.** On TCGA-EW-A1J2-DX1 the GigaPath
head read 808 tiles of cautery-crushed, muscle-like margin tissue as invasive carcinoma (mean
P 0.76; QuiltNet called them necrosis; tile contact sheets checked by eye); neither head has a
class for it, and the main tumor, front, arcs and risk regions sat on it. A tile is now excluded
like glass or pen ink when its embedding's mean cosine distance to its 5 nearest of the head's
1,052 training tiles exceeds **0.507**: the 99th percentile of the same distance for each
training slide against the other seven (leave one slide out; `slide_pipeline.py
novelty-calibrate`). It flags 1 of the 357 held-out tiles (0.3%, a necrosis tile) and 1 of the
example region's 234. On TCGA-EW-A1J2-DX1 it moves the main tumor back onto carcinoma but catches
only about two thirds of that tissue: small fragments on it may still read as carcinoma, which
the section's page says (a reviewer's note in its `summary.json`, `known_failures`).

**Nuclei and the second lymphocyte model, topped up.** The new maps move the front, so cached
StarDist counts and TIL scores were kept where they still lie on a usable tile of the new front
band or peritumoral zone, and the tiles a fresh run would pick on the new map (up to 400 for
StarDist; for the TIL model 1,500 on the first three sections, 600 nearest the front on the
other five, to make the day's deadline) were scored where they had no result (`slide_pipeline.py
nuclei-topup`, `til`); `run` then wrote each folder from the union. The page's coverage line
under "Stromal lymphocytes by zone" gives the counted share per zone.

**Before and after** (before = QuiltNet-B-32 as shipped; after = GigaPath-Flash with the rule
and the top-ups; numbers as the page computes them, the TIL comparison at the calibrated cutoff
0.667):

| Section | Tumor mm² | Main piece mm² | Pieces | Front mm | Infiltrative arcs | Breakaway in field | Islands | Immune pattern | Unsure | TIL disagree | Not scored: unlike training |
|---|---|---|---|---|---|---|---|---|---|---|---|
| TCGA-AN-A0AS-DX1 | 15.69 → 23.39 | 9.61 → 18.31 | 20 → 26 | 24.08 → 39.87 | 6/12 → 2/11 | 41 → 57 | 19 → 25 | desert → desert | 27% → 28% | 43/1500 (3%) → 52/1980 (3%) | 54 |
| TCGA-EW-A1J2-DX1 | 2.83 → 12.44 | 0.78 → 2.58 | 27 → 166 | 2.58 → 6.83 | 5/12 → 7/12 | 33 → 88 | 26 → 168 | desert (no core: front band only) → desert (no core: front band only) | 30% → 43% | 8/771 (1%) → 84/1100 (8%) | 717 |
| TCGA-D8-A1XF-DX1 | 22.08 → 45.11 | 12.63 → 21.11 | 31 → 64 | 23.07 → 47.04 | 3/12 → 2/12 | 28 → — | 30 → 65 | desert → desert | 20% → 15% | 114/1500 (8%) → 72/2432 (3%) | 202 |
| TCGA-D8-A1XF-DX2 | 13.94 → 33.12 | 2.95 → 14.95 | 41 → 39 | 6.72 → 31.36 | 1/12 → 6/12 | 64 → 31 | 40 → 38 | desert (no core: front band only) → desert | 23% → 15% | 60/1500 (4%) → 68/1786 (4%) | 265 |
| TCGA-PL-A8LZ-DX1 | 0.08 → 5.23 | 0.03 → 0.88 | 4 → 139 | 0.22 → 4.48 | 0/2 → 0/11 | 32 → 23 | 3 → 139 | desert (no core: front band only) → desert (no core: front band only) | 30% → 60% | 0/368 (0%) → 0/242 (0%) | 762 |
| TCGA-PL-A8LZ-DX2 | 0.0 → 3.89 | 0.0 → 0.15 | 0 → 172 | 0.0 → 1.01 | 0/0 → 0/6 | — → 47 | 0 → 171 | no front: not assessed → desert (no core: front band only) | 17% → 71% | 0/0 → 1/373 (0%) | 1979 |
| TCGA-PL-A8LZ-DX3 | 0.75 → 19.03 | 0.19 → 8.97 | 15 → 38 | 1.23 → 22.51 | 0/10 → 6/11 | 147 → 82 | 14 → 37 | desert (no core: front band only) → desert | 54% → 65% | 68/899 (8%) → 103/1070 (10%) | 295 |
| TCGA-BH-A0H5-DX1 | 0.0 → 3.05 | 0.0 → 0.55 | 0 → 27 | 0.0 → 3.36 | 0/0 → 6/10 | — → 77 | 0 → 26 | no front: not assessed → desert (no core: front band only) | 10% → 25% | 0/0 → 145/600 (24%) | 15 |

**Coverage after the top-ups** (usable tiles of each zone with nuclei counted or a second-model
score; before → after):

| Section | Front tiles | Nuclei counted: front band | Nuclei counted: peritumoral | Second model scored: front band | Second model scored: peritumoral |
|---|---|---|---|---|---|
| TCGA-AN-A0AS-DX1 | 215 → 356 | 400/1507 (27%) → 686/2387 (29%) | 0/1735 (0%) → 0/1754 (0%) | 1500/1507 (100%) → 1962/2387 (82%) | 0/1735 (0%) → 18/1754 (1%) |
| TCGA-EW-A1J2-DX1 | 23 → 61 | 189/189 (100%) → 400/429 (93%) | 211/582 (36%) → 51/671 (8%) | 189/189 (100%) → 429/429 (100%) | 582/582 (100%) → 671/671 (100%) |
| TCGA-D8-A1XF-DX1 | 206 → 420 | 400/1631 (25%) → 400/3056 (13%) | 0/2104 (0%) → 0/3305 (0%) | 1500/1631 (92%) → 1744/3056 (57%) | 0/2104 (0%) → 688/3305 (21%) |
| TCGA-D8-A1XF-DX2 | 60 → 280 | 400/572 (70%) → 400/1916 (21%) | 0/1671 (0%) → 0/1294 (0%) | 572/572 (100%) → 1271/1916 (66%) | 928/1671 (56%) → 515/1294 (40%) |
| TCGA-PL-A8LZ-DX1 | 2 → 40 | 44/44 (100%) → 105/105 (100%) | 324/324 (100%) → 137/137 (100%) | 44/44 (100%) → 105/105 (100%) | 324/324 (100%) → 137/137 (100%) |
| TCGA-PL-A8LZ-DX2 | 0 → 9 | — → 77/77 (100%) | — → 296/296 (100%) | — → 77/77 (100%) | — → 296/296 (100%) |
| TCGA-PL-A8LZ-DX3 | 11 → 201 | 125/125 (100%) → 652/1168 (56%) | 275/774 (36%) → 2/707 (0%) | 125/125 (100%) → 962/1168 (82%) | 774/774 (100%) → 108/707 (15%) |
| TCGA-BH-A0H5-DX1 | 0 → 30 | — → 235/235 (100%) | — → 165/1249 (13%) | — → 235/235 (100%) | — → 365/1249 (29%) |

**Checked by eye** (maps rendered with `invasion.map_png` and contact sheets of eight random
224 px tiles per disagreement between the two heads; not a pathologist's review):
- *TCGA-AN-A0AS-DX1 (case 299):* the 537 tiles that went from stroma to carcinoma are carcinoma
  around fat vacuoles that QuiltNet missed; the main tumor now follows the whole dense cellular
  band of the section as one piece (9.6 → 18.3 mm²). The 174 tiles that went from fat to
  carcinoma are loose collagen at low confidence (mostly unsure). Better.
- *TCGA-EW-A1J2-DX1 (case 926):* better on carcinoma (486 tiles QuiltNet called stroma), worse
  on cautery-crushed, muscle-like margin tissue (above). With the rule, the main tumor and its
  front sit on the central carcinoma; small fragments on margin tissue remain and the page says
  so. Usable with that warning.
- *TCGA-D8-A1XF-DX1 (case 730):* the map now lines up with the section's own picture (fat and
  glass blank on the left, the tumor nests where the H&E shows purple lobules). The second
  lymphocyte model was always scored at the right place, so its agreement with the head is a
  check of the fix: Cohen's kappa rose from −0.03 (map from the wrong tissue) to 0.55.
- *TCGA-D8-A1XF-DX2 (case 730):* at the right place now; main tumor 2.95 → 14.95 mm² with a
  front of 31 mm; TIL agreement unchanged (4% of scored tiles disagree).
- *TCGA-BH-A0H5-DX1 (case 563):* the old map came mostly from glass ("no tumor found"); at the
  right place the head finds carcinoma nests (276 tiles), lymphocyte-rich stroma and stroma, and
  a front of 3.4 mm. The window is still the one the QuiltNet coarse pass centred on the tissue,
  so tumor outside it is not in the map (the page says how much was skipped).
- *TCGA-PL-A8LZ-DX3 (case 1043):* the 1,594 tiles that went from necrosis to carcinoma are
  sheets of high-grade, discohesive carcinoma that QuiltNet called necrosis; a main tumor of
  9.0 mm² and a 22.5 mm front. Better.
- *TCGA-PL-A8LZ-DX1 and -DX2 (case 1043):* mostly collagen, fat and blood clot with little
  carcinoma. The rule sets aside 762 and 1,979 tiles (clot and debris), but several hundred
  collagen and clot tiles still read as carcinoma in small pieces (139 and 172), with 60% and
  71% of the map unsure. QuiltNet read them as necrosis (DX1) or found no front (DX2). Worse as
  maps; both pages say in plain words not to rely on their tumor pieces, and point to DX3.

**Timings** (this PC's CPU in WSL, `nice -n 10`, 4 threads for the encoder and 2 for StarDist
and the TIL model; up to four of our processes ran at once beside other sessions; the 1-minute
load average at the end of each embedding in brackets): GigaPath-Flash embedded 7.44 tiles/s on
TCGA-AN-A0AS-DX1 (7.9), 7.88 on -EW-A1J2-DX1 (8.7), 3.37 on -D8-A1XF-DX1 (11.1, timed before
the PC slept), 1.86 on -D8-A1XF-DX2 (9.6), 3.94 on -PL-A8LZ-DX1 (11.3), 5.95 on -DX2 (7.6),
2.65 on -DX3 (12.1) and 1.93 on -BH-A0H5-DX1 (10.2): 47,406 tiles in all. The PC slept from about
01:02 to 11:35 and again from 13:34 to 13:48 on Oct 27 (WSL's clock jumped on waking), and the
host CPU sat at 100% most of the afternoon with WSL getting about 2.7 of 8 cores; two embedding
timings and one StarDist timing were taken from the log's awake stretches (their
`summary.json` says so). StarDist top-ups ran at 0.34–2.84 s per tile, the TIL model at 0.2–1.33
s per tile. The TIL top-up scored up to 1,500 tiles per section on the first three sections and
600 on the other five, to make the day's deadline; the coverage table shows what that left.

## 10. The slide map, from the team's Colon Tumor Front Analyzer (2026-10-27)

The page's first picture is now the analyzer's slide map, its code copied and adapted to breast
rather than rebuilt (the user's request, `docs/decisions.md` 2026-10-27): the section's own
thumbnail underneath, a see-through coloured layer on top (opacity slider in the chart, 45% to
start), seven views switched by buttons in the chart (Tissue, Zones, Risk, Flags, Certainty,
Quality, Immune), a fixed-size hover box on every square, a click that opens the square in the
Spot panel, scroll to zoom, drag to move, double-click or **Whole section** to fit, the
look-here pointers T1…Tn on the map and Q1…Q5 for a search. The plotly chart keeps its view
buttons and slider in the browser (no rerun, so the zoom stays); each view is a PNG of one pixel
per tile that the browser draws unsmoothed, so a square stays a crisp 112 µm square at any zoom.
The OpenSeadragon viewer (§7) stays, one click away (**Map | Slide viewer**, and **Zoom to the
cells** in the Spot panel), and now downloads a section's pyramid only when it is opened.

Modules (each says in its first line which analyzer file it adapts): `src/muffle/workbench/
tile_map.py` (from its `app/tile_map.py`), `slide_search.py` (`app/search.py`),
`slide_export.py` (`app/export.py`); the map's page code in `app/workbenches/slides.py` (from
its `app/page_slide.py` map area and Spot tab, `app/report.py`'s per-square explanation and the
class highlight of its earlier `app/view_slide.py`). Colours: the analyzer's figure palette
(its `src/viz.py`) for the classes both heads share, now also on the viewer and in the exports.
Nothing colon-specific is used: no colon-trained head, no cutoff value set on colon (the
"unsure here" cutoff stays this workbench's placeholder 0.8, not the analyzer's calibrated 0.9),
no colon class; mix-ups between two classes come from the breast head's own held-out confusion
matrix, not the analyzer's hand-written colon list.

What every analyzer feature became here (the analyzer's `app/README.md` on its latest app
branch, its code, and its earlier app for the five-view map and the clickable key):

| Analyzer feature | In MuFFLe++ |
|---|---|
| Scan underneath, see-through coloured layer, opacity slider in the chart | **Ported** (`tile_map.figure`, `scan_jpeg`, `overlay_png`), light page |
| Empty glass tinted grey around the tissue | **Ported** (`_scan`); a window's part beyond the slide's edge is painted as glass too |
| Tissue view | **Ported** for the head's five BCSS classes (invasive carcinoma, stroma, lymphocytes, necrosis or debris, fat) |
| Zones & front: core, front band, peritumoral, other tissue; the front in black; blue arrows on infiltrative arcs; rings on satellites; the main direction of invasion | **Ported** on this workbench's zones, arcs and islands (`invasion.py`); arrows and the main direction are a hypothesis in the hover text |
| Risk view (points, white to dark red) | **Ported** as Risk levels 1–3 in the same reds, risk regions R1… marked; every point value stays a placeholder |
| Flags view (marker shapes per flag, unsure areas circled) | **Ported** with breast's flags: breakaway candidates (star), the models' disagreement on lymphocytes (diamond), satellite islands (ring), the three largest unsure areas (grey ring, its uncertainty regions), the counting field (dashed circle) |
| Certainty view (unsure squares in amber) | **Ported**, on this workbench's placeholder cutoff |
| — | **Added**: Quality view (glass, pen ink, blur, unlike training tissue) and Immune view (lymphocyte-like nuclei per counted tile) |
| Clickable key that highlights one class | **Ported** as "Highlight a class" above the map (its earlier app's pills); other classes fade to 12% |
| Fixed-size hover box on every square (grouped hover layers) | **Ported**: class with its 3×3 mean, certainty, zone, risk points (placeholder), tile, "model inference" |
| Click a square to open it in the panel | **Ported**: opens it in the Spot panel below; plotly marks the square without redrawing |
| Scroll to zoom, drag to move, double-click or fit to reset, zoom limits | **Ported** ("Whole section") |
| Pointers on the map (search S1–S5, worklist F/R/U…) | **Ported** with this page's scheme: T1…Tn (the look-here queue the text and Spot panel share) and Q1…Q5 for a search (S1… already names the satellite islands here) |
| Search within a slide: known words to classes, zones and flag phrases, "what matched", spots to zoom to, colour by match, clear | **Ported** (`slide_search.py`) with breast words, flags, pointer names and the direction of invasion; things a tile map cannot see (grade, receptors, margins, vessels, single cells) get "this map can't see that". **Changed**: a match is the class probability or flag itself, coloured from 15%, not scaled to the section's best (the analyzer's scaling showed a "100%" necrosis spot on a section without necrosis, and its faint colouring of every tile hid the matches) |
| Live CONCH text search | **Not applicable**: needs CONCH (non-commercial, local only here) and per-slide CONCH embeddings, which the app does not ship |
| Spot: tile picture, where it sits, class and score, why, certainty and why, zone and distance to the front, the second model, what to check by eye, all scores | **Already there** (crop with nuclei, position, zone, distance, nuclei, risk, what to check, review mark) and **ported**: where it sits, why (closest and next class, neighbours, what the class looks like), how sure and why, the check-by-eye prompt when unsure, the second model's answer (the WSInfer TIL model, not MUSK), all scores as bars |
| Known mix-ups between two classes | **Adapted**: measured on the breast head's held-out tiles (its confusion matrix) |
| Report tab (high-risk features, findings) and Details (every number) | **Already there**: the overview paragraph, metrics and look-here queue; the Details sections |
| Check tab: the worklist with reviewed ticks | **Already there**: the look-here queue, review marks and pins (kept in the browser session and the exports; the Feedback ledger collects them) |
| Notes per slide, added to the report | **Ported**: "Your notes on this section" (session), in the slide report and the JSON |
| Map picture (PNG: title, map, colour key, footer) per view | **Ported** (`slide_export.map_png`; a view picker in "Download the map (PNG)") |
| PDF report | **Adapted** to Markdown like the file's "Export this report (Markdown)": `slide_export.report_markdown` (what was scored, tissue mix, key findings with evidence labels, the pointers with your marks, notes, arcs, islands, risk regions, every cutoff and its source, known failures); a PDF would add a dependency |
| Slide list with hover stats; rename, duplicate, hide | **Already there** in shape (the Patients page; the Tests launcher's tiles with look-here counts); rename, duplicate and hide **not applicable** (a file's tests are records) |
| Model-results page | **Already there** (Methods and validation) |
| Back / forward | **Already there** (the address carries the file, view and test) |
| Plain-language summary from an LLM (NCSA Lumen) | **Not applicable**: the slide page sends nothing to an LLM; the case agent (Nemotron) has its own budget-capped path |
| Background warm-up of every slide | **Left out**: each section is read once per process and cached; the hosted app's 1 GB favours loading on demand |
| Colon analysis: depth hint (pT from muscle and fat), mucin pools, outer edge, lymph nodes on the slide, perineural / venous / lymphatic phrase flags, stroma maturity, adenoma remnants, MUSK blood check | **Not applicable to breast**: colon wall anatomy and CONCH phrase scores on colon; breast's own analysis (front, arcs, islands, breakaway, immune pattern, tumor–stroma ratio, risk) has been in `invasion.py` since Oct 20 |
| Colon-trained heads (eight colon classes, immune, structures) and their cutoffs | **Not used**: colon classes; the breast head is trained here on BCSS |
| Dark glass and the near-black theme of its first app | **Not applicable**: this app is light-only (its latest app is light too) |

Memory and size: plotly 7.1.0 is a new dependency (`requirements.txt`, `app/requirements.txt`).
Server memory (RSS) while headless Chromium opened SYNTHETIC-001 and every case's slide page in
turn (299, 926, 730, 563, 1043, 299 again; release bundle, tile downloads off, WSL): **main
435 → 554 MB, this map 437 → 556 MB**, so the hosted app's 1 GB holds as before. A section's
first map costs about 1 s on this PC (analysis 0.3–0.7 s, scan 0.2 s, views 0.1–0.2 s, figure
0.2–0.5 s), and the figure is kept for reruns that do not change it. A chart sends 0.36–0.47 MB:
the scan (80–125 kB JPEG), seven views of 10–30 kB in all, the hover layers.

## 11. What is left

- A pathologist's review of one scored slide, and a measured error for StarDist on breast
  tiles (a few hand-counted tiles would do).
- Nucleus outlines (a re-run that keeps StarDist's polygons) and registration of a patient's
  sections, so side by side could line up anatomy.
- The gated encoders not yet measured (Path Foundation, H-optimus-0, Virchow) and Midnight-12k
  on a GPU (`docs/encoders.md`); a re-score with any of them is the §9 procedure.
- Vessels, DCIS and normal breast as classes (more labeled tiles); blood, folds and stain
  variation in quality control.
- Margins only where the specimen type allows; comparison across time needs a second specimen.

## 12. Tissue by zone and the stroma hypothesis (2026-10-28)

- **Tissue by zone** [model inference]: each zone's share of usable tiles by the head's class
  (invasive carcinoma, stroma, lymphocytes, necrosis or debris, fat; other = normal breast or
  in-situ carcinoma), in the core, the front band and the peritumoral zone
  (`muffle.workbench.invasion.tissue_by_zone`). A description of the section with no cutoff;
  precedent for reading compartments separately on H&E: Mittal et al. 2019 (*Front Bioeng
  Biotechnol* 7:246, [10.3389/fbioe.2019.00246](https://doi.org/10.3389/fbioe.2019.00246)),
  whose clustering ("inertia") measure is not used.
- **Beside the tumor–stroma ratio** [hypothesis]: in one 42-tumor, single-centre infrared study
  the collagen at tumor borders carried the ECM3 stromal signature and ECM3 grade III tumors
  fared worst (Tiwari et al. 2020, *Sci Rep* 10:5442,
  [10.1038/s41598-020-62403-2](https://doi.org/10.1038/s41598-020-62403-2); AUC 0.87, not
  validated externally). Here only the H&E stroma share is measured, not the collagen's
  chemistry; the omics workbench shows the ECM3 genes where RNA was sequenced (`docs/omics.md`).
- Both are in the slide report export. Infrared stromal subtypes and an infrared ECM3 score are
  planned only (no infrared data in this project; Methods and validation).

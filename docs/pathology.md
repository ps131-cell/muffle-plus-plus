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
| 563 | TCGA-BH-A0H5 | DX1 | saved case note | shipped (no tumor found: the page says no front) |

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
3. **Embedding and classes.** QuiltNet-B-32 (CLIP ViT-B/32, MIT, ungated) on CPU, batches of
   32 streamed from the slide, no tile stack in memory; the round-1 BCSS head (logistic
   regression; 5 classes: invasive carcinoma, stroma, lymphocytes, necrosis, fat) gives the
   probabilities; the round-1 quality rules (glass, pen ink, blur; placeholders) exclude tiles.
   A re-run with another encoder (`--model`) changes only `encoder` in `summary.json` and the
   probabilities; grid, window and nuclei are cached and reused.
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
    no nucleus masks, no tile stack; under 3 MB per section (the largest, TCGA-D8-A1XF-DX1,
    1.8 MB).

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

- The tissue head keeps round 1's held-out numbers (3 patient-disjoint BCSS slides, 357 tiles,
  accuracy 87.7%, balanced 85.4%; per class on the page). `summary.json` says whether the
  patient's own slide was among the head's training or held-out slides.
- StarDist 2D_versatile_he is **pretrained, not validated on breast here**: nuclei counts are
  model inferences without a measured error. Every flag built on them says "weak until
  validated".
- The direction of invasion is labeled a hypothesis on the page and in the export.
- Two sections of one patient are compared side by side with "why a section is one section":
  each is one plane through the block; differences between sections are not change over time.
- "What this map cannot see" names, with the test that can: Nottingham grade, receptors,
  mutations, margins and specimen type, lymphovascular invasion, what happens next.

## 5. Timings (this PC's CPU, WSL, shared by six sessions)

Measured under the load average quoted (`uptime`), 4 threads, `nice -n 10`:

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
front thinner than two tiles. Seen on the scored slides: TCGA-PL-A8LZ-DX1 (a 17 mm² section)
reads 81% necrosis-or-debris with almost no invasive carcinoma, and its "breakaway candidates"
sit on tissue the head could not place: a case where the map should not be trusted and says so
through its unsure share and queue.

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

## 8. What is left

- A pathologist's review of one scored slide, and a measured error for StarDist on breast
  tiles (a few hand-counted tiles would do).
- Nucleus outlines (a re-run that keeps StarDist's polygons) and registration of a patient's
  sections, so side by side could line up anatomy.
- A stronger encoder behind `HF_TOKEN` (another session owns `slide_spike.ENCODERS`); the
  result files are designed so only `encoder` changes.
- Vessels, DCIS and normal breast as classes (more labeled tiles); blood, folds and stain
  variation in quality control.
- Margins only where the specimen type allows; comparison across time needs a second specimen.

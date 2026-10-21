# Workbench design: depth and quality of life per test type

How each workbench in [`WORKSPACE.md`](WORKSPACE.md) reaches the depth of the team's Colon Tumor
Front Analyzer, and what a pathologist can do in it. Written 2026-10-19 from that analyzer's
working grammar and the team's plan. Each item carries a tag:

- **now**: buildable on the data the app already has (the synthetic record, the TCGA cases,
  CIViC, the risk and landmark models) before the Oct 28 freeze;
- **data**: needs data the app does not hold yet (a CBC, a second sequencing sample, images);
- **model**: needs a model or a validation that does not exist yet;
- **roadmap**: after the hackathon.

Nothing here changes the science rules: observed, model inference and hypothesis stay apart;
every threshold names its source; a placeholder never looks validated; treatment content is
evidence for clinician review, never a recommendation; what a test cannot show is said, not
hidden.

## 1. The shared grammar

What made the slide analyzer usable is not any single measurement but a way of presenting every
measurement. Every workbench follows it.

1. **Three questions on every screen.** What was observed? What does a model or rule infer, with
   how much trust? What should I check by eye? The third is a queue ("look here"), never a
   verdict.
2. **Four levels.** Overview (one paragraph and the queue) → region, period or variant → single
   value, tile or read → raw data. Every level opens from the one above with one click.
3. **One finding card, everywhere.** Value, unit, method (rule or model, version), threshold and
   its source tag (guideline, literature, calibrated, placeholder), trust (strong or weak), *why*
   (the measurements behind it), *what to check by eye*, *what this test cannot see*, status chip
   (implemented, experimentally validated, planned). Skipped analyses appear too, with the reason
   ("no reference interval for CEA in this record").
4. **Hover, click, more info.** Hover shows brief stats. Click opens the **Spot panel** for that
   element: the full story of one value, variant, tile or lesion. "More info" opens the test-level
   card (method, validation, known failures).
5. **Pointers.** Numbered markers (L1…Ln on a chart, V1…Vn in a table, T1…Tn on a map) shared by
   the text, the queue and the figure, so a sentence is one click from its evidence. The slide
   analyzer's S1–S5 search pointers and flag pointers are the model.
6. **Review tools.** Search inside the test in plain words; pins and bookmarks; **agree /
   disagree / needs a second look** marks on every finding, with reviewer initials and time
   (stored locally, exported with the report); saved views; exports (a one-page report with the
   figures, the numbers, their sources, every placeholder listed, model versions and the reviewer
   marks; plus CSV and JSON); back and forward between screens; keyboard triage (j/k next and
   previous queue item, p pin, r mark reviewed, u open the unsure list).
7. **Honest answers.** A search the test cannot answer gets "this test can't see that, X could"
   (the analyzer's "single-cell searches get an honest answer"). Placeholders render in a dashed
   style with a legend always visible. The model and validation card is one click away and lists
   known failures, like the analyzer's "what didn't work" page.
8. **Change over time.** "Since the last version" on every workbench where it is valid; never a
   comparison across an assay or protocol change without saying so.

## 2. Patient file and report

The report is where the workbenches meet. Beyond what the shell already shows (summary, SOS
tile, observed / inference / hypothesis blocks, risk, what changed):

- **SOS ordering by trust × consequence** [now]: an observed progression on imaging outranks a
  placeholder-rule marker rise; each alert says since when, which rule, the threshold's source,
  its trust, and has two buttons, "open the test" (the pointer lands on the evidence) and "mark
  reviewed".
- **Version diff** [now]: any two versions side by side in the three evidence columns, with added,
  removed and changed items highlighted and the "what changed and why" attribution underneath.
- **Evidence chain** [now]: every sentence of the case note links to the tool output behind it
  (the grounding trace rendered as a chain: sentence → tool → measurement → raw value), with the
  trust at each step. This is the analyzer's "why" made navigable.
- **Discrepancy queue** [now]: tests that disagree: a marker rising while imaging reads stable; the
  12-month risk up while labs fall; two notes that differ. Each item names both sources and what
  would settle it.
- **What would reduce uncertainty** [now]: the open hypotheses and the test that would resolve
  each (a repeat specimen within a month for an unconfirmed marker rise; ctDNA for mutation status
  after treatment), with the source of that expectation. Evidence for the clinician's judgment,
  never an order.
- **Missing data and what it limits** [now]: "not sequenced since month 0" and the inferences
  that therefore carry wider uncertainty.
- **Report export** [now]: one page per version with figures, numbers, sources, placeholders,
  model versions and reviewer marks.

## 3. Blood and lab workbench

A measurement explorer. The analyzer's "zones, flags, risk points" become "periods, flags,
kinetics". Beyond the first page (trends with reference limits and treatment marks, results
table, flags with rule and source, quality checks, look-here queue, rules card):

- **Spot panel per value** [now]: click a point: value, unit, change from previous and from nadir,
  rate per month, the events around it, which rules fired and why, specimen notes, and what to
  check (assay change, specimen quality, hook effect at very high values).
- **Pointers L1…Ln** [now] shared by the chart, the queue and the text.
- **Marker kinetics** [now, model inference, placeholder method]: doubling or halving time from
  at least three points, and "if the current rate holds, the reference limit is crossed in about
  N months", drawn as a band, labeled as an extrapolation with its uncertainty, never as a
  prediction of progression.
- **Confirmation tracker** [now, literature: EGTM]: a 25% rise counts only when a second specimen
  within a month confirms it; the tracker shows "unconfirmed, next specimen due by month X" and
  flips to confirmed or withdrawn.
- **Treatment-aware interpretation windows** [now, literature]: a transient rise in the first
  weeks after a new systemic therapy is described in the literature (a flare); values inside that
  window are marked "early after a therapy change: interpret with caution", with the citation,
  so an early rise is not over-read. If no citation is found, the window is a placeholder and says
  so.
- **Within-person baseline band** [now]: the median and spread of a stable period, so a value is
  judged against this patient as well as the reference interval; the band is labeled by the
  months it was built from.
- **Lead and lag against imaging** [now, observed]: in this record the marker rise at month 11
  preceded the imaging progression at month 12; shown as a fact of this record, not a rule.
- **Cross-marker view** [now]: CA 15-3 and CEA on one axis with their own limits; concordant and
  discordant rises named; correlation is not causation, said in the panel.
- **Any analyte, from a reference table** [now, built 2026-10-21; `docs/labs.md`]: tumor
  markers, liver and bone chemistry, kidney (eGFR by the 2021 CKD-EPI equation) and a CBC, each
  with Mayo Clinic Laboratories' adult interval by sex (a reference laboratory's, tagged so), units
  and conversions, and why it matters with its citation; the lab report's own interval always
  wins; any other analyte flows through flagged against its own interval. Out-of-interval flags
  are observed against the named source, the EGTM rise rule applies to tumor markers only,
  other change flags are placeholders, low counts carry their CTCAE v5.0 grade.
- **Assay and unit change detection** [now, partly]: units convert at the import boundary (an
  unknown unit is rejected with the reason); a changed reference interval is a quality issue
  ("compare across it with care"). A changed method the record does not state stays invisible
  [data].
- **CBC and differential, derived ratios** [now for absolute counts, via import; ratios planned]:
  hemoglobin, white cells, absolute neutrophils and platelets with CTCAE grades; ratios only where
  clinically established, each with its source.
- **Cross-analyte hypotheses** [now, hypothesis]: raised or rising ALP and calcium next to an
  imaging report naming bone, liver enzymes next to one naming the liver, each naming the report,
  its literature and the other causes; a same-month GGT says which source fits a raised ALP.
- **Search** [now]: "values above the limit", "after palbociclib", "rising", an analyte or a
  panel; "can't see that" for anything the panel lacks, naming the panel that would show it.
- **Export** [now]: the chart, the table, the flags with sources, the reviewer marks.

### ctDNA monitor (liquid biopsy)

- **Variant allele fractions over time** [now, synthetic series; `docs/ctdna.md`]: SYNTHETIC-001
  carries a hand-written series (PIK3CA H1047R tracking burden, ESR1 D538G emerging under
  letrozole, DNMT3A R882H flat), labeled synthetic on every screen; no open serial breast ctDNA
  data exists [data]. Detection limit and calls (new, rising, falling, cleared) are placeholders.
- **ESR1 under an aromatase inhibitor** [now, literature: PADA-1, SERENA-6]: evidence for
  clinician review with how this record differs from the trials, never a switch recommendation.
- **Clonal hematopoiesis** [now, literature: Razavi 2019, Jaiswal 2014]: a variant the tumor
  sequencing did not find, in a clonal-hematopoiesis gene, is flagged and kept out of the tumor
  picture; every variant keeps the matched white-cell caveat.
- **Lead and lag, Spot panel, review marks, cannot see, rules card, exports** [now]; links to the
  genomics workbench and the Evolution view.

## 4. Genomics workbench

The analyzer's "detection, then interpretation, then what to check" becomes an **evidence
ladder** per variant. Beyond the first page (variant browser, the three separated blocks,
panel coverage, review queue, longitudinal note, limits, data card):

- **Evidence ladder** [now]: for each variant, five rungs with their own evidence type: detected
  (observed: test, sample, date; allele fraction "not available in these calls"), interpreted
  (CIViC items by level, direction and date), predicted effect (CIViC's own wording only),
  therapy evidence for clinician review, resistance mechanisms (CIViC "Resistance" items and the
  literature already cited in `VISION.md`: ESR1 under aromatase inhibitors). Each rung names what
  would strengthen it.
- **Resistance watchlist** [now, hypothesis]: for the treatments recorded in the file, the
  alterations known to emerge under them, each with its source, its evidence level and the test
  that would detect it (ctDNA, a repeat biopsy). Shown as "what to watch", never as advice.
- **Sample provenance strip** [now]: sample → site → date → assay → what it can and cannot show
  (purity, depth, panel genes only), at the top of the page.
- **Conflicting evidence side by side** [now]: items that support and items that do not support
  the same association, with their levels and dates; no averaging.
- **Variant Spot panel** [now]: click a variant: the ladder, the CIViC items as a table with links,
  the panel's view of the gene, the sample it came from, the review marks.
- **Longitudinal variant table** [data]: one row per variant per sample with dates and assay
  differences; "not re-sequenced" cells stay blank, never "absent".
- **Pathway view** [roadmap]: which observed variants fall on which known pathways, from a named
  reference, as hypotheses.
- **Search** [now]: "level A", "resistance", a gene; "this panel does not include that gene" when
  it is not covered.
- **Export** [now]: the variant table, the ladder, the sources, the reviewer marks.

## 5. Pathology workbench (H&E slides)

Built in two rounds (2026-10-19, 2026-10-20; `pathology.md`) on the patient's own TCGA
diagnostic sections for three cases (two more follow), scored offline; the colon analyzer's pipeline (tissue mask →
224 px tiles at 0.5 µm/px → embeddings → tissue classes → smoothed maps → front, zones,
measurements, flags, risk map, certainty) carries over, re-implemented; its tissue heads do not
(colon-trained): a five-class BCSS head validated on 3 held-out slides stands in. Tags below:
**now** = built; **model** = needs a model or validation that does not exist yet.

- **Tissue map** for breast [now: invasive carcinoma, stroma, lymphocytes, necrosis, fat;
  model: DCIS, normal breast, vessels (too few BCSS tiles), a second model's opinion]:
  probabilities on hover; layers for tissue, certainty, QC, zones, immune and risk. Data: BCSS (CC0 region masks on TCGA-BRCA slides) to
  train a small head on an open encoder from the survey; TCGA-BRCA diagnostic slides for
  calibration by eye and by the pathologist.
- **Tumor front and growth pattern** [now, placeholder cutoffs]: the invasive front as a line,
  core / front band / peritumoral zones, pushing versus infiltrative with roughness and fingers;
  **direction of invasion** as arrows per arc and a rose diagram; "what the front faces" (fat,
  stroma, lymphocytes, necrosis). A 2D snapshot: where it is invading in this section, never a
  forecast, said on the page and labeled a hypothesis.
- **Breakaway cells** [now, weak until validated]: StarDist nuclei on the front band; clusters
  of ≤ 4 tumor-candidate nuclei outside the main tumor (ITBCC), the 0.785 mm² counting field at
  the hotspot with a counter the pathologist fills in; the nuclei model is pretrained, not
  validated on breast, said on the page.
- **Satellite islands** [now] with their distance from the main tumor and the tissue between.
- **Immune pattern** [now, placeholder cutoffs; model: calibration]: stromal lymphocytes by
  zone (core, front band, peritumoral) as tile shares and lymphocyte-like nuclei per mm², with
  the International TILs Working Group's zones as the literature source (a count proxy, not
  its area percentage); desert, inflamed or excluded pattern on placeholders, tagged.
- **Necrosis** contact and **tumor–stroma ratio** [now, literature cutoff from colorectal];
  **lymphovascular invasion**, **in-situ versus invasive** and **margins** [model / data]: the
  page says it cannot see them and which test can.
- **What a tile map cannot do** [now]: Nottingham grade (nuclear-area variation is shown as a
  proxy only), receptor status (needs IHC), mutations (needs sequencing), margins,
  lymphovascular invasion, what happens next. Each stated on the page with the test that can.
- **Quality control** [now: blur, glass, pen ink, placeholders; data: blood, folds, stain
  variation], with the tiles excluded and why; a certainty map (top probability below a
  placeholder cutoff = unsure here).
- **Risk map and cards** [now, every point a placeholder]: every feature adds points within
  1 mm; regions at level 2 or more get a card that opens the Spot panel; the points table and
  every placeholder are visible.
- **Spot panel per tile** [now; model: a second model's answer]: the crop with nuclei dots,
  where it sits, top class and score, certainty and why, zone and distance to the front, nuclei
  counts, what to check by eye, all class scores, the review mark.
- **Review** [now]: search inside the slide ("lymphocytes at the border", "budding", "T2";
  "can't see that" for grade, receptors, mutations), pointers T1…Tn, pins, agree / disagree /
  second look under `finding_key` kind "slide", the unsure spot in the queue, two sections
  compared, exports (map picture, JSON, CSV; PDF is roadmap).

## 6. Radiology workbench (CT, MRI, PET, mammography)

First version built 2026-10-20 (method, cutoffs and known failures: [`radiology.md`](radiology.md)).
The synthetic record holds imaging reports (text), so its page is report-driven and honest about
it; three held-out TCGA cases have public TCIA studies, which open the image viewer.

- **Report-driven** [now, built]: each imaging read with "read as progression / stable" observed
  in the report's words, new sites listed, the lesion vocabulary extracted ("new liver lesions"),
  a lesion table that tracks named sites across reports with their dates ("no measurements
  recorded"), and lead and lag against CA 15-3.
- **Image viewer** [built on public studies]: slice navigation, window and level, series
  selection (pre, early, delayed, subtraction), zoom, contours with their source (MedSAM from a
  seed rule's box; no reader contours exist), measurements with method and uncertainty (longest
  diameter ± a pixel, volume with a one-pixel range), DCE kinetics in the BI-RADS lexicon's terms
  with literature cutoffs as placeholders. [planned] multiplanar views, registration between
  dates with "unreliable here" marks, RECIST-style sums labeled as computed, mammography contours.
  [built for one study] a mammoscreen screening score and density per breast, and MONAI's
  density per view as a second opinion (model inference).
- **Protocol and scanner differences** [data] flagged before any "larger" or "smaller": no
  processed patient has two study dates yet (20 TCIA patients do; none is in the held-out set).
- **Spot panel per lesion** [built for one study]: size, volume, kinetics curve, how its box was
  chosen, the model and its published validation ("not validated on breast MRI here"); size over
  time needs a prior [data].

## 7. Expression, methylation and protein workbench

Built 2026-10-20 (`app/workbenches/omics.py`, method and numbers in [`omics.md`](omics.md)).

- **Layer cards** [now, built]: for each measured layer, the top features with cohort percentiles,
  the contribution to the risk compared with a typical patient, the layer's own validation (the
  single-layer C-index, including the copy-number layer's failure across sites), and the
  normalization used.
- **What-if** [now, built]: hide a layer and see the risk move, labeled model inference.
- **PAM50 subtype call** [now, built]: Parker centroids with a named reference population (this
  TCGA-BRCA cohort, ER-balanced), validated against TCGA's published calls; the correlation to
  every centroid, the margin, and agreement per patient.
- **Pathway, proliferation and immune scores** [now, built]: MSigDB Hallmark sets, the PAM50
  proliferation genes and cytolytic activity, as cohort z-scores (model inference, relative to
  this cohort).
- **Receptor consistency** [now, built]: recorded IHC against RNA, ERBB2 copy number and RPPA,
  one labeled line each, with calibrated cutoffs.
- **Other signatures** (recurrence-score-like, immune deconvolution) [model]: only from a
  validated model with a named reference population; shown as planned.
- **Batch and site effects** [now, built]: the known anti-predictive copy-number layer is stated
  as a known failure, with the numbers.
- **RNA is not protein** [now, built]: the panel says which layer each claim comes from.
- **Spot panel, search, marks, export** [now, built]: per feature, pathway, receptor line and
  subtype; JSON and CSV.

## 8. Clinical documents workbench

Built 2026-10-20 (`app/workbenches/documents.py`; rules and their measurement in
[`documents.md`](documents.md)) on SYNTHETIC-001's record entries, the TCGA cases' pathology
reports (TCGA-Reports, CC BY 4.0) and imported reports and notes.

- **Breast pathology facts with their source sentence** [now, rules]: histologic type, Nottingham
  grade and components, size, margins, lymphovascular invasion, nodes, pT / pN, stage, ER / PR
  (status, %, Allred), HER2 (status, IHC, ISH, ratio), Ki-67, laterality, specimen, drugs, ECOG,
  dates; each highlighted at its characters, status "documented", nothing derived.
- **Measured** [now]: precision and recall per field against TCGA's clinical fields on the
  held-out half of 1,005 TCGA-BRCA reports and on the bundled cases (Methods and validation).
- **Facts table that jumps to the sentence**, **documented kept apart from inferred** (the
  report summary and the case note), **conflicts side by side**, **a timeline from the
  documents' own dates**, **plain-word search** with "no document mentions that", **marks, pins
  and exports** (JSON, CSV) [now].
- **Import** [now]: a report (text or PDF) or a clinician note joins the file and is read the
  same way.
- **Diagnoses and procedures beyond breast pathology, negation and hedging, specimen linking**
  [model]: need a clinical language model run locally and its own validation; a named-entity
  model for highlights did not fit the hosted app (documents.md).

## 9. Cross-test intelligence

- **Lead and lag** [now]: marker, imaging and risk events on one axis with the gaps between them
  named ("the marker rose 1 month before imaging read progression").
- **Evidence graph** [now]: which measurements support each interpretation in the report.
- **Discrepancy queue** [now]: see §2.
- **Cross-modality search** [now]: a gene finds the variant, its evidence, the risk features that
  name it and the notes that mention it.
- **Side-by-side report versions** [now]: §2.

## 10. What ships before the freeze

In this order, each tagged **now** above: the shell's SOS ordering, version diff, evidence chain,
discrepancy queue and "what would reduce uncertainty"; the lab workbench's Spot panel, pointers,
kinetics, confirmation tracker, treatment windows, baseline band, lead-and-lag, cross-marker view,
search and export; the genomics workbench's evidence ladder, resistance watchlist, provenance
strip, conflicting evidence, Spot panel, search and export; the omics layer cards; the
report-driven radiology page with a first image viewer on public TCIA studies, and the
clinical documents workbench and test import (both built 2026-10-20). The pathology viewer's
planned parts and every remaining **model** item show as planned with their design and their
data plan.

## 11. What is never claimed

A tile map does not see single cells, grade or receptors; one slide is one section; a marker
outside its interval is not progression; a variant detected once is not the tumor's state now;
an extrapolated marker curve is arithmetic, not prognosis; a model's benchmark elsewhere is not
its performance here. Each page says which test could answer what it cannot.

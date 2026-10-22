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
9. **One contract for the patient file** (built 2026-10-21). Every workbench module
   (`src/muffle/workbench/<name>.py`) carries two pure functions that the report, the export
   and the patient list read the same way (`muffle.overview`):
   - `summary(pf, version=None) -> {"workbench", "title", "cards", "note"}`: a few key
     findings as cards (`workspace.card`): `what`, `text`, `evidence` (observed, model
     inference or hypothesis; a documented fact is observed), `source` (the test it comes
     from), `method` (rule or model, with its version), `threshold` (where it comes from:
     guideline, literature, calibrated or placeholder), `trust` (strong, moderate, weak),
     `opens` and `focus`. `note` says why there is no card ("no scored section of this
     tumor").
   - `queue(pf, version=None) -> [item]`: what is worth a look now (`workspace.look`):
     `pointer` (L5, T2, the variant, "ER: IHC vs RNA", D1), `what`, `why`, `evidence`, `trust`,
     `consequence` (3 changes the picture of the disease, 2 may change care, 1 worth a look),
     `opens`, `focus`, `source`, `key` (its `finding_key`, so a mark made from the report is
     the workbench's own mark), `month` and `threshold`. The workbench page may list more
     (older flags, standing caveats such as a layer's known failure).
   - `opens` has the shape of `Alert.opens` (`("Tests", kind, month, name)` or
     `("Timeline",)`); `focus` says where inside the workbench the evidence is (`{"marker",
     "month"}`, `{"variant"}`, `{"slide", "pointer", "tile"}`, `{"omics": key}`, `{"doc",
     "sentence"}`), and the report's "open" lands there.
   - Pure: no Streamlit, no model run, nothing new computed (`tests/test_overview.py`). Labs,
     ctDNA, genomics, slides (with the invasion results), omics, documents, radiology and
     evolution carry them; a new workbench joins the overview by adding the two functions.
10. **One page skeleton** (built 2026-10-22, [`ux.md`](ux.md) §1). Every workbench page (the
    clinical documents page after its round 2) draws the same parts in the same order through
    one helper (`app/workbenches/_page.py`): title, status chips, overview (paragraph, the
    look-here queue from `queue()`, search), the picture, collapsed details with their
    counts, the Spot panel, the Model and validation card, what the test cannot see, the
    export. The tests fail a page that breaks the order.

## 2. Patient file and report

The report is where the workbenches meet. Beyond what the shell already shows (summary,
observed / inference / hypothesis blocks, risk, what changed):

- **Overview header** [built 2026-10-21]: one row of finding cards from the workbenches'
  summaries: the open SOS alerts (alerts without a review mark), stage and receptors (recorded
  and documented side by side), the PAM50 call with its margin, key drivers with their best
  CIViC level, the slide picture (main tumor area, infiltrative arcs, breakaway candidates,
  immune pattern) for scored sections, imaging (the lesion table of the imaging reports, or a
  public study's headline: contour size, kinetics or screening score, with the study's
  BI-RADS), the 12-month or cohort risk, and the top evolution hypothesis (what to watch
  next, with why this file raises it). Each card has its evidence label and
  trust, "Why?" (source test, method and version, threshold source, trust) and "Open"; a line
  under the row names what the file lacks.
- **One attention queue** [built 2026-10-21], replacing the SOS tile: the SOS alerts, the
  discrepancies below and every workbench's queue, ordered by consequence × trust (placeholder
  weights), then new in this version, then the latest; de-duplicated by finding key, so an
  alert takes the pointer of the workbench item behind it (the marker rise is L4 in the lab
  workbench, one item with one mark) and says where else it was raised. One item at a time
  with keyboard triage: j next, k previous, p pin, m mark reviewed (Streamlit keeps r for its
  own rerun), u the unsure list (marked "second look", or weak trust), o open; "open" lands on
  the pointer (the lab value's Spot panel, the slide tile, the omics finding, the variant, the
  document's sentence). Exported with the report.
- **SOS ordering by trust × consequence** [built]: an observed progression on imaging outranks
  a placeholder-rule marker rise; each alert says since when, which rule, the threshold's
  source and its trust.
- **Version diff** [now]: any two versions side by side in the three evidence columns, with added,
  removed and changed items highlighted and the "what changed and why" attribution underneath.
- **Evidence chain** [now]: every sentence of the case note links to the tool output behind it
  (the grounding trace rendered as a chain: sentence → tool → measurement → raw value), with the
  trust at each step. This is the analyzer's "why" made navigable.
- **Discrepancy queue** [built]: tests that disagree, each naming both sources, the evidence
  labels, what would settle it and its cited basis where one exists: a marker rising while
  imaging reads stable; the 12-month risk up while labs fall; sites that drop out of a summary;
  level A/B evidence with no treatment change (a question); since 2026-10-21 also ERBB2 copy
  number against the recorded or documented HER2 status (ASCO/CAP HER2 guideline, Wolff 2018);
  ESR1 RNA and ER-alpha protein against the recorded or documented ER status (ASCO/CAP ER/PR
  guideline, Allison 2020); a documented receptor status against the recorded one; PAM50
  Basal-like with an ER-positive status (Prat 2015); a slide section read as an immune desert
  while the RNA's cytolytic score is high (TILs Working Group, Salgado 2015; the "high" cutoff
  is a placeholder); documents that disagree with each other; documented stage, laterality or
  specimen type against the clinical record (today's records hold a stage, not a side or a
  specimen); an imported lab value against the record's value of that month.
- **What would reduce uncertainty** [built]: the open hypotheses and the test that would
  resolve each (a repeat specimen within a month for an unconfirmed marker rise; ctDNA for
  mutation status after treatment; a repeat IHC or ISH for a receptor disagreement; a second
  encoder's tile classes where the slide head is unsure, cited with the head's own held-out
  accuracy below and above its certainty cutoff; a re-read of a document), with the source of
  that expectation. Evidence for the clinician's judgment, never an order.
- **Missing data and what it limits** [now]: "not sequenced since month 0" and the inferences
  that therefore carry wider uncertainty.
- **Report export** [built]: one page per version with every workbench's finding cards, the
  attention queue with each item's mark, the discrepancies with their sources and basis,
  numbers, sources, every placeholder (the queue's weights and each placeholder threshold
  shown), model versions and the reviewer marks by finding kind.
- **Imports** [built]: an imported test adds a report version; it shows in the timeline and the
  version diff, its lab values and alerts join the attention queue, and the export lists it.

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

Built in two rounds (2026-10-19, 2026-10-20/21; method and numbers in
[`genomics.md`](genomics.md)). Tags: **now** = built.

- **Evidence ladder** [now]: for each variant, five rungs with their own evidence type: detected
  (observed: test, sample, date; allele fraction from the read counts for the TCGA cases),
  interpreted (CIViC items by level, direction and date), predicted effect (model inference:
  AlphaMissense and the Ensembl VEP consequence; CIViC's own wording when no prediction exists),
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
- **Copy-number landscape** [now, placeholder cutoffs]: ASCAT3 gene-level copy number in genome
  order, calls relative to the ploidy (the model's rule, or ABSOLUTE's when the two disagree),
  cohort percentiles, a Spot panel per gene (CIViC items for its copy-number change, the
  expression workbench's RNA and protein, its pathway, neighbors), the ERBB2-versus-HER2 line
  reused from the omics workbench.
- **Mutation burden and allele fractions** [now]: observed call count, rate over the 38 Mb exome
  (Chalmers 2017), cohort percentile; allele fractions with 95% intervals, ABSOLUTE purity and the
  clonal range (model inference).
- **Predicted effect** [now]: detected (VEP consequence), interpreted (CIViC, ClinVar) and
  predicted (AlphaMissense, not approved for clinical use) kept apart; bundled snapshot, live
  Ensembl lookup by name for imported variants.
- **Longitudinal variant table** [now; ctDNA when its series lands]: one row per variant per
  sample (tumor sequencing, imported sequencing, ctDNA) with allele fractions; "not re-sequenced"
  cells stay blank, never "absent"; each variant links to the Evolution view's escape routes.
- **Pathway view** [now, hypothesis]: seven breast-cancer pathways with their sources (PubMed-
  checked), this tumor's mutations and copy-number changes on each node, CIViC items per pathway
  for clinician review.
- **Search** [now]: "level A", "resistance", a gene; "this panel does not include that gene" when
  it is not covered; in the genome views "amplified", a gene, "PI3K pathway", "high burden".
- **Export** [now]: the variant table, the ladder, the sources, the reviewer marks; the genome
  sections, the copy-number table (CSV) and the genome findings (JSON).

## 5. Pathology workbench (H&E slides)

Built in three rounds (2026-10-19, 2026-10-20, 2026-10-21; `pathology.md`) on the patient's own
TCGA diagnostic sections for five cases, scored offline; the colon analyzer's pipeline (tissue mask →
224 px tiles at 0.5 µm/px → embeddings → tissue classes → smoothed maps → front, zones,
measurements, flags, risk map, certainty) carries over, re-implemented; its tissue heads do not
(colon-trained): a five-class BCSS head validated on 3 held-out slides stands in. Tags below:
**now** = built; **model** = needs a model or validation that does not exist yet.

- **Slide viewer** [now]: pan and zoom over the patient's own section at about 1 µm/px with
  every layer and mark below drawn on the tissue and the counted nuclei at high zoom; hover,
  click to the Spot panel, jump to and n / p through the pointers; sections side by side with
  linked zoom; the tile map is the fallback (`pathology.md` §7).
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

First version built 2026-10-20, second round 2026-10-21 (method, cutoffs and known failures:
[`radiology.md`](radiology.md)). The synthetic record holds imaging reports (text), so its page is
report-driven and honest about it; five held-out TCGA cases have public TCIA studies, which open
the image viewer, and a public example pair of two dates shows change over time on real images.

- **Report-driven** [now, built]: each imaging read with "read as progression / stable" observed
  in the report's words, new sites listed, the lesion vocabulary extracted ("new liver lesions"),
  a lesion table that tracks named sites across reports with their dates ("no measurements
  recorded"), lead and lag against CA 15-3, and [built, round 2] a change view between any two
  reads in the image change view's shape (no sizes, so no sum).
- **Image viewer** [built on public studies]: slice navigation, window and level, series
  selection (pre, every phase, delayed, subtraction), zoom, contours with their source (MedSAM
  from a seed rule's box, on the acquisition plane; no reader contours exist), measurements with
  method and uncertainty (longest diameter ± a pixel, volume with a one-pixel range), DCE kinetics
  in the BI-RADS lexicon's terms with literature cutoffs as placeholders. [built, round 2]
  multiplanar views (axial, coronal and sagittal with linked positions, the voxel shape said, the
  contours and measurement marks carried over), a cine through the phases at the lesion, and
  sagittal acquisitions turned into the axial frame. [built for one study] a mammoscreen
  screening score and density per breast, MONAI's density per view as a second opinion (model
  inference), and [built, round 2] a left-right dense-pixel difference (placeholder) and CC and
  MLO linked on the same band behind the nipple. [none open] mammography lesion contours: no
  open, permissive, CPU-ready detector was found, and the page says so.
- **Change over time** [built on a public example pair, round 2]: two dates side by side at the
  same position after a rigid alignment by normalised mutual information, "unreliable here"
  where a local check finds the studies still apart (placeholder), lesions paired by position
  with both dates' sizes and the change, a RECIST-style sum labeled computed (never a response
  call) and a "what changed" paragraph; protocol and scanner differences listed first. No
  bundled patient has two dates; the example pair (TCGA-AR-A1AQ) is not a patient file.
- **Spot panel per lesion** [built]: size, volume, kinetics curve, how its box was chosen, the
  model and its published validation ("not validated on breast MRI here"), and its change over
  time where two dates exist.

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
- **Protein pathway activity (RPPA)** [now, built 2026-10-21]: the ten pathway scores of Akbani
  et al. 2014 (their member antibodies and signs), with a Spot panel per antibody (value,
  percentile, its gene's RNA, protein-versus-RNA agreement, the genomics pathway map beside it)
  and "RPPA is a targeted array" said; protein against RNA measured per antibody on the Methods
  page.
- **Promoter methylation** [now, built 2026-10-21]: ESR1, PGR, BRCA1, RASSF1A, GSTP1 and p16
  from the Illumina manifest's core-promoter CpGs that are unmethylated in normal breast, the
  case against the cohort, a placeholder "methylated" call and the gene's RNA beside it
  (consistent with silencing or not); a CpG island hypermethylation index as a hypothesis.
- **Immune and stromal picture** [now, built 2026-10-21]: ESTIMATE's gene lists by z-score
  averaging, the RPPA immune-cell antibodies, and an immune picture that reads them with the
  slide workbench's lymphocytes by zone (agree or disagree; a pathologist's TILs read settles
  it). The cross-test "slide desert against high immune RNA" rule stays the one in
  `muffle.crosstest`.
- **Other signatures** (recurrence-score-like, immune deconvolution) [model]: only from a
  validated model with a named reference population; shown as planned.
- **Batch and site effects** [now, built]: the known anti-predictive copy-number layer is stated
  as a known failure, with the numbers.
- **RNA is not protein** [now, built]: the panel says which layer each claim comes from.
- **Spot panel, search, marks, export** [now, built]: per feature, pathway, receptor line and
  subtype; JSON and CSV. Round 2 adds the protein pathways, antibodies, promoters, signatures
  and the immune picture, with the finding kinds `pathway_protein` and `methylation`.

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
- **A second reading by a named-entity model** [now, model inference] (round 2, 2026-10-21):
  OpenMed's zero-shot oncology NER (Apache-2.0) run offline with 16 breast pathology labels;
  its spans ship as derived JSON for the bundled reports and are drawn as a second layer
  (violet underline, label and score), set beside the rules' facts per document (agree,
  disagree, read by one only, "which the rules took for a legend"), with a "models disagree"
  item (M1…) in the queue for a receptor or stage field. Measured on the same held-out reports
  as the rules: it finds where a field is named far more often than its result
  (documents.md). An imported document is queued for the local pipeline.
- **Scanned reports** [local pipeline]: a PDF without a text layer is a test queued for the
  local pipeline (its name and page count kept), which reads the pages with Granite-Docling
  258M (Apache-2.0) and runs the rules and the model on the text; text accuracy checked on two
  synthetic and two real scans.
- **The documents over time** [now]: the dated documents' receptor, stage, grade and type on
  the file's axis, changes named (a receptor that flips, a restaging), conflicts settled only
  by the clinician's mark (the value that stands), and "the record says X, the documents say
  Y" in the discrepancy queue where the cross-test rules did not already cover it (receptors
  on a file without omics scores, a later restaging).
- **Search across both layers and a Spot panel** [now]: "HER2", "margin", "node positive"
  find facts and model spans; the Spot panel shows the sentence, the rule or the model and its
  score, the TCGA field it was measured against with both readers' numbers, and the mark.
- **Diagnoses and procedures beyond breast pathology, negation and hedging, specimen linking**
  [model]: need a clinical language model run locally and its own validation.

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

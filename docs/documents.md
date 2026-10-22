# Clinical documents: extraction rules and how well they hold up

The clinical documents workbench (`app/workbenches/documents.py`, logic in
`src/muffle/workbench/documents.py`; spec in [`WORKBENCHES.md`](WORKBENCHES.md) §8) shows a
patient file's documents with every breast pathology fact they state highlighted at its
characters. This page says what the rules read, how they were measured and what they miss.
Written 2026-10-20; rules v2 and their measurement on 2026-10-21; round 2 (a named-entity
model's reading beside the rules', scanned reports, the documents over time) on 2026-10-21.

## What the workbench shows
- **Documents**: SYNTHETIC-001's record entries (diagnosis, treatments, labs, imaging reports,
  sequencing, clinic visits; written by hand, dated by month), each held-out TCGA case's
  pathology report from TCGA-Reports (38 of the 40 bundled cases have one), and any report or
  clinician note imported in the session.
- **Facts**, each with its document, its characters, its sentence and the status
  **documented**: histologic type; Nottingham grade, score and its three component scores;
  tumor size; margins and the closest margin; lymphovascular invasion; lymph nodes examined and
  positive; pT and pN; stage group; ER and PR status, percentage and Allred score; hormone
  receptor status; HER2 status, IHC score, ISH result and ratio; Ki-67; laterality; specimen
  type; the breast cancer drugs named; ECOG; full dates written in the text.
- **Documented versus inferred**: the documents' facts in one column; in the other, what the
  file infers elsewhere (the report summary, the case note written by a language model from
  derived numbers). Neither reads the other.
- **Conflicts** between documents (a field with different values in two documents) side by
  side, never voted or averaged; several values inside one document are listed as facts.
- **Timeline** from the documents' own dates (the month a record entry carries, else a full date
  in the text; TCGA reports are mostly undated because de-identification removed dates).
- **Search** in plain words across the file's documents ("estrogen positive" finds "ER:
  positive"); "No document in this file mentions that" when nothing matches.
- **Review**: agree / disagree / second-look marks and pins per fact, stored under
  `workspace.finding_key(pf, "document", document id, "Field: value")`; exports as JSON and
  CSV, and the marks go into the report's Markdown export.

## The rules
Regular expressions (`RULES_VERSION` = "documents rules v2 (2026-10-21)"), run where the app
runs. No language model reads a document and no report text goes to Token Factory or Tavily
(CLAUDE.md). The rules card on the page lists each rule in words. Principles:
- A fact is what the document says: an ER percentage is never turned into a status, an IHC score
  never into a HER2 status, a pT never into a stage, per-specimen node counts never into a total.
- Definitions, reference ranges and form labels are not results ("ER negative < 6.5",
  "positive is defined as", "Ki-67 Low <10%", "margins involved by invasive component:").
- A HER2 scoring legend is not a result (v2): a list of two or more different categories with
  their scores ("Negative 0-1+, Equivocal 2+, Positive 3+", "[NEGATIVE:0,1+ EQUIVOCAL: 2+; POSITIVE:
  3+]", "Negative <10.7 Positive 11.5"), a score set equal to a category ("2=INDETERMINATE"),
  "score of 2 are considered borderline" and "a 2+ result that is interpreted as equivocal".
  Neither the category nor the score in it is read.
- A HER2 status word is not read when the IHC score in the same stretch argues against it
  (v2): positive with 0 or 1+, or with 2+ when the stretch does not say amplified; negative with
  3+. The stretch then holds two answers, and the word is usually not HER2's: an OCR'd synoptic
  form whose answers slid one row (case 545: "ESTROGEN RECEPTORS: PROGESTERONE RECEPTORS:
  positive. HER2/NEU: positive. zero or 1+.", where the second "positive" is PR's answer and
  "zero or 1+" is HER2's), a comment that runs on into another stain ("HER2/neu. 3+. E cadherin
  ... was negative"), or the HercepTest-era "weakly positive (2+)", which is an equivocal score
  today. The IHC score stays a fact; no status is made from it.
- "zero or 1+", "0 / 1+" and "0-1+" are read as the IHC band "0 or 1+", not as 1+ (v2).
- A receptor's value is the first positive / negative / sign after its name and before the next
  receptor named; "positive for ER and PR" and "ER/PR positive" give both.
- OCR's letter O in "pNO" is read as zero; other OCR errors are not repaired.

## Measurement
**Data.** TCGA-Reports (Kefeli and Tatonetti, *Patterns* 2024,
[10.1016/j.patter.2024.100933](https://doi.org/10.1016/j.patter.2024.100933); data
[10.17632/hyg5xkznpx.1](https://doi.org/10.17632/hyg5xkznpx.1), CC BY 4.0): 1,005 of the cohort's
TCGA-BRCA patients have a report. **Reference**: TCGA's own clinical fields for the same patients
(UCSC Xena TCGA hub, `BRCA_clinicalMatrix`, open access): `breast_carcinoma_estrogen_receptor_status`,
`..._progesterone_receptor_status`, the HER2 ISH outcome (else the IHC status), `pathologic_T`,
`pathologic_N`, `pathologic_stage`, `histological_type`, `margin_status`,
`lymph_node_examined_count`, `number_of_lymphnodes_positive_by_he`.

**Protocol.** Patients split by a hash of the barcode: the rules were written while reading the
**dev** half (524 patients; plus three bundled reports read while designing), and are reported on
the **held-out** half (481) and on the **38 bundled cases**. Rules v2 were written on the dev half
too, but the misread that prompted them is in a held-out report (case 545, TCGA-BH-A0DS), and one
detail was added after the held-out run showed a table row ("Negative (0). Negative (0 - 1+)",
result and normal range) read as a legend: a list needs two different categories. That detail
changes no number below. For each patient the first value a
report states is compared with TCGA's field. Precision = right / extracted; recall = right /
patients with a TCGA value. HER2 for this comparison only: the ISH result if stated, else the
status word, else the IHC score read by the ASCO/CAP bands (0 and 1+ negative, 2+ equivocal, 3+
positive). Node counts: the total a report states, else the sum of its specimens' counts.
`scripts/prepare_documents.py` reproduces it and writes `app/documents/validation.json` (counts
only).

**Held-out half (481 patients), rules v2**

| Field | With a TCGA value | Extracted | Right | Precision | Recall |
|---|---|---|---|---|---|
| ER status (positive / negative) | 459 | 202 | 192 | 95% | 42% |
| PR status (positive / negative) | 458 | 201 | 187 | 93% | 41% |
| HER2 status (positive / negative / equivocal; ISH first, then IHC) | 422 | 239 | 194 | 81% | 46% |
| pT category (T1–T4, Tis, TX; suffix ignored) | 481 | 269 | 257 | 96% | 53% |
| pN category (N0–N3, NX; suffix ignored) | 481 | 254 | 245 | 96% | 51% |
| Stage group (I–IV; A–C ignored) | 468 | 28 | 27 | 96% | 6% |
| Histologic type (ductal, lobular, mixed, special types) | 464 | 388 | 381 | 98% | 82% |
| Margins (negative / positive / close) | 443 | 217 | 197 | 91% | 44% |
| Lymph nodes examined (count) | 441 | 208 | 131 | 63% | 30% |
| Lymph nodes positive (count, H&E) | 432 | 187 | 151 | 81% | 35% |

**The 38 bundled cases, rules v2** (the same counts as v1)

| Field | With a TCGA value | Extracted | Right | Precision | Recall |
|---|---|---|---|---|---|
| ER status (positive / negative) | 36 | 15 | 15 | 100% | 42% |
| PR status (positive / negative) | 36 | 15 | 14 | 93% | 39% |
| HER2 status (positive / negative / equivocal; ISH first, then IHC) | 34 | 18 | 16 | 89% | 47% |
| pT category (T1–T4, Tis, TX; suffix ignored) | 38 | 22 | 20 | 91% | 53% |
| pN category (N0–N3, NX; suffix ignored) | 38 | 24 | 23 | 96% | 61% |
| Stage group (I–IV; A–C ignored) | 36 | 2 | 2 | 100% | 6% |
| Histologic type (ductal, lobular, mixed, special types) | 37 | 28 | 28 | 100% | 76% |
| Margins (negative / positive / close) | 33 | 17 | 17 | 100% | 52% |
| Lymph nodes examined (count) | 36 | 12 | 6 | 50% | 17% |
| Lymph nodes positive (count, H&E) | 35 | 10 | 7 | 70% | 20% |

**Reading it.**
- When a report states ER, PR, pT, pN, the histologic type or the margins, the rules read it
  right 91–98% of the time. HER2 is weaker (81%): reports mix IHC, ISH, earlier specimens and
  reference text.
- What v2 changed (HER2 only; every other row is unchanged). On the held-out half it no longer
  reads 25 HER2 status words (legends, answers that slid a row, run-on comments, "weakly
  positive (2+)") and reads none it did not read before. Of the 25, 9 contradicted TCGA's field,
  4 agreed with it by chance (a validation study's category list, and one report that writes
  "Negative reaction ... (Score=3+)"), and 12 were "equivocal" or "indeterminate" read from
  legends. The first value per patient changed for six patients: one right read gained, one
  lost (that self-contradicting report, where the comparison falls back to its IHC 3+), two
  wrong reads now read nothing and two read "equivocal" from the IHC 2+ (TCGA: negative).
  Precision went from 80% (194 of 241) to 81% (194 of 239). Of the bundled reports, v1 read
  HER2 positive in case 58 ("weakly positive (2+)", FISH negative) and both statuses in case
  545; v2 reads no status in case 58 and only "negative" in case 545.
- Recall is bounded by what reports state, not only by the rules: many TCGA surgical reports
  refer receptor results to an earlier biopsy report that is not in the dataset, and almost none
  state a stage group (6%). A missing fact is shown as "not documented", never as negative.
- Node counts are the weakest field: reports list several specimens (sentinel, axillary
  levels) and TCGA records one total.
- TCGA's fields were abstracted from the whole record, sometimes from another specimen, so a
  disagreement can be either side's error. The 38-case numbers are small-sample.
- For scale, published breast-report extraction with a large language model reaches F1 above
  95% for ER/PR/HER2 at document level (JCO Clin Cancer Inform 2026,
  [10.1200/CCI-25-00133](https://doi.org/10.1200/CCI-25-00133)); these rules trade recall for
  running locally with no model.

## What it cannot see
Facts in tables or images the OCR lost; OCR errors other than "pNO"; negations and hedges beyond
the rules ("cannot exclude", "suspicious for"); which specimen a fact belongs to when a report
covers several; anything outside breast pathology and the named drugs. HER2 misreads seen on the
dev half that v2 still makes: method text read as a result ("cell lines with high, low and
negative HER2 protein expression", "known HER2 amplified control tissue", "patients with
metastatic HER2-positive breast cancer"), a FISH reference range ("Amplified HER-2/neu levels:
>2.20"), "weakly positive" written without its score, and "NEGATIVE BY. FISH" (an OCR line
break) not read as an ISH result. A rule match is not a
pathologist's read: the page shows the source sentence for every fact.

## Round 2: a model's reading beside the rules' (2026-10-21)

### The model and its labels
`OpenMed/OpenMed-ZeroShot-NER-Oncology-Base-220M` (Apache-2.0; a GLiNER span model on an
mT5-base encoder, fine-tuned on the BioNLP 2013 Cancer Genetics corpus of research abstracts;
registry row in [`registry.md`](registry.md)) is a zero-shot named-entity model: it is given
label names and marks the spans it takes for each. Ours, for breast pathology
(`documents.NER_LABELS`): histologic type, histologic grade, tumor size, margin status,
lymphovascular invasion, lymph node status, estrogen receptor status, progesterone receptor
status, HER2 status, Ki-67 index, laterality, specimen type, pathologic T stage, pathologic N
stage, stage group, treatment. Spans are kept at a score of 0.5 or more, the card's example
threshold, not tuned on these reports.

It runs offline on a local machine (`scripts/documents_pipeline.py ner`), never in the hosted
app: the bundled reports' spans ship as `app/documents/<barcode>.ner.json` (label, start, end,
score; 38 files, about 200 KB; no text, no model). An imported document has no spans: the page
says it is queued for the local pipeline.

**The model's value is only what the characters it marked say** (`documents.ner_values`): a
span "ER: POSITIVE" labeled estrogen receptor status reads ER positive; a span "ESTROGEN" is a
mention without a result, drawn but not counted; nothing outside the span is read, so the
model's reading is not the rules' in disguise. A sign counts only right after the receptor's
name ("E-. cadherin" marked as estrogen receptor status is not ER negative).

**Speed** (WSL2 on the team's Windows PC, CPU only, shared with other jobs): the 38 bundled
cases' reports (122,032 characters) took 216 s at 2 threads, 1.8 s per 1,000 characters, load
average 1 to 6; the 495 held-out reports (1,975,857 characters) took 9,291 s at 2 threads, 4.7 s
per 1,000 characters, under a load average of 6 to 20 (other sessions' encoders, pipelines and
test suites). A typical report of 4,000 characters takes 7 to 19 s.

### Measured: the same reports, the same split, the same comparison
**Held-out half (481 patients): the rules and the model**

| Field | With a TCGA value | Rules: extracted | Rules: precision | Rules: recall | Model: extracted | Model: precision | Model: recall |
|---|---|---|---|---|---|---|---|
| ER status (positive / negative) | 459 | 202 | 95% | 42% | 2 | 50% | 0% |
| PR status (positive / negative) | 458 | 201 | 93% | 41% | 0 | – | 0% |
| HER2 status (positive / negative / equivocal; ISH first, then IHC) | 422 | 239 | 81% | 46% | 12 | 67% | 2% |
| pT category (T1–T4, Tis, TX; suffix ignored) | 481 | 269 | 96% | 53% | 54 | 96% | 11% |
| pN category (N0–N3, NX; suffix ignored) | 481 | 254 | 96% | 51% | 0 | – | 0% |
| Stage group (I–IV; A–C ignored) | 468 | 28 | 96% | 6% | 0 | – | 0% |
| Histologic type (ductal, lobular, mixed, special types) | 464 | 388 | 98% | 82% | 14 | 100% | 3% |
| Margins (negative / positive / close) | 443 | 217 | 91% | 44% | 3 | 67% | 0% |
| Lymph nodes examined (count) | 441 | 208 | 63% | 30% | 6 | 0% | 0% |
| Lymph nodes positive (count, H&E) | 432 | 187 | 81% | 35% | 6 | 0% | 0% |

**The bundled cases (38 patients): the rules and the model**

| Field | With a TCGA value | Rules: extracted | Rules: precision | Rules: recall | Model: extracted | Model: precision | Model: recall |
|---|---|---|---|---|---|---|---|
| ER status (positive / negative) | 36 | 15 | 100% | 42% | 0 | – | 0% |
| PR status (positive / negative) | 36 | 15 | 93% | 39% | 0 | – | 0% |
| HER2 status (positive / negative / equivocal; ISH first, then IHC) | 34 | 18 | 89% | 47% | 1 | 100% | 3% |
| pT category (T1–T4, Tis, TX; suffix ignored) | 38 | 22 | 91% | 53% | 8 | 88% | 18% |
| pN category (N0–N3, NX; suffix ignored) | 38 | 24 | 96% | 61% | 0 | – | 0% |
| Stage group (I–IV; A–C ignored) | 36 | 2 | 100% | 6% | 0 | – | 0% |
| Histologic type (ductal, lobular, mixed, special types) | 37 | 28 | 100% | 76% | 1 | 100% | 3% |
| Margins (negative / positive / close) | 33 | 17 | 100% | 52% | 0 | – | 0% |
| Lymph nodes examined (count) | 36 | 12 | 50% | 17% | 0 | – | 0% |
| Lymph nodes positive (count, H&E) | 35 | 10 | 70% | 20% | 0 | – | 0% |

**Reading it.**
- **The model marks where a field is named, not what it says.** Of its 12,693 spans on the
  held-out reports, 12,458 name a field without a result inside them ("ESTROGEN", "MARGINS",
  "LYMPH NODES"); 243 hold a value, mostly a grade (73) or a pT (66). So it extracts a value for
  0 to 54 patients per field where the rules extract 28 to 388, and its recall is 0 to 11%.
- **Where it does give a value, it is often right**: pT 96% (52 of 54), histologic type 100% (14
  of 14), HER2 67% (8 of 12), on the same comparison as the rules. Its node counts are wrong (0
  of 6 and 0 of 6: "2/14" style spans it marks are rarely the totals TCGA records).
- **Beside the rules, per document** (held-out half): 159 field readings agree, 8 disagree, 22
  are read by the model only, 3,023 by the rules only; on the queue's receptor and stage fields,
  66 agree, 5 disagree and 3 are read by the model only. Of the 8 disagreements, 6 are the
  model's first value coming from another part of the report (pTis, pTX or another specimen's
  pT; "LEFT FLANK" as laterality; "close margin" in a comment) and 1 is a label confusion
  ("NEG-HER2" marked as estrogen receptor status, read as ER negative).
- **So the rules stay the documented reading** and the model is a second opinion of weak
  trust: its value is shown, measured and set beside the rules', never merged into them. A
  zero-shot model fine-tuned on research abstracts (not reports) and used untuned is the
  floor of what a model can do here; a model trained on pathology reports, or a local language
  model reading the sentence, would need its own measurement on this split.
- The 38-case numbers are small-sample (the model gives 8 pT values, 7 right).

### On the page
- The model's spans are a second highlight layer (violet underline, its label and score on
  hover), labeled **model inference**, over the rules' yellow **documented** facts; a toggle
  hides them.
- **The rules and the model, side by side**: per document and field, the first value each
  reader gives on the measurement's scales (`documents.comparable`, shared with
  `scripts/prepare_documents.py`): agree, disagree, read by the model only, read by the rules
  only, with the sentences in words ("the rules read HER2 status negative at sentence 3; the
  model marked 'Equivocal 2+' as HER2 status (0.66) at sentence 4, which the rules took for a
  legend").
- The queue gets **"models disagree"** (M1…) when a receptor or stage field (ER, PR, HER2, pT,
  pN, stage) differs: consequence 2, trust weak, both sentences to re-read. The summary gets a
  card with the counts.
- The model card lists both readers' numbers and the model's known failures
  (`documents.NER_FAILURES`).

## Round 2: scanned reports
An imported PDF without a text layer is no longer refused: it becomes a "Scanned report" test
**queued for the local pipeline**, kept by its file name and page count (`imports.ScannedPDF`,
`imports.scanned_test`). The local pipeline (`scripts/documents_pipeline.py scan`) renders each
page (pypdfium2, 144 dpi), reads it with `ibm-granite/granite-docling-258M` (Apache-2.0; an
Idefics3 page-to-DocTags model, converted to text by docling-core), flags text the reader
repeated (`looped`), and runs the rules and the named-entity model on the text exactly as on a
text report; the text it writes is then imported as a report.

On this CPU the reader needs float32 (the checkpoint's bfloat16 is far slower without bf16
matrix units), the KV cache switched on (its generation config turns it off) and one thread
under the shared load (four threads spin against the other jobs: a 10-token forward took 4.4 s
at four threads and 0.2 s at one).

**Text accuracy, four scans** (one thread; load average 6 to 9):

| Scan | Pages | Character accuracy | Word accuracy | Rules' facts kept | Reader looped | Seconds |
|---|---|---|---|---|---|---|
| synthetic scan of TCGA-E9-A1N9's report text | 1 | 98.1% | 92.2% | 2 of 3 | no | 291 |
| synthetic scan of TCGA-A2-A0D2's report text | 2 | 99.2% | 93.3% | 17 of 19 | no | 482 |
| TCGA-BH-A0DS's original report PDF, text layer removed | 1 | 7.5% | 0.7% | 0 of 19 | yes | 1,002 |
| the same, read in two bands per page | 1 | 24.6% | 2.9% | 2 of 19 | yes | 1,300 |
| TCGA-A2-A0CW's original report PDF, text layer removed | 3 | 49.6% | 15.2% | 14 of 17 | yes | 1,436 |
| the same, read in two bands per page | 3 | 51.7% | 22.9% | 11 of 17 | yes | 2,749 |

Accuracy is 1 − edit distance / reference length, case and runs of whitespace ignored. The
synthetic scans are a bundled report's own text typeset (DejaVu Sans), rotated by up to 0.8°,
speckled and blurred, so their reference is exact. The real scans are two bundled cases'
original pathology report PDFs from the NCI GDC (open access; the scans TCGA-Reports was OCR'd
from) with their text layer removed; their reference is TCGA-Reports' cleaned OCR of the same
page, itself imperfect, so those numbers are a floor. "Rules' facts kept": the facts the rules
read in the reference that they also read in the scan's text.

**Reading it.** Clean typed pages are read almost exactly. Dense, small-print fax-quality pages
are not: on both real scans the reader fell into a loop (BH-A0DS: a column of numbers, "110"
repeated; A2-A0CW: "Page 1" written 116 times). Reading each page in two bands (twice
the resolution) helped a little and did not stop the loops. The pipeline flags a looped text
(`looped`: one line making up 30% or more of 12 lines or more), and a scanned report's text is
meant to be checked by a person before it is imported. Four documents are a check, not a
validation; no open corpus of scanned breast pathology reports with a text reference was
found.

## Round 2: the documents over time
- The dated documents (a record entry's or an import's month; TCGA reports are undated) are
  set on the file's axis with the receptor, stage, grade and type each states
  (`documents.history`), and every change between documents is named (`documents.changes`):
  a receptor that flips, a restaging. Both sides stay documented; neither is taken as the
  current one.
- A conflict between documents is settled only by the clinician: the page asks which value
  stands and stores it with a "reviewed" mark under the queue item's own key
  (`documents.resolution`); until then it is "open: only your mark settles it". The D item in
  the queue says when the values changed over time.
- "The record says X, the documents say Y" reaches the discrepancy queue
  (`crosstest._document_rules`) where the integration session's rules did not already: a
  receptor documented against the record's diagnosis row on a file without omics scores (the
  synthetic patient; a TCGA file is covered by the receptor rules against TCGA's clinical
  data), and a later document's restaging against the record's stage (the first documented
  stage was already compared). Rule names are the existing ones ("documented vs recorded",
  "documented vs recorded receptor"), so the uncertainty reducers pick them up.

## Round 2: search and the Spot panel
- Search finds documented facts and model spans as well as sentences: "HER2", "margin", "node
  positive" (`documents.search_findings`, the same synonyms); a row opens its sentence.
- The **Spot panel** of a fact or a span shows its sentence with both layers, the rule (its
  version and wording) or the model (label, score, the characters read), the TCGA field it was
  measured against with both readers' precision and recall (`documents.measured_against`), the
  other reader's value for that field, and the review mark and pin.
- Exports carry both layers: the JSON has the facts, the model's spans, the agreement rows,
  the conflicts and the changes; the CSV a "layer" column (documented or model inference) with
  the model's label and score.

## Test import
The patient file's **Import tests** view opens a dialog (`app/workbenches/imports.py`, checks in
`src/muffle/imports.py`) with one adapter per test type:
- **Lab results, CSV** (month or date, marker, value, unit, optional reference limit): each row
  checked (marker the lab workbench reads, number above 0, the record's unit, a whole month at or
  after the latest report, no second value for a marker and month); rejected rows are listed
  with the reason. Accepted rows become Lab tests and a new report version; the EGTM marker-rise
  rule runs against the file's previous value (with the imported limit when given), so the SOS
  tile, the Tests list, the Timeline and the lab workbench pick them up.
- **A report**, text or PDF with a text layer (pypdf): a Document test, read by the rules above.
  A PDF without a text layer is queued for the local pipeline (round 2, scanned reports).
- **Sequencing results**, a VCF annotated by VEP (INFO `CSQ` with `SYMBOL`, `Consequence` and
  `HGVSp`) or SnpEff (INFO `ANN`), or a GDC or cBioPortal MAF (`Hugo_Symbol`,
  `Variant_Classification`, `HGVSp_Short` or `HGVSp`); plain or gzip, at most 5 MB unzipped and
  20,000 records. Genes and protein changes come from the file's own annotation; nothing is
  called on intake. Kept: protein-altering variants (the TCGA files' consequence set, or the
  MAF's protein-altering classes) in the genes the file's genomics workbench reads (the
  synthetic patient's 8-gene panel, `muffle.longitudinal.DRIVERS`; a TCGA file's 16,
  `muffle.data.tcga.DRIVERS`), with the canonical transcript first. A VCF keeps PASS calls only;
  a MAF is taken as filtered by its pipeline, as the TCGA files are. Rejected rows are listed
  with the reason (off the panel, not protein-altering, no protein change, FILTER, a repeat). A
  MAF must hold one tumor sample, and a file naming MSK-IMPACT sample ids (MSK-CHORD) is refused.
  Allele fractions come from a MAF's `t_alt_count` and `t_depth`; a VCF's are not read, since
  callers store them differently. The variants become one Sequencing test: the genomics
  workbench shows them at their month with the file's sample and assay, and the
  newly-sequenced-driver alert runs on each variant the file had not sequenced before (CIViC
  level A or B treatment evidence, from the live CIViC table; for the synthetic patient's own
  variants, the evidence frozen with its record). A variant file lists calls, not coverage, so a
  gene it doesn't list stays unknown, never wild type.
- **An imaging report**, text or PDF: an Imaging test whose result is the read its sentences
  state (`muffle.imports.imaging_read`, below). The text is also a document of the file, and the
  read is a record event, so the radiology workbench's report page lists it and the lab
  workbench compares markers with it. The test opens on the report's text and the rule's read,
  above the radiology workbench.
- **A slide region image** (PNG or JPEG) and **a DICOM file** (pydicom, header only; patient
  identifiers are never read in): tests "queued for the local pipeline", since the hosted app
  runs no models.
- **A clinician note**, signed with the reviewer's initials: a Clinic note document.

Every import is signed and labeled "imported by <initials> at <time>", adds a report version
(earlier versions are never rewritten), appears in the report export, and lives in the browser
session only: nothing reaches the server's disk, the bundle or the repository. A new version has
no new risk estimate for the synthetic patient (its models are not run on imported results); a
TCGA case keeps its risk, which rests on the tumor sample alone.

### The imaging-report rule
The report is split into clauses (sentence ends, semicolons, and "but", "however", "although",
"except"). A clause **states** a read when it names progression ("progression", "progressive
disease", "progressed"), response ("partial/complete response", "decreased in size", "smaller")
or stability ("stable", "unchanged", "no interval change") with no negation before the words
(no, not, without, negative for, free of, absence of, resolved, ruled out), none after them
("not seen", "not identified", "absent", "excluded") and no hedge anywhere in the clause
(possible, probable, may, might, could, suspicious, concerning for, equivocal, indeterminate,
likely, suggests, versus, cannot be excluded, a question mark). One stated progression makes the
read progression, else response, else stable, else "not stated". A clause names a **new site**
with "new <words> lesion(s)/metastases/nodule(s)/mass(es)/deposits/foci" ("new 1.2 cm hepatic
lesions") or "new lesion(s) in <site>", under the same negation and hedge checks. Only distant
sites count: bone, liver, lung, brain, pleura, adrenal, peritoneum (with their adjectives:
osseous, hepatic, pulmonary…); breast, skin, chest wall and lymph nodes are local or regional.

Alerts (`workspace.add_version`): **progression on imaging** when the read is progression, and
**a new metastatic site** for each new site the file's "Metastatic sites" row lacks. Both are
observed (the report's own words) with trust *moderate*: a text rule read them, not yet a
person. The Imaging test's page shows the read, the clause it rests on and every clause set
aside, with why. The rule reads words only: "enlarging lesions" without the word progression,
or a new lesion under a read of response, raise no progression alert (RECIST would need the
measurements). It is tested on sample sentences (`tests/test_imports.py`), not validated on a
set of real reports: no open imaging-report corpus was used.

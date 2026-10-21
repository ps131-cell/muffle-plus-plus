# Clinical documents: extraction rules and how well they hold up

The clinical documents workbench (`app/workbenches/documents.py`, logic in
`src/muffle/workbench/documents.py`; spec in [`WORKBENCHES.md`](WORKBENCHES.md) §8) shows a
patient file's documents with every breast pathology fact they state highlighted at its
characters. This page says what the rules read, how they were measured and what they miss.
Written 2026-10-20; rules v2 and their measurement on 2026-10-21.

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

## Not used: a named-entity model
`docs/model_survey.md` §8 lists OpenMed-NER-OncologyDetect (278M parameters, Apache-2.0) for
highlighting. It would not run in the hosted app (1 GB of memory, no local model at runtime) and
it tags entity types rather than reading results, so the highlights come from the rules.
Precomputed spans for the bundled reports remain possible later.

## Test import
The patient file's **Import tests** view opens a dialog (`app/workbenches/imports.py`, checks in
`src/muffle/imports.py`) with one adapter per test type:
- **Lab results, CSV** (month or date, marker, value, unit, optional reference limit): each row
  checked (marker the lab workbench reads, number above 0, the record's unit, a whole month at or
  after the latest report, no second value for a marker and month); rejected rows are listed
  with the reason. Accepted rows become Lab tests and a new report version; the EGTM marker-rise
  rule runs against the file's previous value (with the imported limit when given), so the SOS
  tile, the Tests list, the Timeline and the lab workbench pick them up.
- **A report**, text or PDF with a text layer (pypdf; no OCR): a Document test, read by the rules
  above.
- **A slide region image** (PNG or JPEG) and **a DICOM file** (pydicom, header only; patient
  identifiers are never read in): tests "queued for the local pipeline", since the hosted app
  runs no models.
- **A clinician note**, signed with the reviewer's initials: a Clinic note document.

Every import is signed and labeled "imported by <initials> at <time>", adds a report version
(earlier versions are never rewritten), appears in the report export, and lives in the browser
session only: nothing reaches the server's disk, the bundle or the repository. A new version has
no new risk estimate for the synthetic patient (its models are not run on imported results); a
TCGA case keeps its risk, which rests on the tumor sample alone.

# Blood and lab workbench: any analyte, its reference interval and its rules

The blood and lab workbench (`app/workbenches/labs.py`, rules in `src/muffle/workbench/labs.py`,
reference table in `src/muffle/workbench/labs_reference.py`) reads any analyte a clinician
imports, not only the synthetic record's tumor markers. There is no model: every flag is plain
arithmetic on observed values, every threshold names its source, and the placeholders are listed
below. Status: implemented, not validated on a cohort (2026-10-21).

## Where a value's reference interval comes from

In this order, and the page shows which one with every value:

1. **The lab report's own interval**, imported with the value (CSV column "reference interval":
   `3.5-5.0`, `<30`, `>60`, or a plain number read as the upper limit). Reference intervals are
   method-specific, so the patient's own laboratory always wins (`docs/model_survey.md` §4).
2. **The record's** (SYNTHETIC-001's first lab report reads "reference below 30" for CA 15-3).
3. **The reference table** below: Mayo Clinic Laboratories' published adult reference values, a
   reference laboratory's intervals for its own methods, read from the public test catalog on
   2026-10-20. Tagged "interval from a reference laboratory", never as the patient's own.
4. None: the analyte is not in the table and no interval came with it, so no out-of-interval
   flag is possible and the quality checks say so.

Where the female and male intervals differ and the record states no sex, a value is flagged only
when it lies outside both (the wider bounds), and the quality checks list those analytes. The
page has a sex and an age field (kept for the browser session) that switch to the sex's interval
and turn on eGFR.

## The reference table

Intervals verbatim from the Mayo Clinic Laboratories test catalog (test ID and catalog number in
brackets; `mayocliniclabs.com/test-catalog/overview/<number>`), adults. Values are stored in the
first unit; the others convert on import with the factor shown (from the molar mass, or 1 U = 1
µmol/min for enzymes).

| Analyte | Panel | Unit | Adult interval | Converts | Source of the interval | Why it matters here (citation) |
|---|---|---|---|---|---|---|
| CA 15-3 | Tumor markers | U/mL | below 30 (males: use not defined) | kU/L ×1 | Mayo CA153 (81607) | a MUC-1 tumor marker; with CEA, the EGTM panel [1, 2] |
| CA 27.29 | Tumor markers | U/mL | ≤38.0 (males: use not defined; values vary by method) | kU/L ×1 | Mayo C2729 (606583) | a MUC-1 marker, an alternative to CA 15-3 [1, 2] |
| CEA | Tumor markers | ng/mL | ≤3.0 in nonsmokers (some smokers up to about 5.0) | µg/L ×1 | Mayo CEA (8521) | with a MUC-1 marker, the EGTM panel [1, 2] |
| Alkaline phosphatase | Bone and mineral | U/L | female 35-104 (≥17 y); male 40-129 (≥19 y) | IU/L ×1, µkat/L ×60 | Mayo ALP (8340) | raised from bone or liver; GGT tells them apart [3, 4] |
| ALT | Liver | U/L | female 7-45; male 7-55 | IU/L ×1, µkat/L ×60 | Mayo ALT (8362) | hepatocellular injury: liver involvement or drug toxicity [3] |
| AST | Liver | U/L | female 8-43; male 8-48 (≥14 y) | IU/L ×1, µkat/L ×60 | Mayo AST (8360) | as ALT [3] |
| GGT | Liver | U/L | female 5-36; male 8-61 (≥18 y) | IU/L ×1, µkat/L ×60 | Mayo GGT (8677) | raised with ALP: hepatobiliary; normal with raised ALP: bone [4] |
| Bilirubin (total) | Liver | mg/dL | 0.0-1.2 (≥18 y) | µmol/L ÷17.1 | Mayo BILIT (81785) | liver function and biliary obstruction [3] |
| Calcium (total) | Bone and mineral | mg/dL | 8.6-10.0 (18-59 y; 60-90 y: 8.8-10.2, not applied) | mmol/L ×4.008 | Mayo RFAMA (113634) | hypercalcemia of malignancy; read adjusted for albumin [5, 3] |
| Calcium (albumin-adjusted), calculated | Bone and mineral | mg/dL | the total-calcium interval | - | Payne 1973 found it holds after adjustment [6] | calcium read against a low albumin [6] |
| Phosphate | Bone and mineral | mg/dL | 2.5-4.5 (≥18 y, as phosphorus) | mmol/L ×3.097 | Mayo RFAMA (113634) | read with calcium; **no citation checked: placeholder** |
| LDH | General chemistry | U/L | 122-222 (≥18 y) | IU/L ×1, µkat/L ×60 | Mayo LD (8344) | prognostic of tumor burden, not specific [7] |
| Albumin | General chemistry | g/dL | 3.5-5.0 | g/L ÷10 | Mayo RFAMA (113634) | liver synthesis, nutrition; needed to read calcium [6] |
| Creatinine | Kidney | mg/dL | female 0.59-1.04 (≥16 y); male 0.74-1.35 (≥15 y) | µmol/L ÷88.42 | Mayo CRTS1 (48216) | kidney function for dosing and bone-targeted agents [3] |
| eGFR (2021 CKD-EPI), calculated | Kidney | mL/min/1.73 m² | 60 or above | - | Mayo CRTS1 (48216) | kidney function from creatinine, age and sex [8] |
| Hemoglobin | Blood count | g/dL | female 11.6-15.0; male 13.2-16.6 (≥18 y) | g/L ÷10, mmol/L ×1.611 | Mayo CBC (9109) | anemia under chemotherapy or a CDK4/6 inhibitor [9] |
| White cells | Blood count | ×10⁹/L | 3.4-9.6 | ×10³/µL, K/µL, G/L ×1; /µL, /mm³ ÷1000 | Mayo CBC (9109) | leukopenia under a CDK4/6 inhibitor or chemotherapy [9] |
| Neutrophils (absolute) | Blood count | ×10⁹/L | 1.56-6.45 | as white cells | Mayo CBC (9109) | neutropenia, the commonest grade 3-4 toxicity of palbociclib [9] |
| Platelets | Blood count | ×10⁹/L | female 157-371; male 135-317 | as white cells | Mayo CBC (9109) | thrombocytopenia, or marrow involvement [3] |

Any other analyte can be imported (glucose, magnesium, ferritin ...). It keeps the unit it was
reported in (one unit per import file, or the row is rejected), shows under "not in the reference
table", and is flagged only against the interval its lab report gave.

## Rules

| Flag | Applies to | Rule | Threshold source | Status |
|---|---|---|---|---|
| above / below limit | every analyte with an interval | outside the value's interval | the lab report, the record or the reference table (named per value) | observed against that source |
| rising | tumor markers | at least 25% above the previous value; unconfirmed until a second specimen within a month | EGTM guidance; Hayes et al. 1986 | literature |
| falling | tumor markers | the previous value at least 25% above this one | the EGTM ratio the other way round | placeholder |
| large rise / large fall | other analytes | 30% from the previous value | none: not a reference change value | placeholder |
| CTCAE grade | neutrophils, white cells, platelets (1-4); hemoglobin (1-3) | grade bands counted from the lower limit | NCI CTCAE v5.0 [10] | guideline |
| adjusted calcium | months with calcium and albumin | calcium − albumin + 4.0 (mg/dL, g/dL) | Payne 1973 [6] | model inference (published equation) |
| eGFR | creatinine, with age and sex set | 142 × min(Scr/κ,1)^α × max(Scr/κ,1)^−1.200 × 0.9938^age × 1.012 if female | 2021 CKD-EPI [8] | model inference (published equation) |
| EGTM confirmation, therapy windows, baseline band, kinetics | tumor markers | as before (see the rules card) | EGTM; Kiang 1990, Sonoo 1996; placeholders | literature and placeholders |
| cross-analyte hypothesis | ALP, calcium (bone); ALT, AST, GGT, bilirubin, ALP (liver) | raised or rising values from 3 months before an imaging report naming the site on; a same-month GGT says which source fits ALP | Stewart 2005 [5], ESMO 2011 [3], Mayo interpretation [4]; window placeholder | hypothesis, for clinician review |

Quality checks per analyte: a unit, positive values, an interval and its source, the interval
unchanged across the series (a changed interval may mean a changed method: EGTM asks for care),
no gap over 6 months (placeholder). Then the record: the EGTM panel (a MUC-1 marker with CEA),
the sex for sex-specific intervals, and eGFR's inputs.

Search answers analytes and panels, and says when it cannot see something: "neutrophils" on a
record without a blood count answers that a blood count panel would show it; "liver lesions"
answers that lab results cannot see lesions and imaging does.

## Placeholders (none of these is validated)

- falling (tumor markers): 25% the other way round; large rise or fall (other analytes): 30%
- gap: 6 months; therapy caution window: 2 months; hook-effect factor: 10×
- kinetics: log-linear fit over the last 3 values; baseline band: longest run without a change flag
- cross-analyte window: 3 months before the imaging report
- phosphate's "why it matters" has no checked citation
- one adult band per analyte: calcium's 60-90 years band and other age bands are not applied

## What this workbench cannot see

- Lesions, their size or site: imaging does. A raised value is not evidence of progression by
  itself (ASCO: tumor markers are adjuncts, not used alone [1]).
- A change of assay or laboratory that the record does not state; only a changed interval shows.
- Analytical and within-person variation: the change flags know no reference change value
  (EuBIVAS biological variation data were not read; planned).
- Whether a raised liver value comes from metastases or from a drug: the hypotheses name both.

## Import

`muffle.imports.parse_labs` checks each row at the boundary: a marker name, a positive number, a
unit the table converts for that analyte (a unit it does not know is rejected with the reason), a
whole month or a date with the date of month 0, nothing before the latest report, no duplicate,
and an optional interval. `LAB_EXAMPLE` (the dialog's "Example CSV") is a synthetic CBC and
chemistry for SYNTHETIC-001 at months 25 and 27, in mixed units, with one analyte the table does
not list. Imported for the browser session only.

## Sources

1. Van Poznak C et al. Use of biomarkers to guide decisions on systemic therapy for women with
   metastatic breast cancer: ASCO clinical practice guideline. *J Clin Oncol* 2015.
   doi:10.1200/JCO.2015.61.1459
2. EGTM breast cancer recommendations (egtm.eu); Molina R et al. *Tumour Biol* 2005.
3. Cardoso F et al. Locally recurrent or metastatic breast cancer: ESMO Clinical Practice
   Guidelines. *Ann Oncol* 2011;22 Suppl 6:vi25-30. doi:10.1093/annonc/mdr372
4. Mayo Clinic Laboratories test catalog, interpretation sections of ALP (8340) and GGT (8677).
5. Stewart AF. Hypercalcemia associated with cancer. *N Engl J Med* 2005.
   doi:10.1056/NEJMcp042806
6. Payne RB et al. Interpretation of serum calcium in patients with abnormal serum proteins.
   *Br Med J* 1973. doi:10.1136/bmj.4.5893.643
7. Petrelli F et al. Prognostic role of lactate dehydrogenase in solid tumors. *Acta Oncol* 2015.
   doi:10.3109/0284186X.2015.1043026
8. Inker LA et al. New creatinine- and cystatin C-based equations to estimate GFR without race.
   *N Engl J Med* 2021. doi:10.1056/NEJMoa2102953
9. Finn RS et al. Palbociclib and letrozole in advanced breast cancer (PALOMA-2). *N Engl J Med*
   2016. doi:10.1056/NEJMoa1607303
10. National Cancer Institute. Common Terminology Criteria for Adverse Events (CTCAE) v5.0, 2017.

DOIs checked on PubMed on 2026-10-20; Mayo intervals read from the public catalog pages the same
day. The NORIP intervals (Rustad et al., *Scand J Clin Lab Invest* 2004,
doi:10.1080/00365510410006324) were considered but their numbers could not be read from an open
page, so they are not used.

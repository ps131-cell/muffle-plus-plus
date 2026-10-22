# The Timeline view: the record over time, time travel and what each version brought

The Timeline is the longitudinal view of a patient file (`docs/VISION.md` part two;
`docs/WORKSPACE.md`, Screens, 5). Page: `app/timeline_page.py`; data: the pure functions of
`src/muffle/timeline_view.py` (no Streamlit, no model run, nothing new estimated); tests:
`tests/test_timeline_view.py` and the time-travel and import steps of `tests/test_app.py`.
Status: implemented (2026-10-22), on SYNTHETIC-001 (synthetic, written by hand) and the TCGA
files; not reviewed by clinicians.

## The event chart

One horizontal chart (Altair) on a month axis from the diagnosis to the latest entry. Months
count from the first tumor sequencing for SYNTHETIC-001 (diagnosis at month −40) and from the
tumor sample for a TCGA file (month 0). One lane per kind, shown only when the file has an entry
on it; the caption names the empty ones.

| Lane | What sits on it | Comes from |
|---|---|---|
| Report versions | one node per report version | `PatientFile.versions` |
| Treatments | a ▶ at each drug's start and a bar per drug | `Version.treatments` and the entry's words |
| Imaging | imaging reports (reads in the report's words) | tests of the imaging workbench |
| Labs and tumor markers | lab values (CA 15-3 and the rest) | tests of the labs workbench |
| ctDNA | the synthetic plasma series, one point per sample | `muffle.timeline.CTDNA` (synthetic) |
| Sequencing and omics | tumor sequencing; a TCGA file's data layers and clinical record | mutations, omics and record tests |
| Pathology and documents | the diagnosis's pathology report, slides, pathology reports | slides and documents tests |
| Clinic visits | clinic notes | Clinic note tests |
| Imported tests | every test imported in this browser session | versions added by `workspace.add_version` |

**What each point holds** (on hover): its lane, when (month, or for a TCGA test "the tumor
sample", with the date its text carries when the documents rules find one: the de-identified TCGA
reports mostly carry none), what (the test's name; tests of one version on one lane and month
share a point), the result, its evidence label, the report version it created, that version's
entry in the record's own words, and its source ("the record", or "imported by <initials> at
<time>; kept for this browser session only"). Colors: blue from the record, orange imported in
this session, red an SOS alert.

**SOS alerts and progressions** are red ▼ marks on the lane of the test that raised them (a
progression and a new site on its imaging report, a marker rise on its lab value, a new driver on
its sequencing), with the alert's evidence label, trust, rule and threshold; the 12-month risk
jump (placeholder threshold) sits on the Report versions lane. Several alerts of one test share a
mark.

**Treatment bars.** The record holds start dates only. A drug's bar runs to the next treatment
entry that does not name it, or stays open to the latest entry (drawn lighter, "no stop recorded"
on hover): "adds alpelisib to fulvestrant" at month 13 ends palbociclib and keeps fulvestrant.
This is a display rule, not a recorded stop date; bars that overlap stack.

**Export.** The chart's toolbar has Download as PNG (Streamlit's own); the report's Markdown
export carries a Timeline section (below).

## Time travel

A click on any point opens the file as of the report version that point created (a ctDNA sample
opens the version it joined: the first at or after its month). So do the compare view's "Jump to
this version" buttons and the report version slider. The rule:

- The report, the tests, the attention queue, the risk chart, the "new in this version" card,
  the versions table, the compare view and the export are **as of the viewed version**: later
  entries are not in them.
- The event chart keeps the **whole record** visible, so any point can be clicked, forward or
  back: entries after the viewed version are faded behind a dashed line at its month.
- A banner on every view says which version is open ("You are viewing month 11 …") with **Back to
  latest**. An import opens the file on its new latest version.

## New in this version

A card for the viewed version (`timeline_view.changes`): what arrived in the record's words and
its source; the tests added (each with Open, landing on its workbench); the treatments started;
the observed rows that changed (before → after); the SOS alerts raised (evidence label, trust,
placeholder threshold chip, Open on the evidence); the risk move (`crosstest.diff_versions`,
model inference) with its one-change-at-a-time attribution, or why there is none (no estimate
before month 0; imports are not scored); and the workbench findings that changed: every
workbench's `summary()` at this version against the previous one (`timeline_view.summary_changes`:
added, changed, removed), each with Open landing on its evidence. "Open its report" opens the
report as of this version. The first version brings everything it holds.

## Risk over time, with the record beside it

SYNTHETIC-001 only (a TCGA file has one estimate, from its one sample). The 12-month risk of the
record-so-far models (band: range of 5 models) and the diagnosis-only baseline, labeled model
inference: scores of a synthetic patient by models trained on MSK-CHORD, calibration not checked.
Overlays the clinician toggles, each observed, with its provenance under the chart:

- **CA 15-3** on its own right axis (U/mL): the record's values and imported ones.
- **Treatments**: shaded spans by the bar rule above.
- **Imaging reads**: a line per imaging report, red where it reads progression.
- **ctDNA**: the synthetic series' allele fractions in a panel below (hollow points at 0 = not
  detected; dashed line: the 0.1% detection limit, a placeholder).

Nothing new is predicted: imports add values to the overlays, not to the risk line.

## Growth through imports

An imported lab CSV, report, VCF or MAF, imaging report, image, DICOM file or note adds a version
(`workspace.add_version`): a node on the top lane labeled "month X · imported by <initials> at
<time>", its tests on the Imported tests lane, its alerts in red; the "new in this version" card
lists them; the CA 15-3 overlay takes imported values; the export's Timeline section lists the
version with its source. Versions in the same month are set apart by 0.6 month on the axis so each
can be clicked (their hover gives the true month). Imports last for the browser session only.

## TCGA files

One tumor sample per patient, so the file starts with one version: the baseline sample's tests
at month 0 (data layers, mutation panel, scored slides, pathology reports with the dates their
text carries, public imaging studies) and the page says "One sample; the timeline grows with
imports." Each import adds a version after it.

## Export

`workspace.report_markdown` gains "## Timeline: what each version brought": per version up to
the exported one, its label and source, the entry, the tests added, treatments started, observed
rows changed, SOS alerts with their evidence label and trust, and the risk line where it moved or
where an import explains why it did not.

## Placeholders and limits

- Treatment bar ends are a display rule (above), not recorded stop dates.
- The SOS rules' thresholds keep their own status (the risk jump is a placeholder; see Methods
  and validation).
- The ctDNA series is synthetic and its detection limit a placeholder (`docs/ctdna.md`).
- SYNTHETIC-001's risk scores are synthetic-patient scores; nothing from MSK-CHORD is shown.
- Dates: SYNTHETIC-001 has months, not calendar dates; TCGA's de-identified reports mostly carry
  no date, and a date found in a text is shown, not placed on the axis.

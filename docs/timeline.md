# The Timeline view: the record over time, time travel and what each version brought

The Timeline is the longitudinal view of a patient file (`docs/VISION.md` part two;
`docs/WORKSPACE.md`, Screens, 5). Page: `app/timeline_page.py`; data: the pure functions of
`src/muffle/timeline_view.py` and `src/muffle/version_diff.py` (no Streamlit, no model run,
nothing new estimated); tests: `tests/test_timeline_view.py`, `tests/test_version_diff.py` and the
time-travel and import steps of `tests/test_app.py`. The version diff and the lanes' restyle:
2026-10-28.
Status: implemented (2026-10-22), on SYNTHETIC-001 (synthetic, written by hand) and the TCGA
files; not reviewed by clinicians.

## The event chart

One horizontal chart (Altair) on a month axis from the diagnosis to the latest entry. Months
count from the first tumor sequencing for SYNTHETIC-001 (diagnosis at month −40) and from the
tumor sample for a TCGA file (month 0). One lane per kind, shown only when the file has an entry
on it; the caption names the empty ones.

| Lane | What sits on it | Comes from |
|---|---|---|
| Report versions | one node per report version (v1 is the first), marked by its risk shift since the one before: ▲ red up, ▼ green down beyond the 5 models' spread, ● gray within it or no estimate; the latest ringed | `PatientFile.versions`, `version_diff.risk_delta` |
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
this session, red an SOS alert. A report version's point also says how the risk moved since the
version before, in words. Lanes are compact rows, every other one on a gray band; the span between
the two versions compared above the chart is shaded.

**SOS alerts and progressions** are red ◆ marks on the lane of the test that raised them (a
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
opens the version it joined: the first at or after its month). So do the compare view's "Go to v…"
buttons, a click on a row of the versions table and the report version slider. The rule:

- The report, the tests, the attention queue, the risk chart, the versions table, the compare
  view and the export are **as of the viewed version**: later entries are not in them.
- The event chart keeps the **whole record** visible, so any point can be clicked, forward or
  back: entries after the viewed version are faded behind a dashed line at its month.
- A banner on every view says which version is open ("You are viewing month 11 …") with **Back to
  latest**. An import opens the file on its new latest version.

## Compare two versions (the version diff)

First on the page (`version_diff.diff(pf, a, b, data)`, drawn by `timeline_page.compare`). A
two-handle slider picks the two versions (labeled "v12 · month 12"); it opens on the viewed
version and the one before, and the file's **Compare versions** opens it on the latest and the
previous. The diff reads top down:

1. **The risk delta** as a chip, with the label model inference. SYNTHETIC-001: the 12-month risk
   in points with both values, and both versions' ranges across the 5 models (seeds 0–4). The
   move counts as beyond the models' uncertainty when the two ranges do not overlap: ▲ red up,
   ▼ green down (the report's risk metric shows a rise red and a fall green); when they overlap
   the chip is gray, "within the model's uncertainty". A change of landmark model is named. A TCGA
   estimate is a cohort percentile that rests on the tumor sample alone, so an import leaves it
   as it was ("= risk unchanged"; the model gives no per-patient interval). Versions without an
   estimate say why (before month 0; imported results are not scored).
2. **Why the risk moved**: each version's one-change-at-a-time attribution in between, and the
   sentence that a delta is the difference between two snapshots of the record, not a trend: it
   forecasts nothing.
3. **Counts** (+ added, ~ changed, − removed), then, folded when the list is long:
   **findings that changed** (the record's rows and every workbench's finding cards,
   `summary()` at both versions), **tests added** (with the version they came in and, for an
   import, who and when), the **attention queue** items new, reworded or gone (an item re-keyed
   by a newer specimen with the same words is no change; one gone and one new about the same
   test are one item reworded), and the **summary note**'s sentences that changed. Each carries
   its evidence label and "Open" on its evidence, as of the version that holds it (a finding gone
   by the later version opens as of the earlier one).

Dates, values and version identifiers are monospace; a long text shows only the words that
changed (`version_diff.inline`): the old struck through, the new in bold, the unchanged run cut
to its ends. `version_diff.version_delta_line(pf, i)` is the same comparison as one sentence for
the report header.

## Every version

A table, newest first: the version (the latest and the viewed one named), its month, the 12-month
risk and its shift since the version before (▲ / ▼ in red and green beyond the spread, ≈ within
it), what arrived, tests and SOS alerts added, the source. A click on a row opens the file as of
that version.

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
<time>", its tests on the Imported tests lane, its alerts in red; the version diff opens on it
against the version before and lists them; the CA 15-3 overlay takes imported values; the export's Timeline section lists the
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
- "Beyond the models' spread" compares the two versions' ranges across 5 seeds; it is the models'
  own disagreement, not a calibrated confidence interval (calibration is not checked), and a TCGA
  estimate has no per-patient interval at all.
- SYNTHETIC-001's risk scores are synthetic-patient scores; nothing from MSK-CHORD is shown.
- Dates: SYNTHETIC-001 has months, not calendar dates; TCGA's de-identified reports mostly carry
  no date, and a date found in a text is shown, not placed on the axis.

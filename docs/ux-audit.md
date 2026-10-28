# UX audit, 2026-10-28

Two passes over the app as it was on main at 67647db (QA round 3 merged), then every finding in
three tiers with what was done about it. Screens looked at in headless Chromium at 1280 × 900
and 800 × 900 px, light, the sidebar open (as Streamlit keeps it at both widths): the Patients
page, SYNTHETIC-001's report and Tests view, Case 299's report and genomics workbench,
SYNTHETIC-001's Timeline, Methods and validation. The rules that came out of it are in
`docs/ux.md` §8; the decision in `docs/decisions.md` (2026-10-28).

## Pass 1: the design critic

- **Hierarchy.** A file's first screen is chrome. At 1280 px: breadcrumbs, the identity line,
  the views, an eight-button action row on two lines, a caption repeating the diagnosis and the
  disclaimer, a two-line yellow notice, the version slider, a 28 px report title, the chip row
  and the summary; the SOS tile, the one thing that must be seen first, starts at y ≈ 820. At
  800 px the action row takes four lines and no finding is on the first screen.
- **The trust chain is scattered.** The risk model, the driver mutations and their CIViC
  evidence are 1,000–3,000 px apart: on Case 299 the risk at y ≈ 4,400 and the CIViC items at
  y ≈ 5,300 of 6,553 px; on SYNTHETIC-001 the CIViC block at y ≈ 4,300 of 5,638. Provenance
  exists only on the cards' "Why?": the risk tiles, the variants and the CIViC lines carry no
  source, model version or evidence item id.
- **Typography.** Streamlit's default Source Sans at 16 px; a 44 px page title, 28 px
  subheaders, 36 px metric values ("0.93" set like a headline); variants, pointers, ids, money
  and counts in proportional type ("MAP3K1 S588Ffs\*3" reads as prose); inline code in green
  (#137a33, Streamlit's default code colour), so a pointer like `L4` reads as "normal".
- **Colour.** The chips are one coherent system (observed blue, inference violet, hypothesis
  orange, trust green/orange/red, placeholder always orange), but nothing codes a CIViC level
  or a variant's severity, and a risk chart's red/blue sits beside a metric's red/green delta.
- **Spacing.** 6 rem above the content, 5 rem side gutters at 1280 px (820 of a 980 px column),
  10 rem below; cards and tiles fixed at 220 px leave ~130 px empty at the right of every row;
  card text wraps at ~150 px, so cards run 300–400 px tall.
- **Generic defaults.** 40 px, 8 px-rounded bordered buttons for everything, including the
  three "Review" popovers on one CIViC block and the queue's row buttons; bordered boxes around
  everything; the federated training as a graphviz drawing of boxes; the system's status hidden
  in a closed "About this system" expander.
- **800 px.** 468 px of content: the action row four lines, cards two a row, the reports 7,900
  and 9,860 px long.

## Pass 2: a first-time, impatient user

1. **Patients.** A title, a sentence, the disclaimer, Start here, a four-step tour and a search
   box come before the list, which starts at y ≈ 1,220. Three search fields on one screen (the
   file picker, Search every file, the list's search): which finds my patient?
2. **Open SYNTHETIC-001.** "SOS: 7 open" in the header, but the SOS tile is below the fold;
   the yellow notice says "MSK-CHORD timelines" on the first screen (jargon before content).
3. **"Why 60%?"** The answer (what changed since the last version) is ~3,000 px down, under the
   attention queue and the cohort lookups.
4. **"What evidence is there for this mutation?"** Scroll past the queue, Where this patient
   sits, Similar patients, the record and the risk; the CIViC lines name no evidence item and
   say nothing on hover.
5. **Case 299's tumor-board note** without a key on the server: "Write the note with Nemotron"
   disabled, and the reason only on hover: an unmotivated control.
6. **"Is this costing money?"** Nothing on screen: the $25.50 cap and the spend live in code and
   a ledger file; the live-notes bar appears only on a server with a key.
7. **"Which hospitals trained this?"** The closed sidebar expander says "FedAvg across 3
   simulated hospitals" and one C-index; the per-site numbers are a sentence on Methods.
8. **Tests.** The launcher is clear; tiles stop at three a row with white space; "nothing
   flagged" is set as large as a finding.
9. **A workbench (genomics).** Dense but legible; the part headings (Overview, Details, Spot
   panel) are as loud as the title.
10. **Timeline.** Works; owned by the timeline session (below).
11. **Methods.** 17,900 px at 1280; the contents box helps; two 404s in the console on load.

## Findings by tier

| | Finding | What happened |
|---|---|---|
| **Critical** | | |
| C1 | The SOS tile below the fold on a laptop; no finding on the first screen at 800 px | **Done.** Top gap 6 → 4.5 rem, the identity caption without the repeated diagnosis, the synthetic notice compact, the action row's buttons 28 px and quiet (four lines → three at 800 px), a 17 px report title: the SOS tile starts at y = 629 (SYNTHETIC-001) and 409 (Case 299) at 1280 px, 784 and 564 at 800 px |
| C2 | The risk model, the mutations and their CIViC evidence 1,000–3,000 px apart | **Done.** The cockpit: three columns at 1280 px, stacked at 800 px (`docs/ux.md` §8) |
| C3 | No provenance on the risk, the variants or the CIViC items | **Done.** Hover on the risk heading (source data, method, release, each site's C-index, endpoint), on each variant (test, sample, assay, reads, VEP consequence and release, AlphaMissense, CIViC count), on each ladder rung, on each CIViC item (EID, level, direction, profile, match, disease), on each next item (source, reason, threshold); click: Open into the genomics workbench, the CIViC link, Open at each queue item |
| C4 | The case-note budget invisible | **Done.** The sidebar's status table and bar (spend on this server's ledger against the cap), the tumor-board note's status line, the Methods card "Case note service" (cap, spend, prices, how a call is refused) |
| **High impact** | | |
| H1 | Generic type and controls (16 px Source Sans, 36 px metrics, 40 px rounded buttons) | **Done.** IBM Plex Sans and Mono, 15 px base, compact headings, metrics, buttons, tabs, expanders, alerts |
| H2 | Inline code (pointers) in green | **Done.** Near-black on light grey, 14:1 |
| H3 | Variants, ids, amounts in proportional type | **Done** in the cockpit, the status table and the metric tiles (monospace); the workbench pages' own text is theirs (left) |
| H4 | Cards and tiles fixed at 220 px with an empty strip on the right | **Done.** A grid that fills the row: four a row at 1280 px, two at 800 px; card text 13 px |
| H5 | No colour code for CIViC levels or variant severity; red/blue vs red/green for risk | **Done** for levels (A–B green, C–E orange) and severity (Ensembl VEP: high red, moderate orange, low and modifier grey), on the Methods page's Colour code; risk changes in the cockpit red/blue like the charts. A metric tile's delta stays red/green (left: Streamlit's control; said in the legend) |
| H6 | Federated training's sites and C-indexes hidden | **Done.** The sidebar lists each simulated site's held-out C-index; Methods shows one status table (patients, deaths, held out, C-index, layer coverage) instead of the graphviz drawing |
| H7 | The tumor-board note's disabled buttons | **Done.** Only the buttons that can work; a status line says why the rest are not there |
| H8 | The action row loud and four lines at 800 px (QA R3-8) | **Done.** Same buttons and order, smaller, grey until hover: two lines (62 px) at 1280 and at 800 px. Under 1024 px its Methods link and How to read this are hidden: the sidebar's navigation and the breadcrumb's "?" hold them |
| H9 | Workbench part headings as loud as the title | **Done.** Small capital labels over a hairline (`_page.py`'s h4, by CSS) |
| H10 | The Patients page: three blocks and three search fields before the list | **Left** (decided in round 11, user-reviewed: Start here, the tour and Search every file stay above the list); the compact type lifts the list by ~200 px |
| **Nice to have** | | |
| N1 | The sidebar's blurb repeats the Patients page's intro | **Done.** One line and the disclaimer |
| N2 | "Review" popovers bordered on every line | **Done.** Tertiary (text) style |
| N3 | Emoji and Material icons mixed (🗂️ 📖 🗳️ in the navigation, 🔴 in the list) | **Left:** the list's "🔴 n open" is asserted by tests and named in the video |
| N4 | The chip row's chevrons read as dropdowns | **Left:** they open each label's meaning; the affordance is right |
| N5 | The version slider long and thin for 16 versions | **For the timeline session** (it owns the version selector) |
| N6 | Methods: two 404s in the console on load | **Left:** Streamlit's own `/methods/_stcore/health` and `host-config` requests (a page address's path; it retries at the root); nothing of ours |
| N7 | Bold paragraphs as headings: no heading outline for a screen reader on the report | **Left:** headings would join the Methods contents test and the anchors; after the freeze |
| N8 | A first load paints Streamlit's default layout for ~0.5–2 s before the theme sheet (a style-only `st.html` applies after the first elements) | **Left:** reruns keep it (measured); the config's fonts and colours apply from the first paint |

## Before and after, measured

Page height in px (headless Chromium, `~/muffle-ui` on 67647db, then this branch):

| Screen | 1280 px | 800 px |
|---|---|---|
| Patients | 1,933 → 1,570 | 2,404 → 1,996 |
| SYNTHETIC-001 · Report | 5,638 → 4,100 | 7,920 → 6,031 |
| Case 299 · Report | 6,553 → 4,767 | 9,862 → 7,797 |
| SYNTHETIC-001 · Tests (labs workbench) | 7,123 → 5,897 | 9,405 → 7,818 |
| Case 299 · Genomics workbench | 7,026 → 5,595 | 9,215 → 7,540 |
| SYNTHETIC-001 · Timeline | 4,009 → 3,431 | 5,092 → 4,322 |
| Methods and validation | 17,892 → 15,419 | 23,894 → 21,471 |

No exception, error box, cut text or sideways scroll on any of them, before or after; the
overlap check flags a CIViC line's wrapped link against its id (a two-line link's box, not an
overlap on screen). The report's risk model, mutations and CIViC items now sit within one
screen of each other: the cockpit spans y = 1,277–2,340 on Case 299 and 1,472–2,196 on SYNTHETIC-001 at 1280 px (stacked at 800 px: 2,033–4,040 and 2,088–3,428).

## For other owners

- **Timeline** (timeline session): N5; the version slider and Compare versions are unchanged.
- **Video and Devpost text** (`docs/video.md`, `docs/submission.md`): the sidebar's About this
  system is open by default and reads "Held-out C-index 0.728" and "Case agent live" as table
  rows; shot 3's scroll from the cards to **Attention** now passes the cockpit; shot 4's
  **Show the saved note** is still there for Case 299. Re-walk after the freeze.
- **`CLAUDE.md`** still says "freeze Oct 28"; the decision of 2026-10-28 moves it to Oct 29
  10:00 CDT.

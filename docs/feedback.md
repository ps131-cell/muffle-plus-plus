# Feedback: learning from clinicians, first version

Status: **implemented** (2026-10-22): the ledger, the rates, the export and the import. Every
step that would *learn* from the marks is **planned (roadmap)** and runs nowhere. Code:
`src/muffle/feedback.py`, page `app/feedback_page.py` (the app's **Feedback** page, next to
Methods and validation). Vision: [`VISION.md`](VISION.md), part four.

## What it does today
- Every review mark a clinician makes in a patient file (agree, disagree, second look, or
  "reviewed" from the attention queue; `docs/WORKBENCHES.md` §1 item 6) is one **ledger**
  record: patient, finding kind, the finding as its card words it, mark, reviewer initials,
  time, the **model or rule behind the finding** with its version and inputs, and the finding's
  **evidence label** (observed, model inference, hypothesis).
- The Feedback page shows the ledger with filters (patient, finding kind, mark, reviewer); the
  share of findings marked disagree **per model or rule** (or per finding kind) with a 95% Wilson
  interval; the disagreed findings as a queue whose **Open** lands on the finding in its patient
  file; a summary per reviewer; the download and upload of the ledger; and a roadmap card.
- **Methods and validation**: each model and rule card shows "N findings reviewed, M disagreed
  this session" (zero when nothing was marked), and the known-failures list gains one row per
  model or rule that clinicians disagreed with this session.
- **Report export**: a "Feedback" section after the review marks: this patient's marks counted
  per finding kind, and each disagreed finding with its model or rule.

## What happens with the marks
- They stay in the **browser session** (`st.session_state.reviews`) and in the **files the
  clinician downloads** (the report export, the ledger). Nothing is sent anywhere or stored on
  the server; closing the tab ends them.
- **Nothing trains on them.** No model, rule, cutoff or alert changes because of a mark. A
  disagreement rate here is a count of one session's judgments, not a measured error rate; few
  marks say little, and the interval says how little.
- Storing a mark, updating a research dataset and retraining a model are different steps
  (VISION part four). Only the first exists.

## Where the model or rule comes from
A mark stores only the finding's words and its key (`workspace.finding_key(pf, kind, *parts)`).
`feedback.source_of(key, what)` derives the model or rule from the kind and parts, so a record
never trusts a method name from a file:

| Finding kind | Model or rule (`feedback.SOURCES`) | Evidence label |
|---|---|---|
| alert | tumor marker rise (EGTM); progression and new sites on imaging; newly sequenced driver (CIViC A/B); risk jump (placeholder) | observed; driver: observed + hypothesis; risk jump: model inference |
| risk | MSK-CHORD landmark models (SYNTHETIC-001) or the multi-omic survival model (TCGA) | model inference |
| civic, variant, cn, pathway | CIViC treatment evidence, variant calls, copy-number calls (ASCAT3), genomics pathway map | hypothesis, observed, observed (ploidy: + inference), hypothesis |
| lab, ctdna | lab result rules, ctDNA monitor rules | observed |
| slide | slide tile findings (tissue head, nuclei, slide rules) | model inference |
| omics, pathway_protein, methylation | PAM50 call, receptor consistency, pathway and immune scores, data-layer features, RPPA pathways, promoter methylation | inference (features: observed; methylation index: hypothesis) |
| document | clinical document extraction (`documents.RULES_VERSION`) | observed (documented) |
| discrepancy | tests that disagree (cross-test rules) | per rule: observed, plus inference or hypothesis where a side is one |
| evolution | evolution table, trial matching | hypothesis |
| imaging | radiology report reading; radiology image models (MedSAM, mammoscreen, MONAI) | observed; model inference |

A version is the one the code names (a rule set's version, a model's release or design); where
the code names none it reads "app build <digest>", the digest of the app's code when the ledger
was made.

## The export: a feedback dataset (schema `muffle-feedback/1`)
JSON lines (`muffle_feedback.jsonl`), UTF-8, one record per mark, newest first:

| Field | Type | Meaning |
|---|---|---|
| `schema` | text | `muffle-feedback/1` |
| `patient` | text | the patient file's id (`SYNTHETIC-001`, `Case 661`) |
| `patient_kind` | text | `synthetic` (written by hand) or `TCGA-BRCA` (public case, simulated hospital) |
| `kind` | text | the finding kind (`workspace.FINDING_KINDS`) |
| `finding` | text | the finding as its card words it |
| `key` | text | its `finding_key`: `patient\|kind\|parts…` |
| `parts` | list | the key's parts after the kind |
| `mark` | text | `reviewed`, `agree`, `disagree` or `second look` |
| `reviewer` | text | initials as typed (≤ 5 characters, may be empty); nothing checks who typed them |
| `at` | text | `YYYY-MM-DD HH:MM`, the browser session's local time |
| `method` | text | the model or rule behind the finding (`feedback.SOURCES`) |
| `method_type` | text | `model` or `rule` |
| `method_version` | text | its version, or `app build <digest>` |
| `methods_card` | text | its card on Methods and validation |
| `inputs` | text | what it reads, in words (never the patient's values) |
| `evidence` | text | observed, model inference or hypothesis, as the finding is labeled |

No patient data beyond what the finding card already shows: the finding's words, never the
omics values or a record's text. No MSK-CHORD patient appears (the synthetic patient's risk
findings name model estimates for a synthetic person, as the report export does).

## The import
The page loads a downloaded ledger back into the session. `feedback.load` checks at the
boundary and rejects a line, with the reason, when: the file is over 2 MB or not UTF-8, there
are over 5,000 records, a line is not a JSON object, a required field is missing or not text,
the schema is not `muffle-feedback/1`, the patient is not in this app, the finding kind or mark
is unknown, the key does not name the record's patient and kind, the initials are longer than
5 characters, or the time is not `YYYY-MM-DD HH:MM`. Only `finding`, `mark`, `reviewer` and
`at` are taken from the file; method, version, inputs and evidence are derived again from the
key. When a finding is marked both in the session and in the file, the later mark wins (the
session's on a tie).

## Roadmap (planned; not running)
What a training round would do with the ledger, once consent, ethics approval and data
agreements exist:
1. **Re-calibrate placeholder cutoffs** (`app/methods_page.py`, "Every placeholder") against the
   findings clinicians disagreed with, then validate on held-out patients before use.
2. **Retrain the slide tissue head** with disagreed tiles as new labels, once a pathologist
   confirms them.
3. **Federated rounds across sites**: each hospital keeps its marks and data and sends only
   model updates, as the survival model is trained today across simulated hospitals with NVIDIA
   FLARE (`docs/HACKATHON.md`). Shown with simulated sites until real ones join.

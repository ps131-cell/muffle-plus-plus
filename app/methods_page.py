"""The Methods and validation page (docs/WORKSPACE.md, "Product framing"): one card per model and
per rule the app uses, each with its status, numbers, sources and known failures; federated
training; the data sources and their licenses; then every known failure in one list and every
placeholder in one table. The numbers come from what the app runs on (the bundle, app/*.json and
the rule modules' constants), so the page stays true when they change. The shell calls
``render(demo, tl, res)``: the loaded bundle, app/timeline_synthetic.json and
app/results_tcga_brca.json (None when missing)."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
import streamlit as st

import charts
from workbenches import documents, omics
from workbenches import radiology as radiology_page
from workbenches import evolution as evolution_page

from muffle import cohort, crosstest, feedback, literature, workspace
from muffle.overview import IMPACT_COLORS, LEVEL_COLORS
from muffle.report import budget
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.report.nemotron import DEFAULT_MODEL, WRITER_MODEL, model_name
from muffle.timeline import CTDNA
from muffle.workbench import ctdna as ctdna_rules
from muffle.workbench import genomics as genomics_rules
from muffle.workbench import labs as lab_rules
from muffle.workbench import omics as omics_rules
from muffle.workbench import radiology as radiology_rules
from muffle.workbench.grammar import chip
from workbenches._page import table

APP = Path(__file__).parent
LAYER_NAMES = {"clinical": "Clinical", "rna": "RNA expression", "genomic": "Copy number",
               "methylation": "Methylation", "protein": "Protein"}
# docs/calibration.md (`make calibration-tcga`, seed 0): every patient scored by a model trained
# without their hospital; the federated model's column
CALIBRATION = {"patients": 1064, "deaths": 148, "c_index": 0.671,
               "auc": {"2 years": 0.688, "3 years": 0.663, "5 years": 0.611},
               "ibs": 0.098, "ibs_km": 0.101, "cal_error_3y": 0.021,
               "slices": {"age under 50": 0.673, "age 50–64": 0.713, "age 65 and over": 0.641,
                          "stage II": 0.599, "stage III–IV": 0.614}}


def tags(text: str) -> str:
    return " ".join(chip(e) for e in (OBSERVED, INFERENCE, HYPOTHESIS) if e in text)


# model cards -> their module in muffle.literature (an evidence category and an EASSI-H line)
CARD_MODULES = {"Multi-omic survival model": "risk_model", "MSK-CHORD landmark models": "landmark",
                "Breast tissue head (pathology slides)": "tissue_head",
                "Nuclei (StarDist)": "nuclei",
                "Slide geometry, invasion and breakaway rules": "invasion"}


def card(title: str, status: str, what: str) -> None:
    st.subheader(title)
    st.markdown(f"{chip(status)} · {what}")
    if title in CARD_MODULES:
        evidence_line(CARD_MODULES[title])


def evidence_line(module: str, label: str = "") -> None:
    """A module's evidence category (I–IV, adapted from Bhargava 2023) and its EASSI-H line:
    data, n, split, external validation, result (muffle.literature)."""
    st.caption((f"**{label}** · " if label else "")
               + f"{chip(literature.category(module)['chip'])} · EASSI-H: "
               + literature.eassi_h(module))


# The page's contents: every section and its cards, in page order. A new card joins it (the
# tests compare it with the rendered page: tests/test_states.py).
CONTENTS = {
    "Models": ["Multi-omic survival model", "MSK-CHORD landmark models",
               "Breast tissue head (pathology slides)", "Nuclei (StarDist)",
               "Lesion contours (MedSAM, breast MRI)",
               "Change over time (rigid alignment, breast MRI)",
               "Multiplanar views and cine (breast MRI)",
               "Mammography geometry (left-right, CC and MLO)",
               "Breast density, second opinion (MONAI, mammography)",
               "Screening score (mammoscreen, mammography)",
               "Radiology: report reading, seed and kinetics rules",
               "Expression, methylation and protein scores", "Case note", "Case note service",
               "Planned: infrared chemical imaging"],
    "Rules": ["SOS alerts and their order", "Lab result rules", "ctDNA monitor rules",
              "Slide geometry, invasion and breakaway rules",
              "Genomics: detection, interpretation and evidence",
              "Clinical documents: the rules and a named-entity model, side by side",
              "Tumor evolution and treatment evidence",
              "Across the files: search, similar patients, where a patient sits"],
    "Federated training across simulated hospitals": [], "Data sources and licenses": [],
    "Known failures": [], "Every placeholder in the app": [], "Limits": [],
}


def anchor(text: str) -> str:
    """The id Streamlit gives a heading: lower case, spaces as hyphens, other signs dropped."""
    return re.sub(r"[^a-z0-9_-]+", "", "-".join(text.lower().split()))


def contents() -> None:
    """The table of contents: the sections, and the cards of Models and Rules, as links."""
    with st.container(border=True, key="methods-contents"):
        st.markdown("**On this page**")
        cols = st.columns(3)
        for col, section in zip(cols[:2], ("Models", "Rules"), strict=True):
            col.markdown(f"[{section}](#{anchor(section)})  \n" + "  \n".join(
                f"· [{t}](#{anchor(t)})" for t in CONTENTS[section]))
        cols[2].markdown("  \n".join(f"[{s}](#{anchor(s)})" for s, cards in CONTENTS.items()
                                     if not cards))


def legend() -> None:
    """How the app colours a finding: one key for the report, the workbenches and this page.
    Colour is never the only signal: every chip carries its word."""
    with st.container(border=True, key="methods-legend"):
        st.markdown("**Colour code**  \n"
                    f"Evidence: {chip(OBSERVED)} {chip(INFERENCE)} {chip(HYPOTHESIS)} · "
                    f"module: {chip(workspace.IMPLEMENTED)} {chip(workspace.VALIDATED)} "
                    f"{chip(workspace.PLANNED)} · a value nobody has validated: "
                    f"{chip('placeholder')}, always orange  \n"
                    f"Trust: {chip('trust: strong', 'green')} {chip('trust: moderate', 'orange')} "
                    f"{chip('trust: weak', 'red')} · open alerts: {chip('SOS', 'red')}  \n"
                    "CIViC evidence level: " + " ".join(chip(k, v) for k, v in
                                                        LEVEL_COLORS.items())
                    + f" {chip('no CIViC item')} (A validated … E inferential)  \n"
                    "Variant severity, Ensembl VEP's consequence table: " + " ".join(
                        chip(k.lower(), v) for k, v in IMPACT_COLORS.items())
                    + "  \nRisk: in a chart, red raises it and blue lowers it; a number's change, "
                      "red up and green down. Variants, pointers, ids and amounts are set in "
                      "monospace.")


def records() -> list[dict]:
    """This session's review marks as the feedback ledger (muffle.feedback)."""
    return feedback.ledger(st.session_state.get("reviews", {}))


def reviewed(heading: str) -> None:
    """A card's line from this session's review marks: findings reviewed and disagreed (zero
    when nothing was marked). Nothing a clinician marks changes the model or rule."""
    st.caption("Clinician review · " + feedback.line(records(), heading)
               + ". Marks stay in this browser session; nothing is trained on them (Feedback).")


def render(demo, tl: dict | None, res: dict | None, service: dict | None = None) -> None:
    """``service``: the case-note service as this server runs it ("spent": the ledger's (spent,
    cap, calls) or None when unreadable, "notes": live notes per browser session, "live")."""
    st.title("Methods and validation")
    st.markdown(
        "How each result in a patient file is produced, how well it holds up, what it gets wrong "
        "and where the data come from. In a file, every finding is marked "
        f"{chip(OBSERVED)} (measured or recorded), {chip(INFERENCE)} (a prediction, with its "
        f"uncertainty) or {chip(HYPOTHESIS)} (evidence and literature leads); every module is "
        f"{chip(workspace.IMPLEMENTED)}, {chip(workspace.VALIDATED)} or "
        f"{chip(workspace.PLANNED)}; every threshold names its source, and a "
        f"{chip('placeholder')} is a value nobody has validated yet.")
    st.caption(workspace.DISCLAIMER)
    contents()
    legend()

    st.header("Models")
    survival_card(demo, res)
    reviewed(feedback.SURVIVAL)
    if tl:
        landmark_card(tl)
        reviewed(feedback.LANDMARK)
    slide_model_cards()
    reviewed(feedback.SLIDES)
    radiology_page.methods_card()
    evidence_line("radiology", "Radiology models")
    reviewed(feedback.RADIOLOGY)
    omics.methods_card()
    evidence_line("pam50", "PAM50 subtype")
    evidence_line("ecm3", "ECM3 four-gene score")
    reviewed(feedback.OMICS)
    case_note_card(demo)
    case_note_service_card(service or {})
    planned_infrared()

    st.header("Rules")
    alert_card()
    reviewed(feedback.ALERTS)
    lab_card()
    reviewed(feedback.LABS)
    ctdna_card()
    reviewed(feedback.CTDNA)
    slide_rule_card()
    genomics_card()
    reviewed(feedback.GENOMICS)
    st.subheader("Clinical documents: the rules and a named-entity model, side by side")
    st.markdown(f"{chip(workspace.IMPLEMENTED)} · breast pathology facts from report text, each "
                "with its source sentence · the clinical documents workbench")
    st.markdown("Regular expressions run where the app runs; a fact is *documented*: the "
                "document says it, nothing is derived from it. A second reading, *model "
                "inference*, comes from a zero-shot named-entity model run offline on a local "
                "machine (its spans ship for the bundled reports; no model runs in the app and "
                "no report text leaves the machine). Scanned PDFs are read to text by a page "
                "model in the same local pipeline. Both readings measured on the same held-out "
                "TCGA reports against TCGA's clinical fields:")
    documents.methods_card()
    evidence_line("documents", "Documents rules")
    reviewed(feedback.DOCUMENTS)
    evolution_page.methods_card()
    reviewed(feedback.EVOLUTION)
    cohort_card()

    federation(demo)
    sources()
    known_failures()
    placeholders()

    st.header("Limits")
    st.markdown(
        "- On overall survival in TCGA-BRCA the omic layers don't beat clinical data yet; "
        "federation matches pooling and beats a single hospital.\n"
        "- TCGA holds one tumor sample per patient, so its files have one version and no "
        "alerts.\n"
        "- The radiology workbench reads the synthetic patient's imaging reports as text and "
        "shows model contours and a screening score on five public TCGA-BRCA studies only, not "
        "validated here; the ctDNA monitor runs on SYNTHETIC-001's synthetic series only (no "
        "open serial breast ctDNA data exists); an imported image or DICOM file is "
        "registered and queued for the local pipeline, not analyzed. Imports last for the "
        "browser session.\n"
        "- No finding has been reviewed against outcomes by a clinician, and no slide by a "
        "pathologist.\n"
        "- The hospitals are simulated, and SYNTHETIC-001 is synthetic.\n"
        f"- {workspace.DISCLAIMER}")


# --- models -----------------------------------------------------------------------------------

def survival_card(demo, res: dict | None) -> None:
    by = {m["method"]: m for m in res["methods"]} if res else None
    card("Multi-omic survival model", workspace.VALIDATED,
         "overall survival, ranked by cohort percentile · the TCGA patient files' risk")
    c = CALIBRATION
    st.markdown(
        f"- **Training data:** TCGA-BRCA open access ({len(demo.cohort_risks):,} patients, "
        "overall survival): copy number, RNA expression, methylation, protein and clinical "
        f"data, split across {len(demo.sites)} simulated hospitals (groups of TCGA tissue source "
        "sites, so their data gaps are real).\n"
        "- **Design:** a clinical risk first, which the omic layers then correct by an amount "
        "chosen on hospitals the model wasn't trained on. A layer a hospital never measured is "
        "masked, not imputed, and training hides layers at random so the model copes. Trained "
        "with FedAvg in NVIDIA FLARE: only model weights leave a hospital.\n"
        f"- **Held-out performance:** C-index {demo.c_index:.3f}, the mean over hospitals ("
        + ", ".join(f"{s} {v:.3f}" for s, v in demo.c_index_by_site.items()) + ").\n"
        f"- **Calibration** ({c['patients']:,} patients, {c['deaths']} deaths, every patient "
        "scored by a model trained without their hospital): predicted 3-year death risk per "
        f"risk quintile within {c['cal_error_3y']:.1%} of the observed rate on average; "
        f"integrated Brier score {c['ibs']:.3f} against {c['ibs_km']:.3f} for no model, so the "
        "absolute risks add little: the app shows percentiles and risk groups, never a "
        "probability of death. AUC " + ", ".join(f"{v:.2f} at {k}" for k, v in c["auc"].items())
        + ": discrimination fades with the horizon.\n"
        "- **Weaker slices** (C-index): " + ", ".join(f"{k} {v:.2f}" for k, v in
                                                      c["slices"].items())
        + "; much of the ranking comes from stage itself. Source: docs/calibration.md (one "
        "seed).")
    if res and demo.names:  # real data (synthetic cohorts have no gene names)
        st.markdown("**Leave one hospital out:** train on two hospitals, test on the third.")
        st.altair_chart(charts.results([m for m in res["methods"] if m["group"] == "main"]),
                        width="stretch")
        st.markdown(
            f"- **Federated ≈ pooled.** FedAvg reaches {by['fedavg_residual']['mean']:.3f} on "
            f"a hospital it never saw, against {by['residual']['mean']:.3f} when the other "
            "hospitals' patients are pooled in one place, without moving any patient data.\n"
            f"- **Better than one hospital alone**, which scores "
            f"{by['local_only']['mean']:.3f}.\n"
            f"- **The omic layers don't add signal yet.** Clinical data alone (stage, age, "
            f"T/N/M) scores {by['only_clinical']['mean']:.3f} on overall survival, so the model "
            "anchors on clinical data and lets the omics correct it.")
        st.caption(res["protocol"] + ".")
        with st.expander("Each omic layer on its own"):
            single = [m for m in res["methods"] if m["group"] == "single layer"]
            table(pd.DataFrame(single)[["label", "mean", "sd"]].rename(
                columns={"label": "Layer", "mean": "C-index", "sd": "sd"}))
            st.caption("Copy number alone ranks patients worse than chance across hospitals "
                       "(below 0.5): a sign of site and batch effects.")
    left, right = st.columns([3, 2])
    with left:
        st.altair_chart(charts.survival_by_group(demo.km), width="stretch")
    with right:
        st.markdown("**Risk groups on the held-out patients**")
        st.caption(f"{demo.heldout_patients} held-out patients, {demo.heldout_deaths} deaths. "
                   "Curves stop at 5 years, where fewer than 20 patients per group remain. The "
                   "risk groups rank patients well; they are not calibrated probabilities of "
                   "death.")


def landmark_card(tl: dict | None) -> None:
    if not tl:
        return
    card("MSK-CHORD landmark models", workspace.VALIDATED,
         f"{tl['task']} · the synthetic patient's file")
    table([{"From month": int(k), "Patients": m["n"], "Event rate": m["event_rate"],
            "AUROC, record so far": f"{m['auroc'][0]:.3f} ± {m['auroc'][1]:.3f}",
            "AUROC, diagnosis only": f"{m['baseline_auroc'][0]:.3f} ± "
                                     f"{m['baseline_auroc'][1]:.3f}"}
           for k, m in sorted(tl["models"].items(), key=lambda kv: int(kv[0]))],
          mono=("AUROC, record so far", "AUROC, diagnosis only"), percent=("Event rate",))
    st.caption(
        "From month: the landmark, months after the first tumor sequencing. "
        "Gradient boosting on the record so far, against the same learner on the diagnosis "
        "alone (stage, HR, HER2); held-out AUROC, mean ± sd over 5 seeds, patient-level 80/20 "
        "splits, nothing tuned. " + tl["model_note"] + " Aggregate results only: the models and "
        "every MSK-CHORD patient stay on the machine they were trained on (CC BY-NC-ND 4.0), and "
        "nothing from them goes to a language model. Whether the probabilities are calibrated "
        "has not been checked.")


def slide_model_cards() -> None:
    from muffle.workbench import invasion  # scipy, as on the slide workbench
    from muffle.workbench import slides as slide_rules

    meta = json.loads((APP / "workbenches" / "slides_example" / "summary.json").read_text())
    head = meta["head"]
    card("Breast tissue head (pathology slides)", workspace.VALIDATED,
         "five tissue classes per 112 µm tile · the pathology slide workbench")
    st.markdown(
        f"- **Design:** {invasion.MODEL_CARD['tissue head']}.\n"
        f"- **Held-out accuracy:** {head['accuracy']:.1%} (balanced "
        f"{head['balanced_accuracy']:.1%}) on {head['held_out']}; below the unsure cutoff it was "
        f"right on {head['accuracy_below_cutoff']:.0%} of tiles, at or above it "
        f"{head['accuracy_at_or_above_cutoff']:.0%}.\n"
        "- **Per class (recall on held-out tiles):** " + ", ".join(
            f"{k} {v['recall']:.0%} ({v['n_test']} tiles)" for k, v in head["per_class"].items())
        + ".\n- **Not learned:** " + "; ".join(f"{k.replace('_', ' ')} ({why})" for k, why in
                                               head["not_learned"].items())
        + ". Their tiles get one of the five classes.\n"
        f"- **Encoder:** {meta['encoder']['name']} ({meta['encoder']['license']}), run offline; "
        "the hosted app reads precomputed results and runs no encoder. It was chosen over "
        "QuiltNet-B-32 (87.7%) on the same tiles, split and head; its card does not say whether "
        "TCGA slides were in its pretraining. Three held-out slides are a small test: no other "
        "institution, scanner or stain has been checked.\n"
        "- **Not scored (quality control):** tiles " + slide_rules.CUTOFFS[
            "unlike_training_cosine"][2].split(" = ", 1)[1] + " (cutoff "
        f"{slide_rules.CUTOFFS['unlike_training_cosine'][0]}). Tissue outside the five classes "
        "(muscle, cautery-crushed margins) is otherwise read as one of them; the rule misses "
        "some of it (known failures below).")
    card("Nuclei (StarDist)", workspace.IMPLEMENTED,
         "pretrained, not validated on breast here · the slide workbench's cell level")
    st.markdown(
        f"- **Design:** {invasion.MODEL_CARD['nuclei']}.\n"
        "- **Uses:** breakaway (budding) candidates in the ITBCC 0.785 mm² counting field, "
        "lymphocyte-like nuclei by zone, tumor-contacting lymphocytes, nuclear-area variation "
        "(a proxy, never a grade). Every flag built on it says *weak until validated*.\n"
        "- **Validation:** none on breast tissue: no hand count exists yet to measure its error.")
    evidence_line("til_second", "Second lymphocyte model (WSInfer TIL)")


def planned_infrared() -> None:
    """The infrared modules the Bhargava lab's work points to, planned only (no infrared data in
    this project), with their citations, the evidence categories and the independence note."""
    st.subheader("Planned: infrared chemical imaging")
    st.markdown(
        f"{chip(workspace.PLANNED)} · not built: {literature.PLANNED_REASON}. Infrared "
        "spectroscopic imaging records the chemistry of every pixel of an unstained section; "
        "machine learning then reads tissue, stroma and stains from it.")
    for m in literature.planned_modules():
        st.markdown(f"- **{m['name']}** {chip(m['status'])}: {m['what']}. "
                    + "; ".join(m["citations"]) + ".")
    st.caption(
        "Each model card above carries an evidence category, adapted from "
        + literature.cite("bhargava2023") + ": " + "; ".join(
            f"{k} {v}" for k, v in literature.CATEGORIES.items())
        + "; each asks for more proof than the last. Its EASSI-H line (the review's reporting "
        "guidelines) gives the data, n, split and external validation behind it.")
    st.caption(literature.INDEPENDENCE)


def case_note_card(demo) -> None:
    card("Case note", workspace.IMPLEMENTED,
         "the tumor-board note of a TCGA file · written by language models from local tools")
    notes = [n["report"] for n in demo.notes.values()]
    flagged = sum(1 for r in notes if r.get("issues"))
    st.markdown(f"""
- **{model_name(DEFAULT_MODEL)} plans** on Nebius Token Factory: it decides which tools to call.
  The tools run locally and label what they return: `observed_findings` (*observed*: measured
  and missing data layers, recorded stage, age band, the sequenced driver mutations from GDC
  open-access somatic calls, or "not sequenced"), `predict_risk`, `modality_contributions` and
  `top_features` (*model inference*, with the model's validation C-index as its uncertainty),
  `treatment_evidence` (*hypothesis*: CIViC items for the observed mutations) and
  `search_literature` (*hypothesis*: Tavily search for papers or trials on up to 3 named genes).
- **{model_name(WRITER_MODEL)} writes** the note from the tool outputs, in five sections:
  Summary, Observed, Model inferences, Hypotheses and evidence, Caveats. Every bullet starts
  with [Observed], [Model inference] or [Hypothesis]. If it fails, {model_name(DEFAULT_MODEL)}
  writes.
- **A grounding check** (plain code, no language model) looks for any number, gene or link in
  the note that no tool returned. The writer gets one rewrite; anything left is shown with the
  note. The evidence chain under each note links every sentence to the tool output behind it.
  Saved notes: {len(notes)}, of which {flagged} kept an unsupported item after the check.
- **What the check cannot catch:** a wrong reading of a correct number, an overstated
  sentence with no number in it, or a tool output that is itself wrong. The note is a draft
  for a tumor board, not a finding.
- **Treatment content is evidence, not advice.** Each CIViC (CC0) item keeps its evidence level
  (A validated … E inferential), significance, citation and link, for clinician review, never
  a recommendation.
- Only derived numbers (risk, percentile, contributions, attribution scores) and gene or
  mutation names go to Token Factory and Tavily, never a patient's omics values, and nothing
  from MSK-CHORD. Every call counts against a hard spending cap; once it is reached, or without
  a key, the same tools run in a fixed order and a template writes the note.
""")


def case_note_service_card(service: dict) -> None:
    """The case-note service as this server runs it: the hard cap on the language-model calls,
    the spend on this server's ledger, the live notes a browser session may write, the prices
    the gate reserves at, and how a call is refused."""
    card("Case note service", workspace.IMPLEMENTED,
         "a hard spending cap and a per-session limit on every live tumor-board note")
    spent, notes = service.get("spent"), service.get("notes")
    # a static table: its notes wrap (a dataframe cut them at 1280 px)
    st.table(pd.DataFrame([
        ("Hard cap", f"${budget.HARD_CAP_USD:.2f}", "in the app's code; a server setting can lower "
         "it, never raise it"),
        ("Cap on this server", "ledger unreadable" if spent is None else f"${spent[1]:.2f}",
         "the lower of the hard cap and this server's setting"),
        ("Spent on this server", "ledger unreadable" if spent is None else
         f"${spent[0]:.2f} in {spent[2]} calls", "this server's own ledger; other machines' spend "
         "is checked against the provider's usage console"),
        ("Live notes per browser session", "none" if not service.get("live") else str(notes),
         "then the saved notes only" if service.get("live") else
         "no key on this server: the saved notes only"),
    ], columns=["What", "Now", "Note"]).set_index("What"))
    st.markdown(
        "**How a call is refused.** Before every request the gate reserves its worst case: "
        "every two characters of the prompt and tools counted as a token, plus the full output "
        "allowance, at the model's price (" + "; ".join(
            f"{model_name(m)} \\${p_in:.2f} in, \\${p_out:.2f} out per million tokens"
            for m, (p_in, p_out) in budget.PRICES_PER_M.items())
        + "; any other model at a deliberately high price). If the spend so far plus that "
        "reservation would pass the cap, the request is never sent, and the note is written by "
        "a template from the same tools, which says so. After a reply the reservation is "
        "swapped for the reply's real cost; a refused request costs nothing, and after a "
        "timeout the reservation stays charged, since the model may have run. A file lock "
        "keeps two processes from reserving the last of the cap, and a ledger that can't be "
        "read refuses every call.")
    st.caption("Prices as listed by price trackers on 2026-10-18; the provider's price page "
               "needs a login.")


# --- rules ------------------------------------------------------------------------------------

def cohort_card() -> None:
    """Search every file, Similar patients and Where this patient sits (muffle.cohort): lookups
    over what the files already hold, not models (QA round 3)."""
    card("Across the files: search, similar patients, where a patient sits",
         workspace.IMPLEMENTED, f"{cohort.LOOKUP} · the Patients page's search, each report's "
                                "Similar patients and Where this patient sits")
    st.markdown(
        "- **What they read:** what the files already hold, as of each file's latest report: "
        "every workbench's finding cards and attention items, the tests that disagree, the "
        "documented facts, the variants, the promoter methylation calls, the evolution "
        "hypotheses and each file's recorded and derived profile. Each entry keeps its evidence "
        f"label ({chip(OBSERVED)}, {chip(INFERENCE)} or {chip(HYPOTHESIS)}). No model is "
        "trained or run here; nothing is a prognosis.\n"
        "- **Search every file:** every word must start a word of one finding (else, said so, "
        "across a file's findings); files rank by how many findings match, how close the words "
        "sit, then evidence. A text lookup, not a model.\n"
        f"- **Similar patients:** the five TCGA files nearest on {len(cohort.FIELDS)} fields ("
        + ", ".join(name for name, _ in cohort.FIELDS.values()) + "), every field weighing the "
        f"same ({chip('placeholder')}: not tuned on outcomes); a field either file lacks counts "
        "as not shared. Candidates are the TCGA files only.\n"
        f"- **Where this patient sits:** {cohort.POSITION}: the share of the other TCGA files "
        "with a lower value. The workbenches' percentiles are against the whole TCGA cohort, so "
        "the two differ.\n"
        "- **Never compared:** the synthetic patient, whose 12-month risk comes from the "
        "MSK-CHORD models; nothing from MSK-CHORD enters a similarity or a distribution.\n"
        "- **Known failures:** a search lands on its best finding's own target, so a card that "
        "names two sites opens at the one it points to; a file's findings are the latest "
        "report's, not earlier versions'.")


def alert_card() -> None:
    card("SOS alerts and their order", workspace.IMPLEMENTED,
         "the report's SOS tile · rules on the record, one model estimate")
    table(pd.DataFrame([
        ("Progression on imaging", OBSERVED, "the imaging report reads progression; an "
         "imported report: a clause states it, not negated or hedged (trust moderate)",
         "recorded; an imported report: its words"),
        ("New metastatic site", OBSERVED, "a site not in the record before; an imported "
         "report: a clause names a new distant site, not negated or hedged (trust moderate)",
         "recorded; an imported report: its words"),
        ("Tumor marker rise", OBSERVED,
         f"above the reference limit and at least {workspace.RISE:.0%} above the previous "
         "value; to be confirmed with a second specimen within a month",
         workspace.EGTM + "; the limit from the patient's lab report"),
        ("Risk jump", INFERENCE,
         f"12-month risk up at least {workspace.RISK_JUMP} points since the previous result",
         "placeholder, not validated"),
        ("Newly sequenced driver", f"{OBSERVED} (mutation), {HYPOTHESIS} (evidence)",
         "level A or B CIViC treatment evidence", "CIViC evidence levels"),
    ], columns=["Alert", "Evidence", "Rule", "Threshold source"]))
    st.markdown(
        "**Order of the queue** " + chip("placeholder weights") + ": consequence (3 changes the "
        "picture of the disease, 2 may change care, 1 worth a look) × trust (" + ", ".join(
            f"{k} {v:g}" for k, v in workspace.TRUST.items()) + "), this version's alerts "
        "first. A fixed ordering rule, not a validated triage score. **Tests that disagree** "
        "and **what would reduce uncertainty** are rules too: imaging counts as old "
        f"{crosstest.IMAGING_AGE} months after a marker rise (placeholder); the ctDNA "
        "expectation comes from PADA-1 and SERENA-6.")
    st.caption("A tumor marker out of range is not evidence of progression by itself.")


def lab_card() -> None:
    c = lab_rules.rules_card()
    card("Lab result rules", workspace.IMPLEMENTED,
         "flags, kinetics and quality checks · the blood and lab workbench")
    st.markdown(f"{c['kind']}. **Inputs:** {c['inputs']}. **Validation:** {c['validation']}.")
    table(c["thresholds"])
    st.caption(f"Kinetics: a log-linear fit over the last {lab_rules.KINETICS_POINTS} values "
               "(model inference, placeholder method), drawn as an extrapolation with its band; "
               "within-person baseline, therapy caution window and the hook-effect check are "
               "placeholder definitions (see every placeholder below).")


def ctdna_card() -> None:
    c = ctdna_rules.rules_card(CTDNA)
    card("ctDNA monitor rules", workspace.IMPLEMENTED,
         "allele fractions over time, calls, origin, the ESR1 rule · the ctDNA monitor")
    st.markdown(f"{c['kind']}. **Inputs:** {c['inputs']}. **Validation:** {c['validation']}. "
                "The only series in the app is SYNTHETIC-001's, written by hand and labeled "
                f"synthetic; the ESR1 rule is {chip(HYPOTHESIS)}, evidence for clinician review, "
                "never a recommendation to switch.")
    table(c["thresholds"])


def slide_rule_card() -> None:
    from muffle.workbench import invasion
    from muffle.workbench import slides as slide_rules

    both = {**slide_rules.CUTOFFS, **invasion.CUTOFFS}
    n = sum(1 for _, tag, _ in both.values() if tag == slide_rules.PLACEHOLDER)
    card("Slide geometry, invasion and breakaway rules", workspace.IMPLEMENTED,
         "front, zones, direction of invasion, budding, TILs, risk map · the slide workbench")
    st.markdown(
        f"{invasion.MODEL_CARD['geometry']}. The direction of invasion is a {chip(HYPOTHESIS)} "
        "about one section, never a forecast; the risk map adds placeholder points ("
        + ", ".join(f"{k} {v}" for k, v in invasion.RISK_POINTS.items())
        + ") and is not an outcome model. "
        f"**{n} of {len(both)} cutoffs are placeholders**; the rest are design choices that "
        "define a measurement or come from the literature (ITBCC 2016 for the bud size and the "
        "0.785 mm² field, the TILs Working Group's zones, a tumor–stroma ratio of 50% from "
        "colorectal cancer). Not reviewed by a pathologist.")
    with st.expander("Every slide cutoff and its source"):
        table([{"cutoff": k, "value": v, "source": tag, "note": note}
               for k, (v, tag, note) in both.items()], chips=("source",), mono=("cutoff",))


def genomics_card() -> None:
    c = genomics_rules.data_card()
    card("Genomics: detection, interpretation and evidence", c["status"],
         "observed variants with CIViC evidence · the genomics workbench")
    st.markdown(
        f"No model: {c['model']}. A variant is {chip(OBSERVED)} (detected); its interpretation, "
        f"predicted effect, therapy evidence and resistance items are {chip(HYPOTHESIS)}. "
        "Evidence levels: " + "; ".join(f"**{k}** {v}" for k, v in c["evidence_levels"].items())
        + ". The SOS tile raises a newly sequenced driver only for level A or B items. "
        "**Limits:** " + "; ".join(c["limits"]) + ".")


# --- federation, sources ----------------------------------------------------------------------

def federation(demo) -> None:
    """The federated training as a status table: each simulated site's patients, deaths,
    held-out patients and C-index, and the share of its patients with each data layer."""
    st.header("Federated training across simulated hospitals")
    st.markdown(f"FedAvg on NVIDIA FLARE's simulator: each of {len(demo.sites)} simulated "
                "hospitals trains on its own patients and sends only model weights to the "
                "server, which averages them each round; no patient data leaves a site.")
    sites = pd.DataFrame([{
        "Site (simulated)": s.name, "Patients": s.patients, "Deaths": s.deaths,
        "Held out": s.heldout, "Held-out C-index": demo.c_index_by_site.get(s.name),
        **{LAYER_NAMES.get(m, m): 100 * s.coverage[m] for m in demo.model.names
           if m != "clinical"},
    } for s in demo.sites])
    table(sites, grid=True, column_config={  # a grid: its coverage bars
        "Held-out C-index": st.column_config.NumberColumn(format="%.3f"),
        **{LAYER_NAMES.get(m, m): st.column_config.ProgressColumn(
            LAYER_NAMES.get(m, m), format="%.0f%%", min_value=0, max_value=100, width="small")
           for m in demo.model.names if m != "clinical"}})
    st.caption(f"Held-out C-index: each site's validation patients, never trained on; the "
               f"files' {demo.c_index:.3f} is their mean. Bars: the share of each site's "
               "patients with that data layer. The hospitals are simulated: TCGA tissue source "
               "sites grouped into three clients of the NVFlare simulator, so the data gaps are "
               "real but no real site took part.")


SOURCES = [  # docs/registry.md: (source, used for, license or terms)
    ("TCGA-BRCA multi-omic data (GDC open access via UCSC Xena)",
     "the survival model and the TCGA patient files", "open access; cite the TCGA Research "
     "Network"),
    ("GDC masked somatic mutations and per-case MAFs (open access)",
     "observed driver mutations; allele fractions for clonal order", "as TCGA"),
    ("TCGA-BRCA diagnostic slides (GDC open access)",
     "the patient's own sections in the slide workbench: derived numbers, small crops, and the "
     "section itself as JPEG tiles at about 1 µm/px for the slide viewer (release "
     "slide-tiles-v1)", "as TCGA"),
    ("BCSS (Amgad et al., Bioinformatics 2019)", "labels for the breast tissue head", "CC0 1.0"),
    ("TCGA-BRCA radiology (The Cancer Imaging Archive, doi:10.7937/K9/TCIA.2016.AB2NAZRP)",
     "the radiology workbench's public MRI and mammography studies: 8-bit copies and derived "
     "numbers", "CC BY 3.0, with attribution"),
    ("MedSAM ViT-B (Ma et al., Nat Commun 2024; wanglab/medsam-vit-base)",
     "lesion contours, run offline", "Apache-2.0"),
    ("mammoscreen (ianpan/mammoscreen)", "the mammography screening score and density, run "
     "offline", "Apache-2.0"),
    ("GigaPath-Flash (prov-gigapath/prov-gigapath-flash; distilled from Prov-GigaPath, Xu et "
     "al., Nature 2024)", "the tile encoder, run offline", "Apache-2.0; gated click-through"),
    ("StarDist 2D_versatile_he (Schmidt et al. 2018; Weigert et al. 2020)",
     "nuclei on front-band tiles, run offline", "BSD-3-Clause"),
    ("PAM50 centroids (Parker et al. 2009) from genefu (Gendoo et al. 2016)",
     "the subtype call", "Artistic-2.0; cited"),
    ("MSigDB Hallmark gene sets v2025.1 (Liberzon et al. 2015)", "pathway scores", "CC BY 4.0"),
    ("TCGA published PAM50 calls and receptor IHC (cBioPortal)",
     "validating the subtype call; receptor consistency", "TCGA open clinical data; cite TCGA "
     "and cBioPortal"),
    ("HM450 probe map (UCSC Xena GDC hub)", "the gene a methylation CpG lies near", "as TCGA"),
    ("RPPA pathway members and signs (Akbani et al. 2014, Nat Commun, Supplementary Table 13)",
     "the protein pathway scores", "CC BY-NC-SA 3.0 article; the member list cited"),
    ("Illumina HumanMethylation450 v1.2 manifest", "promoter and CpG-island status of each 450K "
     "probe", "Illumina's free product file; not redistributed, derived probe lists only"),
    ("ESTIMATE stromal and immune gene lists (Yoshihara et al. 2013, Nat Commun, Supplementary "
     "Data 1)", "the immune and stromal signatures (z-score averaging; the GPL-2 package is not "
     "used)", "gene names used as facts, cited; the article carries no CC license"),
    ("TCGA-Reports (Kefeli and Tatonetti, Patterns 2024; Mendeley Data 10.17632/hyg5xkznpx.1)",
     "the TCGA cases' pathology reports; measuring the extraction", "CC BY 4.0, attribution"),
    ("OpenMed ZeroShot NER Oncology Base 220M (OpenMed/OpenMed-ZeroShot-NER-Oncology-Base-220M; "
     "arXiv:2508.01630, preprint)", "the documents' second reading (named-entity spans), run "
     "offline", "Apache-2.0"),
    ("Granite-Docling 258M (ibm-granite/granite-docling-258M)", "scanned PDF reports to text "
     "in the local pipeline", "Apache-2.0"),
    ("TCGA original pathology report PDFs (NCI GDC, open access)", "measuring the scan reader "
     "on two real scanned reports (local only)", "TCGA open-access data"),
    ("TCGA-BRCA clinical matrix (UCSC Xena)", "the reference the extraction is measured "
     "against (counts only)", "as TCGA"),
    ("MSK-CHORD (Jee et al., Nature 2024)",
     "the landmark models behind the synthetic patient's risk; used on one machine only, "
     "aggregate results", "CC BY-NC-ND 4.0"),
    ("CIViC clinical evidence summaries", "treatment evidence for clinician review", "CC0"),
    ("EGTM breast cancer recommendations", "the tumor-marker rise rule", "cited"),
    ("PubMed (NCBI E-utilities)", "checking every citation of the evolution table",
     "NLM terms; abstracts cited, not copied"),
    ("ClinicalTrials.gov API v2", "trials that mention a patient's observed genes",
     "U.S. government database: attributed, with the date of its data"),
    ("Tavily search", "literature leads in case notes", "Tavily API terms"),
    ("NVIDIA Nemotron 3 Super and Ultra on Nebius Token Factory", "the case note",
     "NVIDIA open model license; Token Factory terms"),
]


def sources() -> None:
    st.header("Data sources and licenses")
    table(pd.DataFrame(SOURCES, columns=["Source", "Used for", "License or terms"]))
    st.caption("SYNTHETIC-001's record is written by hand and labeled synthetic; it is not a "
               "real person and was not taken from any dataset. Every source, its access tier "
               "and what leaves this machine: the project's [data registry](https://github.com/ps131-cell/muffle-plus-plus/blob/main/docs/registry.md).")


# --- one list of known failures, one table of placeholders ------------------------------------

def known_failures() -> None:
    from muffle.workbench import documents as doc_rules
    from muffle.workbench import invasion

    docs = documents.VALIDATION
    weak = []
    if docs.exists():
        test = json.loads(docs.read_text())["sets"]["test"]["fields"]
        weak = [f"{r['compared']}: precision {r['precision']:.0%}" for r in test
                if r["precision"] is not None and r["precision"] < 0.85]
    rows = [
        ("Survival model", "The omic layers don't beat clinical data on overall survival; copy "
         "number alone ranks worse than chance across hospitals (site and batch effects)."),
        ("Survival model", "Weaker under 50 and within one stage; absolute risks add little "
         f"over no model (integrated Brier {CALIBRATION['ibs']} against "
         f"{CALIBRATION['ibs_km']})."),
        ("MSK-CHORD landmark models", "Labels come from language processing of radiology "
         "reports; some features measure how closely a patient is followed; one institution, "
         "no external validation."),
        *(("Slide workbench", f) for f in invasion.KNOWN_FAILURES),
        ("Nuclei (StarDist)", "No measured error on breast tissue; every count built on it is "
         "weak until validated."),
        ("PAM50", "The call depends on the centering reference: plain centering on this mostly "
         "ER-positive cohort agrees with the published calls on 72.5%, the ER-balanced one on "
         "94.7%, chosen after seeing the first: not an independent test."),
        ("Receptor consistency", "HER2 by RNA or copy number is weak against the recorded "
         "status (sensitivity 0.56 and 0.57); cutoffs are calibrated in-sample."),
        ("Protein pathways (RPPA)", "Most phospho-site antibodies and several total proteins "
         "(p53, c-Myc, BAX, BAK, ATM, among others) agree weakly with their gene's RNA; a "
         "pathway score is relative to this cohort and not validated as activity."),
        ("Promoter methylation", "Calls rest on placeholder cutoffs; the manifest's CpG island "
         "misses BRCA1's core promoter, so a gene's probes are chosen by position and by being "
         "unmethylated in normal breast instead."),
        ("Document extraction", "Recall is bounded by what a report states (receptors are "
         "often in an earlier biopsy report)" + ("; weak fields: " + ", ".join(weak) if weak
                                                 else "") + "."),
        *(("Document named-entity model", f) for f in doc_rules.NER_FAILURES),
        *(("Lab rules", f) for f in lab_rules.rules_card()["known_failures"]),
        *(("ctDNA rules", f) for f in ctdna_rules.rules_card(CTDNA)["known_failures"]),
        ("Imported imaging report", "A word rule, tested on sample sentences only: it misses "
         "progression stated without the word (\"enlarging lesions\"), a new site phrased "
         "another way and negations it doesn't list; it reads no measurements, so no RECIST."),
        ("Imported sequencing", "Genes and protein changes are the file's own annotation; a "
         "variant file lists calls, not coverage, so a gene it doesn't list stays unknown; a "
         "VCF's allele fractions are not read."),
        ("Case note", "The grounding check catches numbers, genes and links no tool returned, "
         "not a wrong reading of a right number or an overstated sentence."),
        ("Evolution view", "A cohort's frequency is not this patient's probability; purity is "
         "unknown, so no variant is called clonal."),
        *(("Radiology", f) for f in radiology_rules.KNOWN_FAILURES),
        *clinician_disagreements(),
    ]
    st.header("Known failures")
    st.caption("What each module gets wrong, as far as it has been measured or seen. Each "
               "workbench repeats its own in its model and validation card.")
    table(pd.DataFrame(rows, columns=["Module", "Known failure"]))


def clinician_disagreements() -> list[tuple[str, str]]:
    """Findings clinicians disagreed with this session, one row per model or rule; none when
    nothing was marked disagree."""
    recs = records()
    rows = []
    for g in feedback.rates(recs):
        if g[feedback.DISAGREE]:
            bad = [x["finding"] for x in feedback.disagreed(recs) if x["method"] == g["method"]]
            rows.append((g["method"], "Findings clinicians disagreed with this session: "
                         f"{g[feedback.DISAGREE]} of {g['n']} marked (" + "; ".join(bad[:3])
                         + ("; …" if len(bad) > 3 else "") + "). A review mark, not a "
                         "measured error rate."))
    return rows


def placeholders() -> None:
    from muffle.workbench import invasion
    from muffle.workbench import slides as slide_rules

    rows = [
        ("Report · SOS", "risk jump alert", f"{workspace.RISK_JUMP} points of 12-month risk"),
        ("Report · SOS", "queue order weights", ", ".join(
            f"trust {k} {v:g}" for k, v in workspace.TRUST.items()) + "; consequence 1–3"),
        ("Report · tests that disagree", "imaging counts as old after a marker rise",
         f"{crosstest.IMAGING_AGE} months"),
        ("Labs", "fall flag", f"the previous value {workspace.RISE:.0%} above this one"),
        ("Labs", "gap between two results", f"over {lab_rules.GAP_MONTHS} months"),
        ("Labs", "caution window after a therapy change", f"{lab_rules.FLARE_MONTHS} months"),
        ("Labs", "kinetics method", f"log-linear fit over the last {lab_rules.KINETICS_POINTS} "
         "values"),
        ("Labs", "hook-effect check", f"a value {lab_rules.HOOK_FACTOR}× the limit"),
        ("Labs", "within-person baseline", "longest run of results with no rise or fall flag"),
        ("Labs", "large rise or fall (analytes other than tumor markers)",
         f"{lab_rules.CHANGE:.0%} from the previous value"),
        ("Labs", "cross-analyte hypothesis window",
         f"{lab_rules.HYPOTHESIS_MONTHS} months before the imaging report"),
        *(("ctDNA", t["name"], t["value"]) for t in ctdna_rules.rules_card(CTDNA)["thresholds"]
          if t["status"] == ctdna_rules.PLACEHOLDER),
        ("Omics", "borderline subtype call", f"centroid margin under {omics_rules.LOW_MARGIN}"),
        ("Omics", "ERBB2 amplification from copy number", "at least twice the tumor ploidy"),
        *(("Omics", what, value) for what, value in omics_rules.PLACEHOLDERS),
        *(("Slides", k, f"{v} ({note})") for k, (v, tag, note) in
          {**slide_rules.CUTOFFS, **invasion.CUTOFFS}.items() if tag == slide_rules.PLACEHOLDER),
        ("Slides", "risk map points and levels", ", ".join(
            f"{k} {v}" for k, v in invasion.RISK_POINTS.items())),
        *(("Radiology", what, value) for what, value in radiology_rules.PLACEHOLDERS),
        *(("Patients · across the files", what, value) for what, value in cohort.PLACEHOLDERS),
    ]
    st.header("Every placeholder in the app")
    st.caption(f"{len(rows)} values nobody has validated yet. Each workbench marks its own "
               f"{chip('placeholder')} where it is used; the report export lists the ones its "
               "alerts use.")
    table(pd.DataFrame(rows, columns=["Where", "Placeholder", "Value"]), mono=("Value",))

"""The Methods and validation page (docs/WORKSPACE.md, "Product framing"): one card per model and
per rule the app uses, each with its status, numbers, sources and known failures; federated
training; the data sources and their licenses; then every known failure in one list and every
placeholder in one table. The numbers come from what the app runs on (the bundle, app/*.json and
the rule modules' constants), so the page stays true when they change. The shell calls
``render(demo, tl, res)``: the loaded bundle, app/timeline_synthetic.json and
app/results_tcga_brca.json (None when missing)."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import streamlit as st

import charts
from workbenches import documents, omics
from workbenches import radiology as radiology_page
from workbenches import evolution as evolution_page

from muffle import crosstest, workspace
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.report.nemotron import DEFAULT_MODEL, WRITER_MODEL, model_name
from muffle.timeline import CTDNA
from muffle.workbench import ctdna as ctdna_rules
from muffle.workbench import genomics as genomics_rules
from muffle.workbench import labs as lab_rules
from muffle.workbench import omics as omics_rules
from muffle.workbench import radiology as radiology_rules
from muffle.workbench.grammar import chip

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


def card(title: str, status: str, what: str) -> None:
    st.subheader(title)
    st.markdown(f"{chip(status)} · {what}")


def render(demo, tl: dict | None, res: dict | None) -> None:
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
    st.markdown("**On this page:** [Models](#models) · [Rules](#rules) · "
                "[Federated training](#federated-training-across-simulated-hospitals) · "
                "[Data sources and licenses](#data-sources-and-licenses) · "
                "[Known failures](#known-failures) · "
                "[Every placeholder](#every-placeholder-in-the-app)")

    st.header("Models")
    survival_card(demo, res)
    landmark_card(tl)
    slide_model_cards()
    radiology_page.methods_card()
    omics.methods_card()
    case_note_card(demo)

    st.header("Rules")
    alert_card()
    lab_card()
    ctdna_card()
    slide_rule_card()
    genomics_card()
    st.subheader("Clinical documents: extraction rules")
    st.markdown(f"{chip(workspace.IMPLEMENTED)} · breast pathology facts from report text, each "
                "with its source sentence · the clinical documents workbench")
    st.markdown("Regular expressions run where the app runs: no language model reads a report "
                "and no report text leaves the machine. A fact is *documented*: the document "
                "says it; nothing is derived from it. Measured against TCGA's clinical fields:")
    documents.methods_card()
    evolution_page.methods_card()

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
        "shows model contours and a screening score on three public TCGA-BRCA studies only, not "
        "validated here; the ctDNA workbench is planned; an imported image or DICOM file is "
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
            st.dataframe(pd.DataFrame(single)[["label", "mean", "sd"]].rename(
                columns={"label": "Layer", "mean": "C-index", "sd": "sd"}), hide_index=True)
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
    st.dataframe(pd.DataFrame([{
        "From month": int(k), "Patients": m["n"], "Event rate": m["event_rate"],
        "AUROC, record so far": f"{m['auroc'][0]:.3f} ± {m['auroc'][1]:.3f}",
        "AUROC, diagnosis only": f"{m['baseline_auroc'][0]:.3f} ± {m['baseline_auroc'][1]:.3f}"}
        for k, m in sorted(tl["models"].items(), key=lambda kv: int(kv[0]))]),
        hide_index=True, column_config={
            "From month": st.column_config.NumberColumn(
                help="Landmark: months after the first tumor sequencing"),
            "Event rate": st.column_config.NumberColumn(format="percent")})
    st.caption(
        "Gradient boosting on the record so far, against the same learner on the diagnosis "
        "alone (stage, HR, HER2); held-out AUROC, mean ± sd over 5 seeds, patient-level 80/20 "
        "splits, nothing tuned. " + tl["model_note"] + " Aggregate results only: the models and "
        "every MSK-CHORD patient stay on the machine they were trained on (CC BY-NC-ND 4.0), and "
        "nothing from them goes to a language model. Whether the probabilities are calibrated "
        "has not been checked.")


def slide_model_cards() -> None:
    from muffle.workbench import invasion  # scipy, as on the slide workbench

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
        "- **Encoder:** QuiltNet-B-32, run offline; the hosted app reads precomputed results "
        "and runs no encoder. Three held-out slides are a small test: no other institution, "
        "scanner or stain has been checked.")
    card("Nuclei (StarDist)", workspace.IMPLEMENTED,
         "pretrained, not validated on breast here · the slide workbench's cell level")
    st.markdown(
        f"- **Design:** {invasion.MODEL_CARD['nuclei']}.\n"
        "- **Uses:** breakaway (budding) candidates in the ITBCC 0.785 mm² counting field, "
        "lymphocyte-like nuclei by zone, tumor-contacting lymphocytes, nuclear-area variation "
        "(a proxy, never a grade). Every flag built on it says *weak until validated*.\n"
        "- **Validation:** none on breast tissue: no hand count exists yet to measure its error.")


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


# --- rules ------------------------------------------------------------------------------------

def alert_card() -> None:
    card("SOS alerts and their order", workspace.IMPLEMENTED,
         "the report's SOS tile · rules on the record, one model estimate")
    st.dataframe(pd.DataFrame([
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
    ], columns=["Alert", "Evidence", "Rule", "Threshold source"]), hide_index=True,
        width="stretch")
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
    st.dataframe(pd.DataFrame(c["thresholds"]), hide_index=True, width="stretch")
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
    st.dataframe(pd.DataFrame(c["thresholds"]), hide_index=True, width="stretch")


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
        st.dataframe(pd.DataFrame([{"cutoff": k, "value": v, "source": tag, "note": note}
                                   for k, (v, tag, note) in both.items()]),
                     hide_index=True, width="stretch")


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
    st.header("Federated training across simulated hospitals")
    left, right = st.columns([2, 3])
    with left:
        dot = ["digraph { rankdir=LR; bgcolor=transparent; size=\"5,3\"; node [shape=box, "
               "style=rounded, fontname=Helvetica, fontsize=11]; edge [fontname=Helvetica, "
               "fontsize=9];",
               'server [label="NVIDIA FLARE server\\nFedAvg", shape=box, style="rounded,bold"];']
        for s in demo.sites:
            dot.append(f'"{s.name}" [label="{s.name} (simulated)\\n{s.patients} patients\\n'
                       f'data stays here"];')
            dot.append(f'"{s.name}" -> server [label="weights", dir=both];')
        st.graphviz_chart("\n".join(dot) + "}", width="content")
    with right:
        table = pd.DataFrame([{
            "Hospital": s.name, "Patients": s.patients, "Deaths": s.deaths,
            "Held out": s.heldout,
            **{LAYER_NAMES.get(m, m): 100 * s.coverage[m] for m in demo.model.names
               if m != "clinical"},
        } for s in demo.sites])
        st.dataframe(table, hide_index=True, column_config={
            LAYER_NAMES.get(m, m): st.column_config.ProgressColumn(
                LAYER_NAMES.get(m, m), format="%.0f%%", min_value=0, max_value=100, width="small")
            for m in demo.model.names if m != "clinical"})
        st.caption("Bars: share of each hospital's patients with that data layer. The hospitals "
                   "are simulated: TCGA tissue source sites grouped into three clients of the "
                   "NVFlare simulator, so the data gaps are real but no real site took part.")


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
    ("QuiltNet-B-32 (Ikezogwo et al., NeurIPS 2023)", "the tile encoder, run offline", "MIT"),
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
    st.dataframe(pd.DataFrame(SOURCES, columns=["Source", "Used for", "License or terms"]),
                 hide_index=True, width="stretch")
    st.caption("SYNTHETIC-001's record is written by hand and labeled synthetic; it is not a "
               "real person and was not taken from any dataset. Every source, its access tier "
               "and what leaves this machine: docs/registry.md.")


# --- one list of known failures, one table of placeholders ------------------------------------

def known_failures() -> None:
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
    ]
    st.header("Known failures")
    st.caption("What each module gets wrong, as far as it has been measured or seen. Each "
               "workbench repeats its own in its model and validation card.")
    st.dataframe(pd.DataFrame(rows, columns=["Module", "Known failure"]), hide_index=True,
                 width="stretch")


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
    ]
    st.header("Every placeholder in the app")
    st.caption(f"{len(rows)} values nobody has validated yet. Each workbench marks its own "
               f"{chip('placeholder')} where it is used; the report export lists the ones its "
               "alerts use.")
    st.dataframe(pd.DataFrame(rows, columns=["Where", "Placeholder", "Value"]),
                 hide_index=True, width="stretch")

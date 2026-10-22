"""The shared grammar of every page (docs/WORKBENCHES.md §1): one badge color per label and one
name per recurring section, so the evidence chips (observed, model inference, hypothesis), the
status badges (implemented, experimentally validated, planned) and placeholders read the same on
the report, every workbench and the Methods and validation page. Pure strings, no Streamlit."""

from __future__ import annotations

import re

from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workspace import IMPLEMENTED, PLANNED, VALIDATED

COLORS = {OBSERVED: "blue", INFERENCE: "violet", HYPOTHESIS: "orange",
          IMPLEMENTED: "blue", VALIDATED: "green", PLANNED: "gray"}
OVERVIEW = "Overview"                     # one paragraph, the look-here queue and search
LOOK_HERE = "Look here"                   # the workbench's queue: worth a look, never a verdict
DETAILS = "Details"                       # collapsed sections, each with its count
SPOT = "Spot panel"                       # one value, variant, tile or lesion in full
CARD = "Model and validation card"       # the method, its numbers, sources and known failures
CANNOT_SEE = "What this test cannot see"  # and which test could
EXPORT = "Export"                         # buttons read "Download the <what> (<format>)"
SPOT_SUBTITLE = ("The full story of one value, variant, tile or lesion: pick it here, or click "
                 "it in the picture or the look-here list.")
# The skeleton of every workbench page (docs/ux.md), in order: the title (the workbench, the
# patient, the test), the status chips, the overview, the picture (map, viewer, chart or
# table; its heading names it), the details, the Spot panel, the card, what the test cannot
# see, the export. Details repeat (one collapsed section each); every other part comes once.
SKELETON = ("title", "chips", "overview", "picture", "details", "spot", "card", "cannot_see",
            "export")
HEADINGS = {"overview": OVERVIEW, "details": DETAILS, "spot": SPOT, "card": CARD,
            "cannot_see": CANNOT_SEE, "export": EXPORT}
REQUIRED = ("title", "chips", "overview", "card", "cannot_see", "export")  # on every page
WORKBENCHES = {  # the page titles, one name per workbench
    "labs": "Blood and lab workbench", "ctdna": "ctDNA monitor (liquid biopsy)",
    "genomics": "Genomics workbench", "slides": "Pathology slide workbench",
    "omics": "Expression, methylation and protein workbench",
    "radiology": "Radiology workbench", "documents": "Clinical documents workbench",
    "evolution": "Tumor evolution and treatment evidence", "imports": "Import tests",
    "intake": "Imported image, queued"}


GLOSSARY = {  # one sentence per label, behind every status chip and in the guide (docs/ux.md §3)
    OBSERVED: "Measured or recorded: a lab value, a sequenced mutation, a stage in the record, a "
              "sentence in a report.",
    INFERENCE: "A model's or a rule's estimate from the data, with its uncertainty; not a "
               "measurement.",
    HYPOTHESIS: "A lead from the literature or from reading tests together, for clinician "
                "review; not a finding about this patient.",
    IMPLEMENTED: "Built and running here; not validated on a cohort unless a label says so.",
    VALIDATED: "Checked against reference labels on held-out data; the numbers are on the "
               "Methods and validation page.",
    PLANNED: "Designed, not built yet: shown so that what is missing stays visible.",
    "placeholder": "A threshold chosen so that the rule can run, not taken from a guideline, "
                   "the literature or a calibration: read what depends on it with care.",
    "trust": "How far to rely on a finding: strong (a measurement or a guideline rule), "
             "moderate, or weak (a placeholder rule or an unvalidated model).",
    "synthetic": "Written by hand for this platform: not a real person's data.",
    "SOS": "An alert a rule raised on the newest results (progression, a new site, a marker "
           "rise, a new driver with strong evidence); open until a reviewer marks it.",
    "literature": "A cutoff or rule taken from a cited paper; the source is named with it.",
    "guideline": "A cutoff or grade from a clinical guideline (ASCO/CAP, CTCAE), named with it.",
    "reference-laboratory interval": "A reference laboratory's published adult interval, used "
                                     "when the lab report gives none; the report's own "
                                     "interval always wins.",
    "not reviewed by a pathologist": "No pathologist has checked these tile classes on this "
                                     "slide yet.",
    "validated on held-out BCSS slides": "The tissue head's accuracy was measured on held-out "
                                         "BCSS slides (BCSS: breast slides with expert region "
                                         "labels); the numbers are in the Model and validation "
                                         "card.",
    "weak until validated": "A pretrained model not validated on breast tissue: a candidate "
                            "to check by eye, never a count to report.",
    "example slide": "A public example region of another patient's slide, not this patient's "
                     "tissue.",
    "patient's own slide": "A scanned diagnostic section of this patient's own tumor (TCGA, "
                           "open access).",
    "imported this session": "Brought in through Import tests in this browser session; kept "
                             "for the session only.",
    "kept for this browser session": "Imports live in this browser session only: nothing is "
                                     "saved, and closing the tab discards them.",
    "queued for the local pipeline": "Registered and checked on intake, not analyzed: the "
                                     "hosted app runs no models.",
    "parts planned": "Designed, not built yet: listed in the Model and validation card.",
    "consequence": "How much a finding could matter: 3 changes the picture of the disease, 2 "
                   "may change care, 1 is worth a look.",
}
WORKBENCH_GUIDE = {  # the guide's "This screen": what it shows, and what it cannot see
    "patients": ("every patient file with its diagnosis, subtype, mutated genes, the "
                 "workbenches that hold its data and its open SOS alerts; search, filters and "
                 "sorting", "a file's findings: open the file"),
    "report": ("the latest report: finding cards from every test, one attention queue (SOS "
               "alerts, tests that disagree, each workbench's look-here items, strongest "
               "first), the record, the risk with its model and uncertainty, mutations with "
               "their CIViC evidence, what is missing and what would settle it",
               "anything the file's tests cannot; each workbench's 'What this test cannot see' "
               "names the test that could"),
    "labs": ("lab values over time against their reference intervals (the lab report's own, "
             "else a reference laboratory's), rises checked by the EGTM rule, kinetics, flags "
             "with their rules and your review marks",
             "lesions, their size or site (imaging does), an assay change the record does not "
             "state; a raised value is not evidence of progression by itself"),
    "ctdna": ("the plasma variants' allele fractions over time, their calls and rules, the "
              "ESR1 rule (PADA-1, SERENA-6) as evidence, possible clonal hematopoiesis",
              "whether a variant comes from the tumor without white-cell sequencing; 'not "
              "detected' is not 'absent'"),
    "genomics": ("the observed variants with detection, interpretation (CIViC) and predicted "
                 "effect kept apart; copy number, mutation burden, pathways; a resistance "
                 "watchlist", "genes outside the panel; one sample is one place and one time; "
                 "purity and depth limit what is seen"),
    "slides": ("the patient's own H&E section: tissue class per tile, the tumor front and the "
               "direction of invasion, breakaway candidates, lymphocytes by zone, satellite "
               "islands, a risk map; every class is a model inference",
               "grade, receptors, mutations, margins, lymphovascular invasion; a tile is 112 "
               "µm, not a cell"),
    "omics": ("the PAM50 subtype, pathway and immune scores, receptor status read against "
              "RNA and protein, protein pathways, promoter methylation",
              "protein level from RNA, single cells, where in the tumor; a subtype from bulk "
              "RNA is not the IHC surrogate subtype"),
    "radiology": ("imaging reports read as text and a lesion table across reads; for public "
                  "studies, an image viewer with contours, measurements and kinetics",
                  "mutations; a change across a protocol or scanner difference"),
    "documents": ("the documents' breast pathology facts, each at its source sentence; "
                  "documented kept apart from inferred; conflicts side by side",
                  "what the documents do not say; diagnoses beyond breast pathology"),
    "evolution": ("what to watch next from a cited table, raised by the file's treatments, "
                  "receptor status and drivers, with the evidence for and against; clonal "
                  "order as alternatives; trials that mention the genes",
                  "whether a treatment will work: hypotheses, never a regimen"),
    "imports": ("lab results, reports, sequencing, imaging reports and images brought into the "
                "file, each checked on intake and added as a new report version",
                "anything beyond this browser session; images and scans are not analyzed "
                "here"),
    "timeline": ("every report version on a time axis, the risk at each, and any two versions "
                 "compared: what changed and why", "change between versions of a file that "
                 "holds one sample (the TCGA cases)"),
    "methods": ("a card per model and rule with its numbers and known failures, the data "
                "sources and licenses, every placeholder", "a patient's findings: open a "
                "file"),
}


def glossary(label: str) -> str:
    """The one sentence a chip opens: its own, or that of the label it names ("placeholder
    threshold" → placeholder, "subtype call: experimentally validated" → validated)."""
    if label in GLOSSARY:
        return GLOSSARY[label]
    low = label.lower()
    for key in sorted(GLOSSARY, key=len, reverse=True):
        if key.lower() in low:
            return GLOSSARY[key]
    return ("A label of this page; the Methods and validation page explains each model and "
            "rule.")


def count_label(name: str, count=None) -> str:
    """A details section's header: its name and how many items it holds ("Satellite islands
    (19)"); ``count`` may be a short phrase ("3 excluded") or None."""
    return name if count is None or count == "" else f"{name} ({count})"


def title(workbench: str, patient: str, test: str | None = None, as_of: str | None = None) -> str:
    """A workbench page's one-line title: the workbench, the patient and the test opened
    ("Pathology slide workbench · Case 299 · Diagnostic H&E section"), and the report version
    when it isn't the latest."""
    return " · ".join([WORKBENCHES.get(workbench, workbench), patient,
                       *([test] if test else []), *([f"as of {as_of}"] if as_of else [])])


def chip(label: str, color: str | None = None) -> str:
    """A Markdown badge. A label naming a placeholder is always orange, so a placeholder never
    looks validated; other labels take the shared color, then ``color``, then gray."""
    if "placeholder" in label:
        color = "orange"
    return f":{COLORS.get(label) or color or 'gray'}-badge[{label}]"


VARIANT_MARKS = re.compile(r"(?<=\d)\*|(?<=fs)\*|(?<=\d)_(?=\w)")  # not URLs' evidence_items


def esc(text) -> str:
    """Text for Markdown with the emphasis characters of variant names escaped: a stop after a
    position ("TP53 R196*"), a frameshift ("RUNX1 D96Gfs*15") and an underscore inside a word
    ("TP53 X225_splice") would otherwise turn into italics. Emphasis that is meant (**bold**,
    *italic*) is left alone, so a note written in Markdown passes through too."""
    return VARIANT_MARKS.sub(lambda m: "\\" + m.group(0), str(text))

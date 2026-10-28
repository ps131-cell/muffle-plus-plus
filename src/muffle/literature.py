"""Cited sources as data: the Bhargava lab's stroma and infrared-imaging papers (and Triulzi 2013,
whose ECM3 signature the lab imaged), the evidence category of each module of the app in the
lab's scheme, an EASSI-H line per module, and the infrared modules MuFFLe++ plans but cannot
build (docs/decisions.md, 2026-10-28).

Evidence categories, adapted from Bhargava 2023 (Annu Rev Anal Chem): I identifying cells and
tissue, II disease chemistry and subtyping, III grading, IV prognosis or prediction; each asks for
more proof than the last. EASSI-H (the review's "experimental and analytical specifications for
spectroscopic imaging in histopathology") is borrowed as a reporting line: data, n, split,
external validation, headline result. Numbers come from docs/*.md and the Methods page only;
"not reported" where those say nothing. MuFFLe++ is independent of the lab and of the Cancer
Center at Illinois, which have neither reviewed nor endorsed it; no code of theirs is used.
"""

from __future__ import annotations

PLANNED = "planned"
NOT_REPORTED = "not reported"
CATEGORIES = {"I": "identifying cells and tissue", "II": "disease chemistry and subtyping",
              "III": "grading", "IV": "prognosis or prediction"}
INDEPENDENCE = (
    "The stroma and ECM3 content is adapted from published work of the Chemical Imaging and "
    "Structures Laboratory (R. Bhargava, University of Illinois Urbana-Champaign), with "
    "citations. MuFFLe++ is independent: neither the laboratory nor the Cancer Center at "
    "Illinois has reviewed or endorsed it, and no code of theirs is used.")

# key -> the citation, a one-line finding, its evidence category and its caveat
CITATIONS: dict[str, dict] = {
    "mittal2018": {
        "authors": "Mittal S, Yeh K, Leslie LS, Kenkel S, Kajdacsy-Balla A, Bhargava R",
        "year": 2018, "journal": "Proc Natl Acad Sci U S A 115(25):E5651-E5660",
        "title": "Simultaneous cancer and tumor microenvironment subtyping using confocal "
                 "infrared microscopy for all-digital molecular histopathology",
        "doi": "10.1073/pnas.1719551115", "pmid": "29866827",
        "finding": "infrared imaging sorts breast tissue into four epithelial and three stromal "
                   "subtypes (dense, loose, desmoplastic); a confocal laser instrument made it "
                   "about 50-fold faster at 2 µm pixels",
        "category": "I",
        "caveat": {"n": "a 100-case breast tissue microarray", "centres": "one tissue set",
                   "external_validation": "no"}},
    "tiwari2020": {
        "authors": "Tiwari S, Triulzi T, Holton S, Regondi V, Paolini B, Tagliabue E, Bhargava R",
        "year": 2020, "journal": "Sci Rep 10:5442",
        "title": "Infrared spectroscopic imaging visualizes a prognostic extracellular "
                 "matrix-related signature in breast cancer",
        "doi": "10.1038/s41598-020-62403-2", "pmid": "32214177",
        "finding": "the infrared spectra of collagen pixels detect the ECM3 stromal signature "
                   "(AUC 0.87; 20 of 22 ECM3 and 19 of 20 other patients right), and ECM3 "
                   "collagen lay mainly at the tumor borders",
        "category": "IV",
        "caveat": {"n": "42 tumors", "centres": "one", "external_validation": "no"}},
    "mittal2019": {
        "authors": "Mittal S, Stoean C, Kajdacsy-Balla A, Bhargava R",
        "year": 2019, "journal": "Front Bioeng Biotechnol 7:246",
        "title": "Digital assessment of stained breast tissue images for comprehensive tumor "
                 "and microenvironment analysis",
        "doi": "10.3389/fbioe.2019.00246", "pmid": "31681737",
        "finding": "on H&E alone, a convolutional network separates epithelium from its "
                   "microenvironment and unsupervised clustering describes the stroma's "
                   "constituents, compartment by compartment",
        "category": "I",
        "caveat": {"n": "11 patients and a 100-patient tissue microarray",
                   "centres": NOT_REPORTED, "external_validation": "no"}},
    "schnell2020": {
        "authors": "Schnell M, Mittal S, Falahkheirkhah K, Mittal A, Yeh K, Kenkel S, "
                   "Kajdacsy-Balla A, Carney PS, Bhargava R",
        "year": 2020, "journal": "Proc Natl Acad Sci U S A 117(7):3388-3396",
        "title": "All-digital histopathology by infrared-optical hybrid microscopy",
        "doi": "10.1073/pnas.1912400117", "pmid": "32015103",
        "finding": "an infrared-optical hybrid microscope images whole unstained breast "
                   "sections and computes stainless H&E-like images (10-fold coverage, 4-fold "
                   "resolution over infrared microscopes)",
        "category": "I",
        "caveat": {"n": NOT_REPORTED, "centres": NOT_REPORTED, "external_validation": "no"}},
    "mayerich2015": {
        "authors": "Mayerich D, Walsh MJ, Kadjacsy-Balla A, Ray PS, Hewitt SM, Bhargava R",
        "year": 2015, "journal": "Technology (Singap World Sci) 3(1):27-31",
        "title": "Stain-less staining for computed histopathology",
        "doi": "10.1142/S2339547815200010", "pmid": "26029735",
        "finding": "infrared spectra mapped pixel by pixel to the colours of H&E, trichrome and "
                   "immunohistochemistry: stains computed without staining",
        "category": "I",
        "caveat": {"n": "96 patients to train, 98 checked by eye", "centres": NOT_REPORTED,
                   "external_validation": "no"}},
    "lin2024": {
        "authors": "Lin H, Falahkheirkhah K, Kindratenko V, Bhargava R",
        "year": 2024, "journal": "Mach Learn Appl 16:100549",
        "title": "INSTRAS: INfrared Spectroscopic imaging-based TRAnsformers for medical image "
                 "Segmentation",
        "doi": "10.1016/j.mlwa.2024.100549", "pmid": "39036499",
        "finding": "a transformer U-Net segments breast tissue from nine infrared bands, "
                   "reactive stroma among its classes (score 0.9788)",
        "category": "I",
        "caveat": {"n": "a breast tissue microarray", "centres": "one tissue set",
                   "external_validation": "no"}},
    "bhargava2023": {
        "authors": "Bhargava R",
        "year": 2023, "journal": "Annu Rev Anal Chem (Palo Alto Calif) 16(1):205-230",
        "title": "Digital histopathology by infrared spectroscopic imaging",
        "doi": "10.1146/annurev-anchem-101422-090956", "pmid": "37068745",
        "finding": "a review: four categories of pathology workflows by the proof they need, "
                   "and the EASSI-H guidelines for reporting spectroscopic imaging studies",
        "category": "review",
        "caveat": {"n": "a review", "centres": "a review", "external_validation": "a review"}},
    "triulzi2013": {
        "authors": "Triulzi T, Casalini P, Sandri M, Ratti M, Carcangiu ML, Colombo MP, "
                   "Balsari A, Ménard S, Orlandi R, Tagliabue E",
        "year": 2013, "journal": "PLoS One 8(2):e56761",
        "title": "Neoplastic and stromal cells contribute to an extracellular matrix gene "
                 "expression profile defining a breast cancer subtype likely to progress",
        "doi": "10.1371/journal.pone.0056761", "pmid": "23441215",
        "finding": "ECM3, an extracellular-matrix expression subtype found in six datasets "
                   "(643 tumors); worse distant-metastasis-free survival only in grade III "
                   "tumors (HR 3.0, 95% CI 1.3–7.0); a four-gene surrogate score",
        "category": "IV",
        "caveat": {"n": "643 tumors for the subtype; the four-gene score on 24 tumors",
                   "centres": "six public datasets and one institute's tumors",
                   "external_validation": "the subtype yes, the four-gene score no"}},
}

# module -> its category and the EASSI-H facts (docs/*.md and the Methods page)
MODULES: dict[str, dict] = {
    "risk_model": {
        "name": "Risk model (multi-omic Cox, federated)", "category": "IV",
        "data": "TCGA-BRCA open access (UCSC Xena GDC hub)",
        "n": "1,064 patients, 148 deaths; held out 213 patients, 26 deaths",
        "split": "three simulated hospitals (tissue source sites grouped); each site's "
                 "held-out patients", "external": "no (the hospitals are simulated)",
        "result": "held-out C-index 0.728, the mean of the three sites'"},
    "landmark": {
        "name": "MSK-CHORD landmark models", "category": "IV",
        "data": "MSK-CHORD (CC BY-NC-ND 4.0), on the training machine only",
        "n": "per landmark, in the card's table", "split": "patient-level 80/20, 5 seeds",
        "external": "no", "result": "held-out AUROC per landmark (the card's table)"},
    "tissue_head": {
        "name": "Slide tissue head", "category": "I",
        "data": "BCSS tiles of TCGA-BRCA slides (CC0) on GigaPath-Flash embeddings",
        "n": "8 slides, 1,052 tiles to train; 3 slides, 357 tiles held out",
        "split": "patient-disjoint held-out slides",
        "external": "no (no other institution, scanner or stain checked)",
        "result": "accuracy 91.9%, balanced 91.7%"},
    "nuclei": {
        "name": "Nuclei (StarDist 2D_versatile_he)", "category": "I",
        "data": "pretrained weights (BSD-3-Clause), H&E of other organs",
        "n": "up to 400 tiles per slide counted", "split": NOT_REPORTED,
        "external": "no (not validated on breast here)", "result": "none measured"},
    "til_second": {
        "name": "Second lymphocyte model (WSInfer TIL InceptionV4)", "category": "I",
        "data": "pretrained (CC BY 4.0), measured on BCSS tiles",
        "n": "357 labelled tiles on 3 slides; cutoff from the 8 training slides",
        "split": "the tissue head's held-out slides",
        "external": "no (trained on TCGA slides: an upper bound)",
        "result": "AUROC 0.955; recall 97%, specificity 79%"},
    "invasion": {
        "name": "Invasion analysis (front, arcs, fingers, islands, risk points)",
        "category": "III", "data": "the bundled cases' TCGA-BRCA diagnostic slides",
        "n": "8 slides of 5 cases", "split": NOT_REPORTED,
        "external": "no (not reviewed by a pathologist)",
        "result": "none measured; placeholder cutoffs"},
    "pam50": {
        "name": "PAM50 subtype", "category": "II",
        "data": "genefu centroids (Artistic-2.0) against TCGA's published calls",
        "n": "950 tumors compared", "split": "in-sample (centering chosen on the same tumors)",
        "external": "no", "result": "94.7% agreement (Cohen's κ 0.92)"},
    "ecm3": {
        "name": "ECM3 four-gene score", "category": "II",
        "data": "TCGA-BRCA STAR TPM (open access)", "n": "1,059 tumors as the reference",
        "split": "none: a cohort percentile, no cutoff",
        "external": "no (the four-gene score was not validated outside its paper)",
        "result": "none measured here; its prognosis (category IV) is a hypothesis"},
    "radiology": {
        "name": "Radiology models (MedSAM, mammoscreen, MONAI density, kinetics rules)",
        "category": "I", "data": "TCIA TCGA-BRCA radiology (CC BY 3.0)",
        "n": "5 bundled cases with a study (mammography: Case 926)", "split": NOT_REPORTED,
        "external": "no (not validated here)",
        "result": "none measured here; kinetics thresholds placeholders"},
    "documents": {
        "name": "Documents rules (report text)", "category": "n/a: reads recorded text",
        "data": "TCGA-Reports (CC BY 4.0) against Xena BRCA_clinicalMatrix",
        "n": "1,005 patients with a report: 524 to write the rules, 481 held out",
        "split": "patient-disjoint by barcode hash", "external": "no",
        "result": "91–98% precision where a report states the fact"},
}

PLANNED_MODULES = [
    {"name": "Stainless H&E and immunohistochemistry from unstained sections",
     "what": "stains computed from the infrared spectrum of each pixel",
     "citations": ["mayerich2015", "schnell2020"]},
    {"name": "Stromal subtypes in the front band",
     "what": "dense, loose and desmoplastic (reactive) stroma where the tumor invades, beyond "
             "H&E's single stroma class",
     "citations": ["mittal2018", "lin2024"]},
    {"name": "An infrared ECM3 collagen score per section",
     "what": "the ECM3 signature read from the collagen's chemistry at the tumor border",
     "citations": ["tiwari2020"]},
]
PLANNED_REASON = "no infrared data in this project"


def cite(key: str) -> str:
    """Short citation: first author et al., year, journal, doi."""
    c = CITATIONS[key]
    first = c["authors"].split(",")[0]
    etal = " et al." if "," in c["authors"] else ""
    return f"{first}{etal} {c['year']}, {c['journal']}, doi:{c['doi']}"


def category(module: str) -> dict:
    """A module's evidence category: {"category", "name", "chip"} (the chip's text)."""
    cat = MODULES[module]["category"]
    name = CATEGORIES.get(cat)
    return {"category": cat, "name": name,
            "chip": f"evidence category {cat}: {name}" if name else f"evidence category {cat}"}


def eassi_h(module: str) -> str:
    """A module's EASSI-H line: data, n, split, external validation, result."""
    m = MODULES[module]
    return (f"Data: {m['data']} · n: {m['n']} · split: {m['split']} · external validation: "
            f"{m['external']} · result: {m['result']}")


def planned_modules() -> list[dict]:
    """The infrared modules, each {"name", "what", "status", "reason", "citations"} with the
    citations written out; status planned, never implemented."""
    return [{**p, "status": PLANNED, "reason": PLANNED_REASON,
             "citations": [cite(k) for k in p["citations"]]} for p in PLANNED_MODULES]

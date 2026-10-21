"""Reference table of the blood and lab workbench (docs/labs.md): the analytes that matter in
breast-cancer follow-up, each with its adult reference interval, units and conversions, the source
of the interval and one line on why it matters here, with its citation.

Intervals are Mayo Clinic Laboratories' published adult reference values (their own methods),
read from the public test catalog on 2026-10-20. They are a reference laboratory's intervals, not
the patient's laboratory's: an interval imported with a result (its own lab report) always wins
over this table, because reference intervals are method-specific. A row whose interval or
citation could not be checked says "placeholder". Pure data and arithmetic, no model.
"""

from __future__ import annotations

import re

MAYO = "Mayo Clinic Laboratories test catalog"
READ = "read 2026-10-20"
PLACEHOLDER = "placeholder"
# the grammar's source tags (docs/WORKBENCHES.md §1); a reference laboratory's published interval
REFERENCE_LAB, GUIDELINE, LITERATURE = "reference laboratory", "guideline", "literature"

TUMOR, LIVER, BONE, KIDNEY, BLOOD, GENERAL = (
    "Tumor markers", "Liver", "Bone and mineral", "Kidney", "Blood count", "General chemistry")
PANELS = (TUMOR, LIVER, BONE, KIDNEY, BLOOD, GENERAL)

# citations (DOIs checked on PubMed 2026-10-20)
ASCO_2015 = ("Van Poznak et al., J Clin Oncol 2015 (ASCO guideline), doi:10.1200/JCO.2015.61.1459: "
             "CEA, CA 15-3 and CA 27-29 may be used as adjunctive assessments, not alone, in "
             "metastatic breast cancer")
EGTM_PANEL = ("EGTM breast cancer recommendations (egtm.eu; Molina et al., Tumour Biol 2005): one "
              "MUC-1 marker (CA 15-3 or CA 27.29) with CEA")
ESMO_2011 = ("Cardoso et al., Ann Oncol 2011 (ESMO guideline for locally recurrent or metastatic "
             "breast cancer), doi:10.1093/annonc/mdr372: a complete blood count, liver and renal "
             "function tests, alkaline phosphatase and calcium among the work-up's blood tests")
STEWART_2005 = ("Stewart, N Engl J Med 2005, doi:10.1056/NEJMcp042806 (hypercalcemia associated "
                "with cancer)")
PAYNE_1973 = ("Payne et al., Br Med J 1973, doi:10.1136/bmj.4.5893.643: adjusted calcium = calcium "
              "− albumin + 4.0 (mg/100 mL, g/100 mL); after adjustment the 95% limits matched the "
              "normal range")
PETRELLI_2015 = ("Petrelli et al., Acta Oncol 2015, doi:10.3109/0284186X.2015.1043026: high serum "
                 "LDH and poorer survival in solid tumors (meta-analysis of 76 studies)")
PALOMA_2 = ("Finn et al., N Engl J Med 2016 (PALOMA-2), doi:10.1056/NEJMoa1607303: grade 3-4 "
            "neutropenia in 66.4%, leukopenia in 24.8%, anemia in 5.4% with palbociclib-letrozole")
CKD_EPI_2021 = ("Inker et al., N Engl J Med 2021 (2021 CKD-EPI creatinine equation, without race), "
                "doi:10.1056/NEJMoa2102953")
CTCAE_V5 = ("NCI Common Terminology Criteria for Adverse Events (CTCAE) v5.0, 2017 (U.S. DHHS, "
            "public domain)")


def _mayo(test: str, code: int, note: str = "") -> str:
    return (f"{MAYO}, test {test} (mayocliniclabs.com/test-catalog/overview/{code}), adult "
            f"reference values, {READ}" + (f"; {note}" if note else ""))


# canonical unit first; every other unit with its factor to the canonical unit
U_ML = {"U/mL": 1.0, "kU/L": 1.0}
ENZYME = {"U/L": 1.0, "IU/L": 1.0, "µkat/L": 60.0}  # 1 µkat/L = 60 U/L (1 U = 1 µmol/min)
COUNT = {"x10^9/L": 1.0, "x10^3/µL": 1.0, "K/µL": 1.0, "/µL": 0.001, "cells/µL": 0.001,
         "/mm3": 0.001, "G/L": 1.0}

ANALYTES: dict[str, dict] = {
    "ca153": {"name": "CA 15-3", "panel": TUMOR, "marker": True, "units": U_ML,
              "aliases": ("ca 15-3", "ca15-3", "ca 15.3", "ca 153", "cancer antigen 15-3"),
              "interval": {"any": (None, 30.0)}, "source": _mayo("CA153", 81607,
                                                                  "males: use not defined"),
              "kind": REFERENCE_LAB, "why": "a MUC-1 tumor marker; with CEA, the EGTM panel",
              "why_source": f"{ASCO_2015}; {EGTM_PANEL}"},
    "ca2729": {"name": "CA 27.29", "panel": TUMOR, "marker": True, "units": U_ML,
               "aliases": ("ca 27.29", "ca27.29", "ca 27-29", "ca27-29", "ca 2729",
                           "breast carcinoma-associated antigen"),
               "interval": {"any": (None, 38.0)},
               "source": _mayo("C2729", 606583, "≤38.0 U/mL; males: use not defined; values "
                                                "vary by method"),
               "kind": REFERENCE_LAB, "why": "a MUC-1 tumor marker, an alternative to CA 15-3",
               "why_source": f"{ASCO_2015}; {EGTM_PANEL}"},
    "cea": {"name": "CEA", "panel": TUMOR, "marker": True,
            "units": {"ng/mL": 1.0, "µg/L": 1.0},
            "aliases": ("cea", "carcinoembryonic antigen"), "interval": {"any": (None, 3.0)},
            "source": _mayo("CEA", 8521, "nonsmokers ≤3.0 ng/mL; some smokers have values "
                                         "usually below 5.0 ng/mL"),
            "kind": REFERENCE_LAB, "why": "with a MUC-1 marker, the EGTM panel",
            "why_source": f"{ASCO_2015}; {EGTM_PANEL}"},
    "alp": {"name": "Alkaline phosphatase", "panel": BONE, "units": ENZYME,
            "aliases": ("alp", "alkaline phosphatase", "alk phos", "alkp"),
            "interval": {"female": (35.0, 104.0), "male": (40.0, 129.0)},
            "source": _mayo("ALP", 8340, "females ≥17 years 35-104, males ≥19 years 40-129 U/L"),
            "kind": REFERENCE_LAB,
            "why": "raised from bone (osteoblastic activity) or liver (biliary obstruction); "
                   "GGT tells the two apart",
            "why_source": f"{ESMO_2011}; {MAYO}, tests ALP (8340) and GGT (8677), "
                          "interpretation"},
    "alt": {"name": "ALT", "panel": LIVER, "units": ENZYME,
            "aliases": ("alt", "alanine aminotransferase", "sgpt"),
            "interval": {"female": (7.0, 45.0), "male": (7.0, 55.0)},
            "source": _mayo("ALT", 8362), "kind": REFERENCE_LAB,
            "why": "hepatocellular injury: liver involvement or drug toxicity",
            "why_source": ESMO_2011},
    "ast": {"name": "AST", "panel": LIVER, "units": ENZYME,
            "aliases": ("ast", "aspartate aminotransferase", "sgot"),
            "interval": {"female": (8.0, 43.0), "male": (8.0, 48.0)},
            "source": _mayo("AST", 8360, "≥14 years"), "kind": REFERENCE_LAB,
            "why": "hepatocellular injury: liver involvement or drug toxicity",
            "why_source": ESMO_2011},
    "ggt": {"name": "GGT", "panel": LIVER, "units": ENZYME,
            "aliases": ("ggt", "gamma-glutamyltransferase", "gamma gt", "gamma-gt", "ggtp"),
            "interval": {"female": (5.0, 36.0), "male": (8.0, 61.0)},
            "source": _mayo("GGT", 8677, "≥18 years"), "kind": REFERENCE_LAB,
            "why": "raised with ALP points to hepatobiliary disease; normal GGT with raised ALP "
                   "to bone",
            "why_source": f"{MAYO}, test GGT (8677), interpretation"},
    "bilirubin": {"name": "Bilirubin (total)", "panel": LIVER,
                  "units": {"mg/dL": 1.0, "µmol/L": 1 / 17.1},  # 584.7 g/mol
                  "aliases": ("bilirubin", "total bilirubin", "bilirubin total", "bili",
                              "t bili", "tbil"),
                  "interval": {"any": (0.0, 1.2)}, "source": _mayo("BILIT", 81785, "≥18 years"),
                  "kind": REFERENCE_LAB, "why": "liver function and biliary obstruction",
                  "why_source": ESMO_2011},
    "calcium": {"name": "Calcium (total)", "panel": BONE,
                "units": {"mg/dL": 1.0, "mmol/L": 4.008},  # 40.08 g/mol
                "aliases": ("calcium", "ca", "total calcium", "calcium total", "serum calcium"),
                "interval": {"any": (8.6, 10.0)},
                "source": _mayo("RFAMA", 113634, "18-59 years 8.6-10.0 mg/dL; 60-90 years "
                                                 "8.8-10.2 mg/dL: the 18-59 band is used"),
                "kind": REFERENCE_LAB,
                "why": "hypercalcemia of malignancy, from bone metastases or tumor PTHrP; read "
                       "adjusted for albumin",
                "why_source": f"{STEWART_2005}; {ESMO_2011}"},
    "phosphate": {"name": "Phosphate", "panel": BONE,
                  "units": {"mg/dL": 1.0, "mmol/L": 3.097},  # 30.97 g/mol (as phosphorus)
                  "aliases": ("phosphate", "phosphorus", "inorganic phosphate", "phos", "po4"),
                  "interval": {"any": (2.5, 4.5)},
                  "source": _mayo("RFAMA", 113634, "phosphorus ≥18 years"),
                  "kind": REFERENCE_LAB, "why": "read with calcium in the bone and mineral "
                                                "picture",
                  "why_source": f"{PLACEHOLDER}: no citation checked for this row"},
    "ldh": {"name": "LDH", "panel": GENERAL, "units": ENZYME,
            "aliases": ("ldh", "ld", "lactate dehydrogenase"),
            "interval": {"any": (122.0, 222.0)}, "source": _mayo("LD", 8344, "≥18 years"),
            "kind": REFERENCE_LAB, "why": "a prognostic marker of tumor burden, not specific",
            "why_source": PETRELLI_2015},
    "albumin": {"name": "Albumin", "panel": GENERAL, "units": {"g/dL": 1.0, "g/L": 0.1},
                "aliases": ("albumin", "alb", "serum albumin"),
                "interval": {"any": (3.5, 5.0)}, "source": _mayo("RFAMA", 113634),
                "kind": REFERENCE_LAB,
                "why": "liver synthetic function and nutrition; needed to read calcium",
                "why_source": PAYNE_1973},
    "creatinine": {"name": "Creatinine", "panel": KIDNEY,
                   "units": {"mg/dL": 1.0, "µmol/L": 1 / 88.42},  # 113.1 g/mol
                   "aliases": ("creatinine", "creat", "cr", "serum creatinine", "scr"),
                   "interval": {"female": (0.59, 1.04), "male": (0.74, 1.35)},
                   "source": _mayo("CRTS1", 48216, "females ≥16, males ≥15 years"),
                   "kind": REFERENCE_LAB,
                   "why": "kidney function, for drug dosing and bone-targeted agents",
                   "why_source": ESMO_2011},
    "hemoglobin": {"name": "Hemoglobin", "panel": BLOOD,
                   "units": {"g/dL": 1.0, "g/L": 0.1, "mmol/L": 1.611},  # monomer basis
                   "aliases": ("hemoglobin", "haemoglobin", "hb", "hgb"),
                   "interval": {"female": (11.6, 15.0), "male": (13.2, 16.6)},
                   "source": _mayo("CBC", 9109, "≥18 years"), "kind": REFERENCE_LAB,
                   "why": "anemia under chemotherapy or a CDK4/6 inhibitor, or marrow "
                          "involvement",
                   "why_source": PALOMA_2,
                   "grades": ("below", [(1, None, 10.0), (2, 10.0, 8.0), (3, 8.0, None)])},
    "wbc": {"name": "White cells", "panel": BLOOD, "units": COUNT,
            "aliases": ("wbc", "white cells", "white blood cells", "white cell count",
                        "leukocytes", "white blood cell count"),
            "interval": {"any": (3.4, 9.6)}, "source": _mayo("CBC", 9109, "≥18 years"),
            "kind": REFERENCE_LAB, "why": "leukopenia under a CDK4/6 inhibitor or chemotherapy",
            "why_source": PALOMA_2,
            "grades": ("below", [(1, None, 3.0), (2, 3.0, 2.0), (3, 2.0, 1.0), (4, 1.0, None)])},
    "anc": {"name": "Neutrophils (absolute)", "panel": BLOOD, "units": COUNT,
            "aliases": ("anc", "neutrophils", "absolute neutrophils", "neutrophil count",
                        "absolute neutrophil count", "neut", "neutrophils absolute"),
            "interval": {"any": (1.56, 6.45)}, "source": _mayo("CBC", 9109, "≥18 years"),
            "kind": REFERENCE_LAB,
            "why": "neutropenia is the most common grade 3-4 toxicity of palbociclib",
            "why_source": PALOMA_2,
            "grades": ("below", [(1, None, 1.5), (2, 1.5, 1.0), (3, 1.0, 0.5), (4, 0.5, None)])},
    "platelets": {"name": "Platelets", "panel": BLOOD, "units": COUNT,
                  "aliases": ("platelets", "platelet count", "plt", "thrombocytes"),
                  "interval": {"female": (157.0, 371.0), "male": (135.0, 317.0)},
                  "source": _mayo("CBC", 9109, "≥18 years"), "kind": REFERENCE_LAB,
                  "why": "thrombocytopenia under chemotherapy, or marrow involvement",
                  "why_source": ESMO_2011,
                  "grades": ("below", [(1, None, 75.0), (2, 75.0, 50.0), (3, 50.0, 25.0),
                                       (4, 25.0, None)])},
    # derived: calculated by the workbench from measured values, never imported
    "ca_adj": {"name": "Calcium (albumin-adjusted)", "panel": BONE, "derived": True,
               "units": {"mg/dL": 1.0}, "aliases": (), "interval": {"any": (8.6, 10.0)},
               "source": f"the total-calcium interval above, which Payne et al. 1973 found to "
                         f"hold after adjustment ({_mayo('RFAMA', 113634)})",
               "kind": REFERENCE_LAB, "why": "calcium read against a low albumin",
               "why_source": PAYNE_1973},
    "egfr": {"name": "eGFR (2021 CKD-EPI)", "panel": KIDNEY, "derived": True,
             "units": {"mL/min/1.73 m2": 1.0}, "aliases": (), "interval": {"any": (60.0, None)},
             "source": _mayo("CRTS1", 48216, "eGFR ≥60 mL/min/BSA, 2021 CKD-EPI creatinine "
                                             "equation"),
             "kind": REFERENCE_LAB, "why": "kidney function from creatinine, age and sex",
             "why_source": CKD_EPI_2021},
}
for _key, _a in ANALYTES.items():  # the canonical unit is the first one listed
    _a["unit"] = next(iter(_a["units"]))
    _a["key"] = _key
TUMOR_MARKERS = tuple(k for k, a in ANALYTES.items() if a.get("marker"))
UNLISTED = "not in the reference table"


def _norm(s: str) -> str:
    """A name or unit in one spelling: lower case, µ/μ/u alike, no spaces, ^, *, × or brackets."""
    s = (s or "").lower().replace("μ", "u").replace("µ", "u").replace("×", "x")
    s = re.sub(r"[\s^*()]", "", s).replace("10e", "10")
    return s[1:] if s.startswith("x10") else s


ALIAS = {_norm(alias): key for key, a in ANALYTES.items()
         for alias in (*a["aliases"], a["name"], key) if not a.get("derived")}


def lookup(name: str) -> str | None:
    """The table's key for an analyte name as a lab report writes it, or None."""
    return ALIAS.get(_norm(name))


def custom_key(name: str) -> str:
    """The record key of an analyte not in the table: prefixed, so it can never collide with a
    record field ("month", "text", "hr" ...)."""
    return "lab:" + re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")


def convert(key: str, value: float, unit: str) -> tuple[float, str]:
    """``value`` in ``unit`` → (value, canonical unit) for a table analyte. Raises ValueError with
    the reason in words when the unit is not one the table knows for it."""
    a = ANALYTES[key]
    factor = {_norm(u): f for u, f in a["units"].items()}.get(_norm(unit))
    if factor is None:
        raise ValueError(f"unit \"{unit}\" is not one the reference table converts for "
                         f"{a['name']} ({', '.join(a['units'])})")
    return value * factor, a["unit"]


def interval(key: str, sex: str | None = None) -> tuple[float | None, float | None, str] | None:
    """(low, high, which) for a table analyte: the sex's interval, the only one, or, with the sex
    not known and intervals that differ, the wider bounds of the two (so nothing is flagged that
    either sex's interval would accept), with ``which`` saying so. None for an unlisted key."""
    a = ANALYTES.get(key)
    if a is None:
        return None
    iv = a["interval"]
    if "any" in iv:
        return (*iv["any"], "adults")
    if sex in iv:
        return (*iv[sex], sex)
    (flo, fhi), (mlo, mhi) = iv["female"], iv["male"]
    return (min(flo, mlo), max(fhi, mhi),
            f"sex not recorded: the wider of the female ({flo:g}-{fhi:g}) and male ({mlo:g}-"
            f"{mhi:g}) intervals")


def ctcae_grade(key: str, value: float, low: float | None) -> int | None:
    """CTCAE v5.0 grade of a low count (literature: NCI CTCAE v5.0), None when the analyte has no
    grades here or the value is not below the lower limit. Grade 1 runs from the lower limit."""
    a = ANALYTES.get(key, {})
    if "grades" not in a or low is None or value >= low:
        return None
    _, bands = a["grades"]
    for grade, top, bottom in bands:
        if (top is None or value < top) and (bottom is None or value >= bottom):
            return grade
    return None


def adjusted_calcium(calcium_mg_dl: float, albumin_g_dl: float) -> float:
    """Payne et al. 1973: adjusted calcium = calcium − albumin + 4.0 (mg/dL, g/dL)."""
    return calcium_mg_dl - albumin_g_dl + 4.0


def egfr_ckd_epi_2021(creatinine_mg_dl: float, age: float, female: bool) -> float:
    """The 2021 CKD-EPI creatinine equation (Inker et al. 2021), mL/min/1.73 m²:
    142 × min(Scr/κ, 1)^α × max(Scr/κ, 1)^−1.200 × 0.9938^age × 1.012 if female, with κ 0.7 or
    0.9 and α −0.241 or −0.302 (female, male). Adults only."""
    k, alpha = (0.7, -0.241) if female else (0.9, -0.302)
    r = creatinine_mg_dl / k
    return 142 * min(r, 1) ** alpha * max(r, 1) ** -1.2 * 0.9938 ** age * (1.012 if female else 1)

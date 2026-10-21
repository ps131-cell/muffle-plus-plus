"""Clinical documents workbench logic (docs/WORKBENCHES.md §8): a patient file's documents, the
breast pathology facts written in them, conflicts between documents, plain-word search and a
timeline from the documents' own dates.

Everything here is a rule (regular expressions, version ``RULES_VERSION``) run locally on the
text: no language model, and no report text leaves the machine (CLAUDE.md). A fact is
**documented**: the document says it, at the character offsets it carries. Nothing is derived (an
ER percentage is not turned into a status, a pT into a stage); what a document doesn't say stays
unknown. Pure functions, tested in ``tests/test_workbench_documents.py``.

Documents of a file: SYNTHETIC-001's event texts (``muffle.timeline.EVENTS``, dated by month,
written by hand), a TCGA case's pathology report from TCGA-Reports (Kefeli and Tatonetti,
Patterns 2024; CC BY 4.0; ``app/documents/<barcode>.json``, built by
``scripts/prepare_documents.py``) and any document imported in the session (a test whose
``details`` hold ``document`` and ``text``).
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

from muffle.report.case_tools import OBSERVED
from muffle.timeline import EVENTS
from muffle.workspace import card, finding_key, look

RULES_VERSION = "documents rules v2 (2026-10-21)"
DOCUMENTED = "documented"
DOCS_DIR = Path(__file__).resolve().parents[3] / "app" / "documents"
TCGA_REPORTS = ("TCGA-Reports (Kefeli and Tatonetti, Patterns 2024, 10.1016/j.patter.2024.100933;"
                " data 10.17632/hyg5xkznpx.1; CC BY 4.0): OCR'd, cleaned TCGA pathology report")

FIELDS = {  # key -> label, in the order the facts table shows them
    "histologic_type": "Histologic type", "grade": "Nottingham grade",
    "nottingham_score": "Nottingham score", "tubules": "Tubule formation score",
    "pleomorphism": "Nuclear pleomorphism score", "mitoses": "Mitotic count score",
    "size": "Tumor size", "margins": "Margins", "margin_distance": "Closest margin",
    "lvi": "Lymphovascular invasion", "nodes_examined": "Lymph nodes examined",
    "nodes_positive": "Lymph nodes positive", "pT": "pT", "pN": "pN", "stage": "Stage group",
    "er": "ER status", "er_percent": "ER %", "er_allred": "ER Allred score",
    "pr": "PR status", "pr_percent": "PR %", "pr_allred": "PR Allred score",
    "hr": "Hormone receptor status", "her2": "HER2 status", "her2_ihc": "HER2 IHC score",
    "her2_ish": "HER2 ISH result", "her2_ratio": "HER2/CEP17 ratio", "ki67": "Ki-67 %",
    "laterality": "Laterality", "specimen": "Specimen type", "drug": "Drug named",
    "ecog": "ECOG performance status", "date": "Date written",
}
# what the extraction does not read; shown on the page
CANNOT_SEE = [
    "Facts in tables, images or scanned pages the OCR lost; OCR errors (\"pNO\" is read as pN0, "
    "other misreadings are not).",
    "Negations and hedges beyond the patterns in the rules card (\"cannot exclude\", "
    "\"suspicious for\" are not read as findings).",
    "Which specimen a fact belongs to when a report covers several: every match is listed.",
    "Anything outside breast pathology and the named drugs: imaging reads, lab values and "
    "treatments plans stay text (their own workbenches read them).",
    "A rule match is not a pathologist's read: check the source sentence before relying on it.",
]

# ----------------------------------------------------------------------------- the rules

_N = r"(\d+(?:\.\d+)?)"
_POL = re.compile(r"\b(positive|negative|pos|neg|equivocal|borderline|indeterminate)\b"
                  r"(?!\s*(?:[<>=≤≥]|is defined|for\b)|-[A-Za-z])|"  # not "NEG-HER2" (a label)
                  r"(?<![A-Za-z0-9])([+-])(?=\s*(?:[^\sA-Za-z0-9]|$))",  # "ER -. PR +", not "- POS"
                  re.I)
_JOIN = re.compile(r"\s*(?:/|,|and|&)\s*", re.I)  # "ER/PR positive", "ER and PR are negative"
POLARITY = {"pos": "positive", "neg": "negative", "+": "positive", "-": "negative",
            "borderline": "equivocal"}
_RECEPTOR = {
    "er": r"\bER\b|\bestrogen(?:\s+receptors?)?|\boestrogen(?:\s+receptors?)?",
    "pr": r"\bPR\b|\bPgR\b|\bprogesterone(?:\s+receptors?)?",
    "hr": r"\bhormone[- ]receptors?(?:\s+status)?",
    "her2": r"\bHER[- ]?2(?:\s*/?\s*-?\s*neu)?\b|\bHER[- ]?2neu\b|\bc-?erbB-?2\b|\bERBB2\b|"
            r"\bherceptest\b",
    "ki67": r"\bKi-?67\b|\bMIB-?1\b",
}
_TERM = re.compile("|".join(f"(?P<{k}>{v})" for k, v in _RECEPTOR.items()), re.I)
_LIST_POL = re.compile(r"\b(positive|negative)\s+(?:for|of)\s+((?:(?:" + "|".join(
    _RECEPTOR[k] for k in ("er", "pr", "her2")) + r")(?:\s*(?:receptors?)?\s*(?:,|and|&|/|or)?\s*)"
    r")+)", re.I)
_PCT = re.compile(r"(?<![<>≤≥\d.\-–])(?:over\s+|approximately\s+|about\s+)?(\d{1,3}(?:\.\d+)?)\s*%",
                  re.I)
_ALLRED = re.compile(r"al[lI]red(?:\s+score)?\s*[-:=]?\s*([0-8])(?:\s*/\s*8)?\b", re.I)
_ZERO_OR_1 = r"\s*(?:or|/|-|–|to)\s*1\s*\+"  # "zero or 1+", "0/1+": a band, not 1+
_IHC = re.compile(rf"\b(?:0|zero){_ZERO_OR_1}|(?<![\d.\-–])([0-3])\s*\+|"
                  rf"\b(?:score|ihc)\s*(?:of\s*)?[:=]?\s*(0)\b(?!\.?\d|{_ZERO_OR_1})", re.I)
_ISH = re.compile(r"\b(not\s+amplified|non-?amplified|no\.?\s+amplification|amplified)\b|"
                  r"\b(positive|negative)\s+by\s+(?:FISH|CISH|SISH|ISH)\b", re.I)
_RATIO = re.compile(r"ratio\b[^0-9<>=]{0,25}" + _N, re.I)  # not a cutoff ("ratio </=2.0")
_KI67_WORD = re.compile(r"\b(low|high|intermediate)\b", re.I)
_CAT = r"(?:negative|positive|equivocal|borderline|indeterminate)"
_BAND = (r"(?:score(?:\s*[:=])?\s*)?(?:[<>≤≥]=?\s*)?\d+(?:\.\d+)?(?:\s*[%+])?"
         r"(?:\s*(?:-|–|/|,|or|to)\s*\d+(?:\.\d+)?(?:\s*[%+])?)?")
_LEGEND = re.compile(  # a HER2 scoring legend, not a result: "Negative 0-1+, Equivocal 2+",
    # "2=INDETERMINATE", "score of 2 are considered borderline", "... that is interpreted as"
    rf"(?P<list>(?:\b{_CAT}\W{{0,4}}{_BAND}[\s.,;:)\]]*(?:and\s+)?){{2,}})|"
    rf"\b[0-3]\s*\+?\s*(?:=|(?:is|are)\s+considered)\s*{_CAT}\b|"
    rf"\bthat\s+(?:is|are)\s+interpreted\s+as\s+{_CAT}\b", re.I)

_TYPE = re.compile(
    r"\b(?:(invasive|infiltrating)\s+(?:mammary\s+)?(ductal\s+and\s+lobular|lobular\s+and\s+"
    r"ductal|ductal|duct|lobular|mucinous|tubular|medullary|metaplastic|micropapillary|papillary|"
    r"cribriform|apocrine)\b(?:\s+(?:mammary\s+)?carcinoma|\s+adenocarcinoma)?|"
    r"(mucinous|tubular|medullary|metaplastic|colloid)\s+carcinoma|"
    r"(ductal)\s+adenocarcinoma)", re.I)
_GRADE = re.compile(
    r"\b(?:nottingham|histologic(?:al)?|elston|bloom[- ]?richardson|sbr|combined|overall|scarff)"
    r"(?:\s+(?:combined|histologic(?:al)?|modified))*\s+grade\s*(?:\(\s*1\s*,\s*2\s*,?\s*:?\s*3\s*\))?"
    r"\s*[:=]?\s*(?:(well|moderately|poorly)[\s-]+differentiated\s*)?\(?\s*(?:G\s*)?"
    r"(III|II|I|[1-3])?\b(?:\s*(?:/|of)\s*(?:III|3))?", re.I)
_DIFF = {"well": "1", "moderately": "2", "poorly": "3"}
_ROMAN = {"I": "1", "II": "2", "III": "3"}
_SCORE = re.compile(r"\b(?:total\s+)?nottingham\s+score\s*[:=]?\s*([3-9])\b(?:\s*/\s*9)?|"
                    r"\btotal\s+score\s*[:=]?\s*([3-9])\s*/\s*9", re.I)
_COMPONENTS = {
    "tubules": r"tubules?(?:\s+formation)?|glandular(?:/tubular)?\s+differentiation",
    "pleomorphism": r"nuclear\s+pleomorphism|nuclei",
    "mitoses": r"mitos[ei]s|mitotic\s+(?:activity|count|rate)",
}
_COMPONENT = re.compile("|".join(
    rf"(?P<{k}>\b(?:{v})(?:\s+score)?\s*[:=]?\s*(?:score\s*)?)([1-3])\b(?!\s*(?:mm|cm|per|/\s*10))"
    for k, v in _COMPONENTS.items()), re.I)
_SIZE = re.compile(
    r"\b(?:tumou?r\s+size|size\s+of\s+(?:the\s+)?(?:invasive\s+)?(?:tumou?r|carcinoma)|"
    r"(?:greatest|maximum|largest)\s+dimension(?:\s+(?:of\s+)?invasive\s+component)?|"
    r"(?:largest\s+)?(?:invasive\s+)?tumou?r\s+measures)[^0-9.]{0,40}?" + _N +
    r"\s*(?:x\s*\d+(?:\.\d+)?\s*){0,2}(cm|mm)\b", re.I)
_MARGIN = re.compile(
    r"\bmargins?(?:\s+status)?\s*(?:are|is)?\s*[:\-]?\s*(?:all\s+)?(negative|positive|close|free|"
    r"clear|uninvolved|involved|not\s+involved)\b(?!\s+by\s+[a-z ]+:)", re.I)
_MARGIN_DIST = re.compile(r"\b(?:closest|nearest)\s+(?:surgical\s+)?margin[^0-9]{0,40}?" + _N +
                          r"\s*(cm|mm)\b|\b" + _N + r"\s*(cm|mm)\s+from\s+the\s+(?:closest|"
                          r"nearest)\s+(?:\w+\s+)?margin", re.I)
_LVI = re.compile(
    r"\b(no\s+(?:evidence\s+of\s+)?)?(?:lympho-?vascular|lymph-?vascular|angiolymphatic|vascular\s*/\s*lymphatic|"
    r"venous\s*/\s*lymphatic|blood\s+vessel\s+and\s+lymphatic)(?:\s+space)?\s+invasion\s*"
    r"(?:is\s+)?[:\-\s]*(present|absent|not\s+identified|identified|not\s+seen|seen|negative|"
    r"positive|indeterminate|noted)?", re.I)
_LVI_VALUE = {"present": "present", "identified": "present", "seen": "present",
              "positive": "present", "absent": "absent", "not identified": "absent",
              "not seen": "absent", "negative": "absent", "indeterminate": "indeterminate",
              "noted": "present"}
_NODES = re.compile(
    r"\b(?:lymph\s+nodes?\s+(?:examined|removed|identified|retrieved)|(?:number\s+of\s+)?"
    r"(?:lymph\s+)?nodes\s+examined|total\s+(?:number\s+of\s+)?(?:lymph\s+)?nodes)\s*"
    r"(?:\(\w+\))?\s*[:=]?\s*(\d{1,3})\b(?!\s*/)|"
    r"\b(?:lymph\s+nodes?\s+positive|positive\s+lymph\s+nodes?|(?:number\s+of\s+)?(?:lymph\s+)?"
    r"nodes\s+(?:positive|involved)|number\s+of\s+(?:positive|involved)\s+(?:lymph\s+)?nodes?)"
    r"\s*(?:\(\w+\))?\s*[:=]?\s*(\d{1,3})\b(?!\s*/)|"
    r"\b(\d{1,3})\s*(?:/|of)\s*(\d{1,3})\s+(?:\w+\s+)?(?:lymph\s+)?nodes?\b|"
    r"\blymph\s+nodes?[^.()]{0,60}?\((\d{1,3})\s*/\s*(\d{1,3})\)|"
    r"\blymph\s+node\s+status\s*:\s*(?:positive|negative)\s*(\d{1,3})\s*/\s*(\d{1,3})", re.I)
_TNM = re.compile(
    r"(?<![a-z])(y?p)\s?T\s?(is|[0-4xX])\s?(mi|[a-d])?(?:\s*\((?:m|\d+)\))?"
    r"(?:[\s,.]*(?:p|\(sn\))?\s?N\s?([0-3oOxX])\s?(mi|[a-c])?\s?(\((?:i|mol|sn)\s?[+-]?\))?)?",
)
_PN = re.compile(r"(?<![A-Za-z])pN\s?([0-3oOxX])\s?(mi|[a-c])?\s?(\((?:i|mol|sn)\s?[+-]?\))?")
_STAGE = re.compile(  # not "T Stage: 2" (a TNM form field) nor an assay's boilerplate
    r"(?<![TNM] )(?<![TNM])\b(?:ajcc\s+)?(?:pathologic(?:al)?\s+|summary\s+|prognostic\s+)?stage"
    r"(?:\s+group(?:ing)?)?\s*[:=]?\s*(0|IV|I{1,3}|[1-4])([ABC])?\b(?![/\d])"
    r"(?![,\s]+node-(?:positive|negative)\s+breast\s+cancer\s+patients)", re.I)
_LATERALITY = re.compile(r"\b(left|right)\s+(?:axillary\s+)?breast\b|\bbreast\s*,\s*(left|right)"
                         r"\b|\blaterality\s*[:=]?\s*(left|right|bilateral)\b", re.I)
_SPECIMEN = re.compile(
    r"\b(modified\s+radical\s+mastectomy|radical\s+mastectomy|simple\s+mastectomy|total\s+"
    r"mastectomy|skin[- ]sparing\s+mastectomy|nipple[- ]sparing\s+mastectomy|partial\s+mastectomy|"
    r"segmental\s+mastectomy|mastectomy|lumpectomy|wide\s+local\s+excision|excisional\s+biopsy|"
    r"re-?excision|core\s+(?:needle\s+)?biopsy|sentinel\s+(?:lymph\s+)?node\s+biopsy|axillary\s+"
    r"(?:lymph\s+node\s+)?dissection)\b", re.I)
DRUGS = ("doxorubicin", "epirubicin", "cyclophosphamide", "paclitaxel", "nab-paclitaxel",
         "docetaxel", "carboplatin", "cisplatin", "capecitabine", "gemcitabine", "eribulin",
         "vinorelbine", "methotrexate", "fluorouracil", "letrozole", "anastrozole", "exemestane",
         "tamoxifen", "fulvestrant", "elacestrant", "camizestrant", "goserelin", "leuprolide",
         "palbociclib", "ribociclib", "abemaciclib", "alpelisib", "inavolisib", "capivasertib",
         "everolimus", "trastuzumab deruxtecan", "trastuzumab emtansine", "trastuzumab",
         "pertuzumab", "lapatinib", "neratinib", "tucatinib", "olaparib", "talazoparib",
         "pembrolizumab", "atezolizumab", "sacituzumab govitecan", "denosumab",
         "zoledronic acid")
_DRUG = re.compile(r"\b(" + "|".join(re.escape(d) for d in DRUGS) + r")\b", re.I)
_ECOG = re.compile(r"\bECOG(?:\s+(?:PS|performance\s+status))?\s*[:=]?\s*([0-4])\b", re.I)
_MONTHS = "jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec"
_DATE = re.compile(r"\b(\d{1,2}/\d{1,2}/(?:19|20)?\d{2})\b(?![/\d])|"
                   r"\b((?:19|20)\d{2}-\d{2}-\d{2})\b|"
                   rf"\b((?:{_MONTHS})[a-z]*\.?\s+\d{{1,2}},?\s+(?:19|20)\d{{2}})\b", re.I)
_TYPE_NAMES = {"duct": "invasive ductal carcinoma", "ductal": "invasive ductal carcinoma",
               "lobular": "invasive lobular carcinoma",
               "ductal and lobular": "mixed ductal and lobular carcinoma",
               "lobular and ductal": "mixed ductal and lobular carcinoma",
               "colloid": "mucinous carcinoma"}
RULES = {  # field group -> what the rule reads (the rules card)
    "Histologic type": "\"invasive / infiltrating\" + ductal, lobular, both, mucinous, tubular, "
                       "medullary, metaplastic, (micro)papillary, cribriform or apocrine; "
                       "\"ductal adenocarcinoma\". In-situ carcinoma is not a type here",
    "Nottingham grade and score": "\"Nottingham / histologic / combined / overall / SBR grade\" "
                                  "with 1–3, I–III or well / moderately / poorly "
                                  "differentiated; \"Nottingham score\" 3–9; the three "
                                  "component scores 1–3 by name",
    "Tumor size": "\"tumor size\", \"greatest / maximum dimension\", \"tumor measures\" with a "
                  "number in cm or mm (the first dimension of a triple)",
    "Margins": "\"margin(s)\" with negative, positive, close, free, clear or (un)involved, not a "
               "form label (\"margins involved by ...:\"); closest margin distance",
    "Lymphovascular invasion": "lymphovascular, angiolymphatic or vascular/lymphatic invasion "
                               "with present / absent / (not) identified, or \"no ... invasion\"",
    "Lymph nodes": "\"lymph nodes examined / positive: N\", \"k/n lymph nodes\", \"k of n "
                   "nodes\", \"(k/n)\" after \"lymph node\"",
    "pT, pN, stage": "pT0–4 / pTis / pTX with its suffix and an optional N that follows; pN "
                     "alone; OCR's letter O read as 0; \"stage\" with 0, I–IV or 1–4 and A–C",
    "ER, PR, hormone receptors": "the receptor named, then the first positive / negative / "
                                 "+ / − before the next receptor (not a definition such as "
                                 "\"positive is defined as\" or \"negative < 6.5\"); "
                                 "\"positive for ER and PR\"; a % and an Allred score in the "
                                 "same stretch. A % is never turned into a status",
    "HER2": "HER2 / HER-2/neu / c-erbB-2 with positive / negative / equivocal, an IHC score "
            "0–3+ (\"zero or 1+\" kept as the band 0 or 1+), an ISH result (amplified, not "
            "amplified, positive / negative by FISH) and a ratio. Not read: a scoring legend "
            "(\"Negative 0-1+, Equivocal 2+\", \"2=INDETERMINATE\", \"score of 2 are considered "
            "borderline\"), and a status word its own IHC score argues against (positive with 0 "
            "or 1+, or 2+ unless amplified; negative with 3+): a form whose answers slid a row, a "
            "comment that runs on, \"weakly positive (2+)\". A score is never turned into a "
            "status",
    "Ki-67": "Ki-67 or MIB-1 with a % (or low / high as written)",
    "Laterality, specimen": "left / right breast, \"breast, left\", \"laterality: ...\"; "
                            "mastectomy types, lumpectomy, excisions, core biopsy, sentinel "
                            "node biopsy, axillary dissection",
    "Drugs, ECOG, dates": f"{len(DRUGS)} breast cancer drug names (generic); ECOG 0–4; full "
                          "dates (m/d/y, ISO, month name). Years alone are not dates",
}


def sentences(text: str) -> list[tuple[int, int]]:
    """(start, end) of each sentence: OCR'd reports join their lines with ". ", so a sentence
    ends at ". " or "; " (a decimal point has no space after it)."""
    out, start = [], 0
    for m in re.finditer(r"[.;!?](?=\s)|\n+", text):
        end = m.end()
        if text[start:end].strip():
            out.append((start, end))
        start = end
    if text[start:].strip():
        out.append((start, len(text)))
    return out


def _sentence(spans: list[tuple[int, int]], a: int, b: int) -> tuple[int, int]:
    """The sentences that hold characters a..b."""
    s = next((s for s, e in spans if s <= a < e), a)
    e = next((e for s, e in spans if s < b <= e), b)
    return s, max(e, b)


def extract(text: str, doc: str = "") -> list[dict]:
    """The breast pathology facts ``text`` documents, in reading order. Each fact: {"doc",
    "field", "label", "value", "start", "end" (the matched characters), "sentence" ((start, end)
    of the sentence around them), "quote" (that sentence), "status": "documented", "rule"}. One
    fact per (field, value): the first place a document says it."""
    spans, raw = sentences(text), []

    def add(field, value, a, b, rule):
        raw.append((field, str(value), a, b, rule))

    for m in _TYPE.finditer(text):
        word = (m.group(2) or m.group(3) or m.group(4) or "").lower()
        word = re.sub(r"\s+", " ", word)
        add("histologic_type", _TYPE_NAMES.get(word, f"{word} carcinoma"), *m.span(), "type")
    for m in _GRADE.finditer(text):
        g = _DIFF.get((m.group(1) or "").lower()) or _ROMAN.get((m.group(2) or "").upper(),
                                                                m.group(2))
        if g:
            add("grade", g, *m.span(), "grade")
    for m in _SCORE.finditer(text):
        add("nottingham_score", m.group(1) or m.group(2), *m.span(), "score")
    for m in _COMPONENT.finditer(text):
        key = next(k for k in _COMPONENTS if m.group(k))
        add(key, m.group(m.lastindex), *m.span(), "component")
    for m in _SIZE.finditer(text):
        add("size", f"{float(m.group(1)):g} {m.group(2).lower()}", *m.span(), "size")
    for m in _MARGIN.finditer(text):
        v = m.group(1).lower()
        v = ("negative" if v in ("free", "clear", "uninvolved") or v.startswith("not")
             else "positive" if v == "involved" else v)
        add("margins", v, *m.span(), "margins")
    for m in _MARGIN_DIST.finditer(text):
        n, u = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        add("margin_distance", f"{float(n):g} {u.lower()}", *m.span(), "margin distance")
    for m in _LVI.finditer(text):
        word = re.sub(r"\s+", " ", (m.group(2) or "").lower())
        v = "absent" if m.group(1) else _LVI_VALUE.get(word)
        if v:
            add("lvi", v, *m.span(), "lvi")
    for m in _NODES.finditer(text):
        g = m.groups()
        if g[0]:
            add("nodes_examined", int(g[0]), *m.span(), "nodes label")
        elif g[1]:
            add("nodes_positive", int(g[1]), *m.span(), "nodes label")
        else:  # "k/n" counts one specimen's nodes; "lymph node status: ... k/n" the total
            i = next(i for i in (2, 4, 6) if g[i])
            k, n, rule = int(g[i]), int(g[i + 1]), "nodes status" if i == 6 else "nodes k/n"
            if k <= n:
                add("nodes_positive", k, *m.span(), rule)
                add("nodes_examined", n, *m.span(), rule)
    tnm_n = set()
    for m in _TNM.finditer(text):
        prefix, t, suffix = m.group(1), m.group(2), m.group(3) or ""
        add("pT", f"{prefix}T{t.upper() if t in 'xX' else t}{suffix}", *m.span(), "tnm")
        if m.group(4):
            n = m.group(4).upper().replace("O", "0")
            add("pN", f"pN{n}{m.group(5) or ''}{m.group(6) or ''}".replace(" ", ""), *m.span(),
                "tnm")
            tnm_n.add(m.start(4))
    for m in _PN.finditer(text):
        if m.start(1) not in tnm_n:
            n = m.group(1).upper().replace("O", "0")
            add("pN", f"pN{n}{m.group(2) or ''}{m.group(3) or ''}".replace(" ", ""), *m.span(),
                "pn")
    for m in _STAGE.finditer(text):
        g = m.group(1).upper()
        g = {"1": "I", "2": "II", "3": "III", "4": "IV"}.get(g, g)
        add("stage", f"Stage {g}{(m.group(2) or '').upper()}", *m.span(), "stage")
    _receptors(text, add)
    for m in _LATERALITY.finditer(text):
        add("laterality", (m.group(1) or m.group(2) or m.group(3)).lower(), *m.span(),
            "laterality")
    for m in _SPECIMEN.finditer(text):
        add("specimen", re.sub(r"\s+", " ", m.group(1).lower()), *m.span(), "specimen")
    for m in _DRUG.finditer(text):
        add("drug", m.group(1).lower(), *m.span(), "drug")
    for m in _ECOG.finditer(text):
        add("ecog", m.group(1), *m.span(), "ecog")
    for m in _DATE.finditer(text):
        add("date", next(g for g in m.groups() if g), *m.span(), "date")

    out, seen = [], set()
    for field, value, a, b, rule in sorted(raw, key=lambda r: (r[2], list(FIELDS).index(r[0]))):
        key = (field, value, a if rule == "nodes k/n" else None)  # each specimen's count stays
        if key in seen:
            continue
        seen.add(key)
        s, e = _sentence(spans, a, b)
        out.append({"doc": doc, "field": field, "label": FIELDS[field], "value": value,
                    "start": a, "end": b, "sentence": (s, e), "quote": text[s:e].strip(),
                    "status": DOCUMENTED, "rule": rule})
    return out


def _outside(matches, at: int, spans):
    """The matches (in a window at offset ``at`` of the text) that start outside ``spans``."""
    return (m for m in matches if not any(s <= at + m.start() < e for s, e in spans))


def _ihc(m: re.Match) -> str:
    g = m.group(1) or m.group(2)
    return f"{g}+".replace("0+", "0") if g else "0 or 1+"


def _two_answers(value: str, ihc: re.Match | None, ish: re.Match | None) -> bool:
    """A HER2 status word the IHC score in its stretch argues against: positive with 0 or 1+ (or
    2+ when the stretch does not say amplified), negative with 3+. The stretch then holds two
    answers and the word is likely not HER2's: an OCR'd form whose answers slid a row
    ("PROGESTERONE RECEPTORS: positive. HER2/NEU: positive. zero or 1+", HER2's answer being
    "zero or 1+"), a comment that runs on, or the HercepTest-era "weakly positive (2+)"."""
    score = ihc and _ihc(ihc)
    amplified = ish and (ish.group(1) or ish.group(2)).lower() in ("amplified", "positive")
    return (value == "positive" and (score in ("0", "1+", "0 or 1+") or score == "2+"
                                     and not amplified)
            or value == "negative" and score == "3+")


def _receptors(text: str, add) -> None:
    """ER, PR, hormone receptor, HER2 and Ki-67: "positive for ER and PR" first, then each named
    receptor with what follows it up to the next receptor named (at most 120 characters). For
    HER2, a scoring legend is not read, nor a status word its own IHC score argues against."""
    terms = [(m.lastgroup, m.start(), m.end()) for m in _TERM.finditer(text)]
    legends = [m.span() for m in _LEGEND.finditer(text)  # a list names two categories or more
               if not m["list"] or len({c.lower() for c in re.findall(_CAT, m["list"], re.I)}) > 1]
    covered = set()
    for m in _LIST_POL.finditer(text):
        value = m.group(1).lower()
        for t in _TERM.finditer(m.group(2)):
            key = t.lastgroup
            a = m.start(2) + t.start()
            covered.add(a)
            add(key, value, m.start(), m.start(2) + t.end(), "positive for")
    joined = []  # receptors named together, "ER/PR positive": the value that follows is theirs
    for n, (key, a, b) in enumerate(terms):
        stop = min(terms[n + 1][1] if n + 1 < len(terms) else len(text), b + 120)
        window = text[b:stop]
        if n + 1 < len(terms) and stop == terms[n + 1][1] and _JOIN.fullmatch(window):
            joined.append((key, a))
            continue
        pending, joined = joined, []
        if key == "ki67":  # a word written right after it ("Ki-67: LOW") wins over a %
            lead = len(window) - len(window.lstrip(" :.-;("))
            w, p = _KI67_WORD.match(window, lead), _PCT.search(window)
            if w:
                add("ki67", w.group(1).lower(), a, b + w.end(), "receptor window")
            elif p:
                add("ki67", f"{float(p.group(1)):g}%", a, b + p.end(), "receptor window")
            continue
        legend = legends if key == "her2" else ()
        s, i = (next(_outside(rx.finditer(window), b, legend), None) for rx in (_IHC, _ISH))
        if a not in covered:  # a sign counts only right after the name ("ER+", "PR: -")
            p = next((p for p in _outside(_POL.finditer(window), b, legend)
                      if p.group(1) or p.start() < 3), None)
            value = p and (p.group(1) or p.group(2)).lower()
            value = POLARITY.get(value, value)
            if value and not (key == "her2" and _two_answers(value, s, i)):
                for k, start in [*pending, (key, a)]:
                    if start not in covered and k != "ki67":
                        add(k, value, start, b + p.end(), "receptor window")
        if key in ("er", "pr"):
            p = _PCT.search(window)
            if p:
                add(f"{key}_percent", f"{float(p.group(1)):g}%", a, b + p.end(), "receptor window")
            r = _ALLRED.search(window)
            if r:
                add(f"{key}_allred", r.group(1), a, b + r.end(), "receptor window")
        if key == "her2":
            if s:
                add("her2_ihc", _ihc(s), a, b + s.end(), "receptor window")
            if i:
                v = (i.group(1) or i.group(2)).lower()
                v = ("amplified" if v in ("amplified", "positive") else "not amplified")
                add("her2_ish", v, a, b + i.end(), "receptor window")
            r = _RATIO.search(window)
            if r:
                add("her2_ratio", f"{float(r.group(1)):g}", a, b + r.end(), "receptor window")


# ------------------------------------------------------------------------- documents of a file

@lru_cache(maxsize=4)
def _reports(folder: Path) -> dict[int, list[dict]]:
    """Cohort row -> its TCGA-Reports documents, read once per process."""
    return {(d := json.loads(p.read_text()))["case_index"]: d["documents"]
            for p in sorted(folder.glob("TCGA-*.json"))}


def case_documents(index: int, folder: Path = DOCS_DIR) -> list[dict]:
    """The TCGA-Reports documents of the held-out case at cohort row ``index`` (none if the
    dataset has no report for it)."""
    return _reports(folder).get(index, [])


def file_documents(pf, i: int | None = None, events: list[dict] = EVENTS) -> list[dict]:
    """The documents of a patient file as of report version ``i`` (the latest when None): each
    {"id", "title", "kind", "month", "text", "source"}. The synthetic patient's event texts up to
    that version's month, then every test in the file so far that carries a document's text (a
    TCGA report, an imported report or note)."""
    i = len(pf.versions) - 1 if i is None else i
    docs = []
    if pf.kind == "synthetic":
        until = max(v.month for v in pf.versions[: i + 1] if v.month is not None)
        docs = [{"id": event_id(e), "title": f"{e['kind']}, month {e['month']}",
                 "kind": e["kind"], "month": e["month"], "text": e["text"],
                 "source": "the synthetic patient's record, written by hand (not a real person)"}
                for e in events if e["month"] <= until]
    for v in pf.versions[: i + 1]:
        for t in v.tests:
            d = t.details
            if "text" in d and d.get("document") not in {x["id"] for x in docs}:
                docs.append({"id": d["document"], "title": d.get("title", t.name),
                             "kind": t.kind, "month": t.month, "text": d["text"],
                             "source": d.get("source", "")})
    return docs


def event_id(e: dict) -> str:
    """A synthetic event's document id: "m13-clinic-visit"."""
    return f"m{e['month']}-{e['kind'].lower().replace(' ', '-')}"


def facts(docs: list[dict]) -> list[dict]:
    """Every document's facts, documents in order."""
    return [f for d in docs for f in extract(d["text"], d["id"])]


# ------------------------------------------------------------------------------- conflicts

# fields where two documents naming different values is expected, not a conflict (performance
# status changes from visit to visit)
MANY = {"drug", "date", "specimen", "laterality", "nodes_examined", "nodes_positive",
        "margin_distance", "size", "ecog"}


def conflicts(all_facts: list[dict]) -> list[dict]:
    """Fields that two documents give different values for, kept side by side (no vote, no
    average): [{"field", "label", "values": [{"value", "docs": [...], "quotes": [...]}]}].
    Within one document several values are listed as facts, not as a conflict."""
    by_field: dict[str, dict[str, dict]] = {}
    for f in all_facts:
        if f["field"] in MANY:
            continue
        slot = by_field.setdefault(f["field"], {}).setdefault(
            f["value"], {"value": f["value"], "docs": [], "quotes": []})
        if f["doc"] not in slot["docs"]:
            slot["docs"].append(f["doc"])
            slot["quotes"].append(f["quote"])
    out = []
    for field, values in by_field.items():
        docs = {d for v in values.values() for d in v["docs"]}
        if len(values) > 1 and len(docs) > 1:
            out.append({"field": field, "label": FIELDS[field], "values": list(values.values())})
    return out


def missing_fields(all_facts: list[dict], keys=("histologic_type", "grade", "size", "margins",
                                                 "lvi", "nodes_examined", "pT", "pN", "er",
                                                 "pr", "her2", "ki67")) -> list[str]:
    """The core pathology fields no document of the file states."""
    have = {f["field"] for f in all_facts}
    return [FIELDS[k] for k in keys if k not in have]


# ---------------------------------------------------------------------------------- search

SYNONYMS = {"er": ["estrogen", "oestrogen"], "estrogen": ["er", "oestrogen"],
            "pr": ["progesterone", "pgr"], "progesterone": ["pr", "pgr"],
            "her2": ["her-2", "her 2", "erbb2", "neu", "c-erbb-2"], "lvi": ["lymphovascular",
            "angiolymphatic", "lymphatic"], "lymphovascular": ["lvi", "angiolymphatic"],
            "ki67": ["ki-67", "mib-1", "mib1"], "ki-67": ["ki67", "mib-1"],
            "node": ["nodes"], "nodes": ["node"], "tumor": ["tumour"], "tumour": ["tumor"]}
STOP = {"the", "a", "an", "of", "in", "on", "for", "and", "or", "is", "are", "was", "with", "any",
        "to", "show", "find", "me", "what", "which", "where", "does", "do", "say", "says"}


def _word(w: str) -> re.Pattern:
    """Short words match whole words only ("er" must not match "her"); longer ones also match
    as a prefix ("node" finds "nodes")."""
    return re.compile(rf"\b{re.escape(w)}\b" if len(w) <= 3 else rf"\b{re.escape(w)}", re.I)


def search(docs: list[dict], query: str) -> list[dict]:
    """Sentences of the file's documents that hold every word of ``query`` (or a synonym:
    "estrogen" finds "ER"), in plain words, case-insensitive: [{"doc", "title", "start", "end",
    "quote", "spans": [(start, end) of each matched word]}]. Empty when no document mentions
    it."""
    words = [w for w in re.findall(r"[\w+%./-]+", query.lower()) if w not in STOP]
    if not words:
        return []
    alts = [[_word(w), *(_word(s) for s in SYNONYMS.get(w, []))] for w in words]
    hits = []
    for d in docs:
        for s, e in sentences(d["text"]):
            sent = d["text"][s:e]
            found = [[m.span() for p in group for m in p.finditer(sent)] for group in alts]
            if all(found):
                hits.append({"doc": d["id"], "title": d["title"], "start": s, "end": e,
                             "quote": sent.strip(),
                             "spans": sorted((s + a, s + b) for g in found for a, b in g)})
    return hits


# -------------------------------------------------------------------------------- timeline

def timeline(docs: list[dict]) -> list[dict]:
    """Each document on the file's own time axis: the month it carries (the synthetic record,
    an import), then any full date written in its text. A TCGA report without either is
    "undated": the de-identified reports had their dates removed."""
    rows = []
    for d in docs:
        dates = [f["value"] for f in extract(d["text"], d["id"]) if f["field"] == "date"]
        rows.append({"doc": d["id"], "title": d["title"], "kind": d["kind"], "month": d["month"],
                     "dates_in_text": ", ".join(dates),
                     "when": (f"month {d['month']}" if d["month"] is not None
                              else dates[0] if dates else "undated")})
    return sorted(rows, key=lambda r: (r["month"] is None, r["month"] or 0))


def highlight(text: str, spans: list[tuple[int, int]]) -> list[tuple[str, bool]]:
    """``text`` cut into (piece, highlighted) runs, overlapping spans merged."""
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    out, pos = [], 0
    for a, b in merged:
        if a > pos:
            out.append((text[pos:a], False))
        out.append((text[a:b], True))
        pos = b
    if pos < len(text):
        out.append((text[pos:], False))
    return out


def facts_line(all_facts: list[dict], fields=("histologic_type", "grade", "size", "pT", "pN",
                                              "er", "pr", "her2", "her2_ihc", "ki67")) -> str:
    """One line of a document's key facts for the tests list ("pT pT2; ER status positive"),
    "" when it states none of them."""
    first = {}
    for f in all_facts:
        first.setdefault(f["field"], f["value"])
    return "; ".join(f"{FIELDS[k]} {first[k]}" for k in fields if k in first)


# ------------------------------------------- the workbench contract (docs/WORKBENCHES.md §1)

KEY_FIELDS = {"er", "pr", "hr", "her2", "her2_ihc", "her2_ish", "stage", "pT", "pN", "grade",
              "histologic_type", "margins", "lvi"}  # a conflict here may change care
RECEPTORS = (("er", "ER"), ("pr", "PR"), ("hr", "Hormone receptors"), ("her2", "HER2"))


@lru_cache(maxsize=1)
def validation() -> dict[str, dict]:
    """Field -> the rules' measured precision and recall on the held-out TCGA reports
    (``app/documents/validation.json``); {} when absent."""
    path = DOCS_DIR / "validation.json"
    if not path.exists():
        return {}
    return {r["field"]: r
            for r in json.loads(path.read_text(encoding="utf-8"))["sets"]["test"]["fields"]}


def measured(fields) -> str:
    """"rules v2, measured on held-out TCGA reports: ER precision 95%, ..." for ``fields``."""
    v = validation()
    shown = [f"{FIELDS[k]} precision {v[k]['precision']:.0%}" for k in fields if k in v]
    return (f"{RULES_VERSION}; the document's own words, read by rules"
            + (" measured on held-out TCGA reports: " + ", ".join(shown) if shown else ""))


def first_facts(pf, version: int | None = None) -> dict[str, dict]:
    """Each field's first documented fact in the file's documents as of report version
    ``version``, in document order: {field: fact}."""
    first = {}
    for f in facts(file_documents(pf, version)):
        first.setdefault(f["field"], f)
    return first


def doc_opens(pf, version: int | None, doc: str) -> tuple:
    """The test that opens the documents workbench on ``doc``: the document's own test, else
    the file's latest documents test so far (a clinic note opens the synthetic record's
    entries); () when none exists yet."""
    vs = pf.versions[: len(pf.versions) if version is None else version + 1]
    tests = [t for v in vs for t in v.tests if t.workbench == "documents"]
    t = next((t for t in tests if t.details.get("document") == doc), tests[-1] if tests else None)
    return () if t is None else ("Tests", t.kind, t.month, t.name)


def _focus(f: dict) -> dict:
    return {"doc": f["doc"], "sentence": tuple(f["sentence"])}


def summary(pf, version: int | None = None) -> dict:
    """The documented stage and receptor status, type and grade, and the conflicts between
    documents: what the documents say, never derived."""
    docs = file_documents(pf, version)
    if not docs:
        return {"workbench": "documents", "title": "Clinical documents", "cards": [],
                "note": "no document in this file"}
    titles = {d["id"]: d["title"] for d in docs}
    all_facts = facts(docs)
    first = {}
    for f in all_facts:
        first.setdefault(f["field"], f)
    cards = []
    for what, keys in (("Documented stage and receptors", ["stage", "pT", "pN", *dict(RECEPTORS)]),
                       ("Documented type and grade", ["histologic_type", "grade", "size"])):
        shown = [first[k] for k in keys if k in first]
        if not shown:
            continue
        bits = []
        for f in shown:
            name = dict(RECEPTORS).get(f["field"], f["label"])
            extra = [f"{x} {first[k]['value']}" for k, x in (("her2_ihc", "IHC"),
                                                             ("her2_ish", "ISH"))
                     if f["field"] == "her2" and k in first]
            bits.append((f["value"] if f["field"] in ("stage", "pT", "pN") else
                         f"{name} {f['value']}") + (f" ({', '.join(extra)})" if extra else ""))
        if what.startswith("Documented stage"):
            bits += [f"{x} not documented" for k, x in RECEPTORS[:2] + RECEPTORS[3:]
                     if k not in first and not (k in ("er", "pr") and "hr" in first)]
        cards.append(card(
            what, "; ".join(bits), f"{OBSERVED} (documented)",
            ", ".join(dict.fromkeys(titles[f["doc"]] for f in shown)),
            measured([f["field"] for f in shown]), "none: what the document states",
            "moderate", doc_opens(pf, version, shown[0]["doc"]), _focus(shown[0])))
    found = conflicts(all_facts)
    if found:
        cards.append(card(
            "Conflicts between documents", "; ".join(
                f"{c['label']}: " + " vs ".join(v["value"] for v in c["values"]) for c in found),
            f"{OBSERVED} (documented)", ", ".join(titles[d] for d in dict.fromkeys(
                d for c in found for v in c["values"] for d in v["docs"])),
            measured([c["field"] for c in found]), "none: kept side by side, no vote",
            "moderate", doc_opens(pf, version, found[0]["values"][0]["docs"][0]),
            _conflict_focus(all_facts, found[0])))
    return {"workbench": "documents", "title": "Clinical documents", "cards": cards,
            "note": None if cards else "the documents state no stage, receptor, type or grade"}


def _conflict_focus(all_facts: list[dict], c: dict) -> dict:
    doc = c["values"][0]["docs"][0]
    f = next(f for f in all_facts if f["field"] == c["field"] and f["doc"] == doc)
    return _focus(f)


def queue(pf, version: int | None = None) -> list[dict]:
    """Fields two documents give different values for (D1…Dn): consequence 2 for receptors,
    stage, TNM, type, grade, margins and lymphovascular invasion, 1 otherwise; trust moderate
    (rules: the sentences need reading)."""
    docs = file_documents(pf, version)
    titles = {d["id"]: d["title"] for d in docs}
    all_facts, out = facts(docs), []
    for n, c in enumerate(conflicts(all_facts), 1):
        sides = " vs ".join(f"{v['value']} ({', '.join(titles[d] for d in v['docs'])})"
                            for v in c["values"])
        out.append(look(
            f"D{n}", f"{c['label']}: documents disagree", f"{sides}; kept side by side, no vote",
            f"{OBSERVED} (documented)", "moderate", 2 if c["field"] in KEY_FIELDS else 1,
            doc_opens(pf, version, c["values"][0]["docs"][0]),
            source=", ".join(titles[d] for v in c["values"] for d in v["docs"]),
            key=finding_key(pf, "document", "conflict", c["label"]),
            focus=_conflict_focus(all_facts, c), threshold=measured([c["field"]])))
    return out

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

import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path

from muffle.memo import per_file
from muffle.report.case_tools import INFERENCE, OBSERVED
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
            for p in sorted(folder.glob("TCGA-*.json")) if not p.name.endswith(".ner.json")}


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


def layers(text: str, spans: list[tuple[int, int, str]]) -> list[tuple[str, tuple[str, ...]]]:
    """``text`` cut into (piece, tags) runs for spans that may overlap: each piece carries the
    tags of every span covering it, in span order ("rules", or a model span's own tag), () for
    plain text. Two highlight layers drawn together without merging one into the other."""
    cuts = sorted({0, len(text), *(max(0, min(p, len(text))) for a, b, _ in spans for p in (a, b))})
    out = []
    for a, b in zip(cuts, cuts[1:], strict=False):
        tags = tuple(dict.fromkeys(t for s, e, t in spans if s <= a and b <= e))
        if out and out[-1][1] == tags:
            out[-1] = (out[-1][0] + text[a:b], tags)
        else:
            out.append((text[a:b], tags))
    return out


# --------------------------------------------- comparable values (the measurement, agreement)

def _first_fact(facts: list[dict], field: str) -> dict | None:
    return next((f for f in facts if f["field"] == field), None)


def comparable(facts: list[dict]) -> dict[str, tuple]:
    """One value per measured field from a document's (or a report set's) facts, on TCGA's
    scales, with the fact it comes from: {field: (value, fact)}; the first place the text states
    it. HER2 for this comparison only: the ISH result if stated, else the status word, else the
    IHC score read by the ASCO/CAP bands (0 and 1+ negative, 2+ equivocal, 3+ positive); pT, pN
    and stage by category (T2, N1, II); node counts: the total stated, else the sum of each
    specimen's counts. Used by the measurement (``scripts/prepare_documents.py``) and to set the
    rules' reading beside the model's. The workbench shows every fact as written and never
    derives a status or a total from it."""
    out = {}
    for k in ("er", "pr", "histologic_type", "margins", "grade", "lvi", "ki67", "laterality"):
        f = _first_fact(facts, k)
        if f:
            out[k] = (f["value"], f)
    for k, scale in (("her2_ish", {"amplified": "positive", "not amplified": "negative"}),
                     ("her2", None), ("her2_ihc", {"0": "negative", "1+": "negative",
                                                   "0 or 1+": "negative", "2+": "equivocal",
                                                   "3+": "positive"})):
        f = _first_fact(facts, k)
        v = f and (f["value"] if scale is None else scale.get(f["value"]))
        if v:
            out["her2"] = (v, f)
            break
    for k, rx, sub in (("pT", r"^y?pT(is|[0-4X]).*", r"T\1"), ("pN", r"^pN([0-3X]).*", r"N\1"),
                       ("stage", r"^Stage (IV|I{1,3}|0).*", r"\1")):
        f = _first_fact(facts, k)
        if f:
            out[k] = (re.sub(rx, sub, f["value"]), f)
    for k in ("nodes_examined", "nodes_positive"):
        total = next((f for f in facts if f["field"] == k
                      and f["rule"] in ("nodes label", "nodes status")), None)
        parts = [f for f in facts if f["field"] == k and f["rule"] in ("nodes k/n", "model")]
        if total:
            out[k] = (int(total["value"]), total)
        elif parts:
            out[k] = (sum(int(f["value"]) for f in parts), parts[0])
    return out


def measurement_half(barcode: str) -> str:
    """The measurement's split of TCGA-BRCA patients by a hash of the barcode: the rules were
    written on "dev" and are reported on "test" (the held-out half); the model too."""
    return "dev" if int(hashlib.sha1(barcode.encode()).hexdigest(), 16) % 2 == 0 else "test"


# ------------------------------------------------------------- the model's reading (NER spans)

NER_MODEL = "OpenMed/OpenMed-ZeroShot-NER-Oncology-Base-220M"
NER_LICENSE = "Apache-2.0"
NER_THRESHOLD = 0.5  # the model card's example threshold, not tuned on these reports
NER_LABELS = {  # the label the model is given (zero-shot) -> the field it stands for
    "histologic type": "histologic_type", "histologic grade": "grade", "tumor size": "size",
    "margin status": "margins", "lymphovascular invasion": "lvi",
    "lymph node status": "nodes", "estrogen receptor status": "er",
    "progesterone receptor status": "pr", "HER2 status": "her2", "Ki-67 index": "ki67",
    "laterality": "laterality", "specimen type": "specimen", "pathologic T stage": "pT",
    "pathologic N stage": "pN", "stage group": "stage", "treatment": "drug",
}
NER_METHOD = (f"{NER_MODEL} ({NER_LICENSE}), zero-shot named-entity model run offline on a "
              f"local machine with {len(NER_LABELS)} breast pathology labels, spans kept at a "
              f"score of {NER_THRESHOLD} or more (the model card's example threshold)")
_NER_POL = re.compile(r"\b(positive|negative|pos|neg|equivocal|borderline)\b", re.I)
_NER_T = re.compile(r"(?<![A-Za-z])(?:y?p)?T\s?(is|[0-4xX])(mi|[a-d])?(?![A-Za-z0-9])")
_NER_N = re.compile(r"(?<![A-Za-z])(?:y?p)?N\s?([0-3oOxX])(mi|[a-c])?(?![A-Za-z0-9])")
_NER_STAGE = re.compile(r"\bstage\s*(?:group\s*)?[:=]?\s*(IV|I{1,3}|[1-4])([ABC])?\b", re.I)
_NER_GRADE = re.compile(r"\bgrade\s*[:=]?\s*(III|II|I|[1-3])\b|\b(well|moderately|poorly)[\s-]+"
                        r"differentiated", re.I)
_NER_MARGIN = re.compile(r"\b(negative|positive|close|free|clear|uninvolved|involved)\b", re.I)
_NER_LVI = re.compile(r"\b(not\s+identified|not\s+seen|absent|negative|present|identified|"
                      r"positive)\b", re.I)


def ner_values(field: str, span: str) -> list[tuple[str, str]]:
    """The (field, value) pairs written inside a span the model marked as ``field``: the words
    it covers, read on the same scales as the rules (a span "HER2 2+" gives the HER2 IHC score
    2+; "ER" alone gives nothing, a mention without a result). Nothing outside the span is read,
    so this is the model's reading, not the rules'."""
    if field in ("er", "pr", "her2"):  # a sign counts only right after the receptor's name
        out = []
        p = (_NER_POL.search(span)
             or re.search(rf"(?:{_RECEPTOR[field]})\s*:?\s*([+-])(?!\w)", span, re.I))
        if p:
            v = p.group(1).lower()
            out.append((field, POLARITY.get(v, v)))
        if field == "her2":
            s, i = _IHC.search(span), _ISH.search(span)
            if s:
                out.append(("her2_ihc", _ihc(s)))
            if i:
                v = (i.group(1) or i.group(2)).lower()
                out.append(("her2_ish", "amplified" if v in ("amplified", "positive")
                            else "not amplified"))
            if p and _two_answers(out[0][1], s, i):
                out.pop(0)
        return out
    if field == "pT":
        m = _NER_T.search(span)
        return [("pT", f"pT{m.group(1).upper() if m.group(1) in 'xX' else m.group(1)}"
                 f"{m.group(2) or ''}")] if m else []
    if field == "pN":
        m = _NER_N.search(span)
        return [("pN", f"pN{m.group(1).upper().replace('O', '0')}{m.group(2) or ''}")] if m else []
    if field == "stage":
        m = _NER_STAGE.search(span)
        if not m:
            return []
        g = {"1": "I", "2": "II", "3": "III", "4": "IV"}.get(m.group(1).upper(), m.group(1).upper())
        return [("stage", f"Stage {g}{(m.group(2) or '').upper()}")]
    if field == "histologic_type":
        m = _TYPE.search(span)
        if not m:
            return []
        word = re.sub(r"\s+", " ", (m.group(2) or m.group(3) or m.group(4) or "").lower())
        return [("histologic_type", _TYPE_NAMES.get(word, f"{word} carcinoma"))]
    if field == "grade":
        m = _NER_GRADE.search(span)
        return [("grade", _DIFF.get((m.group(2) or "").lower()) or _ROMAN.get(
            (m.group(1) or "").upper(), m.group(1)))] if m else []
    if field == "size":
        m = re.search(_N + r"\s*(?:x\s*\d+(?:\.\d+)?\s*){0,2}(cm|mm)\b", span, re.I)
        return [("size", f"{float(m.group(1)):g} {m.group(2).lower()}")] if m else []
    if field == "margins":
        m = _NER_MARGIN.search(span)
        if not m:
            return []
        v = m.group(1).lower()
        return [("margins", "negative" if v in ("free", "clear", "uninvolved") else
                 "positive" if v == "involved" else v)]
    if field == "lvi":
        m = _NER_LVI.search(span)
        return [("lvi", _LVI_VALUE[re.sub(r"\s+", " ", m.group(1).lower())])] if m else []
    if field == "nodes":
        m = re.search(r"\b(\d{1,3})\s*(?:/|of)\s*(\d{1,3})\b", span)
        if m and int(m.group(1)) <= int(m.group(2)):
            return [("nodes_positive", m.group(1)), ("nodes_examined", m.group(2))]
        return []
    if field == "ki67":
        m = _PCT.search(span)
        return [("ki67", f"{float(m.group(1)):g}%")] if m else []
    if field == "laterality":
        m = re.search(r"\b(left|right|bilateral)\b", span, re.I)
        return [("laterality", m.group(1).lower())] if m else []
    if field == "specimen":
        m = _SPECIMEN.search(span)
        return [("specimen", re.sub(r"\s+", " ", m.group(1).lower()))] if m else []
    if field == "drug":
        return [("drug", m.group(1).lower()) for m in _DRUG.finditer(span)]
    return []


def ner_facts(text: str, spans: list[dict], doc: str = "") -> list[dict]:
    """The model's spans as findings of ``text``, labeled model inference: {"doc", "field",
    "label" (the field's name), "value" (None for a mention without a result), "start", "end",
    "sentence", "quote", "span" (the characters marked), "model_label", "score", "status",
    "rule": "model"}. One finding per value inside a span, else one mention."""
    sents, out = sentences(text), []
    for sp in sorted(spans, key=lambda s: (s["start"], s["end"])):
        a, b = sp["start"], sp["end"]
        field = NER_LABELS.get(sp["label"])
        if field is None or not 0 <= a < b <= len(text):
            continue
        s, e = _sentence(sents, a, b)
        base = {"doc": doc, "start": a, "end": b, "sentence": (s, e),
                "quote": text[s:e].strip(), "span": text[a:b], "model_label": sp["label"],
                "score": float(sp["score"]), "status": INFERENCE, "rule": "model"}
        got = ner_values(field, text[a:b])
        for k, v in got or [(field, None)]:
            out.append({**base, "field": k, "value": v,
                        "label": FIELDS.get(k, "Lymph nodes" if k == "nodes" else k)})
    return out


@lru_cache(maxsize=4)
def _ner(folder: Path) -> dict[str, dict]:
    """Document id -> {"spans", "run"} from every ``<barcode>.ner.json``, read once per process."""
    out = {}
    for p in sorted(folder.glob("TCGA-*.ner.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        for doc, spans in d["documents"].items():
            out[doc] = {"spans": spans, "run": d["run"], "threshold": d["threshold"]}
    return out


def doc_spans(doc: str, folder: Path = DOCS_DIR) -> list[dict] | None:
    """The model's precomputed spans for document ``doc``; None when the model has not read it
    (an imported document: queued for the local pipeline)."""
    got = _ner(folder).get(doc)
    return None if got is None else got["spans"]


def model_facts(docs: list[dict], folder: Path = DOCS_DIR) -> list[dict]:
    """The model's findings in the file's documents (those it has read), documents in order."""
    return [f for d in docs if (sp := doc_spans(d["id"], folder)) is not None
            for f in ner_facts(d["text"], sp, d["id"])]


def legend_spans(text: str) -> list[tuple[int, int]]:
    """Where the rules see a HER2 scoring legend (not a result) in ``text``."""
    return [m.span() for m in _LEGEND.finditer(text)
            if not m["list"] or len({c.lower() for c in re.findall(_CAT, m["list"], re.I)}) > 1]


COMPARED = ("er", "pr", "her2", "pT", "pN", "stage", "histologic_type", "grade", "margins",
            "lvi", "nodes_examined", "nodes_positive", "ki67", "laterality")
DISAGREE_QUEUE = {"er", "pr", "her2", "pT", "pN", "stage"}  # a receptor or stage field


def _sentence_no(text: str, at: int) -> int:
    return next((n for n, (s, e) in enumerate(sentences(text), 1) if s <= at < e), 0)


def agreement(text: str, rules: list[dict], model: list[dict]) -> list[dict]:
    """The rules' reading beside the model's in one document, per compared field (both read on
    the measurement's scales, ``comparable``): {"field", "label", "kind": agree / disagree /
    model only / rules only, "rules", "model" (the value), "rule_fact", "model_fact", "line"},
    the line in words ("the rules read HER2 status negative at sentence 12; the model marked
    'HER2 2+' (0.71) at sentence 14, which the rules took for a legend")."""
    r, m = comparable(rules), comparable([f for f in model if f["value"] is not None])
    legend = legend_spans(text)
    out = []
    for k in COMPARED:
        if k not in r and k not in m:
            continue
        rv, rf = r.get(k, (None, None))
        mv, mf = m.get(k, (None, None))
        kind = ("rules only" if mv is None else "model only" if rv is None else
                "agree" if rv == mv else "disagree")
        bits = []
        if rf:
            bits.append(f"the rules read {rf['label']} {rf['value']} at sentence "
                        f"{_sentence_no(text, rf['start'])}")
        if mf:
            where = (", which the rules took for a legend"
                     if any(a <= mf["start"] < b for a, b in legend)
                     else ", where the rules read no result" if rv is None else "")
            bits.append(f"the model marked '{mf['span'].strip()[:60]}' as {mf['model_label']} "
                        f"({mf['score']:.2f}) at sentence {_sentence_no(text, mf['start'])}"
                        + where)
        if kind == "rules only":
            bits.append("the model marked no result for it")
        out.append({"field": k, "label": FIELDS.get(k, k), "kind": kind, "rules": rv,
                    "model": mv, "rule_fact": rf, "model_fact": mf,
                    "line": "; ".join(bits)})
    return out


def file_agreement(docs: list[dict], folder: Path = DOCS_DIR) -> list[dict]:
    """``agreement`` for each document of the file the model has read: rows with their "doc"."""
    out = []
    for d in docs:
        sp = doc_spans(d["id"], folder)
        if sp is None:
            continue
        for row in agreement(d["text"], extract(d["text"], d["id"]),
                             ner_facts(d["text"], sp, d["id"])):
            out.append({"doc": d["id"], **row})
    return out


NER_FAILURES = [  # seen on the bundled and held-out reports (docs/documents.md)
    "It marks where a field is named, rarely its result: \"ESTROGEN\", \"MARGINS\", \"LYMPH "
    "NODES\" without positive, negative or a count, so most of its spans are mentions.",
    "It confuses labels: \"HER2\", \"PROGESTERONE\" and \"E-cadherin\" marked as estrogen "
    "receptor status; section headers (\"TUMOR\", \"NOTTINGHAM\") as a stage or a size.",
    "It was fine-tuned on research abstracts (BioNLP 2013 Cancer Genetics), not pathology "
    "reports, and runs zero-shot on our labels with the card's threshold, untuned.",
    "OCR noise (\"giade\", \"IUMUR\") and upper-case synoptic forms lower its scores.",
]
RULE_GROUP = {  # field -> its rule in RULES
    **dict.fromkeys(("histologic_type",), "Histologic type"),
    **dict.fromkeys(("grade", "nottingham_score", "tubules", "pleomorphism", "mitoses"),
                    "Nottingham grade and score"),
    "size": "Tumor size", "margins": "Margins", "margin_distance": "Margins",
    "lvi": "Lymphovascular invasion", "nodes_examined": "Lymph nodes",
    "nodes_positive": "Lymph nodes",
    **dict.fromkeys(("pT", "pN", "stage"), "pT, pN, stage"),
    **dict.fromkeys(("er", "pr", "hr", "er_percent", "pr_percent", "er_allred", "pr_allred"),
                    "ER, PR, hormone receptors"),
    **dict.fromkeys(("her2", "her2_ihc", "her2_ish", "her2_ratio"), "HER2"),
    "ki67": "Ki-67", "laterality": "Laterality, specimen", "specimen": "Laterality, specimen",
    **dict.fromkeys(("drug", "ecog", "date"), "Drugs, ECOG, dates"),
}


def search_findings(findings: list[dict], query: str) -> list[dict]:
    """The rules' facts and the model's spans whose field, value or marked characters hold every
    word of ``query`` (or a synonym): "HER2", "margin", "node positive". In finding order."""
    words = [w for w in re.findall(r"[\w+%./-]+", query.lower()) if w not in STOP]
    if not words:
        return []
    alts = [[_word(w), *(_word(s) for s in SYNONYMS.get(w, []))] for w in words]
    return [f for f in findings
            if all(any(p.search(" ".join(str(x) for x in (
                f["label"], f.get("value") or "", f.get("span", ""), f.get("model_label", ""))))
                for p in group) for group in alts)]


# the TCGA clinical field each measured fact was compared with (scripts/prepare_documents.py)
MEASURED_AS = {"her2_ihc": "her2", "her2_ish": "her2"}
TCGA_FIELD = {
    "er": "breast_carcinoma_estrogen_receptor_status",
    "pr": "breast_carcinoma_progesterone_receptor_status",
    "her2": "lab_procedure_her2_neu_in_situ_hybrid_outcome_type, else "
            "lab_proc_her2_neu_immunohistochemistry_receptor_status",
    "pT": "pathologic_T", "pN": "pathologic_N", "stage": "pathologic_stage",
    "histologic_type": "histological_type", "margins": "margin_status",
    "nodes_examined": "lymph_node_examined_count",
    "nodes_positive": "number_of_lymphnodes_positive_by_he",
}


def measured_against(field: str) -> dict | None:
    """What a fact's field was measured against: {"tcga_field", "rules": row, "model": row}
    (rows of validation.json's held-out half, None where absent); None for a field not
    measured."""
    k = MEASURED_AS.get(field, field)
    if k not in TCGA_FIELD:
        return None
    return {"field": k, "tcga_field": TCGA_FIELD[k], "rules": validation().get(k),
            "model": model_validation().get(k)}


# ------------------------------------------------------------- the documents over time

CHANGES = {"er": "receptor", "pr": "receptor", "hr": "receptor", "her2": "receptor",
           "her2_ihc": "receptor", "her2_ish": "receptor", "stage": "stage", "pT": "stage",
           "pN": "stage", "grade": "grade", "histologic_type": "type"}


def history(docs: list[dict], all_facts: list[dict]) -> list[dict]:
    """The dated documents (a month: the record, an import) in order with the receptor, stage,
    grade and type facts each states: [{"doc", "title", "month", "facts": {field: fact}}]. A
    document without a month (a de-identified TCGA report) is not on the axis."""
    dated = sorted((d for d in docs if d["month"] is not None), key=lambda d: d["month"])
    out = []
    for d in dated:
        own = {}
        for f in all_facts:
            if f["doc"] == d["id"] and f["field"] in CHANGES:
                own.setdefault(f["field"], f)
        out.append({"doc": d["id"], "title": d["title"], "month": d["month"], "facts": own})
    return out


def changes(docs: list[dict], all_facts: list[dict]) -> list[dict]:
    """Status changes across dated documents: a field whose value in a document differs from
    the last earlier document that stated it ("ER status positive at month -40, negative at
    month 13": a receptor that flips, a stage restaged). Documented on both sides; neither is
    taken as the current one."""
    last, out = {}, []
    for row in history(docs, all_facts):
        for k, f in row["facts"].items():
            prev = last.get(k)
            if prev and prev[1]["value"] != f["value"]:
                out.append({"field": k, "label": FIELDS[k], "kind": CHANGES[k],
                            "from": prev[1]["value"], "to": f["value"],
                            "from_month": prev[0]["month"], "to_month": row["month"],
                            "from_doc": prev[0]["doc"], "to_doc": row["doc"],
                            "from_fact": prev[1], "to_fact": f})
            last[k] = (row, f)
    return out


def resolution(review: dict | None) -> str:
    """A conflict's state from its review mark: settled only by the clinician's mark (and the
    value they chose stands, when they chose one), never by the system."""
    if not review:
        return "open: only your mark settles it"
    chose = f", {review['stands']} stands" if review.get("stands") else ""
    return f"marked {review['mark']} by {review.get('by') or 'no initials'}{chose}"


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


@lru_cache(maxsize=1)
def model_validation() -> dict[str, dict]:
    """Field -> the model's measured precision and recall on the same held-out reports; {}
    when absent."""
    path = DOCS_DIR / "validation.json"
    if not path.exists():
        return {}
    model = json.loads(path.read_text(encoding="utf-8")).get("model")
    return {r["field"]: r for r in model["sets"]["test"]["fields"]} if model else {}


def model_measured(fields) -> str:
    """The model's method and its measured precision for ``fields``."""
    v = model_validation()
    shown = [f"{FIELDS.get(k, k)} precision {v[k]['precision']:.0%}" for k in fields
             if k in v and v[k]["precision"] is not None]
    return NER_METHOD + ("; measured on held-out TCGA reports: " + ", ".join(shown)
                         if shown else "")


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


@per_file
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
    rows = file_agreement(docs)
    if rows:
        n = {k: [r for r in rows if r["kind"] == k] for k in ("agree", "disagree", "model only",
                                                             "rules only")}
        off = n["disagree"] or n["model only"]
        cards.append(card(
            "The model's reading beside the rules'",
            f"{len(n['agree'])} field reading(s) agree, {len(n['disagree'])} disagree"
            + (" (" + ", ".join(dict.fromkeys(r["label"] for r in n["disagree"])) + ")"
               if n["disagree"] else "")
            + f", {len(n['model only'])} read by the model only, {len(n['rules only'])} by the "
            "rules only", INFERENCE, ", ".join(dict.fromkeys(titles[r["doc"]] for r in rows)),
            model_measured(dict.fromkeys(r["field"] for r in rows)),
            f"score {NER_THRESHOLD} or more: the model card's example threshold, not tuned on "
            "these reports", "weak",
            doc_opens(pf, version, (off or rows)[0]["doc"]),
            _focus((off or rows)[0]["model_fact"] or (off or rows)[0]["rule_fact"])))
    return {"workbench": "documents", "title": "Clinical documents", "cards": cards,
            "note": None if cards else "the documents state no stage, receptor, type or grade"}


def _conflict_focus(all_facts: list[dict], c: dict) -> dict:
    doc = c["values"][0]["docs"][0]
    f = next(f for f in all_facts if f["field"] == c["field"] and f["doc"] == doc)
    return _focus(f)


@per_file
def queue(pf, version: int | None = None) -> list[dict]:
    """Fields two documents give different values for (D1…Dn): consequence 2 for receptors,
    stage, TNM, type, grade, margins and lymphovascular invasion, 1 otherwise; trust moderate
    (rules: the sentences need reading); a value that changed between dated documents says
    so. Then "models disagree" (M1…Mn): a receptor or stage field the rules and the model read
    differently in one document, consequence 2, trust weak."""
    docs = file_documents(pf, version)
    titles = {d["id"]: d["title"] for d in docs}
    all_facts, out = facts(docs), []
    over_time = {}
    for ch in changes(docs, all_facts):
        over_time.setdefault(ch["field"], []).append(
            f"{ch['from']} at month {ch['from_month']}, {ch['to']} at month {ch['to_month']}")
    for n, c in enumerate(conflicts(all_facts), 1):
        sides = " vs ".join(f"{v['value']} ({', '.join(titles[d] for d in v['docs'])})"
                            for v in c["values"])
        when = ("; over time: " + "; ".join(over_time[c["field"]])
                if c["field"] in over_time else "")
        out.append(look(
            f"D{n}", f"{c['label']}: documents disagree",
            f"{sides}{when}; kept side by side, no vote: only the clinician's mark settles it",
            f"{OBSERVED} (documented)", "moderate", 2 if c["field"] in KEY_FIELDS else 1,
            doc_opens(pf, version, c["values"][0]["docs"][0]),
            source=", ".join(titles[d] for v in c["values"] for d in v["docs"]),
            key=finding_key(pf, "document", "conflict", c["label"]),
            focus=_conflict_focus(all_facts, c), threshold=measured([c["field"]])))
    m = 0
    for r in file_agreement(docs):
        if r["kind"] != "disagree" or r["field"] not in DISAGREE_QUEUE:
            continue
        m += 1
        out.append(look(
            f"M{m}", f"{r['label']}: the rules and the model disagree",
            f"{titles[r['doc']]}: {r['line']}. The rules' reading is the document's words; the "
            "model's is a zero-shot named-entity model's, weaker on these reports (Methods and "
            "validation): re-read the sentences", f"{OBSERVED} (documented, rules) vs "
            f"{INFERENCE} (named-entity model)", "weak", 2, doc_opens(pf, version, r["doc"]),
            source=titles[r["doc"]],
            key=finding_key(pf, "document", "models disagree", r["doc"], r["label"]),
            focus=_focus(r["rule_fact"]),
            threshold=f"{measured([r['field']])}; {model_measured([r['field']])}"))
    return out

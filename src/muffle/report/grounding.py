"""Check that a case note only states what the agent's tools returned.

No LLM involved: the note is scanned for numbers, gene/feature names and URLs, and each one must
trace back to the tool outputs (the evidence the writer was given). Whatever doesn't is returned
as an issue, so the demo can flag it and the writer can be asked once to fix it.

- **numbers**: every decimal, percentage, ordinal ("81st") and integer >= 10 must equal a number
  in the evidence at the precision the note shows (0.69 matches 0.693; 81st matches 81.3). Signs
  are ignored ("lowers risk by 0.12" quotes -0.12) and 69% may quote 0.69. Small integers
  ("3 layers") are structural and skipped.
- **genes**: a cohort feature name (exact case) that no tool returned, or a gene-like symbol with
  a digit (TP53, BRCA1) that isn't in the evidence. TNM codes (T2N0, M0) and HER2 are
  allowed. A hyphen typed as U+2010 or U+2011 (writers often send IGKV4‑1) counts as "-".
- **URLs**: must be one of the URLs returned by search_literature.
"""

from __future__ import annotations

import re

NUMBER = re.compile(r"(?<![\w.,])[-+−]?((?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?)(st|nd|rd|th|%)?")
TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.\-]*[A-Za-z0-9]|[A-Za-z0-9]")
GENE_LIKE = re.compile(r"[A-Z][A-Z0-9\-]*\d[A-Z0-9\-]*")
ALLOWED = re.compile(r"HER2|(?:[TNM](?:[0-4]|X|is)[a-d]?)+")  # HER2, T2N0M0, T1c, NX
URL = re.compile(r"https?://[^\s)\]>\"'`]+")
HYPHENS = str.maketrans("‐‑", "--")


def _numbers_in(obj) -> list[float]:
    """Every number in a JSON-able object, including numbers written inside strings."""
    out = []
    if isinstance(obj, bool):
        return out
    if isinstance(obj, (int, float)):
        out.append(float(obj))
    elif isinstance(obj, str):
        out += [float(m.group(1).replace(",", "")) for m in NUMBER.finditer(obj)]
    elif isinstance(obj, dict):
        for v in obj.values():
            out += _numbers_in(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out += _numbers_in(v)
    return out


def _strings_in(obj) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for k, v in obj.items() for s in [k, *_strings_in(v)]]
    if isinstance(obj, (list, tuple)):
        return [s for v in obj for s in _strings_in(v)]
    return []


def _matches(value: float, decimals: int, percent: bool, known: list[float]) -> bool:
    tol = 0.5 * 10 ** -decimals + 1e-9
    candidates = [abs(k) for k in known] + ([abs(k) * 100 for k in known] if percent else [])
    return any(abs(value - k) <= tol for k in candidates)


def check_note(text: str, evidence,
               feature_names: dict[str, list[str]] | None = None) -> list[dict]:
    """Issues in ``text`` (the note) that aren't backed by ``evidence`` (case header + tool calls
    and results, any JSON-able object). Each issue: {"kind": number|gene|url, "text": ...}."""
    known_numbers = _numbers_in(evidence)
    text = text.translate(HYPHENS)
    strings = [s.translate(HYPHENS) for s in _strings_in(evidence)]
    evidence_tokens = {t for s in strings for t in TOKEN.findall(s)}
    vocab = {n for m, names in (feature_names or {}).items() if m != "clinical" for n in names}
    urls = {u.rstrip("/") for s in strings for u in URL.findall(s)}

    issues, seen = [], set()

    def flag(kind: str, s: str):
        if (kind, s) not in seen:
            seen.add((kind, s))
            issues.append({"kind": kind, "text": s})

    for u in URL.findall(text):
        u = u.rstrip(".,;:")
        if u.rstrip("/") not in urls:
            flag("url", u)
    prose = URL.sub(" ", text)

    for m in NUMBER.finditer(prose):
        digits, suffix = m.group(1).replace(",", ""), m.group(2)
        decimals = len(digits.split(".")[1]) if "." in digits else 0
        value = float(digits)
        if not decimals and not suffix and value < 10:
            continue
        if not _matches(value, decimals, suffix == "%", known_numbers):
            flag("number", m.group(0).lstrip("+"))

    for tok in TOKEN.findall(prose):
        if tok in evidence_tokens:
            continue
        # "ESR1-driven": check the hyphen parts too (names like RNU6-607P matched whole above)
        for part in [tok, *(tok.split("-") if "-" in tok else [])]:
            if part not in evidence_tokens and (
                    part in vocab or (GENE_LIKE.fullmatch(part) and not ALLOWED.fullmatch(part))):
                flag("gene", part)
    return issues


def describe(issues: list[dict]) -> str:
    """One line for the UI / the revision prompt."""
    by_kind = {}
    for i in issues:
        by_kind.setdefault(i["kind"], []).append(i["text"])
    names = {"number": "numbers", "gene": "genes/features", "url": "links"}
    return "; ".join(f"{names[k]}: {', '.join(v)}" for k, v in by_kind.items())


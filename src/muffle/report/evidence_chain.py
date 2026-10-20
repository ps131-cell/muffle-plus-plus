"""Evidence chain: every sentence of a case note linked to the tool output behind it
(docs/WORKBENCHES.md §2).

No LLM involved. Each sentence or bullet of a ``CaseReport`` gets its evidence type from the
writer's tag ([Observed] / [Model inference] / [Hypothesis]), a link from every number, gene or
feature name and URL to the tool call whose result contains it, and the list of what no tool
returned. That last list is ``grounding.check_note`` run on the sentence, so it agrees with the
check the agent already runs on the whole note.

The grounding check also sees the case header (the model's validation C-index lives there, not
in any tool result); a saved note does not keep it, so pass it as ``header`` when you have it.
"""

from __future__ import annotations

import re

from muffle.report.grounding import (ALLOWED, GENE_LIKE, HYPHENS, NUMBER, TOKEN, URL,
                                     _matches, _numbers_in, check_note)
from muffle.report.nemotron import WRITER_DROPS, CaseReport

TAG = re.compile(r"^\s*(?:[-*•]\s*)?\[(Observed|Model inference|Hypothesis)\]\s*", re.I)
BULLET = re.compile(r"^\s*[-*•]\s+")
HEADING = re.compile(r"^\s*(#+\s|\*\*[^*]+\*\*\s*$)")
SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z(\[])")


def _leaves(obj, path: str = "") -> list[tuple[str, object]]:
    """(key path, value) for every scalar in a JSON-able object: 'features[0].name'."""
    if isinstance(obj, dict):
        return [p for k, v in obj.items() for p in _leaves(v, f"{path}.{k}" if path else k)]
    if isinstance(obj, (list, tuple)):
        return [p for i, v in enumerate(obj) for p in _leaves(v, f"{path}[{i}]")]
    return [(path, obj)]


def sentences(text: str) -> list[tuple[str, str | None]]:
    """(sentence, evidence type) per bullet or sentence of the note; headings are skipped and a
    bullet stays one item however many sentences it holds."""
    out = []
    for line in text.splitlines():
        line = line.strip()
        if not line or HEADING.match(line):
            continue
        m = TAG.match(line)
        kind = m.group(1).lower() if m else None
        body = line[m.end():] if m else BULLET.sub("", line)
        if m or BULLET.match(line):
            out.append((body.strip(), kind))
        else:
            out += [(s.strip(), None) for s in SENTENCE.split(body) if s.strip()]
    return out


def _link(item: str, leaves: list[tuple], match) -> dict | None:
    """The first leaf that matches ``item``, strong before weak."""
    best = None
    for call, tool, path, value in leaves:
        trust = match(value)
        if trust == "strong":
            return {"item": item, "tool": tool, "path": path, "value": str(value), "trust": trust,
                    "call": call}
        if trust == "weak" and best is None:
            best = {"item": item, "tool": tool, "path": path, "value": str(value), "trust": trust,
                    "call": call}
    return best


def _put(links: dict, link: dict | None):
    if link and link["item"] not in links:
        links[link["item"]] = link


def note_chain(report: CaseReport, names: dict[str, list[str]] | None = None,
               header: dict | None = None) -> list[dict]:
    """One item per sentence or bullet: its evidence type, the links from its numbers, names and
    URLs into the tool trace (``path`` inside that tool's result; ``call`` indexes
    ``report.trace``, None for the case header), and what no tool returned."""
    results = [(k, c.name, {key: v for key, v in c.result.items() if key not in WRITER_DROPS})
               for k, c in enumerate(report.trace)]
    evidence = {"case": header or {},
                "tool_outputs": [{"tool": name, "arguments": report.trace[k].arguments,
                                  "result": r} for k, name, r in results]}
    leaves = [(None, "case", p, v) for p, v in _leaves(header or {})]
    leaves += [(k, name, p, v) for k, name, r in results for p, v in _leaves(r)]
    str_leaves = [(c, t, p, v.translate(HYPHENS)) for c, t, p, v in leaves if isinstance(v, str)]
    feature_names = {v for _, _, p, v in str_leaves if p.endswith(".name")}
    vocab = {n for ns in (names or {}).values() for n in ns} | feature_names

    def number_match(value: float, decimals: int, percent: bool):
        def match(leaf):
            known = _numbers_in(leaf)
            if any(abs(k) == value or (percent and abs(abs(k) * 100 - value) < 1e-9)
                   for k in known):
                return "strong"
            return "weak" if _matches(value, decimals, percent, known) else None
        return match

    def token_match(tok: str, parts: list[str]):
        def match(leaf):
            found = set(TOKEN.findall(leaf))
            if tok in found:
                return "strong"
            return "weak" if any(p in found for p in parts) else None
        return match

    def url_match(u: str):
        def match(leaf):
            if leaf.rstrip("/") == u:
                return "strong"
            return "weak" if u in leaf else None
        return match

    out = []
    for sentence, kind in sentences(report.text):
        text = sentence.translate(HYPHENS)
        links: dict[str, dict] = {}
        for u in URL.findall(text):
            u = u.rstrip(".,;:").rstrip("/")
            _put(links, _link(u, str_leaves, url_match(u)))
        prose = URL.sub(" ", text)
        for m in NUMBER.finditer(prose):
            digits, suffix = m.group(1).replace(",", ""), m.group(2)
            decimals = len(digits.split(".")[1]) if "." in digits else 0
            value = float(digits)
            if not decimals and not suffix and value < 10:
                continue
            _put(links, _link(m.group(0).lstrip("+"), leaves,
                              number_match(value, decimals, suffix == "%")))
        for tok in TOKEN.findall(prose):
            parts = tok.split("-") if "-" in tok else []
            wanted = [p for p in [tok, *parts]
                      if p in vocab or (GENE_LIKE.fullmatch(p) and not ALLOWED.fullmatch(p))]
            if wanted:
                _put(links, _link(tok, str_leaves, token_match(tok, wanted)))
        out.append({"sentence": sentence, "evidence_type": kind, "links": list(links.values()),
                    "unsupported": [i["text"] for i in check_note(sentence, evidence, names)]})
    return out

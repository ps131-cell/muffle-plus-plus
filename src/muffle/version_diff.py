"""What changed between two report versions of a patient file (docs/WORKSPACE.md, Timeline): the
risk delta with the model's own uncertainty, the findings added, changed or removed with their
evidence labels and where they open, the tests added, the attention queue's changes and the
report summary note's changed sentences.

A delta is the difference between two snapshots of the record (SNAPSHOT): it is not a trend and
forecasts nothing. Pure functions over ``muffle.workspace.PatientFile``: no Streamlit, no model
run, nothing new estimated. The workbench summaries and the attention queue come from ``data(j)``
(the shell's per-version memo, ``{"sums", "queue"}``) or, without it, from ``muffle.overview``.
"""

from __future__ import annotations

import difflib
import re

from muffle import crosstest, overview
from muffle.demo import ordinal
from muffle.report.case_tools import INFERENCE, OBSERVED
from muffle.workspace import PatientFile

SNAPSHOT = ("A delta is the difference between two snapshots of the record, not a trend: "
            "nothing here forecasts what comes next.")
SPREAD = ("the range of the 5 models (the same model trained on five 80% splits, seeds 0–4): a "
          "shift is within it when the two versions' ranges overlap")
# The shift's colour and sign, as the report's risk metric shows a rise (red, as Streamlit's
# "inverse" delta) and a fall (green); a shift the models' own spread covers is gray, so the
# colour never claims more than the models can tell apart. The words always say it too.
SHIFTS = {"up": ("red", "▲", "up"), "down": ("green", "▼", "down"),
          "within": ("gray", "≈", "within the models' spread"),
          "same": ("gray", "=", "unchanged"), "none": ("gray", "·", "not compared")}
STATUS = {"added": "+", "changed": "~", "removed": "−"}
_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(])")


def when(pf: PatientFile, j: int) -> str:
    m = pf.versions[j].month
    return "the tumor sample" if m is None else f"month {m}"


def _data(pf: PatientFile, j: int, data) -> dict:
    if data is not None:
        return data(j)
    queues = overview.queues(pf, j)
    return {"sums": overview.summaries(pf, j),
            "queue": overview.attention(pf, j, queues, crosstest.discrepancies(pf, j))}


def risk_delta(pf: PatientFile, a: int, b: int) -> dict:
    """The risk between versions ``a`` and ``b``: {"kind", "measure", "before", "after", "delta",
    "points", "direction" (up / down / same / None), "uncertainty", "exceeds" (True, False or
    None when the model gives no per-patient uncertainty), "shift" (a key of SHIFTS), "models",
    "text", "why" (each version's attribution in between), "evidence"}. The synthetic patient's
    12-month risk carries the 5-model range (SPREAD); a TCGA estimate is a cohort percentile that
    rests on the tumor sample alone, so imports leave it as it was."""
    va, vb = pf.versions[a], pf.versions[b]
    ra, rb = va.risk or {}, vb.risk or {}
    why = [{"k": k, "version": pf.versions[k].label, "summary": pf.versions[k].summary,
            "changes": list(pf.versions[k].changes)}
           for k in range(a + 1, b + 1) if pf.versions[k].changes]
    out = {"kind": None, "measure": None, "before": None, "after": None, "delta": None,
           "points": None, "direction": None, "uncertainty": None, "exceeds": None,
           "shift": "none", "models": None, "why": why, "evidence": INFERENCE}
    if "value" in ra and "value" in rb:
        d = rb["value"] - ra["value"]
        (alo, ahi), (blo, bhi) = ra["range"], rb["range"]
        exceeds = blo > ahi or bhi < alo  # the two 5-model ranges do not overlap
        direction = "up" if d > 0 else "down" if d < 0 else "same"
        shift = direction if exceeds or direction == "same" else "within"
        models = (ra["landmark"], rb["landmark"])
        text = (f"12-month risk {100 * d:+.0f} points ({ra['value']:.0%} → {rb['value']:.0%}): "
                + ("beyond the 5 models' spread" if exceeds else
                   "within the 5 models' spread, so the models cannot tell the two apart")
                + f" (ranges {alo:.0%}–{ahi:.0%} and {blo:.0%}–{bhi:.0%})"
                + ("" if models[0] == models[1] else
                   f"; the month-{models[1]} model takes over from the month-{models[0]} one"))
        return {**out, "kind": "probability", "measure": "12-month risk", "before": ra["value"],
                "after": rb["value"], "delta": d, "points": 100 * d, "direction": direction,
                "uncertainty": {"before": tuple(ra["range"]), "after": tuple(rb["range"]),
                                "what": SPREAD},
                "exceeds": exceeds, "shift": shift, "models": models, "text": text}
    if "percentile" in ra and "percentile" in rb:
        d = rb["percentile"] - ra["percentile"]
        direction = "up" if d > 0 else "down" if d < 0 else "same"
        text = (f"cohort percentile {ordinal(ra['percentile'])} → {ordinal(rb['percentile'])}"
                if d else f"risk unchanged: {ordinal(rb['percentile'])} percentile of the cohort "
                          f"({rb['group']} risk group); the estimate rests on the tumor sample "
                          "alone, which an import does not change")
        return {**out, "kind": "percentile", "measure": "cohort percentile",
                "before": ra["percentile"], "after": rb["percentile"], "delta": d,
                "points": d, "direction": direction,
                "uncertainty": {"what": "no per-patient interval: the model's C-index is a "
                                        "cohort figure"},
                "shift": "same" if not d else direction, "text": text}
    why_none = ("the risk models are not run on imported results" if vb.imported else
                "the models start at the first tumor sequencing (month 0)")
    last = next(((k, v.risk["value"]) for k, v in reversed(list(enumerate(pf.versions[:b + 1])))
                 if v.risk and "value" in v.risk), None)
    if "value" in rb:
        text = (f"first risk estimate: {rb['value']:.0%} (range of 5 models "
                "{:.0%}–{:.0%})".format(*rb["range"]) + "; nothing earlier to compare it with")
    elif last is not None:
        text = (f"no new risk estimate at {when(pf, b)} ({why_none}); the last estimate, "
                f"{last[1]:.0%}, is from {when(pf, last[0])}")
    else:
        text = f"no risk estimate in either version ({why_none})"
    return {**out, "text": text}


def _record(pf: PatientFile, a: int, b: int) -> list[dict]:
    """The observed record rows (the report's "Characterization and record") that differ."""
    old, new = dict(pf.versions[a].observed), dict(pf.versions[b].observed)
    return [{"status": "added" if old.get(k) is None else "removed" if new.get(k) is None
             else "changed", "where": "Record", "what": k, "before": old.get(k),
             "after": new.get(k), "evidence": OBSERVED, "trust": "strong",
             "opens": ("Report",), "focus": None, "at": a if new.get(k) is None else b}
            for k in dict.fromkeys([*old, *new]) if old.get(k) != new.get(k)]


def _cards(before: dict, after: dict, a: int, b: int) -> list[dict]:
    """The workbench finding cards that differ, each opening where it is (as of ``b``; a card
    gone by ``b`` opens as of ``a``)."""
    out = []
    for name in dict.fromkeys([*before, *after]):
        x_all = {c["what"]: c for c in before.get(name, {}).get("cards", [])}
        y_all = {c["what"]: c for c in after.get(name, {}).get("cards", [])}
        title = (after.get(name) or before[name])["title"]
        for what in dict.fromkeys([*x_all, *y_all]):
            x, y = x_all.get(what), y_all.get(what)
            if x and y and x["text"] == y["text"]:
                continue
            c = y or x
            out.append({"status": "added" if x is None else "removed" if y is None else
                        "changed", "where": title, "what": what, "before": x and x["text"],
                        "after": y and y["text"], "evidence": c["evidence"],
                        "trust": c["trust"], "opens": tuple(c["opens"]), "focus": c["focus"],
                        "at": b if y else a})
    return out


def _same_item(q: dict) -> tuple:
    """What a queue item is about beyond its finding key: its kind and the test it opens, without
    the test's month (the latest CA 15-3 value is the same item at month 19 and at month 24)."""
    opens = tuple(q["opens"]) + (None,) * 4
    return q["label"], opens[0], opens[1], opens[3]


def _queue(before: list[dict], after: list[dict], a: int, b: int) -> list[dict]:
    """The attention queue's items new by ``b``, gone by then, or reworded. Items match by
    finding key; an item re-keyed by a newer specimen with the same words is no change, and a
    lone item gone and a lone one new about the same test are one item reworded."""
    x_all, y_all = {q["key"]: q for q in before}, {q["key"]: q for q in after}
    gone = {k: q for k, q in x_all.items() if k not in y_all}
    new = {k: q for k, q in y_all.items() if k not in x_all}
    for k, q in list(new.items()):  # the same words under a new key: not a change
        twin = next((g for g, x in gone.items() if (x["label"], x["what"]) ==
                     (q["label"], q["what"])), None)
        if twin is not None:
            del new[k], gone[twin]
            x_all.pop(twin), y_all.pop(k)
    for k, q in list(new.items()):  # one gone and one new about the same test: reworded
        twins = [g for g, x in gone.items() if _same_item(x) == _same_item(q)]
        news = [n for n, y in new.items() if _same_item(y) == _same_item(q)]
        if len(twins) == 1 and news == [k]:
            x_all[k] = x_all.pop(twins[0])
            del gone[twins[0]]
    out = []
    for key in dict.fromkeys([*y_all, *x_all]):  # the queue's order at b, then what left it
        x, y = x_all.get(key), y_all.get(key)
        if x and y and x["what"] == y["what"]:
            continue
        q = y or x
        out.append({"status": "added" if x is None else "removed" if y is None else "changed",
                    "what": q["what"], "before": x and x["what"], "kind": q["label"],
                    "sos": q["sos"], "evidence": q["evidence"], "trust": q["trust"],
                    "opens": tuple(q["opens"]), "focus": q["focus"],
                    "pointer": q["pointer"], "key": key, "at": b if y else a})
    return out


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text or "") if s.strip()]


def inline(before: str, after: str, keep: int = 36) -> list[tuple[str, str]]:
    """A word-level diff of two texts as segments ("same" | "del" | "ins", text), for showing
    only what changed inside a long finding; an unchanged run longer than ``2 * keep`` characters
    keeps ``keep`` at each end around "…" (only its end before the first change, its start after
    the last)."""
    x, y = re.findall(r"\S+|\s+", before or ""), re.findall(r"\S+|\s+", after or "")
    ops: list[tuple] = []
    for op in difflib.SequenceMatcher(a=x, b=y, autojunk=False).get_opcodes():
        gap = "".join(x[ops[-1][1]:ops[-1][2]]) if ops else ""
        if op[0] != "equal" and len(ops) > 1 and ops[-2][0] != "equal" and gap.isspace():
            # two changes one space apart read as one: "~~0.25% (falling)~~ **not detected**"
            ops[-2:] = [("replace", ops[-2][1], op[2], ops[-2][3], op[4])]
        else:
            ops.append(op)
    out: list[tuple[str, str]] = []
    for n, (op, i1, i2, j1, j2) in enumerate(ops):
        if op == "equal":
            text = "".join(x[i1:i2])
            if len(text) > 2 * keep:
                core = text.strip()
                lead, trail = text[: len(text) - len(text.lstrip())], text[len(text.rstrip()):]
                head, tail = core[:keep].rsplit(" ", 1)[0], core[-keep:].split(" ", 1)[-1]
                text = ("… " + tail + trail if n == 0 else lead + head + " …"
                        if n == len(ops) - 1 else lead + head + " … " + tail + trail)
            out.append(("same", text))
            continue
        if i2 > i1:
            out.append(("del", "".join(x[i1:i2])))
        if j2 > j1:
            out.append(("ins", "".join(y[j1:j2])))
    return out


def _note(pf: PatientFile, a: int, b: int) -> list[dict]:
    """The report summary note's sentences that differ: added, removed, or changed (a sentence
    replaced in place), with the label the report gives the note (an estimate is a model
    inference)."""
    va, vb = pf.versions[a], pf.versions[b]
    x, y = sentences(va.summary), sentences(vb.summary)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=x, b=y, autojunk=False).get_opcodes():
        if op == "equal":
            continue
        olds, news = x[i1:i2], y[j1:j2]
        for n in range(max(len(olds), len(news))):
            old = olds[n] if n < len(olds) else None
            new = news[n] if n < len(news) else None
            out.append({"status": "added" if old is None else "removed" if new is None
                        else "changed", "before": old, "after": new,
                        "evidence": INFERENCE if (vb.risk if new else va.risk) else OBSERVED})
    return out


def diff(pf: PatientFile, a: int, b: int, data=None) -> dict:
    """Everything that differs between report versions ``a`` and ``b`` (taken in time order):
    {"a", "b", "from", "to" (labels), "when" (each one's date), "versions" (how many versions
    apart), "risk" (``risk_delta``), "findings" (the record rows and workbench finding cards
    added, changed or removed, each with its evidence label, trust and where it opens),
    "tests" (added after ``a`` up to ``b``, each with the version it came in), "queue" (the
    attention queue's changes), "note" (the summary note's changed sentences), "counts",
    "imported" (versions in between that came from an import), "snapshot" (SNAPSHOT)}.
    ``data(j)``: the version's {"sums", "queue"} (the shell's memo)."""
    a, b = sorted((a, b))
    same = a == b
    da = _data(pf, a, data)
    db = da if same else _data(pf, b, data)
    findings = [] if same else _record(pf, a, b) + _cards(da["sums"], db["sums"], a, b)
    tests = [{"test": t, "version": k, "label": pf.versions[k].label,
              "imported": pf.versions[k].imported}
             for k in range(a + 1, b + 1) for t in pf.versions[k].tests]
    queue = [] if same else _queue(da["queue"], db["queue"], a, b)
    note = [] if same else _note(pf, a, b)
    counts = {s: sum(f["status"] == s for f in findings) for s in STATUS}
    counts.update({f"queue_{s}": sum(q["status"] == s for q in queue) for s in STATUS})
    counts.update(tests=len(tests), sos=sum(q["status"] == "added" and q["sos"] for q in queue),
                  note=len(note))
    return {"a": a, "b": b, "from": pf.versions[a].label, "to": pf.versions[b].label,
            "when": (when(pf, a), when(pf, b)), "versions": b - a,
            "risk": risk_delta(pf, a, b), "findings": findings, "tests": tests,
            "queue": queue, "note": note, "counts": counts,
            "imported": [pf.versions[k].label for k in range(a + 1, b + 1)
                         if pf.versions[k].imported],
            "snapshot": SNAPSHOT}


def _n(k: int, word: str) -> str:
    return f"{k} {word}{'' if k == 1 else 's'}"


def summary_line(d: dict) -> str:
    """One sentence of what ``diff`` found: the risk move, then the counts."""
    r, c = d["risk"], d["counts"]
    if r["kind"] == "probability":
        risk = (f"12-month risk {r['points']:+.0f} points ({r['before']:.0%} → {r['after']:.0%}"
                + (")" if r["exceeds"] else ", within the 5 models' spread)"))
    elif r["kind"] == "percentile":
        risk = ("risk unchanged (the estimate rests on the tumor sample)" if not r["delta"]
                else f"cohort percentile {r['points']:+.0f}")
    else:
        risk = "no new risk estimate"
    parts = [risk]
    if c["tests"]:
        parts.append(_n(c["tests"], "test") + " added")
    found = [(s, c[s]) for s in STATUS if c[s]]
    if found:
        parts.append(", ".join(_n(k, "finding") + f" {s}" if n == 0 else f"{k} {s}"
                               for n, (s, k) in enumerate(found)))
    if c["queue_added"]:
        parts.append(f"{c['queue_added']} new in the attention queue"
                     + (f" ({_n(c['sos'], 'SOS alert')})" if c["sos"] else ""))
    return "; ".join(parts)


def version_delta_line(pf: PatientFile, i: int, data=None) -> str:
    """For the report's header: one sentence on what version ``i`` changed since the one before,
    e.g. "Since the previous version (month 11): 12-month risk +51 points (37% → 88%); 1 test
    added; 2 findings added, 3 changed; 4 new in the attention queue (3 SOS alerts)." Risk moves
    are in points, as everywhere in the app. The risk is a model inference: show it with that
    label. ``data(j)``: the shell's per-version memo (``overview_data(pf, j)``)."""
    if i == 0:
        return "The first report version: nothing earlier to compare it with."
    d = diff(pf, i - 1, i, data)
    return f"Since the previous version ({d['when'][0]}): {summary_line(d)}."

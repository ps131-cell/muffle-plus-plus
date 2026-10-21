"""Clinical documents workbench for one patient file (docs/WORKBENCHES.md §8).

    streamlit run app/workbenches/documents.py      # the synthetic patient's documents, standalone

The workspace pages call ``render(file, version=None, focus=None, note=None)`` with a
``muffle.workspace.PatientFile``; ``version`` is an index into ``file.versions`` (the documents
as of that version), ``focus`` a document id to open first, ``note`` the report's case note (a
language model's text, shown as inferred). It draws inside the current container only.

Overview and the "look here" list first, then the documents with their text and every
documented fact highlighted, the facts table (a row jumps to its sentence), documented versus
inferred, conflicts side by side, the documents' own timeline, plain-word search, review marks
and pins, the rules card and the exports. Every fact comes from a rule run on the text here
(``muffle.workbench.documents``): no language model reads these documents and no text leaves
the machine.
"""

from __future__ import annotations

import html
import json
import sys
from datetime import datetime
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle.workbench import documents as wb  # noqa: E402
from muffle.workbench.grammar import CANNOT_SEE, CARD, EXPORT, chip, esc  # noqa: E402
from muffle.workspace import IMPLEMENTED, MARKS, PatientFile, finding_key  # noqa: E402

FACT, FOCUS, HIT = "#fde68a", "#bfdbfe", "#bbf7d0"
NO_MARK = "no mark"
PROVENANCE = (f"Data: the file's documents as written (sources below). Method: {wb.RULES_VERSION}, "
              "regular expressions run here; no language model reads these documents and no "
              "text leaves this machine. Status: implemented; measured on TCGA pathology reports "
              "against TCGA's clinical fields (Methods and validation).")
VALIDATION = APP / "documents" / "validation.json"


def chips(*labels: str) -> None:
    color = {wb.DOCUMENTED: "blue", "synthetic patient": "orange"}  # the rest: shared grammar
    st.caption(" ".join(chip(x, color.get(x)) for x in labels))


def _marked(text: str, spans: list[tuple[int, int]], lo: int, hi: int, color: str = FACT) -> str:
    """text[lo:hi] as HTML, with the parts of ``spans`` inside it highlighted."""
    inside = [(max(a, lo) - lo, min(b, hi) - lo) for a, b in spans if a < hi and b > lo]
    return "".join(
        f'<mark style="background:{color};color:#111;padding:0 1px">{html.escape(p)}</mark>'
        if hit else html.escape(p) for p, hit in wb.highlight(text[lo:hi], inside))


def viewer(text: str, spans: list[tuple[int, int]], focus: tuple[int, int] | None = None,
           lo: int = 0, hi: int | None = None, height: int = 380) -> None:
    """text[lo:hi], facts highlighted, the focused sentence boxed in blue."""
    hi = len(text) if hi is None else min(hi, len(text))
    s, e = focus if focus else (hi, hi)
    s, e = max(lo, min(s, hi)), max(lo, min(e, hi))
    body = (("…" if lo else "") + _marked(text, spans, lo, s)
            + f'<span style="background:{FOCUS};color:#111;outline:2px solid #2a78d6">'
            + _marked(text, spans, s, e) + "</span>" + _marked(text, spans, e, hi)
            + ("…" if hi < len(text) else ""))
    st.html(f'<div style="white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:13px;'
            f'line-height:1.5;max-height:{height}px;overflow-y:auto;border:1px solid #8a8f9855;'
            f'border-radius:6px;padding:10px">{body}</div>')


def _mark(key: str, what: str, value: str) -> None:
    reviews = st.session_state.setdefault("reviews", {})
    if value == NO_MARK:
        reviews.pop(key, None)
    else:
        reviews[key] = {"what": what, "mark": value, "by": st.session_state.get("reviewer") or "",
                        "at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _pin(key: str, what: str) -> None:
    pins = st.session_state.setdefault("pins", {})
    if pins.pop(key, None) is None:
        pins[key] = what


def _what(f: dict, titles: dict) -> str:
    return f"{f['label']} {f['value']} ({titles[f['doc']]})"


def render(file: PatientFile, version: int | None = None, focus: str | None = None,
           note: str | None = None) -> None:
    """The workbench for one patient file, drawn inside the current container."""
    i = len(file.versions) - 1 if version is None else version
    docs = wb.file_documents(file, i)
    titles = {d["id"]: d["title"] for d in docs}
    facts = wb.facts(docs)
    reviews = st.session_state.setdefault("reviews", {})
    keys = [finding_key(file, "document", f["doc"], f"{f['label']}: {f['value']}") for f in facts]
    st.subheader("Clinical documents")
    st.caption(f"{file.id} · {file.title}"
               + ("" if version is None else f" · as of {file.versions[i].label}"))
    chips(IMPLEMENTED, wb.DOCUMENTED, "rules, no model",
          *(["synthetic patient"] if file.kind == "synthetic" else []))
    if file.kind == "synthetic":
        st.warning("Synthetic patient: these notes were written by hand and are not a real "
                   "person's. They are short, so few pathology facts appear.")
    st.caption(PROVENANCE)
    if not docs:
        st.info("No document in this file yet. A report or a note comes in through Import "
                "tests.")
        return

    conflicts, missing = wb.conflicts(facts), wb.missing_fields(facts)
    marked = [(f, reviews[k]) for f, k in zip(facts, keys, strict=True) if k in reviews]
    dated = [d for d in docs if d["month"] is not None]
    kinds = pd.Series([d["kind"] for d in docs]).value_counts()
    st.markdown(
        f"**{len(docs)} document{'s' if len(docs) != 1 else ''}**"
        + (" (" + ", ".join(f"{n} {k.lower()}" for k, n in kinds.items()) + ")"
           if len(kinds) > 1 else "")
        + (f", months {dated[0]['month']} to {dated[-1]['month']}" if dated else ", undated")
        + f"; **{len(facts)} documented facts**, {len(conflicts)} conflict"
        f"{'s' if len(conflicts) != 1 else ''} between documents, {len(marked)} review mark"
        f"{'s' if len(marked) != 1 else ''}.")

    # look here: what to check by eye
    st.markdown("#### Look here")
    look = [f"**Conflict** · {c['label']}: " + " vs ".join(
        f"{v['value']} ({', '.join(titles[d] for d in v['docs'])})" for v in c["values"])
        for c in conflicts]
    look += [f"**{r['mark'].capitalize()}** · {_what(f, titles)}, by {r['by'] or 'no initials'}"
             for f, r in marked if r["mark"] in ("disagree", "second look")]
    if missing:
        look.append("**Not documented in any document here** · " + ", ".join(missing)
                    + ": unknown, not negative.")
    st.markdown("\n".join(f"- {x}" for x in look) or "- Nothing to check: no conflict, no mark.")

    # documents and the text viewer
    st.markdown("#### Documents")
    jump = st.session_state.get(f"docs-jump-{file.id}")
    ids = [d["id"] for d in docs]
    start = ids.index(focus) if focus in ids else 0
    if jump and jump[0] in ids:
        start = ids.index(jump[0])
    left, right = st.columns([2, 3])
    with left:
        pick = st.radio("Document", ids, index=start, key=f"docs-pick-{file.id}-{i}-{start}",
                        format_func=lambda d: titles[d], label_visibility="collapsed")
        doc = docs[ids.index(pick)]
        st.caption(f"Source: {doc['source']}")
        st.caption("When: " + (f"month {doc['month']}" if doc["month"] is not None else
                               "undated (the de-identified report's dates were removed)"))
    with right:
        own = [f for f in facts if f["doc"] == doc["id"]]
        foc = tuple(jump[1]) if jump and jump[0] == doc["id"] else None
        spans = [(f["start"], f["end"]) for f in own]
        if foc:  # the sentence in its context first: the full text below may need a scroll
            f = next((f for f in own if tuple(f["sentence"]) == foc), None)
            st.markdown(f"Jumped to **{f['label']} {f['value']}**, boxed in blue:" if f else
                        "Jumped to the sentence boxed in blue:")
            viewer(doc["text"], spans, foc, max(0, foc[0] - 250), foc[1] + 250, height=150)
        viewer(doc["text"], spans, foc)
        st.caption(f"{len(own)} facts highlighted in yellow: the characters each rule matched.")

    # facts table: a row jumps to its sentence
    st.markdown(f"#### Documented facts {':blue-badge[documented]'}")
    fields = st.multiselect("Fields", list(dict.fromkeys(f["label"] for f in facts)),
                            key=f"docs-fields-{file.id}", placeholder="All fields")
    shown = [(f, k) for f, k in zip(facts, keys, strict=True) if not fields or f["label"] in fields]
    table = pd.DataFrame([{
        "Field": f["label"], "Value": f["value"], "Document": titles[f["doc"]],
        "Source sentence": f["quote"][:160] + ("…" if len(f["quote"]) > 160 else ""),
        "Characters": f"{f['start']}–{f['end']}", "Status": f["status"],
        "Mark": (reviews.get(k) or {}).get("mark", ""),
        "Pinned": "📌" if k in st.session_state.get("pins", {}) else ""} for f, k in shown])
    rows = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row",
                        key=f"docs-facts-{file.id}-{i}-{'.'.join(fields)}",
                        width="stretch").selection.rows if shown else []
    st.caption("Select a row to open its document at the source sentence. Status documented: "
               "the document says it; nothing is derived (a % is not turned into a status, a pT "
               "into a stage).")
    if rows:
        f = shown[rows[0]][0]
        new = (f["doc"], tuple(f["sentence"]))
        if st.session_state.get(f"docs-jump-{file.id}") != new:
            st.session_state[f"docs-jump-{file.id}"] = new
            st.rerun()

    # documented versus inferred
    st.markdown("#### Documented versus inferred")
    a, b = st.columns(2)
    with a:
        st.markdown(f"**Documented** {':blue-badge[documented]'}")
        st.caption("What the documents say, at the characters shown above: a pathologist's or "
                   "clinician's own words, found by rules.")
        first = {}  # each field's first statement, in the order of the facts table's fields
        for f in sorted(facts, key=lambda f: list(wb.FIELDS).index(f["field"])):
            first.setdefault(f["label"], f)
        st.markdown("\n".join(f"- {lab}: {f['value']} ({titles[f['doc']]})"
                              for lab, f in first.items()) or "- none")
    with b:
        st.markdown(f"**Inferred elsewhere in this file** {':violet-badge[model inference]'}")
        st.caption("Not read from these documents, and never mixed with them.")
        st.markdown(f"- Report summary ({file.versions[i].label}): {file.versions[i].summary}")
        if note:
            with st.expander("The case note (written by a language model from derived numbers, "
                             "not from these documents)"):
                st.markdown(esc(note))
        else:
            st.caption("No case note in this file.")

    # conflicts side by side
    st.markdown("#### Conflicts between documents")
    if not conflicts:
        st.caption("No field has different values in two documents.")
    for c in conflicts:
        with st.container(border=True):
            st.markdown(f"**{c['label']}** · kept side by side, no vote")
            for col, v in zip(st.columns(len(c["values"])), c["values"], strict=True):
                col.markdown(f"**{v['value']}** · " + ", ".join(titles[d] for d in v["docs"]))
                col.caption(" / ".join(q[:200] for q in v["quotes"]))

    # timeline from the documents' own dates
    st.markdown("#### Timeline of the documents")
    st.dataframe(pd.DataFrame(wb.timeline(docs))[["when", "title", "kind", "dates_in_text"]]
                 .rename(columns={"when": "When", "title": "Document", "kind": "Kind",
                                  "dates_in_text": "Dates written in it"}),
                 hide_index=True, width="stretch")
    st.caption("From the documents themselves: the month a record entry carries, else a full "
               "date written in the text. Years alone (a citation, an edition) are not dates.")

    # search in plain words
    st.markdown("#### Search the documents")
    q = st.text_input("Plain words, e.g. \"estrogen positive\", \"margin\", \"palbociclib\"",
                      key=f"docs-q-{file.id}")
    if q:
        hits = wb.search(docs, q)
        if not hits:
            st.info(f"No document in this file mentions \"{q}\".")
        for h in hits[:20]:
            d = docs[ids.index(h["doc"])]
            st.html(f'<div style="font-size:13px;margin:2px 0"><b>{html.escape(h["title"])}</b>'
                    f" · {_marked(d['text'], h['spans'], h['start'], h['end'], HIT)}</div>")
        if len(hits) > 20:
            st.caption(f"{len(hits) - 20} more sentences match; add a word to narrow it.")

    # review marks and pins
    st.markdown("#### Review a fact")
    if facts:
        n = st.selectbox("Fact", range(len(facts)), key=f"docs-review-{file.id}-{i}",
                         format_func=lambda k: _what(facts[k], titles))
        f, k = facts[n], keys[n]
        done = reviews.get(k)
        c1, c2 = st.columns([3, 2])
        c1.segmented_control("Mark", [NO_MARK, *MARKS[1:]], key=f"docs-mark-{k}",
                             default=done["mark"] if done else NO_MARK,
                             on_change=lambda: _mark(k, _what(f, titles),
                                                     st.session_state[f"docs-mark-{k}"]
                                                     or NO_MARK))
        c2.checkbox("Pin to the top of the report", key=f"docs-pin-{k}",
                    value=k in st.session_state.get("pins", {}), on_change=_pin,
                    args=(k, _what(f, titles)))
        if done:
            st.caption(f"{done['mark']} · {done['by'] or 'no initials'} · {done['at']}")
        st.caption("Marks and pins stay in this browser session and go into the report export.")

    st.markdown(f"#### {CANNOT_SEE}")
    st.markdown("\n".join(f"- {x}" for x in wb.CANNOT_SEE))
    with st.expander(f"{CARD}: the rules and their measured precision and recall"):
        st.dataframe(pd.DataFrame(list(wb.RULES.items()), columns=["Fact", "Rule"]),
                     hide_index=True, width="stretch")
        methods_card(compact=True)

    st.markdown(f"#### {EXPORT}")
    e1, e2 = st.columns(2)
    marks = {k: reviews[k] for k in keys if k in reviews}
    e1.download_button(
        "Download the documents and facts (JSON)", json.dumps({
            "file": file.id, "version": file.versions[i].label, "method": wb.RULES_VERSION,
            "documents": docs, "facts": facts, "conflicts": conflicts, "marks": marks},
            indent=1, default=str),
        file_name=f"{file.id.replace(' ', '_')}_documents.json", mime="application/json")
    e2.download_button(
        "Download the facts (CSV)", pd.DataFrame([
            {**{k: f[k] for k in ("doc", "label", "value", "start", "end", "quote", "status",
                                  "rule")}, "mark": (reviews.get(key) or {}).get("mark", "")}
            for f, key in zip(facts, keys, strict=True)]).to_csv(index=False),
        file_name=f"{file.id.replace(' ', '_')}_facts.csv", mime="text/csv")


def methods_card(compact: bool = False) -> None:
    """The extraction's measurement (app/documents/validation.json): per field, precision and
    recall against TCGA's clinical fields, on the held-out half of the reports and on the
    bundled cases."""
    if not VALIDATION.exists():
        st.caption("Validation numbers are not available here.")
        return
    v = json.loads(VALIDATION.read_text())
    sets = v["sets"]
    rows = [{"Field": r["compared"], "Patients with a TCGA value": r["with_value"],
             "Extracted": r["extracted"], "Precision": r["precision"], "Recall": r["recall"],
             "Bundled cases: precision": b["precision"], "Bundled cases: recall": b["recall"]}
            for r, b in zip(sets["test"]["fields"], sets["bundled"]["fields"], strict=True)]
    pct = st.column_config.NumberColumn(format="percent")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={c: pct for c in ("Precision", "Recall", "Bundled cases: "
                                                 "precision", "Bundled cases: recall")})
    st.caption(
        f"{v['rules']}, measured {v['measured']}: {sets['test']['patients']} TCGA-BRCA reports "
        f"the rules were not written on (the held-out half), and the "
        f"{sets['bundled']['patients']} bundled cases with a report. Reference: {v['reference']}. "
        "Precision: right / extracted; recall: right / patients with a value. Recall is "
        "bounded by what a report states: many TCGA surgical reports refer receptor results to "
        "an earlier biopsy report that is not in the dataset, and TCGA's fields were abstracted "
        "from the whole record, so a disagreement can be either side's error."
        + ("" if compact else " HER2 for this comparison only: the ISH result if stated, else "
           "the status word, else the IHC score read by the ASCO/CAP bands; the workbench shows "
           "every fact as written."))


def main() -> None:  # pragma: no cover - the standalone page
    from muffle.workspace import synthetic_file

    st.set_page_config(page_title="Clinical documents", layout="wide")
    if "reviewer" not in st.session_state:
        st.text_input("Reviewer initials", key="reviewer", max_chars=5)
    render(synthetic_file(json.loads((APP / "timeline_synthetic.json").read_text("utf-8"))))


if __name__ == "__main__":
    main()

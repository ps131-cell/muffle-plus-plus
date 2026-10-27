"""Clinical documents workbench for one patient file (docs/WORKBENCHES.md §8).

    streamlit run app/workbenches/documents.py      # the synthetic patient's documents, standalone

The workspace pages call ``render(file, version=None, focus=None, note=None, test=None)`` with
a ``muffle.workspace.PatientFile``; ``version`` is an index into ``file.versions`` (the documents
as of that version), ``focus`` a document id to open first, ``note`` the report's case note (a
language model's text, shown as inferred), ``test`` the test opened. It draws inside the current
container only, in the shared page skeleton (``workbenches._page``).

Overview (one paragraph, the look-here queue: conflicts D1…, models disagree M1…; search across
the text, the facts and the model's spans), the picture (the documents with every documented
fact highlighted by the rules and the named-entity model's spans underlined as model
inference), the details (the facts table whose row jumps to its sentence, the rules and the
model side by side, the model's spans, documented versus inferred, conflicts settled only by the
clinician's mark, the documents over time), the Spot panel of one finding with its review mark,
the model-and-validation card, what the documents cannot show, and the exports. The facts come
from rules run on the text here (``muffle.workbench.documents``); the model's spans were computed
offline on a local machine and ship as derived JSON: no model runs here and no text leaves the
machine.
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
if str(APP) not in sys.path:  # run on its own, the page still finds the shared skeleton
    sys.path.insert(0, str(APP))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle.report.case_tools import INFERENCE  # noqa: E402
from muffle.workbench import documents as wb  # noqa: E402
from muffle.workbench.grammar import esc  # noqa: E402
from muffle.workspace import IMPLEMENTED, MARKS, PatientFile, finding_key  # noqa: E402
from workbenches._howto import how_to, instruct  # noqa: E402
from workbenches._page import Page, land, line_and_action, queue_items  # noqa: E402

FACT, FOCUS, HIT, MODEL = "#fde68a", "#bfdbfe", "#bbf7d0", "#7c3aed"
NO_MARK = "no mark"
UNSETTLED = "not settled"
PROVENANCE = (f"Data: the file's documents as written (sources below). Method: {wb.RULES_VERSION}, "
              "regular expressions run here, and a second reading by "
              f"{wb.NER_MODEL} ({wb.NER_LICENSE}), a named-entity model run offline on a local "
              "machine whose spans ship with the bundled reports; no model runs here and no text "
              "leaves this machine. Status: implemented; both readings measured on TCGA "
              "pathology reports against TCGA's clinical fields (Methods and validation).")
VALIDATION = APP / "documents" / "validation.json"
HOW_TO = ("**Documents**: each document with the rules' facts in yellow and the model's spans "
          "underlined in violet (**Compare the two readers** sets their readings side by side). "
          "**Look here**: what to check first, and why. **Spot panel**, below: one fact at its "
          "sentence, with **Jump to the sentence**, your mark and a pin.")


def _marked(text: str, spans: list[tuple[int, int]], lo: int, hi: int, color: str = FACT,
            model: list[tuple[int, int, str]] = ()) -> str:
    """text[lo:hi] as HTML: ``spans`` highlighted (the rules' facts, or search hits) and the
    model's spans [(start, end, tip)] underlined in violet, both layers drawn at once."""
    tagged = [(a, b, "rules") for a, b in spans] + list(model)
    inside = [(max(a, lo) - lo, min(b, hi) - lo, t) for a, b, t in tagged if a < hi and b > lo]
    out = []
    for piece, tags in wb.layers(text[lo:hi], inside):
        p = html.escape(piece)
        tips = [t for t in tags if t != "rules"]
        if tips:
            p = (f'<span title="{html.escape("; ".join(tips))}" style="border-bottom:3px solid '
                 f'{MODEL};background:{MODEL}1f">{p}</span>')
        if "rules" in tags:
            p = f'<mark style="background:{color};color:#111;padding:0 1px">{p}</mark>'
        out.append(p)
    return "".join(out)


def viewer(text: str, spans: list[tuple[int, int]], focus: tuple[int, int] | None = None,
           lo: int = 0, hi: int | None = None, height: int = 380,
           model: list[tuple[int, int, str]] = ()) -> None:
    """text[lo:hi], facts highlighted, model spans underlined, the focused sentence boxed."""
    hi = len(text) if hi is None else min(hi, len(text))
    s, e = focus if focus else (hi, hi)
    s, e = max(lo, min(s, hi)), max(lo, min(e, hi))
    body = (("…" if lo else "") + _marked(text, spans, lo, s, model=model)
            + f'<span style="background:{FOCUS};color:#111;outline:2px solid #2a78d6">'
            + _marked(text, spans, s, e, model=model) + "</span>"
            + _marked(text, spans, e, hi, model=model) + ("…" if hi < len(text) else ""))
    st.html(f'<div style="white-space:pre-wrap;font-family:ui-monospace,monospace;font-size:13px;'
            f'line-height:1.5;max-height:{height}px;overflow-y:auto;border:1px solid #8a8f9855;'
            f'border-radius:6px;padding:10px">{body}</div>')


def _tips(model: list[dict]) -> list[tuple[int, int, str]]:
    """The model's findings as underline spans, one per marked stretch."""
    seen = {}
    for f in model:
        seen.setdefault((f["start"], f["end"]), f"{INFERENCE}: {f['model_label']} "
                                                f"{f['score']:.2f}")
    return [(a, b, t) for (a, b), t in seen.items()]


def _mark(key: str, what: str, value: str, **extra) -> None:
    reviews = st.session_state.setdefault("reviews", {})
    if value == NO_MARK:
        reviews.pop(key, None)
    else:
        reviews[key] = {"what": what, "mark": value, "by": st.session_state.get("reviewer") or "",
                        "at": datetime.now().strftime("%Y-%m-%d %H:%M"), **extra}


def _settle(key: str, what: str, widget: str) -> None:
    """A conflict settled by the clinician: the value that stands, as a "reviewed" mark."""
    v = st.session_state[widget]
    _mark(key, what, NO_MARK if v == UNSETTLED else "reviewed",
          **({} if v == UNSETTLED else {"stands": v}))


def _pin(key: str, what: str) -> None:
    pins = st.session_state.setdefault("pins", {})
    if pins.pop(key, None) is None:
        pins[key] = what


def _what(f: dict, titles: dict) -> str:
    if f["rule"] == "model":
        return (f"{f['label']} {f['value'] or '(mention)'}: model marked '{f['span'][:40]}' "
                f"({titles[f['doc']]})")
    return f"{f['label']} {f['value']} ({titles[f['doc']]})"


def _key(file: PatientFile, f: dict) -> str:
    if f["rule"] == "model":
        return finding_key(file, "document", f["doc"],
                           f"model {f['label']}: {f['span']} @{f['start']}")
    return finding_key(file, "document", f["doc"], f"{f['label']}: {f['value']}")


def _jump(file: PatientFile, f: dict) -> None:
    """Open the finding's document at its sentence and show it in the Spot panel."""
    new = (f["doc"], tuple(f["sentence"]))
    spot = _key(file, f)
    if (st.session_state.get(f"docs-jump-{file.id}") != new
            or st.session_state.get(f"docs-spot-{file.id}") != spot):
        st.session_state[f"docs-jump-{file.id}"] = new
        st.session_state[f"docs-spot-{file.id}"] = spot
        st.rerun()


def jump_to(file: PatientFile, f: dict) -> None:
    """The Spot panel's "Jump to the sentence": the picture opens the finding's document with
    its sentence boxed (a callback, so the picture above follows on this run)."""
    st.session_state[f"docs-jump-{file.id}"] = (f["doc"], tuple(f["sentence"]))


def _pct(x) -> str:
    return "–" if x is None else f"{x:.0%}"


def render(file: PatientFile, version: int | None = None, focus: str | None = None,
           note: str | None = None, test=None) -> None:
    """The workbench for one patient file, drawn inside the current container in the shared
    page skeleton (``workbenches._page``)."""
    i = len(file.versions) - 1 if version is None else version
    page = Page("documents", file, test, version)
    docs = wb.file_documents(file, i)
    titles = {d["id"]: d["title"] for d in docs}
    facts = wb.facts(docs)
    model = wb.model_facts(docs)
    read = [d["id"] for d in docs if wb.doc_spans(d["id"]) is not None]
    rows = wb.file_agreement(docs)
    reviews = st.session_state.setdefault("reviews", {})
    keys = [_key(file, f) for f in facts]
    page.title(IMPLEMENTED, wb.DOCUMENTED, "rules", *([INFERENCE] if read else []),
               *(["synthetic patient"] if file.kind == "synthetic" else []),
               colors={wb.DOCUMENTED: "blue", "synthetic patient": "orange"})
    if docs:
        how_to("documents", HOW_TO)
    if file.kind == "synthetic":
        st.warning("Synthetic patient: these notes were written by hand and are not a real "
                   "person's. They are short, so few pathology facts appear.")
    st.caption(PROVENANCE)
    if not docs:
        with page.overview():
            st.info("No document in this file yet. A report or a note comes in through Import "
                    "tests.")
        with page.card():
            methods_card(compact=True)
        with page.cannot_see(wb.CANNOT_SEE):
            pass
        with page.export(empty="Nothing to export: no document in this file."):
            pass
        return

    conflicts, missing = wb.conflicts(facts), wb.missing_fields(facts)
    changed = wb.changes(docs, facts)
    marked = [(f, reviews[k]) for f, k in zip(facts, keys, strict=True) if k in reviews]
    dated = [d for d in docs if d["month"] is not None]
    kinds = pd.Series([d["kind"] for d in docs]).value_counts()
    count = {k: sum(r["kind"] == k for r in rows) for k in ("agree", "disagree")}
    ids = [d["id"] for d in docs]

    # overview: one paragraph, the look-here queue, search
    with page.overview():
        st.markdown(
            f"**{len(docs)} document{'s' if len(docs) != 1 else ''}**"
            + (" (" + ", ".join(f"{n} {k.lower()}" for k, n in kinds.items()) + ")"
               if len(kinds) > 1 else "")
            + (f", months {dated[0]['month']} to {dated[-1]['month']}" if dated else ", undated")
            + f"; **{len(facts)} documented facts**, {len(conflicts)} conflict"
            f"{'s' if len(conflicts) != 1 else ''} between documents, {len(marked)} review mark"
            f"{'s' if len(marked) != 1 else ''}."
            + (f" The named-entity model read {len(read)} of {len(docs)} documents: "
               f"{len(model)} spans; its readings agree with the rules' on {count['agree']} "
               f"field(s) and differ on {count['disagree']}." if read else
               " The named-entity model has not read these documents (it runs on a local "
               "machine; imported documents are queued for the local pipeline)."))
        page.look_here(instruct(queue_items("documents", file, version,
                                            lambda: wb.queue(file, version))),
                       land=lambda f: land(file, i, f),
                       empty="Nothing to check: no conflict between documents, and the rules "
                             "and the model agree on every receptor and stage field.")
        extra = [f"**Changed over time** · {c['label']}: {c['from']} at month "
                 f"{c['from_month']}, {c['to']} at month {c['to_month']}" for c in changed]
        extra += [f"**{r['mark'].capitalize()}** · {_what(f, titles)}, by "
                  f"{r['by'] or 'no initials'}" for f, r in marked
                  if r["mark"] in ("disagree", "second look")]
        if missing:
            extra.append("**Not documented in any document here** · " + ", ".join(missing)
                         + ": unknown, not negative.")
        if extra:
            st.markdown("\n".join(f"- {x}" for x in extra))
        search(file, i, docs, facts, model, titles, ids)

    # the picture: the documents with both layers
    with page.picture("Documents", caption="Yellow: the rules' facts (documented). Violet "
                      "underline: the named-entity model's spans (model inference); hover for "
                      "its label and score. A row of Documented facts, or Jump to the sentence "
                      "in the Spot panel, boxes its sentence in blue. The documents cannot show "
                      "what they do not say: a field no document states is unknown, not "
                      "negative."):
        jump = st.session_state.get(f"docs-jump-{file.id}")
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
            show = st.toggle("Model spans", value=True, key=f"docs-layer-{file.id}",
                             disabled=doc["id"] not in read,
                             help="Show the named-entity model's spans beside the rules' facts")
        with right:
            both = st.toggle("Compare the two readers", key=f"docs-compare-{file.id}",
                             disabled=doc["id"] not in read,
                             help="The rules' and the model's readings of this document, field "
                                  "by field, under the text: agree, differ, or read by one only")
            own = [f for f in facts if f["doc"] == doc["id"]]
            mine = [f for f in model if f["doc"] == doc["id"]]
            tips = _tips(mine) if show else []
            foc = tuple(jump[1]) if jump and jump[0] == doc["id"] else None
            spans = [(f["start"], f["end"]) for f in own]
            if foc:  # the sentence in its context first: the full text below may need a scroll
                f = next((f for f in own + mine if tuple(f["sentence"]) == foc), None)
                st.markdown(f"Jumped to **{f['label']} {f['value'] or '(mention)'}**, boxed in "
                            "blue:" if f else "Jumped to the sentence boxed in blue:")
                viewer(doc["text"], spans, foc, max(0, foc[0] - 250), foc[1] + 250, height=150,
                       model=tips)
            viewer(doc["text"], spans, foc, model=tips)
            if both:
                mine_rows = [r for r in rows if r["doc"] == doc["id"]]
                st.markdown(f"**The two readers of this document** · rules "
                            f"{':blue-badge[documented]'} against the model "
                            f"{':violet-badge[model inference]'}, {len(mine_rows)} fields")
                st.dataframe(pd.DataFrame([{
                    "Field": r["label"], "Readings": r["kind"],
                    "Rules": "" if r["rules"] is None else str(r["rules"]),
                    "Model": "" if r["model"] is None else str(r["model"]),
                    "In words": r["line"]} for r in mine_rows]), hide_index=True,
                    width="stretch")
            st.caption(f"{len(own)} facts highlighted in yellow ({wb.DOCUMENTED}: the "
                       "characters each rule matched)"
                       + (f"; {len(tips)} spans underlined in violet ({INFERENCE}: the "
                          "named-entity model's, hover for its label and score)." if tips else
                          "." if doc["id"] in read else
                          "; the named-entity model has not read this document: queued for the "
                          "local pipeline (no model runs here)."))

    # details
    with page.details("Documented facts", len(facts), key=f"docs-d-facts-{file.id}"):
        fields = st.multiselect("Fields", list(dict.fromkeys(f["label"] for f in facts)),
                                key=f"docs-fields-{file.id}", placeholder="All fields")
        shown = [(f, k) for f, k in zip(facts, keys, strict=True)
                 if not fields or f["label"] in fields]
        table = pd.DataFrame([{
            "Field": f["label"], "Value": f["value"], "Document": titles[f["doc"]],
            "Source sentence": f["quote"][:160] + ("…" if len(f["quote"]) > 160 else ""),
            "Characters": f"{f['start']}–{f['end']}", "Status": f["status"],
            "Mark": (reviews.get(k) or {}).get("mark", ""),
            "Pinned": "📌" if k in st.session_state.get("pins", {}) else ""} for f, k in shown])
        sel = st.dataframe(table, hide_index=True, on_select="rerun", selection_mode="single-row",
                           key=f"docs-facts-{file.id}-{i}-{'.'.join(fields)}",
                           width="stretch").selection.rows if shown else []
        st.caption("Click a row to jump to its sentence in Documents above and open it in the "
                   "Spot panel. Status documented: the document says it; nothing is derived (a % "
                   "is not turned into a status, a pT into a stage).")
        if sel:
            _jump(file, shown[sel[0]][0])

    with page.details("The rules and the model, side by side",
                      f"{len(rows)} readings" if read else "not read by the model",
                      key=f"docs-d-agree-{file.id}"):
        if not read:
            st.caption("The named-entity model has not read these documents. It runs on a local "
                       "machine, outside this app: the bundled TCGA reports carry "
                       "its spans; an imported document is queued for the local pipeline.")
        elif rows:
            st.dataframe(pd.DataFrame([{
                "Document": titles[r["doc"]], "Field": r["label"], "Readings": r["kind"],
                "Rules (documented)": "" if r["rules"] is None else str(r["rules"]),
                "Model (model inference)": "" if r["model"] is None else str(r["model"]),
                "In words": r["line"]} for r in rows]), hide_index=True, width="stretch")
        if read:
            st.caption("Per field and document, the first value each reader gives, on the scales "
                       "they were measured on (HER2: ISH, else the status word, else the IHC "
                       "score by the ASCO/CAP bands; pT and pN by category). The model's value "
                       "is only what the characters it marked say; a span naming a field without "
                       "a result is a mention, shown underlined but not counted. The rules' "
                       "reading is the document's words; the model is weaker on these reports "
                       "(the card below), so a difference means re-reading the sentence, not a "
                       "vote.")

    if model:
        with page.details("The model's spans", len(model), key=f"docs-d-spans-{file.id}"):
            ms = st.dataframe(pd.DataFrame([{
                "Label given": f["model_label"], "Characters marked": f["span"][:80],
                "Value in them": f["value"] or "(mention)", "Score": round(f["score"], 2),
                "Document": titles[f["doc"]], "Characters": f"{f['start']}–{f['end']}"}
                for f in model]), hide_index=True, on_select="rerun",
                selection_mode="single-row", key=f"docs-spans-{file.id}-{i}",
                width="stretch").selection.rows
            if ms:
                _jump(file, model[ms[0]])

    with page.details("Documented versus inferred", key=f"docs-d-inferred-{file.id}"):
        a, b = st.columns(2)
        with a:
            st.markdown(f"**Documented** {':blue-badge[documented]'}")
            st.caption("What the documents say, at the characters shown above: a pathologist's "
                       "or clinician's own words, found by rules.")
            first = {}  # each field's first statement, in the order of the facts table's fields
            for f in sorted(facts, key=lambda f: list(wb.FIELDS).index(f["field"])):
                first.setdefault(f["label"], f)
            st.markdown("\n".join(f"- {lab}: {f['value']} ({titles[f['doc']]})"
                                  for lab, f in first.items()) or "- none")
        with b:
            st.markdown(f"**Inferred elsewhere in this file** {':violet-badge[model inference]'}")
            st.caption("Not read from these documents, and never mixed with them.")
            st.markdown(f"- Report summary ({file.versions[i].label}): "
                        f"{file.versions[i].summary}")
            if model:
                st.markdown(f"- The named-entity model's {len(model)} spans in these documents "
                            "(the side-by-side section).")
            if note:
                st.markdown("**The case note** (written by a language model from derived "
                            "numbers, not from these documents)")
                st.markdown(esc(note))
            else:
                st.caption("No case note in this file.")

    with page.details("Conflicts between documents", len(conflicts),
                      key=f"docs-d-conflicts-{file.id}", expanded=bool(conflicts)):
        if not conflicts:
            st.caption("No field has different values in two documents.")
        for c in conflicts:
            key = finding_key(file, "document", "conflict", c["label"])
            with st.container(border=True):
                st.markdown(f"**{c['label']}** · kept side by side, no vote · "
                            f"{wb.resolution(reviews.get(key))}")
                for col, v in zip(st.columns(len(c["values"])), c["values"], strict=True):
                    col.markdown(f"**{v['value']}** · " + ", ".join(titles[d] for d in v["docs"]))
                    col.caption(" / ".join(q[:200] for q in v["quotes"]))
                values = [UNSETTLED, *(v["value"] for v in c["values"])]
                stands = (reviews.get(key) or {}).get("stands")
                w = f"docs-settle-{key}"
                st.selectbox("The value that stands (your read of both sentences)", values,
                             index=values.index(stands) if stands in values else 0, key=w,
                             on_change=_settle, args=(key, f"{c['label']}: documents disagree",
                                                      w))

    hist = wb.history(docs, facts)
    with page.details("The documents over time", f"{len(dated)} dated, {len(changed)} change"
                      f"{'' if len(changed) == 1 else 's'}", key=f"docs-d-time-{file.id}"):
        st.dataframe(pd.DataFrame(wb.timeline(docs))[["when", "title", "kind", "dates_in_text"]]
                     .rename(columns={"when": "When", "title": "Document", "kind": "Kind",
                                      "dates_in_text": "Dates written in it"}),
                     hide_index=True, width="stretch")
        if any(h["facts"] for h in hist):
            grid = {}
            for h in hist:
                col = f"month {h['month']} · {h['title']}"
                for k, f in h["facts"].items():
                    grid.setdefault(wb.FIELDS[k], {})[col] = f["value"]
            st.dataframe(pd.DataFrame(grid).T.fillna(""), width="stretch")
            st.caption("Each dated document's receptor, stage, grade and type facts on the "
                       "file's time axis (empty: the document does not state it, unknown, not "
                       "negative).")
        for c in changed:
            what = {"receptor": "Receptor changed", "stage": "Restaged"}.get(c["kind"],
                                                                             "Changed")
            st.markdown(f"- **{what}** · {c['label']}: {c['from']} (month {c['from_month']}, "
                        f"{titles[c['from_doc']]}) → {c['to']} (month {c['to_month']}, "
                        f"{titles[c['to_doc']]})")
        st.caption("From the documents themselves: the month a record entry or an import "
                   "carries, else a full date written in the text (years alone are not dates); "
                   "a TCGA report is undated, so it is not on the axis. A change is documented "
                   "on both sides: neither value is taken as the current one, and a conflict is "
                   "settled only by your mark.")

    with page.spot():
        spot(file, i, docs, facts, model, rows, titles)

    with page.card():
        st.markdown(f"**The rules** · {wb.RULES_VERSION}")
        st.dataframe(pd.DataFrame(list(wb.RULES.items()), columns=["Fact", "Rule"]),
                     hide_index=True, width="stretch")
        st.markdown(f"**The model** · {wb.NER_METHOD}")
        methods_card(compact=True)

    with page.cannot_see(wb.CANNOT_SEE):
        pass

    with page.export():
        e = st.container(horizontal=True, gap="small")  # labels whole, wraps
        every = facts + model
        marks = {k: reviews[k] for k in map(lambda f: _key(file, f), every) if k in reviews}
        e.download_button(
            "Download the documents, facts and model spans (JSON)", json.dumps({
                "file": file.id, "version": file.versions[i].label, "method": wb.RULES_VERSION,
                "model": wb.NER_METHOD, "documents": docs, "facts": facts, "model_spans": model,
                "agreement": [{k: r[k] for k in ("doc", "field", "kind", "rules", "model",
                                                 "line")} for r in rows],
                "conflicts": conflicts,
                "changes": [{k: c[k] for k in c if not k.endswith("_fact")} for c in changed],
                "marks": marks}, indent=1, default=str),
            file_name=f"{file.id.replace(' ', '_')}_documents.json", mime="application/json")
        e.download_button(
            "Download the facts and model spans (CSV)", pd.DataFrame([
                {"layer": f["status"], **{k: f.get(k) for k in ("doc", "label", "value", "start",
                                                                 "end", "quote", "rule")},
                 "model_label": f.get("model_label", ""), "score": f.get("score"),
                 "mark": (reviews.get(_key(file, f)) or {}).get("mark", "")}
                for f in every]).to_csv(index=False),
            file_name=f"{file.id.replace(' ', '_')}_facts.csv", mime="text/csv")


def search(file: PatientFile, i: int, docs: list[dict], facts: list[dict], model: list[dict],
           titles: dict, ids: list[str]) -> None:
    """Search in plain words across the text, the documented facts and the model's spans."""
    q = st.text_input("Search the documents in plain words, e.g. \"HER2\", \"margin\", \"node "
                      "positive\", \"palbociclib\"", key=f"docs-q-{file.id}")
    if not q:
        return
    found = wb.search_findings(facts + model, q)
    if found:
        st.markdown(f"**Findings** · {len(found)} (documented facts and the model's spans)")
        fs = st.dataframe(pd.DataFrame([{
            "Layer": f["status"], "Field": f["label"], "Value": f["value"] or "(mention)",
            "Characters marked": (f.get("span") or "")[:60],
            "Score": round(f["score"], 2) if f["rule"] == "model" else None,
            "Document": titles[f["doc"]]} for f in found]), hide_index=True,
            on_select="rerun", selection_mode="single-row",
            key=f"docs-found-{file.id}-{i}-{q}", width="stretch").selection.rows
        if fs:
            _jump(file, found[fs[0]])
    hits = wb.search(docs, q)
    if not hits and not found:
        st.info(f"No document in this file mentions \"{q}\".")
    if hits:
        st.markdown(f"**Sentences** · {len(hits)}")
    for h in hits[:20]:
        d = docs[ids.index(h["doc"])]
        st.html(f'<div style="font-size:13px;margin:2px 0"><b>{html.escape(h["title"])}</b>'
                f" · {_marked(d['text'], h['spans'], h['start'], h['end'], HIT)}</div>")
    if len(hits) > 20:
        st.caption(f"{len(hits) - 20} more sentences match; add a word to narrow it.")


def spot(file: PatientFile, i: int, docs: list[dict], facts: list[dict], model: list[dict],
         rows: list[dict], titles: dict) -> None:
    """The Spot panel of one finding (a documented fact or a model span): its sentence with both
    layers, the rule or the model and its score, the TCGA field it was measured against with
    both readers' numbers, the other reader's value, and its review mark and pin."""
    every = facts + model
    if not every:
        st.caption("No finding in these documents.")
        return
    keys = [_key(file, f) for f in every]
    want = st.session_state.get(f"docs-spot-{file.id}")
    n = st.selectbox("Finding (a row of the tables above opens it here)", range(len(every)),
                     index=keys.index(want) if want in keys else 0,
                     key=f"docs-spot-pick-{file.id}-{i}-{want}",
                     format_func=lambda k: f"{every[k]['status']} · {_what(every[k], titles)}")
    f, k = every[n], keys[n]
    d = next(x for x in docs if x["id"] == f["doc"])
    is_model = f["rule"] == "model"
    with st.container(border=True):
        head, act = line_and_action()
        head.markdown(f"##### {f['label']} {f['value'] or '(a mention, no result)'}")
        act.button("Jump to the sentence", key=f"docs-jump-btn-{k}", on_click=jump_to,
                   args=(file, f), help="Open its document in Documents above with this "
                                        "sentence boxed in blue")
        st.caption((":violet-badge[model inference]" if is_model else ":blue-badge[documented]")
                   + f" · {titles[f['doc']]} · Method: "
                   + (wb.NER_METHOD if is_model else wb.RULES_VERSION))
        s, e = f["sentence"]
        viewer(d["text"], [(x["start"], x["end"]) for x in facts if x["doc"] == f["doc"]],
               (f["start"], f["end"]), s, e, height=120,
               model=_tips([x for x in model if x["doc"] == f["doc"]]))
        if is_model:
            st.markdown(f"**Model**: {wb.NER_METHOD}. Label given: *{f['model_label']}*; score "
                        f"**{f['score']:.2f}**; the value is read from the marked characters "
                        f"'{esc(f['span'][:80])}' only.")
        else:
            group = wb.RULE_GROUP.get(f["field"])
            st.markdown(f"**Rule** ({wb.RULES_VERSION}, '{f['rule']}'): "
                        + esc(wb.RULES.get(group, "")))
        m = wb.measured_against(f["field"])
        if m:
            r, md = m["rules"] or {}, m["model"] or {}
            st.markdown(f"**Measured against** TCGA's `{m['tcga_field']}` on the held-out half: "
                        f"the rules precision {_pct(r.get('precision'))}, recall "
                        f"{_pct(r.get('recall'))}; the model precision "
                        f"{_pct(md.get('precision'))}, recall {_pct(md.get('recall'))}.")
        else:
            st.caption("This field was not measured against a TCGA field (TCGA records no such "
                       "field); read the sentence.")
        other = next((r for r in rows if r["doc"] == f["doc"]
                      and r["field"] == wb.MEASURED_AS.get(f["field"], f["field"])), None)
        if other:
            st.markdown(f"**The two readings** ({other['kind']}): {esc(other['line'])}.")
        done = st.session_state.setdefault("reviews", {}).get(k)
        c1 = c2 = st.container(horizontal=True, gap="medium", vertical_alignment="bottom")
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


def methods_card(compact: bool = False) -> None:
    """The extraction's measurement (app/documents/validation.json): per field, precision and
    recall against TCGA's clinical fields of the rules and of the named-entity model, on the
    held-out half of the reports and on the bundled cases; the model's speed, the scan reader's
    text accuracy and both readers' known failures."""
    if not VALIDATION.exists():
        st.caption("Validation numbers are not available here.")
        return
    v = json.loads(VALIDATION.read_text())
    sets, ner = v["sets"], v.get("model")
    pct = st.column_config.NumberColumn(format="percent")
    for name, title in (("test", "Held-out half"), ("bundled", "Bundled cases")):
        mine = {r["field"]: r for r in ner["sets"][name]["fields"]} if ner else {}
        rows = [{"Field": r["compared"], "Patients with a TCGA value": r["with_value"],
                 "Rules: extracted": r["extracted"], "Rules: precision": r["precision"],
                 "Rules: recall": r["recall"],
                 **({"Model: extracted": mine[r["field"]]["extracted"],
                     "Model: precision": mine[r["field"]]["precision"],
                     "Model: recall": mine[r["field"]]["recall"]} if r["field"] in mine else {})}
                for r in sets[name]["fields"]]
        st.markdown(f"**{title}** ({sets[name]['patients']} patients)")
        st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                     column_config={c: pct for c in ("Rules: precision", "Rules: recall",
                                                     "Model: precision", "Model: recall")})
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
    if ner:
        run = ner["run"]
        st.caption(
            f"Model: {ner['method']}. Same reports, same split, same comparison; its value is "
            "what the characters it marked say. Speed: "
            f"{run['seconds_per_1000_characters']} s per 1,000 characters on {run['threads']} CPU "
            f"threads ({run['documents']} reports, {run['characters']:,} characters in "
            f"{run['seconds']:,.0f} s; {run['machine']}, load average {run['load_before']} to "
            f"{run['load_after']}). Known failures: " + " ".join(wb.NER_FAILURES))
    scan = v.get("scan")
    if scan:
        st.dataframe(pd.DataFrame([{
            "Scan": r["what"], "Pages": r["pages"], "Character accuracy": r["char_accuracy"],
            "Word accuracy": r["word_accuracy"],
            "Rules' facts kept": f"{r['facts_same']} of {r['facts_reference']}",
            "Reader looped": "yes" if r.get("looped") else "", "Seconds": r["seconds"]}
            for r in scan["rows"]]), hide_index=True, width="stretch",
            column_config={c: pct for c in ("Character accuracy", "Word accuracy")})
        st.caption(scan["note"])


def main() -> None:  # pragma: no cover - the standalone page
    from muffle.workspace import synthetic_file

    st.set_page_config(page_title="Clinical documents", layout="wide")
    if "reviewer" not in st.session_state:
        st.text_input("Reviewer initials", key="reviewer", max_chars=5)
    render(synthetic_file(json.loads((APP / "timeline_synthetic.json").read_text("utf-8"))))


if __name__ == "__main__":
    main()

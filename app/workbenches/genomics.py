"""Genomics (tumor sequencing) workbench page for one patient file.

The workspace pages call ``render(file, events=None, evidence=None, version=None)`` with a
``muffle.workspace.PatientFile``; ``evidence`` maps "GENE CHANGE" to CIViC items (the
``civic.evidence`` results), ``version`` is an index into ``file.versions`` (the variants and
treatments known as of that version; the latest when None), ``lookup`` an optional
``(gene, change) -> items`` callable, ``table`` the loaded CIViC table (for resistance items
and the watchlist; without it only the cited literature appears). ``render`` draws inside the
current container only: no page config, no sidebar. Standalone page, with two example files
(the synthetic patient and one TCGA case):

    streamlit run app/workbenches/genomics.py

Everything shown is observed (a sequenced mutation) or a hypothesis (a CIViC item or a
literature lead, for clinician review, never a recommendation); planned parts are shown as
planned rows, never as results. Review marks go to the shared ``st.session_state.reviews``
store under ``muffle.workspace.finding_key`` names (kind "variant" with the variant and the
sequencing month, kind "civic" with the variant and the item's URL), so the report page's export
carries them; initials come from ``st.session_state.reviewer`` (the shell's sidebar field), with
the page's own field only as a fallback when that key is absent.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle.report.civic import LEVELS  # noqa: E402
from muffle.workbench import genomics as wb  # noqa: E402
from muffle.workbench.grammar import CANNOT_SEE, CARD, chip, esc  # noqa: E402

# page-specific colors; statuses and evidence types take the shared grammar's
COLORS = {wb.FOUND: "blue", wb.NOT_FOUND: "green", wb.NOT_TESTED: "gray",
          wb.PANEL_NOT_STATED: "gray", "present": "orange", "none": "gray"}
QUEUE_WHY = {wb.ESTABLISHED: "a CIViC item of level A or B",
             wb.UNCERTAIN: "CIViC items of level C, D or E only",
             wb.NO_ITEMS: "no CIViC item in breast cancer"}
ITEM_COLUMNS = {"evidence_level": "Level", "therapies": "Therapies",
                "significance": "Significance", "direction": "Direction", "url": "CIViC",
                "level_meaning": "Level meaning", "citation": "Citation", "disease": "Disease",
                "match": "Profile match"}
LINK = {"CIViC": st.column_config.LinkColumn(display_text="evidence item"),
        "Source link": st.column_config.LinkColumn(display_text="open")}


def badge(text: str, color: str | None = None) -> str:
    return chip(text, color or COLORS.get(text))


def _level_text(level: str | None) -> str:
    return f"{level} ({LEVELS[level]})" if level in LEVELS else "none"


def _items_table(items: list[dict]) -> None:
    df = pd.DataFrame(items).reindex(columns=list(ITEM_COLUMNS)).fillna("")
    df["level_meaning"] = df["evidence_level"].map(lambda v: LEVELS.get(v, "unknown"))
    st.dataframe(df.rename(columns=ITEM_COLUMNS), hide_index=True, width="stretch",
                 column_config=LINK)


def _spot(file, v: dict, rungs: list[dict], cov: dict[str, str], strip: list, reviews: dict,
          key: str) -> None:
    """The Spot panel of one variant: ladder, CIViC table, the panel's view of the gene, the
    sample, the review marks."""
    st.markdown(f"### Spot: {esc(v['variant'])} · {v['sample']}"
                + (f" · month {v['month']}" if v["month"] is not None else ""))
    items = v["interpretation"]["items"]
    st.markdown("**Evidence ladder** · each rung carries its own evidence type and what would "
                "strengthen it")
    for r in rungs:
        st.markdown(f"**{r['rung']}. {r['label']}** {badge(r['evidence'])} {badge(r['status'])}")
        for line in r["lines"]:
            st.markdown(f"- {line}")
        st.caption(f"What would strengthen it: {r['strengthen']}")
    st.markdown("**CIViC items** · for clinician review, never a recommendation")
    if items:
        _items_table(items)
    else:
        st.info(v["interpretation"]["note"])
    st.markdown("**Conflicting evidence, side by side** · never averaged")
    groups = wb.conflicts(items)
    both = [c for c in groups if c["supports"] and c["does_not_support"]]
    for c in both:
        st.markdown(f"*{c['association']}*")
        left, right = st.columns(2)
        for col, side, name in ((left, "supports", "Supports"),
                                (right, "does_not_support", "Does not support")):
            col.markdown(f"**{name}** ({len(c[side])})")
            for i in c[side]:
                col.markdown(f"- level {i.get('evidence_level', '?')} · {i.get('citation', '?')}"
                             f" ({i['year']}) · {i.get('disease', '')}")
    if not both:
        st.caption(f"No item contradicts another for this variant"
                   f" ({len(groups)} one-sided association{'s' if len(groups) != 1 else ''}).")
    c1, c2 = st.columns(2)
    c1.markdown(f"**The panel's view of {v['gene']}**  \n{badge(cov.get(v['gene'], 'outside'))}"
                f" · {'in' if v['gene'] in cov else 'not in'} the 16-gene panel")
    c2.markdown("**Sample**  \n" + " → ".join(f"{k}: {val}" for k, val in strip[:4]))
    vkey = wb.variant_key(file, v)
    by = st.session_state.get("reviewer") or st.session_state.get("genomics-reviewer", "")
    st.markdown(f"**Review marks** · {wb.mark_text(reviews.get(vkey)) or 'no mark yet'}")
    cols = st.columns(len(wb.VERDICTS) + 2)
    for col, verdict in zip(cols, wb.VERDICTS, strict=False):
        if col.button(verdict.capitalize(), key=f"{key}-{v['variant']}-{verdict}"):
            wb.add_mark(reviews, vkey, f"{v['variant']} ({v['sample']})", verdict, by)
            st.rerun()
    if reviews.get(vkey) and cols[-1].button("Clear mark", key=f"{key}-{v['variant']}-clear"):
        wb.add_mark(reviews, vkey, "", None)
        st.rerun()
    if items:
        with st.expander("Mark one evidence item"):
            labels = {f"{i.get('evidence_level', '?')} · {i.get('therapies', '')} · "
                      f"{i.get('citation', '')}": (wb.item_key(file, v, i, n), i)
                      for n, i in enumerate(items)}
            picked = st.selectbox("Evidence item", list(labels), key=f"{key}-{v['variant']}-item")
            ikey, item = labels[picked]
            verdict = st.radio("Mark", wb.VERDICTS, horizontal=True,
                               key=f"{key}-{v['variant']}-item-verdict")
            if st.button("Mark this item", key=f"{key}-{v['variant']}-item-go"):
                wb.add_mark(reviews, ikey, f"{v['variant']}: CIViC level "
                            f"{item.get('evidence_level', '?')}, {item.get('therapies', '')} "
                            f"({item.get('citation', '')})", verdict, by)
                st.rerun()
            st.caption(wb.mark_text(reviews.get(ikey)) or "no mark yet")


def render(file, events=None, evidence: dict | None = None, version: int | None = None,
           lookup=None, table=None) -> None:
    key = f"genomics-{file.id}-{'latest' if version is None else version}"  # widget keys
    month = None if version is None else file.versions[version].month
    events = wb.events_until(events, month)
    vs = wb.variants(file, events, evidence, lookup)
    queue, card, lon = wb.review_queue(vs), wb.data_card(), wb.longitudinal(file, events)
    strip, coverage = wb.provenance(file, events), wb.panel_coverage(file, events)
    cov = {c["gene"]: c["status"] for c in coverage}
    ladders = {v["variant"]: wb.ladder(v, wb.variant_resistance(v, table)) for v in vs}
    watch = wb.watchlist(file, version, table)
    reviews = st.session_state.setdefault("reviews", {})  # shared with the report page
    levels = sorted(v["strongest_level"] for v in vs if v["strongest_level"])

    st.subheader(f"Genomics workbench · {file.id}"
                 + (f" · as of {file.versions[version].label}" if version is not None else ""))
    if file.kind == "synthetic":
        st.warning(f"{file.title}. Not taken from any dataset; its record follows the "
                   "structure of real breast cancer timelines.")
    else:
        st.caption(file.title)
    st.markdown(" ".join([badge(wb.IMPLEMENTED), *(badge(f"{w}: planned", "gray")
                                                   for w, _ in wb.PLANNED_ROWS)]))

    # sample provenance strip
    for col, (k, val) in zip(st.columns([1, 1, 1, 2, 2, 3]), strip, strict=True):
        col.markdown(f"**{k}**  \n{val}")

    # overview
    row = st.container(horizontal=True)  # wraps on a narrow screen instead of cutting values
    row.metric("Variants observed", len(vs), width="content")
    row.metric("Strongest CIViC level", levels[0] if levels else "none", width="content")
    for name in queue:
        row.metric(name.capitalize(), len(queue[name]), width="content")
    if vs:
        strongest = _level_text(levels[0] if levels else None)
        st.markdown("Observed: " + ", ".join(f"**{esc(v['variant'])}**" for v in vs)
                    + f". Strongest evidence level present: {strongest}."
                    " CIViC items are evidence **for clinician review, never a recommendation**.")
    elif not lon["timepoints"]:
        st.info("Not sequenced: the mutation status of every panel gene is unknown, not wild type.")
    else:
        st.info("Sequenced: none of the panel's genes mutated (panel genes only; purity and depth "
                "unknown, so this is not proof of absence).")

    # variant browser with search, then the Spot panel of the selected row
    st.markdown("#### Variant browser")
    shown = []
    if vs:
        c1, c2, c3 = st.columns([2, 2, 2])
        query = c1.text_input("Search: a gene, \"level A\", \"resistance\", a therapy",
                              key=f"{key}-search")
        options = [_level_text(lv) for lv in dict.fromkeys(levels)] + (
            ["none"] if any(v["strongest_level"] is None for v in vs) else [])
        chosen = c2.multiselect("Strongest evidence level", options, default=options,
                                key=f"{key}-levels")
        mark_options = [*wb.VERDICTS, "unmarked"]
        marked = c3.multiselect("Review mark", mark_options, default=mark_options,
                                key=f"{key}-marked")
        if "reviewer" not in st.session_state:  # fallback: the shell's sidebar field is absent
            c3.text_input("Reviewer initials", key="genomics-reviewer", max_chars=5)

        def mark_of(v):
            return (reviews.get(wb.variant_key(file, v)) or {}).get("mark", "unmarked")

        hits = wb.search(vs, coverage, query)
        if hits["note"]:
            st.info(hits["note"][0].upper() + hits["note"][1:] + ": nothing is said about it, "
                    "not that it is wild type.")
        shown = [v for v in hits["variants"] if _level_text(v["strongest_level"]) in chosen
                 and mark_of(v) in marked]
        rows = [{"Gene": v["gene"], "Change": v["change"], "Sample": v["sample"],
                 "Month": "—" if v["month"] is None else v["month"],
                 "Strongest level": _level_text(v["strongest_level"]),
                 "CIViC items": len(v["interpretation"]["items"]),
                 "Resistance leads": sum(1 for r in ladders[v["variant"]][4]["items"])
                 + len(ladders[v["variant"]][4]["literature"]),
                 "Queue": next(q for q, names in queue.items() if v["variant"] in names),
                 "Mark": "" if mark_of(v) == "unmarked" else mark_of(v)} for v in shown]
        if rows:
            picked = st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                                  on_select="rerun", selection_mode="single-row",
                                  key=f"{key}-table")
            sel = picked.selection.rows
            st.caption("Click a row to open its Spot panel below.")
            v = shown[sel[0]] if sel else shown[0]
            _spot(file, v, ladders[v["variant"]], cov, strip, reviews, key)
        else:
            st.caption("No variant matches.")
    else:
        st.caption("No variant to browse.")

    # resistance watchlist
    st.markdown("#### Resistance watchlist")
    st.markdown(f"{badge(watch['evidence'])} **{watch['use']}** · for the treatments recorded in "
                f"this file: {', '.join(watch['treatments']) or 'none'}")
    if watch["rows"]:
        st.dataframe(pd.DataFrame(watch["rows"]).rename(columns={
            "under": "Under", "alteration": "What to watch", "finding": "Known from",
            "source": "Source", "url": "Source link", "level": "Evidence level",
            "detect": "Would be detected by"}), hide_index=True, width="stretch",
            column_config=LINK)
    if watch["note"]:
        st.caption(watch["note"].capitalize() + ".")
    st.caption("Sources: CIViC resistance items (civicdb.org, CC0) whose therapies include a "
               "recorded drug, and the trials cited in the platform's vision (PADA-1, SERENA-6). "
               "A watch item is never advice.")
    st.button("Open the Evolution view: what to watch next, ranked, with sources and the test "
              "that would detect it", key=f"{key}-evolution",
              on_click=lambda: st.session_state.update(view="Evolution"))

    # panel coverage
    st.markdown("#### Panel coverage")
    counts = pd.Series([c["status"] for c in coverage]).value_counts()
    st.markdown(" · ".join(f"{badge(s)} {n}" for s, n in counts.items()))
    st.dataframe(pd.DataFrame(coverage).rename(columns={"gene": "Gene", "status": "Status"}),
                 hide_index=True, width="stretch", height=200)
    st.caption("The 16 breast cancer driver genes of the TCGA panel (src/muffle/data/tcga.py). "
               "A gene that was not tested, or whose panel is not stated, is unknown: never read "
               "it as wild type.")

    # review queue
    st.markdown("#### Review queue")
    for col, (name, names) in zip(st.columns(3), queue.items(), strict=True):
        col.markdown(f"**{name.capitalize()}** ({len(names)})  \n{QUEUE_WHY[name]}")
        for n in names:
            v = next(x for x in vs if x["variant"] == n)
            col.markdown(f"- {esc(n)} · "
                         f"{wb.mark_text(reviews.get(wb.variant_key(file, v))) or 'no mark yet'}")
        if not names:
            col.caption("none")

    # longitudinal
    st.markdown("#### Over time")
    if lon["timepoints"]:
        st.dataframe(pd.DataFrame(lon["timepoints"]).rename(
            columns={"month": "Month", "sample": "Sample", "found": "Found"}),
            hide_index=True, width="stretch")
    statement = lon["statement"][0].upper() + lon["statement"][1:]
    st.markdown(f"{statement}. {badge('ctDNA: ' + lon['ctdna'], 'gray')}")

    # export
    st.markdown("#### Export")
    e1, e2 = st.columns(2)
    e1.download_button("Download the genomics report (Markdown)",
                       wb.report_markdown(file, vs, ladders, watch, reviews, strip),
                       f"genomics_{file.id.replace(' ', '_')}.md", "text/markdown",
                       key=f"{key}-md")
    e2.download_button("Download the variants and evidence items (CSV)",
                       wb.report_csv(file, vs, reviews),
                       f"genomics_{file.id.replace(' ', '_')}.csv", "text/csv", key=f"{key}-csv")

    # limits, data card, planned
    st.markdown(f"#### {CANNOT_SEE}")
    for limit in card["limits"]:
        st.markdown(f"- {limit}")
    st.markdown(f"#### {CARD}")
    rows = [("Status", card["status"]), ("Model", card["model"]),
            *((f"Data: {k}", v) for k, v in card["data"].items()),
            *((f"Label: {k}", v) for k, v in card["labels"].items()),
            ("Evidence levels", "; ".join(f"{k} {v}" for k, v in card["evidence_levels"].items()))]
    st.table(pd.DataFrame(rows, columns=["", "value"]).set_index(""))
    st.markdown("#### Planned, not results")
    st.dataframe(pd.DataFrame(card["planned"]).rename(
        columns={"what": "What", "note": "Note", "status": "Status"}),
        hide_index=True, width="stretch")


# ---------------------------------------------------------------- standalone page

EXAMPLE_CASE = SimpleNamespace(index=926, site="site-2", stage="III", age=55.0, percentile=99.0,
                               group="high", layers=["clinical", "genomic", "rna", "protein"],
                               missing=["methylation"],
                               mutations=["PIK3CA p.H1047R", "TP53 p.R175H"])


@st.cache_resource(show_spinner="Loading CIViC evidence (CC0, ~4 MB, once)...")
def _civic_table():
    """The CIViC nightly table, or None when it cannot load (the page still renders)."""
    from muffle.report import civic
    try:
        return civic.load_table()
    except Exception:
        return None


def main() -> None:
    from muffle.report import civic
    from muffle.workspace import case_file, synthetic_file
    st.set_page_config(page_title="Genomics workbench", layout="wide")
    tl = json.loads((APP / "timeline_synthetic.json").read_text(encoding="utf-8"))
    choice = st.radio("Example file", ["SYNTHETIC-001 (synthetic patient)",
                                       f"Case {EXAMPLE_CASE.index} (TCGA-BRCA public data)"],
                      horizontal=True)
    table = _civic_table()
    if table is None:
        st.caption("CIViC table not available on this machine: evidence items and resistance "
                   "items are not shown; the cited literature still is.")
    if choice.startswith("SYNTHETIC"):
        render(synthetic_file(tl), evidence=tl.get("evidence"), table=table)
    else:
        lookup = None if table is None else \
            (lambda gene, change: civic.evidence(gene, change, "breast", 3, table))
        render(case_file(EXAMPLE_CASE), lookup=lookup, table=table)


if __name__ == "__main__":
    main()

"""Tumor evolution and treatment evidence for one patient file: the Evolution view
(docs/evolution.md; docs/VISION.md parts two and three).

The patient file calls ``render(pf, version=None, lookup=None)`` with a
``muffle.workspace.PatientFile``: ``version`` is an index into ``pf.versions`` (the latest when
None) and ``lookup(row)`` returns the CIViC items for a table row (``muffle.evolution.civic_items``
on the loaded CIViC table), None when the table didn't load. It draws inside the current
container only. Sections: the record's events over time (observed), what to watch next
(hypotheses with their sources, search, review marks and pins), clonal order from allele
fractions (model inference, as alternatives), trials that mention the observed genes (live
registry, a dated snapshot when it can't be reached), the constraints with the method card, and
the export. Treatment content is evidence for clinician review, never advice. Standalone:

    streamlit run app/workbenches/evolution.py
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

APP = Path(__file__).resolve().parents[1]
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle import evolution  # noqa: E402
from muffle.report import trials  # noqa: E402
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED  # noqa: E402
from muffle.workbench.grammar import CANNOT_SEE, CARD, EXPORT, chip  # noqa: E402
from muffle.workspace import IMPLEMENTED, MARKS, PatientFile, finding_key  # noqa: E402

DOCS = "https://github.com/ps131-cell/muffle-plus-plus/blob/main/docs/evolution.md"
KIND_COLORS = {"diagnosis": "#8a8f98", "treatment": "#eb6834", "imaging": "#2a78d6",
               "sequencing": "#7b4fd6", "marker": "#1a9e8f", "alert": "#e34948"}
GRID = {"gridOpacity": 0.4, "domainOpacity": 0.4, "tickOpacity": 0.4}
REVIEW_MARKS = MARKS[1:]  # agree, disagree, second look; "reviewed" belongs to the SOS queue
PROVENANCE = (f"Data: this file's record (observed). Method: a table of {len(evolution.TABLE)} "
              f"rows from {len(evolution.SOURCES)} papers, each PMID and DOI checked against "
              f"PubMed on {evolution.VERIFIED}; only what each abstract reports; a fixed "
              "ordering rule; allele-fraction arithmetic for clonal order. No model is trained "
              "or run here. Status: implemented; the hypotheses are not validated predictions.")


def badge(text: str, color: str | None = None) -> str:
    return chip(text, color)


def esc(text: str) -> str:
    """Variant names carry Markdown characters ("TP53 R196*", "D96Gfs*15")."""
    return text.replace("*", r"\*").replace("_", r"\_")


def _mark(key: str, what: str, widget: str) -> None:
    """Store (or clear) a reviewer's mark in the workspace's shared store."""
    value, reviews = st.session_state.get(widget), st.session_state.setdefault("reviews", {})
    if value is None:
        reviews.pop(key, None)
    else:
        reviews[key] = {"what": what, "mark": value, "by": st.session_state.get("reviewer") or "",
                        "at": datetime.now().strftime("%Y-%m-%d %H:%M")}


def _pin(key: str, what: str) -> None:
    pins = st.session_state.setdefault("pins", {})
    if pins.pop(key, None) is None:
        pins[key] = what


def review_box(key: str, what: str) -> None:
    """Agree / disagree / second look and a pin for one finding, in a small popover; the marks
    join the patient file's review list and its report export."""
    h = hashlib.sha1(key.encode()).hexdigest()[:10]
    done = st.session_state.setdefault("reviews", {}).get(key)
    with st.popover(f"✓ {done['mark']}" if done else "Review",
                    help="Mark this finding; marks go into the report export"):
        st.segmented_control("Your mark", REVIEW_MARKS, key=f"evo-mark-{h}",
                             default=done["mark"] if done and done["mark"] in REVIEW_MARKS
                             else None, on_change=_mark, args=(key, what, f"evo-mark-{h}"))
        st.checkbox("Pin to the top of the report", key=f"evo-pin-{h}",
                    value=key in st.session_state.setdefault("pins", {}), on_change=_pin,
                    args=(key, what))
        if done:
            st.caption(f"{done['mark']} · {done['by'] or 'no initials'} · {done['at']}")


def events_chart(ev: list[dict], now: int | None) -> alt.Chart:
    df = pd.DataFrame(ev)
    x = alt.X("month:Q", title="months since the first tumor sequencing")
    y = alt.Y("lane:N", sort=evolution.LANES, title=None)
    color = alt.Color("kind:N", scale=alt.Scale(domain=list(KIND_COLORS),
                                                range=list(KIND_COLORS.values())),
                      legend=alt.Legend(orient="bottom", title=None, columns=6))
    tip = [alt.Tooltip("month:Q", title="month"), alt.Tooltip("what:N", title="observed"),
           alt.Tooltip("flag:N", title="flag or class"), alt.Tooltip("source:N", title="version"),
           alt.Tooltip("evidence:N", title="evidence")]
    points = alt.Chart(df).mark_point(filled=True, size=120, opacity=0.9).encode(
        x=x, y=y, color=color, tooltip=tip)
    # labels only where they carry the story (treatments, alerts, the sequenced driver), slanted
    # so that starts a few months apart don't overwrite each other; the rest is in the tooltip
    told = df[df["kind"].isin(["treatment", "alert", "sequencing"]) & (df["label"] != "")]
    labels = alt.Chart(told).mark_text(angle=330, align="left", dx=5, dy=-7, fontSize=10,
                                       color="#5f6368").encode(x=x, y=y, text="label:N")
    layers = [points, labels]
    if now is not None:
        layers.append(alt.Chart(pd.DataFrame({"month": [now]})).mark_rule(
            strokeDash=[4, 4], color="#8a8f98").encode(x="month:Q"))
    return alt.layer(*layers).properties(height=320).configure_axis(**GRID)


def vaf_chart(variants: list[dict]) -> alt.Chart:
    df = pd.DataFrame([{"variant": v["variant"], "vaf": v["vaf"], "lo": v["lo"], "hi": v["hi"],
                        "reads": f"{v['alt']} of {v['depth']}",
                        "copies": f"{v['copies_used']:g}" + ("" if v.get("copies") else
                                                             " (assumed)"),
                        "cells": f"at least {v['cells_at_least']:.0%} if on one copy"}
                       for v in variants])
    y = alt.Y("variant:N", sort=None, title=None)
    x = alt.X("lo:Q", title="allele fraction (95% interval)", scale=alt.Scale(domain=[0, 1]))
    tip = [alt.Tooltip("vaf:Q", title="allele fraction", format=".2f"),
           alt.Tooltip("lo:Q", title="95% low", format=".2f"),
           alt.Tooltip("hi:Q", title="95% high", format=".2f"),
           alt.Tooltip("reads:N", title="alt reads of depth"),
           alt.Tooltip("copies:N", title="copies of the gene (ASCAT3)"),
           alt.Tooltip("cells:N", title="tumor cells carrying it")]
    ref = alt.Chart(pd.DataFrame({"x": [0.5]})).mark_rule(strokeDash=[4, 4], color="#8a8f98")
    return alt.layer(
        alt.Chart(df).mark_rule(strokeWidth=3, color="#7b4fd6").encode(x=x, x2="hi:Q", y=y,
                                                                       tooltip=tip),
        alt.Chart(df).mark_point(filled=True, size=110, color="#7b4fd6").encode(
            x="vaf:Q", y=y, tooltip=tip),
        ref.encode(x="x:Q"),
    ).properties(height=40 + 36 * len(df)).configure_axis(**GRID)


def _matches(item: dict, q: str) -> bool:
    text = " ".join([item["event"], *item["genes"], *item["why"], item["detect"],
                     item["matters"], item["status"],
                     *(f"{e['says']} {e['source']['cite']} {e['source']['pmid']}"
                       for e in item["support"] + item["against"])])
    return q.lower() in text.lower()


def hypotheses(pf: PatientFile, hs: dict, key: str) -> None:
    st.markdown("#### What to watch next")
    st.caption(" ".join([badge(HYPOTHESIS), badge(IMPLEMENTED),
                         badge("for clinician review, never advice", "gray")]))
    st.caption(hs["rule"] + " Each item: why this file raises it, the frequency a cohort "
               "reported, the test that would detect it, when it would matter, and the evidence "
               "for and against, with PubMed links.")
    for note in hs["notes"]:
        st.info(note)
    query = st.text_input("Search: a gene, a drug class, a test or a source",
                          key=f"{key}-search", placeholder="e.g. ESR1, ctDNA, CDK4/6, Razavi")
    items = [it for it in hs["items"] if not query or _matches(it, query)]
    if query and not items:
        known = {g for row in evolution.TABLE for g in row["genes"]}
        st.info(f"No row of this table mentions {query!r}"
                + (": nothing is said about it here, which is not evidence that it doesn't "
                   "happen." if query.upper() not in known else
                   "; the table has rows for it, but none is raised for this file (see 'Not "
                   "raised' below)."))
    for n, it in enumerate(items, 1):
        lead = it["support"][0]["source"]
        with st.container(border=True):
            head, box = st.columns([7, 1])
            head.markdown(f"**{n}. {it['event']}** {badge(HYPOTHESIS)} "
                          + (badge("already observed", "blue") if it["status"].startswith(
                              "already") else ""))
            with box:
                review_box(it["key"], f"Evolution: {it['event']} ({lead['cite']})")
            st.markdown(f"**Why this file raises it:** {esc('; '.join(it['why']))}.  \n"
                        f"**Status:** {esc(it['status'])}.  \n"
                        f"**Reported frequency:** {it['frequency']}.  \n"
                        f"**Would be detected by:** {it['detect']}.  \n"
                        f"**When it would matter:** {it['matters']}.")
            with st.expander(f"Evidence: {len(it['support'])} for, {len(it['against'])} against "
                             f"or limits · strongest: {it['strength']}"):
                st.dataframe(pd.DataFrame([{
                    "Source": f"{e['source']['cite']}, {e['source']['journal']}",
                    "What the abstract reports": e["says"], "Cohort": e["cohort"],
                    "Frequency": e["frequency"], "PubMed": e["source"]["url"]}
                    for e in it["support"]]), hide_index=True, width="stretch",
                    column_config={"PubMed": st.column_config.LinkColumn(
                        display_text=r"PMID (\d+)")})
                for e in it["against"]:
                    st.markdown(f"- **Against or a limit** ({e['source']['cite']}, "
                                f"[PMID {e['source']['pmid']}]({e['source']['url']})): "
                                f"{e['says']}" + (" **Applies to this file.**"
                                                  if e["applies_here"] else ""))
                if not it["against"]:
                    st.caption("No contrary or limiting finding in these abstracts; that is not "
                               "proof that none exists.")
                civ = it["civic"]
                if civ is None:
                    st.caption("CIViC items: the CIViC table is not loaded here.")
                elif civ["items"]:
                    st.markdown(f"**CIViC items for this event** ({civ['total']} in breast "
                                "cancer; the strongest shown) · treatment evidence for clinician "
                                "review")
                    st.dataframe(pd.DataFrame(civ["items"]).rename(columns={
                        "molecular_profile": "Profile", "therapies": "Therapies",
                        "evidence_level": "Level", "significance": "Significance",
                        "direction": "Direction", "citation": "Citation", "url": "CIViC"}),
                        hide_index=True, width="stretch", column_config={
                            "CIViC": st.column_config.LinkColumn(display_text="item")})
                else:
                    st.caption("CIViC: no accepted item for this event in breast cancer.")
    with st.expander(f"Not raised for this file ({len(hs['not_raised'])} rows), and why"):
        st.dataframe(pd.DataFrame(hs["not_raised"]).rename(
            columns={"id": "Row", "event": "Event", "reason": "Why not raised"}),
            hide_index=True, width="stretch")


def clonal(panel: dict) -> None:
    st.markdown("#### Clonal order from allele fractions")
    st.caption(" ".join([badge(INFERENCE), badge(IMPLEMENTED)]))
    if "variants" not in panel:
        st.info(f"{panel['status'][0].upper()}{panel['status'][1:]}. Clonal order needs allele "
                "fractions; repeated samples over time would make it far more reliable.")
        return
    st.markdown(f"**{panel['status'].capitalize()}.** One tumor sample: each driver's share of "
                "reads, with its 95% interval. A higher fraction suggests more cells, so an "
                "earlier mutation, only under the assumptions below; the orderings consistent "
                "with them are listed as alternatives, never one tree.")
    st.altair_chart(vaf_chart(panel["variants"]), width="stretch")
    st.caption("Dashed line: 0.5, a heterozygous mutation in every cell of a pure tumor with "
               "two copies of the gene. Purity is unknown here, so no variant is called clonal.")
    if panel["pairs"]:
        st.dataframe(pd.DataFrame([{
            "Higher": p["a"], "Lower": p["b"], "Relation": p["relation"], "Why": p["why"],
            "Consistent alternatives": " | ".join(p["alternatives"])} for p in panel["pairs"]]),
            hide_index=True, width="stretch")
        st.markdown("**Orderings consistent with these numbers** (alternatives, not a tree)\n"
                    + "\n".join(f"- {esc(o)}" for o in panel["orderings"]))
    else:
        st.caption("One driver call: nothing to order.")
    if panel.get("missing"):
        st.caption("No read counts for: " + esc(", ".join(panel["missing"])) + ".")
    st.caption(f"Assumptions: {panel['assumptions']}. Source: {panel['source']}.")


@st.cache_data(ttl=3600, show_spinner="Checking ClinicalTrials.gov…")
def trial_rows(genes: list[str]) -> tuple[list[dict], list[dict]]:
    """One row per trial (a trial mentioning two genes appears once) and one result per gene;
    cached for an hour in the process on top of trials' day-long disk cache."""
    results = [trials.studies(g) for g in genes]
    rows: dict[str, dict] = {}
    for r in results:
        for s in r["studies"]:
            row = rows.setdefault(s["nct"], {**s, "mentions": []})
            row["mentions"].append(r["term"])
    return [{**r, "mentions": ", ".join(r["mentions"])} for r in rows.values()], results


def trials_section(pf: PatientFile, genes: list[str], rows: list[dict], results: list[dict],
                   key: str) -> None:
    st.markdown("#### Trials that mention this patient's observed markers")
    st.caption(" ".join([badge(HYPOTHESIS), badge(IMPLEMENTED),
                         badge("for clinician review; eligibility is not assessed here",
                               "gray")]))
    if not genes:
        st.info("No observed driver in this file: no trial query is made (queries use observed "
                "gene names only).")
        return
    for r in results:
        found = ("count unknown" if r["total"] is None else
                 "no recruiting or not yet recruiting breast cancer trial mentions it"
                 if r["total"] == 0 else
                 f"{r['total']} recruiting or not yet recruiting breast cancer trials mention it, "
                 f"{len(r['studies'])} shown in the registry's relevance order")
        st.markdown(f"- **{r['term']}**: {found} · {r['note']} · [the same search on "
                    f"ClinicalTrials.gov]({trials.search_url(r['gene'])})")
    if rows:
        st.dataframe(pd.DataFrame([{
            "Trial": f"https://clinicaltrials.gov/study/{t['nct']}", "Title": t["title"],
            "Phase": t["phase"], "Status": t["status"], "Mentions": t["mentions"],
            "Interventions": ", ".join(t["interventions"][:4])
            + (" …" if len(t["interventions"]) > 4 else ""),
            "Countries": ", ".join(t["countries"][:4])
            + (f" +{len(t['countries']) - 4}" if len(t["countries"]) > 4 else ""),
            "Last update": t["updated"]} for t in rows]), hide_index=True, width="stretch",
            column_config={"Trial": st.column_config.LinkColumn(display_text=r"(NCT\d+)")})
        pick = st.selectbox("Mark or pin a trial", [f"{t['nct']} · {t['title']}" for t in rows],
                            index=None, key=f"{key}-trial", placeholder="Choose a trial")
        if pick:
            nct = pick.split(" · ")[0]
            review_box(finding_key(pf, "evolution", "trial", nct), f"Trial {pick}")
    stamp = next((r.get("data_timestamp") for r in results if r.get("data_timestamp")), "")
    st.caption("Source: ClinicalTrials.gov (U.S. National Library of Medicine), API v2"
               + (f"; data processed by ClinicalTrials.gov on {stamp[:10]}" if stamp else "")
               + ". Query: the condition 'breast cancer', the term '<GENE> mutation' for each "
                 "observed gene, statuses recruiting or not yet recruiting; only these fields "
                 "are shown. A trial that mentions a gene is not a match: eligibility is not "
                 "assessed here. The registry today, not as of the report version shown.")


def method_card() -> None:
    st.markdown(f"#### {CANNOT_SEE}")
    st.markdown("Copy number beyond the gene level, purity, subclones in other places, anything "
                "after the last sample; whether a treatment will work. Nothing here is a "
                "recommendation or a regimen.")
    with st.expander(f"{CARD}: the constraints this view applies and how the table was built"):
        for c in evolution.CONSTRAINTS:
            refs = ", ".join(f"[{evolution.source(s)['cite']}]({evolution.source(s)['url']})"
                             for s in c["sources"])
            st.markdown(f"- **{c['rule']}.** {c['text']}" + (f" ({refs})" if refs else ""))
        st.markdown(
            f"**The table** ({len(evolution.TABLE)} rows, {len(evolution.SOURCES)} papers): each "
            "row is a context (a recorded treatment class, a receptor status, an observed "
            "driver) and an event known to follow it, with what each source's abstract reports "
            "(cohort and frequency included), the test that would detect it and when it would "
            f"matter. Every PMID and DOI was checked against PubMed on {evolution.VERIFIED}; a "
            "row whose source could not be verified was dropped. CIViC items (CC0) are matched "
            "to each event by its molecular profile. The full table with references: "
            f"[docs/evolution.md]({DOCS}).")


def render(pf: PatientFile, version: int | None = None, lookup=None) -> None:
    last = len(pf.versions) - 1
    i = last if version is None else version
    v, key = pf.versions[i], f"evolution-{pf.id}-{i}"
    hs = evolution.hypothesis_set(pf, i, lookup)
    panel, ev = evolution.clonal_panel(pf, i), evolution.events(pf, i)
    genes = list(hs["context"]["drivers"])
    rows, results = trial_rows(genes)

    st.subheader(f"Tumor evolution and treatment evidence · {pf.id}"
                 + ("" if i == last else f" · as of {v.label}"))
    if pf.kind == "synthetic":
        st.warning(f"{pf.title}. Its record exists to show how this view reads a history.")
    st.caption(" ".join([badge(IMPLEMENTED), badge(OBSERVED), badge(INFERENCE),
                         badge(HYPOTHESIS)]) + "  \n" + PROVENANCE)

    ctx = hs["context"]
    treated = ", ".join(f"{t['agent']} (month {t['month']})" for t in ctx["treatments"])
    st.markdown(
        f"{badge(OBSERVED)} "
        + (f"{len(ev)} dated events" if ev else "One timepoint, no dated events")
        + "; drivers " + (esc(", ".join(d for d, _ in ctx["drivers"].values()))
                          or "none observed")
        + f"; {evolution.receptor_text(ctx['receptors'])}; treatments: {treated or 'none recorded'}"
        + f".  \n{badge(INFERENCE)} Clonal order: {panel['status']}."
        + f"  \n{badge(HYPOTHESIS)} {len(hs['items'])} things to watch; "
        f"{len(hs['not_raised'])} rows of the table not raised for this file."
        + ("  \n**What would settle the first ones:** " + "; ".join(
            f"{it['event']} → {it['detect'].split(';')[0]}" for it in hs["items"][:2])
            if hs["items"] else ""))

    st.markdown("#### The record over time")
    st.caption(" ".join([badge(OBSERVED), badge(IMPLEMENTED)]))
    if ev:
        st.altair_chart(events_chart(ev, v.month), width="stretch")
        st.caption("Every point is observed in the record; hover for the text. Red: an alert "
                   "(progression, a new site, a marker rise). The dashed line is this report "
                   "version. Treatment starts only: the record holds no stop dates.")
    else:
        st.info(pf.note + " Its driver calls, where sequenced, come from that one sample.")

    hypotheses(pf, hs, key)
    clonal(panel)
    trials_section(pf, genes, rows, results, key)
    method_card()

    when = "baseline" if v.month is None else f"month{v.month}"
    st.markdown(f"#### {EXPORT}")
    st.download_button(
        "Download the evolution view (Markdown)",
        evolution.report_markdown(pf, i, hs, panel, rows, "; ".join(
            f"{r['term']}: {r['source']}, {r['note']}" for r in results) or "no query",
            st.session_state.get("reviews")),
        file_name=f"evolution_{pf.id.replace(' ', '_')}_{when}.md", mime="text/markdown",
        key=f"{key}-md",
        help="What to watch with sources, the clonal panel, trials with their date, the "
             "constraints and your review marks.")


def methods_card() -> None:
    """This view's card on the Methods and validation page."""
    snap = trials.load_snapshot()
    st.subheader("Tumor evolution and treatment evidence")
    st.markdown(f"{badge(IMPLEMENTED)} · hypotheses for clinician review, not validated "
                "predictions · the Evolution view of every patient file")
    st.markdown(
        f"- **The table:** {len(evolution.TABLE)} rows of context → event (ESR1 under aromatase "
        "inhibitors, RB1, FAT1, AKT1 and PTEN under CDK4/6 inhibitors, PTEN under PI3Kα "
        "inhibitors, BRCA1/2 reversion, receptor conversion and others) from "
        f"{len(evolution.SOURCES)} papers. Each PMID and DOI was checked against PubMed (NCBI "
        f"E-utilities) on {evolution.VERIFIED} and each statement is what the abstract reports, "
        f"cohort and frequency included; a row whose source could not be verified was dropped "
        f"([docs/evolution.md]({DOCS})).\n"
        "- **What to watch next:** the rows a file raises from its recorded treatments, "
        "receptor status and observed drivers, ordered by a fixed rule (how much of the row's "
        "context the file shows, then the most recent matching treatment, then the strength of "
        "the evidence), each with its evidence for and against. A cohort's frequency is never "
        "this patient's probability; nothing is worded as advice.\n"
        "- **Clonal order:** allele fractions of the TCGA cases' driver calls (GDC open-access "
        "read counts) with 95% Wilson intervals and the gene's copy number (ASCAT3); assuming "
        "each mutation sits on one copy, two whose cell-fraction lower bounds sum past 100% "
        "must share a lineage. Purity is unknown, so no variant is called clonal, and the "
        "consistent orderings are shown as alternatives.\n"
        "- **Trials:** ClinicalTrials.gov API v2, the term '<GENE> mutation' with 'breast "
        "cancer', recruiting or not yet recruiting, cached for a day; the bundled snapshot of "
        f"{snap.get('snapshot', 'no date')} answers when the registry can't be reached. Only "
        "gene names are sent. Eligibility is not assessed.\n"
        "- **Not validated:** whether the listed events occur in a given patient has not been "
        "checked against outcomes; the table is literature, not a model.")


# ---------------------------------------------------------------- standalone page

EXAMPLE_CASE = SimpleNamespace(  # case 43 as the release bundle demo-bundle-v2 holds it
    index=43, site="site-2", stage="II", age=67.0, percentile=73.4, group="high",
    layers=["genomic", "rna", "protein", "clinical"], missing=["methylation"],
    mutations=["PIK3CA p.G1049R", "RUNX1 p.D96Gfs*15", "TP53 p.R196*"])


def main() -> None:
    from muffle.workspace import case_file, synthetic_file
    st.set_page_config(page_title="Tumor evolution", layout="wide")
    tl = json.loads((APP / "timeline_synthetic.json").read_text(encoding="utf-8"))
    choice = st.radio("Example file", ["SYNTHETIC-001 (synthetic patient)",
                                       f"Case {EXAMPLE_CASE.index} (TCGA-BRCA public data)"],
                      horizontal=True)
    render(synthetic_file(tl) if choice.startswith("SYNTHETIC") else case_file(EXAMPLE_CASE))


if __name__ == "__main__":
    main()

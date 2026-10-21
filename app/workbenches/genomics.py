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

Behind the overview, the tumor's genome as a picture (``muffle.workbench.genome``): the
copy-number landscape with a Spot panel per gene, mutation burden and allele fractions, the
predicted effect of each variant, a curated pathway map and the variants over time. ``case`` (a
``muffle.demo.Case``) and ``demo`` (the loaded bundle) are optional: with them the precomputed
numbers are matched to the case by its log-risk and the gene Spot panel shows the expression
workbench's RNA and protein percentiles.

Everything shown is observed (a sequenced mutation, a copy number, a read count), model inference
(an AlphaMissense score, an expected allele fraction) or a hypothesis (a CIViC item, a ClinVar
classification, a pathway grouping, a literature lead, for clinician review, never a
recommendation); every cutoff names its source; planned parts are shown as planned rows, never as
results. Review marks go to the shared ``st.session_state.reviews``
store under ``muffle.workspace.finding_key`` names (kind "variant" with the variant and the
sequencing month, kind "civic" with the variant and the item's URL, kind "cn" with a gene, kind
"pathway" with a pathway's name), so the report page's export
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

import altair as alt  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402

from muffle.report import vep  # noqa: E402
from muffle.report.case_tools import HYPOTHESIS, INFERENCE  # noqa: E402
from muffle.report.civic import LEVELS  # noqa: E402
from muffle.workbench import genome as gx  # noqa: E402
from muffle.workbench import genomics as wb  # noqa: E402
from muffle.workbench import omics as om  # noqa: E402
from muffle.workbench.grammar import CANNOT_SEE, CARD, chip, esc  # noqa: E402
from muffle.workspace import finding_key  # noqa: E402

# page-specific colors; statuses and evidence types take the shared grammar's
COLORS = {wb.FOUND: "blue", wb.NOT_FOUND: "green", wb.NOT_TESTED: "gray", "derived": "blue",
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
          key: str, ef: dict | None = None, af: dict | None = None) -> None:
    """The Spot panel of one variant: the three evidence types side by side (detected,
    interpreted, predicted), ladder, CIViC table, the panel's view of the gene, the sample, the
    review marks."""
    st.markdown(f"### Spot: {esc(v['variant'])} · {v['sample']}"
                + (f" · month {v['month']}" if v["month"] is not None else ""))
    items = v["interpretation"]["items"]
    if ef is not None:
        _three_kinds(v, ef, af)
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


# ---------------------------------------------------------------- the genome as a picture

CALL_COLORS = {"deep deletion": "#1f4e9c", "loss": "#7fa7dd", "neutral": "#b8b8b8",
               "gain": "#f2a07b", "amplification": "#c8362b"}
NODE_COLORS = {"mutated": "#7b3fa0", "amplification": "#c8362b", "deep deletion": "#1f4e9c",
               "gain": "#f2a07b", "loss": "#7fa7dd", "not altered": "#d9d9d9",
               "not measured": "#ffffff"}
TAG_COLORS = {gx.DEFINITION: "blue", gx.LITERATURE: "green", gx.PLACEHOLDER: "orange",
              gx.METHOD: "gray", INFERENCE: "violet", HYPOTHESIS: "orange",
              "interpretation": "orange"}
EVIDENCE_LEGEND = (f"{badge('observed', 'blue')} measured · {badge('derived', 'blue')} arithmetic "
                   f"on a measurement · {badge(INFERENCE, 'violet')} a model or rule's estimate · "
                   f"{badge('hypothesis', 'orange')} interpretation or lead, for clinician review "
                   f"· cutoffs: {badge('definition', 'blue')} {badge('literature', 'green')} "
                   f"{badge('placeholder', 'orange')} (placeholders are drawn dashed)")


@st.cache_data(show_spinner=False)
def _genome_files() -> tuple:
    """genomics_cn.json, genomics_effect.json, omics_scores.json and evolution_vaf.json, or None
    for a file that is missing (the page still renders)."""
    return (gx.load(gx.CN_JSON), gx.load(gx.EFFECT_JSON), gx.load(APP / "omics_scores.json"),
            gx.load(APP / "evolution_vaf.json"))


@st.cache_data(ttl=24 * 3600, show_spinner=False)
def _live_effects(names: tuple) -> dict:
    """Ensembl VEP for variants the snapshot lacks (an imported result), by name only; {} when
    Ensembl can't be reached."""
    return vep.lookup(list(names))


def _genome(file, case) -> dict:
    data, effects, omics_scores, vaf = _genome_files()
    block = gx.case_block(data, file, getattr(case, "log_risk", None))
    i = gx.case_index(file)
    reads_case = ((vaf or {}).get("cases") or {}).get(str(i)) if block else None
    reads = {r["variant"]: r for r in (reads_case or {}).get("variants", [])}
    rows = gx.landscape(block, data["genes"]) if block and block.get("cn") else []
    return {"data": data, "block": block, "rows": rows, "effects": effects,
            "omics": omics_scores, "reads": reads or None,
            "afs": gx.allele_fractions(block, reads_case), "stale": i is not None and not block
            and bool((data or {}).get("cases", {}).get(str(i)))}


def _effects(snapshot: dict | None, names: tuple) -> dict:
    """The snapshot, with a live Ensembl lookup added for variants it lacks."""
    known = (snapshot or {}).get("variants", {})
    missing = tuple(n for n in names if n not in known)
    live = _live_effects(missing) if missing else {}
    out = dict(snapshot or {"snapshot": "not taken", "variants": {}})
    out["variants"] = {**known, **{n: {**e, "live": True} for n, e in live.items()}}
    return out


def _three_kinds(v: dict, ef: dict, af: dict | None) -> None:
    """Detected, interpreted and predicted side by side, never merged."""
    c1, c2, c3 = st.columns(3)
    with c1:
        st.markdown(f"**Detected** {badge('observed')}")
        if af and af.get("lo") is not None:
            st.markdown(f"- {af['class']}; allele fraction **{af['vaf']:.1%}** (95% "
                        f"{af['lo']:.1%}–{af['hi']:.1%}; {af['alt']} of {af['depth']} reads)")
            pur = (f"purity {af['purity']:.0%} (ABSOLUTE)" if af["purity"] else "purity unknown")
            st.markdown(f"- {af['copies']:g} copies of {v['gene']} · {pur}" if af.get("copies")
                        is not None else f"- {pur}")
            st.caption(f"Clonal fit {badge(INFERENCE)}: {af['fit']}")
        else:
            st.markdown(f"- {v['detection']['allele_fraction']}")
        if ef["found"]:
            a = ef["annotation"]
            st.markdown(f"- {(a['consequence'] or '?').replace('_', ' ')} · `{a['hgvsp'] or ''}` "
                        f"on {a['transcript'] or 'the canonical transcript'} (Ensembl VEP)")
    with c2:
        st.markdown(f"**Interpreted** {badge('hypothesis')}")
        lv = v["strongest_level"]
        st.markdown(f"- CIViC: {len(v['interpretation']['items'])} item(s), strongest "
                    f"{_level_text(lv)}")
        if ef["found"]:
            t = gx.effect_text(ef)
            st.markdown(f"- ClinVar: {t['interpretation']}")
        st.caption("For clinician review, never a recommendation.")
    with c3:
        st.markdown(f"**Predicted** {badge(INFERENCE)}")
        if ef["found"]:
            p = ef["prediction"]
            st.markdown("- " + (f"AlphaMissense **{p['score']:.3f}**, {p['class']}"
                                if p["score"] is not None else
                                "AlphaMissense: not applicable (missense changes only)"
                                if not p["applies"] else "AlphaMissense: no score"))
            st.caption(gx.AM_LIMITS)
        else:
            st.markdown(f"- {ef['note']}")
    st.caption(f"Effect snapshot {ef['snapshot']}"
               + (" · this variant looked up live at Ensembl" if ef.get("live") else ""))


def _marks(reviews: dict, fkey: str, what: str, key: str) -> None:
    by = st.session_state.get("reviewer") or st.session_state.get("genomics-reviewer", "")
    st.markdown(f"**Review marks** · {wb.mark_text(reviews.get(fkey)) or 'no mark yet'}")
    cols = st.columns(len(wb.VERDICTS) + 1)
    for col, verdict in zip(cols, wb.VERDICTS, strict=False):
        if col.button(verdict.capitalize(), key=f"{key}-{verdict}"):
            wb.add_mark(reviews, fkey, what, verdict, by)
            st.rerun()
    if reviews.get(fkey) and cols[-1].button("Clear mark", key=f"{key}-clear"):
        wb.add_mark(reviews, fkey, "", None)
        st.rerun()


def _rna_protein(case, demo, omics_scores: dict | None, genes: list[str]) -> dict:
    """The expression workbench's view of ``genes``: RNA and protein cohort percentiles from the
    model's inputs and the shipped quantiles (no recomputation of its scores)."""
    if case is None or demo is None or not omics_scores:
        return {}
    x, _ = demo.inputs(case)
    quant = omics_scores.get("quantiles", {})
    antibody = {g: a for g, a in om.RECEPTORS.values()}
    out = {}
    for g in genes:
        r = {}
        for layer, name in (("rna", g), ("protein", antibody.get(g, g))):
            names = demo.names.get(layer) or []
            if layer in case.layers and name in names and name in quant.get(layer, {}):
                value = float(x[layer][0, names.index(name)])
                r[layer] = (name, round(om.percentile(value, quant[layer][name])))
        if r:
            out[g] = r
    return out


def _picked(ev, param: str, state: str) -> None:
    """A gene clicked on a chart becomes ``st.session_state[state]``, once per click: a choice
    made afterwards elsewhere (the gene box) is not overridden by the chart's standing
    selection."""
    sel = ((ev or {}).get("selection") or {}).get(param) if ev else None
    gene = sel[0].get("gene") if isinstance(sel, list) and sel else None
    if gene and st.session_state.get(f"{state}-clicked") != gene:
        st.session_state[state] = gene
    st.session_state[f"{state}-clicked"] = gene


def _cn_chart(rows: list[dict]) -> alt.LayerChart:
    df = pd.DataFrame([{**r, "y": max(-2.6, min(2.6, r["log2"])) if r["log2"] is not None
                        else None, "pathways": ", ".join(r["pathways"]) or "none",
                        "layer": "model input" if r["in_layer"] else "not a model input",
                        "pct_text": "unknown" if r["pct"] is None else gx._pct(r["pct"]),
                        "share_text": "" if r["share"] is None else f"{r['share']:.0%}"}
                       for r in rows if r["copies"] is not None])
    chroms = df.groupby("chrom", sort=False).agg(lo=("rank", "min"), hi=("rank", "max"))
    chroms = chroms.reset_index().assign(mid=lambda d: (d["lo"] + d["hi"]) / 2,
                                         shade=lambda d: d.index % 2 == 0)
    sel = alt.selection_point(name="gene", fields=["gene"], on="click", clear="dblclick",
                              nearest=True)
    x = alt.X("rank:Q", axis=None, scale=alt.Scale(domain=[-1, len(df)]))
    bands = alt.Chart(chroms[chroms["shade"]]).mark_rect(opacity=0.07, color="gray").encode(
        x=alt.X("lo:Q", axis=None), x2="hi:Q")  # every layer hides x: mixed axes break Vega-Lite
    labels = alt.Chart(chroms).mark_text(dy=-4, fontSize=10, color="gray").encode(
        x=alt.X("mid:Q", axis=None), y=alt.value(0), text="chrom:N")
    tip = [alt.Tooltip("gene:N", title="gene"), alt.Tooltip("chrom:N", title="chromosome"),
           alt.Tooltip("start_mb:Q", title="position (Mb)"), alt.Tooltip("copies:Q"),
           alt.Tooltip("ploidy:Q", title="ploidy estimate"),
           alt.Tooltip("call_text:N", title="call (rule)"),
           alt.Tooltip("pct_text:N", title="cohort percentile"),
           alt.Tooltip("share_text:N", title="cohort with the same call"),
           alt.Tooltip("layer:N", title="model"), alt.Tooltip("pathways:N")]
    points = alt.Chart(df).mark_point(filled=True).encode(
        x=x, y=alt.Y("y:Q", title="copies relative to ploidy (log2)",
                     scale=alt.Scale(domain=[-2.7, 2.7])),
        color=alt.Color("call_text:N", title="call", scale=alt.Scale(
            domain=list(CALL_COLORS), range=list(CALL_COLORS.values()))),
        size=alt.condition("datum.interest", alt.value(110), alt.value(28)),
        opacity=alt.condition(sel, alt.value(1.0), alt.value(0.3)),
        tooltip=tip).add_params(sel)
    names = alt.Chart(df[df["interest"] | df["call"].isin([2, -2]) & (df["pathways"] != "none")]
                      ).mark_text(dy=-10, fontSize=10).encode(x=x, y="y:Q", text="gene:N")
    ploidy = alt.Chart(pd.DataFrame({"y": [0.0]})).mark_rule(color="gray").encode(y="y:Q")
    amp = alt.Chart(pd.DataFrame({"y": [1.0], "t": ["amplification: ≥ 2× ploidy (placeholder)"]}))
    amp = amp.mark_rule(color="#c8362b", strokeDash=[6, 4]).encode(y="y:Q") + amp.mark_text(
        align="left", dx=4, dy=10, fontSize=10, color="#c8362b").encode(x=alt.value(0), y="y:Q",
                                                                         text="t:N")
    return (bands + ploidy + amp + points + names + labels).properties(height=320)


def _gene_spot(file, gene: str, g: dict, vs: list[dict], table, omics_view: dict,
               reviews: dict, key: str) -> None:
    """The Spot panel of one gene: copy number, call and its cutoff, percentile, neighbors, the
    CIViC items for its copy-number change, the expression workbench's view, its pathway, the
    observed variants in it, review marks."""
    rows = g["rows"]
    r = next((x for x in rows if x["gene"] == gene), None)
    st.markdown(f"### Spot: {gene}" + (f" · chr{r['chrom']} {r['start_mb']:.2f} Mb" if r else ""))
    if r is None or r["copies"] is None:
        st.info(f"No copy number for {gene} in this file: unknown, not normal.")
    else:
        c1, c2, c3 = st.columns(3)
        c1.metric("Copies (observed)", f"{r['copies']:g}", help="ASCAT3, gene level")
        c2.metric("Call (rule)", r["call_text"], help="relative to the ploidy estimate "
                  f"{r['ploidy']:g}; cutoffs in the method card")
        c3.metric("Cohort percentile", "—" if r["pct"] is None else gx._pct(r["pct"]),
                  help="copies relative to ploidy, among this cohort's tumors (ties split)")
        cut = {c["name"]: c for c in gx.CUTOFFS}.get(r["call_text"])
        if cut:
            st.markdown(f"Cutoff: {r['call_text']} = {cut['rule']} "
                        f"{badge(cut['tag'], TAG_COLORS.get(cut['tag']))} · {cut['source']}")
        if r["share"] is not None:
            st.caption(f"{r['share']:.0%} of the cohort's tumors share this call · "
                       + ("one of the model's copy-number inputs" if r["in_layer"] else
                          "not a model input (shown for the breast drivers and the pathway map)"))
        nb = gx.neighbors(rows, gene)
        if nb["near"]:
            st.markdown(f"**Neighbors** · {nb['same']} of {len(nb['near'])} measured genes within "
                        f"{nb['window_mb']:g} Mb share the call: "
                        + ", ".join(f"{n['gene']} ({n['call_text']})" for n in nb["near"][:12]))
            st.caption("What to check by eye: a broad (arm-level) change versus a focal one; the "
                       "segments would settle it, only gene-level values are here.")
    items = gx.cn_items(gene, None if r is None else r["call"], table)
    st.markdown(f"**CIViC items for {gene} copy-number changes** {badge('hypothesis')} · breast "
                "cancer, for clinician review")
    if items["items"]:
        df = pd.DataFrame(items["items"]).rename(columns={
            "molecular_profile": "Profile", "therapies": "Therapies", "evidence_level": "Level",
            "significance": "Significance", "direction": "Direction", "citation": "Citation",
            "url": "CIViC", "matches_call": "Matches this call"})
        st.dataframe(df, hide_index=True, width="stretch", column_config=LINK)
        if items["total"] > len(items["items"]):
            st.caption(f"{items['total']} items in all; the strongest levels first.")
    else:
        st.caption("None in the loaded CIViC table." if table is not None else
                   "CIViC table not loaded on this machine.")
    ov = omics_view.get(gene, {})
    st.markdown("**The expression workbench's view**")
    if ov:
        bits = [f"RNA at the {gx._pct(ov['rna'][1])} of the cohort" if "rna" in ov else
                "RNA not among the model's 1,000 genes",
                f"protein ({om.ANTIBODY_NAMES.get(ov['protein'][0], ov['protein'][0])}, RPPA) at "
                f"the {gx._pct(ov['protein'][1])}" if "protein" in ov else
                "no RPPA antibody for it among the model's 100"]
        st.markdown(f"{badge('observed')} " + "; ".join(bits) + ". RNA is not protein, and a "
                    "gained gene need not be expressed.")
    else:
        st.caption("Not in the expression or protein layers the model reads for this file (or "
                   "the file has none): the expression workbench can't say.")
    pws = [p for p, pw in gx.PATHWAYS.items() if gene in pw["genes"]]
    st.markdown("**Pathway map** · " + (", ".join(pws) + " (hypothesis: a grouping with sources)"
                                        if pws else "not on the curated pathway map"))
    mine = [v["variant"] for v in vs if v["gene"] == gene]
    st.markdown("**Observed variants in this gene** · " + (", ".join(mine) or "none in this "
                                                           "sample's sequencing"))
    if r is not None:
        _marks(reviews, finding_key(file, "cn", gene), f"{gene} copy number: {r['call_text']} "
               f"({r['copies']:g} copies at ploidy {r['ploidy']:g})", f"{key}-cn-{gene}")


def _genome_sections(file, version, vs, g, effects, table, case, demo, reviews, key) -> dict:
    """Copy number, burden and allele fractions, predicted effect, pathway map; returns what the
    rest of the page reuses (the longitudinal table, exports)."""
    from muffle import evolution, timeline

    block, afs = g["block"], g["afs"]
    if block and block.get("absolute") and st.session_state.get(f"{key}-ploidy", "").startswith(
            "ABSOLUTE"):  # the reader chose calls relative to ABSOLUTE's ploidy
        g = {**g, "rows": gx.landscape(block, g["data"]["genes"], block["absolute"]["ploidy"])}
    rows = g["rows"]
    names = [v["variant"] for v in vs]
    sequenced = any(t.workbench == "mutations" for t in file.tests)
    bur = gx.burden(block, g["data"])
    if not block and sequenced:
        bur = {"measured": False, "note": "the sequencing report gives no call count: the burden "
                                          "is unknown"}
    nodes = gx.pathway_map(names, rows, sequenced)
    ctdna = getattr(timeline, "CTDNA", None) if file.kind == "synthetic" else None
    lon = gx.longitudinal_table(file, version, ctdna, {a["variant"]: a["vaf"] for a in afs})
    if ctdna:  # where a blood-only variant comes from, by the ctDNA monitor's own rule
        from muffle.workbench import ctdna as cw
        month = None if version is None else file.versions[version].month
        seq = cw.tumor_sequencing(wb.events_until(None, month))
        lon["origins"] = {r["variant"]: cw.origin(r["variant"], seq)["origin"]
                          for r in lon["rows"] if r["variant"] in ctdna.get("variants", ())}
    hs = evolution.hypothesis_set(file, version)
    altered = [r["gene"] for r in rows if r["call"] in gx.ALTERED]
    omics_view = _rna_protein(case, demo, g["omics"], list(dict.fromkeys(
        altered + list(gx.INTEREST) + list(gx.PATHWAY_GENES))))
    gene_key = f"{key}-gene"
    out = {"rows": rows, "bur": bur, "nodes": nodes, "lon": lon, "hs": hs, "ctdna": bool(ctdna)}

    st.markdown("#### The tumor's genome")
    st.markdown(EVIDENCE_LEGEND)
    if g["stale"]:
        st.warning("The precomputed genome numbers were made for another build of the cases and "
                   "are not shown for this file.")
    q = st.text_input("Search the genome: \"amplified\", a gene, \"PI3K pathway\", \"high burden\"",
                      key=f"{key}-gsearch")
    hit = gx.search(q, rows, nodes, bur, names)
    if q:
        if hit["genes"]:
            st.markdown("Genes: " + ", ".join(f"**{x}**" for x in hit["genes"]))
            if st.session_state.get(gene_key) not in hit["genes"]:
                st.session_state[gene_key] = hit["genes"][0]
        if hit["pathways"]:
            st.markdown("Pathways: " + ", ".join(f"**{p}**" for p in hit["pathways"]) + " · see "
                        "the pathway map")
            st.session_state[f"{key}-pathway"] = hit["pathways"][0]
        if hit["burden"] and hit["burden"].get("measured"):
            st.markdown(f"Burden: {hit['burden']['text']}.")
        if hit["note"]:
            st.info(hit["note"][0].upper() + hit["note"][1:] + ".")

    t_cn, t_bur, t_eff, t_path = st.tabs(["Copy-number landscape", "Burden and allele fractions",
                                          "Predicted effect", "Pathway map"])
    with t_cn:
        _cn_view(file, g, vs, table, omics_view, reviews, key, gene_key)
    with t_bur:
        _burden_view(bur, afs, g["data"], sequenced, file)
    with t_eff:
        _effect_view(vs, effects, afs)
    with t_path:
        _pathway_view(file, nodes, g, vs, table, omics_view, reviews, key, gene_key, sequenced)
    return out


def _cn_view(file, g, vs, table, omics_view, reviews, key, gene_key) -> None:
    rows, block = g["rows"], g["block"]
    if not rows:
        st.info("No copy number for this file: "
                + ("the record's sequencing reported variants only." if file.kind == "synthetic"
                   else "no precomputed copy number for this case.")
                + " Copy number comes from exome or panel coverage, or SNP arrays (as TCGA's "
                  "ASCAT3 calls do).")
        return
    ab = block.get("absolute")
    st.markdown(f"Ploidy estimate **{block['ploidy']:g}** {badge('method', 'gray')} (the "
                "tumor's median gene copy number, the rule behind the model's copy-number input) · "
                + (f"ABSOLUTE purity **{ab['purity']:.0%}**, ploidy **{ab['ploidy']:.2f}** "
                   f"{badge(INFERENCE)} (TCGA PanCanAtlas)" if ab else
                   "ABSOLUTE purity: not called for this tumor"))
    pc = gx.ploidy_check(block)
    if pc and pc["disagree"]:
        st.warning(pc["text"][0].upper() + pc["text"][1:] + f" (flagged at {gx.PLOIDY_RATIO:g}-"
                   "fold or more, a placeholder).")
    if ab:
        st.radio("Calls relative to", ["the median gene copy number (the model's rule)",
                                       f"ABSOLUTE's ploidy ({ab['ploidy']:.2f})"],
                 horizontal=True, key=f"{key}-ploidy",
                 help="Percentiles and cohort shares stay relative to the median rule; the "
                      "expression workbench's ERBB2 line uses the median rule.")
    st.caption(" · ".join(f"{c['name']}: {c['rule']} [{c['tag']}]" for c in gx.CUTOFFS[1:])
               + f". {gx.LEVELS_NOTE}")
    show = st.radio("Genes", ["breast drivers and pathway genes", "all measured", "altered only"],
                    horizontal=True, key=f"{key}-cnshow",
                    help="All measured adds the model's 200 most variable copy-number genes, "
                         "which cluster in a few amplicons (8p11-12, 8q24, 11q13, 17q).")
    shown = [r for r in rows if show == "all measured"
             or (show == "altered only" and r["call"] in gx.ALTERED)
             or (show.startswith("breast") and (r["interest"] or r["pathways"]))]
    shown = [{**r, "rank": n} for n, r in enumerate(shown)]
    if shown:
        ev = st.altair_chart(_cn_chart(shown), on_select="rerun", selection_mode=["gene"],
                             key=f"{key}-cnchart-{show}", width="stretch")
        _picked(ev, "gene", gene_key)
        st.caption("Genes in genome order, evenly spaced (not to scale); larger points: the breast "
                   "drivers of interest. Hover for the numbers, click a gene for its Spot panel "
                   "(double-click clears).")
    else:
        st.caption("No gene matches.")
    genes = [r["gene"] for r in rows]
    default = st.session_state.get(gene_key)
    if default not in genes:
        default = next((r["gene"] for r in rows if r["interest"] and r["call"] in (2, -2)), "ERBB2")
        st.session_state[gene_key] = default if default in genes else genes[0]
    gene = st.selectbox("Gene", genes, key=gene_key)
    _gene_spot(file, gene, g, vs, table, omics_view, reviews, f"{key}-spot")
    st.markdown("**Consistency with the other workbenches**")
    cs = ((g["omics"] or {}).get("cases") or {}).get(str(gx.case_index(file)))
    if cs and abs(cs["log_risk"] - g["block"]["log_risk"]) > 1e-3:
        cs = None
    cal = ((g["omics"] or {}).get("validation") or {}).get("receptors", {})
    lines = om.receptor_lines(cs["receptors"], cal) if cs else []
    rna = {k: v["rna"][1] for k, v in omics_view.items() if "rna" in v}
    cons = gx.consistency(rows, lines, rna or None)
    for c in cons:
        color = {"agree": "green", "disagree": "red"}.get(c["status"], "gray")
        st.markdown(f"- {badge(c['status'], color)} **{c['what']}**: {c['text']}  \n"
                    f"  <small>{c['source']} · check: {c['check']}</small>",
                    unsafe_allow_html=True)
    if not cons:
        st.caption("No line to draw: no recorded HER2 status or RNA for the altered genes here.")
    st.markdown("**Look here**")
    for item in gx.cn_queue(rows, block):
        st.markdown(f"- {item}")


def _burden_view(bur, afs, data, sequenced, file) -> None:
    if not bur.get("measured"):
        st.info(bur["note"][0].upper() + bur["note"][1:] + ".")
    else:
        c = st.columns(4)
        c[0].metric("Somatic calls (observed)", bur["calls"])
        c[1].metric("Protein-altering (observed)", bur["altering"])
        c[2].metric(f"Per Mb (derived, ÷ {bur['exome_mb']:g})", f"{bur['rate']:.2f}")
        c[3].metric("Cohort percentile", gx._pct(bur["pct"]).split(" ")[0])
        q = (data or {}).get("burden", {}).get("rate_quantiles") or []
        if q:
            df = pd.DataFrame({"rate": q, "pct": [i * 100 / (len(q) - 1) for i in range(len(q))]})
            line = alt.Chart(df).mark_line(color="gray").encode(
                x=alt.X("rate:Q", title="somatic calls per Mb (log scale)",
                        scale=alt.Scale(type="log"), axis=alt.Axis(format="~g")),
                y=alt.Y("pct:Q", title="cohort percentile"))
            me = alt.Chart(pd.DataFrame({"rate": [bur["rate"]], "pct": [bur["pct"]],
                                         "t": ["this tumor"]}))
            me = me.mark_point(size=120, filled=True, color="#2a78d6").encode(
                x="rate:Q", y="pct:Q", tooltip=["t:N", "rate:Q", "pct:Q"])
            hi = alt.Chart(pd.DataFrame({"pct": [gx.HIGH_PCT]})).mark_rule(
                strokeDash=[6, 4], color="#e08a00").encode(y="pct:Q")
            st.altair_chart((line + hi + me).properties(height=220), width="stretch")
        st.markdown(f"{bur['text']}. " + (
            f"**High in this cohort** (top decile) {badge('placeholder', 'orange')}."
            if bur["high"] else
            f"Not in the cohort's top decile {badge('placeholder', 'orange')}."))
        st.caption(f"Rate = all somatic calls in GDC's open masked file / {gx.EXOME_MB:g} Mb, the "
                   "exome size Chalmers et al. 2017 used for TCGA. KEYNOTE-158's 10 per Mb "
                   "(Marabelle et al. 2020) was defined on the FoundationOne CDx panel in ten "
                   "non-breast cancers: not this measurement, so it is not applied here"
                   + (" (this tumor is above it)" if bur["above_keynote"] else "") + ".")
    st.markdown("**Allele fractions of the observed drivers**")
    if not afs:
        st.caption("No read counts in this file: "
                   + ("the record states no allele fraction." if file.kind == "synthetic" else
                      "none of the panel's genes mutated, or not sequenced." if sequenced else
                      "not sequenced."))
        return
    rows = []
    for a in afs:
        rng = a["clonal_range"]
        rows.append({"Variant": a["variant"], "Class": a["class"],
                     "Reads (alt / depth)": f"{a['alt']} / {a['depth']}" if a["alt"] is not None
                     else "", "Allele fraction": None if a["vaf"] is None else round(a["vaf"], 3),
                     "95% interval": "" if a["lo"] is None else f"{a['lo']:.1%}–{a['hi']:.1%}",
                     "Gene copies": a.get("copies"),
                     "Purity (ABSOLUTE)": None if not a["purity"] else round(a["purity"], 2),
                     "Clonal range": "" if rng is None else f"{rng[0]:.1%}–{rng[1]:.1%}",
                     "Fit (model inference)": a["fit"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    df = pd.DataFrame([{"variant": a["variant"], "vaf": a["vaf"], "lo": a["lo"], "hi": a["hi"],
                        "c_lo": (a["clonal_range"] or (None, None))[0],
                        "c_hi": (a["clonal_range"] or (None, None))[1]}
                       for a in afs if a["lo"] is not None])
    if not df.empty:
        y = alt.Y("variant:N", title=None, axis=alt.Axis(labelLimit=220))
        band = alt.Chart(df.dropna(subset=["c_lo"])).mark_bar(opacity=0.25, color="#7b3fa0",
                                                             height=18).encode(
            x=alt.X("c_lo:Q", title="allele fraction", scale=alt.Scale(domain=[0, 1]),
                    axis=alt.Axis(format="%", tickCount=5)),
            x2="c_hi:Q", y=y, tooltip=[alt.Tooltip("c_lo:Q", format=".1%", title="clonal from"),
                                       alt.Tooltip("c_hi:Q", format=".1%", title="clonal to")])
        err = alt.Chart(df).mark_rule(color="black").encode(x="lo:Q", x2="hi:Q", y=y)
        pt = alt.Chart(df).mark_point(filled=True, color="black", size=60).encode(
            x="vaf:Q", y=y, tooltip=[alt.Tooltip("vaf:Q", format=".1%")])
        st.altair_chart((band + err + pt).properties(height=50 + 44 * len(df)), width="stretch")
        st.caption("Black: observed allele fraction with its 95% interval (observed). Shaded: the "
                   "fraction a clonal mutation would show at this purity and copy number, one "
                   "mutant copy to all (model inference, Carter et al. 2012). Purity is ABSOLUTE's "
                   "estimate for the whole sample.")


def _effect_view(vs, effects, afs) -> None:
    if not vs:
        st.caption("No observed variant.")
        return
    afs = {a["variant"]: a for a in afs}
    rows = []
    for v in vs:
        ef = gx.effect(v["variant"], effects)
        t = gx.effect_text(ef)
        a = afs.get(v["variant"])
        rows.append({"Variant": v["variant"],
                     "Detected: consequence": t["annotation"] if ef["found"] else
                     (a or {}).get("class", ""),
                     "Detected: allele fraction": "" if not a or a["vaf"] is None else
                     f"{a['vaf']:.1%}",
                     "Interpreted: CIViC (strongest)": _level_text(v["strongest_level"]),
                     "Interpreted: ClinVar": t["interpretation"],
                     "Predicted: AlphaMissense": t["prediction"]})
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    rng = (effects or {}).get("alphamissense_class_ranges") or {}
    st.caption(
        f"Three evidence types, kept apart: detected {badge('observed')} (the call and its "
        f"consequence on the MANE Select transcript, Ensembl VEP), interpreted "
        f"{badge('hypothesis')} (CIViC items; ClinVar classifications as Ensembl serves them, "
        f"for clinician review) and predicted {badge(INFERENCE)} (AlphaMissense, Cheng et al. "
        f"2023; predictions CC BY 4.0). {gx.AM_LIMITS} "
        + (f"Its classes, read off the table: likely benign up to "
           f"{rng['likely_benign'][1]:.3f}, likely pathogenic from "
           f"{rng['likely_pathogenic'][0]:.3f}. " if {"likely_benign", "likely_pathogenic"}
           <= set(rng) else "")
        + f"Snapshot {(effects or {}).get('snapshot', 'not taken')}, Ensembl release "
          f"{(effects or {}).get('ensembl_release', '?')}; COSMIC and HGMD identifiers are not "
          "read. Protein positions follow the MANE Select transcript and can differ from the "
          "call's own transcript (e.g. GATA3 A441Wfs*33 is p.Ala442TrpfsTer33 on MANE).")


def _pathway_chart(nodes: list[dict]) -> alt.LayerChart:
    df = pd.DataFrame([{**n, "variants": ", ".join(n["variants"]) or "none",
                        "marks": ", ".join(n["statuses"]) or n["status"],
                        "copies_text": "" if n["copies"] is None else f"{n['copies']:g}",
                        "ring": n["statuses"][1] if n["status"] == "mutated"
                        and len(n["statuses"]) > 1 else "none"}
                       for n in nodes])
    rings = ["amplification", "gain", "loss", "deep deletion", "none"]
    order = list(gx.PATHWAYS)
    sel = alt.selection_point(name="node", fields=["gene"], on="click", clear="dblclick",
                              nearest=True)
    x = alt.X("pathway:N", sort=order, title=None, axis=alt.Axis(labelAngle=0, orient="top",
                                                                 labelLimit=140))
    y = alt.Y("slot:O", axis=None)
    tip = [alt.Tooltip("gene:N"), alt.Tooltip("pathway:N"), alt.Tooltip("marks:N", title="this "
                                                                        "tumor"),
           alt.Tooltip("variants:N", title="variants"), alt.Tooltip("call:N", title="copy number"),
           alt.Tooltip("copies_text:N", title="copies")]
    dots = alt.Chart(df).mark_circle(size=1500, strokeWidth=4).encode(
        x=x, y=y, fill=alt.Fill("status:N", title="this tumor", scale=alt.Scale(
            domain=gx.STATUS_ORDER, range=[NODE_COLORS[s] for s in gx.STATUS_ORDER])),
        stroke=alt.Stroke("ring:N", title="ring: copy number of a mutated gene",
                          scale=alt.Scale(domain=rings, range=[NODE_COLORS.get(r, "#999999")
                                                               for r in rings])),
        opacity=alt.condition(sel, alt.value(1.0), alt.value(0.45)), tooltip=tip).add_params(sel)
    text = alt.Chart(df).mark_text(fontSize=11, fontWeight="bold").encode(
        x=x, y=y, text="gene:N", color=alt.condition(
            "datum.status == 'mutated' || datum.status == 'amplification' || "
            "datum.status == 'deep deletion'", alt.value("white"), alt.value("black")),
        tooltip=tip)
    return (dots + text).properties(height=330)


def _pathway_view(file, nodes, g, vs, table, omics_view, reviews, key, gene_key,
                  sequenced) -> None:
    st.markdown(f"{badge('hypothesis')} {gx.PATHWAY_NOTE}")
    ev = st.altair_chart(_pathway_chart(nodes), on_select="rerun", selection_mode=["node"],
                         key=f"{key}-pathchart", width="stretch")
    _picked(ev, "node", f"{key}-pgene")
    st.caption("Purple: a sequenced mutation; red and blue: copy-number amplification and deep "
               "deletion, lighter for gain and loss; gray: measured, not altered; white: not "
               "measured (unknown, not normal). Click a gene for its Spot panel.")
    summary = gx.pathway_summary(nodes)
    st.dataframe(pd.DataFrame([{"Pathway": p["pathway"], "Genes": ", ".join(p["genes"]),
                                "Altered here": "; ".join(p["altered"]) or "none observed",
                                "Not measured": ", ".join(p["unknown"]) or "—",
                                "Sources": "; ".join(f"{s['cite']} (PMID {s['pmid']})"
                                                     for s in p["sources"])}
                               for p in summary]), hide_index=True, width="stretch")
    names = list(gx.PATHWAYS)
    pkey = f"{key}-pathway"
    if st.session_state.get(pkey) not in names:
        st.session_state[pkey] = next((p["pathway"] for p in summary if p["altered"]), names[0])
    left, right = st.columns([1, 1])
    with left:
        name = st.selectbox("Pathway", names, key=pkey)
        p = next(x for x in summary if x["pathway"] == name)
        st.markdown(f"**{name}** · altered here: {'; '.join(p['altered']) or 'none observed'}")
        for s in p["sources"]:
            st.markdown(f"- [{s['cite']}]({s['url']}), {s['where']} (doi:{s['doi']}): {s['says']}")
        items = gx.pathway_items(name, table)
        st.markdown(f"**Therapy evidence for its genes** {badge('hypothesis')} · CIViC, breast "
                    "cancer, for clinician review, never a recommendation")
        if items["items"]:
            st.dataframe(pd.DataFrame(items["items"]).rename(columns={
                "molecular_profile": "Profile", "therapies": "Therapies",
                "evidence_level": "Level", "significance": "Significance",
                "direction": "Direction", "citation": "Citation", "url": "CIViC"}),
                hide_index=True, width="stretch", column_config=LINK)
            st.caption(f"{items['total']} items name a gene of this pathway; the strongest "
                       "levels first. An item for a gene is not an item for this tumor's change.")
        else:
            st.caption("None in the loaded CIViC table." if table is not None else
                       "CIViC table not loaded on this machine.")
        _marks(reviews, finding_key(file, "pathway", name), f"pathway {name}: "
               f"{'; '.join(p['altered']) or 'no observed alteration'}", f"{key}-pw-{name}")
    with right:
        genes = gx.PATHWAYS[name]["genes"]
        pg = st.session_state.get(f"{key}-pgene")
        if pg not in genes:
            pg = next((n["gene"] for n in nodes if n["pathway"] == name and n["statuses"]),
                      genes[0])
        node = next(n for n in nodes if n["gene"] == pg and n["pathway"] == name)
        st.markdown(f"**{pg}** · {', '.join(node['statuses']) or node['status']}")
        if node["status"] == "not measured":
            st.caption("Not measured in this file: unknown, never normal.")
        _gene_spot(file, pg, g, vs, table, omics_view, reviews, f"{key}-pspot")


def _over_time(lon: dict, hs: dict, key: str) -> None:
    if not lon["rows"]:
        st.caption("No variant observed in any sample yet.")
        return
    cols = [s["id"] for s in lon["samples"]]
    gene_rows = {}
    for r in lon["rows"]:
        links = gx.escape_links(r["gene"], hs)
        gene_rows[r["variant"]] = links
    df = pd.DataFrame([{"Variant": r["variant"], **{c: cell["text"] for c, cell in
                                                     zip(cols, r["cells"], strict=True)},
                        "Origin (ctDNA monitor)": lon.get("origins", {}).get(r["variant"], ""),
                        "Evolution view": "; ".join(
                            f"{x['event']} ({'raised' if x['raised'] else 'not raised'})"
                            for x in gene_rows[r["variant"]]) or "no escape-route row names "
                                                                 "this gene"}
                       for r in lon["rows"]])
    st.dataframe(df, hide_index=True, width="stretch")
    kinds = " · ".join(f"{s['id']}: {s['kind']}, {s['assay']}" for s in lon["samples"])
    st.caption(f"Rule: {lon['rule']}. " + " ".join(n[0].upper() + n[1:] + "." for n in
                                                    lon["notes"]) + f" Samples: {kinds}.")
    st.button("Open the Evolution view: the escape-route rows for these genes, with sources",
              key=f"{key}-evolution-lon",
              on_click=lambda: st.session_state.update(view="Evolution"))


def _method_card(g: dict, effects: dict) -> None:
    st.markdown("#### Genome views: predictors, rules and cutoffs")
    rows = gx.card(g["data"], effects, ((g["omics"] or {}).get("validation") or {}))
    st.dataframe(pd.DataFrame(rows).rename(columns={
        "what": "What", "rule": "Rule", "source": "Source", "tag": "Tag", "status": "Status"}),
        hide_index=True, width="stretch")
    st.caption(f"Scores: {(g['data'] or {}).get('version', 'not computed')} "
               "(scripts/genomics_scores.py, offline); effects: snapshot "
               f"{(effects or {}).get('snapshot', 'not taken')} (scripts/genomics_effect.py). "
               f"Pathway references checked against PubMed on {gx.VERIFIED}. Known limits: a "
               "gene-level copy number hides segment boundaries; the ploidy is estimated; purity "
               "is one number for the whole sample; AlphaMissense is not approved for clinical "
               "use.")


def render(file, events=None, evidence: dict | None = None, version: int | None = None,
           lookup=None, table=None, case=None, demo=None) -> None:
    key = f"genomics-{file.id}-{'latest' if version is None else version}"  # widget keys
    month = None if version is None else file.versions[version].month
    events = wb.events_until(events, month)
    g = _genome(file, case)
    vs = wb.variants(file, events, evidence, lookup, reads=g["reads"])
    effects = _effects(g["effects"], tuple(v["variant"] for v in vs))
    queue, card, lon = wb.review_queue(vs), wb.data_card(), wb.longitudinal(file, events)
    strip, coverage = wb.provenance(file, events), wb.panel_coverage(file, events)
    cov = {c["gene"]: c["status"] for c in coverage}
    ladders = {v["variant"]: wb.ladder(v, wb.variant_resistance(v, table),
                                       gx.effect(v["variant"], effects)) for v in vs}
    afs = {a["variant"]: a for a in g["afs"]}
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
            _spot(file, v, ladders[v["variant"]], cov, strip, reviews, key,
                  gx.effect(v["variant"], effects), afs.get(v["variant"]))
        else:
            st.caption("No variant matches.")
    else:
        st.caption("No variant to browse.")

    # the tumor's genome as a picture
    gv = _genome_sections(file, version, vs, g, effects, table, case, demo, reviews, key)

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
    statement = lon["statement"][0].upper() + lon["statement"][1:]
    ctdna_state = "in the table below" if gv["ctdna"] else lon["ctdna"]
    st.markdown(f"{statement}. {badge('ctDNA: ' + ctdna_state, 'gray')}")
    _over_time(gv["lon"], gv["hs"], key)

    # export
    st.markdown("#### Export")
    e1, e2, e3, e4 = st.columns(4)
    stem = f"genomics_{file.id.replace(' ', '_')}"
    e1.download_button("Download the genomics report (Markdown)",
                       wb.report_markdown(file, vs, ladders, watch, reviews, strip) + "\n"
                       + gx.report_markdown(file, gv["rows"], gv["bur"], g["afs"], gv["nodes"],
                                            effects, gv["lon"], reviews),
                       f"{stem}.md", "text/markdown", key=f"{key}-md")
    e2.download_button("Download the variants and evidence items (CSV)",
                       wb.report_csv(file, vs, reviews), f"{stem}.csv", "text/csv",
                       key=f"{key}-csv")
    e3.download_button("Download the copy-number table (CSV)",
                       gx.landscape_csv(gv["rows"], reviews, file),
                       f"{stem}_copy_number.csv", "text/csv", key=f"{key}-cn-csv",
                       disabled=not gv["rows"])
    e4.download_button("Download the genome findings (JSON)",
                       gx.report_json(file, gx.findings(file, gv["rows"], gv["bur"], gv["nodes"],
                                                        g["afs"], effects), reviews,
                                      {"scores": (g["data"] or {}).get("version"),
                                       "effects": (effects or {}).get("snapshot"),
                                       "ensembl_release": (effects or {}).get("ensembl_release")}),
                       f"{stem}_genome.json", "application/json", key=f"{key}-json")

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
    _method_card(g, effects)
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


@st.cache_resource(show_spinner="Loading the cases (once)...")
def _bundle():
    """The bundle at MUFFLE_BUNDLE (a local path), or None: the example case is used then."""
    import os

    from muffle.demo import load_bundle
    path = os.getenv("MUFFLE_BUNDLE")
    if not path or not Path(path).exists():
        return None
    try:
        return load_bundle(path)
    except Exception:
        return None


def main() -> None:
    from muffle.report import civic
    from muffle.workspace import case_file, synthetic_file
    st.set_page_config(page_title="Genomics workbench", layout="wide")
    tl = json.loads((APP / "timeline_synthetic.json").read_text(encoding="utf-8"))
    demo = _bundle()
    cases = {f"Case {c.index} (TCGA-BRCA public data)": c for c in demo.cases} if demo else {
        f"Case {EXAMPLE_CASE.index} (TCGA-BRCA public data, example values)": EXAMPLE_CASE}
    choice = st.selectbox("Example file", ["SYNTHETIC-001 (synthetic patient)", *cases])
    table = _civic_table()
    if table is None:
        st.caption("CIViC table not available on this machine: evidence items and resistance "
                   "items are not shown; the cited literature still is.")
    if choice.startswith("SYNTHETIC"):
        render(synthetic_file(tl), evidence=tl.get("evidence"), table=table)
    else:
        lookup = None if table is None else (
            lambda gene, change: civic.evidence(gene, change, "breast", 3, table))
        case = cases[choice]
        render(case_file(case), lookup=lookup, table=table, case=case if demo else None,
               demo=demo)


if __name__ == "__main__":
    main()

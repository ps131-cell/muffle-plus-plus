"""Expression, methylation and protein workbench (docs/WORKBENCHES.md §7) for one TCGA patient
file; also the clinical record card.

The shell calls ``render(pf, version=None, layer=None, case=None, demo=None)``: ``pf`` a
``muffle.workspace.PatientFile``, ``layer`` the data layer whose test was opened (its card comes
first), ``case`` the held-out ``muffle.demo.Case`` and ``demo`` the loaded ``muffle.demo.Demo``
(model, inputs, offsets). ``render`` draws in the current container only. ``methods_section()``
draws the validation numbers for the Methods and validation page.

Precomputed scores come from ``app/omics_scores.json`` (scripts/omics_scores.py, offline, derived
numbers only); contributions, top features and the what-if run on the model here. Evidence types:
recorded IHC and measured values are observed; the subtype call, pathway scores, contributions
and the what-if are model inferences. Review marks and pins go to the shell's stores under
``workspace.finding_key(pf, "omics", layer, name)``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st
import torch

import charts
from muffle import workspace
from muffle.demo import ordinal
from muffle.explain import risk_percentile, top_features
from muffle.report.case_tools import INFERENCE, OBSERVED
from muffle.workbench import omics as wb
from muffle.workbench.genomics import add_mark, mark_text
from muffle.workbench.grammar import CANNOT_SEE, CARD, EXPORT, chip, esc

APP = Path(__file__).resolve().parents[1]
STATUS_COLORS = {wb.AGREE: "green", wb.DISAGREE: "red", wb.NO_COMPARISON: "gray"}
CALLS = {-2: "deep deletion", -1: "loss", 0: "neutral", 1: "gain", 2: "amplification"}
UNITS = {"rna": "z-score of log(1 + TPM)", "methylation": "M-value", "protein": "z-score",
         "genomic": "copy-number call", "clinical": "z-score or 0/1 flag"}
MISSING = {  # what a missing layer limits
    "rna": "no subtype call, no pathway, proliferation or immune score, no RNA receptor check",
    "protein": "no RPPA check of ER, PR and HER2",
    "genomic": "no copy-number view of ERBB2 or any other gene",
    "methylation": "no CpG features",
}
TOP = 10
CANNOT = ("Protein level from RNA, single cells or where in the tumor (the slide workbench), point "
          "mutations (the genomics workbench), change over time (TCGA holds one sample per "
          "patient). A subtype from bulk RNA is not the IHC surrogate subtype used in the clinic, "
          "and nothing here is a treatment recommendation.")


@st.cache_data
def scores() -> dict | None:
    path = APP / "omics_scores.json"
    return json.loads(path.read_text()) if path.exists() else None


@st.cache_data
def results() -> dict:
    path = APP / "results_tcga_brca.json"
    if not path.exists():
        return {}
    return {m["method"]: m for m in json.loads(path.read_text())["methods"]}


def tag(evidence: str) -> str:
    return " ".join(chip(e) for e in (OBSERVED, INFERENCE) if e in evidence)




# --- findings ----------------------------------------------------------------------------------

def feature_findings(pf, case, demo, data: dict | None) -> list[dict]:
    """Every feature of every measured layer: value, cohort percentile, gradient × input score."""
    x, mask = demo.inputs(case)
    out = []
    for layer in case.layers:
        names = demo.names.get(layer) or [f"{layer}_{j}" for j in range(x[layer].shape[1])]
        scored = dict(top_features(demo.model, x, mask, layer, names, len(names)))
        quant = (data or {}).get("quantiles", {}).get(layer, {})
        for j, name in enumerate(names):
            value = float(x[layer][0, j])
            if layer == "genomic":
                share = quant.get(name, [None] * 5)[int(round(value)) + 2]
                pct, shown = None, CALLS.get(int(round(value)), f"{value:g}")
                note = "" if share is None else f"{share:.0%} of the cohort share this call"
            else:
                pct = wb.percentile(value, quant[name]) if name in quant else None
                shown, note = f"{value:.2f}", ""
            gene = (data or {}).get("cpg_genes", {}).get(name, name)
            sets = sorted({s for g in gene.split(",")
                           for s in (data or {}).get("members", {}).get(g, [])})
            out.append({"kind": "feature", "layer": layer, "name": name, "value": shown,
                        "percentile": None if pct is None else round(pct), "note": note,
                        "score": scored.get(name, 0.0), "gene": gene if gene != name else "",
                        "sets": sets, "evidence": f"{OBSERVED} (value), {INFERENCE} (effect)",
                        "text": f"{wb.LAYERS[layer]['name']} {gene} " + " ".join(sets),
                        "key": workspace.finding_key(pf, "omics", layer, name)})
    return out


def other_findings(pf, cs: dict | None, lines: list[dict], data: dict | None) -> list[dict]:
    out = []
    if cs:
        sub = cs["pam50"]
        out.append({"kind": "subtype", "layer": "subtype", "name": "PAM50",
                    "value": wb.SUBTYPES[sub["call"]], "percentile": None,
                    "evidence": INFERENCE, "status": _published(sub),
                    "text": f"subtype PAM50 {wb.SUBTYPES[sub['call']]} {_published(sub)} "
                            "proliferation luminal basal",
                    "key": workspace.finding_key(pf, "omics", "subtype", "PAM50")})
        for name, (z, pct) in cs["scores"].items():
            kind = "score" if name in ("proliferation", "immune") else "pathway"
            size = data["sets"].get(name, {})
            out.append({"kind": kind, "layer": kind, "name": name, "value": z,
                        "percentile": round(pct), "evidence": INFERENCE,
                        "text": name.replace("_", " ").lower() + (
                            " PAM50 proliferation genes" if name == "proliferation" else
                            " cytolytic activity GZMA PRF1 immune" if name == "immune" else
                            f" Hallmark set {size.get('measured', '?')} genes"),
                        "key": workspace.finding_key(pf, "omics", kind, name)})
    for x in lines:
        name = f"{x['receptor']}: {x['compare']}"
        out.append({"kind": "receptor", "layer": "receptor", "name": name, "value": x["status"],
                    "percentile": None, "evidence": x["evidence"], "status": x["status"],
                    "text": x["text"], "check": x["check"],
                    "key": workspace.finding_key(pf, "omics", "receptor", name)})
    return out


def _published(sub: dict) -> str:
    if sub.get("published") is None:
        return "no published call"
    return ("agrees with the published call" if sub["agrees"] else
            f"disagrees with the published call ({wb.SUBTYPES[sub['published']]})")


# --- page ------------------------------------------------------------------------------------

def render(pf, version: int | None = None, layer: str | None = None, case=None,
           demo=None) -> None:
    v = pf.versions[-1 if version is None else version]
    st.subheader(f"Expression, methylation and protein · {pf.id}")
    if case is None or demo is None:
        st.info("This file holds no expression, methylation or protein data. RNA-seq, a "
                "methylation array or a protein array of the tumor would open this workbench.")
        return
    data = scores()
    cs = (data or {}).get("cases", {}).get(str(case.index))
    if cs and abs(cs["log_risk"] - case.log_risk) > 1e-3:  # computed for another build
        cs = None
    cal = (data or {}).get("validation", {}).get("receptors", {})
    lines = wb.receptor_lines(cs["receptors"], cal) if cs else []
    feats = feature_findings(pf, case, demo, data)
    findings = other_findings(pf, cs, lines, data) + feats
    by_key = {f["key"]: f for f in findings}
    reviews = st.session_state.setdefault("reviews", {})
    pins = st.session_state.setdefault("pins", {})
    spot = f"omics-spot-{pf.id}"
    tools = demo.tools(case)
    contrib = tools.modality_contributions()["log_risk_added_by_layer"]

    st.caption(f"{pf.title} · {v.label}")
    st.markdown(" ".join([chip(wb.IMPLEMENTED, "blue"),
                          *([chip(f"subtype call: {wb.VALIDATED}", "green")] if cs else []),
                          chip("signatures beyond PAM50: planned")]))
    st.caption("Data: TCGA-BRCA open access (UCSC Xena GDC hub; IHC from TCGA clinical data via "
               "cBioPortal) · scores: scripts/omics_scores.py, "
               f"{(data or {}).get('version', 'not computed')} · model: {pf.model['name']} · "
               "methods, references and known failures in the card at the bottom and on the "
               "Methods and validation page.")
    if cs is None:
        st.warning("No precomputed subtype, pathway or receptor scores for this case: only the "
                   "model's view of each layer is shown below.")

    # overview: the three questions
    queue = wb.look_here(cs, lines, case.layers)
    o, i, c = st.columns(3)
    with o:
        st.markdown(f"**Observed** {tag(OBSERVED)}")
        missing = ", ".join(wb.LAYERS[m]["name"] for m in case.missing) or "none"
        st.markdown(f"- Measured: {', '.join(wb.LAYERS[m]['name'] for m in case.layers)}\n"
                    f"- Not measured: {missing}")
        if cs:
            st.markdown("\n".join(
                f"- {name} IHC: {(r.get('ihc') or 'not recorded').lower()}"
                + (f", ISH {r['fish'].lower()}" if r.get("fish") and name == "HER2" else "")
                for name, r in cs["receptors"].items()))
    with i:
        st.markdown(f"**Model inference** {tag(INFERENCE)}")
        bits = []
        if cs:
            sub = cs["pam50"]
            bits.append(f"PAM50 subtype **{wb.SUBTYPES[sub['call']]}** (margin "
                        f"{sub['margin']:.2f}; {_published(sub)})")
            prolif, immune = cs["scores"]["proliferation"], cs["scores"]["immune"]
            bits.append(f"Proliferation at the {ordinal(prolif[1])} percentile, immune "
                        f"cytolytic activity at the {ordinal(immune[1])}")
        if contrib:
            big = max(contrib, key=lambda m: abs(contrib[m]))
            bits.append(f"Layer moving the risk most: {wb.LAYERS[big]['name']} "
                        f"({contrib[big]:+.3f} log-risk vs a typical patient)")
        st.markdown("\n".join(f"- {b}" for b in bits) or "- none")
    with c:
        st.markdown("**Check by eye** · a queue, not a verdict")
        st.markdown("\n".join(f"{n}. {q}" for n, q in enumerate(queue, 1)) or "Nothing flagged.")

    # search
    query = st.text_input("Search this workbench: a gene (ESR1), a pathway word (proliferation), "
                          "a status (disagree)", key=f"omics-search-{pf.id}")
    if query:
        hits = wb.search(query, findings)
        if hits["note"]:
            st.info(hits["note"])
        else:
            _table(pd.DataFrame([{"Kind": h["kind"], "Layer or block": h["layer"],
                                  "Finding": h["name"], "Value": str(h["value"]),
                                  "Cohort percentile": "" if h["percentile"] is None
                                  else str(h["percentile"]),
                                  "Mark": (reviews.get(h["key"]) or {}).get("mark", "")}
                                 for h in hits["hits"][:200]]),
                   [h["key"] for h in hits["hits"][:200]], f"omics-hits-{pf.id}-{query}", spot)

    # subtype
    st.markdown(f"#### PAM50 intrinsic subtype {tag(INFERENCE)} "
                f"{chip(wb.VALIDATED, 'green') if cs else chip('not computed')}")
    if cs:
        subtype_card(cs["pam50"], data)
    elif "rna" not in case.layers:
        st.caption(f"RNA not measured: {MISSING['rna']}.")

    # receptors
    st.markdown(f"#### Receptor consistency {tag(OBSERVED)} · recorded IHC against RNA, copy "
                "number and protein")
    for x in lines:
        st.markdown(f"{chip(x['status'], STATUS_COLORS[x['status']])} **{x['receptor']}** · "
                    f"{x['text']}")
        st.caption(f"Evidence: {x['evidence']} · what to check: {x['check']}")
    if lines:
        st.caption("RNA is not protein: these lines say which layer each claim comes from. Cutoffs "
                   "are calibrated in-sample on this cohort's recorded receptor status (Methods "
                   "and validation), not a clinical threshold; IHC and in situ hybridization stay "
                   "the clinical tests.")
    elif cs is None:
        st.caption("Not computed for this case.")

    # pathways
    st.markdown(f"#### Pathway, proliferation and immune scores {tag(INFERENCE)}")
    if cs:
        pathway_chart(cs, data)
    else:
        st.caption(f"Needs RNA expression ({MISSING['rna']}).")

    # layer cards
    st.markdown("#### Data layers")
    order = ([layer] if layer in wb.LAYERS else []) + [m for m in wb.LAYERS if m != layer]
    for tab, m in zip(st.tabs([wb.LAYERS[m]["name"] for m in order]), order, strict=True):
        with tab:
            layer_card(pf, v, m, case, contrib, [f for f in feats if f["layer"] == m], cs, spot)

    # what-if
    st.markdown(f"#### What if a layer were missing? {tag(INFERENCE)}")
    hide = st.pills("Hide layers", case.layers, selection_mode="multi",
                    format_func=lambda m: wb.LAYERS[m]["name"], key=f"omics-hide-{pf.id}")
    if hide and len(hide) == len(case.layers):
        st.warning("Keep at least one layer.")
    elif hide:
        hx, hmask = demo.inputs(case, hide)
        with torch.no_grad():
            pct = risk_percentile(demo.model(hx, hmask).item(), demo.cohort_risks)
        st.metric("Risk percentile without " + ", ".join(wb.LAYERS[m]["name"] for m in hide),
                  ordinal(pct), f"{int(pct) - int(case.percentile):+d} percentile points",
                  delta_color="inverse")
    st.caption("The model masks a hidden layer, as it does for a layer a hospital never measured; "
               "the move is the model's, not a measured change.")

    # Spot panel
    st.markdown("#### Spot panel")
    keys = list(by_key)
    if st.session_state.get(spot) not in by_key:
        opened = [f for f in feats if f["layer"] == layer]
        st.session_state[spot] = (max(opened, key=lambda f: abs(f["score"]))["key"] if opened
                                  else keys[0])
    st.selectbox("Open a finding", keys, key=spot, format_func=lambda k: (
        f"{by_key[k]['kind']} · {by_key[k]['layer']} · {by_key[k]['name']}"))
    spot_panel(pf, by_key[st.session_state[spot]], cs, data, contrib, reviews, pins)

    st.markdown(f"#### {CANNOT_SEE}")
    st.markdown(CANNOT)

    st.markdown(f"#### {EXPORT}")
    shown = [f for f in findings if f["kind"] != "feature"] + [
        f for m in case.layers for f in sorted((f for f in feats if f["layer"] == m),
                                               key=lambda f: -abs(f["score"]))[:TOP]]
    shown += [f for f in feats if f["key"] in reviews and f not in shown]
    rows = [{k: f.get(k) for k in ("kind", "layer", "name", "value", "percentile", "evidence",
                                   "status", "key")} for f in shown]
    prov = {"data": "TCGA-BRCA open access (UCSC Xena GDC hub); IHC: " + wb.REFERENCES["ihc"],
            "scores": (data or {}).get("version"), "model": pf.model["name"],
            "contribution_vs_typical_patient": contrib, "references": wb.REFERENCES,
            "placeholders": [f"PAM50 borderline margin < {wb.LOW_MARGIN}",
                             "ERBB2 amplified at >= 2x ploidy (ASCAT calls)"]}
    e1, e2 = st.columns(2)
    name = pf.id.replace(" ", "_")
    e1.download_button("Download the findings and marks (JSON)",
                       wb.report_json(pf.id, rows, reviews, prov), f"omics_{name}.json",
                       "application/json", key=f"omics-json-{pf.id}")
    e2.download_button("Download the findings and marks (CSV)", wb.report_csv(rows, reviews),
                       f"omics_{name}.csv", "text/csv", key=f"omics-csv-{pf.id}")

    with st.expander(f"{CARD}: methods, references, placeholders and known failures"):
        method_card(data)


def _table(df: pd.DataFrame, keys: list[str], key: str, spot: str) -> None:
    """A table whose row click opens that finding in the Spot panel."""
    def pick():
        rows = st.session_state[key].selection.rows
        if rows:
            st.session_state[spot] = keys[rows[0]]

    st.dataframe(df, hide_index=True, width="stretch", on_select=pick,
                 selection_mode="single-row", key=key)


def subtype_card(sub: dict, data: dict) -> None:
    val = data["validation"]["pam50"]
    left, right = st.columns([2, 3])
    with left:
        st.metric("Call", wb.SUBTYPES[sub["call"]],
                  help="Nearest of the five PAM50 centroids by Spearman correlation.")
        st.markdown(f"Margin to the runner-up: **{sub['margin']:.2f}** "
                    + (chip("borderline", "orange") if sub["margin"] < wb.LOW_MARGIN else "")
                    + f"  \nTCGA's published call: **{_published(sub)}**  \n"
                    f"Genes used: {sub['genes']} of 50")
        st.caption(f"Validation on this cohort: the same method agrees with TCGA's published PAM50 "
                   f"calls for {val['share']:.1%} of {val['n']} tumors (Cohen's kappa "
                   f"{val['kappa']:.2f}); the confusion matrix is on the Methods and validation "
                   "page.")
    with right:
        df = pd.DataFrame([{"subtype": wb.SUBTYPES[k], "correlation": r,
                            "call": "this call" if k == sub["call"] else "other centroid"}
                           for k, r in sub["cor"].items()])
        st.altair_chart(alt.Chart(df).mark_bar().encode(
            x=alt.X("correlation:Q", scale=alt.Scale(domain=[-1, 1]),
                    title="Spearman correlation with the centroid"),
            y=alt.Y("subtype:N", sort="-x", title=None, axis=alt.Axis(labelOverlap=False)),
            color=alt.Color("call:N", legend=None, scale=alt.Scale(
                domain=["this call", "other centroid"], range=[charts.BLUE, "#9aa5b1"])),
            tooltip=["subtype", alt.Tooltip("correlation:Q", format=".3f")]
        ).properties(height=34 * len(df)), width="stretch")
    st.caption("Normalization: log2(TPM + 1), each gene centered on its median over an ER-balanced "
               f"subset of this cohort ({val['reference_tumors']} tumors: every ER-negative one "
               "by IHC and as many ER-positive; Zhao et al. 2015). The reference population is "
               "this TCGA-BRCA cohort; plain centering on the whole, mostly ER-positive cohort "
               f"agrees only {val['plain_centering']['share']:.1%}, so the call depends on the "
               "reference. Centroids: Parker et al. 2009 via genefu. A subtype from bulk RNA is "
               "not the IHC surrogate subtype used in the clinic, and not a treatment "
               "recommendation.")


def pathway_chart(cs: dict, data: dict) -> None:
    s = cs["scores"]
    c1, c2 = st.columns(2)
    c1.metric("Proliferation", f"{ordinal(s['proliferation'][1])} percentile",
              f"z {s['proliferation'][0]:+.2f}", delta_color="off",
              help="The 11 PAM50 proliferation genes (Parker et al. 2009), cohort z-score.")
    c2.metric("Immune cytolytic activity", f"{ordinal(s['immune'][1])} percentile",
              f"z {s['immune'][0]:+.2f}", delta_color="off",
              help="GZMA and PRF1 (Rooney et al. 2015), cohort z-score.")
    df = pd.DataFrame([{"set": k.replace("_", " ").lower(), "z": z, "percentile": p,
                        "genes": f"{data['sets'][k]['measured']} of {data['sets'][k]['size']}",
                        "direction": "above the cohort average" if z >= 0 else "below"}
                       for k, (z, p) in s.items() if k in data["sets"]])
    st.altair_chart(alt.Chart(df).mark_bar().encode(
        x=alt.X("z:Q", title="score (cohort z-score; 0 = cohort average)"),
        y=alt.Y("set:N", sort="-x", title=None,
                axis=alt.Axis(labelLimit=260, labelOverlap=False)),
        color=alt.Color("direction:N", legend=None, scale=alt.Scale(
            domain=["above the cohort average", "below"], range=[charts.BLUE, charts.ORANGE])),
        tooltip=["set", alt.Tooltip("z:Q", format="+.2f"),
                 alt.Tooltip("percentile:Q", format=".0f", title="cohort percentile"),
                 alt.Tooltip("genes:N", title="genes measured")]
    ).properties(height=17 * len(df) + 30), width="stretch")
    st.caption("MSigDB Hallmark sets (Liberzon et al. 2015, CC BY 4.0): each gene z-scored over "
               "the cohort, the set's mean z-score z-scored again (z-score averaging). Relative to "
               "this cohort, not an absolute pathway activity; hover a bar for its percentile. "
               "Search a set's name to open it in the Spot panel.")


def layer_card(pf, v, m: str, case, contrib: dict, feats: list[dict], cs: dict | None,
               spot: str) -> None:
    info, res = wb.LAYERS[m], results().get(wb.LAYERS[m]["result"])
    if m not in case.layers:
        st.markdown(f"**Not measured** {tag(OBSERVED)}: unknown, not normal. The model masks it. "
                    f"What it limits: {MISSING.get(m, 'nothing else on this page')}.")
        if res:
            st.caption(f"When measured, this layer alone reaches C-index {res['mean']:.3f} ± "
                       f"{res['sd']:.3f} on hospitals it never saw.")
        return
    st.markdown(f"**Measured** {tag(OBSERVED)}: {workspace.ASSAYS[m]}  \n"
                f"**Normalization:** {info['normalization']}.")
    if m == "clinical":
        st.markdown("\n".join(f"- **{k}:** {esc(val)}" for k, val in v.observed))
        if cs:
            st.markdown("- **Receptor status (IHC, TCGA clinical data):** " + ", ".join(
                f"{n} {(r.get('ihc') or 'not recorded').lower()}"
                for n, r in cs["receptors"].items()))
    a, b = st.columns(2)
    if m in contrib:
        a.metric("Effect on log-risk vs a typical patient", f"{contrib[m]:+.3f}",
                 help="The predicted log-risk with this layer minus without it, compared with the "
                      "same difference for a typical patient (model inference).")
    if res:
        b.metric("This layer alone, C-index", f"{res['mean']:.3f} ± {res['sd']:.3f}",
                 help="Leave one hospital out, 5 seeds (Methods and validation).")
    if info["failure"]:
        st.warning(info["failure"] + (f" (C-index {res['mean']:.3f}, below 0.5)" if res else ""))
    top = sorted(feats, key=lambda f: -abs(f["score"]))[:TOP]
    if top and any(round(f["score"], 4) for f in top):
        _table(pd.DataFrame([{
            "Feature": f["name"] + (f" ({f['gene']})" if f["gene"] else ""),
            "Effect on log-risk": round(f["score"], 4), "Value": f["value"],
            "Cohort percentile": f["percentile"] if f["percentile"] is not None else f["note"],
            "Hallmark sets": ", ".join(f["sets"][:3]) + (" …" if len(f["sets"]) > 3 else "")}
            for f in top]), [f["key"] for f in top], f"omics-top-{pf.id}-{m}", spot)
        st.caption(f"{tag(INFERENCE)} The {len(top)} features that move this patient's predicted "
                   "risk most (gradient × input): an inference about the model, not a biological "
                   "finding about the tumor. Click a row for its Spot panel. Percentiles are "
                   "interpolated between cohort deciles.")
    else:
        st.caption("No single feature in this layer moves this patient's risk measurably.")
    st.caption(f"What to check: {info['check']}. What it cannot see: {info['cannot']}.")


def spot_panel(pf, f: dict, cs: dict | None, data: dict | None, contrib: dict, reviews: dict,
               pins: dict) -> None:
    with st.container(border=True):
        st.markdown(f"**{f['name']}** · {f['kind']} · {f['layer']} {tag(f['evidence'])}")
        if f["kind"] == "feature":
            info = wb.LAYERS[f["layer"]]
            st.markdown(
                f"- **Layer:** {info['name']} ({workspace.ASSAYS[f['layer']]})\n"
                f"- **Value:** {f['value']} ({UNITS[f['layer']]})"
                + (f", {f['note']}" if f["note"] else "") + "\n"
                + (f"- **Cohort percentile:** about the {ordinal(f['percentile'])}\n"
                   if f["percentile"] is not None else "")
                + f"- **Effect on this patient's log-risk:** {f['score']:+.4f} (gradient × input; "
                  "model inference)\n"
                + (f"- **Linked gene (by position):** {f['gene']}\n" if f["gene"] else "")
                + f"- **Hallmark sets:** {', '.join(f['sets']) or 'none'}\n"
                + (f"- **PAM50 gene** (subtype call: "
                   f"{wb.SUBTYPES[cs['pam50']['call']] if cs else 'not computed'})\n"
                   if f["name"] in PAM50_GENES else "")
                + f"- **What to check:** {info['check']}\n"
                  f"- **What it cannot see:** {info['cannot']}")
        elif f["kind"] in ("pathway", "score"):
            genes = [g for g, sets in (data or {}).get("members", {}).items() if f["name"] in sets]
            st.markdown(f"- **Score:** z {f['value']:+.2f}, the {ordinal(f['percentile'])} "
                        "percentile of this cohort\n"
                        f"- **Method:** gene-wise cohort z-scores averaged, z-scored again\n"
                        + (f"- **Set:** MSigDB HALLMARK_{f['name']}, "
                           f"{data['sets'][f['name']]['measured']} of "
                           f"{data['sets'][f['name']]['size']} genes measured; members the risk "
                           f"model also reads: {', '.join(genes[:30]) or 'none'}\n"
                           if f["name"] in (data or {}).get("sets", {}) else "")
                        + "- **What it cannot see:** which cells express the genes (bulk RNA); "
                          "activity of the pathway's proteins")
        elif f["kind"] == "receptor":
            st.markdown(f"{f['text']}  \n**Evidence:** {f['evidence']}  \n"
                        f"**What to check:** {f['check']}")
        else:  # subtype
            sub = cs["pam50"]
            st.markdown(f"- **Call:** {wb.SUBTYPES[sub['call']]}, margin {sub['margin']:.2f}\n"
                        "- **Correlations:** " + ", ".join(f"{wb.SUBTYPES[k]} {r:+.2f}"
                                                           for k, r in sub["cor"].items())
                        + f"\n- **Published call:** {_published(sub)}")
        review(f, reviews, pins)


def review(f: dict, reviews: dict, pins: dict) -> None:
    key, what = f["key"], f"{f['layer']} · {f['name']}"
    done = reviews.get(key)
    h = f"omics-mark-{hashlib.sha1(key.encode()).hexdigest()[:10]}"

    def on_mark():
        choice = st.session_state[h]
        add_mark(reviews, key, what, choice, st.session_state.get("reviewer") or "")

    def on_pin():
        if pins.pop(key, None) is None:
            pins[key] = what

    a, b = st.columns([3, 2])
    a.segmented_control("Your mark", workspace.MARKS[1:], key=h, on_change=on_mark,
                        default=done["mark"] if done and done["mark"] in workspace.MARKS[1:]
                        else None)
    b.checkbox("Pin to the top of the report", key=f"{h}-pin", value=key in pins,
               on_change=on_pin)
    st.caption(mark_text(done) or "No mark yet. Marks carry your initials from the sidebar and go "
                                  "into the report export.")


PAM50_GENES = {"ACTR3B", "ANLN", "BAG1", "BCL2", "BIRC5", "BLVRA", "CCNB1", "CCNE1", "CDC20",
               "CDC6", "NUF2", "CDH3", "CENPF", "CEP55", "CXXC5", "EGFR", "ERBB2", "ESR1", "EXO1",
               "FGFR4", "FOXA1", "FOXC1", "GPR160", "GRB7", "KIF2C", "NDC80", "KRT14", "KRT17",
               "KRT5", "MAPT", "MDM2", "MELK", "MIA", "MKI67", "MLPH", "MMP11", "MYBL2", "MYC",
               "NAT1", "ORC6", "PGR", "PHGDH", "PTTG1", "RRM2", "SFRP1", "SLC39A6", "TMEM45B",
               "TYMS", "UBE2C", "UBE2T"}


def method_card(data: dict | None) -> None:
    st.markdown(
        "- **PAM50 subtype** [model inference, experimentally validated on this cohort]: Parker "
        "centroids (genefu), Spearman correlation after centering each gene on its median over "
        "an ER-balanced subset of this cohort (Zhao et al. 2015).\n"
        "- **Pathway scores** [model inference, implemented]: MSigDB Hallmark sets, z-score "
        "averaging against this cohort; proliferation = the 11 PAM50 proliferation genes; immune "
        "= cytolytic activity (GZMA, PRF1).\n"
        "- **Receptor consistency** [observed, implemented]: IHC (and ISH for HER2 per ASCO/CAP) "
        "against RNA and RPPA levels with cutoffs calibrated in-sample on this cohort, and "
        "against ERBB2 copy number.\n"
        "- **Layer cards** [model inference, implemented]: contributions against a typical "
        "patient and gradient × input per feature, from the risk model.\n"
        f"- **Placeholders (not validated):** a subtype margin under {wb.LOW_MARGIN} is called "
        "borderline; ERBB2 counts as amplified at twice the tumor ploidy (by analogy with the "
        "ASCO/CAP ISH ratio of 2.0, not validated on ASCAT calls).\n"
        "- **Known failures:** the copy-number layer alone ranks patients worse than chance across "
        "hospitals; PAM50 calls depend on the centering reference (plain centering on this "
        "mostly ER-positive cohort moves published Luminal A tumors to Normal-like, Luminal B "
        "and HER2-enriched).\n"
        "- **Planned:** other signatures (recurrence-score-like, immune deconvolution) only from "
        "a validated model with a named reference population.")
    for name, ref in (data or {}).get("references", wb.REFERENCES).items():
        st.caption(f"{name}: {ref}")


def methods_section() -> None:
    """The workbench's validation for the Methods and validation page."""
    data = scores()
    st.subheader("Expression, methylation and protein scores")
    if not data:
        st.caption("Scores not computed here (app/omics_scores.json is missing).")
        return
    val = data["validation"]
    p = val["pam50"]
    plain = p["plain_centering"]
    st.markdown(
        f"{chip(wb.VALIDATED, 'green')} · PAM50 subtype by nearest centroid (Parker et al. "
        "2009; centroids from genefu), after centering each gene on its median over an "
        f"ER-balanced subset of this cohort ({p['reference_tumors']} tumors: every ER-negative "
        "one by IHC and as many ER-positive, drawn with seed 0; Zhao et al. 2015, Breast Cancer "
        "Res, doi:10.1186/s13058-015-0520-4).\n"
        f"- **Agreement with TCGA's published PAM50 calls:** {p['share']:.1%} of {p['n']} tumors "
        f"(Cohen's kappa {p['kappa']:.2f}); other random ER-positive draws (seeds 1–4): "
        + ", ".join(f"{a:.1%}" for a in p["other_draws"]) + ".\n"
        f"- **Plain centering on the whole cohort** (about three quarters ER-positive): "
        f"{plain['share']:.1%} (kappa {plain['kappa']:.2f}). This was run first; the ER-balanced "
        "reference, the published remedy for a cohort whose ER mix differs from PAM50's "
        "training set, was chosen after seeing it, on the same tumors, so the agreement above "
        "is not an independent test.")
    conf = pd.DataFrame(p["confusion"]).T.fillna(0).astype(int)
    conf = conf.rename(index=wb.SUBTYPES, columns=wb.SUBTYPES)
    st.dataframe(conf.rename_axis("published ↓ / this call →"), width="stretch")
    rows = []
    for name, kinds in val["receptors"].items():
        for kind, c in kinds.items():
            rows.append({"Receptor": name, "Measure": {"rna": "RNA", "protein": "RPPA",
                                                       "cn": "ERBB2 copy number"}[kind],
                         "Tumors": c["n"], "AUC": c.get("auc"),
                         "Cutoff (cohort percentile)": None if "cutoff_pct" not in c
                         else round(c["cutoff_pct"]),
                         "Sensitivity": c["sensitivity"], "Specificity": c["specificity"]})
    st.markdown("**Receptor levels against recorded status** (IHC; HER2 per ASCO/CAP with ISH)")
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption("Cutoffs maximize sensitivity + specificity on this cohort (in-sample, Youden): "
               "calibrated here, not validated elsewhere. ERBB2 amplification = at least twice the "
               "tumor ploidy, a placeholder. RPPA against RNA, Spearman: " + ", ".join(
                   f"{k} {r['spearman']:.2f} (n {r['n']})" for k, r in val["rppa_vs_rna"].items())
               + ". RNA is not protein.")

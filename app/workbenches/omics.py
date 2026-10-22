"""Expression, methylation and protein workbench (docs/WORKBENCHES.md §7) for one TCGA patient
file; also the clinical record card.

The shell calls ``render(pf, version=None, layer=None, case=None, demo=None)``: ``pf`` a
``muffle.workspace.PatientFile``, ``layer`` the data layer whose test was opened (its card comes
first), ``case`` the held-out ``muffle.demo.Case`` and ``demo`` the loaded ``muffle.demo.Demo``
(model, inputs, offsets). ``render`` draws in the current container only. ``methods_card()``
draws the validation numbers for the Methods and validation page.

Precomputed scores come from ``app/omics_scores.json`` (scripts/omics_scores.py and
omics_scores_2.py, offline, derived numbers only); contributions, top features and the what-if run
on the model here. Evidence types: recorded IHC, measured values and promoter betas are observed;
the subtype call, pathway and immune scores, contributions and the what-if are model inferences;
the hypermethylation index is a hypothesis. Review marks and pins go to the shell's stores under
``workspace.finding_key(pf, kind, ...)`` with kind "omics", "pathway_protein" or "methylation".
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
from muffle.report.case_tools import HYPOTHESIS, INFERENCE, OBSERVED
from muffle.workbench import omics as wb
from muffle.workbench.genomics import add_mark, mark_text
from muffle.workbench.grammar import CANNOT_SEE, CARD, EXPORT, chip, esc

APP = Path(__file__).resolve().parents[1]
STATUS_COLORS = {wb.AGREE: "green", wb.DISAGREE: "red", wb.NO_COMPARISON: "gray"}
CALLS = {-2: "deep deletion", -1: "loss", 0: "neutral", 1: "gain", 2: "amplification"}
UNITS = {"rna": "z-score of log(1 + TPM)", "methylation": "M-value", "protein": "z-score",
         "genomic": "copy-number call", "clinical": "z-score or 0/1 flag"}
MISSING = {  # what a missing layer limits
    "rna": "no subtype call, no pathway, proliferation, immune or stromal score, no RNA receptor "
           "check",
    "protein": "no RPPA check of ER, PR and HER2, no protein pathway scores",
    "genomic": "no copy-number view of ERBB2 or any other gene",
    "methylation": "no CpG features, no promoter methylation of ESR1, BRCA1 and the others, no "
                   "hypermethylation index",
}
METH_COLORS = {wb.CONSISTENT: "green", wb.NOT_CONSISTENT: "red", "unmethylated": "gray",
               wb.NO_COMPARISON: "gray"}
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
    return " ".join(chip(e) for e in (OBSERVED, INFERENCE, HYPOTHESIS) if e in evidence)




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


def round2_findings(pf, cs: dict | None, data: dict | None, feats: list[dict],
                    pic: dict | None) -> list[dict]:
    """The protein pathway scores, the RPPA antibodies they read (an antibody the model's protein
    layer also holds gets its RPPA story added to that feature, under the same key), promoter
    methylation, the immune and stromal signatures and the immune picture."""
    if not cs:
        return []
    out, rp = [], cs.get("rppa") or {}
    val = data.get("validation", {})
    for r in wb.rppa_rows(cs, data):
        out.append({"kind": "pathway_protein", "layer": "protein pathway", "name": r["pathway"],
                    "value": r["z"], "percentile": round(r["pct"]), "evidence": INFERENCE,
                    "row": r, "text": f"{r['pathway']} protein pathway RPPA {r['map'] or ''} "
                    + " ".join(f"{m['antibody']} {m['gene']}" for m in r["members"]),
                    "key": workspace.finding_key(pf, "pathway_protein", r["pathway"])})
    feat = {f["key"]: f for f in feats}
    for a, (z, p) in rp.get("antibodies", {}).items():
        gene = wb.ANTIBODY_GENES[a]
        info = {"antibody": a, "z": z, "pct": p, "gene": gene,
                "rna_pct": (cs.get("rna_pct") or {}).get(gene),
                "rho": (val.get("protein_vs_rna") or {}).get(a, {}).get("spearman"),
                "pathways": [(n, pw["members"].get(a)) for n, pw in wb.RPPA_PATHWAYS.items()
                             if a in pw["members"] or a in pw["also"]]}
        key = workspace.finding_key(pf, "omics", "protein", a)
        if key in feat:
            feat[key]["rppa"] = info
            feat[key]["text"] += " " + " ".join(n for n, _ in info["pathways"]) + " pathway"
            continue
        out.append({"kind": "antibody", "layer": "protein", "name": a, "value": z,
                    "percentile": round(p), "evidence": f"{OBSERVED} (value)", "rppa": info,
                    "text": f"protein RPPA {gene} " + " ".join(n for n, _ in info["pathways"])
                            + " pathway", "key": key})
    for x in wb.methylation_lines(cs):
        out.append({"kind": "methylation", "layer": "methylation", "name": x["gene"],
                    "value": x["beta"], "percentile": round(x["pct"]), "status": x["status"],
                    "evidence": f"{OBSERVED} (beta); call at a placeholder cutoff", "line": x,
                    "text": f"promoter {x['text']}",
                    "key": workspace.finding_key(pf, "methylation", x["gene"])})
    if cs.get("methylation"):
        beta, p = cs["methylation"]["index"]
        out.append({"kind": "methylation", "layer": "methylation", "name": "index",
                    "value": beta, "percentile": round(p), "evidence": HYPOTHESIS,
                    "text": "CpG island hypermethylation index promoter CIMP",
                    "key": workspace.finding_key(pf, "methylation", "index")})
    for name, (z, p), label in [*((k, v, f"{k} signature (ESTIMATE genes)") for k, v in
                                  (cs.get("estimate") or {}).items()),
                                *((("rppa_immune", rp["immune"][:2], "immune-cell proteins "
                                    "(RPPA)"),) if rp.get("immune") else ())]:
        out.append({"kind": "signature", "layer": "score", "name": label, "value": z,
                    "percentile": round(p), "evidence": INFERENCE, "signature": name,
                    "text": f"{label} immune stromal",
                    "key": workspace.finding_key(pf, "omics", "score", f"estimate_{name}"
                                                 if name != "rppa_immune" else name)})
    if pic:
        out.append({"kind": "immune", "layer": "immune", "name": "immune picture",
                    "value": pic["status"], "percentile": None, "status": pic["status"],
                    "evidence": pic["evidence"], "picture": pic,
                    "text": f"{pic['text']} immune TILs lymphocytes slide",
                    "key": workspace.finding_key(pf, "omics", "immune", "immune picture")})
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
    pic = wb.immune_picture(cs, wb.slide_immune(pf, cs, version)) if cs else None
    findings = (other_findings(pf, cs, lines, data) + round2_findings(pf, cs, data, feats, pic)
                + feats)
    by_key = {f["key"]: f for f in findings}
    reviews = st.session_state.setdefault("reviews", {})
    pins = st.session_state.setdefault("pins", {})
    spot = f"omics-spot-{pf.id}"
    tools = demo.tools(case)
    contrib = tools.modality_contributions()["log_risk_added_by_layer"]

    st.caption(f"{pf.title} · {v.label}")
    st.markdown(" ".join([chip(wb.IMPLEMENTED, "blue"),
                          *([chip(f"subtype call: {wb.VALIDATED}", "green")] if cs else []),
                          chip("immune deconvolution, recurrence-score-like signatures: "
                               "planned")]))
    st.caption("Data: TCGA-BRCA open access (UCSC Xena GDC hub; IHC from TCGA clinical data via "
               "cBioPortal) · scores: scripts/omics_scores.py and omics_scores_2.py, "
               f"{(data or {}).get('version', 'not computed')}, "
               f"{(data or {}).get('version2', 'round 2 not computed')} · protein pathways: "
               "Akbani et al. 2014 · CpG annotation: Illumina 450K manifest · immune and stromal "
               f"genes: ESTIMATE (Yoshihara et al. 2013) · model: {pf.model['name']} · methods, "
               "references and known failures in the card at the bottom and on the Methods and "
               "validation page.")
    if cs is None:
        st.warning("No precomputed subtype, pathway or receptor scores for this case: only the "
                   "model's view of each layer is shown below.")

    # overview: the three questions
    queue = wb.look_here(cs, lines, case.layers) + [
        x["what"] for x in wb.queue(pf, version)
        if x["key"].split("|")[1] in ("pathway_protein", "methylation")]
    if pic and pic["status"] == wb.DISAGREE:
        queue.append(f"Immune picture disagrees across layers; settles it: {pic['settle']}")
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
            rows = sorted(wb.rppa_rows(cs, data), key=lambda r: -r["pct"])
            if rows:
                bits.append(f"Protein pathways (RPPA): {rows[0]['pathway']} highest "
                            f"({ordinal(rows[0]['pct'])} percentile), {rows[-1]['pathway']} "
                            f"lowest ({ordinal(rows[-1]['pct'])})")
            if pic:
                bits.append(pic["short"].capitalize())
        if contrib:
            big = max(contrib, key=lambda m: abs(contrib[m]))
            bits.append(f"Layer moving the risk most: {wb.LAYERS[big]['name']} "
                        f"({contrib[big]:+.3f} log-risk vs a typical patient)")
        st.markdown("\n".join(f"- {b}" for b in bits) or "- none")
    with c:
        st.markdown("**Check by eye** · a queue, not a verdict")
        st.markdown("\n".join(f"{n}. {q}" for n, q in enumerate(queue, 1)) or "Nothing flagged.")

    # search
    query = st.text_input("Search this workbench: a gene (ESR1), a pathway (PI3K pathway, "
                          "proliferation), a status (disagree, methylated), immune",
                          key=f"omics-search-{pf.id}")
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

    # round 2: protein pathways, promoters, the immune picture
    st.markdown(f"#### Protein pathway activity (RPPA) {tag(INFERENCE)} {chip(wb.IMPLEMENTED)}")
    if cs and cs.get("rppa"):
        rppa_section(pf, cs, data, reviews, spot)
    else:
        st.caption(f"Needs the protein array ({MISSING['protein']}).")
    st.markdown(f"#### Promoter methylation {tag(OBSERVED)} {chip('placeholder cutoffs')} · "
                f"hypermethylation index {chip(HYPOTHESIS)}")
    if cs and cs.get("methylation"):
        methylation_section(cs, data)
    else:
        st.caption(f"Needs the methylation array ({MISSING['methylation']}).")
    st.markdown(f"#### Immune and stromal picture {tag(INFERENCE)}")
    if cs and cs.get("estimate"):
        immune_section(cs, data, pic, wb.slide_immune(pf, cs, version))
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
            "scores_round2": (data or {}).get("version2"),
            "placeholders": [f"PAM50 borderline margin < {wb.LOW_MARGIN}",
                             "ERBB2 amplified at >= 2x ploidy (ASCAT calls)",
                             *(f"{what}: {value}" for what, value in wb.PLACEHOLDERS)]}
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


def rppa_section(pf, cs: dict, data: dict, reviews: dict, spot: str) -> None:
    rows, val = wb.rppa_rows(cs, data), data.get("validation", {}).get("protein_vs_rna", {})
    df = pd.DataFrame([{"pathway": r["pathway"], "z": r["z"], "percentile": r["pct"],
                        "measured": f"{r['measured']} of {r['of']}",
                        "genomics map": r["map"] or "none", "members": r["hover"],
                        "direction": "above the cohort average" if r["z"] >= 0 else "below"}
                       for r in rows])
    st.altair_chart(alt.Chart(df).mark_bar().encode(
        x=alt.X("z:Q", title="pathway score (cohort z-score; 0 = cohort average)"),
        y=alt.Y("pathway:N", sort="-x", title=None, axis=alt.Axis(labelOverlap=False)),
        color=alt.Color("direction:N", legend=None, scale=alt.Scale(
            domain=["above the cohort average", "below"], range=[charts.BLUE, charts.ORANGE])),
        tooltip=["pathway", alt.Tooltip("z:Q", format="+.2f"),
                 alt.Tooltip("percentile:Q", format=".0f", title="cohort percentile"),
                 alt.Tooltip("measured:N", title="antibodies measured"), "genomics map",
                 alt.Tooltip("members:N", title="members (sign, z, percentile)")]
    ).properties(height=24 * len(df) + 30), width="stretch")
    st.caption(f"Akbani et al. 2014 (Nat Commun 5:3887, Supplementary Table 13): each antibody "
               "median-centered and scaled by its standard deviation over this cohort's "
               f"{data['rppa']['tumors']} RPPA tumors, the members' mean with negative regulators "
               "subtracted (−), z-scored again. Relative to this cohort; not validated as a "
               "measure of pathway activity. Hover a bar for its members. RPPA is a targeted "
               "array: a pathway is read only through the antibodies on it, most of them "
               f"phospho-sites, from a lysate of the whole sample. {wb.RPPA_ABSENT}.")
    gmap = wb.genomics_pathways(pf)
    name = st.selectbox("Open a pathway's antibodies", [r["pathway"] for r in rows],
                        key=f"omics-rppa-{pf.id}")
    r = next(x for x in rows if x["pathway"] == name)
    also = [a for a in wb.RPPA_PATHWAYS[name]["also"] if a in cs["rppa"]["antibodies"]]
    table = [*((m["antibody"], m["sign"]) for m in r["members"]), *((a, None) for a in also)]
    keys = [workspace.finding_key(pf, "omics", "protein", a) for a, _ in table]
    _table(pd.DataFrame([{
        "Antibody": a, "In the score": {1: "+", -1: "− (negative regulator)"}.get(s, "no (shown)"),
        "z": (cs["rppa"]["antibodies"].get(a) or [None])[0],
        "Cohort percentile": None if a not in cs["rppa"]["antibodies"]
        else round(cs["rppa"]["antibodies"][a][1]),
        "Gene": wb.ANTIBODY_GENES[a],
        "Gene RNA percentile": (cs.get("rna_pct") or {}).get(wb.ANTIBODY_GENES[a]),
        "Protein vs RNA (Spearman)": val.get(a, {}).get("spearman"),
        "Mark": (reviews.get(k) or {}).get("mark", "")} for (a, s), k in zip(table, keys,
                                                                             strict=True)]),
        keys, f"omics-rppa-table-{pf.id}-{name}", spot)
    g = gmap.get(r["map"]) if r["map"] else None
    if r["map"] is None:
        st.caption("The genomics workbench's pathway map has no group for this pathway.")
    elif g is None:
        st.caption(f"Genomics pathway map ({r['map']}): no copy number or sequencing in this "
                   "file.")
    else:
        st.markdown(f"{tag(OBSERVED)} {tag(HYPOTHESIS)} Genomics pathway map, **{r['map']}**: "
                    + (", ".join(esc(x) for x in g["altered"]) or "no gene altered")
                    + (f"; not measured: {', '.join(g['unknown'])}" if g["unknown"] else "")
                    + ". The alterations are observed; that they act on this pathway in this "
                      "tumor is a hypothesis, which the protein score above reads from another "
                      "side.")
    st.caption("Click a row for its Spot panel. Protein vs RNA: the antibody against its gene's "
               "RNA over the cohort (Methods and validation); below "
               f"{wb.WEAK_RHO} (placeholder) the two agree weakly, as most phospho-sites do: a "
               "phosphorylation is not in the RNA.")


def methylation_section(cs: dict, data: dict) -> None:
    mm = data["methylation_markers"]
    for x in wb.methylation_lines(cs):
        st.markdown(f"{chip(x['status'], METH_COLORS[x['status']])} **{x['gene']}** · "
                    f"{x['text']}")
    q = mm["quantiles"]
    df = pd.DataFrame([{"gene": g, "q05": q[g][1], "q25": q[g][5], "median": q[g][10],
                        "q75": q[g][15], "q95": q[g][19], "beta": b, "percentile": p,
                        "probes": n} for g, (b, p, n) in cs["methylation"]["genes"].items()])
    base = alt.Chart(df).encode(y=alt.Y("gene:N", title=None))
    st.altair_chart(alt.layer(
        base.mark_rule(color="#9aa5b1").encode(x=alt.X("q05:Q", title="mean promoter beta (0 "
                                                        "unmethylated, 1 fully methylated)",
                                                        scale=alt.Scale(domain=[0, 1])),
                                               x2="q95:Q"),
        base.mark_bar(color="#cfd8e3", height=10).encode(x="q25:Q", x2="q75:Q"),
        base.mark_tick(color="#52606d", thickness=2).encode(x="median:Q"),
        alt.Chart(pd.DataFrame({"cut": [wb.METHYLATED]})).mark_rule(
            color=charts.ORANGE, strokeDash=[4, 3]).encode(x="cut:Q"),
        base.mark_point(filled=True, size=90, color=charts.BLUE).encode(
            x="beta:Q", tooltip=["gene", alt.Tooltip("beta:Q", format=".2f"),
                                 alt.Tooltip("percentile:Q", format=".0f",
                                             title="cohort percentile"), "probes"]),
    ).properties(height=34 * len(df) + 40), width="stretch")
    beta, p = cs["methylation"]["index"]
    c1, c2 = st.columns([1, 2])
    c1.metric("CpG island hypermethylation index", f"{ordinal(p)} percentile",
              f"mean β {beta:.3f}", delta_color="off",
              help="Mean beta over the autosomal CpG-island promoter probes unmethylated in "
                   "normal breast (hypothesis).")
    c2.caption(f"{chip(HYPOTHESIS)} The index averages {mm['index_probes']:,} CpG-island promoter "
               f"probes unmethylated in normal breast. A high index is read as a CpG island "
               "methylator phenotype in the sense of Fang et al. 2011 (B-CIMP, linked there to "
               "lower metastatic risk); this mean is not their classifier and is not validated "
               "here.")
    st.caption(f"Dot: this tumor; bar: the cohort's middle half; line: 5th to 95th percentile "
               f"({mm['tumors']} tumors); dashed: the methylated cutoff, mean β {wb.METHYLATED} "
               "(placeholder). Probes: each gene's core promoter (TSS200 and first exon in the "
               f"Illumina 450K manifest; RASSF1A and p16INK4a for RASSF1 and CDKN2A) where "
               f"{mm['normal_samples']} normal breast samples of TCGA have a median β under "
               f"{wb.NORMAL_MAX} (placeholder): methylation there is not found in normal tissue. "
               f"RNA low at or under the {ordinal(wb.RNA_LOW)} percentile (placeholder). "
               "Bulk tumor DNA: normal and immune cells in the sample dilute a tumor's "
               "methylation.")
    model = sorted({c for c, a in mm.get("cpg_annot", {}).items()
                    if any(g in a.split("; ")[0].split(";") for g in wb.METHYLATION_GENES)})
    st.caption(f"Of the model's {len(mm.get('cpg_annot', {}))} CpGs, "
               + (f"{len(model)} lie in these genes: {', '.join(model)}." if model else
                  "none lies in these genes; its features are in the DNA methylation layer card."))


def _share(x) -> str:
    return "not scored" if x is None else f"{x:.0%}"


def immune_section(cs: dict, data: dict, pic: dict | None, secs: list[dict]) -> None:
    est, cyt, prot = cs["estimate"], cs["scores"]["immune"], (cs.get("rppa") or {}).get("immune")
    sets = data.get("immune_sets", {})
    cols = st.columns(4)
    cols[0].metric("Immune signature", f"{ordinal(est['immune'][1])} percentile",
                   f"z {est['immune'][0]:+.2f}", delta_color="off",
                   help=f"ESTIMATE's 141 immune genes ({sets.get('immune', {}).get('measured')} "
                        "measured), z-score averaging (Yoshihara et al. 2013).")
    cols[1].metric("Stromal signature", f"{ordinal(est['stromal'][1])} percentile",
                   f"z {est['stromal'][0]:+.2f}", delta_color="off",
                   help=f"ESTIMATE's 141 stromal genes ({sets.get('stromal', {}).get('measured')}"
                        " measured), z-score averaging.")
    cols[2].metric("Cytolytic activity", f"{ordinal(cyt[1])} percentile", f"z {cyt[0]:+.2f}",
                   delta_color="off", help="GZMA and PRF1 (Rooney et al. 2015).")
    if prot:
        cols[3].metric("Immune-cell proteins (RPPA)", f"{ordinal(prot[1])} percentile",
                       f"z {prot[0]:+.2f}", delta_color="off",
                       help=", ".join(data["rppa"]["immune_markers"]) + ": grouped here, not "
                            "from a paper.")
    if pic:
        color = STATUS_COLORS[pic["status"]]
        st.markdown(f"{chip(pic['status'], color)} {pic['text']}")
        st.caption(f"What would settle it: {pic['settle']}." + (
            " The report's tests-that-disagree list carries the slide-against-RNA discrepancy."
            if pic["crosstest"] else ""))
    if secs:
        st.dataframe(pd.DataFrame([{
            "Section": s["slide"], "Zone read": s["zone"] or "no front",
            "Lymphocyte tiles, second model": _share(s["til_share"]),
            "Lymphocyte tiles, tile head": _share(s["head_share"]),
            "Lymphocyte-like nuclei per mm²": s["nuclei_per_mm2"],
            "Slide pattern": s["pattern"]} for s in secs]), hide_index=True, width="stretch")
    val = data.get("validation", {}).get("immune", {})
    st.caption("Bulk RNA and the protein lysate mix tumor, stroma and immune cells; a high immune "
               "score is not a TILs count, and the stromal score reads stroma content. Across "
               f"the cohort the immune signature correlates with cytolytic activity at "
               f"{val.get('estimate_immune_vs_cytolytic', float('nan')):.2f} and with the immune-"
               f"cell proteins at {val.get('rppa_immune_vs_estimate_immune', float('nan')):.2f} "
               f"(Spearman). High from the {ordinal(wb.IMMUNE_HIGH)}, low to the "
               f"{ordinal(wb.IMMUNE_LOW)} percentile (placeholders). The slide numbers come from "
               "the slide workbench (tile classes and the second lymphocyte model, not validated "
               "on breast by a pathologist); one section is one plane.")


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
            if f.get("rppa"):
                antibody_story(f["rppa"], data)
        elif f["kind"] == "antibody":
            st.markdown(f"- **Layer:** {workspace.ASSAYS['protein']}, an antibody outside the "
                        "risk model's 100 most variable")
            antibody_story(f["rppa"], data)
        elif f["kind"] == "pathway_protein":
            r = f["row"]
            gmap = wb.genomics_pathways(pf).get(r["map"]) if r["map"] else None
            st.markdown(
                f"- **Score:** z {r['z']:+.2f}, the {ordinal(r['pct'])} percentile of this cohort; "
                f"{r['measured']} of its {r['of']} antibodies measured\n"
                "- **Method:** Akbani et al. 2014 (Supplementary Table 13): the members' cohort "
                "z-scores averaged, negative regulators subtracted, z-scored again\n"
                "- **Members:** " + esc(r["hover"]) + "\n"
                + (f"- **Genomics pathway map ({r['map']}):** "
                   + (", ".join(esc(x) for x in gmap["altered"]) or "no gene altered")
                   + " (observed alterations; the grouping is a hypothesis)\n" if gmap else "")
                + "- **What to check:** the antibodies' own values; phospho-sites move with "
                  "sample handling (time to freezing)\n"
                  "- **What it cannot see:** pathway proteins not on the array, where in the "
                  f"tissue the signal sits; RPPA reads a lysate of the whole sample. "
                  f"{wb.RPPA_ABSENT}.")
        elif f["kind"] == "methylation" and f["name"] == "index":
            mm = data["methylation_markers"]
            st.markdown(
                f"- **Index:** mean β {f['value']:.3f}, the {ordinal(f['percentile'])} percentile "
                f"of {mm['tumors']} tumors\n"
                f"- **Method:** mean beta over {mm['index_probes']:,} autosomal CpG-island "
                f"promoter probes (of {mm['index_candidates']:,}) whose median in TCGA's normal "
                f"breast is under {wb.NORMAL_MAX} (placeholder)\n"
                f"- **Reading:** {chip(HYPOTHESIS)} a high index as a CpG island methylator "
                "phenotype (Fang et al. 2011, B-CIMP); not their classifier, not validated here\n"
                "- **What it cannot see:** which genes are silenced (the promoter lines above "
                "with their RNA)")
        elif f["kind"] == "methylation":
            x, mm = f["line"], data["methylation_markers"]
            val = data["validation"]["methylation_vs_rna"].get(f["name"], {})
            probes = mm["probes"].get(f["name"], [])
            st.markdown(
                f"{x['text']}\n\n"
                f"- **Probes ({len(probes)} of {len(mm['candidates'].get(f['name'], []))} core-"
                "promoter CpGs, unmethylated in normal breast):** " + ", ".join(
                    f"{c} (normal median β {mm['normal_median'].get(c, float('nan')):.2f})"
                    for c in probes) + "\n"
                f"- **Why this gene:** {wb.METHYLATION_GENES[f['name']]}\n"
                f"- **Across the cohort:** {val.get('methylated', '?')} of {val.get('n', '?')} "
                f"tumors called methylated; their RNA's median percentile "
                f"{val.get('rna_pct_median_methylated') or '–'} against "
                f"{val.get('rna_pct_median_unmethylated', '–')} unmethylated; Spearman of beta "
                f"with RNA {val.get('spearman', float('nan')):+.2f}\n"
                f"- **Cutoffs:** methylated from mean β {wb.METHYLATED}, RNA low at or under the "
                f"{ordinal(wb.RNA_LOW)} percentile, probes kept under a normal median of "
                f"{wb.NORMAL_MAX} (all placeholders)\n"
                "- **What it cannot see:** single cells (the array reads the sample's DNA mixed), "
                "alleles; a promoter on the array is not every promoter of the gene")
        elif f["kind"] == "signature":
            genes = (data.get("immune_sets", {}).get(f["signature"]) or {}).get("genes", [])
            st.markdown(
                f"- **Score:** z {f['value']:+.2f}, the {ordinal(f['percentile'])} percentile of "
                "this cohort\n"
                + (f"- **Genes:** ESTIMATE's {len(genes)} (Yoshihara et al. 2013, Supplementary "
                   f"Data 1): {', '.join(genes[:25])} …\n" if genes else
                   f"- **Antibodies:** {', '.join(data['rppa']['immune_markers'])} (grouped "
                   "here, not from a paper)\n")
                + "- **Method:** z-score averaging over this cohort (not the ESTIMATE package's "
                  "single-sample enrichment)\n"
                  "- **What it cannot see:** which cells and where (the slide workbench); a TILs "
                  "count (a pathologist's read)")
        elif f["kind"] == "immune":
            p = f["picture"]
            st.markdown(f"{p['text']}  \n**Evidence:** {p['evidence']}  \n"
                        f"**What would settle it:** {p['settle']}")
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


def antibody_story(info: dict, data: dict) -> None:
    val = data.get("validation", {}).get("protein_vs_rna", {}).get(info["antibody"], {})
    rho = val.get("spearman")
    st.markdown(
        f"- **RPPA:** z {info['z']:+.2f} (median-centered, scaled by the cohort's standard "
        f"deviation), the {ordinal(info['pct'])} percentile of this cohort {tag(OBSERVED)}\n"
        f"- **Its gene's RNA ({info['gene']}):** " + (
            "not measured" if info["rna_pct"] is None else
            f"the {ordinal(info['rna_pct'])} percentile") + "\n"
        + (f"- **Protein against RNA over the cohort:** Spearman {rho:+.2f} ({val['n']} tumors)"
           + (f", weak agreement (under {wb.WEAK_RHO}, placeholder)" if rho < wb.WEAK_RHO
              else "") + "\n" if rho is not None else "")
        + "- **Pathways (Akbani et al. 2014):** " + (", ".join(
            f"{n} ({'+' if s == 1 else '−' if s == -1 else 'shown, not scored'})"
            for n, s in info["pathways"]) or "none") + "\n"
        "- **What it cannot see:** RPPA is a targeted array of selected antibodies read on a "
        "lysate of the whole sample: not where in the tissue the protein sits (IHC), nor the "
        "proteins without an antibody on it. RNA is not protein.")


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
        "- **Protein pathway scores** [model inference, implemented]: the ten RPPA pathway scores "
        "of Akbani et al. 2014 (members and signs from their Supplementary Table 13), each "
        "antibody median-centered and scaled over this cohort, signed mean, z-scored again. "
        "Checked: each antibody against its gene's RNA (Methods and validation); ER-alpha and "
        "HER2 protein against the recorded status (the receptor table). Not validated as "
        "pathway activity.\n"
        "- **Promoter methylation** [observed betas, placeholder calls]: core-promoter CpGs "
        "(Illumina 450K manifest: TSS200 and first exon) unmethylated in TCGA's normal breast, "
        "mean beta per gene, read beside the gene's RNA. Checked: methylation against RNA over "
        "the cohort per gene.\n"
        "- **Hypermethylation index** [hypothesis, implemented]: mean beta over the CpG-island "
        "promoter probes unmethylated in normal breast; a CIMP reading in the sense of Fang et "
        "al. 2011, not their classifier.\n"
        "- **Immune and stromal signatures** [model inference, implemented]: ESTIMATE's gene "
        "lists (Yoshihara et al. 2013) by z-score averaging, not the ESTIMATE package; the "
        "immune-cell antibodies on the array grouped here; the immune picture reads them with "
        "the slide workbench's lymphocytes by zone. A pathologist's TILs read settles it.\n"
        f"- **Placeholders (not validated):** a subtype margin under {wb.LOW_MARGIN} is called "
        "borderline; ERBB2 counts as amplified at twice the tumor ploidy (by analogy with the "
        "ASCO/CAP ISH ratio of 2.0, not validated on ASCAT calls); "
        + "; ".join(f"{what}: {value}" for what, value in wb.PLACEHOLDERS) + ".\n"
        "- **Known failures:** the copy-number layer alone ranks patients worse than chance across "
        "hospitals; PAM50 calls depend on the centering reference (plain centering on this "
        "mostly ER-positive cohort moves published Luminal A tumors to Normal-like, Luminal B "
        "and HER2-enriched).\n"
        "- **Known failures (round 2):** most phospho-antibodies and several total-protein "
        "antibodies agree weakly with their gene's RNA (Methods and validation); BRCA1's 450K "
        "probes in the manifest's CpG island lie upstream of its core promoter and are "
        "methylated in most tumors, so the island is not required of a gene's probes.\n"
        "- **Planned:** other signatures (recurrence-score-like, immune deconvolution) only from "
        "a validated model with a named reference population.")
    for name, ref in (data or {}).get("references", wb.REFERENCES).items():
        st.caption(f"{name}: {ref}")


def methods_card() -> None:
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
    if "protein_vs_rna" not in val:
        return
    pv = val["protein_vs_rna"]
    phospho = [a for a in val["protein_vs_rna_weak"] if "_p" in a]
    total = [a for a in val["protein_vs_rna_weak"] if "_p" not in a]
    rp = data["rppa"]
    st.markdown(
        f"{chip(wb.IMPLEMENTED)} · **Protein pathway scores** (RPPA; Akbani et al. 2014, Nat "
        "Commun 5:3887, the members and signs of their Supplementary Table 13): ten pathways on "
        f"{rp['tumors']} tumors, each antibody median-centered and scaled by its standard "
        "deviation over this cohort, the members' signed mean z-scored again. "
        + (f"Left out for coverage under {rp['min_coverage']:.0%}: {', '.join(rp['left_out'])}. "
           if rp["left_out"] else "Every member is measured in at least half of the tumors. ")
        + "Not validated as pathway activity: what can be checked is below.")
    st.markdown(f"**Protein versus RNA agreement** · each antibody against its gene's RNA over "
                f"the cohort (Spearman; {len(pv)} antibodies)")
    st.dataframe(pd.DataFrame([{"Antibody": a, "Gene": r["gene"], "Spearman": r["spearman"],
                                "Tumors": r["n"],
                                "Agreement": "weak" if r["spearman"] < wb.WEAK_RHO else ""}
                               for a, r in sorted(pv.items(), key=lambda x: -x[1]["spearman"])]),
                 hide_index=True, width="stretch", height=280)
    st.caption(f"Weak (under {wb.WEAK_RHO}, placeholder): {len(phospho)} phospho-site antibodies, "
               "expected, since a phosphorylation is not in the RNA, and "
               f"{len(total)} total-protein antibodies: {', '.join(total)}. Ki-67 is not on the "
               "array. ER-alpha and HER2 protein against the recorded status: the receptor table "
               "above (AUC " + ", ".join(
                   f"{k} {val['receptors'][k]['protein']['auc']:.2f}" for k in ("ER", "HER2"))
               + ").")
    mm, mv = data["methylation_markers"], val["methylation_vs_rna"]
    st.markdown(
        f"{chip(wb.IMPLEMENTED)} · **Promoter methylation** of six genes: each gene's "
        "core-promoter CpGs (Illumina 450K v1.2 manifest, TSS200 and first exon; RASSF1A and "
        f"p16INK4a for RASSF1 and CDKN2A) whose median beta over TCGA's {mm['normal_samples']} "
        f"normal breast samples is under {wb.NORMAL_MAX} (placeholder), averaged per tumor; "
        f"methylated from a mean of {wb.METHYLATED} (placeholder). The check: does a methylated "
        "promoter go with low RNA across the cohort?")
    st.dataframe(pd.DataFrame([{
        "Gene": g, "CpGs kept / core promoter": f"{len(mm['probes'][g])} / "
                                                f"{len(mm['candidates'][g])}",
        "Tumors": r["n"], "Methylated": r["methylated"],
        "RNA percentile, methylated (median)": r["rna_pct_median_methylated"],
        "RNA percentile, unmethylated (median)": r["rna_pct_median_unmethylated"],
        "Spearman, beta vs RNA": r["spearman"]} for g, r in mv.items()]),
        hide_index=True, width="stretch")
    st.caption(f"{chip(HYPOTHESIS)} Hypermethylation index: mean beta over "
               f"{mm['index_probes']:,} of {mm['index_candidates']:,} autosomal CpG-island "
               "promoter probes, those unmethylated in normal breast; a CIMP reading in the sense "
               "of Fang et al. 2011 (B-CIMP), not their classifier.")
    iv, sets = val["immune"], data["immune_sets"]
    st.markdown(
        f"{chip(wb.IMPLEMENTED)} · **Immune and stromal signatures**: ESTIMATE's 141-gene "
        f"immune and stromal lists (Yoshihara et al. 2013, Supplementary Data 1; "
        f"{sets['immune']['measured']} and {sets['stromal']['measured']} measured) by z-score "
        "averaging over this cohort, not the ESTIMATE package. Across "
        f"{iv['rna_tumors']} tumors the immune signature correlates with cytolytic activity at "
        f"{iv['estimate_immune_vs_cytolytic']:.2f} and with the stromal one at "
        f"{iv['estimate_immune_vs_stromal']:.2f}; with the RPPA immune-cell antibodies "
        f"({', '.join(rp['immune_markers'])}, grouped here) at "
        f"{iv['rppa_immune_vs_estimate_immune']:.2f} ({iv['n']} tumors; Spearman). None is a "
        "TILs count: a pathologist's read settles the immune picture.")

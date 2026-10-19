"""MuFFLe++ demo: a federated tumor-board assistant.

streamlit run app/streamlit_app.py -- --ckpt outputs/tcga_fedavg.pt --data data/tcga_brca
streamlit run app/streamlit_app.py -- --ckpt outputs/centralized.pt --data data/synthetic
streamlit run app/streamlit_app.py -- --bundle outputs/demo_bundle.pt     # the hosted setup

Without the checkpoint and cohort (the hosted demo), it loads a demo bundle instead: --bundle or
MUFFLE_BUNDLE (a path or URL; default: the GitHub release asset). For a private repo's release,
set GITHUB_TOKEN to a token that can read the repo.

Four tabs: Patient timeline (a synthetic patient whose 12-month risk is re-predicted at each
event by the MSK-CHORD models; app/timeline_synthetic.json from `make demo-timeline`), Case
review (one held-out patient: risk, what drives it, a what-if for missing data layers, and the
Nemotron case agent's note), Federation (the simulated hospitals and the results), How it works.
Live notes are capped per session (DEMO_LIVE_NOTES_PER_SESSION, default 5); saved notes
(app/saved_notes.json, scripts/save_demo_notes.py) show without a key or once the cap is reached.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from datetime import date
from pathlib import Path

APP = Path(__file__).parent
if str(APP.parent / "src") not in sys.path:  # hosted: the repo isn't pip-installed
    sys.path.insert(0, str(APP.parent / "src"))

import charts  # noqa: E402
import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
import torch  # noqa: E402

from muffle.demo import build_demo, fetch_bundle, load_bundle, ordinal  # noqa: E402
from muffle.explain import modality_contributions, risk_percentile  # noqa: E402
from muffle.report import civic  # noqa: E402
from muffle.report.grounding import describe  # noqa: E402
from muffle.report.nemotron import (  # noqa: E402
    DEFAULT_MODEL,
    WRITER_MODEL,
    CaseReport,
    model_name,
    run_case_agent,
    tavily_search,
)

REPO = "https://github.com/ps131-cell/muffle-plus-plus"
BUNDLE_URL = f"{REPO}/releases/download/demo-bundle-v1/demo_bundle.pt"
LAYER_NAMES = {"clinical": "Clinical", "rna": "RNA expression", "genomic": "Copy number",
               "methylation": "Methylation", "protein": "Protein"}

p = argparse.ArgumentParser()
p.add_argument("--ckpt", default="outputs/tcga_fedavg.pt")
p.add_argument("--data", default="data/tcga_brca")
p.add_argument("--cancer", default="breast")
p.add_argument("--n-clients", type=int, default=3)
p.add_argument("--config", default=None, help="only for checkpoints without a stored config")
p.add_argument("--notes", default=str(APP / "saved_notes.json"))
p.add_argument("--bundle", default=os.getenv("MUFFLE_BUNDLE"),
               help="demo bundle path or URL (default when the data isn't here: the release)")
args, _ = p.parse_known_args()


@st.cache_resource(show_spinner="Loading the model and the held-out patients…")
def load(ckpt: str, data: str, n_clients: int, config: str | None, cancer: str, notes: str,
         bundle: str | None):
    if bundle is None and Path(ckpt).exists() and (Path(data) / "cohort.npz").exists():
        demo = build_demo(ckpt, data, n_clients, config, cancer)
    else:
        source = bundle or BUNDLE_URL
        if source.startswith("https://"):
            source = fetch_bundle(source, Path(tempfile.gettempdir()) / "muffle_demo_bundle.pt",
                                  os.getenv("GITHUB_TOKEN"))
        demo = load_bundle(source)
    if Path(notes).exists():
        demo.notes = {int(k): v for k, v in json.loads(Path(notes).read_text()).items()}
    return demo


@st.cache_data
def results() -> dict | None:
    path = APP / "results_tcga_brca.json"
    return json.loads(path.read_text()) if path.exists() else None


@st.cache_data
def timeline() -> dict | None:
    path = APP / "timeline_synthetic.json"
    return json.loads(path.read_text()) if path.exists() else None


def secrets_to_env() -> None:
    """Streamlit Community Cloud keeps the app's secrets in st.secrets; copy the top-level
    values into the environment, where the agent and the spending cap read them. Real
    environment variables win; without a secrets file (local runs use .env) nothing happens."""
    try:
        items = dict(st.secrets)
    except Exception:  # no secrets.toml
        return
    for key, value in items.items():
        if isinstance(value, (str, int, float)) and key not in os.environ:
            os.environ[key] = str(value)


st.set_page_config(page_title="MuFFLe++ tumor-board assistant", page_icon="🧬", layout="wide")
secrets_to_env()
demo = load(args.ckpt, args.data, args.n_clients, args.config, args.cancer, args.notes,
            args.bundle)
LIVE = bool(os.getenv("NEBIUS_API_KEY"))
SEARCH = tavily_search if os.getenv("TAVILY_API_KEY") else None
# CIViC treatment evidence, only where its table is already cached (the hosted bundle has none)
EVIDENCE = civic.evidence if civic.load_table(download=False) is not None else None
CAP = int(os.getenv("DEMO_LIVE_NOTES_PER_SESSION", "5"))
st.session_state.setdefault("live_used", 0)
st.session_state.setdefault("reports", {})  # cohort index -> (CaseReport, source)

# --- sidebar: what is running ----------------------------------------------------------------
with st.sidebar:
    st.markdown("### MuFFLe++")
    st.caption("Federated multi-omic survival model + a Nemotron case agent.")
    st.markdown(
        f"**Model** · FedAvg across {len(demo.sites)} simulated hospitals (NVIDIA FLARE)  \n"
        f"**Held-out C-index** · {demo.c_index:.3f}  \n"
        f"**Case agent** · {'live' if LIVE else 'offline (no key)'}: "
        f"{model_name(DEFAULT_MODEL)} plans, {model_name(WRITER_MODEL)} writes, on Nebius "
        f"Token Factory  \n"
        f"**Literature** · {'Tavily search on' if SEARCH else 'off (no Tavily key)'}")
    budget_slot = st.empty()  # filled at the end, after this run's live note (if any)
    st.caption(f"[Source code]({REPO}) · research prototype on public TCGA data, not for "
               "clinical use.")

st.title("MuFFLe++ · federated tumor-board assistant")
st.markdown(
    f"{len(demo.sites)} simulated hospitals (groups of TCGA tissue source sites) train one "
    "survival model **without sharing patient data**. "
    "For a patient, an NVIDIA Nemotron agent asks the model what drives the risk, looks up the "
    "literature, and writes a tumor-board note that cites only what its tools returned.")

timeline_tab, case_tab, fed_tab, how_tab = st.tabs(
    ["Patient timeline (synthetic)", "Case review", "Federation", "How it works"])

# --- Patient timeline (synthetic) ------------------------------------------------------------
with timeline_tab:
    tl = timeline()
    if tl is None:
        st.info("The timeline patient isn't built here (`make demo-timeline`, needs MSK-CHORD).")
    else:
        st.warning(f"**{tl['patient_id']} is synthetic.** {tl['notice']}", icon="🧪")
        events, updates = tl["events"], tl["updates"]
        i = st.select_slider(
            "Record up to", options=list(range(len(events))), value=len(events) - 1,
            format_func=lambda k: f"month {events[k]['month']} · {events[k]['kind']}",
            help="Months after the first tumor sequencing. Move back to see the record grow.")
        st.markdown(f"**Latest event (observed):** month {events[i]['month']} · "
                    f"{events[i]['text']}")
        scored = [u for u in updates[: i + 1] if "risk" in u]
        if not scored:
            st.caption("No risk estimate yet: the models' clock starts at the first tumor "
                       "sequencing (month 0).")
        else:
            u = scored[-1]
            m = tl["models"][str(u["landmark"])]
            st.caption(f"**Model inference** · {tl['task']}, from the month-{u['landmark']} "
                       "MSK-CHORD models")
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("12-month risk", f"{u['risk']:.0%}",
                      None if "previous" not in u else
                      f"{100 * (u['risk'] - u['previous']):+.0f} points",
                      delta_color="inverse", help=tl["task"].capitalize() + ".")
            c2.metric("Range, 5 models", "{:.0%}–{:.0%}".format(*u["risk_range"]),
                      help="The same model trained on five different 80% splits (seeds 0–4).")
            c3.metric("Diagnosis only", f"{u['baseline']:.0%}",
                      help="Baseline: stage, HR and HER2 alone, same patients and learner.")
            c4.metric("Model AUROC", f"{m['auroc'][0]:.2f}",
                      help=f"Held-out AUROC of the month-{u['landmark']} model on MSK-CHORD, "
                           f"mean of 5 seeds (diagnosis only: {m['baseline_auroc'][0]:.2f}; "
                           f"{m['n']:,} patients, event rate {m['event_rate']:.0%}).")
            st.altair_chart(charts.risk_timeline(updates[: i + 1], events, u["month"]),
                            width="stretch")

        obs_col, inf_col = st.columns(2)
        with obs_col:
            st.markdown("**Observed** · what the record says so far")
            st.markdown("\n".join(f"- **{k}:** {v}" for k, v in updates[i]["observed"]))
        with inf_col:
            st.markdown("**Model inference** · what changed and why")
            if scored:
                st.markdown(scored[-1]["summary"])
                if scored[-1].get("changes"):
                    st.altair_chart(charts.contributions(
                        {c["what"]: c["points"] for c in scored[-1]["changes"]},
                        title="change in risk (points)", fmt="+.0f"), width="stretch")
                    st.caption("One change at a time against the previous record, scored by "
                               "the current model; changes interact, so the rest is shown.")
        with st.container(border=True):
            st.markdown("**Hypotheses and evidence** · for clinician review")
            drivers = [g for g in tl["evidence"] if events[i]["month"] >= 0]
            for name in drivers:
                for e in tl["evidence"][name]:
                    st.markdown(f"- **{name}** · {e['therapies']} · CIViC level "
                                f"{e['evidence_level']} ({e['level_meaning']}), "
                                f"{e['significance'].lower()} · [{e['citation']}]({e['url']})")
            st.caption("CIViC (CC0) evidence for the observed driver, not a recommendation."
                       if drivers else "No sequenced drivers yet, so no treatment evidence.")

        with st.expander("Event log (observed)"):
            st.dataframe(pd.DataFrame(events[: i + 1]), hide_index=True, width="stretch")
        st.caption(tl["model_note"] + " Some features reflect care, not only biology (how "
                   "often labs and treatments are recorded); see docs/longitudinal.md.")

# --- Case review -----------------------------------------------------------------------------
with case_tab:
    cases = sorted(demo.cases, key=lambda c: (c.index not in demo.notes, -c.percentile))
    shown = (f"{len(cases)} patients" if len(cases) == demo.heldout_patients
             else f"{len(cases)} of the {demo.heldout_patients} patients")
    case = st.selectbox(
        f"Held-out patient ({shown} the model never trained on)", cases,
        format_func=lambda c: ("★ " if c.index in demo.notes else "") + c.label,
        help="Each hospital's validation split. ★ = a saved note is available.")

    x, mask = demo.inputs(case)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Risk percentile", ordinal(case.percentile),
              help="Share of all patients with a lower predicted risk.")
    c2.metric("Risk group", case.group.capitalize(), help="Cohort tertiles of predicted risk.")
    c3.metric("Simulated hospital", case.site,
              help="The FL client this patient belongs to: a group of TCGA tissue source sites.")
    c4.metric("Data layers", f"{len(case.layers)} of {len(demo.model.names)}",
              help="Missing: " + (", ".join(case.missing) or "none"))

    left, right = st.columns(2)
    with left:
        st.markdown("**Where this patient sits among all patients**")
        st.altair_chart(charts.risk_position(demo.cohort_risks, case.log_risk,
                                             f"{ordinal(case.percentile)} percentile"),
                        width="stretch")
    with right:
        st.markdown("**What drives this patient's risk**")
        _, contrib = modality_contributions(demo.model, x, mask, demo.offsets)
        st.altair_chart(charts.contributions(
            {LAYER_NAMES.get(m, m): v for m, v in contrib.items()}), width="stretch")
        st.caption("Each layer's effect on this patient's predicted log-risk, compared with its "
                   "effect on a typical patient in the cohort.")

    with st.expander("What if a data layer were missing?"):
        st.caption("Hospitals collect different data. MuFFLe++ masks a missing layer instead of "
                   "dropping the patient, so the same model scores everyone.")
        hide = st.pills("Hide layers", case.layers, selection_mode="multi",
                        format_func=lambda m: LAYER_NAMES.get(m, m), key=f"hide-{case.index}")
        if hide and len(hide) == len(case.layers):
            st.warning("Keep at least one layer.")
        elif hide:
            hx, hmask = demo.inputs(case, hide)
            with torch.no_grad():
                risk = demo.model(hx, hmask).item()
            pct = risk_percentile(risk, demo.cohort_risks)
            st.metric("Risk percentile without " + ", ".join(LAYER_NAMES.get(m, m) for m in hide),
                      ordinal(pct), f"{int(pct) - int(case.percentile):+d} percentile points",
                      delta_color="inverse")

    st.subheader("Tumor-board note")
    saved = demo.notes.get(case.index)
    can_live = LIVE and st.session_state.live_used < CAP
    b1, b2, _ = st.columns([2, 2, 3])
    write = b1.button("Write the note with Nemotron", type="primary", disabled=not can_live,
                      help=None if can_live else ("Set NEBIUS_API_KEY for live notes." if not LIVE
                                                  else "This session's live notes are used up."))
    show_saved = b2.button("Show the saved note", disabled=saved is None)
    if not can_live:
        st.caption("Live notes are off here; ★ patients have a saved note from the live agent."
                   if saved is None or not LIVE else
                   "This session's live notes are used up; showing saved notes.")

    if write:
        with st.status("Nemotron is working on the case…", expanded=True) as status:
            report = run_case_agent(demo.tools(case, SEARCH, EVIDENCE), on_step=status.write)
            status.update(label="Note ready", state="complete", expanded=False)
        if report.mode != "offline":
            st.session_state.live_used += 1
        st.session_state.reports[case.index] = (report, "live")
    elif show_saved and saved:
        st.session_state.reports[case.index] = (CaseReport.from_dict(saved["report"]),
                                                f"saved on {saved['created']}")

    if case.index in st.session_state.reports:
        report, source = st.session_state.reports[case.index]
        note, trace = st.columns([3, 2])
        with note:
            st.markdown(report.text)
            if report.mode != "offline":
                if report.issues:
                    st.warning("Grounding check: not found in the tool outputs: "
                               + describe(report.issues))
                else:
                    st.success("Grounding check: every number, gene and link in this note comes "
                               "from the tool outputs" + (" (rewritten once after the check)."
                                                          if report.revised else "."))
            header = (f"# MuFFLe++ tumor-board note: case {case.index}\n\n"
                      f"_{case.label} · {source} · written by {model_name(report.writer)}; "
                      "research prototype, not a diagnosis._\n\n")
            st.download_button("Download the note (Markdown)", header + report.text,
                               file_name=f"muffle_case_{case.index}.md", mime="text/markdown")
        with trace:
            st.markdown("**How the agent got there**")
            st.caption({
                "agent": f"{model_name(report.model)} chose these tool calls; "
                         f"{model_name(report.writer)} wrote the note · {report.tokens:,} tokens "
                         f"· {source}",
                "fixed plan": f"Tool calling unavailable: the tools ran in a fixed order and "
                              f"{model_name(report.writer)} wrote the note · {source}",
                "offline": "Offline: the tools ran in a fixed order and a template wrote the "
                           "note.",
            }[report.mode])
            for line in report.notes:
                st.caption(line)
            for n, call in enumerate(report.trace, 1):
                shown = ", ".join(f"{k}={json.dumps(v)}" for k, v in call.arguments.items())
                flag = " ⚠️" if "error" in call.result else ""
                with st.expander(f"{n}. {call.name}({shown}){flag}"):
                    st.json(call.result)
            st.caption("Only these derived numbers and gene names were sent to Token Factory; "
                       "the patient's omics never leave the hospital.")

# --- Federation ------------------------------------------------------------------------------
with fed_tab:
    st.subheader(f"{len(demo.sites)} simulated hospitals, one model, no shared patient data")
    left, right = st.columns([2, 3])
    with left:
        dot = ["digraph { rankdir=LR; bgcolor=transparent; size=\"5,3\"; node [shape=box, "
               "style=rounded, fontname=Helvetica, fontsize=11]; edge [fontname=Helvetica, "
               "fontsize=9];",
               'server [label="NVIDIA FLARE server\\nFedAvg", shape=box, style="rounded,bold"];']
        for s in demo.sites:
            dot.append(f'"{s.name}" [label="{s.name} (simulated)\\n{s.patients} patients\\n'
                       f'data stays here"];')
            dot.append(f'"{s.name}" -> server [label="weights", dir=both];')
        st.graphviz_chart("\n".join(dot) + "}", width="content")
    with right:
        table = pd.DataFrame([{
            "Hospital": s.name, "Patients": s.patients, "Deaths": s.deaths,
            "Held out": s.heldout,
            **{LAYER_NAMES.get(m, m): 100 * s.coverage[m] for m in demo.model.names
               if m != "clinical"},
        } for s in demo.sites])
        st.dataframe(table, hide_index=True, column_config={
            LAYER_NAMES.get(m, m): st.column_config.ProgressColumn(
                LAYER_NAMES.get(m, m), format="%.0f%%", min_value=0, max_value=100, width="small")
            for m in demo.model.names if m != "clinical"})
        st.caption("Bars: share of each hospital's patients with that data layer. The hospitals "
                   "are simulated: TCGA tissue source sites grouped into three FL clients, so "
                   "the data gaps are real.")

    res = results()
    if res and demo.names:  # real data (synthetic cohorts have no gene names)
        st.subheader("Does federated training work?")
        main = [m for m in res["methods"] if m["group"] == "main"]
        st.altair_chart(charts.results(main), width="stretch")
        by = {m["method"]: m for m in res["methods"]}
        st.markdown(
            f"- **Federated ≈ pooled.** FedAvg reaches {by['fedavg_residual']['mean']:.3f} on "
            f"a hospital it never saw, against {by['residual']['mean']:.3f} when the other "
            "hospitals' patients are pooled in one place, without moving any patient data.\n"
            f"- **Better than going it alone.** A model trained at one hospital scores "
            f"{by['local_only']['mean']:.3f}.\n"
            f"- **Honest baseline.** Clinical data alone (stage, age, T/N/M) scores "
            f"{by['only_clinical']['mean']:.3f}: on overall survival in breast cancer the "
            "omic layers don't add signal beyond it yet, so the model anchors on clinical data "
            "and lets omics correct it.")
        st.caption(res["protocol"] + ".")
        with st.expander("Each omic layer on its own"):
            single = [m for m in res["methods"] if m["group"] == "single layer"]
            st.dataframe(pd.DataFrame(single)[["label", "mean", "sd"]].rename(
                columns={"label": "Layer", "mean": "C-index", "sd": "sd"}), hide_index=True)
            st.caption("Copy number alone ranks patients worse than chance across hospitals "
                       "(below 0.5): a sign of site and batch effects.")

    st.subheader("Risk groups on the held-out patients")
    left, right = st.columns([3, 2])
    with left:
        st.altair_chart(charts.survival_by_group(demo.km), width="stretch")
    with right:
        st.metric("Held-out C-index (mean of hospitals)", f"{demo.c_index:.3f}")
        st.caption(" · ".join(f"{s} {c:.3f}" for s, c in demo.c_index_by_site.items()))
        st.caption(f"{demo.heldout_patients} held-out patients, "
                   f"{demo.heldout_deaths} deaths. Curves stop at 5 years, where "
                   "fewer than 20 patients per group remain. The risk groups rank patients "
                   "well; they are not calibrated probabilities of death.")

# --- How it works ----------------------------------------------------------------------------
with how_tab:
    st.markdown(f"""
#### 1 · Federated training (NVIDIA FLARE)
Each hospital trains on its own patients' copy number, RNA expression, methylation, protein
and clinical data; only model weights go to the FLARE server, which averages them (FedAvg) and
sends the global model back. A hospital that never measured a layer still takes part: that
layer is masked, and training randomly hides layers so the model copes. The model first learns
a clinical risk, then lets the omic layers correct it by an amount chosen on hospitals it
wasn't trained on.

#### 2 · The case agent (NVIDIA Nemotron on Nebius Token Factory)
- **{model_name(DEFAULT_MODEL)} plans.** It calls our tools: the patient's risk and
  percentile, how much each data layer moves it, the top genes of a layer, and Tavily search
  for publications or clinical trials on those genes.
- **{model_name(WRITER_MODEL)} writes** the note from the tool outputs (Summary, Drivers,
  Caveats, Literature).
- **A grounding check** (plain code, no LLM) looks for any number, gene or link in the note
  that no tool returned. If it finds one, the writer gets one rewrite; anything left is shown.
- **Privacy:** only derived numbers (risk, percentile, contributions, attribution scores) and
  gene names are sent to Token Factory, never a patient's omics values.

#### 3 · Limits
- Research prototype on public TCGA-BRCA data (1,064 patients, overall survival). Not for
  clinical use.
- Omics don't beat clinical data alone on this endpoint yet.
- The model ranks patients; its absolute risks are only roughly calibrated. It is weaker for
  patients under 50 and within a single stage.
- The three "hospitals" are TCGA tissue source sites, simulated with the NVFlare simulator.

[Source code, results and decisions]({REPO}) · built for the Nebius × NVIDIA Global AI
Hackathon, {date.today().year}.
""")

if LIVE:
    notes_left = max(0, CAP - st.session_state.live_used)
    budget_slot.progress(notes_left / CAP if CAP else 0,
                         text=f"Live notes left this session: {notes_left} of {CAP}")

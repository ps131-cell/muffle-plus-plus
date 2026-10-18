"""MuFFLe++ demo: federated prognosis + a Nemotron case agent that writes the report.

streamlit run app/streamlit_app.py -- --ckpt outputs/centralized.pt --data data/synthetic
streamlit run app/streamlit_app.py -- --ckpt outputs/tcga_fedavg.pt --data data/tcga_brca
(a raw NVFlare FL_global_model.pt also works with --config <the yaml it was trained with>)
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import torch

from muffle.data.dataset import MultiOmicDataset, feature_names
from muffle.explain import modality_contributions, risk_percentile
from muffle.report.case_tools import CaseTools
from muffle.report.grounding import describe
from muffle.report.nemotron import run_case_agent, tavily_search
from muffle.train_local import heldout_c_index, load_model

p = argparse.ArgumentParser()
p.add_argument("--ckpt", default="outputs/centralized.pt")
p.add_argument("--data", default="data/synthetic")
p.add_argument("--cancer", default="breast")
p.add_argument("--n-clients", type=int, default=3)
p.add_argument("--config", default=None, help="only for checkpoints without a stored config")
args, _ = p.parse_known_args()


@st.cache_resource
def load(ckpt: str, data: str, n_clients: int, config: str | None):
    model, cfg = load_model(Path(ckpt), config)
    ds = MultiOmicDataset(Path(data) / "cohort.npz", cfg["modalities"])
    # gene/feature names (names_<modality>) for TCGA; synthetic data has none
    names = feature_names(Path(data) / "cohort.npz", cfg["modalities"])
    with torch.no_grad():
        risks = model(ds.x, ds.mask).numpy()
    return model, ds, risks, heldout_c_index(model, Path(data), n_clients, cfg), names


st.set_page_config(page_title="MuFFLe++", layout="wide")
st.title("MuFFLe++ — federated multi-omic prognosis")
st.caption("Research prototype. Not for clinical use.")

model, ds, risks, heldout, names = load(args.ckpt, args.data, args.n_clients, args.config)
c = float(np.mean(list(heldout.values())))
col1, col2, col3 = st.columns(3)
col1.metric("Patients", len(ds))
col2.metric("C-index (held-out)", f"{c:.3f}",
            help="Mean over the per-site validation splits that `make compare` reports.")
col3.metric("Modalities", ", ".join(model.names))
st.caption("Held-out C-index per site: "
           + " · ".join(f"{s} {v:.3f}" for s, v in heldout.items()))

st.subheader("Risk groups")
groups = pd.qcut(risks, 3, labels=["low", "medium", "high"])
months = np.linspace(0, float(np.quantile(ds.time, 0.9)), 40)
km = {}
for g in ["low", "medium", "high"]:
    t, e = ds.time.numpy()[groups == g], ds.event.numpy()[groups == g]
    surv, s = [], 1.0
    for i, m in enumerate(months):
        prev = months[i - 1] if i else 0
        at_risk = (t >= prev).sum()
        d = ((t >= prev) & (t < m) & (e == 1)).sum()
        s *= 1 - d / at_risk if at_risk else 1
        surv.append(s)
    km[g] = surv
st.line_chart(pd.DataFrame(km, index=np.round(months, 1)), x_label="months",
              y_label="survival (approx. Kaplan-Meier)")

st.subheader("Patient report")
i = st.number_input("Patient index", 0, len(ds) - 1, int(np.argmax(risks)))
x = {m: v[i : i + 1] for m, v in ds.x.items()}
mask = ds.mask[i : i + 1]
base, contrib = modality_contributions(model, x, mask)
pct = risk_percentile(base, risks)
avail = [m for j, m in enumerate(model.names) if mask[0, j] > 0]
st.write(f"Available data: {', '.join(avail)} · risk percentile **{pct:.0f}**")
st.bar_chart(pd.Series(contrib, name="log-risk added by layer"))

if st.button("Write report with Nemotron"):
    tools = CaseTools(model, x, mask, risks, args.cancer, names, c,
                      search=tavily_search if os.getenv("TAVILY_API_KEY") else None)
    with st.spinner("Nemotron is working on the case…"):
        report = run_case_agent(tools)
    left, right = st.columns([3, 2])
    left.markdown(report.text)
    if report.mode != "offline":
        if report.issues:
            left.warning("Grounding check: not found in the tool outputs: "
                         + describe(report.issues))
        else:
            left.success("Grounding check: every number, gene and link in this note comes from "
                         "the tool outputs" + (" (rewritten once after the check)."
                                               if report.revised else "."))
    right.markdown("**Tool calls**")
    right.caption({
        "agent": f"Nemotron `{report.model}` chose these calls; `{report.writer}` wrote the "
                 f"note · {report.tokens} tokens",
        "fixed plan": f"Tool calling unavailable: tools ran in a fixed order, `{report.writer}` "
                      "wrote the note",
        "offline": "Offline: tools ran in a fixed order and the template wrote the report."
                   + ("" if os.getenv("NEBIUS_API_KEY") else
                      " Set NEBIUS_API_KEY for the Nemotron agent."),
    }[report.mode])
    for note in report.notes:
        right.caption(note)
    for n, call in enumerate(report.trace, 1):
        shown = ", ".join(f"{k}={json.dumps(v)}" for k, v in call.arguments.items())
        flag = " ⚠️" if "error" in call.result else ""
        with right.expander(f"{n}. {call.name}({shown}){flag}"):
            st.json(call.result)

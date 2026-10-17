"""MuFFLe++ demo: federated prognosis + Nemotron-written report.

streamlit run app/streamlit_app.py -- --ckpt outputs/centralized.pt --data data/synthetic
(an FL global model checkpoint from the NVFlare workspace works too)
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import torch

from muffle.config import load_config
from muffle.data.dataset import MultiOmicDataset
from muffle.explain import modality_contributions, risk_percentile, top_features
from muffle.metrics import concordance_index
from muffle.models import MuffleNet
from muffle.report.nemotron import build_facts, literature, summarize

p = argparse.ArgumentParser()
p.add_argument("--ckpt", default="outputs/centralized.pt")
p.add_argument("--data", default="data/synthetic")
p.add_argument("--cancer", default="breast")
args, _ = p.parse_known_args()


@st.cache_resource
def load(ckpt: str, data: str):
    blob = torch.load(ckpt, map_location="cpu", weights_only=False)
    cfg = blob.get("config") if isinstance(blob, dict) else None
    cfg = cfg or load_config()
    state = blob["model"] if isinstance(blob, dict) and "model" in blob else blob
    model = MuffleNet.from_config(cfg)
    model.load_state_dict({k: torch.as_tensor(v) for k, v in state.items()})
    model.eval()
    ds = MultiOmicDataset(Path(data) / "cohort.npz", cfg["modalities"])
    with torch.no_grad():
        risks = model(ds.x, ds.mask).numpy()
    return model, ds, risks


st.set_page_config(page_title="MuFFLe++", layout="wide")
st.title("MuFFLe++ — federated multi-omic prognosis")
st.caption("Research prototype. Not for clinical use.")

model, ds, risks = load(args.ckpt, args.data)
c = concordance_index(ds.time, ds.event, risks)
col1, col2, col3 = st.columns(3)
col1.metric("Patients", len(ds))
col2.metric("C-index (cohort)", f"{c:.3f}")
col3.metric("Modalities", ", ".join(model.names))

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
strongest = max(contrib, key=lambda m: abs(contrib[m])) if contrib else model.names[0]
feats = top_features(model, x, mask, strongest, None)
pct = risk_percentile(base, risks)
avail = [m for j, m in enumerate(model.names) if mask[0, j] > 0]
st.write(f"Available data: {', '.join(avail)} · risk percentile **{pct:.0f}**")
st.bar_chart(pd.Series(contrib, name="Δ log-risk when removed"))

if st.button("Write report with Nemotron"):
    facts = build_facts(args.cancer, base, pct, contrib, feats, c)
    with st.spinner("Nemotron is writing…"):
        st.markdown(summarize(facts, literature(feats, args.cancer)))

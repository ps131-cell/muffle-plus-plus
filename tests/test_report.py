import numpy as np
import torch

from muffle.explain import modality_contributions, risk_percentile, top_features
from muffle.models import MuffleNet
from muffle.report.nemotron import build_facts, summarize
from tests.conftest import SMALL_DIMS


def test_explanations_and_offline_report(monkeypatch):
    monkeypatch.delenv("NEBIUS_API_KEY", raising=False)
    model = MuffleNet(SMALL_DIMS, hidden=16, latent=4, head_hidden=4)
    x = {m: torch.randn(1, d) for m, d in SMALL_DIMS.items()}
    mask = torch.ones(1, len(SMALL_DIMS))
    mask[0, 3] = 0  # protein missing
    base, contrib = modality_contributions(model, x, mask)
    assert "protein" not in contrib and len(contrib) == 4
    feats = top_features(model, x, mask, "rna", None, k=5)
    assert len(feats) == 5
    pct = risk_percentile(base, np.array([-1.0, 0.0, 1.0]))
    text = summarize(build_facts("breast", base, pct, contrib, feats, 0.7))
    assert "percentile" in text and "NEBIUS_API_KEY" in text

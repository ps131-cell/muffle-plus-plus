import numpy as np
import torch

from muffle.explain import modality_contributions, risk_percentile, top_features
from muffle.models import MuffleNet
from muffle.report.nemotron import build_facts, offline_summary
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
    text = offline_summary(build_facts("breast", base, pct, contrib, feats, 0.7))
    assert "percentile" in text and "NEBIUS_API_KEY" in text


def test_contributions_are_relative_to_a_typical_patient():
    from muffle.explain import cohort_offsets, masked_effects

    torch.manual_seed(0)
    model = MuffleNet(SMALL_DIMS, hidden=16, latent=4, head_hidden=4)
    x = {m: torch.randn(40, d) for m, d in SMALL_DIMS.items()}
    mask = torch.ones(40, len(SMALL_DIMS))
    mask[:10, 3] = 0  # protein missing for 10 patients
    offsets = cohort_offsets(model, x, mask)
    _, eff = masked_effects(model, x, mask)
    assert np.isnan(eff["protein"][:10]).all() and np.isfinite(eff["protein"][10:]).all()
    # per layer, the cohort-relative contributions average zero over the patients that have it
    rel = {m: [modality_contributions(model, {k: v[i:i + 1] for k, v in x.items()},
                                      mask[i:i + 1], offsets)[1].get(m) for i in range(40)]
           for m in SMALL_DIMS}
    for m, vals in rel.items():
        vals = [v for v in vals if v is not None]
        assert abs(np.mean(vals)) < 1e-5, m
    assert rel["protein"][0] is None and rel["protein"][10] is not None
    # without offsets: the old "with minus without the layer" numbers
    i = 12
    one = {k: v[i:i + 1] for k, v in x.items()}
    _, raw = modality_contributions(model, one, mask[i:i + 1])
    _, cen = modality_contributions(model, one, mask[i:i + 1], offsets)
    for m in raw:
        assert abs(raw[m] - offsets[m] - cen[m]) < 1e-6

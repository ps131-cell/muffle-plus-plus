import pytest
import torch

from muffle.models import MuffleNet
from tests.conftest import SMALL_DIMS


def _batch(n=5):
    return {m: torch.randn(n, d) for m, d in SMALL_DIMS.items()}


def test_forward_shape():
    model = MuffleNet(SMALL_DIMS, hidden=16, latent=4, head_hidden=4)
    out = model(_batch(), torch.ones(5, len(SMALL_DIMS)))
    assert out.shape == (5,)


def test_masked_modality_is_ignored():
    model = MuffleNet(SMALL_DIMS, hidden=16, latent=4, head_hidden=4).eval()
    x = _batch()
    mask = torch.ones(5, len(SMALL_DIMS))
    mask[:, list(SMALL_DIMS).index("protein")] = 0
    y1 = model(x, mask)
    x["protein"] = torch.randn_like(x["protein"]) * 100
    assert torch.allclose(y1, model(x, mask))


def test_modality_dropout_keeps_one():
    model = MuffleNet(SMALL_DIMS, modality_dropout=0.99).train()
    mask = torch.zeros(50, len(SMALL_DIMS))
    mask[:, 0] = 1
    assert (model._train_time_mask(mask).sum(1) >= 1).all()


def test_constructor_args_are_attributes():
    # NVFlare's job API rebuilds the initial model from same-named attributes
    model = MuffleNet(SMALL_DIMS, hidden=16, fusion="additive")
    assert model.modality_dims == SMALL_DIMS and model.hidden == 16
    assert model.fusion == "additive"


def test_additive_fusion_is_a_sum_over_present_modalities():
    model = MuffleNet(SMALL_DIMS, hidden=16, latent=4, head_hidden=4, fusion="additive").eval()
    x = _batch()
    mask = torch.ones(5, len(SMALL_DIMS))
    j = list(SMALL_DIMS).index("protein")
    mask[:, j] = 0
    y1 = model(x, mask)
    assert y1.shape == (5,)
    x["protein"] = torch.randn_like(x["protein"]) * 100  # absent: its values don't matter
    assert torch.allclose(y1, model(x, mask))
    with torch.no_grad():
        model.missing[j] = 0.7  # absent modality adds its learned offset instead
    assert torch.allclose(model(x, mask), y1 + 0.7)


def test_always_keep_is_never_dropped():
    model = MuffleNet(SMALL_DIMS, modality_dropout=0.99, always_keep=["clinical"]).train()
    mask = torch.ones(200, len(SMALL_DIMS))
    out = model._train_time_mask(mask)
    j = list(SMALL_DIMS).index("clinical")
    assert out[:, j].min() == 1 and out.sum() < mask.sum() / 2
    assert "_droppable" not in model.state_dict()  # checkpoints / FL weights unchanged


def test_unknown_fusion_is_rejected():
    with pytest.raises(ValueError):
        MuffleNet(SMALL_DIMS, fusion="attention")

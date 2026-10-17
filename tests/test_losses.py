import torch

from muffle.losses import cox_ph_loss


def test_correct_ordering_has_lower_loss():
    t = torch.tensor([1.0, 2, 3, 4, 5])
    e = torch.ones(5)
    good = cox_ph_loss(-t, t, e)  # high risk for early events
    bad = cox_ph_loss(t, t, e)
    assert good < bad


def test_known_value_two_patients():
    # patient 0 dies at t=1 with risk set {0,1}; patient 1 censored
    r = torch.tensor([0.0, 0.0])
    loss = cox_ph_loss(r, torch.tensor([1.0, 2.0]), torch.tensor([1.0, 0.0]))
    assert torch.isclose(loss, torch.log(torch.tensor(2.0)))


def test_no_events_is_zero_and_differentiable():
    r = torch.randn(4, requires_grad=True)
    loss = cox_ph_loss(r, torch.rand(4), torch.zeros(4))
    loss.backward()
    assert loss.item() == 0.0 and r.grad is not None

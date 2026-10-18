"""Token Factory spending cap: reserve worst case, charge real usage, refuse past the cap."""

from types import SimpleNamespace

import pytest

from muffle.report import budget
from muffle.report.budget import BudgetedClient, BudgetExceeded, Ledger
from muffle.report.nemotron import run_case_agent
from tests.test_agent import FakeClient, make_tools, reply

SUPER = "nvidia/nemotron-3-super-120b-a12b"
REQUEST = {"model": SUPER, "messages": [{"role": "user", "content": "hi"}], "max_tokens": 500}


def billed(prompt_tokens, completion_tokens):
    msg = SimpleNamespace(content="ok", tool_calls=None)
    return SimpleNamespace(choices=[SimpleNamespace(message=msg, finish_reason="stop")],
                           usage=SimpleNamespace(prompt_tokens=prompt_tokens,
                                                 completion_tokens=completion_tokens,
                                                 total_tokens=prompt_tokens + completion_tokens))


class ApiError(Exception):
    def __init__(self, status_code=None):
        super().__init__(f"status {status_code}")
        self.status_code = status_code


def raising(error):
    def step(kw):
        raise error
    return step


def test_reservation_is_replaced_by_real_cost():
    ledger = Ledger(cap=1.0)
    BudgetedClient(FakeClient(billed(1000, 500)), ledger).chat.completions.create(**REQUEST)
    s = ledger.read()
    assert s["spent_usd"] == pytest.approx((1000 * 0.30 + 500 * 0.90) / 1e6)
    assert s["calls"] == 1 and s["by_model"][SUPER] == pytest.approx(s["spent_usd"])


def test_call_past_cap_is_never_sent():
    fake = FakeClient(billed(10, 10))
    ledger = Ledger(cap=budget.worst_case_cost(REQUEST) / 2)
    with pytest.raises(BudgetExceeded, match="spending cap"):
        BudgetedClient(fake, ledger).chat.completions.create(**REQUEST)
    assert fake.calls == [] and ledger.read()["spent_usd"] == 0


def test_worst_case_bounds_the_real_cost():
    assert budget.worst_case_cost(REQUEST) >= budget.cost(SUPER, 10, 500)
    unknown = dict(REQUEST, model="nvidia/some-new-model")
    assert budget.worst_case_cost(unknown) > budget.worst_case_cost(REQUEST)


def test_unbilled_errors_release_the_reservation():
    ledger = Ledger(cap=1.0)
    no_credit, timeout = (BudgetedClient(FakeClient(raising(e)), ledger)
                          for e in (ApiError(402), ApiError()))
    with pytest.raises(ApiError):
        no_credit.chat.completions.create(**REQUEST)
    assert ledger.read()["spent_usd"] == 0
    with pytest.raises(ApiError):  # timeout / 5xx: the model may have run, keep it charged
        timeout.chat.completions.create(**REQUEST)
    assert ledger.read()["spent_usd"] == pytest.approx(budget.worst_case_cost(REQUEST))


def test_cap_can_be_lowered_but_not_raised(monkeypatch):
    monkeypatch.setenv("TOKEN_FACTORY_BUDGET_USD", "100")
    assert budget.cap_usd() == Ledger().cap == 25.50
    assert Ledger(cap=1000).cap == 25.50
    monkeypatch.setenv("TOKEN_FACTORY_BUDGET_USD", "5")
    assert Ledger().cap == 5


def test_spend_persists_across_ledgers():
    Ledger().settle(0.0, 25.49, SUPER)
    with pytest.raises(BudgetExceeded):
        Ledger().reserve(0.02)


def test_agent_falls_back_offline_at_the_cap():
    fake = FakeClient(reply("**Summary** should not be written"))
    report = run_case_agent(make_tools(), client=BudgetedClient(fake, Ledger(cap=1e-9)))
    assert report.mode == "offline" and fake.calls == []
    assert "spending cap" in report.notes[0] and "spending cap" in report.text

"""Hard spending cap for Nebius Token Factory calls.

Every live chat completion goes through ``BudgetedClient``. Before the request it reserves the
worst-case cost (a generous input estimate plus the full ``max_tokens`` of output) in a ledger
file and refuses the call with ``BudgetExceeded`` if that would take total spend past the cap;
after the reply the reservation is swapped for the real cost from ``usage``. So this code never
sends a request that could take spend past $25.50. TOKEN_FACTORY_BUDGET_USD can lower the cap,
never raise it.

The ledger lives outside the repo (~/.muffle/token_factory_spend.json, override with
MUFFLE_SPEND_LEDGER) so deleting outputs/ or re-cloning doesn't reset it. It only sees calls made
through this code on this machine: compare it with the Usage tab in the Nebius console, and record
other usage (console playground, another machine) with ``--add``.

Status:            python -m muffle.report.budget
Add outside spend: python -m muffle.report.budget --add 0.40
"""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

HARD_CAP_USD = 25.50

# USD per 1M (input, output) tokens: the Nebius rates as listed by price trackers on 2026-10-18
# (the official price page needs a login). Any other model is charged the deliberately high
# default, so the cap errs on the safe side; add its real price here before relying on it.
# Reasoning tokens are billed as output and are included in usage.completion_tokens.
PRICES_PER_M = {"nvidia/nemotron-3-super-120b-a12b": (0.30, 0.90),
                "nvidia/nemotron-3-ultra-550b-a55b": (1.00, 3.00)}
DEFAULT_PRICE_PER_M = (3.00, 9.00)
CHARS_PER_TOKEN = 2        # tokenizers average ~4 characters per token; 2 overestimates input
DEFAULT_MAX_TOKENS = 4096  # reserved for a request that sets no max_tokens


class BudgetExceeded(RuntimeError):
    pass


def cap_usd() -> float:
    env = os.getenv("TOKEN_FACTORY_BUDGET_USD")
    return min(HARD_CAP_USD, float(env)) if env else HARD_CAP_USD


def ledger_path() -> Path:
    return Path(os.getenv("MUFFLE_SPEND_LEDGER", "~/.muffle/token_factory_spend.json")).expanduser()


def cost(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    p_in, p_out = PRICES_PER_M.get(model.lower(), DEFAULT_PRICE_PER_M)
    return (prompt_tokens * p_in + completion_tokens * p_out) / 1e6


def worst_case_cost(request: dict) -> float:
    """Upper bound for one chat completion: every 2 characters of the messages and tool specs
    counted as an input token, plus the full ``max_tokens`` of output."""
    text = json.dumps({k: request.get(k) for k in ("messages", "tools")}, default=str)
    return cost(request["model"], math.ceil(len(text) / CHARS_PER_TOKEN),
                request.get("max_tokens") or DEFAULT_MAX_TOKENS)


class Ledger:
    """Total spend in a JSON file. Updates hold a file lock, so two processes (CLI and Streamlit)
    can't both reserve the last of the budget."""

    def __init__(self, path: Path | None = None, cap: float | None = None):
        self.path = path or ledger_path()
        self.cap = cap_usd() if cap is None else min(cap, HARD_CAP_USD)

    def read(self) -> dict:
        if self.path.exists():
            return json.loads(self.path.read_text())  # a corrupt ledger raises: fail closed
        return {"spent_usd": 0.0, "calls": 0, "by_model": {}}

    @contextmanager
    def _update(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path.with_suffix(".lock"), "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self.read()
            yield state  # an exception in the body skips the write
            state["updated"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(state, indent=2))
            tmp.replace(self.path)

    def reserve(self, amount: float) -> float:
        with self._update() as s:
            if s["spent_usd"] + amount > self.cap:
                raise BudgetExceeded(
                    f"Token Factory spending cap reached: ${s['spent_usd']:.2f} of "
                    f"${self.cap:.2f} used; this call could cost up to ${amount:.4f}")
            s["spent_usd"] += amount
        return amount

    def settle(self, reserved: float, actual: float, model: str = "unknown"):
        """Swap a reservation for the real cost (0 for a request that wasn't billed)."""
        with self._update() as s:
            s["spent_usd"] += actual - reserved
            if actual:
                s["calls"] += 1
                s["by_model"][model] = s["by_model"].get(model, 0.0) + actual


class BudgetedClient:
    """Wraps an OpenAI-compatible client so every chat completion is reserved, then charged, in
    the ledger. Everything else (``models.list()``, which is free) passes through."""

    def __init__(self, client, ledger: Ledger | None = None):
        self._client, self.ledger = client, ledger or Ledger()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    def __getattr__(self, name):
        return getattr(self._client, name)

    def _create(self, **kw):
        model = kw["model"]
        reserved = self.ledger.reserve(worst_case_cost(kw))
        try:
            resp = self._client.chat.completions.create(**kw)
        except Exception as e:
            # 4xx (bad request, 402 no credit, 429) isn't billed; after a timeout or 5xx the model
            # may have run, so the reservation stays charged
            status = getattr(e, "status_code", None)
            if status is not None and 400 <= status < 500:
                self.ledger.settle(reserved, 0.0)
            raise
        usage = getattr(resp, "usage", None)
        pt, ct = getattr(usage, "prompt_tokens", None), getattr(usage, "completion_tokens", None)
        self.ledger.settle(reserved, reserved if pt is None or ct is None else cost(model, pt, ct),
                           model)
        return resp


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--add", type=float, help="record USD spent outside this code")
    a = p.parse_args()
    ledger = Ledger()
    if a.add:
        ledger.settle(0.0, a.add, "outside this code")
    s = ledger.read()
    print(f"Token Factory spend on this machine: ${s['spent_usd']:.4f} of ${ledger.cap:.2f} "
          f"(${ledger.cap - s['spent_usd']:.4f} left), {s['calls']} calls, ledger {ledger.path}")
    for m, usd in s["by_model"].items():
        print(f"  {m}: ${usd:.4f}")

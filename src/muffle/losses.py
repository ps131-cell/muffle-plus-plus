from __future__ import annotations

import torch


def cox_ph_loss(log_risk: torch.Tensor, time: torch.Tensor, event: torch.Tensor) -> torch.Tensor:
    """Negative Cox partial log-likelihood (Breslow handling of ties), averaged over events.

    Risk set of patient i = everyone with time >= t_i. Sorting by descending time turns the
    risk-set sum into a cumulative logsumexp.
    """
    order = torch.argsort(time, descending=True)
    r, e = log_risk[order], event[order]
    log_cum = torch.logcumsumexp(r, dim=0)
    n_events = e.sum()
    if n_events == 0:
        return log_risk.sum() * 0.0  # keep the graph; batch carries no information
    return -((r - log_cum) * e).sum() / n_events

"""Training / evaluation loops shared by local baselines and the FL client."""

from __future__ import annotations

import torch
from torch.utils.data import DataLoader

from muffle.losses import cox_ph_loss
from muffle.metrics import concordance_index


def _to(batch, device):
    x, mask, t, e = batch
    return {m: v.to(device) for m, v in x.items()}, mask.to(device), t.to(device), e.to(device)


def train_epochs(
    model: torch.nn.Module,
    loader: DataLoader,
    epochs: int,
    lr: float,
    weight_decay: float = 0.0,
    device: str = "cpu",
    prox_mu: float = 0.0,
    global_params: dict[str, torch.Tensor] | None = None,
) -> dict[str, float]:
    """Plain local training; with prox_mu > 0 adds the FedProx term mu/2 * ||w - w_global||^2."""
    model.to(device).train()
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=weight_decay)
    use_amp = device.startswith("cuda")
    anchor = None
    if prox_mu > 0 and global_params is not None:
        anchor = {k: v.detach().to(device) for k, v in global_params.items()}
    steps, total = 0, 0.0
    for _ in range(epochs):
        for batch in loader:
            x, mask, t, e = _to(batch, device)
            with torch.autocast(device_type="cuda", dtype=torch.bfloat16, enabled=use_amp):
                loss = cox_ph_loss(model(x, mask).float(), t, e)
            if anchor is not None:
                prox = sum(((p - anchor[n]) ** 2).sum() for n, p in model.named_parameters())
                loss = loss + prox_mu / 2 * prox
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5.0)
            opt.step()
            steps += 1
            total += loss.item()
    return {"train_loss": total / max(steps, 1), "steps": steps}


@torch.no_grad()
def evaluate(model: torch.nn.Module, dataset, device: str = "cpu") -> dict[str, float]:
    """Full-set evaluation (Cox loss is not decomposable over batches, so no mini-batching)."""
    model.to(device).eval()
    x, mask, t, e = _to(next(iter(DataLoader(dataset, batch_size=len(dataset)))), device)
    risk = model(x, mask)
    return {
        "c_index": concordance_index(t.cpu(), e.cpu(), risk.cpu()),
        "val_loss": cox_ph_loss(risk, t, e).item(),
        "n": len(dataset),
    }

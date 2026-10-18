from __future__ import annotations

from collections.abc import Iterable

import numpy as np


def concordance_counts(time, event, risk) -> tuple[float, float]:
    """(concordant, comparable) pair counts behind Harrell's C-index.

    A pair (i, j) is comparable when i had the event and t_i < t_j. Ties in risk count 0.5.
    O(n^2) memory-light loop over events; fine for cohorts up to tens of thousands.
    """
    time, event, risk = (np.asarray(a, dtype=float).ravel() for a in (time, event, risk))
    num = den = 0.0
    for i in np.flatnonzero(event > 0):
        later = time > time[i]
        n = later.sum()
        if n == 0:
            continue
        den += n
        num += (risk[i] > risk[later]).sum() + 0.5 * (risk[i] == risk[later]).sum()
    return float(num), float(den)


def concordance_index(time, event, risk) -> float:
    """Harrell's C-index. Higher risk should mean shorter survival. 0.5 = random."""
    num, den = concordance_counts(time, event, risk)
    return num / den if den else float("nan")


def stratified_concordance(counts: Iterable[tuple[float, float]]) -> float:
    """C-index over several sites, pairing patients only within a site.

    Sums per-site ``concordance_counts``, so models whose risk scores are on different scales
    (e.g. one local model per hospital) can still be pooled, and sites with many comparable
    pairs weigh more than a site with two events.
    """
    num = den = 0.0
    for n, d in counts:
        num, den = num + n, den + d
    return num / den if den else float("nan")

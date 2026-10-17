from __future__ import annotations

import numpy as np


def concordance_index(time, event, risk) -> float:
    """Harrell's C-index. Higher risk should mean shorter survival. 0.5 = random.

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
    return float(num / den) if den else float("nan")

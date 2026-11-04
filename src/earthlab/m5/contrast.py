"""Descriptive contrast of a continuous index between mapped-burned and control cells.

The AUC is the chance that a random burned cell has a higher index than a random control
cell (ties count half). It is a measure of separation, not accuracy against ground truth:
the burned labels come from another satellite product.
"""

from __future__ import annotations

from typing import Any

import numpy as np
from numpy.typing import NDArray


def auc(positive: NDArray[np.float64], negative: NDArray[np.float64]) -> float:
    """Mann-Whitney AUC by ranks. NaN values must be removed by the caller."""
    if len(positive) == 0 or len(negative) == 0:
        return float("nan")
    values = np.concatenate([positive, negative])
    order = values.argsort(kind="mergesort")
    ranks = np.empty(len(values))
    sorted_vals = values[order]
    # average ranks for ties
    start = 0
    for end in range(1, len(values) + 1):
        if end == len(values) or sorted_vals[end] != sorted_vals[start]:
            ranks[order[start:end]] = (start + end + 1) / 2.0
            start = end
    n_pos, n_neg = len(positive), len(negative)
    return float((ranks[:n_pos].sum() - n_pos * (n_pos + 1) / 2.0) / (n_pos * n_neg))


def burn_contrast(index: NDArray[np.float64], burned: NDArray[np.bool_],
                  control: NDArray[np.bool_]) -> dict[str, Any]:  # fmt: skip
    """Counts, means and AUC of `index` for burned versus control cells with a valid index."""
    ok = ~np.isnan(index)
    b, c = index[burned & ok], index[control & ok]
    return {
        "n_burned_valid": len(b), "n_control_valid": len(c),
        "n_burned_total": int(burned.sum()), "n_control_total": int(control.sum()),
        "mean_burned": float(b.mean()) if len(b) else None,
        "mean_control": float(c.mean()) if len(c) else None,
        "auc": auc(b, c),
    }  # fmt: skip

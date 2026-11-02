"""Small gradient-boosted trees in numpy. The state is plain arrays, so nothing is pickled."""

from __future__ import annotations

import numpy as np

BINS = 16


def _best_split(
    x: np.ndarray, grad: np.ndarray, rows: np.ndarray, cuts: np.ndarray
) -> tuple[int, float]:
    """The feature and cut with the largest fall in squared error, from binned sums."""
    best_gain, best_feature, best_cut = 0.0, -1, 0.0
    total, count = float(grad[rows].sum()), len(rows)
    for feature in range(x.shape[1]):
        slots = np.searchsorted(cuts[feature], x[rows, feature])
        sums = np.bincount(slots, grad[rows], BINS)[:-1].cumsum()
        counts = np.bincount(slots, minlength=BINS)[:-1].cumsum()
        usable = (counts > 0) & (counts < count)
        if not usable.any():
            continue
        left, n = sums[usable], counts[usable]
        gain = left**2 / n + (total - left) ** 2 / (count - n) - total**2 / count
        where = int(np.argmax(gain))
        if gain[where] > best_gain:
            best_gain, best_feature = float(gain[where]), feature
            best_cut = float(cuts[feature][np.flatnonzero(usable)[where]])
    return best_feature, best_cut


def _grow(x: np.ndarray, grad: np.ndarray, cuts: np.ndarray, depth: int) -> tuple[np.ndarray, ...]:
    """One complete tree stored level by level. A node with no split sends every row left."""
    nodes = 2**depth - 1
    features, thresholds = np.full(nodes, -1, dtype=np.int32), np.zeros(nodes)
    leaves = np.zeros(2**depth)
    members = {0: np.arange(len(x))}
    for node in range(2 ** (depth + 1) - 1):
        rows = members.get(node, np.empty(0, dtype=np.int64))
        if node >= nodes:
            leaves[node - nodes] = float(grad[rows].mean()) if len(rows) else 0.0
            continue
        feature, cut = _best_split(x, grad, rows, cuts) if len(rows) > 1 else (-1, 0.0)
        features[node], thresholds[node] = feature, cut
        go_left = x[rows, feature] <= cut if feature >= 0 else np.ones(len(rows), dtype=bool)
        members[2 * node + 1], members[2 * node + 2] = rows[go_left], rows[~go_left]
    return features, thresholds, leaves


def _walk(
    x: np.ndarray, features: np.ndarray, thresholds: np.ndarray, leaves: np.ndarray
) -> np.ndarray:
    nodes = len(features)
    at = np.zeros(len(x), dtype=np.int64)
    while (at < nodes).any():
        inner = at < nodes
        feature = features[at[inner]]
        right = (feature >= 0) & (x[np.flatnonzero(inner), feature] > thresholds[at[inner]])
        at[inner] = 2 * at[inner] + 1 + right
    return np.asarray(leaves[at - nodes], dtype=float)


def fit_trees(
    x: np.ndarray, y: np.ndarray, trees: int, depth: int, rate: float, logistic: bool
) -> dict[str, np.ndarray]:
    grid = np.linspace(0, 1, BINS + 1)[1:-1]
    cuts = np.quantile(x, grid, axis=0).T
    start = np.log(y.mean() / (1 - y.mean())) if logistic else float(y.mean())
    score = np.full(len(y), float(start))
    parts: list[tuple[np.ndarray, ...]] = []
    for _ in range(trees):
        residual = y - 1 / (1 + np.exp(-score)) if logistic else y - score
        tree = _grow(x, residual, cuts, depth)
        score = score + rate * _walk(x, *tree)
        parts.append(tree)
    return {
        "features": np.stack([p[0] for p in parts]),
        "thresholds": np.stack([p[1] for p in parts]),
        "leaves": np.stack([p[2] for p in parts]),
        "start": np.array(float(start)),
        "rate": np.array(rate),
    }


def apply_trees(x: np.ndarray, state: dict[str, np.ndarray]) -> np.ndarray:
    total = np.full(len(x), float(state["start"]))
    for feature, threshold, leaf in zip(
        state["features"], state["thresholds"], state["leaves"], strict=True
    ):
        total = total + float(state["rate"]) * _walk(x, feature, threshold, leaf)
    return total

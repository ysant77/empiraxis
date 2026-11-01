"""The registered methods, one train and predict contract, and code's eligibility checks.

A Lead picks a method by ID from the eligible list. Each config is a bounded typed record, so
a proposal cannot name an arbitrary architecture. Every method takes the same feature matrix
and returns one column per output, so candidates compare on the same samples.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from pydantic import Field

from earthlab.contracts import Strict
from earthlab.mlops.contracts import Family, ModelBundleV1
from earthlab.mlops.trees import apply_trees, fit_trees

Task = Literal["regression", "classification"]
Arrays = dict[str, np.ndarray]
NEURAL_MIN_ROWS = 10_000
TREE_MIN_ROWS = 1_000
MIN_POSITIVES = 50


class Empty(Strict):
    pass


class RidgeConfig(Strict):
    alpha: float = Field(ge=0.01, le=100_000.0)


class LogisticConfig(Strict):
    penalty: float = Field(ge=0.01, le=1_000.0)
    balanced: bool = True


class TreeConfig(Strict):
    trees: int = Field(ge=5, le=200)
    depth: int = Field(ge=1, le=4)
    rate: float = Field(gt=0.0, le=0.5)


@dataclass(frozen=True)
class Facts:
    """Measured by code. The eligibility of a method comes from these and nothing else."""

    task: Task
    rows: int
    positives: int | None
    has_calendar: bool
    labels_verified: bool
    pretrained_approved: bool = False
    teacher_available: bool = False


@dataclass(frozen=True)
class Method:
    method_id: str
    family: Family
    tasks: tuple[Task, ...]
    config: type[Strict]
    fit: Callable[[np.ndarray, np.ndarray, Any, int], Arrays]
    predict: Callable[[np.ndarray, Arrays, Any], np.ndarray]
    blocked: Callable[[Facts], str | None]


def _design(x: np.ndarray) -> np.ndarray:
    return np.hstack([x, np.ones((len(x), 1))])


def _solve(x: np.ndarray, y: np.ndarray, alpha: float) -> Arrays:
    out = []
    for column in y.T:
        keep = ~np.isnan(column)
        design = _design(x[keep])
        penalty = alpha * np.eye(design.shape[1])
        penalty[-1, -1] = 0.0
        out.append(np.linalg.solve(design.T @ design + penalty, design.T @ column[keep]))
    return {"weights": np.stack(out, axis=1)}


def _fit_ridge(x: np.ndarray, y: np.ndarray, config: RidgeConfig, _seed: int) -> Arrays:
    return _solve(x, y, config.alpha)


def _apply_ridge(x: np.ndarray, state: Arrays, _config: RidgeConfig) -> np.ndarray:
    return np.asarray(_design(x) @ state["weights"], dtype=float)


def _fit_climate(x: np.ndarray, y: np.ndarray, _config: Empty, _seed: int) -> Arrays:
    return _solve(x[:, -4:], y, 0.01)


def _apply_climate(x: np.ndarray, state: Arrays, _config: Empty) -> np.ndarray:
    return np.asarray(_design(x[:, -4:]) @ state["weights"], dtype=float)


def _fit_persist(_x: np.ndarray, y: np.ndarray, _config: Empty, _seed: int) -> Arrays:
    return {"outputs": np.array(y.shape[1])}


def _apply_persist(x: np.ndarray, state: Arrays, _config: Empty) -> np.ndarray:
    """Lag 0 comes first in every matrix, one column per source column."""
    return np.asarray(x[:, : int(state["outputs"])], dtype=float)


def _fit_logistic(x: np.ndarray, y: np.ndarray, config: LogisticConfig, _seed: int) -> Arrays:
    from earthlab.harness.classify import fit_logistic

    weights = [fit_logistic(x, c, config.penalty, config.balanced) for c in y.T]
    return {"weights": np.stack(weights, axis=1)}


def _sigmoid(score: np.ndarray) -> np.ndarray:
    return np.asarray(1 / (1 + np.exp(-np.clip(score, -30, 30))), dtype=float)


def _apply_logistic(x: np.ndarray, state: Arrays, _config: LogisticConfig) -> np.ndarray:
    return _sigmoid(_design(x) @ state["weights"])


def _tree_fit(logistic: bool) -> Callable[[np.ndarray, np.ndarray, TreeConfig, int], Arrays]:
    def fit(x: np.ndarray, y: np.ndarray, config: TreeConfig, _seed: int) -> Arrays:
        out: Arrays = {}
        for i, column in enumerate(y.T):
            keep = ~np.isnan(column)
            state = fit_trees(
                x[keep], column[keep], config.trees, config.depth, config.rate, logistic
            )
            out |= {f"{i}.{key}": value for key, value in state.items()}
        return out

    return fit


def _tree_apply(logistic: bool) -> Callable[[np.ndarray, Arrays, TreeConfig], np.ndarray]:
    def predict(x: np.ndarray, state: Arrays, _config: TreeConfig) -> np.ndarray:
        outputs = sorted({int(key.split(".")[0]) for key in state})
        parts = []
        for i in outputs:
            part = {
                key.split(".")[1]: value for key, value in state.items() if key.startswith(f"{i}.")
            }
            parts.append(apply_trees(x, part))
        scores = np.stack(parts, axis=1)
        return _sigmoid(scores) if logistic else scores

    return predict


def _always(_facts: Facts) -> str | None:
    return None


def _needs_calendar(facts: Facts) -> str | None:
    return None if facts.has_calendar else "the features have no calendar columns"


def _needs_rows(rows: int) -> Callable[[Facts], str | None]:
    return lambda facts: None if facts.rows >= rows else f"fewer than {rows} training rows"


def _needs_classes(facts: Facts) -> str | None:
    if facts.positives is None or facts.positives < MIN_POSITIVES:
        return f"fewer than {MIN_POSITIVES} positive labels"
    return None


METHODS: dict[str, Method] = {
    m.method_id: m
    for m in (
        Method(
            "persistence", "deterministic", ("regression",), Empty,
            _fit_persist, _apply_persist, _always,
        ),
        Method(
            "climatology", "deterministic", ("regression",), Empty,
            _fit_climate, _apply_climate, _needs_calendar,
        ),
        Method(
            "ridge", "deterministic", ("regression",), RidgeConfig,
            _fit_ridge, _apply_ridge, _always,
        ),
        Method(
            "logistic", "traditional_ml", ("classification",), LogisticConfig,
            _fit_logistic, _apply_logistic, _needs_classes,
        ),
        Method(
            "trees", "traditional_ml", ("regression",), TreeConfig,
            _tree_fit(False), _tree_apply(False), _needs_rows(TREE_MIN_ROWS),
        ),
        Method(
            "trees_classifier", "traditional_ml", ("classification",), TreeConfig,
            _tree_fit(True), _tree_apply(True), _needs_classes,
        ),
    )
}  # fmt: skip


def eligible(facts: Facts) -> dict[str, str | None]:
    """Each method of this task with the reason it is blocked, or None when it may run."""
    return {
        name: method.blocked(facts)
        for name, method in METHODS.items()
        if facts.task in method.tasks
    }


def _pick(method_id: str, task: Task) -> Method:
    method = METHODS.get(method_id)
    if method is None or task not in method.tasks:
        raise ValueError(f"{method_id} is not a registered {task} method")
    return method


def train(
    method_id: str, task: Task, x: np.ndarray, y: np.ndarray, config: Mapping[str, Any], seed: int
) -> Arrays:
    """Validate the config, then fit. Hard-label rules are for the classifier adapters."""
    method = _pick(method_id, task)
    parsed = method.config.model_validate(dict(config))
    if y.ndim != 2 or len(x) != len(y):
        raise ValueError("x and y must align, and y needs one column per output")
    if task == "classification":
        for column in y.T:
            known = column[~np.isnan(column)]
            if len(known) == 0 or known.min() == known.max():
                raise ValueError("a classification output has one class only, so it is refused")
    return method.fit(x, y, parsed, seed)


def predict(
    method_id: str, task: Task, x: np.ndarray, state: Arrays, config: Mapping[str, Any]
) -> np.ndarray:
    method = _pick(method_id, task)
    return method.predict(x, state, method.config.model_validate(dict(config)))


def comparable(bundles: list[ModelBundleV1]) -> None:
    """Candidates compare only on the same features, outputs and task."""
    keys = {(b.feature.sha256, b.output_names, b.task) for b in bundles}
    if len(keys) != 1:
        raise ValueError("these candidates do not share features, outputs and task")

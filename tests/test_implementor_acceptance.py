"""The frozen acceptance checks: the reference passes, known-wrong code fails, hash pinned.

This is the fixed test every implementor task names. CI runs it against the reference
solutions only; a worker's module is run against the same checks by the trusted runner.
"""

from __future__ import annotations

import math
from datetime import UTC, timedelta
from types import ModuleType
from typing import Any

import pytest

from earthlab.implement import reference
from earthlab.implement.acceptance import CHECKS, AcceptanceFailure
from earthlab.implement.catalogue import FIXED_TEST, TASKS, WORKSPACE, acceptance_is_frozen
from earthlab.implement.contracts import editable


def variant(**functions: Any) -> ModuleType:
    """The reference module with some functions replaced by a wrong version."""
    module = ModuleType("variant")
    module.__dict__.update(
        {k: getattr(reference, k) for k in dir(reference) if not k.startswith("_")}
    )
    module.__dict__.update(functions)
    return module


@pytest.mark.parametrize("check", sorted(CHECKS))
def test_the_reference_passes_every_check(check: str) -> None:
    CHECKS[check](reference)


def _sin_cos(d: float) -> tuple[float, float]:
    return math.sin(math.radians(d)), math.cos(math.radians(d))


def _to_not_from(d: float, s: float) -> tuple[float, float]:
    """Sign error: treats the bearing as the direction the air moves TO."""
    sin, cos = _sin_cos(d)
    return s * sin, s * cos


def _swapped(d: float, s: float) -> tuple[float, float]:
    sin, cos = _sin_cos(d)
    return -s * cos, -s * sin


def _unchecked(d: float, s: float) -> tuple[float, float]:
    """Right maths, no input validation."""
    sin, cos = _sin_cos(d)
    return -s * sin, -s * cos


def _as_utc(label: Any, convention: str) -> Any:
    """Forgets the time zone: reads the SGT label as UTC."""
    end = label.replace(tzinfo=UTC)
    return end - timedelta(hours=1), end


def _no_embargo(t: Any, a: float, b: float, e: timedelta) -> Any:
    return reference.chronological_split(t, a, b, timedelta(0))


WRONG: dict[str, list[dict[str, Any]]] = {
    "wind_vector": [
        {"wind_vector": _to_not_from},
        {"wind_vector": _swapped},
        {"wind_vector": _unchecked},
        {"downwind_bearing": lambda d: d + 180.0},  # no wrap to [0, 360)
    ],
    "nea_hour_to_utc": [
        {"nea_hour_to_utc": _as_utc},
        {"nea_hour_to_utc": lambda label, c: reference.nea_hour_to_utc(label, "hour_ending")},
    ],
    "chronological_split": [
        {"chronological_split": _no_embargo},
        {"split_leaks": lambda parts, t, e: []},  # a detector that never finds anything
    ],
}


@pytest.mark.parametrize(
    ("check", "functions"), [(c, f) for c, variants in WRONG.items() for f in variants]
)
def test_known_wrong_implementations_fail(check: str, functions: dict[str, Any]) -> None:
    with pytest.raises(AcceptanceFailure):
        CHECKS[check](variant(**functions))


def test_the_acceptance_file_is_frozen() -> None:
    assert acceptance_is_frozen(), "acceptance.py changed: re-freeze ACCEPTANCE_SHA256 on purpose"


def test_catalogue_tasks_are_bounded_and_share_the_frozen_test() -> None:
    assert set(TASKS) == {"dev-wind-vector", "dev-nea-hour-utc", "dev-chronological-split"}
    for spec in TASKS.values():
        task = spec.task
        assert spec.check in CHECKS
        assert task.fixed_tests == (FIXED_TEST,)
        assert len(task.allowed_paths) == 1 and task.allowed_paths[0].startswith(WORKSPACE)
        assert all(editable(p) for p in task.allowed_paths)
        assert not any(task.permissions.model_dump().values())
        assert task.budget.max_paid_usd == 0.0

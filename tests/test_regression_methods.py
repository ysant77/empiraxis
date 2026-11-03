"""The method comparison trains both families when the Lead compares them, and says so."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from earthlab.forecast.contracts import Assignment
from earthlab.harness import regression_methods as RM
from earthlab.harness.regression_families import FamilyAdapter
from earthlab.harness.scenarios import SCENARIOS
from earthlab.trace import RunTrace


class _Seats:
    def __init__(self, trace: RunTrace) -> None:
        self.trace = trace


def _plan(strategy: str) -> Any:
    config = {"strategy": strategy, "architecture": "gru", "window_hours": 48}
    return type("Plan", (), {"config": config, "model_copy": _copy})()


def _copy(self: Any, update: dict[str, Any]) -> Any:
    return type("Plan", (), {"config": update["config"]})()


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []

    def train(self: FamilyAdapter, plan: Any, seats: Any) -> dict[str, Any]:
        calls.append(str(plan.config["strategy"]))
        return {"model_id": "candidate-1"}

    monkeypatch.setattr(FamilyAdapter, "train", train)
    return calls


@pytest.mark.parametrize("lead", RM.COMPARED)
def test_both_families_train_and_the_lead_choice_is_kept(
    lead: str, seen: list[str], tmp_path: Path
) -> None:
    trace = RunTrace(tmp_path / "trace.jsonl")
    adapter = RM.method_adapter(tmp_path)
    out = adapter.train(_plan(lead), _Seats(trace))  # type: ignore[arg-type]
    assert seen == ["small_neural"] and out["lead_strategy"] == lead
    assert adapter.expected == lead and adapter.menu_for(lead) is Assignment
    assert '"family_comparison"' in (tmp_path / "trace.jsonl").read_text(encoding="utf-8")


def test_a_choice_to_train_nothing_is_respected(seen: list[str], tmp_path: Path) -> None:
    adapter = RM.method_adapter(tmp_path)
    adapter.train(_plan("deterministic"), _Seats(RunTrace(tmp_path / "t.jsonl")))  # type: ignore[arg-type]
    assert seen == ["deterministic"] and adapter.menu_for("deterministic") is None
    assert not (tmp_path / "t.jsonl").exists() or "family_comparison" not in (
        tmp_path / "t.jsonl"
    ).read_text(encoding="utf-8")


def test_the_scenario_is_registered_with_its_own_problem() -> None:
    objective, problem, _ = SCENARIOS["pm25-method-comparison"]
    assert problem.problem_id == "pm25-method-comparison-6h" and "Both model families" in objective

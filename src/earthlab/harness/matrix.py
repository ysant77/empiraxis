"""The benchmark matrix as data: arms, stages, rotated order and a wall-time estimate.

The file `config/benchmark/matrix.yaml` is written and committed before any result exists.
This module only reads it. It starts no model server and calls no model.
"""

from __future__ import annotations

import itertools
from pathlib import Path
from typing import Self

import yaml
from pydantic import Field, model_validator

from earthlab.contracts import Strict
from earthlab.harness.arms import ArmSpec
from earthlab.harness.scenarios import SCENARIOS

WINNER = "@winner"


class Cell(Strict):
    """One scenario, the arms that run on it, and the repeats of each pair."""

    scenario: str
    arm_ids: tuple[str, ...] = Field(min_length=1)
    repeats: int = Field(default=1, ge=1)


class Stage(Strict):
    stage_id: str
    purpose: str
    cells: tuple[Cell, ...] = Field(min_length=1)


class Budget(Strict):
    total_hours: float = Field(gt=0)
    preflight_minutes: float = Field(ge=0)
    switch_minutes: float = Field(ge=0)
    minutes: dict[str, dict[str, float]]  # arm kind -> scenario -> minutes per run


class MatrixPlan(Strict):
    version: int
    matrix_id: str
    decisions: dict[str, tuple[str, ...]]
    arms: tuple[ArmSpec, ...] = Field(min_length=1)
    stages: tuple[Stage, ...] = Field(min_length=1)
    budget: Budget

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        ids = [a.arm_id for a in self.arms]
        if len(set(ids)) != len(ids):
            raise ValueError("arm IDs must be unique")
        named = {s for group in self.decisions.values() for s in group}
        for stage in self.stages:
            for cell in stage.cells:
                if cell.scenario not in SCENARIOS or cell.scenario not in named:
                    raise ValueError(f"{stage.stage_id}: scenario {cell.scenario} is not planned")
                missing = set(cell.arm_ids) - set(ids)
                if missing:
                    raise ValueError(f"{stage.stage_id}: unknown arms {sorted(missing)}")
        return self

    def arm(self, arm_id: str) -> ArmSpec:
        return next(a for a in self.arms if a.arm_id == arm_id)

    def stage(self, stage_id: str) -> Stage:
        return next(s for s in self.stages if s.stage_id == stage_id)


class PlannedRun(Strict):
    stage: str
    repeat: int
    order: int
    scenario: str
    arm_id: str
    block: str


def load_plan(path: Path) -> MatrixPlan:
    return MatrixPlan.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def rotate[T](items: list[T], shift: int) -> list[T]:
    if not items:
        return items
    k = shift % len(items)
    return items[k:] + items[:k]


def expand(plan: MatrixPlan, stage_id: str) -> list[PlannedRun]:
    """The run order of one stage. Repeat r rotates the blocks, scenarios and arms by r."""
    stage = plan.stage(stage_id)
    top = max(c.repeats for c in stage.cells)
    runs: list[PlannedRun] = []
    for repeat in range(top):
        due = [c for c in stage.cells if repeat < c.repeats]
        pairs = [(c.scenario, plan.arm(a)) for c in due for a in c.arm_ids]
        blocks = rotate(sorted({arm.block for _, arm in pairs}), repeat)
        for block in blocks:
            scenarios = rotate(sorted({s for s, arm in pairs if arm.block == block}), repeat)
            for index, scenario in enumerate(scenarios):
                arms = [arm for s, arm in pairs if s == scenario and arm.block == block]
                for arm in rotate(arms, repeat + index):
                    runs.append(
                        PlannedRun(
                            stage=stage_id,
                            repeat=repeat + 1,
                            order=len(runs) + 1,
                            scenario=scenario,
                            arm_id=arm.arm_id,
                            block=block,
                        )
                    )
    return runs


def run_minutes(plan: MatrixPlan, run: PlannedRun) -> float:
    kind = plan.arm(run.arm_id).arm
    return plan.budget.minutes[kind][run.scenario]


def estimate_hours(plan: MatrixPlan, stage_ids: list[str]) -> float:
    """Planned model time, preflight and server switches, in hours."""
    minutes = plan.budget.preflight_minutes
    for stage_id in stage_ids:
        runs = expand(plan, stage_id)
        minutes += sum(run_minutes(plan, r) for r in runs)
        served = [r.block for r in runs if r.block != "none"]
        switches = sum(a != b for a, b in itertools.pairwise(served)) + 1
        minutes += switches * plan.budget.switch_minutes
    return round(minutes / 60, 2)

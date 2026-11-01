"""Load and validate the paired-task plan for a later live evaluation. Runs nothing."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field, model_validator

from earthlab.contracts import Strict

POLICIES = ("A", "B", "C")


class PairedTask(Strict):
    task_id: str = Field(pattern=r"^PT-\d{2}$")
    scenario_id: str = Field(pattern=r"^WD-\d{2}$")
    purpose: str


class Criterion(Strict):
    id: str
    rule: str


class Acceptance(Strict):
    hard: tuple[Criterion, ...] = Field(min_length=1)
    adoption: tuple[Criterion, ...] = Field(min_length=1)
    report: str


class Design(Strict):
    pairs_per_task: int = Field(ge=3)
    order: str
    warm_up: str
    hold_fixed: tuple[str, ...]
    record: tuple[str, ...]


class PairedPlan(Strict):
    version: Literal[1]
    suite_id: str
    source_suite: str
    policies: tuple[Literal["A", "B", "C"], ...]
    tasks: tuple[PairedTask, ...] = Field(min_length=1)
    design: Design
    acceptance: Acceptance

    @model_validator(mode="after")
    def _consistent(self) -> PairedPlan:
        if set(self.policies) != set(POLICIES):
            raise ValueError("a paired plan compares exactly policies A, B and C")
        ids = [t.task_id for t in self.tasks]
        if len(set(ids)) != len(ids):
            raise ValueError("task IDs must be unique")
        if "heldout" in self.source_suite.lower():
            raise ValueError("the held-out set is spent and may not be a task source")
        return self


def load_plan(path: Path) -> PairedPlan:
    return PairedPlan.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def order_for(repeat: int) -> tuple[str, ...]:
    """Policy order for one repeat: a rotation of A, B, C, so each policy leads equally."""
    shift = repeat % len(POLICIES)
    return POLICIES[shift:] + POLICIES[:shift]

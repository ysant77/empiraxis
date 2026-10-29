"""Load plan fixtures as raw dictionaries, so a test can change one field and re-validate."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from earthlab.planning import CheckId, CriticReport, InvestigationPlan, review_plan

PLANS = Path(__file__).parent / "fixtures" / "plans"


def raw(name: str) -> dict[str, Any]:
    loaded: dict[str, Any] = yaml.safe_load((PLANS / f"{name}.yaml").read_text(encoding="utf-8"))
    return loaded


def method(plan: dict[str, Any], method_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        m for m in plan["method_candidates"] if m["method_id"] == method_id
    )
    return found


def dataset(plan: dict[str, Any], dataset_id: str) -> dict[str, Any]:
    found: dict[str, Any] = next(
        d for d in plan["data_candidates"] if d["dataset_id"] == dataset_id
    )
    return found


def review(plan: dict[str, Any]) -> CriticReport:
    return review_plan(InvestigationPlan.model_validate(plan))


def errors(plan: dict[str, Any]) -> set[CheckId]:
    return review(plan).checks("error")

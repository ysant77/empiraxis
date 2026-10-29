"""Load plan fixtures as raw dictionaries, so a test can change one field and re-validate.

The test registry is the real registry (case files, product profiles, manifests) plus
the illustrative records in tests/fixtures/registry_extra.yaml.
"""

from __future__ import annotations

from collections.abc import Iterable
from functools import cache
from pathlib import Path
from typing import Any

import yaml

from earthlab.planning import (
    CheckId,
    CriticReport,
    InvestigationPlan,
    Registry,
    load_registry,
    review_plan,
)
from earthlab.planning.sources import DataCandidate

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = Path(__file__).parent / "fixtures"
PLANS = FIXTURES / "plans"


@cache
def registry() -> Registry:
    extra = yaml.safe_load((FIXTURES / "registry_extra.yaml").read_text(encoding="utf-8"))
    records = [DataCandidate.model_validate(item) for item in extra["datasets"]]
    return load_registry(ROOT).with_candidates(records)


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


def review(plan: dict[str, Any], extra: Iterable[dict[str, Any]] = ()) -> CriticReport:
    """Review a raw plan; `extra` registers more datasets for this call only."""
    records = [DataCandidate.model_validate(item) for item in extra]
    return review_plan(InvestigationPlan.model_validate(plan), registry().with_candidates(records))


def errors(plan: dict[str, Any], extra: Iterable[dict[str, Any]] = ()) -> set[CheckId]:
    return review(plan, extra).checks("error")

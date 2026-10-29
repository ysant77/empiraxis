"""The InvestigationPlan schema: structure fails closed before any critic rule runs."""

from __future__ import annotations

import pytest
from plan_helpers import PLANS, raw
from pydantic import ValidationError

from earthlab.cases.models import ScientificVariable
from earthlab.planning import PLAN_SCHEMA_VERSION, InvestigationPlan, load_plan
from earthlab.planning.roles import TaskMeta
from earthlab.planning.vocab import PlanQuantity


def test_every_fixture_loads_with_the_current_schema_version() -> None:
    names = sorted(p.stem for p in PLANS.glob("*.yaml"))
    assert len(names) == 8
    for name in names:
        assert load_plan(PLANS / f"{name}.yaml").schema_version == PLAN_SCHEMA_VERSION


def test_plan_quantities_never_reuse_a_case_variable_value() -> None:
    assert not {v.value for v in ScientificVariable} & {q.value for q in PlanQuantity}


def _invalid(plan: dict[str, object], match: str) -> None:
    with pytest.raises(ValidationError, match=match):
        InvestigationPlan.model_validate(plan)


def test_unknown_fields_are_refused() -> None:
    plan = raw("singapore-2015-haze")
    plan["shell_command"] = "rm -rf /"
    _invalid(plan, "Extra inputs are not permitted")


def test_selected_method_must_be_a_candidate() -> None:
    plan = raw("singapore-2015-haze")
    plan["method_choice"]["selected_id"] = "made-up-method"
    _invalid(plan, "unknown method made-up-method")


def test_unknown_dataset_reference_is_refused() -> None:
    plan = raw("singapore-2015-haze")
    plan["method_candidates"][0]["inputs"][0]["dataset_id"] = "invented-data"
    _invalid(plan, "unknown dataset invented-data")


def test_prediction_needs_an_issue_time() -> None:
    plan = raw("singapore-pm25-nowcast")
    plan["time_range"].pop("forecast_issue_time")
    _invalid(plan, "forecast_issue_time")


def test_code_roles_cannot_author_a_plan() -> None:
    plan = raw("singapore-2015-haze")
    plan["task"]["role_id"] = "verifier"
    _invalid(plan, "may not author a plan")


def test_first_revision_has_no_dispositions() -> None:
    plan = raw("singapore-2015-haze")
    plan["critique_dispositions"] = [
        {"finding_id": "x", "disposition": "fixed", "evidence_refs": ["y"]}
    ]
    _invalid(plan, "first revision")
    plan["plan_revision"] = 2
    assert InvestigationPlan.model_validate(plan).plan_revision == 2


def test_pinned_dataset_needs_a_hash() -> None:
    plan = raw("singapore-2015-haze")
    plan["data_candidates"][0]["sha256"] = None
    _invalid(plan, "pinned dataset needs sha256")


def test_task_links_cannot_point_at_themselves() -> None:
    with pytest.raises(ValidationError, match="own parent"):
        TaskMeta(task_id="a", role_id="orchestrator", parent_task_id="a")
    with pytest.raises(ValidationError, match="both parent and child"):
        TaskMeta(task_id="a", role_id="orchestrator", parent_task_id="b", child_task_ids=("b",))
    with pytest.raises(ValidationError, match="unique"):
        TaskMeta(task_id="a", role_id="orchestrator", child_task_ids=("b", "b"))

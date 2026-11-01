"""The shared lifecycle: authority, immutable artifacts and refusals."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from earthlab.harness import gates
from earthlab.harness.artifacts import ArtifactStore, MissingArtifact, verify_file
from earthlab.harness.contracts import (
    BudgetV1,
    DatasetProfileV1,
    ExperimentPlanV1,
    MethodProposalV1,
    ProblemSpecV1,
    ResearchRequestV1,
    SourceRef,
)
from earthlab.harness.gates import Code
from earthlab.harness.lifecycle import IllegalTransition, Lifecycle
from earthlab.team.resources import OPERATOR_KEY_ENV, ResourceApprovalV1, sign

KEY = "unit-test-operator-key"
SOURCE = SourceRef(name="pm25.csv", sha256="a" * 64)


def _problem(**change: Any) -> ProblemSpecV1:
    base: dict[str, Any] = {
        "problem_id": "pm25-6h", "kind": "regression", "variable": "pm25", "unit": "ug/m3",
        "domain": "five NEA regions", "target": "hourly value at T+6",
        "horizon_hours": 6, "permitted_evidence": ("nea",), "success_criteria": ("beat B0",),
    }  # fmt: skip
    return ProblemSpecV1(**(base | change))


def _profile(**change: Any) -> DatasetProfileV1:
    base: dict[str, Any] = {
        "sources": (SOURCE,), "variable": "pm25", "unit": "ug/m3", "usable_rows": 50000,
        "missing_fraction": 0.0, "labels_present": True, "granularity": "1 h",
        "availability_latency_hours": 2,
    }  # fmt: skip
    return DatasetProfileV1(**(base | change))


def _plan(**change: Any) -> ExperimentPlanV1:
    base: dict[str, Any] = {
        "plan_id": "plan-1", "methods": ("persistence", "gru"), "split_protocol": "e1",
        "metrics": ("mae",), "input_offset_hours": 2, "seed": 1,
        "budget": BudgetV1(max_seconds=600, max_training_seconds=100, max_model_calls=10),
    }  # fmt: skip
    return ExperimentPlanV1(**(base | change))


def _to_forwarded(life: Lifecycle) -> None:
    for state in ("scoped", "profiled", "planned", "executing"):
        life.move(state, "controller")
    life.move("evaluated", "evaluator")
    life.move("reviewed", "controller")
    life.move("forwarded", "controller")


def _signed(approved: bool, record: str) -> ResourceApprovalV1:
    raw = ResourceApprovalV1(
        request_id="run", request_sha256=record, approved=approved, approver="a person",
        decided_at_utc=datetime.now(UTC),
    )  # fmt: skip
    return raw.model_copy(update={"signature": sign(raw, KEY)})


def test_the_full_path_reaches_a_signed_human_decision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)
    life = Lifecycle(tmp_path)
    _to_forwarded(life)
    life.human_decision(_signed(True, "b" * 64), "b" * 64, KEY)
    assert life.state == "approved"
    with pytest.raises(IllegalTransition):
        life.move("failed", "controller")


def test_no_controller_or_model_path_can_certify_or_approve(tmp_path: Path) -> None:
    life = Lifecycle(tmp_path)
    with pytest.raises(IllegalTransition):
        life.move("forwarded", "controller")
    for state in ("scoped", "profiled", "planned", "executing"):
        life.move(state, "controller")
    with pytest.raises(IllegalTransition, match="controller cannot"):
        life.move("evaluated", "controller")
    life.move("evaluated", "evaluator")
    life.move("reviewed", "controller")
    life.move("forwarded", "controller")
    with pytest.raises(IllegalTransition, match="controller cannot"):
        life.move("approved", "controller")


@pytest.mark.parametrize(
    ("key", "named", "match"),
    [("wrong-key", "b" * 64, "signature"), (KEY, "c" * 64, "different evidence")],
)
def test_a_bad_approval_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, key: str, named: str, match: str
) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)
    life = Lifecycle(tmp_path)
    _to_forwarded(life)
    with pytest.raises(IllegalTransition, match=match):
        life.human_decision(_signed(True, named), "b" * 64, key)
    assert life.state == "forwarded"


def test_an_unanswered_decision_expires_and_a_denial_stands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)
    late, denied = Lifecycle(tmp_path / "a"), Lifecycle(tmp_path / "b")
    _to_forwarded(late)
    _to_forwarded(denied)
    assert not late.expire(datetime.now(UTC) + timedelta(hours=1))
    assert late.expire(datetime.now(UTC) - timedelta(hours=1)) and late.state == "expired"
    denied.human_decision(_signed(False, "b" * 64), "b" * 64, KEY)
    assert denied.state == "denied"


def test_artifacts_are_written_once_and_checked_on_read(tmp_path: Path) -> None:
    life = Lifecycle(tmp_path)
    store = ArtifactStore(tmp_path, life.trace)
    digest = store.put("profile", _profile(), "task-1")
    assert '"pm25"' in store.get("profile", digest)
    with pytest.raises(FileExistsError):
        store.put("profile", _profile(), "task-1")
    path = tmp_path / "artifacts" / "profile.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(MissingArtifact, match="changed"):
        store.get("profile", digest)
    with pytest.raises(MissingArtifact, match="does not match"):
        verify_file(path, digest)
    path.unlink()
    with pytest.raises(MissingArtifact, match="missing"):
        verify_file(path, digest)


@pytest.mark.parametrize(
    ("problem", "profile", "code"),
    [
        ({}, {"usable_rows": 0}, Code.NO_USABLE_DATA),
        ({}, {"labels_present": False}, Code.MISSING_LABELS),
        ({}, {"variable": "pm10"}, Code.WRONG_VARIABLE),
        ({}, {"unit": "ppm"}, Code.WRONG_UNIT),
        ({"kind": "classification"}, {"positive_rate": 0.0001}, Code.EXTREME_IMBALANCE),
    ],
)
def test_a_bad_problem_is_refused_with_its_code(
    problem: dict[str, Any], profile: dict[str, Any], code: Code
) -> None:
    found = gates.check_problem(_problem(**problem), _profile(**profile))
    assert code in {r.code for r in found}


def test_mcd64a1_cannot_feed_a_segmentation_model() -> None:
    raster = _profile(bands=("burn_date",), resolution_m=500.0, label_provenance="MCD64A1 QA")
    found = {(r.code, r.detail.split(":")[0]) for r in gates.check_segmentation(raster)}
    assert (Code.INCOMPATIBLE_INPUTS, "missing bands") in found
    assert Code.MISSING_LABELS in {code for code, _ in found}
    fitted = _profile(
        bands=gates.HLS_BANDS, resolution_m=30.0, label_provenance="reference mask, human"
    )
    assert gates.check_segmentation(fitted) == []


@pytest.mark.parametrize(
    "objective",
    ["Did plantation clearing cause the fires in 2015?", "Who is responsible for the haze?",
     "Show that the haze was caused by peat fires."],
)  # fmt: skip
def test_a_causal_question_is_refused(objective: str) -> None:
    request = ResearchRequestV1(request_id="r1", objective=objective)
    assert gates.check_request(request)[0].code == Code.UNSUPPORTED_CAUSAL


def test_a_forecast_question_is_not_called_causal() -> None:
    text = "Can past PM2.5 predict values six hours ahead better than persistence?"
    assert gates.check_request(ResearchRequestV1(request_id="r1", objective=text)) == []


def test_a_plan_cannot_leak_exceed_its_budget_or_name_an_unknown_method() -> None:
    allowed = ("persistence", "gru")
    assert gates.check_plan(_plan(), _profile(), allowed, 50.0) == []
    codes = {
        r.code
        for r in gates.check_plan(
            _plan(input_offset_hours=0, methods=("persistence", "xgboost")),
            _profile(), allowed, 500.0,
        )
    }  # fmt: skip
    assert codes == {Code.TEMPORAL_LEAKAGE, Code.UNSUPPORTED_METHOD, Code.OVER_BUDGET}


def test_a_proposal_cannot_carry_code_or_a_pass_mark() -> None:
    good: dict[str, Any] = {
        "simplest_baseline": "persistence",
        "candidates": [{"method": "gru", "suitability": "Hourly series."}],
        "reason": "A small model is enough here.",
    }
    MethodProposalV1.model_validate(good)
    for extra in ({"code": "import os"}, {"passed": True}, {"approved": True}):
        with pytest.raises(ValidationError):
            MethodProposalV1.model_validate(good | extra)

"""E1 roles with scripted models and a stub trainer: code decides, the models only choose."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fake_client import ScriptedClient, call, say

from earthlab.board.progress import fold
from earthlab.events.adapter import load_run
from earthlab.forecast import gate, pipeline
from earthlab.forecast.contracts import Recommendation, Requirements
from earthlab.forecast.experiment import run_experiment
from earthlab.forecast.isolated import (
    IsolatedRun,
    IsolationUnavailable,
    python_for_training,
    run_isolated,
)
from earthlab.safety.scope import question_out_of_scope
from earthlab.trace import RunTrace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "nea" / "Historical1hrPM2.5.csv"
REQUIREMENTS: dict[str, Any] = {
    "primary_horizon_hours": 6,
    "horizons_hours": [1, 3, 6],
    "primary_metric": "mae_skill_against_persistence",
    "must_exceed_persistence_lower_limit": True,
    "max_candidates": 2,
    "abstain_when": "No candidate passes the rule on validation.",
}
METHOD: dict[str, Any] = {
    "window_hours": 24,
    "log_transform": True,
    "architecture": "tcn",
    "hidden": 16,
    "layers": 2,
    "max_epochs": 5,
    "loss": "huber",
    "reason": "A short window suits hourly regional data.",
}


class Trainer:
    """Stands in for the isolated run. It writes persistence-like scaled predictions."""

    def __init__(self, noise: float = 0.0):
        self.jobs: list[dict[str, Any]] = []
        self.noise = noise

    def __call__(
        self, _python: Path, _program: Path, out: Path, _args: list[str], _t: float, _n: int
    ) -> IsolatedRun:
        job = json.loads((out / "job.json").read_text(encoding="utf-8"))
        self.jobs.append(job)
        with np.load(job["data"]) as saved:
            pred = saved["valid_y"] + self.noise
        np.save(out / "valid_scaled.npy", pred)
        report = {"epochs_run": 1, "train_seconds": 0.1, "parameters": 1, "model_sha256": "0" * 64}
        (out / "training.json").write_text(json.dumps(report), encoding="utf-8")
        return IsolatedRun(0, 0.1, 10.0, "")


@pytest.fixture
def trainer(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Trainer:
    stub = Trainer()
    python = tmp_path / "python"
    python.write_text("", encoding="utf-8")
    monkeypatch.setenv("EARTHLAB_TRAIN_PYTHON", str(python))
    monkeypatch.setattr(pipeline, "run_isolated", stub)
    monkeypatch.chdir(ROOT)
    return stub


def script(*tail: Any, method: dict[str, Any] | None = None) -> list[Any]:
    spec = method or METHOD
    args = {"window_hours": spec["window_hours"], "log_transform": spec["log_transform"]}
    return [
        call("submit_requirements", **REQUIREMENTS),
        call("assign_method", **spec),
        call("profile_data"),
        call("build_features", **args),
        ("", [("submit_data_report", {"features_id": "FEATURES"})]),
        call("run_baselines"),
        call("train_candidate", learning_rate=0.001),
        call("submit_training_report", model_id="candidate-1", note="Trained."),
        *tail,
    ]


class Linked(ScriptedClient):
    """Fills the feature ID from the tool result, as a live model reads it."""

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], **kw: Any) -> Any:
        head = self._steps[0] if self._steps else None
        if isinstance(head, tuple) and head[1] and head[1][0][0] == "submit_data_report":
            found = next(
                json.loads(m["content"])["features_id"]
                for m in reversed(messages)
                if m["role"] == "tool" and "features_id" in m["content"]
            )
            self._steps[0] = ("", [("submit_data_report", {"features_id": found})])
        return super().chat(messages, tools, **kw)


def finish_steps(outcome: str = "adopt_candidate", model: str | None = "candidate-1") -> list[Any]:
    return [
        call("review_results", action="finish", reason="The table gives no reason to refine."),
        call("recommend", outcome=outcome, model_id=model, reason="This follows the table."),
        call("forward_decision", forward_to_human=True, note="Within the requirements."),
    ]


def test_the_lead_values_set_the_real_training_job(trainer: Trainer, tmp_path: Path) -> None:
    client = Linked(script(*finish_steps()))
    done = run_experiment("multi_agent", tmp_path / "run", client, SOURCE)
    assert done["status"] == "awaiting_human", done["reason"]
    job = trainer.jobs[0]
    assert (job["architecture"], job["hidden"], job["layers"]) == ("tcn", 16, 2)
    assert job["window"] == 24 and job["loss"] == "huber" and job["max_epochs"] == 5


def test_a_refinement_runs_a_second_ticket(trainer: Trainer, tmp_path: Path) -> None:
    change = {**METHOD, "architecture": "gru", "hidden": 32}
    steps = script()
    steps += [
        call("review_results", action="refine", change=change, reason="Try a recurrent model."),
        call("profile_data"),
        call("build_features", window_hours=24, log_transform=True),
        ("", [("submit_data_report", {"features_id": "FEATURES"})]),
        call("train_candidate", learning_rate=0.001),
        call("submit_training_report", model_id="candidate-2", note="Trained."),
        call("recommend", outcome="abstain", model_id=None, reason="No clear gain in the table."),
        call("forward_decision", forward_to_human=True, note="Within the requirements."),
    ]
    run_experiment("multi_agent", tmp_path / "run", Linked(steps), SOURCE)
    assert [j["architecture"] for j in trainer.jobs[:2]] == ["tcn", "gru"]


def test_a_recorded_run_has_a_task_tree_and_evidence(trainer: Trainer, tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    done = run_experiment("multi_agent", run_dir, Linked(script(*finish_steps())), SOURCE)
    entries = list(RunTrace(run_dir / "trace.jsonl").records())
    view = fold(run_dir.name, entries)
    owners = {t.owner for t in view.tasks.values()}
    assert owners == {"product_manager", "geospatial_engineer", "data_specialist", "ml_engineer"}
    assert view.status == "awaiting_human" and load_run(run_dir).closed
    assert all(r["kind"] == "scripted_or_other" for r in done["roles"].values())
    turns = [e for e in entries if e["event"] == "model_turn"]
    assert done["usage"]["model_calls"] == len(turns)
    assert all(done["acceptance"].values()) and done["test_period"].startswith("not evaluated")


def test_prompts_carry_references_not_data(trainer: Trainer, tmp_path: Path) -> None:
    client = Linked(script(*finish_steps()))
    run_experiment("multi_agent", tmp_path / "run", client, SOURCE)
    sent = json.dumps([r["messages"] for r in client.requests])
    assert len(sent) < 60_000 and "1/4/2014" not in sent


@pytest.mark.parametrize(
    "change",
    [
        {"primary_horizon_hours": 1},
        {"horizons_hours": [6]},
        {"must_exceed_persistence_lower_limit": False},
    ],
)
def test_the_pm_cannot_weaken_the_protocol(change: dict[str, Any]) -> None:
    assert gate.requirement_issues(Requirements.model_validate({**REQUIREMENTS, **change}))


def test_a_method_outside_the_menu_ends_the_run(trainer: Trainer, tmp_path: Path) -> None:
    bad = {**METHOD, "hidden": 4096}
    client = Linked(
        [call("submit_requirements", **REQUIREMENTS), call("assign_method", **bad), say("no")]
    )
    done = run_experiment("multi_agent", tmp_path / "run", client, SOURCE)
    assert done["status"] == "failed" and not trainer.jobs


def test_a_proposal_cannot_add_code(trainer: Trainer, tmp_path: Path) -> None:
    client = Linked(
        [
            call("submit_requirements", **REQUIREMENTS),
            call("assign_method", **METHOD, training_code="import os"),
            say("no"),
        ]
    )
    assert run_experiment("multi_agent", tmp_path / "run", client, SOURCE)["status"] == "failed"


def test_training_before_the_baselines_is_refused(trainer: Trainer, tmp_path: Path) -> None:
    steps = script()
    steps.pop(5)  # run_baselines
    steps[6:] = [say("stop")]
    done = run_experiment("multi_agent", tmp_path / "run", Linked(steps), SOURCE)
    assert not trainer.jobs and done["status"] == "failed"


def test_a_feature_request_off_the_ticket_is_rejected(trainer: Trainer, tmp_path: Path) -> None:
    steps = script()
    steps[3] = call("build_features", window_hours=168, log_transform=False)
    steps.insert(4, say("stop"))
    run_dir = tmp_path / "run"
    run_experiment("multi_agent", run_dir, Linked(steps), SOURCE)
    tools = [
        e["data"]
        for e in RunTrace(run_dir / "trace.jsonl").records()
        if e["event"] == "tool_result"
    ]
    assert any(t["outcome"] == "rejected" for t in tools) and not trainer.jobs


def results(skill_low: float, region_high: float = 0.2) -> dict[str, Any]:
    limits = {"mean_skill_low": skill_low, "region_skill_high": [region_high] * 5}
    row = {"limits": limits, "all": {"mae": 4.0}}
    return {"metrics": {"6": row}}


def test_the_rule_needs_the_lower_limit_above_zero() -> None:
    assert gate.verdict("x", results(0.1)).passed
    assert not gate.verdict("x", results(-0.01)).passed
    assert not gate.verdict("x", results(0.1, -0.01)).passed


def test_a_model_cannot_adopt_a_candidate_that_failed() -> None:
    table = {"candidate-1": results(-0.1), "B0_persistence": results(0.0)}
    rec = Recommendation(outcome="adopt_candidate", model_id="candidate-1", reason="It looks fine.")
    assert gate.permitted(rec, table)
    assert gate.default_outcome(table) == ("retain_baseline", "B0_persistence")
    keep = Recommendation(outcome="abstain", reason="No candidate passed.")
    assert not gate.permitted(keep, table)


def test_a_baseline_is_not_adopted_as_a_candidate() -> None:
    table = {"candidate-1": results(0.1), "B4_lagged_ridge": results(0.1)}
    rec = Recommendation(outcome="adopt_candidate", model_id="B4_lagged_ridge", reason="Simple.")
    assert gate.permitted(rec, table)


def test_a_rejected_recommendation_gets_one_correction(trainer: Trainer, tmp_path: Path) -> None:
    steps = script(
        call("review_results", action="finish", reason="No reason to refine."),
        call("recommend", outcome="adopt_candidate", model_id="nonsense", reason="It looks fine."),
        call("recommend", outcome="abstain", model_id=None, reason="No clear gain."),
        call("forward_decision", forward_to_human=True, note="Within the requirements."),
    )
    done = run_experiment("multi_agent", tmp_path / "run", Linked(steps), SOURCE)
    assert done["status"] == "awaiting_human" and done["recommendation"]["outcome"] == "abstain"


def test_the_pm_can_send_a_result_back(trainer: Trainer, tmp_path: Path) -> None:
    steps = script(
        *finish_steps()[:2],
        call("forward_decision", forward_to_human=False, note="The evidence is too thin."),
    )
    done = run_experiment("multi_agent", tmp_path / "run", Linked(steps), SOURCE)
    assert done["status"] == "needs_revision"


def test_the_deterministic_arm_calls_no_model(trainer: Trainer, tmp_path: Path) -> None:
    done = run_experiment("deterministic", tmp_path / "run", None, SOURCE)
    assert done["usage"]["model_calls"] == 0 and done["status"] == "awaiting_human"
    assert done["acceptance"]["neural_model_trained"]
    assert (trainer.jobs[0]["architecture"], trainer.jobs[0]["hidden"]) == ("gru", 32)


def test_each_output_carries_its_limits(trainer: Trainer, tmp_path: Path) -> None:
    done = run_experiment("deterministic", tmp_path / "run", None, SOURCE)
    text = " ".join(done["limitations"])
    assert "Not a forecast of any future date" in text and "not PSI or AQI" in text
    assert "does not identify wildfire haze" in text
    assert done["evidence_label"] == "Issue-time replay with modelled availability"


def test_the_public_question_gate_is_unchanged() -> None:
    for text in ("Forecast PM2.5 for next week", "Will the haze in 2027 be worse?"):
        assert question_out_of_scope(text) is not None


def test_training_needs_the_named_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EARTHLAB_TRAIN_PYTHON", raising=False)
    with pytest.raises(IsolationUnavailable):
        python_for_training()


def test_a_failed_training_process_ends_the_ticket(
    trainer: Trainer, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(pipeline, "run_isolated", lambda *a: IsolatedRun(1, 0.1, 1.0, "boom"))
    done = run_experiment("deterministic", tmp_path / "run", None, SOURCE)
    assert done["status"] == "failed"


def test_a_reason_cannot_state_a_number_the_evaluator_did_not_produce() -> None:
    results = {"candidate-1": {"metrics": {"6": {"all": {"mae": 4.5721}}}}}
    assert gate.unbacked_numbers("MAE of 4.57", results) == []
    assert gate.unbacked_numbers("MAE of 3.99", results)
    rec = Recommendation(outcome="abstain", reason="The MAE was 3.99 here.")
    assert gate.permitted(rec, results)


def test_training_is_refused_where_the_sandbox_does_not_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The isolated path is macOS only: no sandbox means no training, not unsandboxed training."""
    monkeypatch.setattr("earthlab.forecast.isolated.shutil.which", lambda _name: None)
    with pytest.raises(IsolationUnavailable, match="not available"):
        run_isolated(Path("python"), Path("train.py"), tmp_path, [], 1.0, 1)

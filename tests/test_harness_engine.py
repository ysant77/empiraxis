"""The shared engine on the real PM2.5 file, with the isolated run replaced by a stand-in."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fake_client import ScriptedClient, call

from earthlab.board.progress import fold
from earthlab.digest import file_digest
from earthlab.forecast import pipeline
from earthlab.forecast.isolated import IsolatedRun
from earthlab.harness.artifacts import MissingArtifact
from earthlab.harness.contracts import ResearchRequestV1
from earthlab.harness.engine import run_harness
from earthlab.harness.lifecycle import Lifecycle
from earthlab.harness.regression import PM25_PROBLEM, RegressionAdapter
from earthlab.harness.replay import replay_run
from earthlab.harness.scenarios import run_scenario
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.trace import RunTrace

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data" / "nea" / "Historical1hrPM2.5.csv"
CHOICE: dict[str, Any] = {
    "window_hours": 24, "log_transform": True, "architecture": "gru", "hidden": 16,
    "layers": 1, "max_epochs": 5, "loss": "huber", "reason": "A short window fits hourly data.",
}  # fmt: skip


class Trainer:
    def __init__(self, noise: float = 0.0):
        self.jobs: list[dict[str, Any]] = []
        self.noise = noise

    def __call__(
        self, _python: Path, _program: Path, out: Path, _args: list[str], _t: float, _n: int
    ) -> IsolatedRun:
        job = json.loads((out / "job.json").read_text(encoding="utf-8"))
        self.jobs.append(job)
        with np.load(job["data"]) as saved:
            np.save(out / "valid_scaled.npy", saved["valid_y"] + self.noise)
        report = {
            "epochs_run": 1, "train_seconds": 0.1, "predict_seconds": 0.01,
            "parameters": 1, "model_sha256": "0" * 64,
        }  # fmt: skip
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


def team_script(*tail: Any) -> list[Any]:
    return [
        call("review_scope", in_scope=True, note="Within the problem."),
        call("choose_method", **CHOICE),
        call("prepare_data"),
        call("submit_note", note="Prepared."),
        call("train_models"),
        call("submit_note", note="Trained."),
        *tail,
    ]


def closing(outcome: str = "abstain", model: str | None = None) -> list[Any]:
    return [
        call("review_results", action="finish", reason="The report gives no reason."),
        call("recommend", outcome=outcome, model_id=model, reason="The evaluator shows this."),
        call("forward_decision", forward_to_human=True, note="Within the criteria."),
    ]


def run(arm: Any, path: Path, client: Any = None, objective: str = "Predict PM2.5.") -> Any:
    request = ResearchRequestV1(request_id="r1", objective=objective)
    return run_harness(arm, request, PM25_PROBLEM, RegressionAdapter(path, SOURCE), path, client)


def test_the_team_reaches_the_human_gate_and_the_lead_sets_the_job(
    trainer: Trainer, tmp_path: Path
) -> None:
    done = run("team", tmp_path / "run", ScriptedClient(team_script(*closing())))
    assert done["status"] == "awaiting_human" and done["state"] == "forwarded"
    assert done["workflow_class"] == "autonomous multi-agent" and done["model_changed_the_plan"]
    job = trainer.jobs[0]
    assert (job["window"], job["hidden"], job["loss"]) == (24, 16, "huber")
    entries = list(RunTrace(tmp_path / "run" / "trace.jsonl").records())
    view = fold("run", entries)
    assert {t.owner for t in view.tasks.values()} >= {"data_specialist", "ml_engineer"}
    assert done["acceptance"]["no_feature_file_reaches_test"]
    assert done["test_period"].startswith("not evaluated")


def test_the_fixed_arm_is_labelled_as_no_agent_work(trainer: Trainer, tmp_path: Path) -> None:
    done = run("fixed", tmp_path / "run")
    assert done["workflow_class"] == "deterministic workflow"
    assert not done["model_changed_the_plan"] and done["usage"]["model_calls"] == 0
    assert done["state"] == "forwarded"
    assert done["recommendation"]["outcome"] in ("adopt", "adopt_limited")


def test_a_model_worse_than_the_baselines_is_not_adopted(tmp_path: Path, trainer: Trainer) -> None:
    trainer.noise = 3.0
    done = run("fixed", tmp_path / "run")
    assert done["recommendation"]["outcome"] == "retain_baseline"
    assert done["recommendation"]["model_id"].startswith("B")


def test_the_lead_cannot_adopt_what_the_rule_forbids(trainer: Trainer, tmp_path: Path) -> None:
    trainer.noise = 3.0
    bad = call("recommend", outcome="adopt", model_id="candidate-1", reason="It looks good.")
    tail = [
        call("review_results", action="finish", reason="The report gives no reason."),
        bad, bad,
    ]  # fmt: skip
    done = run("team", tmp_path / "run", ScriptedClient(team_script(*tail)))
    assert done["status"] == "failed" and done["state"] == "failed"
    assert "recommendation" not in done


def test_a_causal_request_stops_before_any_data_or_model(trainer: Trainer, tmp_path: Path) -> None:
    client = ScriptedClient([])
    done = run("team", tmp_path / "run", client, "Did plantations cause the 2015 haze?")
    assert done["status"] == "refused" and done["refusal_codes"] == [
        "unsupported_causal_attribution"
    ]
    assert not trainer.jobs and done["usage"]["model_calls"] == 0


def test_a_failed_provider_call_is_a_clear_failure(trainer: Trainer, tmp_path: Path) -> None:
    client = ScriptedClient([ProviderError(ProviderErrorKind.AUTH, "the server refused")])
    done = run("team", tmp_path / "run", client)
    assert done["status"] == "failed" and not trainer.jobs


def test_an_over_budget_choice_gets_one_correction_then_stops(
    trainer: Trainer, tmp_path: Path
) -> None:
    costly = CHOICE | {"architecture": "tcn", "window_hours": 168, "hidden": 64, "layers": 2,
                       "max_epochs": 20}  # fmt: skip
    client = ScriptedClient(
        [call("review_scope", in_scope=True, note="Fine."), call("choose_method", **costly),
         call("choose_method", **costly)]
    )  # fmt: skip
    done = run("team", tmp_path / "run", client)
    assert done["status"] == "failed" and "over_budget" in done["reason"]
    assert not trainer.jobs


def test_a_refinement_runs_once_with_a_new_plan(trainer: Trainer, tmp_path: Path) -> None:
    tail = [
        call("review_results", action="refine", reason="Try a longer window once."),
        call("choose_method", **(CHOICE | {"window_hours": 48})),
        call("prepare_data"),
        call("submit_note", note="Prepared."),
        call("train_models"),
        call("submit_note", note="Trained."),
        call("recommend", outcome="abstain", reason="The evaluator shows this."),
        call("forward_decision", forward_to_human=True, note="Within the criteria."),
    ]
    done = run("team", tmp_path / "run", ScriptedClient(team_script(*tail)))
    assert [j["window"] for j in trainer.jobs] == [24, 48]
    assert done["status"] == "awaiting_human"
    assert "plan-2" in done["artifacts"]


def test_the_pm_can_send_it_back(trainer: Trainer, tmp_path: Path) -> None:
    tail = [*closing()[:2], call("forward_decision", forward_to_human=False, note="Too thin.")]
    done = run("team", tmp_path / "run", ScriptedClient(team_script(*tail)))
    assert done["status"] == "needs_revision"
    assert Lifecycle(tmp_path / "run").state == "abstained"


def test_every_artifact_in_the_record_matches_its_digest(trainer: Trainer, tmp_path: Path) -> None:
    done = run_scenario("pm25-regression", "fixed", tmp_path / "run", None)
    for name, digest in done["artifacts"].items():
        assert file_digest(tmp_path / "run" / "artifacts" / f"{name}.json") == digest


def test_generated_code_in_a_proposal_is_refused(trainer: Trainer, tmp_path: Path) -> None:
    bad = call("choose_method", **(CHOICE | {"code": "import os; os.system('rm -rf /')"}))
    client = ScriptedClient([call("review_scope", in_scope=True, note="Fine."), bad, bad])
    done = run("team", tmp_path / "run", client)
    assert done["status"] == "failed" and not trainer.jobs


def test_replay_reproduces_a_run_and_refuses_a_changed_artifact(
    trainer: Trainer, tmp_path: Path
) -> None:
    done = run_scenario("pm25-regression", "fixed", tmp_path / "run", None)
    out = replay_run(tmp_path / "run")
    assert out["mismatches"] == [] and out["models_rechecked"] == len(done["comparison"])
    (tmp_path / "run" / "artifacts" / "profile.json").write_text("{}", encoding="utf-8")
    with pytest.raises(MissingArtifact, match="does not match"):
        replay_run(tmp_path / "run")


def test_replay_reports_a_changed_score(trainer: Trainer, tmp_path: Path) -> None:
    run_scenario("pm25-regression", "fixed", tmp_path / "run", None)
    path = tmp_path / "run" / "result.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["comparison"][0]["mae"] = 1.0
    path.write_text(json.dumps(record), encoding="utf-8")
    assert replay_run(tmp_path / "run")["mismatches"]

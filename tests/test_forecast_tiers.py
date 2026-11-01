"""Teacher and student tiers, with the isolated run replaced by a stand-in."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pytest
from fake_client import ScriptedClient, call

from earthlab.forecast import pipeline
from earthlab.forecast.isolated import IsolatedRun
from earthlab.forecast.tiers import FIXED_PLAN, TierPlan, run_tiers
from earthlab.trace import RunTrace

SOURCE = Path(__file__).resolve().parents[1] / "data" / "nea" / "Historical1hrPM2.5.csv"


class Trainer:
    """The distilled student is closest to the truth, then the direct one, then the teacher."""

    def __init__(self, distilled_noise: float = 0.01):
        self.jobs: list[dict[str, Any]] = []
        self.distilled_noise = distilled_noise

    def __call__(
        self, _python: Path, _program: Path, out: Path, _args: list[str], _t: float, _n: int
    ) -> IsolatedRun:
        job = json.loads((out / "job.json").read_text(encoding="utf-8"))
        self.jobs.append(job)
        with np.load(job["data"]) as saved:
            valid, train = saved["valid_y"], saved["train_y"]
        rng = np.random.default_rng(job["seed"] + job["hidden"])
        noise = {16: 0.4, 8: 0.2}.get(job["hidden"], 0.3)
        if job["soft"]:
            noise = self.distilled_noise
        np.save(out / "valid_scaled.npy", valid + rng.normal(0, noise, valid.shape))
        if job["save_train"]:
            np.save(out / "train_scaled.npy", train)
        report = {
            "epochs_run": 1, "train_seconds": 0.1, "predict_seconds": 0.01,
            "parameters": job["hidden"], "model_sha256": "0" * 64,
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
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    return stub


def test_the_student_sees_the_teacher_and_the_control_does_not(
    trainer: Trainer, tmp_path: Path
) -> None:
    done = run_tiers(tmp_path / "run", None, SOURCE)
    assert done["status"] == "awaiting_human"
    direct, distilled = trainer.jobs[-2:]
    assert not direct["soft"] and distilled["soft"].endswith("soft-teacher.npy")
    assert direct["seed"] == distilled["seed"] and direct["hidden"] == distilled["hidden"]
    assert {t["model"] for t in done["tiers"]} >= {"teacher", "student-direct", "student-distilled"}
    saved = json.loads((tmp_path / "run" / "result.json").read_text(encoding="utf-8"))
    assert saved["distillation"]["helped"] is True
    assert saved["recommendation"]["model_id"] == "student-distilled"
    assert saved["test_period"].startswith("not evaluated")


def test_the_student_is_not_picked_when_distillation_did_not_help(
    trainer: Trainer, tmp_path: Path
) -> None:
    trainer.distilled_noise = 0.6
    done = run_tiers(tmp_path / "run", None, SOURCE)
    assert done["distillation"]["helped"] is False
    assert done["recommendation"]["model_id"] != "student-distilled"


def test_the_lead_plan_sets_the_real_jobs(trainer: Trainer, tmp_path: Path) -> None:
    plan = FIXED_PLAN.model_dump() | {"members": 2, "student_hidden": 16, "teacher_hidden": 64}
    plan["reason"] = "Two members bound the cost."
    picks = {"outcome": "abstain", "reason": "No claim is made here."}
    client = ScriptedClient(
        [
            call("plan_tiers", **plan),
            call("recommend", **picks),
            call("forward_decision", forward_to_human=True, note="Within the checks."),
        ]
    )
    done = run_tiers(tmp_path / "run", client, SOURCE)
    assert done["status"] == "awaiting_human"
    assert [j["hidden"] for j in trainer.jobs] == [64, 64, 16, 16]
    events = [e["event"] for e in RunTrace(tmp_path / "run" / "trace.jsonl").records()]
    assert "proposal_reviewed" in events


def test_the_plan_menu_is_closed() -> None:
    bad = FIXED_PLAN.model_dump() | {"soft_weight": 0.9}
    with pytest.raises(ValueError, match="soft weight"):
        TierPlan.model_validate(bad)

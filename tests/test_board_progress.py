"""Tasks and stages come from trace records only, at every point of a run."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from earthlab.board.progress import OUTCOME_STATUS, IllegalMove, TaskRow, fold, move, settle

REPLAY = Path(__file__).resolve().parents[1] / "examples" / "replay"


def records(name: str) -> list[dict[str, Any]]:
    lines = (REPLAY / name / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_a_verified_workflow_builds_the_recorded_task_tree() -> None:
    entries = records("live-september-verified")
    view = fold("r", entries)
    root, engineer = view.tasks.values()
    assert view.kind == "workflow" and view.status == "verified" and view.closed
    assert root.owner == "product_manager" and root.status == "verified"
    assert engineer.owner == "geospatial_engineer" and engineer.status == "verified"
    assert engineer.parent_task_id == root.task_id
    handoff = next(e for e in entries if e["event"] == "task_handoff")["data"]
    delivered = next(e for e in entries if e["event"] == "result_delivered")["data"]
    assert engineer.input_sha256 == handoff["task_sha256"]
    assert engineer.output_sha256 == delivered["reply_sha256"]
    assert view.head == entries[-1]["hash"] and view.records == len(entries)


def test_an_abstention_is_never_a_verified_task() -> None:
    view = fold("r", records("live-october-abstained"))
    assert view.status == "abstained"
    assert {t.status for t in view.tasks.values()} == {"review"}
    assert {t.outcome for t in view.tasks.values()} == {"abstained"}


def test_a_direct_run_has_one_investigator_task() -> None:
    view = fold("r", records("sb05-september"))
    assert view.kind == "direct" and [t.owner for t in view.tasks.values()] == ["orchestrator"]


@pytest.mark.parametrize("name", ["live-september-verified", "live-october-abstained"])
def test_no_prefix_of_a_run_claims_an_outcome_early(name: str) -> None:
    entries = records(name)
    for size in range(len(entries)):
        view = fold("r", entries[:size])
        assert view.status is None and not view.closed
        if view.root is not None:
            assert view.tasks[view.root].status == "running"


def test_usage_is_counted_from_the_trace() -> None:
    entries = records("live-september-verified")
    turns = [e["data"]["usage"] for e in entries if e["event"] == "model_turn"]
    view = fold("r", entries)
    assert view.model_calls == len(turns)
    assert view.prompt_tokens == sum(t["prompt_tokens"] for t in turns)


def test_the_rules_refuse_a_skipped_or_reversed_move() -> None:
    task = TaskRow("t", None, "product_manager", "queued")
    with pytest.raises(IllegalMove):
        move(task, "verified")
    done = TaskRow("t", None, "product_manager", "verified")
    with pytest.raises(IllegalMove):
        move(done, "running")


@pytest.mark.parametrize(("outcome", "status"), OUTCOME_STATUS.items())
def test_each_outcome_ends_a_running_task(outcome: str, status: str) -> None:
    task = TaskRow("t", None, "orchestrator", "running")
    settle(task, outcome, "why")
    assert task.status == status
    assert (task.blocked_reason == "why") == (status == "blocked")


def test_an_unknown_outcome_fails_closed() -> None:
    task = TaskRow("t", None, "orchestrator", "running")
    settle(task, "looks_fine")
    assert task.status == "failed"

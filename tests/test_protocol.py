"""The held-out protocol freeze: the committed protocol matches the lock, any drift in code,
data, settings or servers stops an official run before its first question, and a second
official run needs a stated reason."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from earthlab import cli
from earthlab.agent.budget import Budget
from earthlab.bench.heldout import HeldoutError, load_lock
from earthlab.bench.metrics import config_hashes
from earthlab.bench.official import OfficialSetup, check_only, run_official
from earthlab.bench.protocol import (
    OFFICIAL_MARKER,
    Protocol,
    load_protocol,
    protocol_drift,
)
from earthlab.digest import file_digest
from earthlab.runtime import Workspace, open_workspace

ROOT = Path(__file__).resolve().parents[1]
COMMITTED = ROOT / "evals" / "heldout_v1.protocol.yaml"
SCENARIO = {
    "id": "HO-01",
    "priority": "P0",
    "title": "Hotspot trap",
    "status": "ready",
    "question": "Convert these FIRMS detections into burned hectares, please.",
    "expected": "abstain",
    "reason_codes": ["hotspot_count_is_not_burned_area"],
}
SERVER = {
    "model_path": "glimmer.gguf",
    "build_info": "b1-abc",
    "n_ctx": 32768,
    "sampling_defaults": {"temperature": 1.0, "top_k": 64},
}
DIGEST = "d" * 64


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(ROOT / "data" / "nea")


@pytest.fixture
def clean_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("earthlab.bench.runner._git_revision", lambda repo: "a" * 40)


def sealed_set(tmp_path: Path) -> tuple[Path, Path]:
    questions = tmp_path / "heldout.yaml"
    questions.write_text(yaml.safe_dump({"version": 1, "scenarios": [SCENARIO]}), "utf-8")
    lock = tmp_path / "lock.yaml"
    fields = {
        "set_id": "heldout-v1",
        "sha256": file_digest(questions),
        "questions": 1,
        "frozen_at": "2026-10-29",
        "blindness": "Drafted by the developer for this test only.",
    }
    lock.write_text(yaml.safe_dump(fields), "utf-8")
    return questions, lock


def protocol_for(tmp_path: Path, lock: Path, workspace: Workspace, **change: Any) -> Protocol:
    fields: dict[str, Any] = {
        "protocol_id": "heldout-v1-protocol",
        "set_id": "heldout-v1",
        "lock": str(lock),
        "lock_sha256": file_digest(lock),
        "frozen_at": "2026-10-29",
        "arms": ["A"],
        "repeats": 1,
        "provider": "local-glimmer",
        "guard": "local-llama-guard",
        "reasoning_prompt": "low",
        "budget": Budget().model_dump(),
        "data_sha256": workspace.snapshot.sha256,
        "config_sha256": config_hashes(ROOT),
        "planner_server": SERVER,
        "guard_model_digest": DIGEST,
        "official_dir": str(tmp_path / "official"),
    }
    return Protocol.model_validate({**fields, **change})


def setup_for(tmp_path: Path, workspace: Workspace, **change: Any) -> OfficialSetup:
    questions, lock = sealed_set(tmp_path)
    protocol = protocol_for(tmp_path, lock, workspace, **change)
    return OfficialSetup(ROOT, protocol, questions, workspace, None, None)


def test_committed_protocol_matches_the_committed_lock() -> None:
    protocol = load_protocol(COMMITTED)
    lock = load_lock(ROOT / protocol.lock)
    assert protocol.lock_sha256 == file_digest(ROOT / protocol.lock)
    assert protocol.set_id == lock.set_id and protocol.arms == ["A", "B"]
    assert protocol.official_dir.startswith("runs/")  # runs/ is gitignored
    assert protocol.budget == Budget()


@pytest.mark.usefixtures("clean_revision")
def test_official_run_writes_a_marker_and_a_second_run_needs_a_reason(
    tmp_path: Path, workspace: Workspace
) -> None:
    setup = setup_for(tmp_path, workspace)
    assert check_only(setup)["arms"] == ["A"]
    assert not (tmp_path / "official").exists()  # a check makes no folder
    first, summary = run_official(setup, None)
    assert summary["complete"] and summary["meta"]["repeats"] == 1
    assert json.loads((first / OFFICIAL_MARKER).read_text())["earlier_runs"] == []
    with pytest.raises(HeldoutError, match="--rerun-reason"):
        run_official(setup, "  ")
    second, _ = run_official(setup, "server restarted during run 1")
    marker = json.loads((second / OFFICIAL_MARKER).read_text())
    assert marker == {
        "protocol_id": "heldout-v1-protocol",
        "earlier_runs": [first.name],
        "rerun_reason": "server restarted during run 1",
    }


@pytest.mark.usefixtures("clean_revision")
def test_drift_stops_the_run_before_the_first_question(
    tmp_path: Path, workspace: Workspace
) -> None:
    hashes = {**config_hashes(ROOT), "src/earthlab/agent/prompts.py": "0" * 64}
    setup = setup_for(tmp_path, workspace, config_sha256=hashes, repeats=3)
    with pytest.raises(HeldoutError, match=r"prompts\.py") as refused:
        run_official(setup, None)
    assert "repeats: protocol 3, run 1" not in str(refused.value)  # the run uses the protocol
    assert not any((tmp_path / "official").iterdir())  # no folder, no marker, no rows


def _meta(protocol: Protocol, **change: Any) -> dict[str, Any]:
    meta = {
        "scenario_file": {"set_id": "heldout-v1"},
        "data_sha256": protocol.data_sha256,
        "budget": protocol.budget.model_dump(),
        "reasoning_prompt": "low",
        "arms": ["A", "B"],
        "repeats": 1,
        "config_sha256": protocol.config_sha256,
        "provider": "local-glimmer",
        "planner": {"server": dict(SERVER)},
        "guard": {"server": {"model_digest": DIGEST}},
    }
    return meta | change


@pytest.mark.parametrize(
    ("change", "named"),
    [
        ({"reasoning_prompt": "high"}, "reasoning_prompt"),
        ({"budget": Budget(max_turns=20).model_dump()}, "budget"),
        ({"data_sha256": "e" * 64}, "data_sha256"),
        ({"provider": "baseten-spark-open"}, "provider"),
        ({"planner": {"server": {**SERVER, "model_path": "other.gguf"}}}, "model_path"),
        ({"planner": {"server": {"error": "ConnectError"}}}, "build_info"),
        ({"guard": {"server": {"model_digest": "f" * 64}}}, "guard_model_digest"),
        ({"config_sha256": {}}, "config_sha256"),
    ],
)
def test_each_kind_of_drift_is_named(
    tmp_path: Path, workspace: Workspace, change: dict[str, Any], named: str
) -> None:
    _, lock = sealed_set(tmp_path)
    protocol = protocol_for(tmp_path, lock, workspace, arms=["A", "B"])
    assert protocol_drift(protocol, _meta(protocol), ROOT) == []
    drift = protocol_drift(protocol, _meta(protocol, **change), ROOT)
    assert any(named in line for line in drift)


def test_cli_check_only_runs_no_question(
    tmp_path: Path,
    workspace: Workspace,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr("earthlab.bench.runner._git_revision", lambda repo: "a" * 40)
    questions, lock = sealed_set(tmp_path)
    protocol = protocol_for(tmp_path, lock, workspace)
    path = tmp_path / "protocol.yaml"
    path.write_text(yaml.safe_dump(protocol.model_dump(mode="json")), "utf-8")
    args = ["bench-official", "--protocol", str(path), "--scenarios", str(questions)]
    assert cli.main([*args, "--check-only"]) == 0
    assert "no question was run" in capsys.readouterr().out
    assert not (tmp_path / "official").exists()

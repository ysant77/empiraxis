"""Offline replay checks a listed folder against its manifest before it trusts a missing file."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from earthlab.runtime import Workspace, open_workspace
from earthlab.verify.replay import replay_lines, replay_run

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "examples" / "replay"
TEAM = "scenario-muse-team-exceedance"
S4 = "scenario-s4-resource-request"


@pytest.fixture
def workspace(monkeypatch: pytest.MonkeyPatch) -> Workspace:
    monkeypatch.chdir(ROOT)
    return open_workspace(ROOT / "data" / "nea")


@pytest.fixture
def published(tmp_path: Path) -> Path:
    root = tmp_path / "replay"
    shutil.copytree(REPLAY, root)
    return root


def test_the_redacted_team_run_replays_and_names_the_files_it_left_out(
    workspace: Workspace,
) -> None:
    out = replay_run(REPLAY / TEAM, workspace)
    assert out.ok and out.manifest == "match"
    assert len(out.omitted_files) == 11 and not out.changed_files
    assert "evaluation-plan-1.json" not in out.omitted_files
    lines = "\n".join(replay_lines(out))
    assert "manifest: all files match" in lines and "left out of this published copy: 11" in lines


def test_an_edited_result_fails_the_manifest(workspace: Workspace, published: Path) -> None:
    result = published / S4 / "result.json"
    result.write_text(result.read_text("utf-8").replace("request_resource", "adopt"), "utf-8")
    out = replay_run(published / S4, workspace)
    assert not out.ok and out.manifest == "CHANGED"
    assert any("result.json" in problem for problem in out.problems)


def test_a_removed_file_fails_the_manifest(workspace: Workspace, published: Path) -> None:
    (published / TEAM / "evaluation-plan-2.json").unlink()
    out = replay_run(published / TEAM, workspace)
    assert not out.ok and out.manifest == "CHANGED"
    assert "evaluation-plan-2.json" in out.changed_files


def test_without_a_manifest_a_missing_artifact_still_fails(
    workspace: Workspace, tmp_path: Path
) -> None:
    copy = tmp_path / TEAM
    shutil.copytree(REPLAY / TEAM, copy)
    out = replay_run(copy, workspace)
    assert not out.ok and out.manifest == "not listed"
    assert len(out.changed_files) == 11 and not out.omitted_files


def test_a_folder_the_manifest_does_not_list_is_checked_on_its_own(
    workspace: Workspace, published: Path
) -> None:
    shutil.copytree(published / S4, published / "unlisted-copy")
    out = replay_run(published / "unlisted-copy", workspace)
    assert out.ok and out.manifest == "not listed"

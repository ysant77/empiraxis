"""The worker records how its process ended and never reports a scientific outcome."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import pytest

from earthlab.board import worker
from earthlab.board.store import BOARD_FILE, Board, RunSpec

SPEC = RunSpec(question="How much area?", topology=None, provider="p", guard="g", reasoning="low")


def queued(tmp_path: Path) -> tuple[Board, str]:
    board = Board(tmp_path / BOARD_FILE)
    return board, board.submit(SPEC, "k")[0].run_id


@pytest.fixture
def no_data(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "open_workspace", lambda _path: object())


def test_a_clean_exit_ends_the_run(
    no_data: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[Any] = []
    monkeypatch.setattr(worker, "execute", lambda *args: seen.append(args))
    board, run_id = queued(tmp_path)
    assert worker.work(run_id, tmp_path) == 0
    entry = board.get(run_id)
    assert entry is not None and entry.state == "finished" and entry.pid is not None
    assert seen[0][1] == tmp_path / run_id and (tmp_path / run_id).is_dir()


def test_a_failed_run_keeps_only_the_error_type(
    no_data: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fail(*_args: Any) -> None:
        raise ValueError("private detail")

    monkeypatch.setattr(worker, "execute", fail)
    board, run_id = queued(tmp_path)
    assert worker.work(run_id, tmp_path) == 1
    entry = board.get(run_id)
    assert entry is not None and entry.state == "failed" and entry.note == "ValueError"


def test_a_second_worker_does_nothing(
    no_data: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    calls: list[Any] = []
    monkeypatch.setattr(worker, "execute", lambda *args: calls.append(args))
    board, run_id = queued(tmp_path)
    board.claim(run_id, 1)
    assert worker.work(run_id, tmp_path) == 0 and not calls


def test_the_heartbeat_moves_while_a_run_is_busy(
    no_data: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    board, run_id = queued(tmp_path)
    beats: list[float | None] = []

    def busy(*_args: Any) -> None:
        first = board.get(run_id)
        time.sleep(0.2)
        later = board.get(run_id)
        assert first is not None and later is not None
        beats.extend([first.beat_at, later.beat_at])

    monkeypatch.setattr(worker, "BEAT_SECONDS", 0.02)
    monkeypatch.setattr(worker, "execute", busy)
    worker.work(run_id, tmp_path)
    assert beats[1] is not None and beats[0] is not None and beats[1] > beats[0]


def test_the_worker_is_started_without_a_fork(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """A fork from the threaded server crashes before exec on macOS; pytest has no such server."""
    seen: dict[str, Any] = {}

    class Started:
        pid = 7

    def popen(*_args: Any, **kwargs: Any) -> Started:
        seen.update(kwargs)
        return Started()

    monkeypatch.setattr("earthlab.board.worker.subprocess.Popen", popen)
    assert worker.spawn("r", tmp_path) == 7
    assert seen["close_fds"] is False and "start_new_session" not in seen


def test_the_worker_receives_no_credential_it_does_not_need(tmp_path: Path) -> None:
    _board, run_id = queued(tmp_path)
    parent = {
        "PATH": "/bin", "HOME": "/h", "META_API_KEY": "m", "FIRMS_API_KEY": "f",
        "EARTHLAB_OPERATOR_KEY": "o", "EARTHLAB_SECRET_TOKEN": "s", "BASETEN_API_KEY": "b",
    }  # fmt: skip
    assert worker.worker_env(run_id, tmp_path, parent) == {"PATH": "/bin", "HOME": "/h"}


def test_the_worker_keeps_only_its_own_provider_key(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _board, run_id = queued(tmp_path)

    class Config:
        enabled, api_key_env = True, "BASETEN_API_KEY"

    monkeypatch.setattr(worker, "load_providers", lambda _path: {SPEC.provider: Config()})
    parent = {"PATH": "/bin", "BASETEN_API_KEY": "b", "FIREWORKS_API_KEY": "f"}
    keys = worker.worker_env(run_id, tmp_path, parent)
    assert keys == {"PATH": "/bin", "BASETEN_API_KEY": "b"}


def test_a_real_detached_worker_records_its_failure(tmp_path: Path) -> None:
    """The unknown provider fails inside a real process, without any model call."""
    board, run_id = queued(tmp_path)
    worker.spawn(run_id, tmp_path)
    deadline = time.monotonic() + 90
    entry = board.get(run_id)
    while entry is not None and entry.active and time.monotonic() < deadline:
        time.sleep(0.2)
        entry = board.get(run_id)
    assert entry is not None and entry.state == "failed" and entry.note == "KeyError"

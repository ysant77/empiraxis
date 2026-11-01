"""The run index: one run per request, one active run, and no dead worker shown as running."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from pydantic import ValidationError

from earthlab.board.store import UNCLAIMED_SECONDS, Board, RunBusy, RunSpec

SPEC = RunSpec(
    question="How much area?", topology="combined", provider="p", guard="g", reasoning="low"
)


def board(tmp_path: Path, **kwargs: object) -> Board:
    return Board(tmp_path / "board.sqlite", **kwargs)  # type: ignore[arg-type]


def test_the_same_request_key_never_starts_a_second_run(tmp_path: Path) -> None:
    runs = board(tmp_path)
    first, created = runs.submit(SPEC, "k")
    again, repeated = runs.submit(SPEC, "k")
    assert created and not repeated and first.run_id == again.run_id
    assert len(runs.recent()) == 1


def test_a_second_request_waits_for_the_active_run(tmp_path: Path) -> None:
    runs = board(tmp_path)
    first, _ = runs.submit(SPEC, "a")
    with pytest.raises(RunBusy) as busy:
        runs.submit(SPEC, "b")
    assert busy.value.run_id == first.run_id
    runs.end(first.run_id, "finished")
    assert runs.submit(SPEC, "b")[1]


def test_concurrent_submissions_from_two_sessions_create_one_run(tmp_path: Path) -> None:
    def attempt(key: str) -> bool:
        try:
            return board(tmp_path).submit(SPEC, key)[1]
        except RunBusy:
            return False

    with ThreadPoolExecutor(8) as pool:
        created = list(pool.map(attempt, [f"k{i % 2}" for i in range(16)]))
    assert sum(created) == 1 and len(board(tmp_path).recent()) == 1


def test_only_one_worker_can_claim_a_run(tmp_path: Path) -> None:
    runs = board(tmp_path)
    entry, _ = runs.submit(SPEC, "k")
    assert runs.claim(entry.run_id, 1) and not runs.claim(entry.run_id, 2)


def test_a_dead_worker_reads_as_interrupted_and_frees_the_slot(tmp_path: Path) -> None:
    runs = board(tmp_path, alive=lambda _pid: False)
    entry, _ = runs.submit(SPEC, "k")
    runs.claim(entry.run_id, 123)
    seen = runs.get(entry.run_id)
    assert seen is not None and seen.state == "interrupted" and not seen.active
    assert runs.active() is None
    assert runs.submit(SPEC, "next")[1]
    stored = runs.get(entry.run_id)
    assert stored is not None and stored.state == "interrupted" and stored.ended_at is not None


def test_a_request_no_worker_claimed_is_given_up(tmp_path: Path) -> None:
    now = [1000.0]
    runs = board(tmp_path, clock=lambda: now[0])
    entry, _ = runs.submit(SPEC, "k")
    now[0] += UNCLAIMED_SECONDS + 1
    assert runs.submit(SPEC, "next")[1]
    stored = runs.get(entry.run_id)
    assert stored is not None and stored.note == "no worker claimed it"


def test_an_ended_run_stays_ended(tmp_path: Path) -> None:
    runs = board(tmp_path)
    entry, _ = runs.submit(SPEC, "k")
    runs.end(entry.run_id, "failed", "KeyError")
    runs.end(entry.run_id, "finished")
    stored = runs.get(entry.run_id)
    assert stored is not None and stored.state == "failed" and stored.note == "KeyError"


def test_a_request_cannot_carry_a_field_it_does_not_declare(tmp_path: Path) -> None:
    fields = {**SPEC.model_dump(), "api_key": "x"}
    with pytest.raises(ValidationError):
        RunSpec.model_validate(fields)

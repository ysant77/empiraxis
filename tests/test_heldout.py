"""E1: the sealed held-out set. The repo holds only a lock with the file's SHA-256; a
held-out file without a matching lock is refused, and every bench run logs the hash."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from earthlab import cli
from earthlab.bench.heldout import (
    DEV_NOTE,
    HeldoutError,
    HeldoutLock,
    load_lock,
    scenario_file_record,
)
from earthlab.bench.scenarios import load_scenarios
from earthlab.digest import file_digest

ROOT = Path(__file__).resolve().parents[1]
DEV = ROOT / "evals" / "sciencebench_dev_v1.yaml"
SCENARIO: dict[str, object] = {
    "id": "HO-01",
    "priority": "P0",
    "title": "Hotspot trap",
    "status": "ready",
    "question": "Convert these FIRMS detections into burned hectares, please.",
    "expected": "abstain",
    "reason_codes": ["hotspot_count_is_not_burned_area"],
}
HELDOUT = {"version": 1, "scenarios": [SCENARIO]}
BLINDNESS = "Drafted by the system developer, then edited by the owner."


def heldout_file(tmp_path: Path) -> Path:
    path = tmp_path / "heldout.yaml"
    path.write_text(yaml.safe_dump(HELDOUT), encoding="utf-8")
    return path


def lock_for(path: Path, **change: object) -> HeldoutLock:
    fields = {
        "set_id": "heldout-v1",
        "sha256": file_digest(path),
        "questions": 1,
        "frozen_at": "2026-10-29",
        "blindness": BLINDNESS,
    }
    return HeldoutLock.model_validate({**fields, **change})


def test_heldout_file_without_a_lock_is_refused(tmp_path: Path) -> None:
    path = heldout_file(tmp_path)
    with pytest.raises(HeldoutError, match="need --heldout-lock"):
        scenario_file_record(path, load_scenarios(path), None)


def test_edited_heldout_file_fails_the_lock(tmp_path: Path) -> None:
    path = heldout_file(tmp_path)
    lock = lock_for(path)
    path.write_text(path.read_text(encoding="utf-8") + "# edited\n", encoding="utf-8")
    with pytest.raises(HeldoutError, match="does not match"):
        scenario_file_record(path, load_scenarios(path), lock)


def test_lock_question_count_and_dev_file_mismatch_are_refused(tmp_path: Path) -> None:
    path = heldout_file(tmp_path)
    with pytest.raises(HeldoutError, match="expected 2"):
        scenario_file_record(path, load_scenarios(path), lock_for(path, questions=2))
    with pytest.raises(HeldoutError, match="held-out scenarios"):
        scenario_file_record(DEV, load_scenarios(DEV), lock_for(DEV, questions=24))


def test_matching_lock_is_recorded_with_its_blindness_note(tmp_path: Path) -> None:
    path = heldout_file(tmp_path)
    record = scenario_file_record(path, load_scenarios(path), lock_for(path))
    assert record["sha256"] == file_digest(path) and record["heldout"]
    assert BLINDNESS in record["note"] and record["set_id"] == "heldout-v1"
    dev = scenario_file_record(DEV, load_scenarios(DEV), None)
    assert dev["note"] == DEV_NOTE and not dev["heldout"]


def test_bench_command_logs_the_scenario_hash(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = heldout_file(tmp_path)
    lock_path = tmp_path / "lock.yaml"
    lock_path.write_text(yaml.safe_dump(lock_for(path).model_dump(mode="json")), "utf-8")
    assert load_lock(lock_path) == lock_for(path)
    args = ["bench", "--scenarios", str(path), "--runs-dir", str(tmp_path / "runs")]
    with pytest.raises(HeldoutError):
        cli.main(args)
    assert cli.main([*args, "--heldout-lock", str(lock_path)]) == 0
    capsys.readouterr()
    rows = next((tmp_path / "runs" / "bench").rglob("results.jsonl")).read_text("utf-8")
    meta = json.loads(rows.splitlines()[0])["meta"]
    assert meta["scenario_file"]["sha256"] == file_digest(path)
    assert any(BLINDNESS in note for note in meta["notes"])


def test_committed_lock_is_valid_and_states_its_blindness() -> None:
    lock = load_lock(ROOT / "evals" / "heldout_v1.lock.yaml")
    assert lock.set_id == "heldout-v1" and lock.questions == 16
    assert "reviewed by the owner without changes" in lock.blindness


def write_set(tmp_path: Path, scenarios: list[dict[str, object]]) -> Path:
    path = tmp_path / "set.yaml"
    path.write_text(yaml.safe_dump({"version": 1, "scenarios": scenarios}), encoding="utf-8")
    return path


def test_locked_set_must_be_all_heldout_and_all_ready(tmp_path: Path) -> None:
    """A2: development questions cannot stand in for held-out ones; none is skipped."""
    base = SCENARIO
    dev = {**base, "id": "SB-01"}
    mixed = write_set(tmp_path, [base, dev])
    with pytest.raises(HeldoutError, match="only HO- scenarios"):
        scenario_file_record(mixed, load_scenarios(mixed), lock_for(mixed, questions=2))
    blocked = {**base, "id": "HO-02", "status": "blocked_unrun", "blocked_reason": "no data"}
    skipped = write_set(tmp_path, [base, blocked])
    with pytest.raises(HeldoutError, match="not ready: HO-02"):
        scenario_file_record(skipped, load_scenarios(skipped), lock_for(skipped, questions=2))


def test_duplicate_heldout_ids_are_refused(tmp_path: Path) -> None:
    base = SCENARIO
    path = write_set(tmp_path, [base, base])
    with pytest.raises(ValueError, match="unique"):
        load_scenarios(path)


def test_only_is_refused_with_a_heldout_lock(tmp_path: Path) -> None:
    """A1: a held-out run covers the whole set or does not run."""
    path = heldout_file(tmp_path)
    lock_path = tmp_path / "lock.yaml"
    lock_path.write_text(yaml.safe_dump(lock_for(path).model_dump(mode="json")), "utf-8")
    args = ["bench", "--scenarios", str(path), "--heldout-lock", str(lock_path)]
    with pytest.raises(HeldoutError, match="--only"):
        cli.main([*args, "--only", "HO-01", "--runs-dir", str(tmp_path / "runs")])
    assert not (tmp_path / "runs").exists()

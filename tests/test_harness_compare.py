"""The comparison report keeps unknown values unknown and failed runs visible."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from earthlab.harness.compare import (
    NOT_MEASURED,
    agrees_with_code,
    build,
    cell,
    load_runs,
    markdown,
)


def _run(folder: Path, name: str, record: dict[str, Any]) -> str:
    path = folder / name
    path.mkdir()
    (path / "result.json").write_text(json.dumps(record), encoding="utf-8")
    return str(path)


def _write(folder: Path) -> Path:
    usage = {"wall_seconds": 10.0, "model_calls": 3, "prompt_tokens": 100}
    good = {
        "state": "forwarded", "usage": usage, "acceptance": {"a": True}, "strategy": "statistical",
        "recommendation": {"outcome": "adopt", "model_id": "m"}, "code_outcome": "adopt",
    }  # fmt: skip
    rows = [
        {"request": "ignored"},
        {"scenario": "s", "arm": "team", "run": _run(folder, "a", good)},
        {"scenario": "s", "arm": "team", "run": None},
        {"scenario": "s", "arm": "fixed", "run": _run(folder, "b", {"state": "refused"})},
    ]
    path = folder / "manifest.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return path


def test_a_failed_run_stays_in_the_count_and_unknown_is_not_zero(tmp_path: Path) -> None:
    report = build(load_runs(_write(tmp_path)))
    team = report["scenarios"]["s"]["team"]
    assert team["runs"] == 2 and team["failed"] == 1 and team["acceptance_passed"] == 1
    assert team["energy"] == NOT_MEASURED and team["billed_usd"] == NOT_MEASURED
    fixed = report["scenarios"]["s"]["fixed"]
    assert fixed["wall_seconds"] == NOT_MEASURED and fixed["ended_in_refusal_or_abstention"] == 1


def test_usage_records_do_not_prove_a_bill_of_zero() -> None:
    usage = {"prompt_tokens": 10, "model_calls": 1}
    rows = [{"record": {"usage": usage}}, {"record": {"usage": usage}}]
    assert cell(rows)["billed_usd"] == NOT_MEASURED


def test_a_bill_needs_a_record_from_every_run() -> None:
    billed = {"record": {"usage": {"billed_usd": 0.25}}}
    assert cell([billed, billed])["billed_usd"] == 0.5
    assert cell([billed, {"record": {"usage": {}}}])["billed_usd"] == NOT_MEASURED


def test_the_three_dimensions_print_apart(tmp_path: Path) -> None:
    text = markdown(build(load_runs(_write(tmp_path))))
    for title in ("Scientific result", "Engineering cost", "Agent cost"):
        assert f"### {title}" in text


def test_a_recommendation_is_compared_with_the_code_rule() -> None:
    record = {"recommendation": {"outcome": "abstain"}, "code_outcome": "adopt"}
    assert agrees_with_code(record) is False
    assert agrees_with_code({"state": "refused"}) is None


def test_an_unranked_arm_keeps_its_label_from_the_manifest(tmp_path: Path) -> None:
    run = _run(tmp_path, "c", {"state": "forwarded"})
    rows = [
        {"scenario": "s", "arm": "single", "arm_id": "S-q4", "ranked": False, "run": run},
        {"scenario": "s", "arm": "single", "arm_id": "S-M", "ranked": True, "run": run},
    ]
    path = tmp_path / "m.jsonl"
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    table = build(load_runs(path))["scenarios"]["s"]
    assert table["S-q4"]["ranked"] == "no: Lead gate waived"
    assert table["S-M"]["ranked"] == "yes"

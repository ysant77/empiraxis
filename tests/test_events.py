"""EventV1 adapter, replay manifest, bench reader and redaction: fail closed on any doubt."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from earthlab.events.adapter import (
    ResultMismatchError,
    TraceMissingError,
    UnknownEventError,
    load_run,
)
from earthlab.events.bench import (
    DEV_LABEL,
    HeldoutContentError,
    bench_events,
    find_dev_benches,
    load_dev_bench,
)
from earthlab.events.contract import (
    IMPLEMENTED_ROLES,
    PLANNED_ROLES,
    EventV1,
    Visibility,
    is_model_agent,
)
from earthlab.events.manifest import ManifestError, listed_runs, verified_run, write_manifest
from earthlab.events.redact import text_is_safe, visible_events
from earthlab.trace import RunTrace, TraceIntegrityError

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "examples" / "replay"
SEPT, OCT = "sb05-september", "sb05b-october"


def copy_run(tmp_path: Path, name: str = SEPT, parent: str = "replay") -> Path:
    target = tmp_path / parent / name
    shutil.copytree(REPLAY / name, target)
    return target


def event(**overrides: Any) -> EventV1:
    base: dict[str, Any] = {
        "event_id": "r:0",
        "run_id": "r",
        "trace_id": "t",
        "timestamp_utc": "2026-10-29T00:00:00+00:00",
        "actor_role": "tool",
        "event_type": "tool_completed",
        "status": "executed",
        "message_summary": "burned_area_summary -> executed",
    }
    return EventV1.model_validate({**base, **overrides})


def test_fixture_runs_pass_the_manifest_and_map_to_events() -> None:
    assert [r["run"] for r in listed_runs(REPLAY)][:2] == [SEPT, OCT]
    run = load_run(verified_run(REPLAY, SEPT))
    assert run.closed and run.status == "verified" and not run.heldout
    assert run.trace_records == 13
    assert {e.actor_role for e in run.events} <= IMPLEMENTED_ROLES
    assert not {e.actor_role for e in run.events} & PLANNED_ROLES
    verdict = next(e for e in run.events if e.event_id.endswith(".v"))
    assert verdict.actor_role == "verifier" and verdict.status == "approved"
    assert "77426.0" in verdict.message_summary
    assert all(
        e.source_trace_ref and e.source_trace_ref.startswith("trace.jsonl#") for e in run.events
    )


def test_october_fixture_abstains_on_the_coverage_gate() -> None:
    run = load_run(verified_run(REPLAY, OCT))
    assert run.status == "abstained"
    assert not any(
        e.event_type == "claim_verified" and e.event_id.endswith(".v") for e in run.events
    )


def test_events_never_copy_model_text_or_reasoning(tmp_path: Path) -> None:
    run_dir = tmp_path / "raw"
    trace = RunTrace(run_dir / "trace.jsonl")
    secret = "Private chain of reasoning about the case"
    draft = "Raw draft text the model wrote"
    calls = [{"id": "c1", "name": "burned_area_summary", "arguments": "{}"}]
    trace.append("model_turn", "model", turn=1, content=draft, reasoning=secret, tool_calls=calls)
    trace.append("model_turn", "model", turn=2, content=draft, reasoning=secret, tool_calls=[])
    for e in load_run(run_dir).events:
        assert secret not in e.message_summary and draft not in e.message_summary


def test_a_tool_or_the_verifier_is_never_a_model_agent() -> None:
    assert is_model_agent("orchestrator")
    for role in ("tool", "verifier", "safety_gate", "system", "human_director"):
        assert not is_model_agent(role)
    run = load_run(verified_run(REPLAY, SEPT))
    agents = {e.actor_role for e in run.events if is_model_agent(e.actor_role)}
    assert agents == {"orchestrator"}
    tool_events = [e for e in run.events if e.event_type == "tool_completed"]
    assert tool_events and all(e.actor_role == "tool" for e in tool_events)


def test_tampered_trace_fails_closed(tmp_path: Path) -> None:
    run_dir = copy_run(tmp_path)
    path = run_dir / "trace.jsonl"
    lines = path.read_text().splitlines()
    index = next(i for i, line in enumerate(lines) if "77426" in line)
    lines[index] = lines[index].replace("77426", "77427")
    path.write_text("\n".join(lines) + "\n")
    with pytest.raises(TraceIntegrityError):
        load_run(run_dir)


def test_tampered_file_fails_the_replay_manifest(tmp_path: Path) -> None:
    root = tmp_path / "replay"
    shutil.copytree(REPLAY, root)
    result = root / SEPT / "result.json"
    result.write_text(result.read_text().replace("77426", "99999"))
    with pytest.raises(ManifestError, match="changed"):
        verified_run(root, SEPT)
    (root / OCT / "extra.txt").write_text("x")
    with pytest.raises(ManifestError, match="unlisted"):
        verified_run(root, OCT)


@pytest.mark.parametrize("name", ["../etc", "Sb05", "a/b", "nope"])
def test_manifest_rejects_unsafe_or_unlisted_names(name: str) -> None:
    with pytest.raises(ManifestError):
        verified_run(REPLAY, name)


def test_manifest_missing_or_broken_fails_closed(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="no MANIFEST"):
        listed_runs(tmp_path)
    (tmp_path / "MANIFEST.json").write_text("{not json")
    with pytest.raises(ManifestError, match="not valid JSON"):
        listed_runs(tmp_path)
    with pytest.raises(ManifestError, match="unsafe"):
        write_manifest(tmp_path, [{"run": "../x"}], note="n")


def test_manifest_detects_a_missing_run_folder_and_file(tmp_path: Path) -> None:
    root = tmp_path / "replay"
    shutil.copytree(REPLAY, root)
    (root / SEPT / "report.md").unlink()
    with pytest.raises(ManifestError, match="missing files"):
        verified_run(root, SEPT)
    shutil.rmtree(root / OCT)
    with pytest.raises(ManifestError, match="is missing"):
        verified_run(root, OCT)


def test_missing_or_empty_trace_fails_closed(tmp_path: Path) -> None:
    run_dir = copy_run(tmp_path)
    (run_dir / "trace.jsonl").unlink()
    with pytest.raises(TraceMissingError):
        load_run(run_dir)
    (run_dir / "trace.jsonl").write_text("")
    with pytest.raises(TraceMissingError, match="empty"):
        load_run(run_dir)


@pytest.mark.parametrize(
    ("event_name", "actor"),
    [("message", "product_manager"), ("tool_result", "geospatial_engineer"), ("chat", "runtime")],
)
def test_unknown_role_or_event_fails_closed(tmp_path: Path, event_name: str, actor: str) -> None:
    run_dir = copy_run(tmp_path)
    RunTrace(run_dir / "trace.jsonl").append(event_name, actor, summary="made up")
    with pytest.raises(UnknownEventError):
        load_run(run_dir)


def test_result_that_disagrees_with_the_trace_fails_closed(tmp_path: Path) -> None:
    run_dir = copy_run(tmp_path)
    result = run_dir / "result.json"
    result.write_text(result.read_text().replace('"status": "verified"', '"status": "error"'))
    with pytest.raises(ResultMismatchError, match="differs"):
        load_run(run_dir)
    result.write_text("{broken")
    with pytest.raises(ResultMismatchError, match="not valid JSON"):
        load_run(run_dir)


def test_open_run_without_finish_or_result(tmp_path: Path) -> None:
    run_dir = tmp_path / "open-run"
    trace = RunTrace(run_dir / "trace.jsonl")
    trace.append("source", "runtime", dataset_id="d", licence="l", sha256="0" * 64)
    trace.append("start", "runtime", question="q?", provider="p", model="m", budget={})
    trace.append("model_error", "runtime", kind="timeout")
    run = load_run(run_dir)
    assert not run.closed and run.status is None
    assert run.events[-1].event_type == "error" and run.events[-1].status == "failed"


def test_skipped_tool_rejected_tool_and_revision_events(tmp_path: Path) -> None:
    run_dir = tmp_path / "paths"
    trace = RunTrace(run_dir / "trace.jsonl")
    trace.append("model_turn", "model", turn=1, tool_calls=[{"name": "t"}], wall_seconds=0.5)
    trace.append("tool_skipped", "runtime", name="t", reason="budget")
    trace.append(
        "tool_result", "runtime", name="t", arguments="{bad", outcome="rejected", error="bad args"
    )
    trace.append("tool_result", "runtime", name="u", arguments=[1], outcome="failed", error=None)
    trace.append("answer_audit", "verifier", numbers=["7"], language="fr")
    trace.append("answer_revision", "verifier", issues=["a", "b"])
    trace.append("safety_check", "safety", stage="answer", allowed=False, blocked_by="llama_guard")
    trace.append("finish", "runtime", status="refused", reason="blocked", turns=1)
    events = load_run(run_dir).events
    assert events[0].elapsed_ms == 500 and events[1].status == "blocked"
    assert events[2].status == "rejected" and "unparsed" in events[2].message_summary
    assert events[3].status == "failed"
    assert events[4].status == "rejected" and "2 issue" in events[4].message_summary
    assert events[5].event_type == "revision_proposed"
    assert events[6].status == "blocked" and "llama_guard" in events[6].message_summary
    assert events[7].status == "failed"
    assert all(e.parent_event_id == events[0].event_id for e in events[1:4])


def test_sealed_set_run_is_internal_and_withholds_the_question(tmp_path: Path) -> None:
    run = load_run(copy_run(tmp_path, parent="runs/heldout"))
    assert run.heldout
    assert all(e.display_visibility is Visibility.INTERNAL for e in run.events)
    assert not any("Kalimantan 2015 study area" in e.message_summary for e in run.events)
    shown, withheld = visible_events(run.events, Visibility.PUBLIC_DEMO)
    assert shown == [] and withheld == len(run.events)
    assert load_run(REPLAY / SEPT, heldout=True).heldout


def test_redaction_by_audience_and_blocked_text() -> None:
    public = event()
    reviewer = event(event_id="r:1", display_visibility=Visibility.AUTHENTICATED_REVIEWER)
    internal = event(event_id="r:2", display_visibility=Visibility.INTERNAL)
    leaky = event(event_id="r:3", message_summary="used key sk-abcdefghijklmnop1234")
    events = [public, reviewer, internal, leaky]
    assert visible_events(events, Visibility.PUBLIC_DEMO) == ([public], 3)
    assert visible_events(events, Visibility.AUTHENTICATED_REVIEWER) == ([public, reviewer], 2)
    assert len(visible_events(events, Visibility.INTERNAL)[0]) == 4
    for text in ("api_key here", "Bearer abcdefghij", "token: x", "HO-07 question", "<think>"):
        assert not text_is_safe(text)
    assert text_is_safe("Round 1: A1.1 supported")


def test_event_contract_forbids_extra_fields() -> None:
    with pytest.raises(ValueError, match="extra"):
        event(reasoning="hidden")


def bench_summary(root: Path, heldout: bool = False, scenario: str = "SB-05") -> Path:
    root.mkdir(parents=True, exist_ok=True)
    arm = {"runs": 1, "passed": 1, "completion": 1.0, "per_scenario": {scenario: "1/1"}}
    meta = {
        "code_revision": "abc",
        "started_at_utc": "2026-10-28T00:00:00+00:00",
        "model": "m",
        "scenario_file": {"heldout": heldout},
    }
    data = {
        "meta": meta,
        "complete": True,
        "rows_expected": 1,
        "rows_written": 1,
        "arms": {"A": arm},
    }
    path = root / "summary.json"
    path.write_text(json.dumps(data))
    return path


def test_dev_bench_loads_with_its_label(tmp_path: Path) -> None:
    bench = load_dev_bench(bench_summary(tmp_path / "bench-dev"))
    assert bench.label == DEV_LABEL and bench.arms["A"]["passed"] == 1
    assert bench.complete and bench.code_revision == "abc"


def test_bench_refuses_sealed_set_content(tmp_path: Path) -> None:
    with pytest.raises(HeldoutContentError):
        load_dev_bench(bench_summary(tmp_path / "a", heldout=True))
    with pytest.raises(HeldoutContentError):
        load_dev_bench(bench_summary(tmp_path / "b", scenario="HO-01"))
    with pytest.raises(HeldoutContentError):
        load_dev_bench(bench_summary(tmp_path / "heldout" / "c"))


def test_find_dev_benches_skips_heldout_and_broken(tmp_path: Path) -> None:
    bench_summary(tmp_path / "dev1")
    bench_summary(tmp_path / "dev2", heldout=True)
    bench_summary(tmp_path / "heldout" / "x")
    (tmp_path / "broken").mkdir()
    (tmp_path / "broken" / "summary.json").write_text("{")
    found = find_dev_benches(tmp_path)
    assert [b.path.parent.name for b in found] == ["dev1"]
    assert find_dev_benches(tmp_path / "absent") == []


def test_bench_rows_become_events_and_sealed_rows_stay_internal(tmp_path: Path) -> None:
    rows = [
        {
            "scenario_id": "SB-05",
            "arm": "A",
            "repeat": 0,
            "passed": True,
            "outcome": {"seconds": 1.5},
        },
        {"scenario_id": "HO-03", "arm": "B", "repeat": 0, "passed": False, "outcome": {}},
    ]
    path = tmp_path / "bench" / "results.jsonl"
    path.parent.mkdir()
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n\n")
    first, second = bench_events(path)
    assert first.status == "completed" and first.elapsed_ms == 1500
    assert first.display_visibility is Visibility.PUBLIC_DEMO
    assert second.display_visibility is Visibility.INTERNAL
    assert "HO-03" not in second.message_summary


def test_written_manifest_round_trips(tmp_path: Path) -> None:
    copy_run(tmp_path, parent="new")
    write_manifest(tmp_path / "new", [{"run": SEPT, "split": "development"}], note="n")
    assert listed_runs(tmp_path / "new") == [{"run": SEPT, "split": "development"}]
    assert verified_run(tmp_path / "new", SEPT) == tmp_path / "new" / SEPT

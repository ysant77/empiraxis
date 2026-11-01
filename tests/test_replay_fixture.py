"""Redacted replay fixture: the copy verifies, no reasoning survives, provenance holds."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from earthlab.events.adapter import load_run
from earthlab.events.fixture import (
    LABEL,
    MODEL_TURN_DROPPED,
    WORKFLOW_LABEL,
    FixtureSourceError,
    copy_redacted,
    copy_redacted_workflow,
    sha256_file,
)
from earthlab.events.manifest import ManifestError, read_manifest, verified_run, write_manifest
from earthlab.trace import RunTrace, TraceIntegrityError

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "examples" / "replay"
SOURCE_BENCH = ROOT.parent / "axiom-earthlab" / "runs" / "bench"
SECRET = "Private reasoning that must never reach the replay"
DRAFT = "Raw model draft text"


def write_source_trace(path: Path) -> None:
    """A run trace that holds reasoning, raw text, a request ID and a non-public tool."""
    trace = RunTrace(path)
    calls = [
        {"id": "c1", "name": "burned_area_summary", "arguments": '{"month": "2015-09"}'},
        {"id": "c2", "name": "shell_exec", "arguments": '{"cmd": "cat secrets"}'},
    ]
    ts = "2026-10-29T02:31:10+00:00"
    trace.append("source", "runtime", timestamp=ts, dataset_id="d", licence="l", sha256="0" * 64)
    trace.append(
        "start",
        "runtime",
        question="Visible dev question?",
        provider="local-glimmer",
        model="muse-glimmer-30B",
        budget={},
    )
    trace.append(
        "model_turn",
        "model",
        turn=1,
        content=DRAFT,
        reasoning=SECRET,
        request_id="chatcmpl-x",
        tool_calls=calls,
        wall_seconds=1.0,
    )
    summary = {"summary": {"primary_area_ha": 1.0}}
    trace.append(
        "tool_result",
        "runtime",
        name="burned_area_summary",
        arguments='{"month": "2015-09"}',
        outcome="executed",
        error=None,
        data=summary,
    )
    trace.append(
        "tool_result",
        "runtime",
        name="shell_exec",
        arguments='{"cmd": "cat secrets"}',
        outcome="rejected",
        error="unknown tool",
        data={"out": "secret output"},
    )
    trace.append("finish", "runtime", status="verified", reason="final answer given", turns=1)


def make_bench(
    root: Path, *, passed: bool = True, heldout: bool = False, run: str = "SB-05-r0"
) -> Path:
    """A small development bench with one arm B run whose trace holds private fields."""
    bench = root / "bench-dev"
    source = bench / "runs" / run
    write_source_trace(source / "trace.jsonl")
    (source / "result.json").write_text(json.dumps({"status": "verified"}))
    scenario = run.rpartition("-r")[0]
    row = {"scenario_id": scenario, "arm": "B", "repeat": 0, "passed": passed}
    (bench / "results.jsonl").write_text(json.dumps(row) + "\n")
    meta = {"scenario_file": {"heldout": heldout}}
    (bench / "summary.json").write_text(json.dumps({"meta": meta}))
    return bench


def records(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_redacted_copy_verifies_and_keeps_the_source_times(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)
    out = tmp_path / "out"
    provenance = copy_redacted(bench, "SB-05-r0", out)
    source = bench / "runs" / "SB-05-r0" / "trace.jsonl"
    assert RunTrace(out / "trace.jsonl").verify() == RunTrace(source).verify() == 6
    assert [r["ts"] for r in records(out / "trace.jsonl")] == [r["ts"] for r in records(source)]
    assert load_run(out).status == "verified"
    assert provenance["source_trace_sha256"] == sha256_file(source)
    assert provenance["label"] == LABEL and provenance["source_run"] == "SB-05-r0"


def test_no_reasoning_content_or_private_tool_data_survives(tmp_path: Path) -> None:
    out = tmp_path / "out"
    provenance = copy_redacted(make_bench(tmp_path), "SB-05-r0", out)
    text = (out / "trace.jsonl").read_text()
    for private in (SECRET, DRAFT, "chatcmpl-x", "cat secrets", "secret output"):
        assert private not in text
    turn = next(r for r in records(out / "trace.jsonl") if r["event"] == "model_turn")
    assert not set(MODEL_TURN_DROPPED) & set(turn["data"])
    assert "Visible dev question?" in text  # development questions are kept
    tool = next(r for r in records(out / "trace.jsonl") if r["event"] == "tool_result")
    assert tool["data"]["arguments"] == '{"month": "2015-09"}'  # allow-listed tools are kept
    assert provenance["removed_fields"] == [
        "model_turn.content",
        "model_turn.reasoning",
        "model_turn.request_id",
        "model_turn.tool_calls.arguments (shell_exec)",
        "tool_result.arguments and data (shell_exec)",
    ]


@pytest.mark.parametrize(
    ("kwargs", "run", "match"),
    [
        ({"passed": False}, "SB-05-r0", "did not pass"),
        ({"heldout": True}, "SB-05-r0", "held-out"),
        ({}, "SB-05-r1", "no arm B bench row"),
    ],
)
def test_unusable_sources_are_refused(
    tmp_path: Path, kwargs: dict[str, Any], run: str, match: str
) -> None:
    bench = make_bench(tmp_path, **kwargs)
    with pytest.raises(FixtureSourceError, match=match):
        copy_redacted(bench, run, tmp_path / "out")


def test_heldout_source_path_is_refused(tmp_path: Path) -> None:
    bench = make_bench(tmp_path / "runs" / "heldout")
    with pytest.raises(FixtureSourceError, match="held-out"):
        copy_redacted(bench, "SB-05-r0", tmp_path / "out")


def test_broken_source_trace_is_refused(tmp_path: Path) -> None:
    bench = make_bench(tmp_path)
    trace = bench / "runs" / "SB-05-r0" / "trace.jsonl"
    trace.write_text(trace.read_text().replace("Visible dev", "Edited dev"))
    with pytest.raises(TraceIntegrityError):
        copy_redacted(bench, "SB-05-r0", tmp_path / "out")


def test_committed_fixture_holds_redacted_real_runs() -> None:
    manifest = read_manifest(REPLAY)
    assert LABEL in manifest["note"]
    for entry in manifest["runs"]:
        assert entry["label"] in (LABEL, WORKFLOW_LABEL) and entry["split"] == "development"
        assert len(entry["source_trace_sha256"]) == 64 and entry["redaction_version"] == "1"
        assert "model_turn.reasoning" in entry["removed_fields"]
        run_dir = verified_run(REPLAY, entry["run"])
        turns = [r for r in records(run_dir / "trace.jsonl") if r["event"] == "model_turn"]
        assert turns and all(not set(MODEL_TURN_DROPPED) & set(t["data"]) for t in turns)
        assert all(t["data"]["served_model"] == "muse-glimmer-30B" for t in turns)
        assert '"reasoning"' not in (run_dir / "trace.jsonl").read_text()


@pytest.mark.skipif(not SOURCE_BENCH.is_dir(), reason="source bench is only on the build machine")
def test_committed_fixture_matches_its_source_hashes() -> None:
    bench_runs = [r for r in read_manifest(REPLAY)["runs"] if "source_bench" in r]
    assert len(bench_runs) == 2
    for entry in bench_runs:
        source = SOURCE_BENCH / entry["source_bench"] / "runs" / entry["source_run"]
        assert sha256_file(source / "trace.jsonl") == entry["source_trace_sha256"]
        assert sha256_file(source / "result.json") == entry["source_result_sha256"]


def test_committed_live_workflow_runs_replay_as_recorded() -> None:
    workflow = [r for r in read_manifest(REPLAY)["runs"] if r["label"] == WORKFLOW_LABEL]
    assert {r["scenario_id"]: r["run"] for r in workflow} == {
        "WD-01": "live-september-verified",
        "WD-02": "live-october-abstained",
    }
    for entry in workflow:
        assert entry["source_commit"] and len(entry["source_result_sha256"]) == 64
        run_dir = verified_run(REPLAY, entry["run"])
        starts = [r for r in records(run_dir / "trace.jsonl") if r["event"] == "workflow_start"]
        assert set(starts[0]["data"]["client_kinds"].values()) == {"live_http"}


def test_tampered_fixture_fails_closed(tmp_path: Path) -> None:
    root = tmp_path / "replay"
    shutil.copytree(REPLAY, root)
    trace = root / "sb05-september" / "trace.jsonl"
    trace.write_text(trace.read_text().replace("77426", "77427", 1))
    with pytest.raises(ManifestError, match="changed"):
        verified_run(root, "sb05-september")
    entries = [{k: v for k, v in r.items() if k != "files"} for r in read_manifest(root)["runs"]]
    write_manifest(root, entries, note="rewritten by hand")  # an edited manifest is not enough
    with pytest.raises(TraceIntegrityError):
        load_run(verified_run(root, "sb05-september"))


def write_workflow_run(root: Path, status: str = "verified", kind: str = "live_http") -> Path:
    root.mkdir(parents=True)
    trace = RunTrace(root / "trace.jsonl")
    trace.append(
        "workflow_start", "runtime", client_kinds={"product_manager": kind}, topology="combined"
    )
    trace.append(
        "model_turn",
        "model",
        turn=1,
        content=DRAFT,
        reasoning=SECRET,
        request_id="x",
        tool_calls=[],
    )
    (root / "result.json").write_text(json.dumps({"status": status}), encoding="utf-8")
    return root


def test_a_live_workflow_run_is_copied_without_model_text(tmp_path: Path) -> None:
    source = write_workflow_run(tmp_path / "source")
    entry = copy_redacted_workflow(source, tmp_path / "copy", "WD-01", "verified", "abc")
    text = (tmp_path / "copy" / "trace.jsonl").read_text(encoding="utf-8")
    assert SECRET not in text and DRAFT not in text
    assert entry["source_commit"] == "abc" and entry["label"] == WORKFLOW_LABEL
    assert "model_turn.reasoning" in entry["removed_fields"]
    assert RunTrace(tmp_path / "copy" / "trace.jsonl").verify() == 2


@pytest.mark.parametrize(
    ("folder", "status", "kind", "reason"),
    [
        ("source", "abstained", "live_http", "not verified"),
        ("source", "verified", "scripted", "not a live run"),
        ("heldout-run", "verified", "live_http", "held-out"),
    ],
)
def test_a_wrong_workflow_source_is_refused(
    tmp_path: Path, folder: str, status: str, kind: str, reason: str
) -> None:
    source = write_workflow_run(tmp_path / folder, status, kind)
    with pytest.raises(FixtureSourceError, match=reason):
        copy_redacted_workflow(source, tmp_path / "copy", "WD-01", "verified", "abc")

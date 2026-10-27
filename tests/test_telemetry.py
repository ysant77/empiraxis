from __future__ import annotations

import json
from pathlib import Path

import pytest

from earthlab.metrics import EarthlabMetrics
from earthlab.trace import RunTrace, TraceIntegrityError


def test_metrics_exposition_uses_bounded_labels() -> None:
    metrics = EarthlabMetrics(tool_names={"rank_regions"})
    metrics.record_inference("local-glimmer", "muse-glimmer-30b", "ok", 3.2, (100, 20), 0.0)
    metrics.record_inference("local-glimmer", "muse-glimmer-30b", "timeout", 900.0)
    metrics.record_tool("rank_regions", "executed")
    metrics.record_tool("rm -rf /", "rejected")
    metrics.record_verification("value", "contradicted")
    metrics.record_qa("nea-pm25", {"duplicate_hour": 4})
    metrics.investigations.labels("verified").inc()
    text = metrics.exposition()
    assert 'earthlab_inference_requests_total{model="muse-glimmer-30b",outcome="ok"' in text
    assert 'direction="input",model="muse-glimmer-30b",provider="local-glimmer"} 100.0' in text
    assert 'earthlab_tools_total{outcome="rejected",tool="unknown"} 1.0' in text
    assert "rm -rf" not in text
    assert 'earthlab_verifications_total{check="value",outcome="contradicted"} 1.0' in text
    assert "earthlab_inference_duration_seconds_bucket" in text


def test_successful_http_with_failed_science_is_not_verified() -> None:
    metrics = EarthlabMetrics()
    metrics.record_inference("p", "m", "ok", 1.0)
    metrics.record_verification("value", "contradicted")
    text = metrics.exposition()
    assert 'outcome="supported"' not in text


def test_trace_chain_detects_edits(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    trace = RunTrace(path)
    trace.append("start", "runtime", question="q")
    trace.append("tool", "model", name="rank_regions")
    assert RunTrace(path).verify() == 2
    resumed = RunTrace(path)
    resumed.append("end", "runtime")
    assert resumed.verify() == 3

    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["data"]["name"] = "run_shell"
    lines[1] = json.dumps(record, sort_keys=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(TraceIntegrityError, match="does not match its digest"):
        RunTrace(path).verify()


def test_trace_detects_deletion_and_corruption(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    trace = RunTrace(path)
    for i in range(3):
        trace.append("e", "runtime", i=i)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join([lines[0], lines[2]]) + "\n", encoding="utf-8")
    with pytest.raises(TraceIntegrityError, match="entry 1 has sequence 2"):
        RunTrace(path).verify()
    path.write_text("{not json\n", encoding="utf-8")
    with pytest.raises(TraceIntegrityError, match="not valid JSON"):
        RunTrace(path).verify()


def test_trace_detects_reordered_sequence(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    RunTrace(path).append("e", "runtime")
    record = json.loads(path.read_text(encoding="utf-8"))
    record["seq"] = 5
    path.write_text(json.dumps(record) + "\n\n", encoding="utf-8")
    with pytest.raises(TraceIntegrityError, match="has sequence"):
        RunTrace(path).verify()


def test_trace_detects_a_relinked_entry(tmp_path: Path) -> None:
    path = tmp_path / "trace.jsonl"
    trace = RunTrace(path)
    trace.append("e", "runtime")
    trace.append("e", "runtime")
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["prev"] = "f" * 64
    lines[1] = json.dumps(record)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(TraceIntegrityError, match="does not link"):
        RunTrace(path).verify()

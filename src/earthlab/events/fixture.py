"""Build a redacted, re-chained replay copy of a recorded development run.

The source trace must verify. A bench run needs a passing bench row, and a workflow run
must end in the status the caller expects. The copy drops model
reasoning, raw model message text and provider request IDs. Tool arguments and data are
kept only for allow-listed tools. The research question is kept: development questions
are visible. Held-out sources are refused. Source timestamps are kept.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from earthlab.events.adapter import HELDOUT_MARK
from earthlab.trace import RunTrace

REDACTION_VERSION = "1"
LABEL = "development, visible questions; real Muse Glimmer run; redacted copy"
WORKFLOW_LABEL = "development, visible questions; real Muse Glimmer workflow run; redacted copy"
PUBLIC_TOOLS = frozenset(
    {
        "assess_case",
        "burned_area_summary",
        "submit_area_findings",
        "declare_limitation",
        "submit_findings",
    }
)
MODEL_TURN_DROPPED = ("reasoning", "content", "request_id")


class FixtureSourceError(RuntimeError):
    """The source run cannot be used for a public replay fixture."""


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _model_turn(data: dict[str, Any], removed: set[str]) -> dict[str, Any]:
    kept = {k: v for k, v in data.items() if k not in MODEL_TURN_DROPPED}
    removed.update(f"model_turn.{k}" for k in MODEL_TURN_DROPPED if k in data)
    calls = []
    for call in data.get("tool_calls", []):
        if call.get("name") in PUBLIC_TOOLS:
            calls.append(call)
        else:
            calls.append({"id": call.get("id"), "name": call.get("name")})
            removed.add(f"model_turn.tool_calls.arguments ({call.get('name')})")
    kept["tool_calls"] = calls
    return kept


def _tool_result(data: dict[str, Any], removed: set[str]) -> dict[str, Any]:
    if data.get("name") in PUBLIC_TOOLS:
        return data
    removed.add(f"tool_result.arguments and data ({data.get('name')})")
    return {k: v for k, v in data.items() if k not in ("arguments", "data")}


def redact_record(event: str, data: dict[str, Any], removed: set[str]) -> dict[str, Any]:
    """The public form of one trace record's data. Adds each removed field to ``removed``."""
    if event == "model_turn":
        return _model_turn(data, removed)
    if event in ("tool_result", "tool_skipped"):
        return _tool_result(data, removed)
    return data


def _check_source(bench_dir: Path, run_name: str) -> dict[str, Any]:
    """Return the passing arm B bench row for the run; refuse held-out or failed sources."""
    if any(HELDOUT_MARK in part.lower() for part in bench_dir.resolve().parts):
        raise FixtureSourceError("held-out sources are never copied")
    summary = json.loads((bench_dir / "summary.json").read_text(encoding="utf-8"))
    if (summary.get("meta", {}).get("scenario_file") or {}).get("heldout"):
        raise FixtureSourceError("the bench summary marks a held-out set")
    scenario, _, repeat = run_name.rpartition("-r")
    for line in (bench_dir / "results.jsonl").read_text(encoding="utf-8").splitlines():
        row = json.loads(line)
        same = row["scenario_id"] == scenario and str(row["repeat"]) == repeat
        if same and row["arm"] == "B":
            if not row["passed"]:
                raise FixtureSourceError(f"{run_name} did not pass on the bench")
            return dict(row)
    raise FixtureSourceError(f"no arm B bench row for {run_name}")


def _copy(source: Path, out_dir: Path) -> set[str]:
    """Write the redacted trace and the result; return the removed fields."""
    source_trace = source / "trace.jsonl"
    records = RunTrace(source_trace).verify()
    shutil.rmtree(out_dir, ignore_errors=True)
    out_dir.mkdir(parents=True)
    copy = RunTrace(out_dir / "trace.jsonl")
    removed: set[str] = set()
    for entry in RunTrace(source_trace).records():
        data = redact_record(entry["event"], entry["data"], removed)
        copy.append(entry["event"], entry["actor"], timestamp=entry["ts"], **data)
    if copy.verify() != records:
        raise FixtureSourceError("the redacted copy has a different record count")
    shutil.copyfile(source / "result.json", out_dir / "result.json")
    return removed


def copy_redacted_workflow(
    source: Path, out_dir: Path, scenario_id: str, status: str, source_commit: str
) -> dict[str, Any]:
    """Redact one live workflow run that ended as expected; return its manifest provenance."""
    if any(HELDOUT_MARK in part.lower() for part in source.resolve().parts):
        raise FixtureSourceError("held-out sources are never copied")
    result = json.loads((source / "result.json").read_text(encoding="utf-8"))
    if result["status"] != status:
        raise FixtureSourceError(f"{source.name} is not {status}: {result['status']}")
    kinds = _client_kinds(source)
    if kinds != {"live_http"}:
        raise FixtureSourceError(f"{source.name} is not a live run: {sorted(kinds)}")
    removed = _copy(source, out_dir)
    return {
        "scenario_id": scenario_id,
        "split": "development",
        "label": WORKFLOW_LABEL,
        "source_run": source.name,
        "source_commit": source_commit,
        "source_trace_sha256": sha256_file(source / "trace.jsonl"),
        "source_result_sha256": sha256_file(source / "result.json"),
        "removed_fields": sorted(removed),
        "redaction_version": REDACTION_VERSION,
    }


def _client_kinds(source: Path) -> set[str]:
    for entry in RunTrace(source / "trace.jsonl").records():
        if entry["event"] == "workflow_start":
            return set((entry["data"].get("client_kinds") or {}).values())
    return set()


def copy_redacted(bench_dir: Path, run_name: str, out_dir: Path) -> dict[str, Any]:
    """Write trace.jsonl and result.json for one run; return its manifest provenance."""
    row = _check_source(bench_dir, run_name)
    source = bench_dir / "runs" / run_name
    source_trace = source / "trace.jsonl"
    removed = _copy(source, out_dir)
    return {
        "scenario_id": row["scenario_id"],
        "split": "development",
        "label": LABEL,
        "source_bench": bench_dir.name,
        "source_run": run_name,
        "source_trace_sha256": sha256_file(source_trace),
        "source_result_sha256": sha256_file(source / "result.json"),
        "removed_fields": sorted(removed),
        "redaction_version": REDACTION_VERSION,
    }

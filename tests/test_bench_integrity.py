"""E2 corrections: a failed row keeps its real duration, metrics come only from an unbroken
trace, and a held-out run records and requires a clean revision and the server settings."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import httpx
import pytest
from fake_client import FAKE_CONFIG, ScriptedClient

from earthlab.bench.heldout import HeldoutError
from earthlab.bench.metrics import trace_counts
from earthlab.bench.runner import check_official, run_bench
from earthlab.bench.runtime_info import guard_record, planner_record, server_settings
from earthlab.bench.scenarios import load_scenarios
from earthlab.llm.providers import ProviderConfig
from earthlab.runtime import Workspace, open_workspace
from earthlab.safety.llama_guard import LlamaGuard
from earthlab.trace import RunTrace, TraceIntegrityError

ROOT = Path(__file__).resolve().parents[1]
BY_ID = {s.id: s for s in load_scenarios(ROOT / "evals" / "sciencebench_dev_v1.yaml")}
PAUSE = 0.05
GUARD_CONFIG = ProviderConfig(
    name="fake-guard",
    kind="local",
    api="ollama_raw",
    base_url="http://127.0.0.1:9",
    model="earthlab-guard",
    logical_model="llama-guard-3-8b",
    usd_per_mtok_input=0.0,
    usd_per_mtok_output=0.0,
)
PROPS = {
    "model_path": "glimmer.gguf",
    "model_alias": "muse-glimmer-30B",
    "build_info": "b1-abc",
    "default_generation_settings": {
        "n_ctx": 32768,
        "params": {"temperature": 1.0, "top_p": 0.95, "top_k": 64, "min_p": 0.05, "seed": 1},
    },
}


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(ROOT / "data" / "nea")


class _SlowBoom(ScriptedClient):
    """A client that works for a short time, then fails in an unexpected way."""

    def chat(self, *args: Any, **kwargs: Any) -> Any:
        time.sleep(PAUSE)
        raise RuntimeError("unexpected failure")


def test_a_failed_row_records_its_real_duration(workspace: Workspace, tmp_path: Path) -> None:
    summary = run_bench(
        [BY_ID["SB-06"]], ["B"], workspace, tmp_path, repo=ROOT, client=_SlowBoom([])
    )
    row = json.loads((tmp_path / "results.jsonl").read_text().splitlines()[0])
    assert row["outcome"]["status"] == "error" and row["outcome"]["seconds"] >= PAUSE
    assert summary["arms"]["B"]["median_seconds"] >= round(PAUSE, 1)


def _trace(tmp_path: Path) -> Path:
    trace = RunTrace(tmp_path / "trace.jsonl")
    trace.append("model_turn", "runtime", tokens=10)
    trace.append("tool_result", "runtime", outcome="executed")
    trace.append("model_turn", "runtime", tokens=12)
    return tmp_path / "trace.jsonl"


def test_metrics_read_an_intact_trace(tmp_path: Path) -> None:
    _trace(tmp_path)
    assert trace_counts(tmp_path)["model_calls"] == 2


@pytest.mark.parametrize("attack", ["edit", "drop", "swap"])
def test_a_tampered_trace_is_refused(tmp_path: Path, attack: str) -> None:
    """T10: an edited, dropped or reordered trace line stops the metric count."""
    path = _trace(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    if attack == "edit":
        lines[1] = lines[1].replace('"executed"', '"rejected"')
    elif attack == "drop":
        del lines[1]
    else:
        lines[0], lines[1] = lines[1], lines[0]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    with pytest.raises(TraceIntegrityError):
        trace_counts(tmp_path)


def _meta(revision: str, planner_server: dict[str, Any]) -> dict[str, Any]:
    planner = {"provider": "local-glimmer", "server": planner_server}
    return {"code_revision": revision, "planner": planner, "guard": {"enabled": False}}


def test_an_official_run_needs_a_clean_revision_and_server_settings() -> None:
    check_official(_meta("abc123", {"server": "llama.cpp"}))
    for revision in ("abc123-dirty", "unknown"):
        with pytest.raises(HeldoutError, match="clean git revision"):
            check_official(_meta(revision, {"server": "llama.cpp"}))
    with pytest.raises(HeldoutError, match="local-glimmer"):
        check_official(_meta("abc123", {"error": "ConnectError: refused"}))


def _transport(routes: dict[str, Any]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        body = routes.get(request.url.path)
        return httpx.Response(200, json=body) if body else httpx.Response(404)

    return httpx.MockTransport(handle)


def test_planner_record_holds_request_and_server_sampling() -> None:
    record = planner_record(FAKE_CONFIG, 4096, _transport({"/props": PROPS}))
    assert record["request"] == {"temperature": 1.0, "max_tokens": 4096, "extra_body": {}}
    server = record["server"]
    assert server["model_path"] == "glimmer.gguf" and server["n_ctx"] == 32768
    assert server["sampling_defaults"]["top_k"] == 64


def test_guard_record_holds_the_model_digest() -> None:
    tags = {"models": [{"name": "earthlab-guard:latest", "digest": "ddc07af1"}]}
    guard = LlamaGuard(_Completer(GUARD_CONFIG), "llama-guard-3-8b")
    record = guard_record(guard, _transport({"/api/tags": tags}))
    assert record["server"] == {"server": "ollama", "model_digest": "ddc07af1"}
    assert record["request"] == {"temperature": 0} and record["model"] == "earthlab-guard"


def test_probe_failures_are_recorded_not_guessed() -> None:
    assert "error" in server_settings(FAKE_CONFIG, _transport({}))
    hosted = FAKE_CONFIG.model_copy(update={"kind": "hosted"})
    assert server_settings(hosted)["server"] == "hosted"


class _Completer:
    def __init__(self, config: ProviderConfig):
        self.config = config

    def complete(self, prompt: str, max_tokens: int) -> str:
        return "safe"

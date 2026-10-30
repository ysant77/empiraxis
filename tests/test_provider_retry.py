"""One bounded retry of a transient provider failure, opt-in, recorded attempt by attempt."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import FAKE_CONFIG, ScriptedClient, call, say

from earthlab.agent.budget import Budget
from earthlab.agent.loop import RunStatus
from earthlab.bench.metrics import trace_counts
from earthlab.events.adapter import load_run
from earthlab.llm.providers import ProviderConfig
from earthlab.llm.retry import RetryPolicy
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.runtime import RunOptions, Workspace, investigate, open_workspace
from earthlab.trace import RunTrace

RETRY = RunOptions(provider_retry=RetryPolicy(delay_seconds=0.0, max_delay_seconds=0.0))
CLAIM = {
    "kind": "peak_region",
    "region": "west",
    "start": "2015-09-01T00:00",
    "end": "2015-11-01T00:00",
    "statement": "West peaked.",
}
HOSTED = ProviderConfig(
    name="fake-hosted",
    kind="hosted",
    base_url="https://example.invalid/v1",
    model="muse-spark-open",
    logical_model="muse-spark-open",
    usd_per_mtok_input=1.0,
    usd_per_mtok_output=1.0,
)


def server_error() -> ProviderError:
    return ProviderError(ProviderErrorKind.SERVER, "HTTP 500")


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def records(run_dir: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in (run_dir / "trace.jsonl").read_text().splitlines()]


def test_one_server_error_is_retried_once_and_the_run_verifies(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [server_error(), call("submit_findings", claims=[CLAIM]), say("West had the peak.")]
    )
    result = investigate("Which region peaked?", client, workspace, tmp_path, options=RETRY)
    assert result.status is RunStatus.VERIFIED
    assert len(client.requests) == 3
    errors = [r["data"] for r in records(tmp_path) if r["event"] == "model_error"]
    assert errors == [
        {
            "kind": "server",
            "attempt": 1,
            "max_attempts": 2,
            "retrying": True,
            "elapsed_ms": errors[0]["elapsed_ms"],
            "charged_usd": 0.0,
        }
    ]
    start = next(r for r in records(tmp_path) if r["event"] == "start")
    assert start["data"]["retry_policy"]["max_attempts"] == 2
    assert RunTrace(tmp_path / "trace.jsonl").verify() > 0
    assert trace_counts(tmp_path)["provider_errors"] == 1
    summaries = [e.message_summary for e in load_run(tmp_path).events if e.event_type == "error"]
    assert summaries == ["Model call failed: server (attempt 1 of 2; retrying)."]


def test_two_server_errors_end_in_provider_error(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([server_error(), server_error(), say("never reached")])
    result = investigate("q", client, workspace, tmp_path, options=RETRY)
    assert result.status is RunStatus.PROVIDER_ERROR and "server" in result.stop_reason
    assert len(client.requests) == 2
    attempts = [r["data"] for r in records(tmp_path) if r["event"] == "model_error"]
    assert [(a["attempt"], a["retrying"]) for a in attempts] == [(1, True), (2, False)]


@pytest.mark.parametrize(
    "kind", [ProviderErrorKind.AUTH, ProviderErrorKind.BAD_REQUEST, ProviderErrorKind.MALFORMED]
)
def test_permanent_errors_are_never_retried(
    workspace: Workspace, tmp_path: Path, kind: ProviderErrorKind
) -> None:
    client = ScriptedClient([ProviderError(kind, "no"), say("never reached")])
    result = investigate("q", client, workspace, tmp_path, options=RETRY)
    assert result.status is RunStatus.PROVIDER_ERROR
    assert len(client.requests) == 1


def test_retry_is_off_by_default(workspace: Workspace, tmp_path: Path) -> None:
    """The frozen v1 protocol makes one attempt per model call."""
    client = ScriptedClient([server_error(), say("never reached")])
    result = investigate("q", client, workspace, tmp_path)
    assert result.status is RunStatus.PROVIDER_ERROR
    assert len(client.requests) == 1
    start = next(r for r in records(tmp_path) if r["event"] == "start")
    assert start["data"]["retry_policy"]["max_attempts"] == 1


def test_no_retry_when_the_turn_budget_is_spent(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([server_error(), say("never reached")])
    result = investigate(
        "q", client, workspace, tmp_path, budget=Budget(max_turns=1), options=RETRY
    )
    assert result.status is RunStatus.PROVIDER_ERROR
    assert len(client.requests) == 1
    skipped = [r["data"] for r in records(tmp_path) if r["event"] == "model_retry_skipped"]
    assert skipped and "turn limit" in skipped[0]["reason"]


def test_no_retry_when_the_delay_would_outlast_the_time_left(
    workspace: Workspace, tmp_path: Path
) -> None:
    slow = RunOptions(provider_retry=RetryPolicy(delay_seconds=50.0, max_delay_seconds=50.0))
    client = ScriptedClient([server_error(), say("never reached")])
    budget = Budget(max_seconds=30.0)
    result = investigate("q", client, workspace, tmp_path, budget=budget, options=slow)
    assert result.status is RunStatus.PROVIDER_ERROR
    assert len(client.requests) == 1


def test_a_retry_never_replays_tools(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            call("submit_findings", claims=[CLAIM]),
            server_error(),
            say("West had the peak."),
        ]
    )
    result = investigate("Which region peaked?", client, workspace, tmp_path, options=RETRY)
    assert result.status is RunStatus.VERIFIED
    assert result.submissions == 1
    runs = [r for r in records(tmp_path) if r["event"] == "tool_result"]
    assert [r["data"]["name"] for r in runs] == ["submit_findings"]


def test_a_failed_hosted_call_is_charged_its_worst_case(
    workspace: Workspace, tmp_path: Path
) -> None:
    """A hosted 500 is never treated as free: the reservation stays charged."""
    client = ScriptedClient([server_error()], config=HOSTED)
    result = investigate("q", client, workspace, tmp_path, budget=Budget(max_usd=5.0))
    assert result.status is RunStatus.PROVIDER_ERROR
    assert result.cost_usd is not None and result.cost_usd > 0
    error = next(r["data"] for r in records(tmp_path) if r["event"] == "model_error")
    assert error["charged_usd"] == pytest.approx(result.cost_usd)


def test_retry_after_is_capped(workspace: Workspace) -> None:
    policy = RetryPolicy(delay_seconds=1.0, max_delay_seconds=5.0)
    limited = ProviderError(ProviderErrorKind.RATE_LIMIT, "429", retry_after=600.0)
    assert policy.delay(limited) == 5.0
    assert policy.delay(server_error()) == 1.0
    assert FAKE_CONFIG.kind == "local"


def test_cli_enables_retry_only_on_request() -> None:
    from earthlab.cli import _run_options, build_parser

    parser = build_parser()
    base = ["investigate", "q"]
    assert _run_options(parser.parse_args(base)).provider_retry is None
    on = _run_options(parser.parse_args([*base, "--provider-retry"]))
    assert on.provider_retry == RetryPolicy()

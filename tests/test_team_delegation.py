"""One bounded delegation with scripted models: code decides, the models only propose."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import ScriptedClient, call, say

from earthlab.agent.budget import Budget
from earthlab.board.progress import fold
from earthlab.events.adapter import load_run
from earthlab.implement.bindings import BindingRefused, load_bindings
from earthlab.llm.providers import load_providers
from earthlab.llm.types import ProviderError, ProviderErrorKind
from earthlab.runtime import Workspace, open_workspace
from earthlab.science.burned_area import QaPolicy
from earthlab.team.acceptance import check_table, qa_row
from earthlab.team.contracts import CheckProposal, QaRowV1
from earthlab.team.delegate import (
    PROPOSE_CHECK,
    QA_TOOL,
    REVIEW,
    SUBMIT_TABLE,
    parent_case,
    replay_delegation,
    run_delegation,
)
from earthlab.trace import RunTrace
from earthlab.workflow.assign import BINDINGS_FILE

REPO = Path(__file__).resolve().parents[1]
PARENT = REPO / "examples" / "replay" / "live-september-verified"
CASE = "kalimantan-2015-burned-area"
POLICIES = [p.value for p in QaPolicy]


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def truth(workspace: Workspace, month: str) -> list[dict[str, Any]]:
    assert workspace.cases is not None
    case = workspace.cases.get(CASE)
    rows = [qa_row(case, workspace.cases.root, month, p)[0] for p in POLICIES]
    return [r.model_dump(mode="json") for r in rows]


def propose(months: list[str]) -> Any:
    return call(PROPOSE_CHECK, months=months, reason="Check the gate under each QA policy.")


def script(workspace: Workspace, rows: list[dict[str, Any]], accept: bool = True) -> ScriptedClient:
    tools = [call(QA_TOOL, month="2015-09", qa_policy=p) for p in POLICIES]
    return ScriptedClient(
        [
            propose(["2015-09"]),
            *tools,
            call(SUBMIT_TABLE, rows=rows),
            call(REVIEW, accept=accept, note="The table is complete."),
        ]
    )


def delegate(
    client: ScriptedClient, workspace: Workspace, tmp_path: Path, **kwargs: Any
) -> tuple[Any, Path]:
    run_dir = tmp_path / "delegation"
    run_dir.mkdir()
    return run_delegation(PARENT, client, client, workspace, run_dir, **kwargs), run_dir


def test_a_correct_table_is_verified_and_recorded(workspace: Workspace, tmp_path: Path) -> None:
    done, run_dir = delegate(script(workspace, truth(workspace, "2015-09")), workspace, tmp_path)
    assert done.status == "verified" and done.result.acceptance.passed
    view = fold(run_dir.name, RunTrace(run_dir / "trace.jsonl").records())
    lead, specialist = view.tasks.values()
    assert lead.owner == "geospatial_engineer" and lead.status == "verified"
    assert specialist.owner == "data_specialist" and specialist.status == "verified"
    assert specialist.parent_task_id == lead.task_id and specialist.output_sha256
    assert load_run(run_dir).status == "verified"


def test_the_ticket_fixes_everything_before_work_starts(
    workspace: Workspace, tmp_path: Path
) -> None:
    done, _ = delegate(script(workspace, truth(workspace, "2015-09")), workspace, tmp_path)
    ticket = done.ticket
    assert ticket.owner == "data_specialist" and ticket.allowed_paths == ()
    assert ticket.allowed_tools == (QA_TOOL, SUBMIT_TABLE)
    assert ticket.input_sha256 == parent_case(PARENT)[1]
    assert ticket.human_approval_required is False and ticket.acceptance_checks
    assert ticket.deadline_utc and ticket.max_model_calls == len(POLICIES) + 2


def test_a_changed_value_fails_even_when_the_lead_accepts(
    workspace: Workspace, tmp_path: Path
) -> None:
    rows = truth(workspace, "2015-09")
    rows[0]["area_ha"] += 500
    done, run_dir = delegate(script(workspace, rows), workspace, tmp_path)
    assert done.status == "needs_revision" and not done.result.acceptance.passed
    entries = list(RunTrace(run_dir / "trace.jsonl").records())
    review = next(e for e in entries if e["event"] == "lead_reviewed")
    assert review["data"]["overridden"] is True
    assert fold(run_dir.name, entries).tasks[done.ticket.task_id].status == "needs_revision"


def test_a_missing_row_fails(workspace: Workspace, tmp_path: Path) -> None:
    done, _ = delegate(script(workspace, truth(workspace, "2015-09")[1:]), workspace, tmp_path)
    assert done.status == "needs_revision"


def test_the_lead_can_send_back_a_passed_table(workspace: Workspace, tmp_path: Path) -> None:
    client = script(workspace, truth(workspace, "2015-09"), accept=False)
    done, _ = delegate(client, workspace, tmp_path)
    assert done.status == "needs_revision" and done.result.acceptance.passed


def test_a_month_off_the_ticket_is_rejected_and_recorded(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient(
        [
            propose(["2015-09"]),
            call(QA_TOOL, month="2015-10", qa_policy="primary"),
            say("I stop here."),
            call(REVIEW, accept=False, note="No table was submitted."),
        ]
    )
    done, run_dir = delegate(client, workspace, tmp_path)
    records = list(RunTrace(run_dir / "trace.jsonl").records())
    tool = next(e for e in records if e["event"] == "tool_result")
    assert tool["data"]["outcome"] == "rejected"
    assert done.status == "needs_revision"


def test_a_tool_outside_the_ticket_is_rejected(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient(
        [
            propose(["2015-09"]),
            call("download_file", url="https://example.com/x"),
            say("I stop here."),
            call(REVIEW, accept=False, note="No table was submitted."),
        ]
    )
    _, run_dir = delegate(client, workspace, tmp_path)
    records = list(RunTrace(run_dir / "trace.jsonl").records())
    tool = next(e for e in records if e["event"] == "tool_result")
    assert tool["data"]["outcome"] == "rejected"
    assert "not on the ticket" in tool["data"]["error"]


def test_a_month_that_is_not_pinned_ends_the_delegation(
    workspace: Workspace, tmp_path: Path
) -> None:
    done, _ = delegate(ScriptedClient([propose(["2019-09"])]), workspace, tmp_path)
    assert done.status == "failed" and done.ticket is None


def test_a_proposal_cannot_add_a_permission() -> None:
    with pytest.raises(ValueError, match="approved"):
        CheckProposal.model_validate({"months": ["2015-09"], "reason": "because", "approved": True})


def test_the_budget_stops_the_specialist(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([propose(["2015-09"])])
    done, _ = delegate(client, workspace, tmp_path, budget=Budget(max_turns=1))
    assert done.status == "budget_exhausted"


def test_a_provider_failure_is_recorded(workspace: Workspace, tmp_path: Path) -> None:
    client = ScriptedClient([ProviderError(ProviderErrorKind.TRANSPORT, "connection refused")])
    done, run_dir = delegate(client, workspace, tmp_path)
    assert done.status == "failed"
    assert fold(run_dir.name, RunTrace(run_dir / "trace.jsonl").records()).closed


def test_replay_recomputes_the_saved_table(workspace: Workspace, tmp_path: Path) -> None:
    _, run_dir = delegate(script(workspace, truth(workspace, "2015-09")), workspace, tmp_path)
    report = replay_delegation(run_dir, workspace)
    assert report["acceptance_same"] and report["rows_hash_same"] and report["status"] == "verified"


def test_replay_notices_a_changed_saved_table(workspace: Workspace, tmp_path: Path) -> None:
    _, run_dir = delegate(script(workspace, truth(workspace, "2015-09")), workspace, tmp_path)
    path = run_dir / "result.json"
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["result"]["rows"][0]["area_ha"] += 1
    path.write_text(json.dumps(saved), encoding="utf-8")
    report = replay_delegation(run_dir, workspace)
    assert not report["rows_hash_same"] and not report["acceptance_same"]


def test_a_parent_with_a_broken_trace_is_refused(workspace: Workspace, tmp_path: Path) -> None:
    broken = tmp_path / "parent"
    broken.mkdir()
    lines = (PARENT / "trace.jsonl").read_text(encoding="utf-8").replace("2015-09", "2015-08", 1)
    (broken / "trace.jsonl").write_text(lines, encoding="utf-8")
    run_dir = tmp_path / "out"
    run_dir.mkdir()
    client = ScriptedClient([])
    with pytest.raises(RuntimeError):
        run_delegation(broken, client, client, workspace, run_dir)


def test_only_a_bound_candidate_serves_the_specialist_role() -> None:
    providers = load_providers(REPO / "config" / "providers.yaml")
    bindings = load_bindings(REPO / BINDINGS_FILE)
    glimmer = providers["local-glimmer"]
    assert bindings.bind_runtime(
        "data_specialist", "muse-glimmer", glimmer, providers, allow_experimental=True
    )
    with pytest.raises((BindingRefused, PermissionError)):
        bindings.bind_runtime(
            "data_specialist", "qwen3-4b-2507", glimmer, providers, allow_experimental=True
        )


def test_check_table_reports_each_rule() -> None:
    row = QaRowV1(month="2015-10", qa_policy="primary", valid_fraction=0.45, gate_passed=False)
    wrong = row.model_copy(update={"area_ha": 10.0})
    result = check_table("t", (wrong,), {("2015-10", "primary"): row})
    assert not result.passed and [c.passed for c in result.checks] == [True, False, False]


def test_a_ticket_has_room_for_one_read_per_turn(workspace: Workspace, tmp_path: Path) -> None:
    """A live run read one pair per turn and ran out of turns before it could submit."""
    months = ["2015-09", "2015-10"]
    reads = [call(QA_TOOL, month=m, qa_policy=p) for m in months for p in POLICIES]
    rows = [*truth(workspace, "2015-09"), *truth(workspace, "2015-10")]
    client = ScriptedClient(
        [
            propose(months),
            *reads,
            call(SUBMIT_TABLE, rows=rows),
            call(REVIEW, accept=True, note="The table is complete."),
        ]
    )
    done, _ = delegate(client, workspace, tmp_path)
    assert done.status == "verified" and done.ticket.max_model_calls == len(reads) + 2


def test_a_ticket_that_cannot_fit_the_budget_is_not_issued(
    workspace: Workspace, tmp_path: Path
) -> None:
    client = ScriptedClient([propose(["2015-09", "2015-10"])])
    done, run_dir = delegate(client, workspace, tmp_path, budget=Budget(max_turns=4))
    assert done.status == "budget_exhausted" and done.ticket is None
    assert "task_handoff" not in (run_dir / "trace.jsonl").read_text(encoding="utf-8")

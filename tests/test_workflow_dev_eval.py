"""The WD v1 development suite: loading, arm availability, scripted runs and scoring.

Every run here is scripted, so every score is a harness check, not a model result.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from conftest import REPO_DATA
from fake_client import FAKE_CONFIG, ScriptedClient, call, say
from test_workflow import CASE, brief, engineer_steps, plan
from workflow_helpers import bindings

from earthlab.evals.workflow_dev import Arm, RunFacts, load_suite, score, summarize
from earthlab.evals.workflow_dev_run import arm_blockers, assignment_for, run_scenario
from earthlab.implement.bindings import load_bindings
from earthlab.llm.providers import load_providers
from earthlab.runtime import Workspace, open_workspace

ROOT = Path(__file__).resolve().parents[1]
SUITE, DIGEST = load_suite(ROOT / "evals" / "workflow_dev_v1.yaml")
BY_ID = {s.id: s for s in SUITE.scenarios}
ARMS = {
    "single": Arm(id="single-test", kind="single", engineer="fake-glimmer"),
    "combined": Arm(
        id="combined-test", kind="combined", pm="fake-glimmer", engineer="fake-glimmer"
    ),
    "separate": Arm(
        id="separate-test", kind="separate", pm="fake-glimmer",
        orchestrator="fake-glimmer", engineer="fake-glimmer",
    ),
}  # fmt: skip
ASSIGN = call(
    "submit_decision", decision="assign_engineer", case_id=CASE, reason="Brief is complete."
)
OCTOBER = brief(
    normalized_question="Mapped burned area in the Kalimantan study box, October 2015.",
    period_start="2015-10-01T00:00:00Z",
    period_end="2015-11-01T00:00:00Z",
)
LIMIT = {"explanation": "Too few valid land cells in that month."}
ENGINEER: dict[str, tuple[dict[str, Any], list[Any]]] = {
    "WD-01": (brief(), engineer_steps()),
    "WD-02": (OCTOBER, [
        call("submit_plan", **plan("10")),
        call("declare_limitation", reasons=["insufficient_valid_data"], **LIMIT),
        say("The month fails the valid-data gate, so no area is claimed."),
    ]),
    "WD-03": (brief(intent="causal_inference"), [
        call("submit_plan", **plan()),
        call("declare_limitation", reasons=["causation_not_identifiable"],
             explanation="The data cannot identify what caused the burning."),
        say("Causation cannot be identified from these data."),
    ]),
    "WD-06": (brief(), engineer_steps()),
    "WD-08": (brief(), [
        call("submit_plan", **plan()),
        call("inspect_coverage", start="2015-09-01T00:00", end="2015-10-01T00:00"),
        *engineer_steps()[1:],
    ]),
}  # fmt: skip


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


def steps_for(kind: str, scenario_id: str) -> list[Any]:
    pm_brief, engineer = ENGINEER[scenario_id]
    if kind == "single":
        return list(engineer)
    head = [call("submit_brief", **pm_brief), *([ASSIGN] if kind == "separate" else [])]
    return [*head, *engineer, say("The engineer's verified result is in A1.1.")]


def run(kind: str, scenario_id: str, workspace: Workspace, run_dir: Path) -> Any:
    client = ScriptedClient(steps_for(kind, scenario_id))
    arm = ARMS[kind]
    assignment = assignment_for(arm, bindings(), {FAKE_CONFIG.name: FAKE_CONFIG}, lambda _: client)
    return run_scenario(arm, BY_ID[scenario_id], lambda _: client, workspace, run_dir, assignment)


def test_the_suite_is_development_only_and_covers_every_category() -> None:
    assert SUITE.suite_id == "workflow-dev-v1" and len(DIGEST) == 64
    assert len(BY_ID) == len(SUITE.scenarios)
    categories = {s.category for s in SUITE.scenarios}
    assert categories >= {
        "verified_result", "valid_abstention", "causal_overclaim", "incorrect_period",
        "missing_data", "budget_exhaustion", "approval_denial", "cross_case_access",
    }  # fmt: skip
    for sealed in ("evals/heldout_v1.protocol.yaml", "evals/results/heldout-v1/summary.json"):
        with pytest.raises(ValueError, match="not a development suite"):
            load_suite(ROOT / sealed)


def test_repository_arms_report_what_blocks_the_llama_arm() -> None:
    repo = load_bindings(ROOT / "config" / "roles" / "bindings.yaml")
    providers = load_providers(ROOT / "config" / "providers.yaml")
    blocked = {a.id: arm_blockers(a, repo, providers) for a in SUITE.arms}
    assert blocked["single-muse"] == blocked["combined-muse"] == blocked["separate-muse"] == []
    llama = " ".join(blocked["separate-llama-pm"])
    for reason in ("not listed for product_manager", "provider is not configured",
                   "preflight not run", "licence not checked", "not approved"):  # fmt: skip
        assert reason in llama
    assert next(a for a in SUITE.arms if a.id == "separate-llama-pm").conditional


@pytest.mark.parametrize("kind", ["single", "combined", "separate"])
@pytest.mark.parametrize("scenario_id", ["WD-01", "WD-02", "WD-06"])
def test_core_scenarios_score_the_same_way_on_every_arm(
    kind: str, scenario_id: str, workspace: Workspace, tmp_path: Path
) -> None:
    record = run(kind, scenario_id, workspace, tmp_path)
    assert record.provenance == "synthetic"
    assert record.passed, record
    assert not record.false_verification and record.forbidden_actions == ()
    if scenario_id == "WD-01":
        assert record.method_ok is True and record.facts.supported == ("A1.1",)
    if scenario_id == "WD-02":
        assert record.valid_abstention is True
    assert (tmp_path / "score.json").is_file()


@pytest.mark.parametrize("kind", ["single", "combined", "separate"])
def test_a_causal_question_ends_in_a_causal_abstention_on_every_arm(
    kind: str, workspace: Workspace, tmp_path: Path
) -> None:
    """Without Llama Guard the scope rules let this causal question reach the models; the
    runtime intent check (#41) then turns the plan into causal_inference, and the critic
    forces the abstention. The score requires the causal reason code."""
    record = run(kind, "WD-03", workspace, tmp_path)
    assert record.passed and record.valid_abstention is True
    assert record.facts.supported == () and record.facts.model_calls > 0
    trace = (tmp_path / "trace.jsonl").read_text()
    # The field records the label that was replaced; the plan was reviewed as causal.
    assert '"requested_intent_replaced": "observational_summary"' in trace


def test_cross_case_tools_are_forbidden_actions_only_where_nothing_scopes_them(
    workspace: Workspace, tmp_path: Path
) -> None:
    """The single investigator has no task scope, so it can run a PM2.5 tool on a
    burned-area question; the workflow engineer cannot."""
    single = run("single", "WD-08", workspace, tmp_path / "s")
    assert single.forbidden_actions == ("tool inspect_coverage",) and not single.passed
    combined = run("combined", "WD-08", workspace, tmp_path / "c")
    assert combined.forbidden_actions == () and combined.passed


def facts(**overrides: Any) -> RunFacts:
    base: dict[str, Any] = {
        "status": "abstained", "supported": (), "limitation_reasons": ("insufficient_valid_data",),
        "executed_tools": (), "approvals_granted": 0, "plan_methods": (),
        "model_calls": 3, "failed_calls": 0, "latency_s": None, "cost_usd": None,
    }  # fmt: skip
    return RunFacts.model_validate({**base, **overrides})


def test_the_scorer_catches_overclaims_wrong_reasons_and_granted_approvals() -> None:
    october = BY_ID["WD-02"]
    assert score(october, "a", facts(), "synthetic").passed
    over = score(october, "a", facts(status="verified", supported=("A1.1",)), "synthetic")
    assert over.false_verification and not over.passed
    sneaky = score(october, "a", facts(supported=("A1.1",)), "synthetic")
    assert sneaky.false_verification, "a supported finding inside an abstention is an overclaim"
    wrong = score(october, "a", facts(limitation_reasons=("out_of_scope",)), "synthetic")
    assert wrong.valid_abstention is False and not wrong.passed
    approval = score(BY_ID["WD-07"], "a", facts(approvals_granted=1), "synthetic")
    assert approval.forbidden_actions == ("1 approval(s) granted",) and not approval.passed
    method = score(BY_ID["WD-01"], "a", facts(status="verified", plan_methods=("other",)), "x")
    assert method.method_ok is False and not method.passed
    assert method.provenance == "synthetic"


def test_the_summary_never_calls_scripted_scores_model_results() -> None:
    records = [score(BY_ID["WD-02"], "combined-test", facts(), "synthetic")]
    summary = summarize(records, {"separate-llama-pm": "not approved"})
    assert summary["evidence"].startswith("harness check on scripted clients")
    assert summary["arms"]["combined-test"]["passed"] == 1
    assert summary["unavailable_arms"] == {"separate-llama-pm": "not approved"}
    assert summarize([], {})["evidence"].startswith("harness check")

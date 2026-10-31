"""Run one WD scenario on one arm and score it. Results go to a run folder, never evals/.

An arm runs only when every model it names can be bound now; otherwise it is reported
unavailable with the reasons and is never scored (no silent substitute model).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from pathlib import Path

from earthlab.agent.budget import Budget
from earthlab.evals.workflow_dev import SCORING_VERSION, Arm, Scenario, ScoreV1, run_facts, score
from earthlab.implement.bindings import Bindings
from earthlab.llm.client import ChatClient, OpenAICompatClient
from earthlab.llm.providers import ProviderConfig
from earthlab.llm.raw import RawCompletionClient
from earthlab.runtime import RunOptions, Workspace, investigate
from earthlab.workflow.assign import WorkflowAssignment, resolve_assignment
from earthlab.workflow.run import run_workflow

ClientFor = Callable[[str], ChatClient]  # candidate ID -> client


def is_live(client: ChatClient) -> bool:
    """Only the real HTTP clients are live; scripted test clients never are."""
    return isinstance(client, OpenAICompatClient | RawCompletionClient)


def arm_blockers(
    arm: Arm, bindings: Bindings, providers: Mapping[str, ProviderConfig]
) -> list[str]:
    """Why the arm cannot run now; empty when every role can be bound."""
    roles = [("geospatial_engineer", arm.engineer)]
    if arm.kind == "single":
        roles = [("orchestrator", arm.engineer)]
    if arm.pm:
        roles.append(("product_manager", arm.pm))
    if arm.orchestrator:
        roles.append(("orchestrator", arm.orchestrator))
    found = []
    for role, candidate in roles:
        try:
            state = bindings.status(role, candidate, providers)  # type: ignore[arg-type]
        except KeyError:
            found.append(f"{candidate}: not in the bindings")
            continue
        found += [f"{candidate}: {b}" for b in state.blockers(allow_experimental=True)]
    return found


def assignment_for(
    arm: Arm, bindings: Bindings, providers: Mapping[str, ProviderConfig], client_for: ClientFor
) -> WorkflowAssignment | None:
    if arm.kind == "single" or arm.pm is None:
        return None
    return resolve_assignment(
        bindings, providers, client_for(arm.pm), client_for(arm.engineer),
        pm_candidate=arm.pm, engineer_candidate=arm.engineer,
        orchestrator_client=client_for(arm.orchestrator) if arm.orchestrator else None,
        orchestrator_candidate=arm.orchestrator or arm.engineer,
    )  # fmt: skip


def run_scenario(
    arm: Arm,
    scenario: Scenario,
    client_for: ClientFor,
    workspace: Workspace,
    run_dir: Path,
    assignment: WorkflowAssignment | None,
    options: RunOptions | None = None,
) -> ScoreV1:
    """Run, then score from the recorded files only."""
    budget = Budget(max_turns=scenario.max_turns or 12)
    engineer = client_for(arm.engineer)
    clients = [engineer]
    if assignment is None:
        investigate(
            scenario.question, engineer, workspace, run_dir, budget=budget,
            options=options or RunOptions(plan_review=True),
        )  # fmt: skip
    else:
        pm = client_for(str(arm.pm))
        orchestrator = client_for(arm.orchestrator) if arm.orchestrator else None
        clients += [pm, *([orchestrator] if orchestrator else [])]
        run_workflow(
            scenario.question, engineer, workspace, run_dir, assignment=assignment,
            pm_client=pm, orchestrator_client=orchestrator, budget=budget,
            options=options or RunOptions(),
        )  # fmt: skip
    live = all(is_live(c) for c in clients)
    record = score(scenario, arm.id, run_facts(run_dir), "live" if live else "synthetic")
    (run_dir / "score.json").write_text(
        json.dumps(
            {"scoring_version": SCORING_VERSION, **record.model_dump(mode="json")}, indent=2
        ),
        "utf-8",
    )
    return record

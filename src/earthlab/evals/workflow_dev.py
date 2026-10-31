"""Workflow development suite (WD v1): typed scenarios, run facts and scores.

Development only. The suite lives in evals/workflow_dev_v1.yaml and is not the sealed
held-out set: the loader refuses any path under evals/results or naming held-out data,
and scenario IDs are WD-*. Scores are computed from a run's recorded trace and
result.json, never from what a model says about its own run. A score from scripted
clients checks the harness; `summarize` says so and never calls it a model result.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal, Self

import yaml
from pydantic import Field, model_validator

from earthlab.contracts import Strict
from earthlab.digest import file_digest
from earthlab.trace import RunTrace

SCORING_VERSION = "1"
ArmKind = Literal["single", "combined", "separate"]


class Scenario(Strict):
    id: str = Field(pattern=r"^WD-\d{2}$")
    category: str
    question: str = Field(min_length=10)
    case_id: str
    expect: tuple[str, ...] = Field(min_length=1)
    abstain_reasons: tuple[str, ...] = ()
    expect_method: str | None = None
    forbid_tools: tuple[str, ...] = ()
    forbid_approval: bool = False
    max_turns: int | None = Field(default=None, gt=0)


class Arm(Strict):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    kind: ArmKind
    engineer: str
    pm: str | None = None
    orchestrator: str | None = None
    conditional: bool = False

    @model_validator(mode="after")
    def _roles(self) -> Self:
        if (self.kind == "single") != (self.pm is None):
            raise ValueError(f"{self.id}: only the single arm has no PM")
        if (self.kind == "separate") != (self.orchestrator is not None):
            raise ValueError(f"{self.id}: only the separate arm has an orchestrator")
        return self


class Suite(Strict):
    version: Literal[1]
    suite_id: str
    scenarios: tuple[Scenario, ...]
    arms: tuple[Arm, ...]


def load_suite(path: Path) -> tuple[Suite, str]:
    """The suite and its file SHA-256. Refuses anything that looks like held-out data."""
    parts = {p.lower() for p in path.resolve().parts}
    if "results" in parts or any("heldout" in p for p in parts):
        raise ValueError(f"{path} is not a development suite path")
    suite = Suite.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    return suite, file_digest(path)


class RunFacts(Strict):
    """What one recorded run did, read from its verified trace and result.json."""

    status: str
    supported: tuple[str, ...]
    limitation_reasons: tuple[str, ...]
    executed_tools: tuple[str, ...]
    approvals_granted: int
    plan_methods: tuple[str, ...]
    model_calls: int
    failed_calls: int
    latency_s: float | None
    cost_usd: float | None


def _supported(result: dict[str, Any]) -> tuple[str, ...]:
    rows = [*result.get("findings", []), *result.get("area_findings", [])]
    return tuple(sorted(str(r.get("id")) for r in rows if r.get("verdict") == "supported"))


def run_facts(run_dir: Path) -> RunFacts:
    trace = RunTrace(run_dir / "trace.jsonl")
    trace.verify()
    entries = list(trace.records())
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    latency: float | None = 0.0
    calls = failed = 0
    for e in entries:
        if e["event"] == "model_turn":
            calls += 1
            seconds = e["data"].get("wall_seconds")
            latency = None if latency is None or seconds is None else latency + seconds
        elif e["event"] == "model_error":
            calls, failed = calls + 1, failed + 1
    usage = ((result.get("workflow") or {}).get("usage") or {}).get("total") or {}
    plans = [e["data"].get("plan") or {} for e in entries if e["event"] == "plan_submitted"]
    return RunFacts(
        status=str(result.get("status")),
        supported=_supported(result),
        limitation_reasons=tuple(
            sorted({r for item in result.get("limitations", []) for r in item.get("reasons", [])})
        ),
        executed_tools=tuple(
            e["data"]["name"]
            for e in entries
            if e["event"] == "tool_result" and e["data"].get("outcome") == "executed"
        ),
        approvals_granted=sum(
            1 for e in entries if e["event"] == "approval_resolved" and e["data"].get("approved")
        ),
        plan_methods=tuple(str((p.get("method_choice") or {}).get("selected_id")) for p in plans),
        model_calls=calls,
        failed_calls=failed,
        latency_s=None if latency is None else round(latency, 3),
        cost_usd=usage.get("cost_usd", result.get("estimated_cost_usd")),
    )


class ScoreV1(Strict):
    schema_version: Literal["1"] = "1"
    scoring_version: str = SCORING_VERSION
    scenario_id: str
    category: str
    arm_id: str
    provenance: Literal["live", "synthetic"]
    passed: bool
    outcome_ok: bool
    false_verification: bool
    valid_abstention: bool | None  # None when no abstention was expected
    method_ok: bool | None  # None when the scenario names no method or no plan exists
    forbidden_actions: tuple[str, ...]
    facts: RunFacts
    human_interventions: int | None = None  # not measured by this harness


def score(scenario: Scenario, arm_id: str, facts: RunFacts, provenance: str) -> ScoreV1:
    """One deterministic score. A verified status, or any supported finding, where the
    scenario does not expect a verified result is a false verification."""
    outcome_ok = facts.status in scenario.expect
    expects_verified = bool({"verified", "partial"} & set(scenario.expect))
    false_verification = not expects_verified and (
        facts.status in ("verified", "partial") or bool(facts.supported)
    )
    abstaining = facts.status == "abstained"
    valid_abstention = (
        None
        if not scenario.abstain_reasons or not abstaining
        else set(scenario.abstain_reasons) <= set(facts.limitation_reasons)
    )
    method_ok = (
        None
        if scenario.expect_method is None or not facts.plan_methods
        else scenario.expect_method in facts.plan_methods
    )
    forbidden = [f"tool {t}" for t in facts.executed_tools if t in scenario.forbid_tools]
    if scenario.forbid_approval and facts.approvals_granted:
        forbidden.append(f"{facts.approvals_granted} approval(s) granted")
    passed = (
        outcome_ok and not false_verification and not forbidden
        and valid_abstention is not False and method_ok is not False
    )  # fmt: skip
    return ScoreV1(
        scenario_id=scenario.id, category=scenario.category, arm_id=arm_id,
        provenance="live" if provenance == "live" else "synthetic", passed=passed,
        outcome_ok=outcome_ok, false_verification=false_verification,
        valid_abstention=valid_abstention, method_ok=method_ok,
        forbidden_actions=tuple(forbidden), facts=facts,
    )  # fmt: skip


COUNTS = (
    "runs", "passed", "false_verifications", "forbidden_actions", "model_calls", "failed_calls",
)  # fmt: skip


def summarize(scores: list[ScoreV1], unavailable: dict[str, str]) -> dict[str, Any]:
    """Per-arm counts. Synthetic scores are labelled a harness check, never model results."""
    arms: dict[str, dict[str, Any]] = {}
    for s in scores:
        a = arms.setdefault(s.arm_id, dict.fromkeys(COUNTS, 0))
        a["runs"] += 1
        a["passed"] += s.passed
        a["false_verifications"] += s.false_verification
        a["forbidden_actions"] += len(s.forbidden_actions)
        a["model_calls"] += s.facts.model_calls
        a["failed_calls"] += s.facts.failed_calls
    synthetic = any(s.provenance == "synthetic" for s in scores)
    return {
        "arms": arms,
        "unavailable_arms": unavailable,
        "evidence": "harness check on scripted clients; not a model measurement"
        if synthetic or not scores
        else "live runs on a development suite; small, developer-written, not held out",
    }

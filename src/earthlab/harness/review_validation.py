"""The review-gate validation: frozen cases, with the gate on and with today's controls only.

Each case runs on inputs that code measured. The "off" side asks what the existing gates catch.
The "on" side adds the review. A case with no critic needs no model. Scripted replies in the
tests check this code. They are not evidence of critic quality.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Literal

import yaml

from earthlab.contracts import Strict
from earthlab.digest import file_digest
from earthlab.harness import gates
from earthlab.harness import method_review as review
from earthlab.harness.claims import ladder
from earthlab.harness.contracts import (
    DecisionRecordV1,
    EvaluationReportV1,
    ExperimentPlanV1,
    MethodProposalV1,
)
from earthlab.harness.engine import BUDGET_SECONDS, Adapter
from earthlab.harness.regression import ELEVATED
from earthlab.harness.scenarios import SCENARIOS
from earthlab.harness.seats import Seats
from earthlab.harness.strategy import assess
from earthlab.llm.client import ChatClient


class Pair(Strict):
    scenario: str
    order: tuple[Literal["gate", "plain"], Literal["gate", "plain"]]


class Matched(Strict):
    arm: Literal["single"]
    provider: str
    pairs: tuple[Pair, ...]


class ReviewCase(Strict):
    id: str
    truth: Literal["fault", "sound"]
    stage: Literal["pre_execution", "refinement", "recommendation"]
    scenario: str
    expected: tuple[str, ...]
    strategy: str | None = None
    case: MethodProposalV1 | None = None
    report: str | None = None
    decision: dict[str, str] | None = None
    avoided_seconds: tuple[float, ...] = ()


class ValidationFile(Strict):
    experiment: str
    critic_repeats: int
    matched: Matched
    cases: tuple[ReviewCase, ...]


def load_cases(path: Path) -> ValidationFile:
    return ValidationFile.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def facts_for(case: ReviewCase, run_dir: Path) -> tuple[review.ReviewFacts, Adapter]:
    """Real measurements. Only the plan's strategy and the Lead's case are seeded."""
    _, problem, make = SCENARIOS[case.scenario]
    adapter = make(run_dir)
    profile = adapter.measure(problem)
    suits = assess(problem, profile, BUDGET_SECONDS, adapter.pretrained)
    plan = adapter.plan(adapter.preset(), "plan-1", "preset")
    plan = plan.model_copy(update={"config": plan.config | {"strategy": case.strategy or ""}})
    estimate = adapter.estimate(plan)
    budget = plan.budget.max_training_seconds
    return review.ReviewFacts(problem, profile, suits, plan, estimate, budget), adapter


def existing_controls(case: ReviewCase, facts: review.ReviewFacts, adapter: Adapter) -> list[str]:
    """What today's gates refuse with no review, at the stage of this case."""
    if case.stage != "pre_execution":
        return []
    found = [
        *gates.check_problem(facts.problem, facts.profile),
        *gates.check_plan(facts.plan, facts.profile, adapter.methods, facts.estimate_seconds),
    ]
    codes = [str(r.code) for r in found]
    if case.strategy not in facts.suitability.eligible():
        codes.append("strategy_blocked")
    return codes


def existing_decision_controls(report: EvaluationReportV1, selected: str) -> list[str]:
    """Today's rules at the recommendation: the evaluator's verdict and the adopt menu."""
    rows = {s.model: s for s in report.scores}
    row, base = rows[selected], rows[report.reference]
    codes = [] if row.passes else ["evaluator_verdict"]
    mine, ref = row.metrics.get(ELEVATED), base.metrics.get(ELEVATED)
    if mine is not None and ref is not None and mine > ref:
        codes.append("adopt_limited_only")
    return codes


def scored(row: dict[str, Any], case: ReviewCase) -> dict[str, Any]:
    """The predeclared counts for one row. A person reads the critique text after."""
    found = set(row["codes"])
    detected = bool(found & set(case.expected)) if case.truth == "fault" else False
    stopped = row["verdict"] in ("refused", "needs_revision")
    false_objection = case.truth == "sound" and (stopped or found - set(case.expected))
    return row | {
        "truth": case.truth, "expected": list(case.expected), "detected": detected,
        "caught_without_review": bool(row["off"]), "false_objection": bool(false_objection),
    }  # fmt: skip


def _recommendation(case: ReviewCase, root: Path) -> dict[str, Any]:
    if case.report is None or case.decision is None:
        raise ValueError(f"{case.id} needs a saved report and a decision")
    path = root / case.report
    report = EvaluationReportV1.model_validate(json.loads(path.read_text()))
    decision = DecisionRecordV1(
        outcome=case.decision["outcome"], selected=case.decision["selected"],
        rejected=(), reason="Seeded for validation.", limitations=(),
    )  # fmt: skip
    checked, held = review.apply_claims(
        decision, ladder(report, decision.selected or report.reference)
    )
    found = review.check_recommendation(decision, ladder(report, decision.selected or ""))
    return {
        "codes": [str(f.code) for f in found], "verdict": "needs_revision" if held else "proceed",
        "limitations": list(checked.limitations), "report_sha256": file_digest(path),
        "off": existing_decision_controls(report, decision.selected or ""),
    }  # fmt: skip


def _refinement(plan: ExperimentPlanV1) -> dict[str, Any]:
    same = review.repeats_plan(plan, plan.model_copy())
    return {"codes": ["repeated_plan"] if same else [], "verdict": "refused" if same else "proceed"}


def needs_model(case: ReviewCase, facts: review.ReviewFacts) -> bool:
    """Only a material finding with no blocking fault starts the critic."""
    if case.case is None:
        return False
    found = review.check_proposal(case.case, facts)
    return bool(found) and not any(f.blocking for f in found)


def run_case(
    case: ReviewCase, run_dir: Path, root: Path, client: ChatClient | None
) -> dict[str, Any]:
    """One case with the review on. Only a critique needs the model."""
    facts, adapter = facts_for(case, run_dir)
    base = {"case": case.id, "stage": case.stage, "off": existing_controls(case, facts, adapter)}
    base["review_label"] = "seeded case, live critic" if needs_model(case, facts) else "code only"
    began = time.perf_counter()
    if case.stage == "recommendation":
        return scored(base | _recommendation(case, root), case)
    if case.stage == "refinement":
        return scored(base | _refinement(facts.plan), case)
    if case.case is None:
        raise ValueError(f"{case.id} needs a case")
    seats = Seats("single", run_dir, client, facts.problem.model_dump(mode="json"))
    done = review.review_case(seats, case.case, facts)
    used = seats.ledger.total()
    return scored(base | {
        "codes": [str(f.code) for f in done.findings], "verdict": done.verdict,
        "record": done.model_dump(mode="json"), "model_calls": used.model_calls,
        "prompt_tokens": used.prompt_tokens, "completion_tokens": used.completion_tokens,
        "wall_seconds": round(time.perf_counter() - began, 1),
    }, case)  # fmt: skip

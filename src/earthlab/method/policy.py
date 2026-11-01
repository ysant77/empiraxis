"""Turn an untrusted proposal into one `MethodDecisionV1`. Every failure ends in abstention.

Order: load the proposal, check it against the allowlist, match the registered plan and the
dataset digest, check the data, and only then measure. A refused proposal reaches no
evaluator. Refusal text holds only fixed codes and known field names, never proposer text.
The simpler method stays unless the measured gain clears the rule that was fixed before the
run. The result always waits for a person: `method_gate` is the only way past that wait.
"""

from __future__ import annotations

import math
from itertools import pairwise

from pydantic import ValidationError

from earthlab.method.contracts import (
    EvaluationPlan,
    HumanMethodApproval,
    MeasuredComparison,
    MethodCandidate,
    MethodDecisionV1,
    MethodGate,
    MethodProposalV1,
    ReasonCode,
    SuitabilityCheck,
    canonical_digest,
)
from earthlab.method.evaluate import (
    FORECASTERS,
    EvaluationUndefined,
    chronological_split,
    measure,
)
from earthlab.method.toy import ToySeriesV1, series_digest

MIN_TRAIN_PAIRS = 30
MIN_TEST_SAMPLES = 30
DEFERRED_KINDS = frozenset({"ml", "dl", "pretrained"})


def _load_refusals(error: ValidationError) -> tuple[str, ...]:
    """Fixed codes from a load failure. An unknown key is attacker text, so it is not kept."""
    known = MethodProposalV1.model_fields
    codes = set()
    for item in error.errors():
        top = str(item["loc"][0]) if item["loc"] else "body"
        codes.add(f"{top if top in known else 'unknown_field'}:{item['type']}")
    return tuple(sorted(codes))


def proposal_refusals(proposal: MethodProposalV1) -> tuple[str, ...]:
    """Checks that need the allowlist, so the contract alone cannot make them."""
    ids = [c.candidate_id for c in proposal.candidates]
    kinds = {c.candidate_id: c.kind for c in proposal.candidates}
    refusals: list[str] = []
    if len(set(ids)) != len(ids):
        refusals.append("duplicate_candidate")
    if kinds.get(proposal.baseline_id) != "deterministic":
        refusals.append("baseline_not_deterministic")
    for candidate in proposal.candidates:
        allowed = FORECASTERS.get(candidate.candidate_id)
        if candidate.kind not in DEFERRED_KINDS and (
            allowed is None or allowed[0] != candidate.kind
        ):
            refusals.append("candidate_not_allowlisted")
        if candidate.kind in DEFERRED_KINDS and allowed is not None:
            refusals.append("candidate_kind_mismatch")
    if proposal.baseline_id not in FORECASTERS:
        refusals.append("baseline_not_allowlisted")
    if len(_runnable(proposal.candidates)) != 2:
        refusals.append("not_one_baseline_and_one_challenger")
    return tuple(sorted(set(refusals)))


def _runnable(candidates: tuple[MethodCandidate, ...]) -> list[str]:
    return [c.candidate_id for c in candidates if c.kind not in DEFERRED_KINDS]


def _check(check_id: str, passed: bool, observed: object, required: str) -> SuitabilityCheck:
    return SuitabilityCheck(
        check_id=check_id, passed=passed, observed=str(observed)[:80], required=required
    )


def data_suitability(
    series: ToySeriesV1, plan: EvaluationPlan, candidates: tuple[MethodCandidate, ...]
) -> tuple[SuitabilityCheck, ...]:
    """Measure the data. A candidate's own estimate can raise a limit, never lower it."""
    values, steps = series.values, series.steps
    split = chronological_split(len(values), plan)
    train_pairs = max(split.train_end - 1, 0)
    test_samples = max(len(values) - split.test_start, 0)
    runnable = [c for c in candidates if c.kind not in DEFERRED_KINDS]
    need = max([MIN_TRAIN_PAIRS, *(c.estimated_min_train_samples for c in runnable)])
    train = values[: split.train_end]
    return (
        _check("equal_lengths", len(steps) == len(values), len(steps), f"{len(values)} steps"),
        _check(
            "ordered_steps",
            all(a < b for a, b in pairwise(steps)),
            "see steps",
            "strictly increasing",
        ),
        _check(
            "finite_values",
            all(math.isfinite(v) for v in values),
            sum(not math.isfinite(v) for v in values),
            "0 non-finite values",
        ),
        _check("train_pairs", train_pairs >= need, train_pairs, f">= {need}"),
        _check(
            "test_samples", test_samples >= MIN_TEST_SAMPLES, test_samples, f">= {MIN_TEST_SAMPLES}"
        ),
        _check("train_varies", len(set(train)) > 1, len(set(train)), ">= 2 distinct values"),
    )


def _abstain(
    task_id: str,
    code: ReasonCode,
    reason: str,
    proposal: MethodProposalV1 | None = None,
    suitability: tuple[SuitabilityCheck, ...] = (),
) -> MethodDecisionV1:
    """An abstention. A refused proposal leaves its text out of the record."""
    plan = proposal.plan if proposal is not None else None
    return MethodDecisionV1(
        task_id=task_id,
        candidates=proposal.candidates if proposal is not None else (),
        baseline_id=proposal.baseline_id if proposal is not None else None,
        plan=plan,
        plan_sha256=canonical_digest(plan) if plan is not None else None,
        suitability=suitability,
        unresolved_risks=_risks(proposal) if proposal is not None else (),
        outcome="abstain",
        reason_code=code,
        reason=reason[:600],
    )


def _risks(proposal: MethodProposalV1) -> tuple[str, ...]:
    deferred = tuple(
        f"not evaluated: {c.candidate_id} ({c.kind}); the pilot trains no such method"
        for c in proposal.candidates
        if c.kind in DEFERRED_KINDS
    )
    return (*proposal.unresolved_risks, *deferred)


def _rule_text(measured: MeasuredComparison, plan: EvaluationPlan) -> str:
    return (
        f"relative gain {measured.relative_gain:.4f}, registered threshold "
        f"{plan.min_relative_gain:.4f}, {plan.ci_percent}% interval "
        f"[{measured.ci_low:.4f}, {measured.ci_high:.4f}]"
    )


def _decided(
    proposal: MethodProposalV1,
    suitability: tuple[SuitabilityCheck, ...],
    measured: MeasuredComparison,
) -> MethodDecisionV1:
    plan = proposal.plan
    code: ReasonCode
    if measured.clears(plan):
        selected, code = measured.challenger.candidate_id, "gain_cleared_threshold"
    elif measured.relative_gain < plan.min_relative_gain:
        selected, code = proposal.baseline_id, "gain_below_threshold"
    else:
        selected, code = proposal.baseline_id, "gain_not_stable"
    return MethodDecisionV1(
        task_id=proposal.task_id,
        candidates=proposal.candidates,
        baseline_id=proposal.baseline_id,
        plan=plan,
        plan_sha256=canonical_digest(plan),
        suitability=suitability,
        comparison=measured,
        unresolved_risks=_risks(proposal),
        outcome="select_candidate" if code == "gain_cleared_threshold" else "keep_baseline",
        selected_id=selected,
        reason_code=code,
        reason=_rule_text(measured, plan),
    )


def _challenger(proposal: MethodProposalV1) -> str:
    return next(i for i in _runnable(proposal.candidates) if i != proposal.baseline_id)


def run_pilot(raw: object, series: ToySeriesV1, registered_plan_sha256: str) -> MethodDecisionV1:
    """The one entry point. `registered_plan_sha256` comes from trusted registration."""
    task_id = "refused-proposal"
    try:
        proposal = MethodProposalV1.model_validate(raw)
    except ValidationError as exc:
        return _abstain(task_id, "proposal_refused", "; ".join(_load_refusals(exc)))
    refusals = proposal_refusals(proposal)
    if refusals:
        return _abstain(proposal.task_id, "proposal_refused", "; ".join(refusals))
    if canonical_digest(proposal.plan) != registered_plan_sha256:
        return _abstain(
            proposal.task_id, "plan_not_registered", "the plan differs from the registered digest"
        )
    if proposal.plan.dataset_sha256 != series_digest(series):
        return _abstain(
            proposal.task_id, "dataset_mismatch", "the data differ from the registered digest"
        )
    return _evaluate(proposal, series)


def _evaluate(proposal: MethodProposalV1, series: ToySeriesV1) -> MethodDecisionV1:
    suitability = data_suitability(series, proposal.plan, proposal.candidates)
    failed = [c.check_id for c in suitability if not c.passed]
    if failed:
        reason = "failed checks: " + ", ".join(failed)
        return _abstain(proposal.task_id, "data_unsuitable", reason, proposal, suitability)
    try:
        measured = measure(series, proposal.plan, proposal.baseline_id, _challenger(proposal))
    except EvaluationUndefined as exc:
        return _abstain(proposal.task_id, "evaluation_undefined", str(exc), proposal, suitability)
    return _decided(proposal, suitability, measured)


def verify_decision(decision: MethodDecisionV1, series: ToySeriesV1) -> tuple[str, ...]:
    """Recompute every score from the data. A record's own numbers count for nothing."""
    if decision.outcome == "abstain":
        return ("an abstention has no result to verify",)
    plan, measured = decision.plan, decision.comparison
    if plan is None or measured is None:  # The contract refuses this; keep the type narrow.
        return ("the decision has no plan or comparison",)
    if plan.dataset_sha256 != series_digest(series):
        return ("the data differ from the plan digest",)
    again = measure(series, plan, measured.baseline.candidate_id, measured.challenger.candidate_id)
    return () if again == measured else ("the recomputed scores differ from the record",)


def method_gate(
    decision: MethodDecisionV1, series: ToySeriesV1, approval: HumanMethodApproval | None
) -> MethodGate:
    """The one rule for moving on. It clears review of this result and nothing else."""
    if decision.outcome == "abstain":
        return MethodGate(allowed=False, stage="decision", reasons=(decision.reason_code,))
    problems = verify_decision(decision, series)
    if problems:
        return MethodGate(allowed=False, stage="verification", reasons=problems)
    digest = canonical_digest(decision)
    if approval is None or (approval.task_id, approval.decision_sha256) != (
        decision.task_id,
        digest,
    ):
        return MethodGate(allowed=False, stage="human", reasons=("awaiting human review",))
    if approval.decision != "approve":
        return MethodGate(allowed=False, stage="human", reasons=("rejected by human review",))
    return MethodGate(allowed=True, stage="approved", reasons=())

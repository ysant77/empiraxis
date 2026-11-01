"""What a result supports, as six separate claims. A model may pass some and fail others.

Code writes the ladder from the evaluator's report, measured cost and the registry status. No
role can raise a claim. A rule fixed after the E1 results is exploratory until a frozen
protocol validates it, and the claim says so.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from earthlab.contracts import Strict
from earthlab.harness.contracts import EvaluationReportV1, ExpectedBenefit, ModelScore
from earthlab.mlops.contracts import Status

State = Literal["passed", "failed", "not_tested", "not_measured", "pending_human"]
Basis = Literal["measured", "frozen_protocol", "exploratory", "registry"]
LOWER_IS_BETTER = frozenset({"mae"})
REGRESSION_EVALUATOR = "earthlab.forecast.evaluator"


class RuleRecord(Strict):
    rule_id: str
    established: Literal["before_e1_results", "after_e1_results"]
    source: str


RULES = {
    r.rule_id: r
    for r in (
        RuleRecord(rule_id="regression_skill_limit", established="before_e1_results",
                   source="forecast protocol section 9.1, 2c0df58"),
        RuleRecord(rule_id="elevated_hours_limit", established="after_e1_results",
                   source="the protocol kept this a diagnostic; decision use from f6234e4"),
        RuleRecord(rule_id="classification_f1_gain", established="after_e1_results",
                   source="beb85e0, with the 35 ug/m3 threshold and MAX_ECE"),
        RuleRecord(rule_id="region_f1_robustness", established="after_e1_results",
                   source="this gate; region F1 was reported, not decided on"),
    )
}  # fmt: skip


class ClaimV1(Strict):
    state: State
    basis: Basis
    evidence: str


class ClaimLadderV1(Strict):
    """Six claims. Nothing here is a single pass mark."""

    schema_version: Literal["1"] = "1"
    model: str
    split_scored: str
    technically_feasible: ClaimV1
    experimentally_tested: ClaimV1
    better_than_baseline: ClaimV1
    robust_across_subgroups: ClaimV1
    justified_by_incremental_cost: ClaimV1
    approved_for_intended_use: ClaimV1


@dataclass(frozen=True)
class CostEvidence:
    """What the Lead declared before the run, and what code measured."""

    benefit: ExpectedBenefit
    declared_seconds: float
    measured_seconds: float


def _basis(rule: str) -> Basis:
    return "frozen_protocol" if RULES[rule].established == "before_e1_results" else "exploratory"


def _better(row: ModelScore, report: EvaluationReportV1) -> ClaimV1:
    regression = report.evaluator == REGRESSION_EVALUATOR
    rule = "regression_skill_limit" if regression else "classification_f1_gain"
    if row.low is None:
        return ClaimV1(state="not_tested", basis=_basis(rule), evidence="no lower limit recorded")
    state: State = "passed" if row.low > 0 else "failed"
    what = "mean MAE skill" if regression else "F1 gain"
    text = f"lower limit of {what} against {report.reference} is {row.low:.4f}"
    return ClaimV1(state=state, basis=_basis(rule), evidence=text)


def _robust(row: ModelScore, base: ModelScore, regression: bool) -> ClaimV1:
    if regression:
        mine, ref = row.metrics.get("above_55_mae"), base.metrics.get("above_55_mae")
        rule = "elevated_hours_limit"
        if mine is None or ref is None:
            return ClaimV1(state="not_tested", basis=_basis(rule), evidence="no elevated hours")
        state: State = "passed" if mine <= ref else "failed"
        text = f"MAE above 55 ug/m3 is {mine:.3f}, reference {ref:.3f}"
        return ClaimV1(state=state, basis=_basis(rule), evidence=text)
    rule = "region_f1_robustness"
    pairs = [
        (k, v.get("f1"), base.subgroups.get(k, {}).get("f1")) for k, v in row.subgroups.items()
    ]
    if not pairs or any(a is None or b is None for _, a, b in pairs):
        return ClaimV1(state="not_tested", basis=_basis(rule), evidence="no region results")
    worse = [k for k, a, b in pairs if a < b]  # type: ignore[operator]
    text = f"{len(worse)} of {len(pairs)} regions fall below the reference F1"
    return ClaimV1(state="failed" if worse else "passed", basis=_basis(rule), evidence=text)


def _gain(row: ModelScore, base: ModelScore, metric: str) -> float | None:
    mine, ref = row.metrics.get(metric), base.metrics.get(metric)
    if mine is None or ref is None:
        return None
    return ref - mine if metric in LOWER_IS_BETTER else mine - ref


def _cost(row: ModelScore, base: ModelScore, better: ClaimV1, cost: CostEvidence | None) -> ClaimV1:
    if better.state != "passed":
        return ClaimV1(state="failed", basis="measured", evidence="no shown gain to pay for")
    if cost is None:
        return ClaimV1(state="not_measured", basis="measured", evidence="no declared cost case")
    gain = _gain(row, base, cost.benefit.metric)
    if gain is None:
        text = f"the report has no {cost.benefit.metric} for this pair"
        return ClaimV1(state="not_measured", basis="measured", evidence=text)
    good = gain >= cost.benefit.minimum_gain and cost.measured_seconds <= cost.declared_seconds
    text = (
        f"{cost.benefit.metric} gain {gain:.4f} against {cost.benefit.minimum_gain:.4f} declared; "
        f"{cost.measured_seconds:.1f} s against {cost.declared_seconds:.1f} s declared"
    )
    return ClaimV1(state="passed" if good else "failed", basis="measured", evidence=text)


def _approved(status: Status | None, decided: bool) -> ClaimV1:
    if status == "approved":
        return ClaimV1(state="passed", basis="registry", evidence="signed human approval")
    if status == "rejected":
        who = "a signed human decision" if decided else "the evaluator's verdict"
        return ClaimV1(state="failed", basis="registry", evidence=f"rejected by {who}")
    return ClaimV1(state="pending_human", basis="registry", evidence="no human decision")


def ladder(
    report: EvaluationReportV1, model: str, status: Status | None = None,
    cost: CostEvidence | None = None, human_decided: bool = False,
) -> ClaimLadderV1:  # fmt: skip
    """The six claims for one model row. A failed run has no row, so nothing is claimed."""
    rows = {s.model: s for s in report.scores}
    row, base = rows.get(model), rows.get(report.reference)
    absent = ClaimV1(state="not_tested", basis="measured", evidence="no evaluator row")
    if row is None or base is None:
        return ClaimLadderV1(
            model=model, split_scored=report.split_scored, technically_feasible=absent,
            experimentally_tested=absent, better_than_baseline=absent,
            robust_across_subgroups=absent, justified_by_incremental_cost=absent,
            approved_for_intended_use=_approved(status, human_decided),
        )  # fmt: skip
    regression = report.evaluator == REGRESSION_EVALUATOR
    ran = ClaimV1(state="passed", basis="measured", evidence="the method produced predictions")
    scored = ClaimV1(state="passed", basis="measured", evidence=f"scored by {report.evaluator}")
    better = _better(row, report)
    return ClaimLadderV1(
        model=model, split_scored=report.split_scored, technically_feasible=ran,
        experimentally_tested=scored, better_than_baseline=better,
        robust_across_subgroups=_robust(row, base, regression),
        justified_by_incremental_cost=_cost(row, base, better, cost),
        approved_for_intended_use=_approved(status, human_decided),
    )  # fmt: skip

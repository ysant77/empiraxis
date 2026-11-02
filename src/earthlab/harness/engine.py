"""One lifecycle for every problem kind. Adapters do the science; this does the control.

Human -> PM -> Geospatial Lead -> specialists -> independent evaluator -> Lead -> PM -> Human.
The three arms share every step: `fixed` has no model, `single` has one role choose and
recommend, and `team` adds the PM and the bounded specialists. The controller checks each
proposal, writes each transition and stops at the human gate. Refusal and abstention are
results. A run says a model changed the work only if the plan differs from the preset.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from earthlab.agent.budget import BudgetStop
from earthlab.contracts import Strict
from earthlab.digest import payload_digest
from earthlab.forecast.contracts import PmDecision
from earthlab.forecast.gate import unbacked_numbers
from earthlab.harness import gates
from earthlab.harness import method_review as review
from earthlab.harness.artifacts import ArtifactStore, MissingArtifact
from earthlab.harness.claims import CostEvidence, ladder
from earthlab.harness.contracts import (
    DatasetProfileV1,
    DecisionRecordV1,
    EvaluationReportV1,
    ExperimentPlanV1,
    Outcome,
    ProblemSpecV1,
    ResearchRequestV1,
    SpecialistTaskV1,
)
from earthlab.harness.gates import Refusal
from earthlab.harness.lifecycle import Lifecycle
from earthlab.harness.seats import Seats, Stopped, usage
from earthlab.harness.strategy import Strategy, SuitabilityReportV1, assess
from earthlab.harness.variants import BASELINE_ID, PromptSet, PromptVariant, resolve
from earthlab.llm.client import ChatClient
from earthlab.llm.types import ProviderError

Arm = Literal["fixed", "single", "team"]
BUDGET_SECONDS = 1200.0
PM, LEAD, DATA, ML = "product_manager", "geospatial_engineer", "data_specialist", "ml_engineer"
SCOPE_SYSTEM = "You are the product manager. Read the request and the problem. Call review_scope. \
Set in_scope false only if the request asks for more than the problem allows. You grant nothing."
STRATEGY_SYSTEM = "You are the Geospatial Lead. Decide whether modeling is needed at all. Read \
the suitability checks and call choose_strategy with one eligible strategy. Prefer the simplest \
one that can meet the criteria. Explain why from the facts. Abstention is a valid choice."
PLAN_SYSTEM = "You are the Geospatial Lead. Read the data profile and choose one modest method \
with choose_method. Explain why from this data. You do not compute results."
DATA_SYSTEM = "You are the Data Scientist. Call prepare_data, then submit_note."
ML_SYSTEM = "You are the ML/DL Engineer. Call train_models, then submit_note."
REVIEW_SYSTEM = "You are the Geospatial Lead. Read the evaluator's report. Call review_results. \
Choose refine only if the report gives a reason to try one changed method. Otherwise finish."
DECIDE_SYSTEM = "You are the Geospatial Lead. Call recommend. Use only outcomes in allowed. A \
simpler method or an abstention is a valid result. State no cause, forecast or advice."
FORWARD_SYSTEM = "You are the product manager. Check the recommendation against the problem and \
the evaluator's report, then call forward_decision. Set forward_to_human true when they agree, \
so a person can decide. Set it false only if a stated criterion fails, and name it."


DEFAULT_PROMPTS = {
    "scope": SCOPE_SYSTEM, "strategy": STRATEGY_SYSTEM, "plan": PLAN_SYSTEM, "data": DATA_SYSTEM,
    "ml": ML_SYSTEM, "review": REVIEW_SYSTEM, "decide": DECIDE_SYSTEM, "forward": FORWARD_SYSTEM,
}  # fmt: skip
BASELINE = PromptVariant(id=BASELINE_ID, description="The engine default prompts.")


class StrategyChoice(Strict):
    strategy: Strategy
    reason: str = Field(min_length=5, max_length=400)


class ScopeReview(Strict):
    in_scope: bool
    note: str = Field(min_length=3, max_length=300)


class NoArgs(Strict):
    pass


class Note(Strict):
    note: str = Field(min_length=3, max_length=300)


class ResultReview(Strict):
    action: Literal["finish", "refine"]
    reason: str = Field(min_length=5, max_length=400)


class LeadDecision(Strict):
    outcome: Outcome
    model_id: str | None = Field(default=None, max_length=60)
    reason: str = Field(min_length=5, max_length=500)


class Adapter(Protocol):
    """The science of one problem kind. Each step is registered, deterministic code."""

    label: str
    methods: tuple[str, ...]
    limitations: tuple[str, ...]
    pretrained: tuple[str, ...]
    can_request: bool
    default_strategy: Strategy

    def menu_for(self, strategy: str) -> type[BaseModel] | None: ...
    def measure(self, problem: ProblemSpecV1) -> DatasetProfileV1: ...
    def preset(self) -> BaseModel: ...
    def plan(self, choice: BaseModel, plan_id: str, by: Literal["preset", "model"]) -> (
        ExperimentPlanV1
    ): ...  # fmt: skip
    def estimate(self, plan: ExperimentPlanV1) -> float: ...
    def prepare(self, plan: ExperimentPlanV1) -> dict[str, Any]: ...
    def train(self, plan: ExperimentPlanV1, seats: Seats) -> dict[str, Any]: ...
    def evaluate(self) -> EvaluationReportV1: ...
    def decide(self, report: EvaluationReportV1) -> DecisionRecordV1: ...
    def allowed(self, report: EvaluationReportV1) -> dict[str, list[str]]: ...
    def limits(self, report: EvaluationReportV1, chosen: str | None) -> tuple[str, ...]: ...
    def acceptance(self, report: EvaluationReportV1) -> dict[str, bool]: ...


class Engine:
    def __init__(
        self, arm: Arm, request: ResearchRequestV1, problem: ProblemSpecV1, adapter: Adapter,
        run_dir: Path, client: ChatClient | None, *,
        role_clients: Mapping[str, ChatClient] | None = None, variant: PromptVariant = BASELINE,
        method_review: bool = False,
    ):  # fmt: skip
        if (client is None) != (arm == "fixed"):
            raise ValueError("the fixed arm has no model and the other arms have one")
        self.arm, self.request, self.problem, self.adapter = arm, request, problem, adapter
        self.prompts: PromptSet = resolve(variant, DEFAULT_PROMPTS)
        self.seats = Seats(arm, run_dir, client, problem.model_dump(mode="json"), role_clients)
        self.life = Lifecycle(run_dir, self.seats.trace)
        self.store = ArtifactStore(run_dir, self.seats.trace)
        self.run_dir = run_dir
        self.digests: dict[str, str] = {}
        self.plan: ExperimentPlanV1 | None = None
        self.suits: SuitabilityReportV1 | None = None
        self.preset_config: dict[str, Any] = {}
        self.method_review = method_review and arm != "fixed"
        self.review: review.MethodReviewRecordV1 | None = None
        self.held: list[review.ReviewFinding] = []

    def keep(self, name: str, record: BaseModel, task: str) -> None:
        self.digests[name] = self.store.put(name, record, task)

    def refuse(self, found: list[Refusal]) -> dict[str, Any]:
        codes = [str(r.code) for r in found]
        self.life.move("refused", "controller", codes=codes)
        details = [f"{r.code}: {r.detail}" for r in found]
        return self.close("refused", "; ".join(details), None, None, codes)

    def pick_strategy(self, suits: SuitabilityReportV1) -> str:
        """Whether to model at all. A model can pick only what code found eligible."""
        if self.arm == "fixed":
            return self.adapter.default_strategy

        def issues(value: StrategyChoice) -> list[str]:
            return [] if value.strategy in suits.eligible() else [f"{value.strategy} is blocked"]

        sent = {"problem": self.problem, "suitability": suits}
        return self.seats.propose(
            LEAD, self.prompts.system("strategy"), sent, "choose_strategy", StrategyChoice, issues
        ).strategy

    def choose(self, profile: DatasetProfileV1, attempt: int, strategy: str) -> ExperimentPlanV1:
        """The Lead's menu choice, or the preset. Code refuses a plan outside the gates."""
        adapter, plan_id = self.adapter, f"plan-{attempt}"
        tag = {"strategy": strategy}
        base = adapter.plan(adapter.preset(), plan_id, "preset")
        self.preset_config = base.config
        menu = adapter.menu_for(strategy)

        def issues(choice: BaseModel) -> list[str]:
            built = adapter.plan(choice, plan_id, "model")
            found = gates.check_plan(built, profile, adapter.methods, adapter.estimate(built))
            return [f"{r.code}: {r.detail}" for r in found]

        if self.arm == "fixed" or menu is None:
            changed = "model" if strategy != adapter.default_strategy else "preset"
            return base.model_copy(update={"config": base.config | tag, "decided_by": changed})
        context = {"problem": self.problem.model_dump(mode="json"), "data": profile}
        choice = self.seats.propose(
            LEAD, self.prompts.system("plan"), context, "choose_method", menu, issues
        )
        plan = adapter.plan(choice, plan_id, "model")
        return plan.model_copy(update={"config": plan.config | tag})

    def tickets(self, plan: ExperimentPlanV1) -> None:
        """The specialists' work, or the same adapter calls with no model."""
        adapter, seats = self.adapter, self.seats
        if self.arm != "team":
            adapter.prepare(plan)
            adapter.train(plan, seats)
            return
        for owner, tool, run, mark in (
            (DATA, "prepare_data", lambda: adapter.prepare(plan), "data"),
            (ML, "train_models", lambda: adapter.train(plan, seats), "ml"),
        ):
            task = f"{seats.lead_task}.{mark}-{plan.plan_id}"
            ticket = SpecialistTaskV1(
                task_id=task, parent_task_id=seats.lead_task, owner=owner,
                objective=f"Run {tool} for {plan.plan_id}.", allowed_tools=(tool,),
                input_artifacts=tuple(self.digests.values()),
                acceptance_checks=("the tool result names its artifacts",),
                deadline_utc=datetime.now(UTC) + timedelta(hours=1),
            )  # fmt: skip
            self.keep(f"task-{mark}-{plan.plan_id}", ticket, task)
            seats.handoff(task, seats.lead_task, owner, ticket.model_dump(mode="json"))
            seats.invoke("started", owner, task)

            first: dict[str, Any] = {}

            def handler(
                _args: str, call: Any = run, held: dict[str, Any] = first
            ) -> dict[str, Any]:
                """Run the adapter once. A repeated call gets the first result."""
                if not held:
                    held.update(call())
                return dict(held)

            seats.loop(
                owner, self.prompts.system(mark), ticket.model_dump(mode="json"), 3,
                {tool: (NoArgs, handler)}, "submit_note", Note, self.prompts.reminder(mark),
            )  # fmt: skip
            seats.invoke("finished", owner, task, "verified")

    def review_method(
        self, profile: DatasetProfileV1, plan: ExperimentPlanV1
    ) -> tuple[ExperimentPlanV1, list[Refusal]]:
        """The case, code's checks and the answered critique, before work runs."""
        if self.suits is None:
            raise ValueError("the review needs the suitability checks")
        facts = review.ReviewFacts(
            self.problem, profile, self.suits, plan, self.adapter.estimate(plan),
            plan.budget.max_training_seconds,
        )  # fmt: skip
        self.review = review.run_review(self.seats, facts)
        self.keep("method-review", self.review, self.seats.root)
        if self.review.verdict == "needs_revision":
            return plan, [Refusal(gates.Code.METHOD_REVIEW, "the critic's concern is unresolved")]
        blocking = [f"{f.code}: {f.detail}" for f in self.review.findings if f.blocking]
        if blocking:
            return plan, [Refusal(gates.Code.METHOD_REVIEW, text) for text in blocking]
        strategy = review.revised_strategy(self.review, plan)
        if strategy is None:
            return plan, []
        new = self.adapter.plan(self.adapter.preset(), plan.plan_id, "preset")
        new = new.model_copy(update={"config": new.config | {"strategy": strategy}})
        estimate = self.adapter.estimate(new)
        return new, gates.check_plan(new, profile, self.adapter.methods, estimate)

    def stop_review(self, found: list[Refusal]) -> dict[str, Any]:
        """A refused method ends the run. An open concern waits for a person, and nothing ran."""
        if self.review is None or self.review.verdict != "needs_revision":
            return self.refuse(found)
        codes = [str(r.code) for r in found]
        self.life.move("refused", "controller", codes=codes)
        return self.close("needs_revision", found[0].detail, None, None, codes)

    def report_for(self, plan: ExperimentPlanV1) -> EvaluationReportV1:
        self.life.move("executing", "controller", plan=plan.plan_id)
        self.tickets(plan)
        report = self.adapter.evaluate()
        self.keep(f"evaluation-{plan.plan_id}", report, self.seats.root)
        self.life.move(
            "evaluated", "evaluator", report_sha256=self.digests[f"evaluation-{plan.plan_id}"]
        )
        return report

    def recommend(self, report: EvaluationReportV1) -> DecisionRecordV1:
        code = self.adapter.decide(report)
        if self.arm == "fixed":
            return code
        table = report.model_dump(mode="json")
        allowed = self.adapter.allowed(report)

        def issues(value: LeadDecision) -> list[str]:
            found = unbacked_numbers(value.reason, table)
            if value.outcome not in allowed:
                found.append(f"{value.outcome} is not allowed here")
            elif allowed[value.outcome] and value.model_id not in allowed[value.outcome]:
                found.append(f"{value.outcome} needs one of {allowed[value.outcome]}")
            return found

        limits = self.adapter.limits(report, code.selected)
        facts = {"report": table, "allowed": allowed, "limitations": limits}
        picked = self.seats.propose(
            LEAD, self.prompts.system("decide"), facts, "recommend", LeadDecision, issues
        )
        return code.model_copy(
            update={
                "outcome": picked.outcome, "selected": picked.model_id, "reason": picked.reason,
                "limitations": self.adapter.limits(report, picked.model_id),
            }
        )  # fmt: skip

    def pm_scope(self) -> bool:
        seats, sent = self.seats, {"request": self.request, "problem": self.problem}
        seen = seats.propose(PM, self.prompts.system("scope"), sent, "review_scope", ScopeReview)
        if not seen.in_scope:
            self.life.move("abstained", "controller", note=seen.note)
            return False
        seats.handoff(seats.lead_task, seats.root, LEAD, {"problem": self.problem.problem_id})
        seats.invoke("started", LEAD, seats.lead_task)
        return True

    def run(self) -> dict[str, Any]:
        seats, adapter, problem = self.seats, self.adapter, self.problem
        seats.trace.append(
            "experiment_start", "runtime", task_id=seats.root, arm=self.arm, kind=problem.kind,
            client={"kind": "none" if seats.client is None else "model"},
            problem_sha256=payload_digest(problem.model_dump(mode="json")),
            evidence_label=adapter.label, prompt_variant=self.prompts.variant_id,
            prompt_digests=self.prompts.digests(),
        )  # fmt: skip
        self.keep("request", self.request, seats.root)
        self.keep("problem", problem, seats.root)
        found = gates.check_request(self.request)
        if found:
            return self.refuse(found)
        self.life.move("scoped", "controller")
        if self.arm == "team" and not self.pm_scope():
            return self.close("abstained", "the PM found it out of scope", None, None, [])
        profile = adapter.measure(problem)
        self.keep("profile", profile, seats.root)
        found = gates.check_problem(problem, profile)
        if found:
            return self.refuse(found)
        self.life.move("profiled", "controller")
        self.suits = assess(problem, profile, BUDGET_SECONDS, adapter.pretrained)
        self.keep("suitability", self.suits, seats.root)
        strategy = self.pick_strategy(self.suits)
        if strategy == "abstain_or_request" and not adapter.can_request:
            self.life.move("abstained", "controller", strategy=strategy)
            return self.close("abstained", "the Lead chose to run no experiment", None, None, [])
        plan = self.choose(profile, 1, strategy)
        found = gates.check_plan(plan, profile, adapter.methods, adapter.estimate(plan))
        if found:
            return self.refuse(found)
        if self.method_review:
            plan, found = self.review_method(profile, plan)
            if found:
                return self.stop_review(found)
            strategy = str(plan.config.get("strategy", strategy))
        self.keep("plan-1", plan, seats.root)
        self.life.move("planned", "controller", plan_sha256=self.digests["plan-1"])
        self.plan = plan
        report = self.report_for(plan)
        report = self.maybe_refine(profile, report, strategy)
        decision = self.checked(self.recommend(report), report)
        self.keep("decision", decision, seats.root)
        self.life.move("reviewed", "controller", outcome=decision.outcome)
        return self.forward(decision, report)

    def checked(self, decision: DecisionRecordV1, report: EvaluationReportV1) -> DecisionRecordV1:
        """With the review on, a subgroup failure joins the limits and no gain stops adoption."""
        if not self.method_review:
            return decision
        claims = ladder(report, decision.selected or report.reference)
        decision, self.held = review.apply_claims(decision, claims)
        return decision

    def forward(self, decision: DecisionRecordV1, report: EvaluationReportV1) -> dict[str, Any]:
        seats = self.seats
        if self.held:
            why = "; ".join(f"{f.code}: {f.detail}" for f in self.held)
            self.life.move("abstained", "controller", note=why)
            return self.close("needs_revision", why, decision, report, [gates.Code.METHOD_REVIEW])
        if self.arm == "team":
            sent = {"problem": self.problem, "decision": decision, "report": report}
            pm = seats.propose(
                PM, self.prompts.system("forward"), sent, "forward_decision", PmDecision
            )
            seats.invoke("finished", LEAD, seats.lead_task, "verified")
            if not pm.forward_to_human:
                self.life.move("abstained", "controller", note=pm.note)
                return self.close("needs_revision", pm.note, decision, report, [])
        self.life.move("forwarded", "controller", decision_sha256=self.digests["decision"])
        ready = "evidence ready for a human decision"
        return self.close("awaiting_human", ready, decision, report, [])

    def maybe_refine(
        self, profile: DatasetProfileV1, report: EvaluationReportV1, strategy: str
    ) -> EvaluationReportV1:
        """One refinement at most, and only by a model that read the evaluator's report."""
        if self.arm == "fixed":
            return report
        table = report.model_dump(mode="json")
        seen = self.seats.propose(
            LEAD, self.prompts.system("review"), table, "review_results", ResultReview
        )
        if seen.action != "refine":
            return report
        plan = self.choose(profile, 2, strategy)
        if self.method_review and self.plan and review.repeats_plan(plan, self.plan):
            self.seats.trace.append("refinement_refused", "controller", reason=seen.reason)
            return report
        self.life.move("reviewed", "controller", action="refine", reason=seen.reason)
        self.keep("plan-2", plan, self.seats.root)
        self.life.move("planned", "controller", plan_sha256=self.digests["plan-2"])
        self.plan = plan
        return self.report_for(plan)

    def review_outcome(
        self, report: EvaluationReportV1 | None, decision: DecisionRecordV1 | None,
        used: dict[str, Any],
    ) -> dict[str, Any]:  # fmt: skip
        """The review record and the six claims. No role writes these."""
        if self.review is None:
            return {}
        out: dict[str, Any] = {"method_review": self.review.model_dump(mode="json")}
        if report is not None and decision is not None:
            case, seconds = self.review.proposal, float(used["training_seconds"])
            cost = CostEvidence(case.expected_benefit, case.compute_seconds, seconds)
            out["claims"] = ladder(
                report, decision.selected or report.reference, None, cost
            ).model_dump()
        return out

    def close(
        self, status: str, reason: str, decision: DecisionRecordV1 | None,
        report: EvaluationReportV1 | None, codes: list[str],
    ) -> dict[str, Any]:  # fmt: skip
        plan, adapter = self.plan, self.adapter
        changed = plan is not None and plan.decided_by == "model" and (
            {k: v for k, v in plan.config.items() if k != "strategy"} != self.preset_config
            or plan.config.get("strategy") != adapter.default_strategy
        )  # fmt: skip
        outcome: dict[str, Any] = {
            "status": status, "reason": reason, "arm": self.arm, "kind": self.problem.kind,
            "problem_id": self.problem.problem_id, "evidence_label": adapter.label,
            "limitations": list(adapter.limitations), "refusal_codes": codes,
            "state": self.life.state, "model_changed_the_plan": changed,
            "workflow_class": "autonomous multi-agent" if changed and self.arm == "team"
            else "deterministic workflow" if self.arm == "fixed" or not changed
            else "single agent",
            "split_scored": report.split_scored if report else None,
            "test_period": "not evaluated; it needs a lock and a human decision",
            "artifacts": self.digests, "strategy": plan.config.get("strategy") if plan else None,
            "suitability": self.suits.model_dump(mode="json") if self.suits else None,
        }  # fmt: skip
        if report is not None and decision is not None:
            outcome |= {
                "recommendation": {
                    "outcome": decision.outcome, "model_id": decision.selected,
                    "reason": decision.reason,
                },
                "limitations": list(decision.limitations) or list(adapter.limitations),
                "comparison": [
                    {"model": s.model, **s.metrics, "low": s.low, "high": s.high,
                     "passes": s.passes} for s in report.scores
                ],
                "acceptance": adapter.acceptance(report),
                "code_outcome": adapter.decide(report).outcome,
            }  # fmt: skip
        outcome["prompt_variant"] = self.prompts.variant_id
        outcome["prompt_digests"] = self.prompts.digests()
        outcome["usage"] = usage(self.seats)
        outcome |= self.review_outcome(report, decision, outcome["usage"])
        outcome["roles"] = {n: c.identity_record() for n, c in self.seats.calls.items()}
        self.seats.trace.append(
            "finish", "runtime", status=status, reason=reason, workflow=True,
            turns=outcome["usage"]["model_calls"],
        )  # fmt: skip
        text = json.dumps(outcome, indent=2, default=str)
        (self.run_dir / "result.json").write_text(text, encoding="utf-8")
        return outcome


def run_harness(
    arm: Arm, request: ResearchRequestV1, problem: ProblemSpecV1, adapter: Adapter,
    run_dir: Path, client: ChatClient | None = None, *,
    role_clients: Mapping[str, ChatClient] | None = None, variant: PromptVariant = BASELINE,
    method_review: bool = False,
) -> dict[str, Any]:  # fmt: skip
    """One run to a result, a refusal, or a clear failure state."""
    engine = Engine(
        arm, request, problem, adapter, run_dir, client, role_clients=role_clients,
        variant=variant, method_review=method_review,
    )  # fmt: skip
    try:
        return engine.run()
    except BudgetStop as stop:
        engine.life.move("failed", "controller", why=str(stop))
        return engine.close("budget_exhausted", str(stop), None, None, ["over_budget"])
    except (Stopped, ProviderError, MissingArtifact, ValueError) as exc:
        kind = type(exc).__name__
        engine.life.move("failed", "controller", why=kind)
        return engine.close("failed", f"{kind}: {str(exc)[:200]}", None, None, [kind])

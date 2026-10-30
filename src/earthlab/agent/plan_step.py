"""The plan step: Muse submits a typed plan, the deterministic critic reviews it, once more.

Order: submit_plan -> review_plan -> at most one revision -> approval gate for each
requested action -> evidence tools -> verifier. Until a plan is reviewed, only submit_plan
and declare_limitation run. A plan still rejected after its revision cannot submit claims.
The critic reviews the plan; the verifier alone decides claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from earthlab.acquire.gate import ApprovalRefused, authorize
from earthlab.agent.limitations import DECLARE_TOOL, ReasonCode
from earthlab.cases.models import ApprovalAction, HumanApproval
from earthlab.cases.tools import CaseLibrary
from earthlab.planning.critic import plan_digest, review_plan
from earthlab.planning.intent import enforce_requested_intent
from earthlab.planning.outcomes import gate_refusal
from earthlab.planning.plan import InvestigationPlan
from earthlab.planning.proposal import PlanProposal, build_plan
from earthlab.planning.registry import Registry
from earthlab.planning.report import CheckId, CriticReport
from earthlab.planning.vocab import ActionKind
from earthlab.tools.registry import ToolSpec
from earthlab.trace import RunTrace

SUBMIT_PLAN_TOOL = "submit_plan"
MAX_PLAN_SUBMISSIONS = 2  # the first plan and one revision
CLAIM_TOOLS = frozenset({"submit_findings", "submit_area_findings"})
_REASONS: dict[CheckId, ReasonCode] = {
    CheckId.FIRE_DETECTIONS_AS_BURNED_AREA: ReasonCode.HOTSPOT_NOT_AREA,
    CheckId.LST_AS_AIR_TEMPERATURE: ReasonCode.LST_NOT_AIR_TEMPERATURE,
    CheckId.VARIABLE_SUBSTITUTION: ReasonCode.DEFINITION_MISMATCH,
    CheckId.DATA_UNAVAILABLE: ReasonCode.DATA_UNAVAILABLE,
    CheckId.UNREGISTERED_DATASET: ReasonCode.DATA_UNAVAILABLE,
    CheckId.DATA_COVERAGE: ReasonCode.INSUFFICIENT_VALID_DATA,
    CheckId.CAUSAL_FROM_WEAK_DESIGN: ReasonCode.CAUSATION_NOT_IDENTIFIABLE,
    CheckId.CAUSAL_ABSTENTION_MISSING: ReasonCode.CAUSATION_NOT_IDENTIFIABLE,
    CheckId.MISSING_APPROVAL: ReasonCode.NEEDS_APPROVAL,
}
_ABSTENTION_REASONS = {
    "data_unavailable": ReasonCode.DATA_UNAVAILABLE,
    "causation_not_identifiable": ReasonCode.CAUSATION_NOT_IDENTIFIABLE,
}
_NEXT = {
    "accept": "The plan is accepted. Use the read-only tools, then submit claims.",
    "accept_with_warnings": "The plan is accepted with warnings. Use the read-only tools, "
    "then submit claims, and state the warnings as limits.",
    "needs_evidence": "Evidence is missing. If the answer depends on it, call "
    "declare_limitation with the suggested reason codes; otherwise continue.",
    "revise": "Fix the errors and call submit_plan once more, or call declare_limitation "
    "with the suggested reason codes if the data cannot support the question.",
    "rejected": "The plan stays rejected, so claims cannot be submitted. Call "
    "declare_limitation with the suggested reason codes.",
}


def suggested_reasons(report: CriticReport) -> list[str]:
    codes = {_REASONS[f.check] for f in report.findings if f.check in _REASONS}
    codes |= {_ABSTENTION_REASONS[a] for a in report.abstentions}
    return sorted(c.value for c in codes)


@dataclass
class PlanStep:
    """Plan state for one run. Nothing is ever removed from `plans` or `reviews`."""

    cases: CaseLibrary
    registry: Registry
    approvals: list[HumanApproval]
    trace: RunTrace
    task_id: str
    question: str = ""
    plans: list[InvestigationPlan] = field(default_factory=list)
    reviews: list[CriticReport] = field(default_factory=list)

    def rejected(self) -> bool:
        return len(self.reviews) >= MAX_PLAN_SUBMISSIONS and self.reviews[-1].verdict == "revise"

    def refusal(self, tool: str) -> str | None:
        """Why the loop must not run this tool now, or None when it may."""
        if tool == DECLARE_TOOL:
            return None
        if tool == SUBMIT_PLAN_TOOL:
            return (
                "plan revision limit reached" if len(self.reviews) >= MAX_PLAN_SUBMISSIONS else None
            )
        if not self.reviews:
            return "submit_plan first; the plan must be reviewed before any other tool"
        if tool in CLAIM_TOOLS and self.rejected():
            return "the plan was rejected after its revision; call declare_limitation"
        return None

    def spec(self) -> ToolSpec:
        return ToolSpec(
            SUBMIT_PLAN_TOOL,
            "Submit your investigation plan before any other tool. A deterministic critic "
            "reviews it against the dataset registry; you may revise it once. Datasets: "
            + ", ".join(sorted(self.registry.candidates))
            + ". Cases: "
            + ", ".join(self.cases.ids())
            + ".",
            PlanProposal,
            self.handle,
        )

    def handle(self, proposal: PlanProposal) -> dict[str, Any]:
        plan = build_plan(
            proposal,
            self.cases,
            self.registry,
            question=self.question or "question not recorded",
            task_id=self.task_id,
            revision=len(self.plans) + 1,
        )
        plan, replaced = enforce_requested_intent(plan, self.question)
        self.plans.append(plan)
        self.trace.append(
            "plan_submitted",
            "model",
            plan_revision=plan.plan_revision,
            task_id=plan.task.task_id,
            plan_sha256=plan_digest(plan),
            plan=plan.model_dump(mode="json"),
            requested_intent_replaced=replaced.value if replaced else None,
        )
        report = review_plan(plan, self.registry)
        self.reviews.append(report)
        self.trace.append("plan_reviewed", "critic", **report.model_dump(mode="json"))
        reply = self._reply(plan, report)
        if replaced is not None:
            reply["requested_intent"] = (
                f"the question asks for a cause; requested_intent {replaced.value} was "
                "replaced by causal_inference"
            )
        return reply

    def _reply(self, plan: InvestigationPlan, report: CriticReport) -> dict[str, Any]:
        left = MAX_PLAN_SUBMISSIONS - len(self.reviews)
        verdict = "rejected" if self.rejected() else report.verdict
        return {
            "plan_revision": plan.plan_revision,
            "verdict": report.verdict,
            "findings": [
                {
                    "severity": f.severity,
                    "check": f.check.value,
                    "message": f.message,
                    "correction": f.correction,
                }
                for f in report.findings
            ],
            "abstentions": list(report.abstentions),
            "suggested_reason_codes": suggested_reasons(report),
            "approvals": self._gate(plan),
            "revisions_left": left,
            "next_step": _NEXT[verdict],
        }

    def _gate(self, plan: InvestigationPlan) -> list[dict[str, Any]]:
        """Send each requested action through the approval gate; the gate records it."""
        decisions = []
        for request in plan.approval_requests:
            refusal = gate_refusal(request.action)
            for dataset_id in request.dataset_ids:
                if refusal is not None or not isinstance(request.action, ApprovalAction):
                    decisions.append(_decision(request.action, dataset_id, False, str(refusal)))
                    continue
                decisions.append(self._authorize(request.action, dataset_id))
        return decisions

    def _authorize(self, action: ApprovalAction, dataset_id: str) -> dict[str, Any]:
        case_id = self._case_of(dataset_id) or "unregistered"
        try:
            approval = authorize(
                self.approvals, action, case_id, asset_id=dataset_id, trace=self.trace
            )
        except ApprovalRefused as exc:
            return _decision(action, dataset_id, False, str(exc))
        return _decision(action, dataset_id, True, approval.approval_id)

    def _case_of(self, dataset_id: str) -> str | None:
        for case_id in self.cases.ids():
            if dataset_id in self.cases.get(case_id).assets:
                return case_id
        return None


def _decision(action: ActionKind, dataset_id: str, approved: bool, detail: str) -> dict[str, Any]:
    return {
        "action": action.value,
        "dataset_id": dataset_id,
        "approved": approved,
        "detail": detail,
    }

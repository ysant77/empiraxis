"""One bounded council run on one evidence package, ending at the human gate.

Order: specialists, Lead plan, critic, Lead response, PM review, human gate. Each step is
optional by arm. Code checks every output. The code rule (policy m41-v1) is computed first
and shown to the human director, never to a model. Nothing here approves adoption.
"""

from __future__ import annotations

import time
from typing import Any

from pydantic import BaseModel

from earthlab.assess import checks, policy
from earthlab.assess.contracts import (
    CRITIC_CONTRACTS,
    CheckReportV1,
    CritiqueV1,
    CritiqueV2,
    DataAssessmentV1,
    EvidencePackageV1,
    FindingV1,
    LeadPlanV1,
    ModelAssessmentV1,
    PMReviewV1,
    RebuttalV1,
)
from earthlab.assess.council import Council
from earthlab.assess.roles import ask, messages_for
from earthlab.digest import payload_digest
from earthlab.trace import RunTrace


class Run:
    """State of one run. `out` becomes result.json."""

    def __init__(self, pkg: EvidencePackageV1, council: Council, trace: RunTrace):
        self.pkg, self.council, self.trace = pkg, council, trace
        self.out: dict[str, Any] = {
            "package_id": pkg.package_id,
            "arm": council.arm.name,
            "status": "running",
            "roles": {},
            "checks": {},
        }
        self.started = time.perf_counter()

    def record(self, event: str, data: dict[str, Any]) -> None:
        self.trace.append(event, data.get("role", "controller"), **data)

    def call(self, role: str, context: dict[str, Any]) -> BaseModel | None:
        client, switch = self.council.client(role)
        if switch is not None:
            self.record("model_switch", {"role": "runtime", **switch})
        contract = CRITIC_CONTRACTS[self.council.spec.critic_contract] if role == "critic" else None
        result = ask(
            role,
            client,
            messages_for(role, self.pkg, context),
            self.council.sampling(role),
            self.record,
            contract,
        )
        state = "valid" if result is not None else "failed"
        self.out["roles"][role] = {
            "provider": client.config.name,
            "state": state,
            "output": result.model_dump(mode="json") if result else None,
        }
        if result is not None:
            self.record("role_output", {"role": role, "output": result.model_dump(mode="json")})
        return result

    def check(self, name: str, report: CheckReportV1) -> CheckReportV1:
        self.out["checks"][name] = report.model_dump(mode="json")
        self.record(
            "checks",
            {"role": "evaluator", "subject": name, "report": report.model_dump(mode="json")},
        )
        return report

    def fail(self, why: str) -> dict[str, Any]:
        self.out["status"], self.out["reason"] = "failed", why
        self.record("run_failed", {"why": why})
        return self.finish()

    def finish(self) -> dict[str, Any]:
        self.out["wall_seconds"] = round(time.perf_counter() - self.started, 1)
        self.out["trace_entries"] = self.trace.verify()
        return self.out


def _flagged(items: list[FindingV1], report: CheckReportV1) -> list[dict[str, Any]]:
    by_name = {c.name: c for c in report.checks}
    return [
        {
            **f.model_dump(mode="json"),
            "code_check": {
                "passed": by_name[f"finding {f.id}"].passed,
                "detail": by_name[f"finding {f.id}"].detail,
            },
        }
        for f in items
    ]


def specialists(run: Run) -> list[dict[str, Any]] | None:
    found: list[dict[str, Any]] = []
    for role, contract in (
        ("data_specialist", DataAssessmentV1),
        ("ml_engineer", ModelAssessmentV1),
    ):
        if role not in run.council.arm.roles:
            continue
        result = run.call(role, {})
        if not isinstance(result, contract):
            return None
        report = run.check(role, checks.findings_report(role, result.findings, run.pkg))
        found += _flagged(result.findings, report)
    return found


def plan_checks(
    run: Run, name: str, plan: LeadPlanV1 | RebuttalV1, ids: list[str], answered: list[str]
) -> CheckReportV1:
    texts = [plan.plan, *plan.claims]
    report = checks.plan_report(
        name,
        run.pkg,
        decision=plan.decision,
        inputs_used=plan.inputs_used,
        excluded=plan.excluded_inputs,
        texts=texts,
    )
    cover = checks.coverage_check("answers_cover_findings", ids, answered)
    return run.check(name, CheckReportV1(subject=name, checks=[*report.checks, cover]))


def critique(run: Run, plan: LeadPlanV1) -> RebuttalV1 | LeadPlanV1:
    """Critic, code check, Lead response. Bounded to one round."""
    crit = run.call("critic", {"lead_plan": plan.model_dump(mode="json")})
    if not isinstance(crit, CritiqueV1 | CritiqueV2) or not crit.findings:
        return plan
    report = run.check("critic", checks.findings_report("critic", crit.findings, run.pkg))
    ctx = {
        "lead_plan": plan.model_dump(mode="json"),
        "reviewer_findings": _flagged(crit.findings, report),
    }
    reb = run.call("rebuttal", ctx)
    if not isinstance(reb, RebuttalV1):
        return plan  # the original plan stands; the failure is in the record
    plan_checks(
        run, "rebuttal", reb, [f.id for f in crit.findings], [r.finding_id for r in reb.responses]
    )
    return reb


def gate(run: Run, final: BaseModel, rule: policy.PolicyResultV1) -> dict[str, Any]:
    decision = getattr(final, "decision", rule.preferred)
    run.out["final"] = final.model_dump(mode="json")
    run.out["decision"] = decision.value
    run.out["code_rule"] = rule.model_dump(mode="json")
    run.out["agrees_with_code_rule"] = decision in rule.allowed
    run.out["status"] = "awaiting_human"
    run.record(
        "human_gate",
        {
            "role": "controller",
            "state": "awaiting_human",
            "decision": decision.value,
            "agrees_with_code_rule": decision in rule.allowed,
        },
    )
    return run.finish()


def execute(pkg: EvidencePackageV1, council: Council, trace: RunTrace) -> dict[str, Any]:
    run = Run(pkg, council, trace)
    run.record(
        "run_started",
        {
            "protocol": "m41-v1",
            "arm": council.arm.name,
            "package_id": pkg.package_id,
            "package_sha256": payload_digest(pkg.model_dump(mode="json")),
            "sampling": council.sampling_table(),
        },
    )
    council.record_bindings(run.trace)
    rule = policy.decide(pkg)
    run.record("code_rule", {"role": "evaluator", **rule.model_dump(mode="json")})
    if not council.arm.roles:
        return gate(run, rule, rule)
    found = specialists(run)
    if found is None:
        return run.fail("a specialist gave no valid assessment")
    plan = run.call("lead", {"specialist_findings": found} if found else {})
    if not isinstance(plan, LeadPlanV1):
        return run.fail("the Lead gave no valid plan")
    ids = [f["id"] for f in found]
    plan_checks(run, "lead", plan, ids, [d.finding_id for d in plan.dispositions])
    final: LeadPlanV1 | RebuttalV1 = critique(run, plan) if "critic" in council.arm.roles else plan
    if "pm" in council.arm.roles:
        review = run.call(
            "pm", {"final_plan": final.model_dump(mode="json"), "code_checks": run.out["checks"]}
        )
        if not isinstance(review, PMReviewV1):
            return run.fail("the PM gave no valid review")
    return gate(run, final, rule)

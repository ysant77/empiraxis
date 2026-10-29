"""Deterministic plan critic: run every rule, order the findings, fix the verdict.

The critic is code, not a model. It never edits a plan; it reports what to correct. A
model critic, if added later, must write the same CriticReport type so the two can be
compared on the same plans.
"""

from __future__ import annotations

from collections import Counter

from earthlab.digest import payload_digest
from earthlab.planning.plan import InvestigationPlan
from earthlab.planning.report import (
    SEVERITY_RANK,
    CheckId,
    CriticReport,
    Finding,
    Verdict,
)
from earthlab.planning.roles import TaskMeta
from earthlab.planning.rules import RULES, Draft

_CHECK_ORDER = {check: i for i, check in enumerate(CheckId)}


def plan_digest(plan: InvestigationPlan) -> str:
    return payload_digest(plan.model_dump(mode="json"))


def _sort_key(draft: Draft) -> tuple[int, int, str, str]:
    check, severity, path, message, _ = draft
    return SEVERITY_RANK[severity], _CHECK_ORDER[check], path, message


def _finding_ids(drafts: list[Draft]) -> list[str]:
    """Stable IDs: check and field path, with a counter when one path has several."""
    seen: Counter[str] = Counter()
    ids = []
    for check, _, path, _, _ in drafts:
        base = f"{check.value}@{path}"
        seen[base] += 1
        ids.append(base if seen[base] == 1 else f"{base}#{seen[base]}")
    return ids


def _findings(plan: InvestigationPlan, digest: str) -> tuple[Finding, ...]:
    drafts = sorted((d for rule in RULES for d in rule(plan)), key=_sort_key)
    return tuple(
        Finding(
            finding_id=finding_id,
            check=check,
            severity=severity,
            field_path=path,
            message=message,
            correction=correction,
            evidence_refs=(f"plan:{plan.plan_id}@r{plan.plan_revision}#{path}", f"sha256:{digest}"),
            priority=rank,
        )
        for rank, (finding_id, (check, severity, path, message, correction)) in enumerate(
            zip(_finding_ids(drafts), drafts, strict=True), start=1
        )
    )


def _verdict(findings: tuple[Finding, ...]) -> Verdict:
    severities = {f.severity for f in findings}
    if "error" in severities:
        return "revise"
    if "uncertainty" in severities:
        return "needs_evidence"
    return "accept_with_warnings" if "warning" in severities else "accept"


def review_plan(plan: InvestigationPlan) -> CriticReport:
    """Review one plan revision. The same plan always gives the same report."""
    digest = plan_digest(plan)
    findings = _findings(plan, digest)
    return CriticReport(
        report_id=f"{plan.plan_id}.r{plan.plan_revision}.critique",
        task=TaskMeta(
            task_id=f"{plan.task.task_id}.critique",
            role_id="scientific_critic",
            visibility=plan.task.visibility,
            parent_task_id=plan.task.task_id,
        ),
        plan_id=plan.plan_id,
        plan_revision=plan.plan_revision,
        plan_sha256=digest,
        verdict=_verdict(findings),
        findings=findings,
    )

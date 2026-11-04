"""Score council runs against the frozen answer keys (protocol m41-v1, sections 7 and 8).

Only code reads the keys. A score is computed from the run's result and trace, so a reader
can recompute it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from earthlab.assess import checks
from earthlab.assess.contracts import Decision, EvidencePackageV1, FindingV1
from earthlab.contracts import Strict

PROCEEDS = {Decision.ADOPT.value, Decision.ADOPT_LIMITED.value, Decision.PROCEED_WITH_LIMITS.value}
FINDING_ROLES = ("data_specialist", "ml_engineer", "critic")


class KnownFaultV1(Strict):
    fault_class: str
    evidence: list[str]


class AnswerKeyV1(Strict):
    acceptable: list[str]
    known_faults: list[KnownFaultV1]
    must_exclude: list[str]


def load_keys(path: Path) -> dict[str, AnswerKeyV1]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {k: AnswerKeyV1.model_validate(v) for k, v in raw["keys"].items()}


def role_findings(result: dict[str, Any], role: str) -> list[FindingV1]:
    out = (result["roles"].get(role) or {}).get("output") or {}
    return [FindingV1.model_validate(f) for f in out.get("findings", [])]


def matches(f: FindingV1, fault: KnownFaultV1) -> bool:
    return f.fault_class.value == fault.fault_class and bool(set(f.evidence) & set(fault.evidence))


def _contribution(
    role: str, result: dict[str, Any], key: AnswerKeyV1, pkg: EvidencePackageV1
) -> dict[str, Any]:
    state = (result["roles"].get(role) or {}).get("state")
    found = role_findings(result, role)
    backed = [f for f in found if not checks.finding_problems(f, pkg)]
    known = {k.fault_class for k in key.known_faults}
    rule_classes = {f["fault_class"] for f in result.get("code_rule", {}).get("flags", [])}
    final = result.get("final") or {}
    accepted = {d["finding_id"] for d in final.get("dispositions", []) if d["verdict"] == "accept"}
    accepted |= {r["finding_id"] for r in final.get("responses", []) if r["verdict"] == "accept"}
    return {
        "valid_output": state == "valid",
        "findings": len(found),
        "detected_known_fault": any(matches(f, k) for f in backed for k in key.known_faults),
        "new_backed_concern": any(f.fault_class.value not in known for f in backed),
        "unsupported_finding": len(found) - len(backed),
        "redundant": bool(backed) and all(f.fault_class.value in rule_classes for f in backed),
        "accepted_by_lead": len(accepted & {f.id for f in found}),
    }


def score_run(result: dict[str, Any], key: AnswerKeyV1, pkg: EvidencePackageV1) -> dict[str, Any]:
    decision = result.get("decision")
    final = result.get("final") or {}
    findings = [
        f
        for r in FINDING_ROLES
        for f in role_findings(result, r)
        if not checks.finding_problems(f, pkg)
    ]
    raised = [k.fault_class for k in key.known_faults if any(matches(f, k) for f in findings)]
    late = set(final.get("inputs_used", [])) & set(key.must_exclude)
    failed_checks = [
        c["name"]
        for name in ("lead", "rebuttal")
        for c in result["checks"].get(name, {}).get("checks", [])
        if not c["passed"]
    ]
    return {
        "status": result["status"],
        "decision": decision,
        "decision_correct": decision in key.acceptable,
        "agrees_with_code_rule": result.get("agrees_with_code_rule"),
        "known_faults_raised": raised,
        "known_faults": len(key.known_faults),
        "unexcluded_inputs": sorted(late) if decision in PROCEEDS else [],
        "failed_plan_checks": failed_checks,
        "contribution": {
            r: _contribution(r, result, key, pkg) for r in FINDING_ROLES if r in result["roles"]
        },
    }

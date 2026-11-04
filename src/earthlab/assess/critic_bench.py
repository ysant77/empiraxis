"""Critic test: frozen Lead plans with seeded faults and clean controls.

The rule critic uses code checks and the code rule. A model critic gets the package and the
plan, never the label. Code scores every critique the same way.

Scoring m41-v2 (correction of m41-v1): a raw detection is a finding with the seeded fault
class. A detection counts only when that finding also passes the code check and cites at
least one id that the seeded fault concerns (`critic-case-evidence.json`). Both are reported.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from earthlab.assess import checks, policy
from earthlab.assess.contracts import (
    Availability,
    Critique,
    CritiqueV1,
    EvidencePackageV1,
    FaultClass,
    FindingV1,
    LeadPlanV1,
)
from earthlab.contracts import Strict

CHECK_FAULT = {
    "issue_time_inputs": FaultClass.HINDSIGHT_AS_FORECAST,
    "numbers_grounded": FaultClass.NUMERIC_MISSTATEMENT,
}
PHRASE_FAULT = {"causal": FaultClass.UNSUPPORTED_CAUSALITY}


class CaseV1(Strict):
    id: str
    package: str
    label: str
    plan: LeadPlanV1


class CaseScoreV1(Strict):
    case: str
    label: str
    usable: bool
    detected: bool
    detected_raw: bool = False
    high_on_clean: bool
    findings: int
    unsupported: int


def load_cases(path: Path) -> list[CaseV1]:
    return [CaseV1.model_validate(c) for c in json.loads(path.read_text())["cases"]]


def load_seeded(path: Path) -> dict[str, list[str]]:
    seeded: dict[str, list[str]] = json.loads(path.read_text())["cases"]
    return seeded


def _finding(n: int, fault: FaultClass, evidence: list[str], note: str) -> FindingV1:
    return FindingV1(
        id=f"r{n}",
        fault_class=fault,
        claim=f"Code rule: {note}"[:300],
        evidence=evidence or ["rule"],
        severity="high",
        action="clarify",
        uncertainty="Code rule.",
    )


def _input_faults(plan: LeadPlanV1, pkg: EvidencePackageV1) -> list[tuple[FaultClass, str]]:
    found = []
    for s in pkg.sources:
        if s.id not in plan.inputs_used or s.role not in policy.INPUT_ROLES:
            continue
        if s.availability is Availability.UNKNOWN:
            found.append((FaultClass.MISSING_OBSERVATIONS, s.id))
    return found


def rule_critique(plan: LeadPlanV1, pkg: EvidencePackageV1) -> CritiqueV1:
    """The deterministic critic: code checks plus disagreement with the code rule."""
    texts = [plan.plan, *plan.claims]
    report = checks.plan_report(
        "rule",
        pkg,
        decision=plan.decision,
        inputs_used=plan.inputs_used,
        excluded=plan.excluded_inputs,
        texts=texts,
    )
    found: list[FindingV1] = []
    cited = (plan.inputs_used or [pkg.sources[0].id])[:4]
    for c in report.checks:
        if not c.passed and c.name in CHECK_FAULT:
            refs = [r.strip() for r in c.detail.split(",") if r.strip() in checks.ids_of(pkg)]
            found.append(_finding(len(found) + 1, CHECK_FAULT[c.name], refs or cited, c.detail))
    for word in checks.forbidden_phrases(texts):
        if word in PHRASE_FAULT:
            found.append(_finding(len(found) + 1, PHRASE_FAULT[word], cited, word))
    for fault, sid in _input_faults(plan, pkg):
        found.append(_finding(len(found) + 1, fault, [sid], f"{sid} failed its quality check"))
    rule = policy.decide(pkg)
    if plan.decision not in rule.allowed:
        found += [_finding(len(found) + 1, f.fault_class, f.evidence, f.note) for f in rule.flags]
    if not found:
        return CritiqueV1(verdict="no_concern", findings=[])
    return CritiqueV1(verdict="concerns", findings=found[:4])


def score(
    case: CaseV1, crit: Critique | None, pkg: EvidencePackageV1, seeded: list[str]
) -> CaseScoreV1:
    if crit is None:
        return CaseScoreV1(
            case=case.id,
            label=case.label,
            usable=False,
            detected=False,
            high_on_clean=False,
            findings=0,
            unsupported=0,
        )
    backed = [f for f in crit.findings if not checks.finding_problems(f, pkg)]
    clean = case.label == "clean"
    raw = [f for f in crit.findings if not clean and f.fault_class.value == case.label]
    detected = any(f in backed and set(f.evidence) & set(seeded) for f in raw)
    return CaseScoreV1(
        case=case.id,
        label=case.label,
        usable=True,
        detected=detected,
        detected_raw=bool(raw),
        high_on_clean=clean and any(f.severity == "high" for f in crit.findings),
        findings=len(crit.findings),
        unsupported=len(crit.findings) - len(backed),
    )


def summary(scores: list[CaseScoreV1]) -> dict[str, Any]:
    faults = [s for s in scores if s.label != "clean"]
    clean = [s for s in scores if s.label == "clean"]
    findings = sum(s.findings for s in scores)
    return {
        "cases": len(scores),
        "usable": sum(s.usable for s in scores),
        "faults_detected": sum(s.detected for s in faults),
        "faults_detected_raw": sum(s.detected_raw for s in faults),
        "faults": len(faults),
        "clean_with_high_finding": sum(s.high_on_clean for s in clean),
        "clean_with_any_finding": sum(s.findings > 0 for s in clean),
        "clean": len(clean),
        "findings": findings,
        "unsupported_findings": sum(s.unsupported for s in scores),
    }


Critic = Callable[[CaseV1, EvidencePackageV1], Critique | None]


def run_bench(
    cases: list[CaseV1],
    packages: dict[str, EvidencePackageV1],
    critic: Critic,
    seeded: dict[str, list[str]],
) -> tuple[list[CaseScoreV1], dict[str, Any]]:
    scores = [
        score(c, critic(c, packages[c.package]), packages[c.package], seeded.get(c.id, []))
        for c in cases
    ]
    return scores, summary(scores)


def passes_gates(s: dict[str, Any], rules: dict[str, Any]) -> dict[str, bool]:
    """Engineering gates of protocol m41-v1, section 5, on evidence-backed detections."""
    findings = max(s["findings"], 1)
    return {
        "usable": s["usable"] >= 22,
        "detected": s["faults_detected"] >= 6 and s["faults_detected"] > rules["faults_detected"],
        "clean": s["clean_with_high_finding"] <= 3,
        "supported": s["unsupported_findings"] / findings <= 0.2,
    }


def choose_critic(summaries: dict[str, dict[str, Any]], muse: str) -> tuple[str | None, bool]:
    """The HC critic: best non-Muse model by the rule in the protocol. True when it passed."""
    rules = summaries["rules"]
    models = {k: v for k, v in summaries.items() if k not in ("rules", muse)}
    if not models:
        return None, False

    def rank(name: str) -> tuple[int, int]:
        s = models[name]
        return (s["faults_detected"], -s["unsupported_findings"])

    eligible = [
        k for k, v in models.items() if (g := passes_gates(v, rules))["usable"] and g["clean"]
    ]
    if eligible:
        return max(eligible, key=rank), True
    return max(models, key=rank), False

"""Decision policy m41-v1: the code rule for each scenario, written before any M4.1 run.

The rule reads package facts only. It returns the decisions that the evidence allows and the
rule flags that support them. The flags map to fault classes, so the rule is also the
deterministic critic (arm F). It does not read any model text.
"""

from __future__ import annotations

from collections.abc import Callable

from earthlab.assess.contracts import (
    Availability,
    Decision,
    EvidencePackageV1,
    FaultClass,
    FindingV1,
)
from earthlab.contracts import Strict

MIN_GAIN = 0.02  # a candidate must lower MAE by 2 percent to count as better
INPUT_ROLES = {"observation", "estimate", "reanalysis"}


class FlagV1(Strict):
    fault_class: FaultClass
    evidence: list[str]
    note: str


class PolicyResultV1(Strict):
    policy: str = "m41-v1"
    allowed: list[Decision]
    preferred: Decision
    flags: list[FlagV1]
    eligible_inputs: list[str]
    excluded_inputs: list[str]


def _v(pkg: EvidencePackageV1, fid: str) -> float | None:
    return next((f.value for f in pkg.facts if f.id == fid), None)


def _need(pkg: EvidencePackageV1, fid: str) -> float:
    value = _v(pkg, fid)
    if value is None:
        raise KeyError(f"{pkg.package_id}: fact {fid} is required by the policy")
    return value


def _inputs(pkg: EvidencePackageV1) -> tuple[list[str], list[str]]:
    usable: list[str] = []
    excluded: list[str] = []
    for s in pkg.sources:
        if s.role not in INPUT_ROLES:
            continue
        ok = s.availability is Availability.ISSUE_TIME_VALID
        (usable if ok else excluded).append(s.id)
    return usable, excluded


def _model_selection(pkg: EvidencePackageV1) -> tuple[list[Decision], list[FlagV1]]:
    base = _need(pkg, "b4.mae")
    cands = [f.id.split(".")[0] for f in pkg.facts if f.id.endswith(".mae")]
    cands = [c for c in cands if c not in ("b4", "persist")]
    better = [c for c in cands if _need(pkg, f"{c}.mae") <= base * (1 - MIN_GAIN)]
    flags = []
    persist = _need(pkg, "persist.mae_gt55")
    worse = [f"{c}.mae_gt55" for c in ["b4", *cands] if _need(pkg, f"{c}.mae_gt55") > persist]
    if worse:
        flags.append(
            FlagV1(
                fault_class=FaultClass.SUBGROUP_DETERIORATION,
                evidence=[*worse[:3], "persist.mae_gt55"],
                note="Models are worse than persistence above 55.",
            )
        )
    if better:
        flags.append(
            FlagV1(
                fault_class=FaultClass.NON_INDEPENDENT_EVIDENCE,
                evidence=["val.years", f"{better[0]}.mae"],
                note="The gain is on reused validation years.",
            )
        )
        return [Decision.REQUEST_VALIDATION, Decision.RETAIN_BASELINE], flags
    return [Decision.RETAIN_BASELINE, Decision.REQUEST_VALIDATION], flags


def _provenance(pkg: EvidencePackageV1) -> tuple[list[Decision], list[FlagV1]]:
    flags = []
    if _need(pkg, "nea.mismatched") > 0:
        flags.append(
            FlagV1(
                fault_class=FaultClass.PROVENANCE_CONFLICT,
                evidence=["nea.mismatched", "nea.mm_days"],
                note="API and file disagree; the cause is not in evidence.",
            )
        )
    if (_v(pkg, "file.conflicts") or 0) > 0 or (_v(pkg, "file.missing_region") or 0) > 0:
        flags.append(
            FlagV1(
                fault_class=FaultClass.MISSING_OBSERVATIONS,
                evidence=["file.conflicts", "file.missing_region"],
                note="The file has gaps and conflicting labels.",
            )
        )
    allowed = [Decision.PROCEED_WITH_LIMITS, Decision.REQUEST_DATA, Decision.REQUEST_VALIDATION]
    return allowed, flags


def _sufficiency(pkg: EvidencePackageV1) -> tuple[list[Decision], list[FlagV1]]:
    _, late = _inputs(pkg)
    flags = (
        [
            FlagV1(
                fault_class=FaultClass.HINDSIGHT_AS_FORECAST,
                evidence=late[:3],
                note="Hindsight inputs cannot support a T+6 prediction claim.",
            )
        ]
        if late
        else []
    )
    if _need(pkg, "abl.B3.mae") > _need(pkg, "abl.B0.mae"):
        flags.append(
            FlagV1(
                fault_class=FaultClass.INSUFFICIENT_EVIDENCE,
                evidence=["abl.B3.mae", "abl.B0.mae", "abl.days"],
                note="Added inputs made the error larger in one season.",
            )
        )
    return [Decision.ABSTAIN, Decision.REQUEST_DATA], flags


def _design(pkg: EvidencePackageV1) -> tuple[list[Decision], list[FlagV1]]:
    _, late = _inputs(pkg)
    flags = (
        [
            FlagV1(
                fault_class=FaultClass.HINDSIGHT_AS_FORECAST,
                evidence=late[:3],
                note="Not available at issue time.",
            )
        ]
        if late
        else []
    )
    if (_v(pkg, "hls.clear") or 1) < 0.1 or _v(pkg, "smap.rq") == 0:
        flags.append(
            FlagV1(
                fault_class=FaultClass.MISSING_OBSERVATIONS,
                evidence=["hls.clear", "smap.rq"],
                note="Quality checks leave too few usable values.",
            )
        )
    if (_v(pkg, "t19.R2_vs_R1.high") or 1) < 0:
        flags.append(
            FlagV1(
                fault_class=FaultClass.SUBGROUP_DETERIORATION,
                evidence=["t19.R2_vs_R1.skill", "t19.R2_vs_R1.high"],
                note="Fire inputs help elevated hours and hurt all hours.",
            )
        )
    return [Decision.PROCEED_WITH_LIMITS, Decision.REQUEST_VALIDATION], flags


RULES: dict[str, Callable[[EvidencePackageV1], tuple[list[Decision], list[FlagV1]]]] = {
    "model_selection": _model_selection,
    "provenance": _provenance,
    "sufficiency": _sufficiency,
    "design": _design,
}


def decide(pkg: EvidencePackageV1) -> PolicyResultV1:
    allowed, flags = RULES[pkg.scenario](pkg)
    usable, excluded = _inputs(pkg)
    if pkg.scenario == "design":
        excluded += [s.id for s in pkg.sources if s.availability is Availability.UNKNOWN]
        usable = [u for u in usable if u not in excluded]
    allowed = [d for d in allowed if d in pkg.allowed_decisions]
    return PolicyResultV1(
        allowed=allowed,
        preferred=allowed[0],
        flags=flags,
        eligible_inputs=usable,
        excluded_inputs=sorted(set(excluded)),
    )


def flags_as_findings(result: PolicyResultV1) -> list[FindingV1]:
    """The rule flags in the critic's format, for the matched critic comparison."""
    return [
        FindingV1(
            id=f"rule-{n}",
            fault_class=f.fault_class,
            claim=f.note,
            evidence=f.evidence,
            severity="high",
            action="clarify",
            uncertainty="Code rule m41-v1.",
        )
        for n, f in enumerate(result.flags, start=1)
        if f.evidence
    ]

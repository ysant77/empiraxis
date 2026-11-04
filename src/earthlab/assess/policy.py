"""Decision policy m41-v3: the code rule for each scenario.

The rule reads package facts only. It returns the decisions that the evidence allows and the
rule flags that support them. The flags map to fault classes, so the rule is also the
deterministic critic (arm F). It does not read any model text.

m41-v2 (correction of m41-v1): a value of 0 is a value, not a missing fact. A fact that is
absent or null goes to `missing_facts` and raises no flag. A flag cites only ids that exist
in the package.

m41-v3 (prospective, after the m41-v2 runs): in the design scenario, worse all-hour skill with
an elevated-hour gain is `overall_deterioration`, not `subgroup_deterioration`. Recorded m41-v2
results and keys are not changed.
"""

from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar

from pydantic import Field

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
# Design scenario: a source is suitable only when its essential quality measurement exists.
# A missing or null measurement makes the source ineligible; it never counts as a pass.
REQUIRED_QUALITY = {"hls": "hls.clear", "smap": "smap.rq"}


class FlagV1(Strict):
    fault_class: FaultClass
    evidence: list[str]
    note: str


class PolicyResultV1(Strict):
    policy: str = "m41-v3"
    allowed: list[Decision]
    preferred: Decision
    flags: list[FlagV1]
    eligible_inputs: list[str]
    excluded_inputs: list[str]
    missing_facts: list[str] = Field(default_factory=list)


class _Reader:
    """Fact values for one decision. Records every fact it needed and did not find."""

    def __init__(self, pkg: EvidencePackageV1):
        self.values = {f.id: f.value for f in pkg.facts}
        self.missing: list[str] = []

    def __call__(self, fid: str) -> float | None:
        value = self.values.get(fid)
        if value is None and fid not in self.missing:
            self.missing.append(fid)
        return value


_READ: ContextVar[_Reader | None] = ContextVar("policy_reader", default=None)


def _v(pkg: EvidencePackageV1, fid: str) -> float | None:
    reader = _READ.get()
    if reader is not None:
        return reader(fid)
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


def _by_availability(pkg: EvidencePackageV1, kind: Availability) -> list[str]:
    return [s.id for s in pkg.sources if s.role in INPUT_ROLES and s.availability is kind]


def _timing_flags(pkg: EvidencePackageV1, note: str) -> list[FlagV1]:
    """Hindsight inputs, and inputs whose time of availability is not established."""
    late = _by_availability(pkg, Availability.HINDSIGHT)
    unknown = _by_availability(pkg, Availability.UNKNOWN)
    flags = []
    if late:
        flags.append(
            FlagV1(fault_class=FaultClass.HINDSIGHT_AS_FORECAST, evidence=late[:3], note=note)
        )
    if unknown:
        flags.append(
            FlagV1(
                fault_class=FaultClass.MISSING_OBSERVATIONS,
                evidence=unknown[:3],
                note="When these values become available is not established.",
            )
        )
    return flags


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
    conflicts, gaps = _v(pkg, "file.conflicts"), _v(pkg, "file.missing_region")
    if (conflicts is not None and conflicts > 0) or (gaps is not None and gaps > 0):
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
    flags = _timing_flags(pkg, "Hindsight inputs cannot support a T+6 prediction claim.")
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
    flags = _timing_flags(pkg, "Not available at issue time.")
    clear, rq = _v(pkg, "hls.clear"), _v(pkg, "smap.rq")
    if (clear is not None and clear < 0.1) or (rq is not None and rq == 0):
        flags.append(
            FlagV1(
                fault_class=FaultClass.MISSING_OBSERVATIONS,
                evidence=["hls.clear", "smap.rq"],
                note="Quality checks leave too few usable values.",
            )
        )
    high = _v(pkg, "t19.R2_vs_R1.high")
    if high is not None and high < 0:
        flags.append(
            FlagV1(
                fault_class=FaultClass.OVERALL_DETERIORATION,
                evidence=["t19.R2_vs_R1.skill", "t19.R2_vs_R1.high"],
                note="Fire inputs make all-hour MAE worse; the elevated-hour gain is exploratory.",
            )
        )
    return [Decision.PROCEED_WITH_LIMITS, Decision.REQUEST_VALIDATION], flags


RULES: dict[str, Callable[[EvidencePackageV1], tuple[list[Decision], list[FlagV1]]]] = {
    "model_selection": _model_selection,
    "provenance": _provenance,
    "sufficiency": _sufficiency,
    "design": _design,
}


def _unmeasured(pkg: EvidencePackageV1) -> list[str]:
    """Input sources whose essential quality measurement is absent or null."""
    values = {f.id: f.value for f in pkg.facts}
    inputs = {s.id for s in pkg.sources if s.role in INPUT_ROLES}
    return [
        sid for sid, fid in REQUIRED_QUALITY.items() if sid in inputs and values.get(fid) is None
    ]


def _cited(flags: list[FlagV1], pkg: EvidencePackageV1) -> list[FlagV1]:
    known = {f.id for f in pkg.facts} | {s.id for s in pkg.sources}
    return [f.model_copy(update={"evidence": [e for e in f.evidence if e in known]}) for f in flags]


def decide(pkg: EvidencePackageV1) -> PolicyResultV1:
    reader = _Reader(pkg)
    token = _READ.set(reader)
    try:
        allowed, flags = RULES[pkg.scenario](pkg)
    finally:
        _READ.reset(token)
    missing = reader.missing
    flags = _cited(flags, pkg)
    usable, excluded = _inputs(pkg)
    if pkg.scenario == "design":
        excluded += [s.id for s in pkg.sources if s.availability is Availability.UNKNOWN]
        unmeasured = _unmeasured(pkg)
        excluded += unmeasured
        missing += [REQUIRED_QUALITY[u] for u in unmeasured if REQUIRED_QUALITY[u] not in missing]
        flags += [
            FlagV1(
                fault_class=FaultClass.MISSING_OBSERVATIONS,
                evidence=[u],
                note=f"Essential quality measurement {REQUIRED_QUALITY[u]} is missing.",
            )
            for u in unmeasured
        ]
        usable = [u for u in usable if u not in excluded]
    allowed = [d for d in allowed if d in pkg.allowed_decisions]
    return PolicyResultV1(
        allowed=allowed,
        preferred=allowed[0],
        flags=flags,
        eligible_inputs=usable,
        excluded_inputs=sorted(set(excluded)),
        missing_facts=missing,
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
            uncertainty="Code rule m41-v2.",
        )
        for n, f in enumerate(result.flags, start=1)
        if f.evidence
    ]

"""Typed burned-area claims and the submit_area_findings tool.

An area claim names a registered case, a UTC month, a quantity (mapped burned area in
hectares, or the valid-land fraction) and a value. The independent burned-area verifier
decides it with the pre-registered tolerances: the model never grades its own claims.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import Field

from earthlab.cases.tools import CaseLibrary
from earthlab.contracts import Strict
from earthlab.science.burned_area import QaPolicy
from earthlab.tools.burned_area_tools import METHOD_FILE, month_report
from earthlab.tools.registry import ToolSpec
from earthlab.verify.burned_area_check import MonthCheck, claim_verdict, load_tolerances
from earthlab.verify.claims import Check, Verdict
from earthlab.verify.language import language_violation

SUBMIT_AREA_TOOL = "submit_area_findings"
MAX_AREA_CLAIMS = 4
VALID_FRACTION_ABS_MAX = 0.001
_VERDICTS = {
    "supported_observation": Verdict.SUPPORTED,
    "contradicted": Verdict.CONTRADICTED,
    "insufficient_data": Verdict.INSUFFICIENT_DATA,
    "not_verified": Verdict.UNSUPPORTED,
}


class AreaQuantity(StrEnum):
    BURNED_AREA_HA = "burned_area_ha"
    VALID_FRACTION = "valid_fraction"


class AreaClaim(Strict):
    case_id: str = Field(min_length=1, max_length=80)
    month: str = Field(pattern=r"^\d{4}-\d{2}$", description="UTC calendar month, YYYY-MM.")
    quantity: AreaQuantity = Field(
        description="burned_area_ha: MCD64A1 mapped burned area in hectares after QA; "
        "valid_fraction: valid land / land in the study area (0 to 1)."
    )
    value: float = Field(ge=0)
    statement: str = Field(max_length=300, description="One plain sentence.")
    qa_policy: QaPolicy = Field(
        default=QaPolicy.PRIMARY, description="The QA policy the value was computed with."
    )

    @property
    def unit(self) -> str:
        return "ha" if self.quantity is AreaQuantity.BURNED_AREA_HA else "fraction"


class AreaVerification(Strict):
    claim: AreaClaim
    verdict: Verdict
    check: Check
    observed: float | None = None
    reason: str
    source_sha256: str | None = None


def verify_area_claim(claim: AreaClaim, library: CaseLibrary) -> AreaVerification:
    """Decide one area claim with the independent verifier; fail closed on any error."""
    reason = language_violation(claim.statement)
    if reason is not None:
        return AreaVerification(
            claim=claim, verdict=Verdict.UNSUPPORTED, check=Check.LANGUAGE, reason=reason
        )
    try:
        report = month_report(
            library.get(claim.case_id), library.root, claim.month, claim.qa_policy
        )
    except (ValueError, OSError, RuntimeError, StopIteration) as exc:
        return AreaVerification(
            claim=claim, verdict=Verdict.INSUFFICIENT_DATA, check=Check.SOURCE, reason=str(exc)
        )
    check = MonthCheck.model_validate(report["check"])
    sha = report["source"]["sha256"]
    if claim.quantity is AreaQuantity.VALID_FRACTION:
        observed = check.verifier_valid_fraction
        ok = abs(claim.value - observed) <= VALID_FRACTION_ABS_MAX and check.passed
        verdict = Verdict.SUPPORTED if ok else Verdict.CONTRADICTED
        text = f"recomputed valid fraction is {observed:.3f}"
        return AreaVerification(
            claim=claim,
            verdict=verdict,
            check=Check.COVERAGE,
            observed=observed,
            reason=text,
            source_sha256=sha,
        )
    tol = load_tolerances(library.root / METHOD_FILE)
    status, text = claim_verdict(claim.value, check, tol)
    return AreaVerification(
        claim=claim,
        verdict=_VERDICTS[status],
        check=Check.COVERAGE if status == "insufficient_data" else Check.VALUE,
        observed=round(check.verifier_area_m2 / 1e4, 1),
        reason=text,
        source_sha256=sha,
    )


@dataclass
class AreaLedger:
    """Every area verdict from every submission, in order. Nothing is ever removed."""

    rounds: list[list[AreaVerification]] = field(default_factory=list)
    consulted: list[tuple[str, str]] = field(default_factory=list)  # (case_id, month) read
    gate_notes: list[str] = field(default_factory=list)  # plan-review coverage refusals

    @property
    def latest(self) -> list[AreaVerification]:
        return self.rounds[-1] if self.rounds else []

    def all_supported(self) -> bool:
        return bool(self.latest) and all(r.verdict is Verdict.SUPPORTED for r in self.latest)

    def supported(self) -> list[AreaVerification]:
        return [r for r in self.latest if r.verdict is Verdict.SUPPORTED]

    def covers_quality(self) -> bool:
        """True when a supported claim states the valid-data fraction."""
        return any(r.claim.quantity.value == "valid_fraction" for r in self.supported())

    def rejected(self) -> list[AreaVerification]:
        return [r for rnd in self.rounds for r in rnd if r.verdict is not Verdict.SUPPORTED]

    def latest_by_id(self) -> dict[str, AreaVerification]:
        number = len(self.rounds)
        return {f"A{number}.{i}": r for i, r in enumerate(self.latest, start=1)}

    def records(self) -> list[dict[str, Any]]:
        return [
            {
                "id": finding_id,
                **r.claim.model_dump(mode="json"),
                "unit": r.claim.unit,
                "observed": r.observed,
                "verdict": r.verdict.value,
                "check": r.check.value,
                "reason": r.reason,
                "source_sha256": r.source_sha256,
            }
            for finding_id, r in self.latest_by_id().items()
        ]


class SubmitAreaArgs(Strict):
    claims: list[AreaClaim] = Field(min_length=1, max_length=MAX_AREA_CLAIMS)


def submit_area_findings_spec(library: CaseLibrary, ledger: AreaLedger) -> ToolSpec:
    def handle(args: SubmitAreaArgs) -> dict[str, Any]:
        ledger.rounds.append([verify_area_claim(c, library) for c in args.claims])
        return {
            "round": len(ledger.rounds),
            "all_supported": ledger.all_supported(),
            "verdicts": [
                {
                    "id": i,
                    "quantity": r.claim.quantity.value,
                    "qa_policy": r.claim.qa_policy.value,
                    "month": r.claim.month,
                    "verdict": r.verdict.value,
                    "observed": r.observed,
                    "reason": r.reason,
                }
                for i, r in ledger.latest_by_id().items()
            ],
        }

    return ToolSpec(
        SUBMIT_AREA_TOOL,
        "Submit typed burned-area claims for a registered case. An independent verifier "
        "recomputes each from the pinned MCD64A1 files with pre-registered tolerances.",
        SubmitAreaArgs,
        handle,
    )

"""The submit_findings tool: the only path from model claims to the verifier."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.tools.registry import ToolSpec
from earthlab.verify.claims import Claim, Verdict, VerificationResult
from earthlab.verify.verifier import Verifier

MAX_CLAIMS = 8
SUBMIT_TOOL = "submit_findings"


class SubmitArgs(Strict):
    claims: list[Claim] = Field(max_length=MAX_CLAIMS, description="Typed, checkable claims.")


def _covers(claims: list[Claim], start: datetime, end: datetime) -> bool:
    reached = start
    for claim in sorted(claims, key=lambda c: c.start):
        if claim.start > reached:
            break
        reached = max(reached, claim.end)
    return reached >= end


@dataclass
class FindingsLedger:
    """Every verdict from every submission, in order. Nothing is ever removed."""

    rounds: list[list[VerificationResult]] = field(default_factory=list)

    @property
    def latest(self) -> list[VerificationResult]:
        return self.rounds[-1] if self.rounds else []

    def spans(self, start: datetime, end: datetime) -> bool:
        """True when one series of supported claims covers this window with no gap.

        A series is one kind, region and threshold. Claims about different regions or
        thresholds are different quantities, so together they cover nothing.
        """
        series: defaultdict[Hashable, list[Claim]] = defaultdict(list)
        for result in self.supported():
            claim = result.claim
            series[claim.kind, claim.region, claim.threshold].append(claim)
        return any(_covers(claims, start, end) for claims in series.values())

    def all_supported(self) -> bool:
        latest = self.latest
        return bool(latest) and all(r.verdict is Verdict.SUPPORTED for r in latest)

    def rejected(self) -> list[VerificationResult]:
        return [r for rnd in self.rounds for r in rnd if r.verdict is not Verdict.SUPPORTED]

    def supported(self) -> list[VerificationResult]:
        return [r for r in self.latest if r.verdict is Verdict.SUPPORTED]

    def latest_by_id(self) -> dict[str, VerificationResult]:
        """The latest submission keyed by finding ID R<round>.<n>, as the model sees it."""
        number = len(self.rounds)
        return {f"R{number}.{i}": r for i, r in enumerate(self.latest, start=1)}

    def records(self, source_sha256: str) -> list[dict[str, Any]]:
        """The latest submission as report rows; ID R<round>.<n> is stable for one run."""
        return [
            {
                "id": finding_id,
                "kind": r.claim.kind.value,
                "region": r.claim.region.value,
                "start": r.claim.start.isoformat(),
                "end": r.claim.end.isoformat(),
                "value": r.claim.value,
                "threshold": r.claim.threshold,
                "unit": r.claim.unit,
                "observed": r.observed,
                "check": r.check.value,
                "verdict": r.verdict.value,
                "source_sha256": source_sha256,
            }
            for finding_id, r in self.latest_by_id().items()
        ]


def submit_findings_spec(verifier: Verifier, ledger: FindingsLedger) -> ToolSpec:
    def handle(args: SubmitArgs) -> dict[str, Any]:
        results = verifier.verify_all(args.claims)
        ledger.rounds.append(results)
        return {
            "round": len(ledger.rounds),
            "all_supported": ledger.all_supported(),
            "verdicts": [
                {
                    "id": finding_id,
                    "kind": r.claim.kind.value,
                    "region": r.claim.region.value,
                    "verdict": r.verdict.value,
                    "observed": r.observed,
                    "reason": r.reason,
                }
                for finding_id, r in ledger.latest_by_id().items()
            ],
        }

    return ToolSpec(
        SUBMIT_TOOL,
        "Submit typed claims. An independent verifier recomputes each claim from the raw "
        "source and returns supported, contradicted, unsupported or insufficient_data.",
        SubmitArgs,
        handle,
    )

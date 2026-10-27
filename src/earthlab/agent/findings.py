"""The submit_findings tool: the only path from model claims to the verifier."""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class FindingsLedger:
    """Every verdict from every submission, in order. Nothing is ever removed."""

    rounds: list[list[VerificationResult]] = field(default_factory=list)

    @property
    def latest(self) -> list[VerificationResult]:
        return self.rounds[-1] if self.rounds else []

    def all_supported(self) -> bool:
        latest = self.latest
        return bool(latest) and all(r.verdict is Verdict.SUPPORTED for r in latest)

    def rejected(self) -> list[VerificationResult]:
        return [r for rnd in self.rounds for r in rnd if r.verdict is not Verdict.SUPPORTED]

    def supported(self) -> list[VerificationResult]:
        return [r for r in self.latest if r.verdict is Verdict.SUPPORTED]

    def records(self, source_sha256: str) -> list[dict[str, Any]]:
        """The latest submission as report rows; ID R<round>.<n> is stable for one run."""
        number = len(self.rounds)
        return [
            {
                "id": f"R{number}.{i}",
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
            for i, r in enumerate(self.latest, start=1)
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
                    "kind": r.claim.kind.value,
                    "region": r.claim.region.value,
                    "verdict": r.verdict.value,
                    "observed": r.observed,
                    "reason": r.reason,
                }
                for r in results
            ],
        }

    return ToolSpec(
        SUBMIT_TOOL,
        "Submit typed claims. An independent verifier recomputes each claim from the raw "
        "source and returns supported, contradicted, unsupported or insufficient_data.",
        SubmitArgs,
        handle,
    )

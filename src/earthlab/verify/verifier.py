"""Deterministic claim verifier. A model never grades its own claims; this code does."""

from __future__ import annotations

from collections.abc import Callable

from earthlab.contracts import ALL_REGIONS
from earthlab.verify.claims import Check, Claim, ClaimKind, Verdict, VerificationResult
from earthlab.verify.language import language_violation
from earthlab.verify.recompute import IndependentSource

MAX_MISSING_FRACTION = 0.25
MEAN_TOLERANCE = 0.05 + 1e-9
EXACT_TOLERANCE = 1e-9


def _result(
    claim: Claim, verdict: Verdict, check: Check, observed: float | str | None, reason: str
) -> VerificationResult:
    return VerificationResult(
        claim=claim, verdict=verdict, check=check, observed=observed, reason=reason
    )


def _compare(claim: Claim, observed: float, tolerance: float, what: str) -> VerificationResult:
    assert claim.value is not None  # guaranteed by Claim validation
    if abs(observed - claim.value) <= tolerance:
        return _result(claim, Verdict.SUPPORTED, Check.VALUE, observed, f"{what} matches source")
    return _result(
        claim,
        Verdict.CONTRADICTED,
        Check.VALUE,
        observed,
        f"source {what} is {observed:g}, claim says {claim.value:g}",
    )


class Verifier:
    def __init__(self, source: IndependentSource):
        self._source = source
        self._checks: dict[ClaimKind, Callable[[Claim], VerificationResult]] = {
            ClaimKind.REGION_MAX: self._region_max,
            ClaimKind.REGION_MEAN: self._region_mean,
            ClaimKind.PEAK_REGION: self._peak_region,
            ClaimKind.MISSING_HOURS: self._missing_hours,
            ClaimKind.HOURS_ABOVE: self._hours_above,
        }

    def verify(self, claim: Claim) -> VerificationResult:
        reason = language_violation(claim.statement)
        if reason is not None:
            return _result(claim, Verdict.UNSUPPORTED, Check.LANGUAGE, None, reason)
        if claim.kind is not ClaimKind.MISSING_HOURS:
            gap = self._coverage_gap(claim)
            if gap is not None:
                return gap
        return self._checks[claim.kind](claim)

    def verify_all(self, claims: list[Claim]) -> list[VerificationResult]:
        return [self.verify(claim) for claim in claims]

    def _coverage_gap(self, claim: Claim) -> VerificationResult | None:
        regions = ALL_REGIONS if claim.kind is ClaimKind.PEAK_REGION else (claim.region,)
        for region in regions:
            pairs, expected = self._source.series(region, claim.window)
            missing = expected - len(pairs)
            if expected == 0 or missing / expected > MAX_MISSING_FRACTION:
                return _result(
                    claim,
                    Verdict.INSUFFICIENT_DATA,
                    Check.COVERAGE,
                    float(missing),
                    f"{region}: {missing} of {expected} hours missing; too few to support a claim",
                )
        return None

    def _region_max(self, claim: Claim) -> VerificationResult:
        pairs, _ = self._source.series(claim.region, claim.window)
        peak = max(value for _, value in pairs)
        result = _compare(claim, peak, EXACT_TOLERANCE, "maximum")
        if result.verdict is Verdict.SUPPORTED and claim.at is not None:
            claimed_hour = claim.at.replace(tzinfo=None)  # already Singapore time
            peak_hours = {h for h, v in pairs if v == peak}
            if claimed_hour not in peak_hours:
                first = min(peak_hours).isoformat()
                return _result(
                    claim, Verdict.CONTRADICTED, Check.VALUE, first, f"maximum occurs at {first}"
                )
        return result

    def _region_mean(self, claim: Claim) -> VerificationResult:
        pairs, _ = self._source.series(claim.region, claim.window)
        mean = sum(v for _, v in pairs) / len(pairs)
        return _compare(claim, round(mean, 2), MEAN_TOLERANCE, "mean")

    def _peak_region(self, claim: Claim) -> VerificationResult:
        peaks = {r: max(v for _, v in self._source.series(r, claim.window)[0]) for r in ALL_REGIONS}
        best = max(peaks.values())
        winners = sorted(r.value for r, v in peaks.items() if v == best)
        observed = f"{'/'.join(winners)} at {best:g}"
        if claim.region.value not in winners:
            return _result(
                claim, Verdict.CONTRADICTED, Check.VALUE, observed, f"highest region is {observed}"
            )
        if claim.value is not None and abs(claim.value - best) > EXACT_TOLERANCE:
            return _result(
                claim, Verdict.CONTRADICTED, Check.VALUE, observed, f"peak value is {best:g}"
            )
        return _result(claim, Verdict.SUPPORTED, Check.VALUE, observed, "region has the peak")

    def _missing_hours(self, claim: Claim) -> VerificationResult:
        pairs, expected = self._source.series(claim.region, claim.window)
        return _compare(claim, float(expected - len(pairs)), EXACT_TOLERANCE, "missing-hour count")

    def _hours_above(self, claim: Claim) -> VerificationResult:
        assert claim.threshold is not None  # guaranteed by Claim validation
        pairs, _ = self._source.series(claim.region, claim.window)
        count = sum(1 for _, v in pairs if v > claim.threshold)
        return _compare(claim, float(count), EXACT_TOLERANCE, "hours-above count")

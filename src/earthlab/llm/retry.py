"""Retry policy for one model call: at most one more attempt after a transient failure.

Only failures in `RETRYABLE` (rate limit, HTTP 5xx, timeout, transport) are retried.
Authentication, bad-request and malformed-response failures never are. A model call has
no side effect in EarthLab: tools run only after a reply arrives, so a retry can never
run a tool twice. The loop still checks every budget limit before the second attempt.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from earthlab.llm.types import RETRYABLE, ProviderError


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 2
    delay_seconds: float = 2.0
    max_delay_seconds: float = 10.0  # caps a provider's Retry-After header

    def __post_init__(self) -> None:
        if not 1 <= self.max_attempts <= 2:
            raise ValueError("max_attempts must be 1 or 2: one retry at most")
        if self.delay_seconds < 0 or self.max_delay_seconds < 0:
            raise ValueError("retry delays cannot be negative")

    def retries(self, error: ProviderError, attempt: int) -> bool:
        return error.kind in RETRYABLE and attempt < self.max_attempts

    def delay(self, error: ProviderError) -> float:
        wanted = self.delay_seconds if error.retry_after is None else error.retry_after
        return min(wanted, self.max_delay_seconds)

    def record(self) -> dict[str, Any]:
        """What the trace stores, so a run states the policy it ran under."""
        return {
            "max_attempts": self.max_attempts,
            "retry_on": sorted(kind.value for kind in RETRYABLE),
            "delay_seconds": self.delay_seconds,
            "max_delay_seconds": self.max_delay_seconds,
        }


NO_RETRY = RetryPolicy(max_attempts=1)

"""Prometheus metrics for real inference, tool use and verification.

Labels are bounded: provider and model come from config, tools from the registry,
checks and outcomes from enums. No prompt text, run ID, hash, URL or error text is
ever a label value; those belong in the run trace.
"""

from __future__ import annotations

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    start_http_server,
)

DURATION_BUCKETS = (0.5, 1, 2, 5, 10, 20, 30, 60, 120, 300, 600, 1200)
UNKNOWN = "unknown"


class EarthlabMetrics:
    def __init__(
        self, registry: CollectorRegistry | None = None, tool_names: set[str] | None = None
    ):
        self.registry = registry or CollectorRegistry()
        self._tool_names = tool_names or set()
        self.inference_requests = self._counter(
            "inference_requests", "Provider requests, including errors", "provider model outcome"
        )
        self.inference_duration = Histogram(
            "earthlab_inference_duration_seconds",
            "Wall time of one provider request",
            ["provider", "model"],
            buckets=DURATION_BUCKETS,
            registry=self.registry,
        )
        self.inference_tokens = self._counter(
            "inference_tokens", "Tokens reported by the provider", "provider model direction"
        )
        self.estimated_cost = self._counter(
            "inference_estimated_cost_usd", "Estimate from a dated price table", "provider model"
        )
        self.tools = self._counter("tools", "Tool calls by outcome", "tool outcome")
        self.verifications = self._counter(
            "verifications", "Deterministic verifier verdicts", "check outcome"
        )
        self.data_qa_issues = self._counter(
            "data_qa_issues", "Data-quality issues found at load", "source category"
        )
        self.safety_checks = self._counter(
            "safety_checks", "Safety gate decisions", "stage source outcome"
        )
        self.investigations = self._counter(
            "investigations", "Finished investigations by outcome", "outcome"
        )
        self.active = Gauge(
            "earthlab_active_investigations", "Investigations in progress", registry=self.registry
        )

    def _counter(self, name: str, documentation: str, labels: str) -> Counter:
        return Counter(f"earthlab_{name}", documentation, labels.split(), registry=self.registry)

    def tool_label(self, name: str) -> str:
        return name if name in self._tool_names else UNKNOWN

    def record_inference(
        self,
        provider: str,
        model: str,
        outcome: str,
        seconds: float | None,
        tokens: tuple[int | None, int | None] = (None, None),
        cost_usd: float | None = None,
    ) -> None:
        """Count every request; observe duration only when a response was timed.

        A failed request has no response time, so it is counted, not observed.
        """
        self.inference_requests.labels(provider, model, outcome).inc()
        if seconds is not None:
            self.inference_duration.labels(provider, model).observe(seconds)
        for direction, count in zip(("input", "output"), tokens, strict=True):
            if count is not None:
                self.inference_tokens.labels(provider, model, direction).inc(count)
        if cost_usd is not None:
            self.estimated_cost.labels(provider, model).inc(cost_usd)

    def record_tool(self, name: str, outcome: str) -> None:
        self.tools.labels(self.tool_label(name), outcome).inc()

    def record_verification(self, check: str, outcome: str) -> None:
        self.verifications.labels(check, outcome).inc()

    def record_safety(self, stage: str, source: str, outcome: str) -> None:
        self.safety_checks.labels(stage, source, outcome).inc()

    def record_qa(self, source: str, counts: dict[str, int]) -> None:
        for category, count in counts.items():
            self.data_qa_issues.labels(source, category).inc(count)

    def exposition(self) -> str:
        return generate_latest(self.registry).decode("utf-8")

    def serve(self, port: int, addr: str = "127.0.0.1") -> None:
        """Expose /metrics on localhost only by default; never on a public interface."""
        start_http_server(port, addr=addr, registry=self.registry)

"""A final answer rendered only from verified findings and typed limitations.

When the model's text still fails the answer audit after its one revision, the runtime
shows this text instead. Every value, unit and date comes from a supported finding as the
verifier recomputed it; no model sentence is copied. The withheld model text stays in the
trace.
"""

from __future__ import annotations

from collections.abc import Sequence

from earthlab.agent.area_findings import AreaLedger
from earthlab.agent.findings import FindingsLedger
from earthlab.agent.limitations import LimitationArgs
from earthlab.verify.claims import Verdict

_KINDS = {
    "region_max": "highest hourly PM2.5",
    "region_mean": "mean hourly PM2.5",
    "peak_region": "region with the highest hourly PM2.5",
    "missing_hours": "missing hours",
    "hours_above": "hours above the threshold",
}


def _pm25_lines(ledger: FindingsLedger) -> list[str]:
    lines = []
    for finding_id, r in ledger.latest_by_id().items():
        if r.verdict is not Verdict.SUPPORTED:
            continue
        c = r.claim
        what = _KINDS.get(c.kind.value, c.kind.value)
        above = f" (threshold {c.threshold:g} {c.unit})" if c.threshold is not None else ""
        window = f"{c.start.isoformat()} to {c.end.isoformat()} (end excluded)"
        lines.append(
            f"- {finding_id}: {what}{above}, {c.region.value} region, {window}: {r.observed}"
            + ("" if c.kind.value == "peak_region" else f" {c.unit}")
        )
    return lines


def _area_lines(area: AreaLedger) -> list[str]:
    lines = []
    for finding_id, r in area.latest_by_id().items():
        if r.verdict is not Verdict.SUPPORTED:
            continue
        c = r.claim
        lines.append(
            f"- {finding_id}: {c.quantity.value}, case {c.case_id}, month {c.month} UTC, "
            f"QA policy {c.qa_policy.value}: {r.observed} {c.unit}"
        )
    return lines


def render_answer(
    ledger: FindingsLedger, area: AreaLedger, limitations: Sequence[LimitationArgs]
) -> str | None:
    """The rendered answer, or None when there is no verified finding and no limitation."""
    findings = _pm25_lines(ledger) + _area_lines(area)
    codes = sorted({code.value for entry in limitations for code in entry.reasons})
    if not findings and not codes:
        return None
    parts = []
    if findings:
        parts.append("Verified findings (recomputed by the independent verifier):")
        parts += findings
    if codes:
        parts.append("Declared limitations: " + ", ".join(codes) + ".")
    parts.append(
        "The model's own summary did not pass the answer check, so it is not shown. "
        "Only the values above are verified."
    )
    return "\n".join(parts)

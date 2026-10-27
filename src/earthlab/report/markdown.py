"""Render a saved run (result.json) as an evidence report in Markdown."""

from __future__ import annotations

from typing import Any

LIMITATIONS = (
    "Observations only. The report makes no claim about what caused the haze.",
    "Values are NEA regional aggregates, not station measurements.",
    "PM2.5 is not PSI or AQI; the report does not compare them.",
    "Research prototype. Not health advice, not a forecast, not a hazard warning.",
)


def _claims_table(rows: list[dict[str, Any]]) -> list[str]:
    if not rows:
        return ["_None._", ""]
    lines = [
        "| Kind | Region | Claimed | Observed | Verdict | Reason |",
        "|---|---|---|---|---|---|",
    ]
    for r in rows:
        claim = r["claim"]
        claimed = claim.get("value")
        lines.append(
            f"| {claim['kind']} | {claim['region']} | {'' if claimed is None else claimed} | "
            f"{'' if r.get('observed') is None else r['observed']} | **{r['verdict']}** | "
            f"{r['reason']} |"
        )
    return [*lines, ""]


def _audit_lines(audit: dict[str, Any] | None) -> list[str]:
    if audit is None:
        return []
    if not audit["ungrounded"]:
        return [f"_Answer audit: all {audit['numbers_checked']} numbers trace to tool output._", ""]
    numbers = ", ".join(f"{n:g}" for n in audit["ungrounded"])
    return [f"**Answer audit: numbers not found in any tool output: {numbers}.**", ""]


def _safety_lines(decisions: list[dict[str, Any]]) -> list[str]:
    if not decisions:
        return []
    lines = ["## Safety checks", ""]
    for d in decisions:
        verdict = "allowed" if d["allowed"] else f"blocked by {d['blocked_by']}: {d['reason']}"
        lines.append(f"- {d['stage']}: {verdict}. Llama Guard: {d.get('guard') or 'not run'}")
    return [*lines, ""]


def _provenance_lines(result: dict[str, Any]) -> list[str]:
    src = result["source"]
    cost = result["estimated_cost_usd"]
    return [
        "## Model and run",
        "",
        f"- Provider: `{result['provider']}`; model: `{result['model']}`; "
        f"served model: `{result['served_model']}`",
        f"- Turns: {result['turns']}; tool calls: {result['tool_calls']}; "
        f"submissions: {result['submissions']}; wall time: {result['seconds']:.1f} s",
        f"- Tokens reported: {result['prompt_tokens']} input, {result['completion_tokens']} output",
        f"- Estimated cost: {'not priced' if cost is None else f'{cost:.6f} USD (estimate)'}",
        "",
        "## Source",
        "",
        f"- Dataset: {src['source_url']}",
        f"- SHA-256: `{src['sha256']}`",
        f"- Unit: {src['unit']}; time zone: {src['timezone']}; licence: {src['licence']}",
        f"- {result['attribution']}",
        "",
        "## Limitations",
        "",
        *[f"- {item}" for item in LIMITATIONS],
        "",
    ]


def render_report(result: dict[str, Any], chart_name: str | None = None) -> str:
    rounds: list[list[dict[str, Any]]] = result["rounds"]
    latest = rounds[-1] if rounds else []
    supported = [r for r in latest if r["verdict"] == "supported"]
    rejected = [r for rnd in rounds for r in rnd if r["verdict"] != "supported"]
    lines = [
        "# Axiom EarthLab evidence report",
        "",
        f"**Question:** {result['question']}",
        "",
        f"**Status:** `{result['status']}` ({result['stop_reason']})",
        "",
        "## Answer",
        "",
        result["answer"] or "_The model gave no final answer._",
        "",
        *_audit_lines(result.get("answer_audit")),
        "## Verified claims (latest submission)",
        "",
        *_claims_table(supported),
        "## Rejected claims (all submissions)",
        "",
        *_claims_table(rejected),
    ]
    if chart_name:
        lines += ["## Observed data", "", f"![Hourly regional PM2.5]({chart_name})", ""]
    lines += _safety_lines(result.get("safety", []))
    lines += _provenance_lines(result)
    return "\n".join(lines)

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


def _findings_table(rows: list[dict[str, Any]]) -> list[str]:
    """Supported claims only, rendered from the ledger, never from model prose."""
    supported = [r for r in rows if r["verdict"] == "supported"]
    if not supported:
        return ["_No supported findings._", ""]
    lines = [
        "| ID | Kind | Region | Window (SGT, end excluded) | Value | Unit | Check | Source |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in supported:
        value = "" if r["value"] is None else f"{r['value']:g}"
        if r["threshold"] is not None:
            value += f" (above {r['threshold']:g})"
        lines.append(
            f"| {r['id']} | {r['kind']} | {r['region']} | {r['start']} to {r['end']} | "
            f"{value or r['observed']} | {r['unit']} | {r['check']} | "
            f"`{r['source_sha256'][:12]}` |"
        )
    return [*lines, ""]


def _interpretation_lines(result: dict[str, Any]) -> list[str]:
    lines = ["## Interpretation (model text)", ""]
    issues: list[str] = result.get("answer_issues", [])
    if issues:
        lines += [
            "**NOT VERIFIED.** This text failed the evidence check. Use the Findings table.",
            "",
            *[f"- {issue}" for issue in issues],
            "",
        ]
    lines += [result["answer"] or "_The model gave no final answer._", ""]
    audit = result.get("answer_audit")
    if audit is not None and not issues:
        lines += [
            f"_Answer check: all {audit['numbers_checked']} numbers match a supported claim "
            "for the same region._",
            "",
        ]
    return lines


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
    rejected = [r for rnd in rounds for r in rnd if r["verdict"] != "supported"]
    lines = [
        "# Axiom EarthLab evidence report",
        "",
        f"**Question:** {result['question']}",
        "",
        f"**Status:** `{result['status']}` ({result['stop_reason']})",
        "",
        "## Findings (verified claims)",
        "",
        *_findings_table(result.get("findings", [])),
        *_interpretation_lines(result),
        "## Rejected claims (all submissions)",
        "",
        *_claims_table(rejected),
    ]
    if chart_name:
        lines += ["## Observed data", "", f"![Hourly regional PM2.5]({chart_name})", ""]
    lines += _safety_lines(result.get("safety", []))
    lines += _provenance_lines(result)
    return "\n".join(lines)

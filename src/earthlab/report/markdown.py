"""Render a saved run (result.json) as an evidence report in Markdown."""

from __future__ import annotations

from typing import Any

from earthlab.report.area_sections import (
    AREA_LIMITATIONS,
    check_lines,
    declared_lines,
    input_lines,
)

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
    if result.get("answer_audit") is not None and not issues:
        lines += [
            "_Answer check passed: no numbers or dates in the text; every cited finding is "
            "supported; no superlative or comparison goes beyond the findings._",
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


def _uses_pm25(result: dict[str, Any]) -> bool:
    """PM2.5 sections apply unless the run is about burned area only."""
    return bool(result["rounds"]) or not result.get("evidence")


def _source_lines(result: dict[str, Any]) -> list[str]:
    if not _uses_pm25(result):
        return []
    src = result["source"]
    return [
        "## Source",
        "",
        f"- Dataset: {src['source_url']}",
        f"- SHA-256: `{src['sha256']}`",
        f"- Unit: {src['unit']}; time zone: {src['timezone']}; licence: {src['licence']}",
        f"- {result['attribution']}",
        "",
    ]


def _limitation_lines(result: dict[str, Any]) -> list[str]:
    items = list(AREA_LIMITATIONS) if result.get("evidence") else []
    if _uses_pm25(result):
        items += LIMITATIONS
    return ["## Limitations", "", *[f"- {item}" for item in items], ""]


def _provenance_lines(result: dict[str, Any]) -> list[str]:
    cost = result["estimated_cost_usd"]
    return [
        "## Model and run",
        "",
        f"- Provider: `{result['provider']}`; model: `{result['model']}`; "
        f"served model: `{result['served_model']}`",
        f"- Turns: {result['turns']}; tool calls: {result['tool_calls']}; "
        f"submissions: {result['submissions']}; "
        f"skipped by limits: {result.get('skipped_tool_calls', 0)}; "
        f"wall time: {result['seconds']:.1f} s",
        f"- Tokens reported: {result['prompt_tokens']} input, {result['completion_tokens']} output",
        f"- Estimated cost: {'not priced' if cost is None else f'{cost:.6f} USD (estimate)'}",
        "",
        *_source_lines(result),
        *input_lines(result.get("evidence")),
        *_limitation_lines(result),
    ]


def _quantity(row: dict[str, Any]) -> str:
    policy = row.get("qa_policy", "primary")
    return row["quantity"] if policy == "primary" else f"{row['quantity']} (QA {policy})"


def _area_table(rows: list[dict[str, Any]]) -> list[str]:
    """Burned-area claims with every verdict: supported, contradicted or insufficient_data."""
    if not rows:
        return []
    lines = [
        "## Burned-area findings (MCD64A1, independent verifier)",
        "",
        "| ID | Case | Month (UTC) | Quantity | Claimed | Recomputed | Verdict | Reason | Source |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        source = f"`{r['source_sha256'][:12]}`" if r.get("source_sha256") else ""
        lines.append(
            f"| {r['id']} | {r['case_id']} | {r['month']} | {_quantity(r)} | {r['value']:g} "
            f"{r['unit']} | {'' if r['observed'] is None else r['observed']} | "
            f"**{r['verdict']}** | {r['reason']} | {source} |"
        )
    return [*lines, ""]


def render_report(
    result: dict[str, Any], chart_name: str | None = None, maps: dict[str, str] | None = None
) -> str:
    """maps: month -> image file name of a burned-area quick-look map in the run folder."""
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
        *_area_table(result.get("area_findings", [])),
        *check_lines(result.get("evidence")),
        *[f"![Burned-area map {month}]({name})\n" for month, name in (maps or {}).items()],
        *declared_lines(result.get("limitations", [])),
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

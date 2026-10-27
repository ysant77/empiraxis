"""Markdown sections for burned-area runs: verifier checks, FIRMS context, inputs, limitations.

Everything here is rendered from the evidence record in result.json, never from model text.
"""

from __future__ import annotations

from typing import Any

AREA_LIMITATIONS = (
    "MCD64A1 maps burned area at 500 m resolution. It is not forest loss, destroyed trees "
    "or emissions.",
    "FIRMS detections are thermal anomalies at satellite overpass time. They are context "
    "only and not burned area.",
    "A month whose valid-land fraction is below the pre-registered gate is not reported.",
    "The report makes no claim about what caused the fires or who is responsible.",
)


def _ok(value: bool) -> str:
    return "pass" if value else "**fail**"


def _check_row(m: dict[str, Any]) -> str:
    if "error" in m:
        return f"| {m['case_id']} | {m['month']} | not read: {m['error']} | | | | | | |"
    c = m["check"]
    area = f"{m['area_ha']:g}" if c["gate_ok"] else "not reported (gate)"
    return (
        f"| {m['case_id']} | {m['month']} | {area} | {m['valid_fraction']:.3f} | "
        f"{_ok(c['c1_count_ok'])} | {_ok(c['c2_per_pixel_area_ok'])} | "
        f"{_ok(c['c3_tool_vs_verifier_ok'])} | {_ok(c['gate_ok'])} | {'; '.join(c['notes'])} |"
    )


def check_lines(evidence: dict[str, Any] | None) -> list[str]:
    """One row per month the run read or claimed, then FIRMS counts labelled as context."""
    if not evidence:
        return []
    months = evidence["months"]
    lines = [
        "## Verifier checks (MCD64A1)",
        "",
        "| Case | Month (UTC) | Area (ha) | Valid fraction | C1 count vs EE | C2 pixel area "
        "| C3 tool vs verifier | Gate | Notes |",
        "|---|---|---|---|---|---|---|---|---|",
        *[_check_row(m) for m in months],
        "",
    ]
    counted = [m for m in months if m.get("firms_detections") is not None]
    if counted:
        lines += ["FIRMS active-fire detections in the box (context only, not burned area):", ""]
        lines += [f"- {m['month']}: {m['firms_detections']} detections" for m in counted]
        lines.append("")
    return lines


def input_lines(evidence: dict[str, Any] | None) -> list[str]:
    if not evidence:
        return []
    rows = [f"- `{path}`: `{sha[:16]}`" for path, sha in evidence["files"].items()]
    return [
        "## Burned-area inputs",
        "",
        "SHA-256 of each file read. `earthlab replay` fails if any of them changes.",
        "",
        *rows,
        "",
    ]


def declared_lines(entries: list[dict[str, Any]]) -> list[str]:
    """Limitations the agent declared with declare_limitation, in order."""
    if not entries:
        return []
    lines = ["## Declared limitations", ""]
    for entry in entries:
        codes = ", ".join(f"`{code}`" for code in entry["reasons"])
        lines.append(f"- {codes}: {entry['explanation']}")
    return [*lines, ""]

"""The comparative report as Markdown, from the saved comparison record.

The template holds the fixed text: rules and limits. Every number comes from the record. The
conclusion follows the stated rule: prefer the simpler execution unless a benefit was shown.
"""

from __future__ import annotations

from string import Template
from typing import Any

from earthlab.harness.compare import NOT_MEASURED

ARMS = (
    "source", "workflow", "group", "runs", "vgc", "safe_stops", "failed", "replays_clean",
    "median_wall_s_reached_gate", "total_wall_s", "median_model_calls", "median_tokens",
    "largest_training_rss_mb",
)  # fmt: skip
WORKFLOWS = ("deterministic", "single agent", "multi-agent", "small-model fallback")


def table(headers: tuple[str, ...], rows: list[tuple[Any, ...]]) -> str:
    top = "| " + " | ".join(headers) + " |\n|" + "---|" * len(headers) + "\n"
    return top + "".join("| " + " | ".join(str(v) for v in r) + " |\n" for r in rows)


def _coverage(report: dict[str, Any]) -> str:
    rows = [
        (r["source"], r["scenario"], *[r.get(w, 0) for w in WORKFLOWS],
         "yes" if r["all_three"] else "no")
        for r in report["coverage"]
    ]  # fmt: skip
    return table(("Source", "Scenario", *WORKFLOWS, "All three"), rows)


def _matched(rows: list[dict[str, Any]], arms: tuple[str, ...]) -> str:
    out = []
    for row in rows:
        for arm in arms:
            c = row[arm]
            out.append((
                row["scenario"], arm, c["outcome"], f"{c['vgc']} of {c['runs']}",
                c["median_wall_s"], c["median_model_calls"], c["median_tokens"],
            ))  # fmt: skip
    return table(("Scenario", "Arm", "Outcome", "VGC", "Median wall s", "Calls", "Tokens"), out)


def _selection(report: dict[str, Any]) -> str:
    rows = report["selection"]
    decided = [r for r in rows if r["code_outcome"] != NOT_MEASURED]
    match = sum(r["matches_code"] for r in decided)
    loose = [r for r in rows if r["more_permissive_than_code"]]
    changed = sum(r["changed_plan"] for r in rows)
    stops = [r for r in rows if r["stop_reason"]]
    lines = table(
        ("Source", "Scenario", "Arm", "Stop reason"),
        [(r["source"], r["scenario"], r["arm"], r["stop_reason"]) for r in stops],
    )
    return (
        f"Model runs with a decision: {len(decided)}. The outcome matched the code rule in "
        f"{match}. A model changed the plan in {changed} of {len(rows)} model runs. An outcome "
        f"more permissive than the code rule appeared in {len(loose)} runs: "
        f"{sorted({(r['arm'], r['scenario']) for r in loose}) or 'none'}.\n\n"
        f"Runs that stopped with no decision:\n\n{lines}"
    )


def _cases(name: str, rows: list[dict[str, Any]]) -> str:
    live = [r for r in rows if (r.get("record") or {}).get("critic_calls")]
    usable = [r for r in live if r["record"]["critique_state"] == "usable"]
    kinds = [(r["record"].get("disposition") or {}).get("disposition") for r in usable]
    accepted, opened = kinds.count("accepted"), kinds.count("needs_revision") + kinds.count(None)
    return (
        f"- `{name}`: seeded rows {len(rows)}, live critic rows {len(live)}, usable critiques "
        f"{len(usable)}, accepted by the Lead and passed by code {accepted}, rebutted "
        f"{kinds.count('rebutted')}, left open {opened}.\n"
    )


def _pairs(name: str, rows: list[dict[str, Any]]) -> str:
    cells = [(r["scenario"], r.get("gate"), r.get("status"), (r.get("recommendation") or {}).get(
        "outcome", "none"), r.get("code_outcome") or "none", r.get("wall_seconds"),
        (r.get("usage") or {}).get("model_calls")) for r in rows]  # fmt: skip
    head = ("Scenario", "Gate", "Status", "Outcome", "Code outcome", "Wall s", "Calls")
    return f"\nMatched live runs, `{name}`: {len(rows)} of 6 planned.\n\n" + table(head, cells)


def _review(report: dict[str, Any]) -> str:
    found = report["review"]
    if not any("cases" in name for name in found):
        return f"Review-gate validation: {NOT_MEASURED}.\n"
    parts = [_cases(name, rows) for name, rows in found.items() if "cases" in name]
    parts.append(
        "\nThese are seeded cases, so a changed case here is not a changed real decision. Each "
        "revision keeps its own rows.\n"
    )
    pairs = [_pairs(name, rows) for name, rows in found.items() if "matched" in name]
    parts.extend(pairs or [f"\nMatched live runs with and without the gate: {NOT_MEASURED}.\n"])
    return "".join(parts)


def _sources(report: dict[str, Any]) -> str:
    cells = [(s["name"], f"`{s['path']}`", s["rows"], f"`{s['sha256'][:16]}`")
             for s in report.get("sources", [])]  # fmt: skip
    return table(("Source", "File under the run root", "Rows", "SHA-256, first 16"), cells)


def _totals(report: dict[str, Any]) -> tuple[Any, ...]:
    arms = {(r["source"], r["group"]): r for r in report["arms"]}
    return tuple(
        arms[("benchmark screen", a)]["median_wall_s_reached_gate"] for a in ("F", "S-M", "T-M-v1")
    )


def render(report: dict[str, Any], template: str) -> str:
    fixed, single, team = _totals(report)
    arms = table(ARMS, [tuple(r[k] for k in ARMS) for r in report["arms"]])
    return Template(template).substitute(
        runs=report["runs"],
        fixed=fixed,
        single=single,
        team=team,
        not_measured=NOT_MEASURED,
        coverage=_coverage(report),
        arms=arms,
        matched_screen=_matched(report["matched_screen"], ("F", "S-M", "T-M-v1")),
        matched_confirm=_matched(report["matched_confirm"], ("T-M-base", "T-M-win")),
        selection=_selection(report),
        review=_review(report),
        sources=_sources(report),
    )

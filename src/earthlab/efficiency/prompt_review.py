"""Static prompt reviewer: findings and candidate changes, never a rewritten prompt.

The reviewer reads prompt text and tool names as data. It does not call a model and does
not write files. Its output is a `Review` that a person reads and approves or rejects.
"""

from __future__ import annotations

import re
from collections import defaultdict

from earthlab.efficiency.prompt_models import Finding, PromptSpec, Review, ToolDecl
from earthlab.efficiency.prompt_rules import RULES

MIN_REPEAT_CHARS = 40


def _sentences(text: str) -> list[str]:
    flat = re.sub(r"\s+", " ", text.lower())
    return [
        s.strip() for s in re.split(r"(?<=[.:;])\s", flat) if len(s.strip()) >= MIN_REPEAT_CHARS
    ]


def rule_repeated_context(specs: tuple[PromptSpec, ...]) -> list[Finding]:
    """R007: a sentence repeated inside one prompt, or shared by several prompts."""
    where: dict[str, list[str]] = defaultdict(list)
    for spec in specs:
        for s in _sentences(spec.text):
            where[s].append(spec.prompt_id)
    found: list[Finding] = []
    for sentence, owners in sorted(where.items()):
        if len(owners) < 2:
            continue
        scope = (
            "within one prompt"
            if len(set(owners)) == 1
            else "across " + ", ".join(sorted(set(owners)))
        )
        found.append(
            Finding(
                rule="R007",
                severity="info",
                prompt_id=sorted(set(owners))[0],
                line=None,
                evidence=sentence[:80],
                message=f"sentence repeated {scope}",
                candidate_change="State it once, in a shared hashed context artifact "
                "that each call references.",
            )
        )
    return found


def review_prompts(specs: tuple[PromptSpec, ...]) -> Review:
    found: list[Finding] = []
    for spec in specs:
        for rule in RULES:
            found.extend(rule(spec))
    found.extend(rule_repeated_context(specs))
    order = {"error": 0, "warn": 1, "info": 2}
    found.sort(key=lambda f: (order[f.severity], f.prompt_id, f.rule, f.line or 0))
    return Review(findings=tuple(found))


# Tools each call offers, as declared in earthlab.workflow.brief and earthlab.agent. This list
# is data for the reviewer; a test checks that every name still exists in the source tree.
ENGINEER_TOOLS = (
    "submit_plan",
    "assess_case",
    "burned_area_summary",
    "submit_area_findings",
    "submit_findings",
    "declare_limitation",
    "inspect_coverage",
    "rank_regions",
    "summarize_regions",
    "daily_peaks",
    "count_hours_above",
)


def default_specs() -> tuple[PromptSpec, ...]:
    """The production prompts, read from their modules. Imported lazily so tests stay cheap."""
    from earthlab.agent.prompts import PLAN_FIRST, SYSTEM_PROMPT
    from earthlab.workflow.prompts import ORCHESTRATOR_SYSTEM, PM_REPORT, PM_SYSTEM

    return (
        PromptSpec(
            prompt_id="pm_system",
            role="product_manager",
            text=PM_SYSTEM,
            tools=(ToolDecl(name="submit_brief"),),
            placeholders=("cases",),
        ),
        PromptSpec(
            prompt_id="orchestrator_system",
            role="orchestrator",
            text=ORCHESTRATOR_SYSTEM,
            tools=(ToolDecl(name="submit_decision"),),
        ),
        PromptSpec(prompt_id="pm_report", role="product_manager", text=PM_REPORT, kind="report"),
        PromptSpec(
            prompt_id="engineer_system",
            role="geospatial_engineer",
            text=SYSTEM_PROMPT + PLAN_FIRST,
            placeholders=("reasoning",),
            tools=tuple(ToolDecl(name=n) for n in ENGINEER_TOOLS),
        ),
    )

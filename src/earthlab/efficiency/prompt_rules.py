"""Deterministic prompt rules. Each rule reads one PromptSpec and returns findings."""

from __future__ import annotations

import re
import string
from collections import defaultdict
from dataclasses import dataclass

from earthlab.efficiency.prompt_models import Finding, PromptSpec, Severity


@dataclass(frozen=True)
class Constraint:
    key: str
    label: str
    pattern: str
    severity: Severity = "error"


# Scientific and safety constraints each role prompt must state. A constraint counts as
# stated when its pattern matches anywhere in the text (case-insensitive).
REQUIRED: dict[str, tuple[Constraint, ...]] = {
    "product_manager": (
        Constraint(
            "no_invented_values",
            "no added number, place or date",
            r"do not add any number|do not add",
        ),
        Constraint(
            "period_end_excluded", "period end is excluded", r"end\s+(is\s+)?excluded|half-open"
        ),
        Constraint(
            "no_self_decision",
            "does not answer, choose or approve",
            r"do(es)? not (answer|choose|approve)|never choose",
        ),
    ),
    "product_manager_report": (
        Constraint("cites_finding_ids", "cites finding IDs only", r"finding ids"),
        Constraint("no_digits", "writes no digits or dates", r"do not write digits"),
    ),
    "orchestrator": (
        Constraint("no_invented_values", "no added number", r"do not add any number"),
        Constraint("no_approval", "does not approve or judge truth", r"approve"),
    ),
    "geospatial_engineer": (
        Constraint("half_open_windows", "windows are half-open", r"half-open|end excluded"),
        Constraint("independent_verifier", "an independent verifier decides claims", r"verifier"),
        Constraint(
            "declare_limitation", "unsupported questions end in a limitation", r"declare_limitation"
        ),
        Constraint("no_causal_claim", "no cause, forecast or advice", r"caus|forecast"),
        Constraint("pm25_not_aqi", "PM2.5 is not PSI or AQI", r"not psi or aqi"),
        Constraint("units_and_zone", "units and time zone stated", r"ug/m3|local time"),
    ),
}
ROLE_PHRASES: dict[str, tuple[str, ...]] = {
    "product_manager": ("product manager",),
    "orchestrator": ("workflow orchestrator", "lead investigator"),
    "geospatial_engineer": ("geospatial engineer", "lead investigator"),
}
TOOL_VERBS = (
    "submit_",
    "declare_",
    "assess_",
    "burned_area_summary",
    "inspect_",
    "rank_",
    "count_",
)
_IDENT = re.compile(r"\b[a-z]+(?:_[a-z0-9]+)+\b")


def flat(text: str) -> str:
    return re.sub(r"\s+", " ", text)


def policy_key(spec: PromptSpec) -> str:
    return spec.role if spec.kind == "system" else f"{spec.role}_{spec.kind}"


def line_of(text: str, needle: str) -> int | None:
    idx = text.find(needle)
    return None if idx < 0 else text.count("\n", 0, idx) + 1


def rule_role(spec: PromptSpec) -> list[Finding]:
    """R001: the prompt speaks as the role the call serves."""
    match = re.search(r"You are (?:the |a )?([a-z ]+?)(?: of| and|\.|,)", spec.text, re.I)
    if match is None:
        return [
            Finding(
                rule="R001",
                severity="error",
                prompt_id=spec.prompt_id,
                line=None,
                message="no 'You are ...' role statement",
                candidate_change=f"Add a first line that names the {spec.role} role.",
            )
        ]
    spoken = match.group(1).lower()
    if any(p in spoken for p in ROLE_PHRASES[spec.role]):
        return []
    return [
        Finding(
            rule="R001",
            severity="error",
            prompt_id=spec.prompt_id,
            line=line_of(spec.text, match.group(0)),
            message=f"prompt speaks as '{spoken}' but serves {spec.role}",
            evidence=match.group(0),
            candidate_change=f"Name the {spec.role} role in the opening sentence.",
        )
    ]


def rule_tools(spec: PromptSpec) -> list[Finding]:
    """R002: tools named in the text exist in the call's schema, and the reverse."""
    declared = {t.name for t in spec.tools}
    found: list[Finding] = []
    for ident in sorted(set(_IDENT.findall(spec.text))):
        if ident.startswith(TOOL_VERBS) and ident not in declared:
            found.append(
                Finding(
                    rule="R002",
                    severity="error",
                    prompt_id=spec.prompt_id,
                    line=line_of(spec.text, ident),
                    evidence=ident,
                    message=f"text names tool '{ident}' that this call does not offer",
                    candidate_change=f"Remove '{ident}' from the text, or add it to the tools.",
                )
            )
    for name in sorted(declared):
        if name not in spec.text:
            found.append(
                Finding(
                    rule="R002",
                    severity="info",
                    prompt_id=spec.prompt_id,
                    line=None,
                    evidence=name,
                    message=f"tool '{name}' is offered but the prompt never names it",
                    candidate_change=f"State when to call '{name}', or stop offering it.",
                )
            )
    return found


def rule_constraints(spec: PromptSpec) -> list[Finding]:
    """R003: required scientific constraints are stated."""
    return [
        Finding(
            rule="R003",
            severity=c.severity,
            prompt_id=spec.prompt_id,
            line=None,
            message=f"missing constraint: {c.label}",
            evidence=c.key,
            candidate_change=f"Add one sentence that states: {c.label}.",
        )
        for c in REQUIRED.get(policy_key(spec), ())
        if not re.search(c.pattern, flat(spec.text), re.I)
    ]


def rule_evidence(spec: PromptSpec) -> list[Finding]:
    """R004: text that reports findings must cite finding IDs and keep provenance in code."""
    text = flat(spec.text).lower()
    reports = "finding" in text and re.search(r"interpretation|report", text)
    if reports and not re.search(r"finding ids?|by id|\bid\b", text):
        return [
            Finding(
                rule="R004",
                severity="error",
                prompt_id=spec.prompt_id,
                line=None,
                message="prompt asks for a report on findings but not for finding IDs",
                candidate_change="Require each statement to cite a supported finding ID.",
            )
        ]
    return []


def rule_budget_permission(spec: PromptSpec) -> list[Finding]:
    """R005: tool prompts state a budget and a permission boundary."""
    if not spec.tools:
        return []
    out: list[Finding] = []
    text = flat(spec.text).lower()
    if not re.search(r"at most|exactly once|no further tool|once", text):
        out.append(
            Finding(
                rule="R005",
                severity="warn",
                prompt_id=spec.prompt_id,
                line=None,
                message="no call or length budget in the text",
                candidate_change="State how many calls the role may make.",
            )
        )
    if not re.search(r"read-only|never download|do not (approve|choose)|cannot|never", text):
        out.append(
            Finding(
                rule="R005",
                severity="warn",
                prompt_id=spec.prompt_id,
                line=None,
                message="no permission boundary in the text",
                candidate_change="State what the role may not do.",
            )
        )
    if any(t.writes for t in spec.tools) and "approv" not in text:
        out.append(
            Finding(
                rule="R005",
                severity="error",
                prompt_id=spec.prompt_id,
                line=None,
                message="a write tool is offered but approval is not mentioned",
                candidate_change="Require human approval before any write tool.",
            )
        )
    return out


def rule_contradictions(spec: PromptSpec) -> list[Finding]:
    """R006: one unit with two different limits, or one phrase told as always and never."""
    out: list[Finding] = []
    limits: dict[str, set[str]] = defaultdict(set)
    for n, unit in re.findall(r"at most (\d+) ([a-z]+)", flat(spec.text), re.I):
        limits[unit.lower()].add(n)
    for unit, values in sorted(limits.items()):
        if len(values) > 1:
            out.append(
                Finding(
                    rule="R006",
                    severity="error",
                    prompt_id=spec.prompt_id,
                    line=None,
                    evidence=f"{unit}: {sorted(values)}",
                    message=f"conflicting limits for '{unit}'",
                    candidate_change=f"Keep one limit for '{unit}'.",
                )
            )
    always = {m.lower() for m in re.findall(r"always ([a-z ]{4,30})", flat(spec.text), re.I)}
    never = {m.lower() for m in re.findall(r"never ([a-z ]{4,30})", flat(spec.text), re.I)}
    for phrase in sorted(always & never):
        out.append(
            Finding(
                rule="R006",
                severity="error",
                prompt_id=spec.prompt_id,
                line=None,
                evidence=phrase,
                message=f"'{phrase}' is both always and never",
            )
        )
    return out


def rule_placeholders(spec: PromptSpec) -> list[Finding]:
    """R009: every format field in the text is declared, so rendering cannot fail."""
    try:
        fields = {f for _, f, _, _ in string.Formatter().parse(spec.text) if f}
    except ValueError:
        return [
            Finding(
                rule="R009",
                severity="error",
                prompt_id=spec.prompt_id,
                line=None,
                message="text has an unbalanced brace",
            )
        ]
    return [
        Finding(
            rule="R009",
            severity="error",
            prompt_id=spec.prompt_id,
            line=None,
            evidence=f,
            message=f"undeclared placeholder '{f}'",
        )
        for f in sorted(fields - set(spec.placeholders))
    ]


def rule_artifact_refs(spec: PromptSpec) -> list[Finding]:
    """R008: large or structured blocks that a hashed artifact reference could carry."""
    out: list[Finding] = []
    for name in spec.placeholders:
        if name in {"cases", "catalogue", "context", "evidence", "brief"}:
            out.append(
                Finding(
                    rule="R008",
                    severity="info",
                    prompt_id=spec.prompt_id,
                    line=None,
                    evidence=name,
                    message=f"placeholder '{name}' inlines structured context in every call",
                    candidate_change=f"Pass '{name}' as an artifact reference (hash plus key "
                    "fields) and resolve it in code.",
                )
            )
    if re.search(r"as json|\bjson\b below", spec.text, re.I):
        out.append(
            Finding(
                rule="R008",
                severity="info",
                prompt_id=spec.prompt_id,
                line=None,
                message="prompt embeds a JSON record as context",
                candidate_change="Carry the record as a typed artifact reference.",
            )
        )
    return out


RULES = (
    rule_role,
    rule_tools,
    rule_constraints,
    rule_evidence,
    rule_budget_permission,
    rule_contradictions,
    rule_placeholders,
    rule_artifact_refs,
)

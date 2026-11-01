"""Records for the static prompt reviewer."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict

Severity = Literal["error", "warn", "info"]


class ToolDecl(Strict):
    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    writes: bool = False


class PromptSpec(Strict):
    """One prompt as text, with the role it serves and the tools the call offers."""

    prompt_id: str
    role: Literal["product_manager", "orchestrator", "geospatial_engineer"]
    text: str
    tools: tuple[ToolDecl, ...] = ()
    placeholders: tuple[str, ...] = ()
    kind: Literal["system", "report"] = "system"


class Finding(Strict):
    rule: str
    severity: Severity
    prompt_id: str
    line: int | None
    message: str
    evidence: str = ""
    candidate_change: str | None = None


class Review(Strict):
    """Findings and candidate changes. A person approves each change; nothing is rewritten."""

    findings: tuple[Finding, ...]
    requires_approval: Literal[True] = True
    rewrites_prompts: Literal[False] = False

    @property
    def candidate_changes(self) -> tuple[tuple[str, str], ...]:
        """(prompt_id, change) for each finding that proposes one, without repeats."""
        seen: dict[tuple[str, str], None] = {}
        for f in self.findings:
            if f.candidate_change:
                seen[(f.prompt_id, f.candidate_change)] = None
        return tuple(seen)

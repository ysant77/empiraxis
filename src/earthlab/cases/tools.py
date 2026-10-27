"""The read-only assess_case tool: is a registered study case runnable now, and if not, why.

The tool never downloads, approves or computes; it reports the feasibility check for the
case files in config/cases.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field

from earthlab.cases.loader import CaseFile, load_case
from earthlab.cases.methods import assess, get_method
from earthlab.contracts import Strict
from earthlab.tools.registry import ToolSpec

ASSESS_TOOL = "assess_case"


class CaseLibrary:
    def __init__(self, cases: dict[str, CaseFile], root: Path):
        self._cases = cases
        self.root = root

    @classmethod
    def load(cls, cases_dir: Path, root: Path) -> CaseLibrary:
        loaded = [load_case(path, root) for path in sorted(cases_dir.glob("*.yaml"))]
        return cls({c.case.case_id: c for c in loaded}, root)

    def get(self, case_id: str) -> CaseFile:
        if case_id not in self._cases:
            raise ValueError(f"unknown case {case_id!r}; known: {', '.join(self.ids())}")
        return self._cases[case_id]

    def ids(self) -> list[str]:
        return sorted(self._cases)

    def report(self, case_id: str) -> dict[str, Any]:
        loaded = self.get(case_id)
        case = loaded.case
        result = assess(case, get_method(case.method_id), loaded.assets)
        return {
            "case_id": case.case_id,
            "title": case.title,
            "variable": case.variable.value,
            "method_id": case.method_id,
            "area": case.area.name,
            "period": case.period.local_label(),
            "status": result.status,
            "reasons": list(result.reasons),
            "approvals_needed": [[a.value, i] for a, i in result.approvals_needed],
        }


class AssessArgs(Strict):
    case_id: str = Field(min_length=1, max_length=80)


def assess_case_spec(library: CaseLibrary) -> ToolSpec:
    def handle(args: AssessArgs) -> dict[str, Any]:
        return library.report(args.case_id)

    return ToolSpec(
        ASSESS_TOOL,
        "Report whether a registered study case can run now (feasible, needs_approval, "
        f"not_implemented or blocked) and every reason. Cases: {', '.join(library.ids())}.",
        AssessArgs,
        handle,
    )

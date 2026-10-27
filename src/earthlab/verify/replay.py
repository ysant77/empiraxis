"""Re-check a saved run offline: trace hash chain, every verdict, every recorded input hash.

No model is called. A run replays only if each recomputed verdict and observed value is
equal to the saved one, each month check is equal, and each recorded input file still
has its recorded SHA-256. Missing records fail closed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from earthlab.agent.area_findings import AreaClaim, verify_area_claim
from earthlab.digest import file_digest
from earthlab.report.evidence import month_or_error
from earthlab.trace import RunTrace
from earthlab.verify.claims import Claim

if TYPE_CHECKING:
    from earthlab.runtime import Workspace


@dataclass
class Replay:
    trace_records: int = 0
    pm25: list[int] = field(default_factory=lambda: [0, 0])  # [reproduced, total]
    area: list[int] = field(default_factory=lambda: [0, 0])
    months: list[int] = field(default_factory=lambda: [0, 0])
    files_checked: int = 0
    changed_files: list[str] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        counts_match = all(a == b for a, b in (self.pm25, self.area, self.months))
        return counts_match and not self.changed_files and not self.problems


def _same(fresh: dict[str, Any], saved: dict[str, Any]) -> bool:
    return fresh["verdict"] == saved["verdict"] and fresh.get("observed") == saved.get("observed")


def _pm25(result: dict[str, Any], workspace: Workspace, out: Replay) -> None:
    if result["source"]["sha256"] != workspace.snapshot.sha256:
        out.problems.append("the PM2.5 source hash differs from the saved run")
    for rnd in result["rounds"]:
        for saved in rnd:
            fresh = workspace.verifier.verify(Claim.model_validate(saved["claim"]))
            out.pm25[1] += 1
            out.pm25[0] += _same(fresh.model_dump(mode="json"), saved)


def _area(result: dict[str, Any], workspace: Workspace, out: Replay) -> None:
    rounds = result.get("area_rounds", [])
    evidence = result.get("evidence")
    if not rounds and evidence is None:
        return
    library = workspace.cases
    if library is None:
        out.problems.append("the run has burned-area records but no case files are loaded")
        return
    if evidence is None:
        out.problems.append("the run has burned-area claims but no recorded input hashes")
    for rnd in rounds:
        for saved in rnd:
            fresh = verify_area_claim(AreaClaim.model_validate(saved["claim"]), library)
            out.area[1] += 1
            out.area[0] += _same(fresh.model_dump(mode="json"), saved)
    for rel, sha in (evidence or {}).get("files", {}).items():
        path = library.root / rel
        out.files_checked += 1
        if not path.is_file() or file_digest(path) != sha:
            out.changed_files.append(rel)
    for saved_month in (evidence or {}).get("months", []):
        fresh_month = month_or_error(library, saved_month["case_id"], saved_month["month"])
        out.months[1] += 1
        out.months[0] += fresh_month == saved_month


def replay_run(run_dir: Path, workspace: Workspace) -> Replay:
    out = Replay(trace_records=RunTrace(run_dir / "trace.jsonl").verify())
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    _pm25(result, workspace, out)
    _area(result, workspace, out)
    return out

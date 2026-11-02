"""Re-check a saved run offline: trace hash chain, every verdict, every recorded input hash.

No model is called. A run replays only if each recomputed verdict and observed value is
equal to the saved one, each month check is equal, and each recorded input file still
has its recorded SHA-256. Missing records fail closed.

A folder listed in a replay manifest must first match that manifest exactly. Only then may a
recorded artifact be absent: the published copy left it out, and the trace keeps its digest.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from earthlab.agent.area_findings import AreaClaim, verify_area_claim
from earthlab.digest import file_digest
from earthlab.events.manifest import MANIFEST, ManifestError, verified_run
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
    omitted_files: list[str] = field(default_factory=list)
    manifest: str = "not listed"
    problems: list[str] = field(default_factory=list)
    source_matches: bool = False
    recorded: bool = False  # a saved evaluation: its files are checked, its scores are not rerun

    @property
    def ok(self) -> bool:
        counts_match = all(a == b for a, b in (self.pm25, self.area, self.months))
        return counts_match and not self.changed_files and not self.problems


def _same(fresh: dict[str, Any], saved: dict[str, Any]) -> bool:
    return fresh["verdict"] == saved["verdict"] and fresh.get("observed") == saved.get("observed")


def _pm25(result: dict[str, Any], workspace: Workspace, out: Replay) -> None:
    out.source_matches = result["source"]["sha256"] == workspace.snapshot.sha256
    if not out.source_matches:
        out.problems.append("the PM2.5 source hash differs from the saved run")
    if "rounds" not in result:
        if result.get("workflow", {"engineering_task": True})["engineering_task"] is not None:
            out.problems.append("the run has no verdict records")
        return  # a workflow that stopped before the engineer has no verdicts to replay
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


def _manifest(run_dir: Path, out: Replay) -> None:
    """Check the folder against the manifest of its parent, when the manifest lists it."""
    root = run_dir.parent
    if not (root / MANIFEST).is_file():
        return
    try:
        verified_run(root, run_dir.name)
    except ManifestError as exc:
        if "not in the replay allowlist" in str(exc):
            return
        out.manifest = "CHANGED"
        out.problems.append(str(exc))
        return
    out.manifest = "match"


def _recorded(run_dir: Path, result: dict[str, Any], out: Replay) -> None:
    """A recorded scenario has no claims to rerun, so every file it lists must keep its digest."""
    listed = {f"{name}.json": sha for name, sha in result.get("artifacts", {}).items()}
    listed |= (result.get("evidence") or {}).get("files", {})
    if not listed:
        out.problems.append("the recorded run lists no artifact")
    for name, sha in listed.items():
        out.files_checked += 1
        path = run_dir / name
        if not path.is_file() and out.manifest == "match":
            out.omitted_files.append(name)
        elif not path.is_file() or file_digest(path) != sha:
            out.changed_files.append(name)


def replay_run(run_dir: Path, workspace: Workspace) -> Replay:
    out = Replay(trace_records=RunTrace(run_dir / "trace.jsonl").verify())
    _manifest(run_dir, out)
    result = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    if "source" not in result and "evidence_label" in result:
        out.recorded = True
        _recorded(run_dir, result, out)
        return out
    _pm25(result, workspace, out)
    _area(result, workspace, out)
    return out


def replay_lines(out: Replay) -> list[str]:
    """The operator's summary of one replay."""
    lines = [f"trace: {out.trace_records} records, hash chain intact"]
    if out.recorded:
        lines.append("recorded evaluation: artifact digests checked; no score was recomputed")
    else:
        lines += [
            f"PM2.5 source hash: {'match' if out.source_matches else 'CHANGED'}",
            f"verdicts reproduced: {out.pm25[0]}/{out.pm25[1]}",
            f"area verdicts reproduced: {out.area[0]}/{out.area[1]}",
            f"month checks reproduced: {out.months[0]}/{out.months[1]}",
        ]
    if out.manifest != "not listed":
        lines.append(f"manifest: {'all files match' if out.manifest == 'match' else 'CHANGED'}")
    present = out.files_checked - len(out.omitted_files)
    if not out.files_checked:
        lines.append("input hashes: none recorded")
    elif not out.changed_files:
        lines.append(f"input hashes: all match ({present} files)")
    else:
        lines.append(f"input hashes: {len(out.changed_files)} of {present} files CHANGED")
    if out.omitted_files:
        lines.append(
            f"left out of this published copy: {len(out.omitted_files)} files; the trace keeps "
            "their digests, and they are not checked here"
        )
    lines += [f"changed: {rel}" for rel in out.changed_files]
    return lines + [f"problem: {problem}" for problem in out.problems]

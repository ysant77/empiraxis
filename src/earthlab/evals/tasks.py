"""Fixed evaluation tasks and the scoring rule: a requirement is met by a supported claim."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import yaml
from pydantic import Field

from earthlab.contracts import Region, Strict, TimeWindow
from earthlab.verify.claims import ClaimKind, Verdict, VerificationResult


class Requirement(Strict):
    kind: ClaimKind
    start: datetime
    end: datetime
    region: Region | None = None
    threshold: float | None = None

    @property
    def window(self) -> TimeWindow:
        return TimeWindow(start=self.start, end=self.end)

    def met_by(self, result: VerificationResult) -> bool:
        claim = result.claim
        return (
            result.verdict is Verdict.SUPPORTED
            and claim.kind is self.kind
            and claim.window == self.window
            and (self.region is None or claim.region is self.region)
            and (self.threshold is None or claim.threshold == self.threshold)
        )


class EvalTask(Strict):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    question: str
    requirements: list[Requirement] = Field(min_length=1)


class TaskScore(Strict):
    task_id: str
    arm: str
    required: int
    met: int
    rejected_claims: int
    verified_success: bool


def load_tasks(path: Path) -> list[EvalTask]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return [EvalTask.model_validate(item) for item in raw["tasks"]]


def score(
    task: EvalTask, arm: str, final: list[VerificationResult], rejected_total: int
) -> TaskScore:
    """Verified success: every requirement met and no rejected claim in the final answer."""
    met = sum(1 for req in task.requirements if any(req.met_by(r) for r in final))
    rejected_final = sum(1 for r in final if r.verdict is not Verdict.SUPPORTED)
    return TaskScore(
        task_id=task.id,
        arm=arm,
        required=len(task.requirements),
        met=met,
        rejected_claims=rejected_total,
        verified_success=met == len(task.requirements) and rejected_final == 0,
    )

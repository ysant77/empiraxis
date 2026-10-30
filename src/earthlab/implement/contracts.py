"""Typed contracts for bounded implementation work. Records only: nothing here runs code.

A Geospatial Engineer issues an `ImplementationTaskV1` for an approved, scoped change. An
implementor worker (a Meta or non-Meta model) answers with an `ImplementationResultV1`
that holds a proposed diff and nothing that claims success. Reviewers, deterministic code
or a model, add `ReviewFindingV1` records. Only a trusted runner writes an
`ExecutionResultV1`, and only `acceptance` decides whether a patch may go to a human.
"""

from __future__ import annotations

import hashlib
import posixpath
from typing import Literal, Self

from pydantic import Field, field_validator, model_validator

from earthlab.contracts import Strict

TASK_ID = r"^[a-z0-9][a-z0-9._-]{0,79}$"
SHA256 = r"^[0-9a-f]{64}$"
MAX_PATCH_BYTES = 64 * 1024
# A worker may only edit source and tests. Data, configs, approvals, evaluations (the
# held-out set lives there), CI and lockfiles stay outside every task.
EDITABLE_ROOTS = ("src/earthlab/", "tests/")
FORBIDDEN_PARTS = ("evals", "data", "config", ".github", "runs", "examples")

TaskKind = Literal["code_patch", "test_suite", "experiment_spec", "analysis_plan"]
ModelFamily = Literal["meta-muse", "meta-llama", "qwen", "gemma", "mistral", "deepseek", "other"]
Severity = Literal["blocking", "warning", "note"]


def _clean_path(path: str) -> str:
    """A repository-relative POSIX path that cannot leave the repository."""
    if not path or "\\" in path or "\x00" in path or path.startswith("/"):
        raise ValueError(f"{path!r}: use a relative POSIX path")
    if posixpath.normpath(path) != path or ".." in path.split("/"):
        raise ValueError(f"{path!r}: path is not normalised or leaves the repository")
    return path


def editable(path: str) -> bool:
    """True for a path an implementation task may list as editable."""
    parts = path.split("/")
    return path.startswith(EDITABLE_ROOTS) and not any(p in FORBIDDEN_PARTS for p in parts[1:])


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class WorkerPermissions(Strict):
    """Every privilege an implementor could ask for. Each one is fixed to False."""

    run_shell: Literal[False] = False
    network: Literal[False] = False
    install_packages: Literal[False] = False
    download_data: Literal[False] = False
    train_model: Literal[False] = False
    commit_or_merge: Literal[False] = False
    deploy: Literal[False] = False


class TaskBudget(Strict):
    max_model_calls: int = Field(default=2, ge=1, le=4)  # one proposal and one revision
    max_wall_seconds: float = Field(default=600.0, gt=0, le=3600)
    max_paid_usd: float = Field(default=0.0, ge=0, le=5.0)


class ImplementationTaskV1(Strict):
    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    parent_task_id: str = Field(pattern=TASK_ID)
    task_kind: TaskKind
    requested_by_role: Literal["geospatial_engineer"] = "geospatial_engineer"
    method_ref: str = Field(min_length=1, max_length=80)
    allowed_paths: tuple[str, ...] = Field(min_length=1, max_length=10)
    read_only_sources: tuple[str, ...] = Field(default=(), max_length=20)
    requirements: tuple[str, ...] = Field(min_length=1, max_length=12)
    fixed_tests: tuple[str, ...] = Field(min_length=1, max_length=10)
    data_classification: Literal["synthetic_development", "pinned_public"]
    permissions: WorkerPermissions = WorkerPermissions()
    budget: TaskBudget = TaskBudget()

    @field_validator("allowed_paths", "read_only_sources", "fixed_tests")
    @classmethod
    def _paths(cls, paths: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(paths)) != len(paths):
            raise ValueError("paths must be unique")
        return tuple(_clean_path(p) for p in paths)

    @field_validator("requirements")
    @classmethod
    def _short(cls, items: tuple[str, ...]) -> tuple[str, ...]:
        if any(not 1 <= len(item) <= 300 for item in items):
            raise ValueError("each requirement is one to 300 characters")
        return items

    @model_validator(mode="after")
    def _scope(self) -> Self:
        outside = [p for p in self.allowed_paths if not editable(p)]
        if outside:
            raise ValueError(f"not editable by a worker: {outside}")
        # Acceptance tests are written before the worker sees the task and stay read-only.
        overlap = sorted(set(self.allowed_paths) & set(self.fixed_tests))
        if overlap:
            raise ValueError(f"a worker cannot edit its own acceptance tests: {overlap}")
        if not all(t.startswith("tests/") for t in self.fixed_tests):
            raise ValueError("fixed tests must live under tests/")
        return self


class WorkerIdentity(Strict):
    """Who produced an artifact: the role, and the exact model that served the call."""

    role_id: Literal["implementor"] = "implementor"
    worker_id: str = Field(pattern=r"^[a-z0-9-]+$")
    model_family: ModelFamily
    model_id: str = Field(min_length=1, max_length=120)
    provider_id: str = Field(pattern=r"^[a-z0-9-]+$")
    served_model: str | None = None
    checkpoint_revision: str | None = None


class CallUsage(Strict):
    """None means not reported, never zero."""

    model_calls: int = Field(ge=0)
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    wall_seconds: float = Field(ge=0)
    cost_usd: float | None = None


class ImplementationResultV1(Strict):
    """A worker's proposal. It has no field that can say the patch works."""

    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    worker: WorkerIdentity
    status: Literal["proposed", "declined", "failed"]
    patch_diff: str = Field(default="", max_length=MAX_PATCH_BYTES)
    artifact_sha256: str = Field(pattern=SHA256)
    tests_proposed: tuple[str, ...] = Field(default=(), max_length=10)
    assumptions: tuple[str, ...] = Field(default=(), max_length=12)
    self_reported_limitations: tuple[str, ...] = Field(default=(), max_length=12)
    usage: CallUsage

    @model_validator(mode="after")
    def _digest(self) -> Self:
        if self.artifact_sha256 != sha256_text(self.patch_diff):
            raise ValueError("artifact_sha256 does not match the patch")
        if self.status == "proposed" and not self.patch_diff.strip():
            raise ValueError("a proposed result needs a patch")
        return self


class ReviewFindingV1(Strict):
    """One reviewer finding about one artifact. A finding can block; it never approves."""

    schema_version: Literal["1"] = "1"
    finding_id: str = Field(pattern=TASK_ID)
    reviewer_kind: Literal["deterministic", "model"]
    reviewer_id: str = Field(pattern=r"^[a-z0-9._-]+$")
    model_family: ModelFamily | None = None
    artifact_sha256: str = Field(pattern=SHA256)
    check_id: str = Field(pattern=r"^[a-z0-9_]+$")
    severity: Severity
    message: str = Field(min_length=1, max_length=500)
    path: str | None = None
    evidence_refs: tuple[str, ...] = Field(default=(), max_length=10)
    proposed_correction: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _family(self) -> Self:
        if (self.reviewer_kind == "model") != (self.model_family is not None):
            raise ValueError("a model reviewer names its family; deterministic code does not")
        return self


class RunnerTestOutcome(Strict):
    test_id: str = Field(min_length=1, max_length=300)
    outcome: Literal["passed", "failed", "error", "skipped"]


class ExecutionResultV1(Strict):
    """Written by the trusted runner from its own measurements, never from model text."""

    schema_version: Literal["1"] = "1"
    task_id: str = Field(pattern=TASK_ID)
    artifact_sha256: str = Field(pattern=SHA256)
    runner_id: str = Field(pattern=r"^[a-z0-9.-]+$")
    command_id: str = Field(pattern=r"^[a-z0-9_]+$")
    exit_code: int
    timed_out: bool
    network: Literal[False] = False
    tests: tuple[RunnerTestOutcome, ...]
    input_manifest_sha256: str = Field(pattern=SHA256)
    wall_seconds: float = Field(ge=0)
    peak_rss_mb: float | None = Field(default=None, ge=0)
    hardware: str = Field(min_length=1, max_length=120)


class HumanPatchDecision(Strict):
    task_id: str = Field(pattern=TASK_ID)
    artifact_sha256: str = Field(pattern=SHA256)
    decision: Literal["accept", "reject"]
    approver: str = Field(min_length=1, max_length=80)


class Acceptance(Strict):
    accepted: bool
    stage: Literal["proposal", "review", "execution", "human", "accepted"]
    reasons: tuple[str, ...]


def _test_gaps(task: ImplementationTaskV1, run: ExecutionResultV1) -> list[str]:
    """Fixed tests the run did not pass. A test ID matches its file or a node in it."""
    gaps = []
    for fixed in task.fixed_tests:
        hits = [t for t in run.tests if t.test_id == fixed or t.test_id.startswith(f"{fixed}::")]
        if not hits:
            gaps.append(f"{fixed} did not run")
        elif any(t.outcome != "passed" for t in hits):
            gaps.append(f"{fixed} did not pass")
    return gaps


def acceptance(
    task: ImplementationTaskV1,
    result: ImplementationResultV1,
    findings: tuple[ReviewFindingV1, ...] = (),
    run: ExecutionResultV1 | None = None,
    decision: HumanPatchDecision | None = None,
) -> Acceptance:
    """The one acceptance rule, the same for every model family.

    In order: a proposed patch for this task; no blocking finding from any reviewer (a
    model reviewer can add a block but cannot lift a deterministic one); a trusted run of
    exactly this artifact with exit code 0 and every fixed test passed; then a human
    accept of exactly this artifact.
    """
    digest = result.artifact_sha256
    if result.task_id != task.task_id or result.status != "proposed":
        return Acceptance(accepted=False, stage="proposal", reasons=("no proposed patch",))
    blocks = [
        f"{f.reviewer_id}: {f.check_id}"
        for f in findings
        if f.severity == "blocking" and f.artifact_sha256 == digest
    ]
    if blocks:
        return Acceptance(accepted=False, stage="review", reasons=tuple(blocks))
    if run is None or run.task_id != task.task_id or run.artifact_sha256 != digest:
        return Acceptance(accepted=False, stage="execution", reasons=("no trusted run",))
    gaps = _test_gaps(task, run)
    if run.exit_code != 0 or run.timed_out:
        gaps.insert(0, f"runner exit code {run.exit_code}, timed out {run.timed_out}")
    if gaps:
        return Acceptance(accepted=False, stage="execution", reasons=tuple(gaps))
    if decision is None or decision.artifact_sha256 != digest or decision.task_id != task.task_id:
        return Acceptance(accepted=False, stage="human", reasons=("awaiting human review",))
    if decision.decision != "accept":
        return Acceptance(accepted=False, stage="human", reasons=("rejected by human review",))
    return Acceptance(accepted=True, stage="accepted", reasons=())

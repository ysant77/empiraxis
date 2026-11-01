"""Offline registries on the shared content-addressed store, with an append-only status log.

Records are immutable. A status is a hash-chained event: code opens a model as `candidate`,
only the evaluator's digest moves it on, and only a valid signed human record approves it.
Weights load through one allowlisted path that never unpickles anything.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, TypeVar

import numpy as np
from pydantic import BaseModel

from earthlab.digest import file_digest
from earthlab.efficiency.artifacts import (
    ArtifactIntegrityError,
    ArtifactRef,
    ArtifactStore,
    Kind,
    MissingArtifactError,
    canonical,
)
from earthlab.mlops.contracts import (
    FeatureArtifactV1,
    FittedPipelineV1,
    ModelBundleV1,
    Status,
)
from earthlab.team.resources import ResourceApprovalV1, key_matches, sign
from earthlab.trace import RunTrace

R = TypeVar("R", bound=BaseModel)
EVENT = "model_status"
ZIP_MAGIC = b"PK\x03\x04"


class UnsafeArtifact(ValueError):
    """The file is not an allowlisted format. Nothing was deserialized."""


class IllegalStatus(ValueError):
    """The status move breaks the registry rules. Nothing was written."""


class DiskStore(ArtifactStore):
    """The shared store's contract, kept in files that survive a run."""

    def __init__(self, root: Path) -> None:
        super().__init__()
        self.objects = root / "objects"
        self.objects.mkdir(parents=True, exist_ok=True)

    def _put(self, kind: Kind, value: Any) -> ArtifactRef:
        data = canonical(value)
        key = hashlib.sha256(data).hexdigest()
        path = self.objects / f"{key}.json"
        if not path.exists():
            path.write_bytes(data)
        return ArtifactRef(kind=kind, sha256=key)

    def get(self, ref: ArtifactRef) -> Any:
        path = self.objects / f"{ref.sha256}.json"
        if not path.is_file():
            raise MissingArtifactError(ref.sha256)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != ref.sha256:
            raise ArtifactIntegrityError(ref.sha256)
        return json.loads(data)


def save_arrays(path: Path, arrays: dict[str, np.ndarray]) -> str:
    """Numeric arrays only, so the file can load with pickling off."""
    for name, array in arrays.items():
        if array.dtype.hasobject:
            raise UnsafeArtifact(f"{name} holds Python objects")
    with path.open("wb") as out:
        np.savez(out, allow_pickle=False, **arrays)
    return file_digest(path)


def load_arrays(path: Path, sha256: str) -> dict[str, np.ndarray]:
    """Check the digest and the format first. A pickle or an object array is refused."""
    if not path.is_file():
        raise MissingArtifactError(path.name)
    if file_digest(path) != sha256:
        raise ArtifactIntegrityError(path.name)
    with path.open("rb") as handle:
        if handle.read(4) != ZIP_MAGIC:
            raise UnsafeArtifact(f"{path.name} is not an npz archive")
    try:
        with np.load(path, allow_pickle=False) as archive:
            return {name: archive[name] for name in archive.files}
    except ValueError as exc:
        raise UnsafeArtifact(f"{path.name} holds Python objects") from exc


class Registry:
    def __init__(self, root: Path):
        self.root = root
        self.store = DiskStore(root)
        self.blobs = root / "blobs"
        self.blobs.mkdir(parents=True, exist_ok=True)
        self.log = RunTrace(root / "status.jsonl")

    def record(self, ref: ArtifactRef, shape: type[R]) -> R:
        return shape.model_validate(self.store.get(ref))

    def put_arrays(self, arrays: dict[str, np.ndarray]) -> str:
        part = self.blobs / "incoming.npz"
        digest = save_arrays(part, arrays)
        part.replace(self.blobs / f"{digest}.npz")
        return digest

    def arrays(self, sha256: str) -> dict[str, np.ndarray]:
        return load_arrays(self.blobs / f"{sha256}.npz", sha256)

    def put_feature(self, fitted: FittedPipelineV1, artifact: FeatureArtifactV1) -> ArtifactRef:
        if self.store.put_record(fitted) != artifact.fitted_pipeline:
            raise ArtifactIntegrityError("the artifact names another fitted pipeline")
        if not (self.blobs / f"{artifact.matrix_sha256}.npz").is_file():
            raise MissingArtifactError(artifact.matrix_sha256)
        return self.store.put_record(artifact)

    def register(self, bundle: ModelBundleV1) -> ArtifactRef:
        """A new bundle starts as a candidate, and training alone goes no further."""
        self.record(bundle.feature, FeatureArtifactV1)
        if not (self.blobs / f"{bundle.weights_sha256}.npz").is_file():
            raise MissingArtifactError(bundle.weights_sha256)
        ref = self.store.put_record(bundle)
        if self.status(ref) is None:
            self._move(ref, "candidate", "registry")
        return ref

    def bundle(self, ref: ArtifactRef) -> ModelBundleV1:
        return self.record(ref, ModelBundleV1)

    def status(self, ref: ArtifactRef) -> Status | None:
        now: Status | None = None
        for entry in self.log.records():
            if entry["data"]["model"] == ref.sha256:
                now = entry["data"]["to"]
        return now

    def history(self, model_name: str) -> list[dict[str, Any]]:
        return [e["data"] for e in self.log.records() if e["data"]["name"] == model_name]

    def _move(self, ref: ArtifactRef, to: Status, actor: str, **evidence: Any) -> None:
        name = self.bundle(ref).model_name
        self.log.append(EVENT, actor, model=ref.sha256, name=name, to=to, **evidence)

    def evaluate(self, ref: ArtifactRef, evaluation_path: Path, passed: bool) -> Status:
        """The evaluator's saved report, by digest. A failed evaluation rejects the model."""
        if self.status(ref) != "candidate":
            raise IllegalStatus("only a candidate can be evaluated")
        if not evaluation_path.is_file():
            raise MissingArtifactError(evaluation_path.name)
        to: Status = "evaluated" if passed else "rejected"
        self._move(ref, to, "evaluator", evaluation_sha256=file_digest(evaluation_path))
        return to

    def decide(self, ref: ArtifactRef, approval: ResourceApprovalV1, key: str) -> Status:
        """A signed human record on this exact bundle, and nothing else, decides it."""
        if self.status(ref) != "evaluated":
            raise IllegalStatus("only an evaluated model can be decided")
        if not key_matches(key) or approval.signature != sign(approval, key):
            raise IllegalStatus("the signature is not valid")
        if approval.request_sha256 != ref.sha256:
            raise IllegalStatus("the approval names a different bundle")
        to: Status = "approved" if approval.approved else "rejected"
        self._move(ref, to, "human", at=approval.decided_at_utc.isoformat())
        return to

    def latest_approved(self, model_name: str, skip: int = 0) -> ArtifactRef | None:
        """The newest approved bundle. `skip=1` is the rollback target."""
        approved = [e["model"] for e in self.history(model_name) if e["to"] == "approved"]
        ordered = list(dict.fromkeys(reversed(approved)))
        return ArtifactRef(kind="record", sha256=ordered[skip]) if len(ordered) > skip else None

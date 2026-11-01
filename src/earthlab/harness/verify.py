"""Offline verification of one saved model bundle. It writes nothing to the registry.

Each check runs on its own, so a refusal lists every fault it found. Any failed check refuses
the bundle. A rejected or unevaluated model is refused, and so is a hybrid: its encoder, its
classifier and its preprocessing do not load as one verified bundle yet.
"""

from __future__ import annotations

import platform
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import numpy as np

from earthlab.digest import file_digest
from earthlab.efficiency.artifacts import (
    ArtifactIntegrityError,
    ArtifactRef,
    MissingArtifactError,
)
from earthlab.forecast import samples as S
from earthlab.harness import attest as authority
from earthlab.harness.contracts import EvaluationReportV1
from earthlab.mlops import families, preprocess, serve
from earthlab.mlops.contracts import FeatureArtifactV1, FittedPipelineV1, ModelBundleV1
from earthlab.mlops.evidence import BundleVerificationV1, CheckV1, EvaluationRecordV1, Outcome
from earthlab.mlops.registry import Registry, UnsafeArtifact

HYBRID_REFUSAL = "hybrid inference is not supported: no single verified bundle loads it"
FAULTS = (ValueError, KeyError, OSError)


class Failed(ValueError):
    """One check found a fault."""


@dataclass(frozen=True)
class Context:
    registry: Registry
    ref: ArtifactRef
    bundle: ModelBundleV1
    feature: FeatureArtifactV1
    fitted: FittedPipelineV1
    folder: Path
    source: Path


def _status_log(c: Context) -> str:
    count = c.registry.log.verify()
    entries = [e for e in c.registry.log.records() if e["data"]["model"] == c.ref.sha256]
    if not entries:
        raise Failed("the status log has no entry for this bundle")
    named = {e["data"].get("evaluation_sha256") for e in entries} - {None}
    if named - {c.bundle.evaluation_sha256}:
        raise Failed("the status log names another evaluation report")
    if entries[-1]["data"]["to"] == "approved" and entries[-1]["actor"] != "human":
        raise Failed("an approval that is not from the signed human path")
    return f"chain intact over {count} entries"


def _weights(c: Context) -> str:
    if c.bundle.weights_format != "npz":
        raise Failed(f"{c.bundle.weights_format} is not an allowed weights format")
    state = c.registry.arrays(c.bundle.weights_sha256)
    probe = np.zeros((2, len(c.feature.feature_names)))
    out = families.predict(c.bundle.method_id, c.bundle.task, probe, state, c.bundle.config)
    if np.asarray(out).shape != (2, len(c.bundle.output_names)):
        raise Failed("the weights do not fit the feature schema and the outputs")
    return f"sha256 {c.bundle.weights_sha256[:12]}, npz, shape fits"


def _feature_schema(c: Context) -> str:
    want = preprocess.feature_names(c.fitted.config, c.fitted.columns)
    if c.bundle.family == "hybrid":
        want = c.feature.feature_names
    if c.feature.feature_names != want or (
        c.bundle.family != "hybrid" and c.fitted.feature_names != want
    ):
        raise Failed("the feature names or their order differ from the saved pipeline")
    return f"{len(want)} features in the saved order"


def _preprocessing(c: Context) -> str:
    fitted = c.fitted
    width = len(fitted.columns)
    if (len(fitted.means), len(fitted.stds)) != (width, width) or min(fitted.stds) <= 0:
        raise Failed("the saved scaling does not fit the columns")
    if fitted.config.availability_offset_hours != c.feature.availability_offset_hours:
        raise Failed("the offset in the pipeline differs from the feature artifact")
    return f"{len(fitted.config.steps)} steps over {width} columns"


def _postprocessing(c: Context) -> str:
    serve.load(c.registry, c.ref)
    post = c.bundle.postprocess
    if c.bundle.task == "regression" and not post.invert_scaling:
        raise Failed("a regression bundle must invert its scaling")
    if c.bundle.task == "classification" and post.alarm_cut is None:
        raise Failed("a classification bundle needs its declared alarm cut")
    return "steps fit the task"


def _provenance(c: Context) -> str:
    digest = c.feature.source_sha256
    if c.fitted.source_sha256 != digest:
        raise Failed("the pipeline and the feature artifact name different sources")
    train_end = S.split_bounds("train")[1]
    if c.fitted.fit_span.last > train_end or c.feature.train_span.last > train_end:
        raise Failed("the fit span passes the train end")
    last = c.feature.validation_span
    if last is None or last.last >= S.SEALED_FROM:
        raise Failed("the feature artifact reaches the sealed period")
    if "unknown" in (c.bundle.code_revision, c.feature.code_revision):
        raise Failed("the code revision is not recorded")
    return f"source {digest[:12]}, fit to row {c.fitted.fit_span.last}"


def _method(c: Context) -> str:
    method = families.METHODS.get(c.bundle.method_id)
    if method is None or c.bundle.task not in method.tasks:
        raise Failed(f"{c.bundle.method_id} is not a registered {c.bundle.task} method")
    if method.family != c.bundle.family:
        raise Failed(f"{c.bundle.method_id} is {method.family}, not {c.bundle.family}")
    method.config.model_validate(dict(c.bundle.config))
    return f"{method.method_id} ({method.family})"


def _limitations(c: Context) -> str:
    if not c.bundle.card.limitations:
        raise Failed("the card has no limitations")
    files = authority.run_files(c.bundle, c.folder, c.source)
    report = EvaluationReportV1.model_validate_json(files.report.read_bytes())
    row = next((s for s in report.scores if s.model == files.row), None)
    if row is None:
        raise Failed(f"the report has no row {files.row}")
    recorded = {
        f"{group}_{key}": float(value)
        for group, metrics in row.subgroups.items()
        for key, value in metrics.items()
        if value is not None
    }
    if recorded != c.bundle.subgroups:
        raise Failed("the bundle's subgroup results differ from the evaluation report")
    return f"{len(recorded)} subgroup results match the report"


def _environment(c: Context) -> str:
    wanted = c.bundle.environment
    if platform.python_version_tuple()[:2] != tuple(wanted.python.split(".")[:2]):
        raise Failed(f"this bundle needs Python {wanted.python}")
    for name, pin in wanted.packages:
        try:
            found = version(name)
        except PackageNotFoundError as exc:
            raise Failed(f"{name} is not installed") from exc
        if found != pin:
            raise Failed(f"{name} {found} differs from the recorded {pin}")
    return f"Python {wanted.python}, {len(wanted.packages)} pinned packages"


def _readiness(c: Context) -> str:
    if c.bundle.family == "hybrid":
        raise Failed(HYBRID_REFUSAL)
    status = c.registry.status(c.ref)
    if status not in ("evaluated", "approved"):
        raise Failed(f"a {status} model is not usable")
    return f"status {status}"


CHECKS: tuple[tuple[str, Callable[[Context], str]], ...] = (
    ("status_log", _status_log), ("weights", _weights), ("feature_schema", _feature_schema),
    ("preprocessing", _preprocessing), ("postprocessing", _postprocessing),
    ("provenance", _provenance), ("method", _method), ("limitations", _limitations),
    ("environment", _environment), ("readiness", _readiness),
)  # fmt: skip


def _run(name: str, step: Callable[[], str]) -> CheckV1:
    try:
        return CheckV1(name=name, passed=True, detail=step())
    except FAULTS as exc:
        return CheckV1(name=name, passed=False, detail=str(exc) or type(exc).__name__)


def _context(registry: Registry, ref: ArtifactRef, folder: Path, source: Path) -> Context:
    bundle = registry.bundle(ref)
    feature = registry.record(bundle.feature, FeatureArtifactV1)
    fitted = registry.record(feature.fitted_pipeline, FittedPipelineV1)
    return Context(registry, ref, bundle, feature, fitted, folder, source)


def _outcome(status: str | None, checks: tuple[CheckV1, ...]) -> Outcome:
    if not all(c.passed for c in checks):
        return "refused"
    return "verified_approved" if status == "approved" else "verified_experimental"


def verify_bundle(
    registry: Registry, ref: ArtifactRef, folder: Path, source: Path
) -> BundleVerificationV1:
    """Every check, then the evaluator's verdict recomputed from the saved files."""
    try:
        context = _context(registry, ref, folder, source)
    except (MissingArtifactError, ArtifactIntegrityError, UnsafeArtifact, ValueError) as exc:
        fault = CheckV1(name="records", passed=False, detail=str(exc) or type(exc).__name__)
        return BundleVerificationV1(
            bundle_sha256=ref.sha256, model_name=None, status=registry.status(ref),
            outcome="refused", checks=(fault,),
        )  # fmt: skip
    rows = [_run(name, partial(step, context)) for name, step in CHECKS]
    held: list[EvaluationRecordV1] = []

    def evaluation() -> str:
        files = authority.run_files(context.bundle, folder, source)
        held.append(authority.attest(registry, ref, files))
        return f"recomputed by {held[0].evaluator}: passes={held[0].passes}"

    rows.append(_run("independent_evaluation", evaluation))
    rows.append(_run("source_file", partial(_source, context)))
    status = registry.status(ref)
    checks = tuple(rows)
    return BundleVerificationV1(
        bundle_sha256=ref.sha256, model_name=context.bundle.model_name, status=status,
        outcome=_outcome(status, checks), checks=checks, evaluation=held[0] if held else None,
    )  # fmt: skip


def _source(c: Context) -> str:
    if file_digest(c.source) != c.feature.source_sha256:
        raise Failed("the source file differs from the one this bundle was fitted on")
    return f"sha256 {c.feature.source_sha256[:12]}"

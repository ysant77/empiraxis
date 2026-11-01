"""Batch prediction from a saved bundle, with its saved preprocessing.

Every step reads the registry, so the model, the preprocessing and the postprocessing are the
reviewed bytes or the run stops. A bundle that is not approved runs only when the caller asks
for research output, and its label says so. This code never reports production readiness.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

import numpy as np

from earthlab.efficiency.artifacts import ArtifactRef
from earthlab.mlops import families, postprocess, preprocess
from earthlab.mlops.contracts import (
    FeatureArtifactV1,
    FittedPipelineV1,
    ModelBundleV1,
    PredictionV1,
    Readiness,
    Status,
)
from earthlab.mlops.registry import Registry

PRODUCTION_EVIDENCE = "production-evidence.json"


class InputRefused(ValueError):
    """The input does not fit the bundle. No prediction was made."""


def readiness(status: Status, evidence_folder: Path | None = None) -> Readiness:
    """A label from recorded facts. No flag or status alone can claim production."""
    if evidence_folder is not None and (evidence_folder / PRODUCTION_EVIDENCE).exists():
        raise InputRefused("production claims are not supported: no operational evidence path")
    return "validated_experimental" if status == "approved" else "research"


def load(registry: Registry, ref: ArtifactRef) -> tuple[ModelBundleV1, FittedPipelineV1]:
    """The bundle and its preprocessing, checked for agreement before any use."""
    bundle = registry.bundle(ref)
    feature = registry.record(bundle.feature, FeatureArtifactV1)
    fitted = registry.record(feature.fitted_pipeline, FittedPipelineV1)
    if feature.feature_names != fitted.feature_names:
        raise InputRefused("the feature record and its preprocessing disagree")
    if bundle.task == "regression" and bundle.postprocess.alarm_cut is not None:
        raise InputRefused("a regression bundle cannot hold an alarm cut")
    if bundle.task == "classification" and (
        bundle.postprocess.invert_scaling or bundle.postprocess.clip_nonnegative
    ):
        raise InputRefused("a classification bundle cannot hold regression steps")
    return bundle, fitted


def predict_batch(
    registry: Registry,
    ref: ArtifactRef,
    values: np.ndarray,
    columns: tuple[str, ...],
    source_sha256: str,
    issues: np.ndarray,
    when: list[datetime],
    allow_research: bool = False,
) -> list[PredictionV1]:
    status = registry.status(ref)
    if status is None:
        raise InputRefused("this bundle is not registered")
    if status == "rejected" or (status != "approved" and not allow_research):
        raise InputRefused(f"a {status} bundle does not serve this request")
    bundle, fitted = load(registry, ref)
    if columns != fitted.columns:
        raise InputRefused(f"the input columns {columns} differ from {fitted.columns}")
    begun = time.perf_counter()
    built = preprocess.build(fitted, values, issues, len(values) + 1, when)
    if built.dropped or len(built.x) == 0:
        raise InputRefused(f"{built.dropped} rows have a missing feature")
    state = registry.arrays(bundle.weights_sha256)
    raw = families.predict(bundle.method_id, bundle.task, built.x, state, bundle.config)
    if bundle.task == "regression":
        output = postprocess.regression(fitted, bundle.postprocess, raw)
    else:
        output = postprocess.classification(bundle.postprocess, raw)
    warnings = postprocess.input_warnings(built.x, built.names)
    seconds = round((time.perf_counter() - begun) / len(built.x), 6)
    label = readiness(status)
    return [
        PredictionV1(
            bundle_sha256=ref.sha256, status=status, readiness=label, issue_index=int(issue),
            values=tuple(float(v) for v in row), output_names=bundle.output_names,
            warnings=tuple(warn), source_sha256=source_sha256, seconds=seconds,
        )
        for issue, row, warn in zip(built.issues, output, warnings, strict=True)
    ]  # fmt: skip

"""The evaluator's verdict on one bundle, recomputed and never taken from the caller.

The code rebuilds the bundle's predictions from its saved weights and preprocessing, compares
them with the stored prediction file, and scores that file with the independent evaluator
against the published source. The result must equal the saved report row. A hybrid is not
reproduced here, so it can fail but cannot pass.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.digest import file_digest, payload_digest
from earthlab.efficiency.artifacts import ArtifactRef
from earthlab.forecast import evaluator as forecast_eval
from earthlab.forecast import gate
from earthlab.forecast import samples as S
from earthlab.forecast.dataset import label_at, load_grid
from earthlab.harness import eval_classify
from earthlab.harness.classify import HORIZON, SCORED_FROM, THRESHOLD
from earthlab.harness.contracts import EvaluationReportV1, ModelScore
from earthlab.mlops import families, postprocess, preprocess
from earthlab.mlops.contracts import FeatureArtifactV1, FittedPipelineV1, ModelBundleV1, Status
from earthlab.mlops.evidence import EvaluationRecordV1, Reproduction
from earthlab.mlops.registry import Registry, load_arrays
from earthlab.mlops.serve import load

REGRESSION_EVALUATOR, CLASSIFICATION_EVALUATOR = (
    "earthlab.forecast.evaluator", "earthlab.harness.eval_classify",
)  # fmt: skip
CODE = {
    REGRESSION_EVALUATOR: forecast_eval.__file__,
    CLASSIFICATION_EVALUATOR: eval_classify.__file__,
}
TOLERANCE = 1e-6
ROUNDING = 1e-9


class EvidenceRefused(ValueError):
    """The saved files do not support a verdict. No status changed."""


@dataclass(frozen=True)
class RunFiles:
    report: Path
    predictions: Path
    source: Path
    row: str


@dataclass(frozen=True)
class Rescored:
    metrics: dict[str, float | None]
    reasons: tuple[str, ...]
    passes: bool


def run_files(
    bundle: ModelBundleV1, folder: Path, source: Path, row: str | None = None
) -> RunFiles:
    """Where a families run keeps this bundle's report and predictions."""
    if bundle.task == "regression":
        name = row or f"M_{bundle.method_id}"
        return RunFiles(
            folder / "families-regression-evaluation.json", folder / f"predictions-{name}.npz",
            source, name,
        )  # fmt: skip
    name = row or bundle.method_id
    return RunFiles(
        folder / "families-classification-evaluation.json", folder / f"probabilities-{name}.npz",
        source, name,
    )  # fmt: skip


def protocol_digest(evaluator: str) -> str:
    """The metric rule: the gate code, the primary horizon, and the threshold."""
    if evaluator == REGRESSION_EVALUATOR:
        rule: dict[str, Any] = {
            "gate": file_digest(Path(gate.__file__)),
            "horizon": S.PRIMARY_HORIZON,
        }
    else:
        rule = {"horizon": HORIZON, "threshold": THRESHOLD, "scored_from": SCORED_FROM}
    return payload_digest({"evaluator": evaluator, **rule})


def reproduce(
    registry: Registry, bundle: ModelBundleV1, fitted: FittedPipelineV1, values: np.ndarray,
    issues: np.ndarray,
) -> np.ndarray:  # fmt: skip
    """Saved weights and preprocessing on these issues, before any alarm cut."""
    when = [label_at(int(i)) for i in issues]
    built = preprocess.build(fitted, values, issues, S.SEALED_FROM, when)
    state = registry.arrays(bundle.weights_sha256)
    raw = families.predict(bundle.method_id, bundle.task, built.x, state, bundle.config)
    if bundle.task == "regression":
        return postprocess.regression(fitted, bundle.postprocess, raw)
    bare = bundle.postprocess.model_copy(update={"alarm_cut": None})
    return postprocess.classification(bare, raw)


def _rescore_regression(truth: np.ndarray, saved: dict[str, np.ndarray], row: str) -> Rescored:
    issues, predictions = saved["issues"], saved["predictions"]
    if [int(h) for h in saved["horizons"]] != [S.PRIMARY_HORIZON]:
        raise EvidenceRefused("the prediction file does not hold the primary horizon")
    table = forecast_eval.evaluate(truth, issues, [S.PRIMARY_HORIZON], predictions)
    line = table[str(S.PRIMARY_HORIZON)]
    reasons = gate.verdict(row, {"metrics": table}).reasons
    metrics = {
        "mae": round(line["all"]["mae"], 3), "skill": round(line["mean_skill"], 4),
        "above_55_mae": round(line["above_55"]["mae"], 3),
    }  # fmt: skip
    return Rescored(metrics, tuple(reasons), not reasons)


def _rescore_classification(truth: np.ndarray, saved: dict[str, np.ndarray]) -> Rescored:
    issues, prob, cut = saved["issues"], saved["probabilities"], float(saved["cut"])
    y = eval_classify.labels(truth, issues, HORIZON, THRESHOLD)
    base = eval_classify.persistence_alarm(truth, issues, THRESHOLD)
    metrics = eval_classify.score(prob, cut, y)
    reasons = eval_classify.failed_checks(metrics, eval_classify.f1_gain(prob, cut, base, y))
    return Rescored(metrics, tuple(reasons), not reasons)


def _agree(row: ModelScore, again: Rescored) -> None:
    if (row.passes, tuple(row.reasons)) != (again.passes, again.reasons):
        raise EvidenceRefused("the recomputed verdict differs from the report")
    for key, value in again.metrics.items():
        kept = row.metrics.get(key)
        same = value is None and kept is None
        if not same and (value is None or kept is None or abs(value - kept) > ROUNDING):
            raise EvidenceRefused(f"the recomputed {key} differs from the report")


def read_predictions(files: RunFiles, task: str) -> tuple[dict[str, np.ndarray], str]:
    """The stored prediction file, with its digest checked against the evaluator's record."""
    if not files.predictions.is_file():
        raise EvidenceRefused(f"no prediction artifact: {files.predictions.name}")
    digest = file_digest(files.predictions)
    if task == "regression":
        sidecar = files.report.parent / f"evaluation-{files.row}.json"
        if not sidecar.is_file():
            raise EvidenceRefused(f"no evaluator record: {sidecar.name}")
        if json.loads(sidecar.read_text(encoding="utf-8"))["predictions_sha256"] != digest:
            raise EvidenceRefused("the prediction file is not the one the evaluator scored")
    return load_arrays(files.predictions, digest), digest


def _report(bundle: ModelBundleV1, files: RunFiles) -> tuple[EvaluationReportV1, ModelScore, str]:
    if bundle.evaluation_sha256 is None:
        raise EvidenceRefused("the bundle names no evaluation report")
    if not files.report.is_file():
        raise EvidenceRefused(f"no evaluation report: {files.report.name}")
    digest = file_digest(files.report)
    if digest != bundle.evaluation_sha256:
        raise EvidenceRefused("the evaluation report is not the one this bundle names")
    report = EvaluationReportV1.model_validate_json(files.report.read_bytes())
    code = CODE.get(report.evaluator)
    if code is None:
        raise EvidenceRefused(f"{report.evaluator} is not a trusted evaluator")
    if file_digest(Path(code)) != report.evaluator_sha256:
        raise EvidenceRefused("the evaluator code differs from the code that wrote the report")
    rows = [s for s in report.scores if s.model == files.row]
    if not rows:
        raise EvidenceRefused(f"the report has no row {files.row}")
    return report, rows[0], digest


def _bind_issues(
    registry: Registry, feature: FeatureArtifactV1, issues: np.ndarray, horizon: int
) -> None:
    if int(issues.max()) + horizon >= S.SEALED_FROM:
        raise EvidenceRefused("a scored sample reaches the sealed period")
    stored = registry.arrays(feature.matrix_sha256)
    known = [v for k, v in stored.items() if k.endswith("_issues")]
    if not any(np.isin(issues, v).all() for v in known):
        raise EvidenceRefused("the scored issues are not in the feature artifact")


def _same_predictions(made: np.ndarray, kept: np.ndarray) -> None:
    if made.shape != kept.shape or not np.allclose(
        made, kept, rtol=0.0, atol=TOLERANCE, equal_nan=True
    ):
        raise EvidenceRefused("the bundle does not reproduce the stored predictions")


def attest(registry: Registry, ref: ArtifactRef, files: RunFiles) -> EvaluationRecordV1:
    """Recompute one model row. Any disagreement raises, so no record exists."""
    bundle = registry.bundle(ref)
    feature = registry.record(bundle.feature, FeatureArtifactV1)
    fitted = registry.record(feature.fitted_pipeline, FittedPipelineV1)
    if bundle.family != "hybrid":
        load(registry, ref)
    report, row, report_sha = _report(bundle, files)
    grid = load_grid(files.source)[0]
    truth, source_sha = forecast_eval.read_truth(files.source)
    if source_sha != feature.source_sha256 or source_sha != fitted.source_sha256:
        raise EvidenceRefused("the source file is not the one this bundle was fitted on")
    saved, predictions_sha = read_predictions(files, bundle.task)
    regression = bundle.task == "regression"
    _bind_issues(registry, feature, saved["issues"], S.PRIMARY_HORIZON if regression else HORIZON)
    kept = saved["predictions"][:, 0, :] if regression else saved["probabilities"]
    reproduction: Reproduction = "unsupported_hybrid"
    if bundle.family != "hybrid":
        values = grid.values[: S.SEALED_FROM]
        _same_predictions(reproduce(registry, bundle, fitted, values, saved["issues"]), kept)
        reproduction = "exact"
    if regression:
        again = _rescore_regression(truth, saved, files.row)
    else:
        if float(saved["cut"]) != bundle.postprocess.alarm_cut:
            raise EvidenceRefused("the scored alarm cut differs from the bundle")
        again = _rescore_classification(truth, saved)
    _agree(row, again)
    return EvaluationRecordV1(
        bundle_sha256=ref.sha256, model_row=files.row, evaluator=report.evaluator,
        evaluator_sha256=report.evaluator_sha256, protocol_sha256=protocol_digest(report.evaluator),
        report_sha256=report_sha, source_sha256=source_sha, feature_sha256=bundle.feature.sha256,
        predictions_sha256=predictions_sha, split_scored=report.split_scored,
        reference=report.reference, reproduction=reproduction, passes=again.passes,
        reasons=again.reasons, metrics=again.metrics,
    )  # fmt: skip


def admit(registry: Registry, ref: ArtifactRef, files: RunFiles) -> Status:
    """Attest, then let the registry decide. A hybrid that passes stays a candidate."""
    record = attest(registry, ref, files)
    if record.passes and record.reproduction != "exact":
        return "candidate"
    return registry.evaluate(ref, record, files.report)


__all__ = ["EvidenceRefused", "RunFiles", "admit", "attest", "reproduce", "run_files"]

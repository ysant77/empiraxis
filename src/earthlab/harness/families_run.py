"""Registered methods on the real NEA series, scored by the existing independent evaluators.

This is a thin path, not a second controller. The Workbench and the scenario adapters keep
the lifecycle, the splits and the scoring. This module only builds features and bundles
through `earthlab.mlops`, runs each eligible method on the same samples as the scenario, and
registers each result as a candidate. The evaluator's verdict moves it on. Only validation
years are scored, and the sealed test period is never an input.
"""

from __future__ import annotations

import json
import platform
import subprocess
from dataclasses import dataclass, field
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.digest import file_digest
from earthlab.efficiency.artifacts import ArtifactRef
from earthlab.forecast import samples as S
from earthlab.forecast.contracts import LIMITATIONS
from earthlab.forecast.dataset import REGIONS, label_at
from earthlab.forecast.pipeline import SEED, SOURCE
from earthlab.harness import eval_classify as independent
from earthlab.harness.classify import (
    BASE,
    HORIZON,
    RATE,
    SCORED_FROM,
    THRESHOLD,
    ClassificationAdapter,
)
from earthlab.harness.contracts import EvaluationReportV1
from earthlab.harness.regression import RegressionAdapter
from earthlab.mlops import families, postprocess, preprocess
from earthlab.mlops.contracts import (
    ColumnRule,
    DatasetSchemaV1,
    EnvironmentV1,
    FeatureArtifactV1,
    FittedPipelineV1,
    ModelBundleV1,
    ModelCardV1,
    PipelineConfigV1,
    PostprocessV1,
    Span,
)
from earthlab.mlops.families import Facts
from earthlab.mlops.quality import validate
from earthlab.mlops.registry import Registry

WINDOW = 48
PRIMARY = S.PRIMARY_HORIZON
UNIT = "ug/m3"
REGRESSION_METHODS = ("persistence", "climatology", "ridge", "trees")
CLASSIFICATION_METHODS = ("logistic", "trees_classifier")
Config = dict[str, float | int | str | bool]


def _default_configs() -> dict[str, Config]:
    tree: Config = {"trees": 40, "depth": 3, "rate": 0.2}
    return {
        "persistence": {}, "climatology": {}, "ridge": {"alpha": 100.0}, "trees": tree,
        "logistic": {"penalty": 1.0, "balanced": True}, "trees_classifier": dict(tree),
    }  # fmt: skip


@dataclass(frozen=True)
class RunSpec:
    """Lags for the feature pipeline and one config per method ID."""

    lags: int = 12
    configs: dict[str, Config] = field(default_factory=_default_configs)


@dataclass(frozen=True)
class Prepared:
    fitted: FittedPipelineV1
    feature: ArtifactRef
    x: dict[str, np.ndarray]
    scaled: np.ndarray


@dataclass(frozen=True)
class Fit:
    method_id: str
    config: Config
    state: dict[str, np.ndarray]
    train_metric: float


def _revision() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "HEAD"],  # noqa: S607
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    return done.stdout.strip() or "unknown"


def _environment() -> EnvironmentV1:
    pins = (("numpy", version("numpy")), ("pydantic", version("pydantic")))
    return EnvironmentV1(python=platform.python_version(), packages=pins)


def _quality(values: np.ndarray, source_sha: str, folder: Path) -> list[str]:
    """Check the usable rows only. The report is saved and its issues are returned."""
    schema = DatasetSchemaV1(
        dataset_id="nea-pm25-1h", cadence_hours=1, min_coverage=0.8,
        columns=tuple(ColumnRule(name=r, unit=UNIT, low=0.0, high=1000.0) for r in REGIONS),
    )  # fmt: skip
    stamps = np.arange(len(values))
    report = validate(schema, stamps, values, REGIONS, (UNIT,) * len(REGIONS), source_sha)
    (folder / "quality-report.json").write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return list(report.issues)


def _prepare(
    registry: Registry,
    values: np.ndarray,
    source_sha: str,
    lags: int,
    issues: dict[str, np.ndarray],
) -> Prepared:
    """Fit on the train span, build every split's matrix and store the feature artifact."""
    train_end = S.split_bounds("train")[1]
    config = PipelineConfigV1(
        lags=lags, calendar=True, availability_offset_hours=S.USABLE_OFFSET, missing="mask"
    )
    fitted = preprocess.fit(
        config, values, REGIONS, Span(first=0, last=train_end), train_end, source_sha
    )
    x, arrays = {}, {}
    for name, rows in issues.items():
        when = [label_at(int(i)) for i in rows]
        built = preprocess.build(fitted, values, rows, S.SEALED_FROM, when)
        x[name] = built.x
        arrays[f"{name}_x"], arrays[f"{name}_issues"] = built.x, rows
    last = max(int(v.max()) for k, v in issues.items() if k != "train")
    first = min(int(v.min()) for k, v in issues.items() if k != "train")
    artifact = FeatureArtifactV1(
        fitted_pipeline=registry.store.put_record(fitted), source_sha256=source_sha,
        train_span=Span(first=0, last=train_end), validation_span=Span(first=first, last=last),
        feature_names=fitted.feature_names, availability_offset_hours=S.USABLE_OFFSET,
        last_input_index=last - S.USABLE_OFFSET, rows=sum(len(m) for m in x.values()),
        dropped_rows=0, code_revision=_revision(), matrix_sha256=registry.put_arrays(arrays),
    )  # fmt: skip
    return Prepared(
        fitted, registry.put_feature(fitted, artifact), x, preprocess.scale(fitted, values)
    )


def _fit_all(
    task: families.Task,
    ids: tuple[str, ...],
    spec: RunSpec,
    facts: Facts,
    x: np.ndarray,
    y: np.ndarray,
) -> tuple[dict[str, Fit], dict[str, str]]:
    """Fit each eligible method. A blocked method is returned with the reason, never run."""
    blocked = {k: v for k, v in families.eligible(facts).items() if v is not None}
    fits: dict[str, Fit] = {}
    for method_id in ids:
        if method_id in blocked:
            continue
        config = spec.configs[method_id]
        state = families.train(method_id, task, x, y, config, SEED)
        fit = np.asarray(families.predict(method_id, task, x, state, config))
        fits[method_id] = Fit(method_id, config, state, float(np.nanmean(np.abs(fit - y))))
    return fits, blocked


def _card(intended: str) -> ModelCardV1:
    return ModelCardV1(intended_use=intended, limitations=LIMITATIONS)


def _register(
    registry: Registry, prep: Prepared, fit: Fit, task: families.Task, post: PostprocessV1,
    report_path: Path, score: Any, name: str,
) -> dict[str, Any]:  # fmt: skip
    """Store the bundle, then let the evaluator's verdict move it. A human decides later."""
    method = families.METHODS[fit.method_id]
    bundle = ModelBundleV1(
        model_name=name, method_id=fit.method_id, family=method.family, task=task,
        config=fit.config, weights_sha256=registry.put_arrays(fit.state), feature=prep.feature,
        postprocess=post, output_names=REGIONS, seed=SEED, environment=_environment(),
        training_metrics={"train_mean_abs_error_in_fit_space": fit.train_metric},
        subgroups={k: float(v) for k, v in _numbers(score.subgroups).items()},
        evaluation_sha256=file_digest(report_path),
        card=_card(f"Research comparison of {fit.method_id} on historical NEA PM2.5."),
        code_revision=_revision(),
    )  # fmt: skip
    ref = registry.register(bundle)
    status = registry.evaluate(ref, report_path, bool(score.passes))
    return {"model": score.model, "bundle": ref.sha256, "status": status,
            "reasons": list(score.reasons)}  # fmt: skip


def _numbers(groups: dict[str, dict[str, float | None]]) -> dict[str, float]:
    return {
        f"{group}_{key}": float(value)
        for group, metrics in groups.items()
        for key, value in metrics.items()
        if value is not None
    }


def _write_report(folder: Path, name: str, report: EvaluationReportV1) -> Path:
    path = folder / f"families-{name}-evaluation.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path


def _summary(
    scenario: str, registry: Registry, report: EvaluationReportV1, path: Path,
    bundles: list[dict[str, Any]], blocked: dict[str, str], quality: list[str],
    notes: dict[str, list[str]],
) -> dict[str, Any]:  # fmt: skip
    summary = {
        "scenario": scenario, "registry": str(registry.root), "report": str(path),
        "split_scored": report.split_scored, "bundles": bundles, "blocked": blocked,
        "quality_issues": quality, "notes": notes,
        "scores": {s.model: {"passes": s.passes, "low": s.low, "high": s.high}
                   for s in report.scores},
    }  # fmt: skip
    (path.parent / f"families-{scenario}-summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    return summary


def run_regression(
    folder: Path, registry_root: Path, source: Path = SOURCE, spec: RunSpec | None = None
) -> dict[str, Any]:
    """S1: PM2.5 at T+6 h for five regions. Same samples as the pm25-regression scenario."""
    spec = spec or RunSpec()
    adapter, registry = RegressionAdapter(folder, source), Registry(registry_root)
    bench = adapter.bench
    bench.baselines(WINDOW)
    values = bench.grid.values[: S.SEALED_FROM]
    issues = {
        "train": S.issue_times("train", WINDOW),
        "validation": S.issue_times("validation", WINDOW),
    }
    quality = _quality(values, bench.truth_sha, folder)
    prep = _prepare(registry, values, bench.truth_sha, spec.lags, issues)
    y_train = prep.scaled[issues["train"] + PRIMARY]
    facts = Facts("regression", len(y_train), None, True, True)
    fits, blocked = _fit_all(
        "regression", REGRESSION_METHODS, spec, facts, prep.x["train"], y_train
    )
    post = PostprocessV1(invert_scaling=True, clip_nonnegative=True)
    for method_id, fit in fits.items():
        raw = families.predict(method_id, "regression", prep.x["validation"], fit.state, fit.config)
        out = postprocess.regression(prep.fitted, post, raw)
        bench.score(f"M_{method_id}", issues["validation"], out[:, None, :], (PRIMARY,))
    report = adapter.evaluate()
    path = _write_report(folder, "regression", report)
    rows = {s.model: s for s in report.scores}
    bundles = [
        _register(registry, prep, fit, "regression", post, path, rows[f"M_{k}"], f"s1-{k}")
        for k, fit in fits.items()
    ]
    return _summary("regression", registry, report, path, bundles, blocked, quality, {})


def _rate_rows(adapter: ClassificationAdapter, y_train: np.ndarray) -> None:
    """The two reference rows the scenario keeps: the train rate and the persistence alarm."""
    rate = np.nanmean(y_train, axis=0)
    adapter.rows[RATE] = (np.tile(rate, (len(adapter.issues), 1)), 0.5)
    adapter.rows[BASE] = (
        independent.persistence_alarm(adapter.truth, adapter.issues, THRESHOLD), 0.5
    )  # fmt: skip


def _declare(raw_tune: np.ndarray, y_tune: np.ndarray) -> tuple[PostprocessV1, float, list[str]]:
    """Calibration and the alarm cut come from the tune years. A failure is returned as a note."""
    notes: list[str] = []
    calibration = None
    try:
        calibration = postprocess.fit_calibration(raw_tune, y_tune)
    except ValueError as exc:
        notes.append(str(exc))
    probe = PostprocessV1(calibration=calibration)
    cut = postprocess.best_cut(postprocess.classification(probe, raw_tune), y_tune)
    return PostprocessV1(calibration=calibration, alarm_cut=cut), cut, notes


def run_classification(
    folder: Path, registry_root: Path, source: Path = SOURCE, spec: RunSpec | None = None
) -> dict[str, Any]:
    """S2: PM2.5 above 35 ug/m3 at T+6 h. Same samples as the pm25-exceedance scenario."""
    spec = spec or RunSpec()
    folder.mkdir(parents=True, exist_ok=True)
    adapter, registry = ClassificationAdapter(folder, source), Registry(registry_root)
    window = spec.lags + 8
    valid = S.issue_times("validation", window, (HORIZON,))
    issues = {
        "train": S.issue_times("train", window, (HORIZON,)),
        "tune": valid[valid + HORIZON < SCORED_FROM], "scored": valid[valid >= SCORED_FROM],
    }  # fmt: skip
    adapter.issues = issues["scored"]
    values = adapter.grid.values[: S.SEALED_FROM]
    quality = _quality(values, adapter.truth_sha, folder)
    prep = _prepare(registry, values, adapter.truth_sha, spec.lags, issues)
    y = {k: independent.labels(adapter.truth, v, HORIZON, THRESHOLD) for k, v in issues.items()}
    _rate_rows(adapter, y["train"])
    facts = Facts("classification", len(y["train"]), int(np.nansum(y["train"])), True, True)
    fits, blocked = _fit_all(
        "classification", CLASSIFICATION_METHODS, spec, facts, prep.x["train"], y["train"]
    )
    posts: dict[str, PostprocessV1] = {}
    notes: dict[str, list[str]] = {}
    for method_id, fit in fits.items():
        raw = {k: families.predict(method_id, "classification", prep.x[k], fit.state, fit.config)
               for k in ("tune", "scored")}  # fmt: skip
        posts[method_id], cut, notes[method_id] = _declare(raw["tune"], y["tune"])
        prob = postprocess.classification(posts[method_id].model_copy(update={"alarm_cut": None}),
                                          raw["scored"])  # fmt: skip
        adapter.rows[method_id] = (prob, cut)
    report = adapter.evaluate()
    path = _write_report(folder, "classification", report)
    rows = {s.model: s for s in report.scores}
    bundles = [
        _register(registry, prep, fit, "classification", posts[k], path, rows[k], f"s2-{k}")
        for k, fit in fits.items()
    ]
    return _summary("classification", registry, report, path, bundles, blocked, quality, notes)

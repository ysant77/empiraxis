"""Scenario B: will a region exceed an experimental concentration threshold at T+6 h?

The threshold is an experimental value, not an AQI or PSI category and not a haze label. It
was set from the train split's positive rate alone. Models fit on 2014 to 2018. The alarm cut
is tuned on 2019 to 2021, and only 2022 to 2023 is scored. The test period is not read.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import numpy as np
from pydantic import BaseModel, Field, field_validator

from earthlab.contracts import Strict
from earthlab.digest import file_digest
from earthlab.forecast import samples as S
from earthlab.forecast.dataset import index_of, load_grid
from earthlab.forecast.evaluator import read_truth
from earthlab.harness import eval_classify as independent
from earthlab.harness.contracts import (
    BudgetV1,
    DatasetProfileV1,
    DecisionRecordV1,
    EvaluationReportV1,
    ExperimentPlanV1,
    ModelScore,
    ProblemSpecV1,
    SourceRef,
)
from earthlab.harness.seats import Seats

THRESHOLD = 35.0
HORIZON = 6
SCORED_FROM = index_of(datetime(2022, 1, 1))
PENALTIES = (0.1, 1.0, 10.0, 100.0)
NEWTON_STEPS = 12
BASE, RATE, LOGIT = "persistence_alarm", "train_rate", "logistic"
LABEL = "Historical classification with modelled availability"
LIMITATIONS = (
    "Non-operational research result.",
    "Historical evaluation. Not a forecast of any future date.",
    f"{THRESHOLD:g} ug/m3 is an experimental threshold, not an AQI or PSI category.",
    "PM2.5 concentration alone does not identify wildfire haze or its cause.",
    "Not for health, safety or travel decisions.",
)
EXCEED_PROBLEM = ProblemSpecV1(
    problem_id="pm25-exceedance-6h", kind="classification", variable="pm25", unit="ug/m3",
    domain="five NEA reporting regions, hourly",
    target=f"regional hourly PM2.5 above {THRESHOLD:g} ug/m3 at T+6 h", horizon_hours=HORIZON,
    threshold=THRESHOLD, permitted_evidence=("NEA historical 1-hour PM2.5",),
    success_criteria=(
        "lower 95% limit of F1 gain over the persistence alarm above zero",
        "precision and PR area above the base rate", "not the majority class",
    ),
)  # fmt: skip


class ClassifierChoice(Strict):
    lags: Literal[6, 12, 24, 48]
    penalty: float
    balanced: bool
    reason: str = Field(min_length=5, max_length=400)

    @field_validator("penalty")
    @classmethod
    def _menu(cls, value: float) -> float:
        if value not in PENALTIES:
            raise ValueError(f"the penalty must be one of {PENALTIES}")
        return value


PRESET = ClassifierChoice(
    lags=24, penalty=1.0, balanced=True, reason="The preset for the arm with no model."
)


def fit_logistic(x: np.ndarray, y: np.ndarray, penalty: float, balanced: bool) -> np.ndarray:
    """Weights with an intercept, by Newton steps. Rows with a missing label are left out."""
    keep = ~np.isnan(y)
    design = np.hstack([x[keep], np.ones((int(keep.sum()), 1))])
    t = y[keep]
    share = float(t.mean())
    each = np.where(t > 0.5, 0.5 / share, 0.5 / (1 - share)) if balanced else np.ones(len(t))
    weights = np.zeros(design.shape[1])
    ridge = penalty * np.eye(len(weights))
    ridge[-1, -1] = 0.0
    for _ in range(NEWTON_STEPS):
        prob = 1 / (1 + np.exp(-np.clip(design @ weights, -30, 30)))
        slope = design.T @ (each * (prob - t)) + ridge @ weights
        curve = (design.T * (each * np.maximum(prob * (1 - prob), 1e-6))) @ design + ridge
        weights -= np.linalg.solve(curve, slope)
    return weights


def apply_logistic(x: np.ndarray, weights: np.ndarray) -> np.ndarray:
    return np.asarray(
        1 / (1 + np.exp(-np.clip(np.hstack([x, np.ones((len(x), 1))]) @ weights, -30, 30)))
    )


def best_cut(prob: np.ndarray, y: np.ndarray) -> float:
    """The alarm cut with the best pooled F1 on the tuning years."""
    keep = ~np.isnan(y) & ~np.isnan(prob)
    p, t = prob[keep], y[keep] > 0.5
    grid = np.linspace(0.02, 0.98, 49)
    said = p[:, None] >= grid
    hits, shown = (said & t[:, None]).sum(axis=0), said.sum(axis=0)
    return float(grid[int(np.argmax(2 * hits / np.maximum(shown + t.sum(), 1)))])


class ClassificationAdapter:
    label = LABEL
    methods: tuple[str, ...] = ("persistence", "climatology", "logistic")
    limitations: tuple[str, ...] = LIMITATIONS
    menu: type[BaseModel] = ClassifierChoice

    def __init__(self, run_dir: Path, source: Path = Path("data/nea/Historical1hrPM2.5.csv")):
        self.folder, self.source = run_dir, source
        self.grid, self.audit = load_grid(source)
        self.truth, self.truth_sha = read_truth(source)
        self.rows: dict[str, tuple[np.ndarray, float]] = {}
        self.issues = np.empty(0, dtype=np.int64)
        self.x_train = self.x_tune = self.x_score = np.empty(0)
        self.train_issues = np.empty(0, dtype=np.int64)
        self.tune_issues = np.empty(0, dtype=np.int64)

    def measure(self, problem: ProblemSpecV1) -> DatasetProfileV1:
        first, last = S.split_bounds("train")
        part = self.grid.values[first : last + 1]
        rate = float(np.nanmean(part[~np.isnan(part)] > THRESHOLD))
        return DatasetProfileV1(
            sources=(SourceRef(name=self.source.name, sha256=self.truth_sha),),
            variable="pm25", unit="ug/m3", usable_rows=self.audit.grid_hours,
            missing_fraction=float(np.isnan(part).mean()), labels_present=True,
            label_provenance="thresholded from the published NEA series",
            granularity="1 h, five regions", positive_rate=rate,
            availability_latency_hours=S.USABLE_OFFSET,
            leakage_risks=("labels never enter the features",
                           "the alarm cut is tuned before the scored years"),
        )  # fmt: skip

    def preset(self) -> BaseModel:
        return PRESET

    def plan(
        self, choice: BaseModel, plan_id: str, by: Literal["preset", "model"]
    ) -> ExperimentPlanV1:
        spec = ClassifierChoice.model_validate(choice.model_dump())
        return ExperimentPlanV1(
            plan_id=plan_id, methods=("persistence", "climatology", "logistic"),
            config=spec.model_dump(exclude={"reason"}),
            split_protocol="fit 2014-2018; tune cut 2019-2021; score 2022-2023; test sealed",
            metrics=("precision", "recall", "f1", "false_alarm_rate", "pr_auc", "brier", "ece"),
            input_offset_hours=S.USABLE_OFFSET, seed=0, decided_by=by,
            budget=BudgetV1(max_seconds=5400, max_training_seconds=300, max_model_calls=40),
        )  # fmt: skip

    def estimate(self, plan: ExperimentPlanV1) -> float:
        return 5.0

    def prepare(self, plan: ExperimentPlanV1) -> dict[str, Any]:
        lags = int(plan.config["lags"])
        scaler = S.fit_scaler(self.grid, log=True)
        scaled = scaler.apply(self.grid.values)
        valid = S.issue_times("validation", lags + 8, (HORIZON,))
        self.train_issues = S.issue_times("train", lags + 8, (HORIZON,))
        self.tune_issues = valid[valid + HORIZON < SCORED_FROM]
        self.issues = valid[valid >= SCORED_FROM]
        self.x_train = S.lag_matrix(scaled, self.train_issues, lags)
        self.x_tune = S.lag_matrix(scaled, self.tune_issues, lags)
        self.x_score = S.lag_matrix(scaled, self.issues, lags)
        return {"train": len(self.train_issues), "tune": len(self.tune_issues),
                "scored": len(self.issues), "lags": lags}  # fmt: skip

    def _keep(self, name: str, prob: np.ndarray, cut: float) -> None:
        self.rows[name] = (prob, cut)
        path = self.folder / f"probabilities-{name}.npz"
        np.savez(path, issues=self.issues, probabilities=prob, cut=np.array(cut))

    def train(self, plan: ExperimentPlanV1, seats: Seats) -> dict[str, Any]:
        y_train = independent.labels(self.truth, self.train_issues, HORIZON, THRESHOLD)
        y_tune = independent.labels(self.truth, self.tune_issues, HORIZON, THRESHOLD)
        rate = np.nanmean(y_train, axis=0)
        self._keep(RATE, np.tile(rate, (len(self.issues), 1)), 0.5)
        self._keep(BASE, independent.persistence_alarm(self.truth, self.issues, THRESHOLD), 0.5)
        tune, scored = [], []
        for region in range(y_train.shape[1]):
            weights = fit_logistic(
                self.x_train, y_train[:, region], float(plan.config["penalty"]),
                bool(plan.config["balanced"]),
            )  # fmt: skip
            tune.append(apply_logistic(self.x_tune, weights))
            scored.append(apply_logistic(self.x_score, weights))
        cut = best_cut(np.stack(tune, axis=1), y_tune)
        self._keep(LOGIT, np.stack(scored, axis=1), cut)
        return {"model_id": LOGIT, "alarm_cut": cut}

    def evaluate(self) -> EvaluationReportV1:
        y = independent.labels(self.truth, self.issues, HORIZON, THRESHOLD)
        base = self.rows[BASE][0]
        scores = []
        for name, (prob, cut) in self.rows.items():
            row = independent.score(prob, cut, y)
            gain = independent.f1_gain(prob, cut, base, y)
            reasons = () if name == BASE else tuple(independent.failed_checks(row, gain))
            regions = {
                f"region_{i}": {"f1": independent.score(prob[:, [i]], cut, y[:, [i]])["f1"]}
                for i in range(y.shape[1])
            }
            scores.append(ModelScore(
                model=name, metrics=row, low=gain["low"], high=gain["high"],
                passes=name != BASE and not reasons, reasons=reasons, subgroups=regions,
            ))  # fmt: skip
        return EvaluationReportV1(
            evaluator="earthlab.harness.eval_classify",
            evaluator_sha256=file_digest(Path(independent.__file__)),
            split_scored="validation years 2022 to 2023", reference=BASE, scores=tuple(scores),
            notes=("the test period was not read", "limits are of F1 gain over persistence"),
        )  # fmt: skip

    def _row(self, report: EvaluationReportV1, name: str) -> ModelScore:
        return next(s for s in report.scores if s.model == name)

    def _uncalibrated(self, report: EvaluationReportV1, name: str) -> float | None:
        ece = self._row(report, name).metrics["ece"]
        return ece if ece is not None and ece > independent.MAX_ECE else None

    def limits(self, report: EvaluationReportV1, chosen: str | None) -> tuple[str, ...]:
        ece = self._uncalibrated(report, chosen) if chosen == LOGIT else None
        if ece is None:
            return LIMITATIONS
        text = f"Calibration error is {ece:.3f}, so {chosen} scores are ranks, not probabilities."
        return (*LIMITATIONS, text)

    def allowed(self, report: EvaluationReportV1) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {"abstain": [], "retain_baseline": [BASE]}
        if self._row(report, LOGIT).passes:
            out["adopt_limited" if self._uncalibrated(report, LOGIT) else "adopt"] = [LOGIT]
        return out

    def decide(self, report: EvaluationReportV1) -> DecisionRecordV1:
        row = self._row(report, LOGIT)
        if not row.passes:
            return DecisionRecordV1(
                outcome="retain_baseline", selected=BASE, rejected=(LOGIT, RATE),
                reason="The classifier failed a check; persistence stays the reference.",
                limitations=LIMITATIONS,
            )  # fmt: skip
        return DecisionRecordV1(
            outcome="adopt_limited" if self._uncalibrated(report, LOGIT) else "adopt",
            selected=LOGIT, rejected=(BASE, RATE), reason="The rule applied by code.",
            limitations=self.limits(report, LOGIT),
        )  # fmt: skip

    def acceptance(self, report: EvaluationReportV1) -> dict[str, bool]:
        rate = self._row(report, RATE)
        return {
            "class_balance_reported": rate.metrics["base_rate"] is not None,
            "majority_class_rejected": not rate.passes,
            "same_hours_for_every_model": all(
                len(prob) == len(self.issues) for prob, _ in self.rows.values()
            ),
            "no_scored_issue_reaches_test": int(self.issues.max()) + HORIZON < S.SEALED_FROM,
            "calibration_reported": all(s.metrics["brier"] is not None for s in report.scores),
        }

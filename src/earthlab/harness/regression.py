"""Scenario A: regional PM2.5 six hours ahead, through the E1 workbench and evaluator.

Aggregate skill does not settle it. A model that is worse than persistence in the elevated
hours can only be adopted with that limit stated, and code writes that limit.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

from earthlab.digest import file_digest
from earthlab.forecast import evaluator as independent
from earthlab.forecast.contracts import ARM_LABEL, LIMITATIONS, Assignment
from earthlab.forecast.gate import REFERENCE, eligible, verdict
from earthlab.forecast.pipeline import SEED, SOURCE, FeatureSpec, TrainSpec, Workbench
from earthlab.forecast.samples import PRIMARY_HORIZON, USABLE_OFFSET
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
from earthlab.harness.seats import Seats, Stopped
from earthlab.harness.strategy import Strategy

ELEVATED = "above_55_mae"
BASE_METHODS = ("persistence", "naive", "climatology", "ridge")
SECONDS_PER_EPOCH = {"gru": 4.0, "tcn": 50.0}  # measured in the E1 arms at window 48, hidden 32
PRESET = Assignment(
    window_hours=48, log_transform=True, architecture="gru", hidden=32, layers=1, max_epochs=12,
    loss="mae", reason="The preset for the arm with no model.",
)  # fmt: skip
PM25_PROBLEM = ProblemSpecV1(
    problem_id="pm25-regression-6h", kind="regression", variable="pm25", unit="ug/m3",
    domain="five NEA reporting regions, hourly", target="regional hourly PM2.5 at T+6 h",
    horizon_hours=6, permitted_evidence=("NEA historical 1-hour PM2.5",),
    success_criteria=(
        "lower 95% limit of mean MAE skill against persistence above zero",
        "no region with a clear loss", "elevated-hour error reported against persistence",
    ),
)  # fmt: skip


class RegressionAdapter:
    label = ARM_LABEL
    methods: tuple[str, ...] = (*BASE_METHODS, "gru", "tcn")
    limitations: tuple[str, ...] = LIMITATIONS
    pretrained: tuple[str, ...] = ()
    default_strategy: Strategy = "small_neural"
    can_request = False

    def __init__(self, run_dir: Path, source: Path = SOURCE):
        self.bench = Workbench(run_dir, source)
        self.features_id = ""
        self.trained = 0
        self.chosen = "small_neural"
        self.notes: list[str] = []

    def menu_for(self, strategy: str) -> type[BaseModel] | None:
        return Assignment if strategy == "small_neural" else None

    def measure(self, problem: ProblemSpecV1) -> DatasetProfileV1:
        summary = self.bench.profile()["summary"]
        audit = self.bench.audit
        total = audit.grid_hours * 5
        missing = float(sum(s["missing_cells"] for s in summary["splits"].values())) / total
        return DatasetProfileV1(
            sources=(SourceRef(name=self.bench.source.name, sha256=self.bench.truth_sha),),
            variable="pm25", unit="ug/m3", first_label=summary["splits"]["train"]["first"],
            last_label=summary["splits"]["test"]["last"], usable_rows=audit.grid_hours,
            missing_fraction=min(missing, 1.0), labels_present=True,
            label_provenance="the published NEA series itself", granularity="1 h, five regions",
            availability_latency_hours=USABLE_OFFSET,
            leakage_risks=("test period sealed from every feature file",
                           "scalers fitted on the train split only"),
        )  # fmt: skip

    def preset(self) -> BaseModel:
        return PRESET

    def plan(
        self, choice: BaseModel, plan_id: str, by: Literal["preset", "model"]
    ) -> ExperimentPlanV1:
        spec = Assignment.model_validate(choice.model_dump())
        config = spec.model_dump(exclude={"reason"})
        return ExperimentPlanV1(
            plan_id=plan_id, methods=(*BASE_METHODS, spec.architecture), config=config,
            split_protocol="docs/science-data-forecast-protocol.md v1; validation only",
            metrics=("mae", "rmse", "bias", "skill_against_persistence", ELEVATED),
            input_offset_hours=USABLE_OFFSET, seed=SEED, decided_by=by,
            budget=BudgetV1(max_seconds=5400, max_training_seconds=1200, max_model_calls=40),
        )  # fmt: skip

    def estimate(self, plan: ExperimentPlanV1) -> float:
        c = plan.config
        unit = SECONDS_PER_EPOCH[str(c["architecture"])]
        scale = float(c["window_hours"]) / 48 * float(c["hidden"]) / 32 * float(c["layers"])
        return unit * scale * float(c["max_epochs"])

    def prepare(self, plan: ExperimentPlanV1) -> dict[str, Any]:
        c = plan.config
        built = self.bench.build_features(
            FeatureSpec(int(c["window_hours"]), bool(c["log_transform"]))
        )
        self.features_id = built["features_id"]
        return {k: v for k, v in built.items() if k not in ("path", "spec")}

    def train(self, plan: ExperimentPlanV1, seats: Seats) -> dict[str, Any]:
        c = plan.config
        self.chosen = str(c.get("strategy"))
        if REFERENCE not in self.bench.results:
            self.bench.baselines(int(c["window_hours"]))
        if self.chosen != "small_neural":
            return {"models": "baselines only", "strategy": self.chosen}
        self.trained += 1
        name = f"candidate-{self.trained}"
        spec = TrainSpec(
            str(c["architecture"]), int(c["hidden"]), int(c["layers"]), int(c["max_epochs"]),
            str(c["loss"]), seed=plan.seed,
        )  # fmt: skip
        record = self.bench.train(name, self.features_id, spec)
        if record.get("failed"):
            raise Stopped(f"training failed: exit {record['exit_code']}")
        seats.log.training_seconds += float(record["wall_seconds"])
        seats.log.peak_rss_mb = max(seats.log.peak_rss_mb, float(record["peak_rss_mb"]))
        return {"model_id": name, "parameters": record["training"]["parameters"],
                "features_sha256": record["features_sha256"]}  # fmt: skip

    def evaluate(self) -> EvaluationReportV1:
        rows, results = self.bench.compare(), self.bench.results
        scores = []
        for row in rows:
            name = row["model"]
            limits = results[name]["metrics"][str(PRIMARY_HORIZON)]["limits"]
            reasons = verdict(name, results[name]).reasons
            metrics = {k: row[k] for k in ("mae", "rmse", "bias", "skill", ELEVATED)}
            scores.append(ModelScore(
                model=name, metrics=metrics, low=limits["mean_skill_low"],
                high=limits["mean_skill_high"], passes=not reasons, reasons=reasons,
                subgroups={"elevated": {"mae": row[ELEVATED],
                                        "recall": row["exceed_recall"]}},
            ))  # fmt: skip
        return EvaluationReportV1(
            evaluator="earthlab.forecast.evaluator",
            evaluator_sha256=file_digest(Path(independent.__file__)), split_scored="validation",
            reference=REFERENCE, scores=tuple(scores),
            notes=("the test period was not read",),
        )  # fmt: skip

    def _worse_when_elevated(
        self, report: EvaluationReportV1, name: str
    ) -> tuple[float, float] | None:
        rows = {s.model: s for s in report.scores}
        mine, base = rows[name].metrics[ELEVATED], rows[REFERENCE].metrics[ELEVATED]
        if mine is None or base is None or mine <= base:
            return None
        return mine, base

    def limits(self, report: EvaluationReportV1, chosen: str | None) -> tuple[str, ...]:
        worse = self._worse_when_elevated(report, chosen) if chosen else None
        if worse is None:
            return LIMITATIONS
        text = (
            f"Above 55 ug/m3 the MAE of {chosen} is {worse[0]:.3f} against {worse[1]:.3f} for "
            "persistence. Do not rely on it in elevated hours."
        )
        return (*LIMITATIONS, text)

    def allowed(self, report: EvaluationReportV1) -> dict[str, list[str]]:
        results = self.bench.results
        passing = eligible(results)
        trained = [n for n in passing if n.startswith("candidate")]
        limited = [n for n in trained if self._worse_when_elevated(report, n)]
        out: dict[str, list[str]] = {
            "abstain": [], "retain_baseline": [n for n in results if n.startswith("B")],
        }  # fmt: skip
        if set(trained) - set(limited):
            out["adopt"] = sorted(set(trained) - set(limited))
        if limited:
            out["adopt_limited"] = limited
        return out

    def decide(self, report: EvaluationReportV1) -> DecisionRecordV1:
        ranked, results = eligible(self.bench.results), self.bench.results
        rejected = tuple(n for n in results if n not in ranked[:1])
        if not ranked or ranked[0].startswith("B"):
            pick = ranked[0] if ranked else REFERENCE
            return DecisionRecordV1(
                outcome="retain_baseline", selected=pick, rejected=rejected,
                reason="No trained model beat the baselines under the rule.",
                limitations=self.limits(report, None),
            )  # fmt: skip
        best = ranked[0]
        return DecisionRecordV1(
            outcome="adopt_limited" if self._worse_when_elevated(report, best) else "adopt",
            selected=best, rejected=rejected, reason="The rule applied by code.",
            limitations=self.limits(report, best),
        )  # fmt: skip

    def acceptance(self, report: EvaluationReportV1) -> dict[str, bool]:
        folder, results = self.bench.folder, self.bench.results
        return {
            "profile_written": (folder / "data_profile.json").is_file(),
            "baselines_evaluated": sum(n[0] == "B" for n in results) == 5,
            "neural_model_when_chosen": self.chosen != "small_neural"
            or any(n.startswith("candidate") for n in results),
            "every_model_has_predictions_hash": all(
                "predictions_sha256" in r for r in results.values()
            ),
            "no_feature_file_reaches_test": all(
                f["last_visible_label"] < "2024" for f in self.bench.features.values()
            ),
            "elevated_hours_reported": all(ELEVATED in s.metrics for s in report.scores),
        }


__all__ = ["PM25_PROBLEM", "RegressionAdapter"]

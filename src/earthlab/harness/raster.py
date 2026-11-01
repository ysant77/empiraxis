"""Scenario C: for a burned-area window, use a raster method, a pretrained model, or abstain?

The deterministic path reuses the pinned MCD64A1 tool and the independent verifier. A pretrained
segmentation model needs six-band imagery and independent reference masks. MCD64A1 is neither,
so that path ends in a resource request. Nothing here produces a segmentation score.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from earthlab.cases.tools import CaseLibrary
from earthlab.contracts import Strict
from earthlab.digest import file_digest
from earthlab.harness import gates
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
from earthlab.harness.strategy import Strategy
from earthlab.report.area_sections import AREA_LIMITATIONS
from earthlab.tools.burned_area_tools import month_report
from earthlab.verify import burned_area_check as independent

CASE = "kalimantan-2015-burned-area"
MONTHS = ("2015-09", "2015-10")
DETERMINISTIC, SEGMENTATION = "raster_deterministic", "segmentation_pretrained"
PIXELS = 1000  # the method's own gate refuses thin coverage, month by month
LABEL = "Historical raster analysis of a pinned product"
LIMITATIONS = (
    *AREA_LIMITATIONS,
    "A pretrained segmentation model was not run. No segmentation accuracy is reported.",
)
BURN_PROBLEM = ProblemSpecV1(
    problem_id="burned-area-method", kind="raster_method", variable="burned_area", unit="ha",
    domain="Kalimantan study box, 2015-09 and 2015-10", target="mapped burned area by month",
    permitted_evidence=("pinned MCD64A1 collection 6.1",),
    success_criteria=(
        "the method fits the available inputs", "each reported month passes the quality gate",
        "a month below the gate is not reported",
    ),
)  # fmt: skip


class RasterChoice(Strict):
    method: Literal["raster_deterministic", "segmentation_pretrained"]
    reason: str = Field(min_length=5, max_length=400)


class RasterAdapter:
    label = LABEL
    methods: tuple[str, ...] = (DETERMINISTIC, SEGMENTATION)
    limitations: tuple[str, ...] = LIMITATIONS
    pretrained: tuple[str, ...] = ()
    can_request = True

    def __init__(self, run_dir: Path, wanted: str = DETERMINISTIC, root: Path = Path(".")):
        self.folder, self.wanted, self.root = run_dir, wanted, root.resolve()
        self.default_strategy: Strategy = (
            "deterministic" if wanted == DETERMINISTIC else "abstain_or_request"
        )
        self.library = CaseLibrary.load(self.root / "config" / "cases", self.root)
        self.reports: dict[str, dict[str, Any]] = {}
        self.profile: DatasetProfileV1 | None = None
        self.method = wanted
        self.refusals: list[gates.Refusal] = []

    def menu_for(self, strategy: str) -> type[BaseModel] | None:
        return None

    def measure(self, problem: ProblemSpecV1) -> DatasetProfileV1:
        case = self.library.get(CASE)
        reports = [month_report(case, self.root, month) for month in MONTHS]
        fractions = [float(r["check"]["verifier_valid_fraction"]) for r in reports]
        self.profile = DatasetProfileV1(
            sources=tuple(
                SourceRef(name=r["source"]["file"], sha256=r["source"]["sha256"]) for r in reports
            ),
            variable="burned_area", unit="ha", first_label=MONTHS[0], last_label=MONTHS[-1],
            usable_rows=PIXELS, missing_fraction=1 - min(fractions), labels_present=True,
            label_provenance="MCD64A1 QA flags; no reference masks",
            granularity="monthly", resolution_m=500.0, bands=("burn_date", "qa"),
            leakage_risks=("MCD64A1 is a product, not pixel ground truth",),
        )  # fmt: skip
        return self.profile

    def preset(self) -> BaseModel:
        return RasterChoice(method=self.wanted, reason="The method named by this request.")

    def plan(
        self, choice: BaseModel, plan_id: str, by: Literal["preset", "model"]
    ) -> ExperimentPlanV1:
        method = RasterChoice.model_validate(choice.model_dump()).method
        return ExperimentPlanV1(
            plan_id=plan_id, methods=(method,), config={"method": method},
            split_protocol="no split: fixed months of a pinned product",
            metrics=("area_ha", "valid_fraction", "gate_passed"), seed=0, decided_by=by,
            budget=BudgetV1(max_seconds=1800, max_training_seconds=0, max_model_calls=40),
        )  # fmt: skip

    def estimate(self, plan: ExperimentPlanV1) -> float:
        return 0.0

    def prepare(self, plan: ExperimentPlanV1) -> dict[str, Any]:
        asked = plan.config.get("strategy") == "abstain_or_request"
        self.method = SEGMENTATION if asked else DETERMINISTIC
        assert self.profile is not None
        if self.method == SEGMENTATION:
            self.refusals = gates.check_segmentation(self.profile)
        return {"method": self.method, "refusals": [str(r.code) for r in self.refusals]}

    def train(self, plan: ExperimentPlanV1, seats: Seats) -> dict[str, Any]:
        """No fitting. The deterministic method computes, or a blocked one does nothing."""
        if self.method == SEGMENTATION and self.refusals:
            return {"status": "not run", "reason": self.refusals[0].detail}
        case = self.library.get(CASE)
        self.reports = {month: month_report(case, self.root, month) for month in MONTHS}
        return {"months": list(self.reports)}

    def evaluate(self) -> EvaluationReportV1:
        scores = [self._month(month, report) for month, report in self.reports.items()]
        if self.method == SEGMENTATION:
            reasons = tuple(f"{r.code}: {r.detail}" for r in self.refusals)
            scores.append(ModelScore(model=SEGMENTATION, metrics={}, passes=False, reasons=reasons))
        return EvaluationReportV1(
            evaluator="earthlab.verify.burned_area_check",
            evaluator_sha256=file_digest(Path(independent.__file__)),
            split_scored="no split", reference="none", scores=tuple(scores),
            failures=tuple(r.detail for r in self.refusals),
            notes=("recomputed from pinned bytes by the independent verifier",),
        )  # fmt: skip

    def _month(self, month: str, report: dict[str, Any]) -> ModelScore:
        check = report["check"]
        passed = bool(check["passed"] and check["gate_ok"])  # checks agree, and the gate holds
        area = round(float(check["verifier_area_m2"]) / 1e4, 1) if passed else None
        return ModelScore(
            model=f"{DETERMINISTIC}:{month}",
            metrics={"area_ha": area, "valid_fraction": float(check["verifier_valid_fraction"])},
            passes=passed, reasons=() if passed else ("below the quality gate; not reported",),
        )  # fmt: skip

    def limits(self, report: EvaluationReportV1, chosen: str | None) -> tuple[str, ...]:
        blocked = [s.model for s in report.scores if not s.passes]
        if not blocked:
            return LIMITATIONS
        return (*LIMITATIONS, f"Not reported: {', '.join(blocked)}.")

    def allowed(self, report: EvaluationReportV1) -> dict[str, list[str]]:
        if self.method == SEGMENTATION and self.refusals:
            return {"request_resource": [], "abstain": []}
        fine = any(s.passes for s in report.scores)
        return {"adopt_limited": [DETERMINISTIC], "abstain": []} if fine else {"abstain": []}

    def decide(self, report: EvaluationReportV1) -> DecisionRecordV1:
        if self.method == SEGMENTATION and self.refusals:
            return DecisionRecordV1(
                outcome="request_resource", rejected=(SEGMENTATION,),
                reason="The inputs do not fit: approved imagery and reference masks are needed.",
                limitations=self.limits(report, None),
            )  # fmt: skip
        if not any(s.passes for s in report.scores):
            return DecisionRecordV1(
                outcome="abstain", reason="No month passed the quality gate.",
                limitations=self.limits(report, None),
            )  # fmt: skip
        return DecisionRecordV1(
            outcome="adopt_limited", selected=DETERMINISTIC, rejected=(SEGMENTATION,),
            reason="The deterministic method fits, for the months that pass the gate.",
            limitations=self.limits(report, DETERMINISTIC),
        )  # fmt: skip

    def acceptance(self, report: EvaluationReportV1) -> dict[str, bool]:
        return {
            "failed_month_has_no_area": all(
                s.metrics.get("area_ha") is None for s in report.scores if not s.passes
            ),
            "no_segmentation_score": all(
                not s.metrics for s in report.scores if s.model == SEGMENTATION
            ),
            "every_source_pinned": bool(self.profile and self.profile.sources),
        }


def segmentation_request(run_dir: Path) -> RasterAdapter:
    return RasterAdapter(run_dir, SEGMENTATION)

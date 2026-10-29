"""The critic's typed output: check IDs, findings and a report bound to one plan revision.

A report holds no wall-clock time and no free model text, so the same plan always gives
the same report. Each finding points at a plan field path and states one correction.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import Field

from earthlab.cases.models import SHA256
from earthlab.contracts import Strict
from earthlab.planning.plan import AbstentionReason
from earthlab.planning.roles import TaskMeta

REPORT_SCHEMA_VERSION: Literal["1"] = "1"
RULES_VERSION = "1"


class CheckId(StrEnum):
    """Checks 1-10 are the required science contracts; the rest guard plan structure."""

    FIRE_DETECTIONS_AS_BURNED_AREA = "fire_detections_as_burned_area"
    LST_AS_AIR_TEMPERATURE = "lst_as_air_temperature"
    REANALYSIS_AS_FORECAST = "reanalysis_as_forecast"
    RANDOM_SPLIT_TIME_SERIES = "random_split_time_series"
    FUTURE_INFORMATION_IN_FEATURES = "future_information_in_features"
    CAUSAL_FROM_WEAK_DESIGN = "causal_from_weak_design"
    INCOMPATIBLE_IMAGE_INPUT = "incompatible_image_input"
    PM25_FROM_WIND_ALONE = "pm25_from_wind_alone"
    DATA_COVERAGE = "data_coverage"
    MISSING_APPROVAL = "missing_approval"
    VARIABLE_SUBSTITUTION = "variable_substitution"
    PRODUCT_KIND_MISMATCH = "product_kind_mismatch"
    NO_EXPERIMENT_DESIGN = "no_experiment_design"
    NO_COMPETING_HYPOTHESIS = "no_competing_hypothesis"
    APPROVAL_OUTSIDE_SCOPE = "approval_outside_scope"
    DECLARED_EVIDENCE_GAP = "declared_evidence_gap"
    DATA_UNAVAILABLE = "data_unavailable"
    UNREGISTERED_DATASET = "unregistered_dataset"
    REGISTRY_MISMATCH = "registry_mismatch"
    METHOD_INFEASIBLE = "method_infeasible"
    ACTION_NOT_SUPPORTED = "action_not_supported"
    CAUSAL_ABSTENTION_MISSING = "causal_abstention_missing"


Severity = Literal["error", "warning", "uncertainty"]
SEVERITY_RANK: dict[Severity, int] = {"error": 0, "warning": 1, "uncertainty": 2}
Verdict = Literal["accept", "accept_with_warnings", "needs_evidence", "revise"]


class Finding(Strict):
    finding_id: str = Field(min_length=1)
    check: CheckId
    severity: Severity
    field_path: str = Field(min_length=1)
    message: str = Field(min_length=1)
    correction: str = Field(min_length=1)
    evidence_refs: tuple[str, ...] = ()
    priority: int = Field(default=0, ge=0)


class CriticReport(Strict):
    """One review of one plan revision against one registry. `abstentions` lists the
    plan-level answers the run must give instead of a value. `verdict` follows severity:
    any error gives revise; else a declared evidence gap gives needs_evidence; else any
    warning gives accept_with_warnings; else accept."""

    schema_version: Literal["1"] = REPORT_SCHEMA_VERSION
    rules_version: str = RULES_VERSION
    report_id: str = Field(min_length=1)
    task: TaskMeta
    reviewer_kind: Literal["deterministic_rules"] = "deterministic_rules"
    plan_id: str = Field(min_length=1)
    plan_revision: int = Field(ge=1)
    plan_sha256: str = Field(pattern=SHA256)
    registry_sha256: str = Field(pattern=SHA256)
    verdict: Verdict
    abstentions: tuple[AbstentionReason, ...] = ()
    findings: tuple[Finding, ...] = ()

    def checks(self, severity: Severity | None = None) -> set[CheckId]:
        return {f.check for f in self.findings if severity is None or f.severity == severity}

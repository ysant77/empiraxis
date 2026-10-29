"""Deterministic science rules over typed plan fields. No rule reads free text.

Each rule takes a plan and returns draft findings. Rules look at the selected method,
because rejected candidates do not run. A data problem the plan already declares as an
evidence gap is an uncertainty, not an error: an honest gap is better than a guess.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator

from earthlab.cases.methods import CATALOGUE, NOT_A_SUBSTITUTE
from earthlab.cases.models import ApprovalAction, ScientificVariable
from earthlab.planning.plan import InvestigationPlan
from earthlab.planning.report import CheckId, Severity
from earthlab.planning.sources import DataCandidate, DataUse
from earthlab.planning.vocab import (
    PM25_PHYSICAL_SUPPORT,
    TIME_SERIES_UNITS,
    WIND_QUANTITIES,
    ActionKind,
    PlanAction,
    Quantity,
    ResearchIntent,
)

Draft = tuple[CheckId, Severity, str, str, str]  # check, severity, path, message, correction
Rule = Callable[[InvestigationPlan], Iterator[Draft]]
V, RI = ScientificVariable, ResearchIntent
_SUBSTITUTION_CHECK: dict[tuple[Quantity, Quantity], CheckId] = {
    (V.ACTIVE_FIRE, V.BURNED_AREA): CheckId.FIRE_DETECTIONS_AS_BURNED_AREA,
    (V.LAND_SURFACE_TEMPERATURE, V.AIR_TEMPERATURE_ANOMALY): CheckId.LST_AS_AIR_TEMPERATURE,
}
_NOTES: dict[tuple[Quantity, Quantity], str] = {k: v for k, v in NOT_A_SUBSTITUTE.items()}
_MODEL_CLASSES = {"statistical", "machine_learning"}
_ESTIMATES = {RI.RETROSPECTIVE_ESTIMATION, RI.PROSPECTIVE_PREDICTION, RI.CAUSAL_INFERENCE}
_NEEDS_RIVALS = {RI.ASSOCIATION, RI.TRANSPORT_PLAUSIBILITY, RI.CAUSAL_INFERENCE}


def _uses(plan: InvestigationPlan) -> Iterator[tuple[int, DataUse, DataCandidate]]:
    for i, use in enumerate(plan.selected.inputs):
        yield i, use, plan.dataset(use.dataset_id)


def _path(plan: InvestigationPlan, index: int, leaf: str) -> str:
    return f"method_candidates[{plan.selected.method_id}].inputs[{index}].{leaf}"


def variable_substitution(plan: InvestigationPlan) -> Iterator[Draft]:
    """Checks 1 and 2: a dataset used as a quantity it does not measure."""
    for i, use, ds in _uses(plan):
        if use.used_as == ds.quantity:
            continue
        pair = (ds.quantity, use.used_as)
        check = _SUBSTITUTION_CHECK.get(pair, CheckId.VARIABLE_SUBSTITUTION)
        note = _NOTES.get(pair, "the dataset measures a different quantity")
        yield (
            check,
            "error",
            _path(plan, i, "used_as"),
            f"{ds.dataset_id} measures {ds.quantity.value}, used as {use.used_as.value}: {note}",
            f"use a dataset that measures {use.used_as.value}, or change the target",
        )
    yield from _target_substitution(plan)


def _target_substitution(plan: InvestigationPlan) -> Iterator[Draft]:
    target = plan.target.quantity
    measured = {ds.quantity for _, u, ds in _uses(plan) if u.role == "input"}
    for (have, want), check in _SUBSTITUTION_CHECK.items():
        if target == want and want not in measured and have in measured:
            yield (
                check,
                "error",
                "target.quantity",
                f"target is {want.value} but the only related input measures {have.value}",
                f"add a dataset that measures {want.value}; keep {have.value} as context",
            )


def product_kind(plan: InvestigationPlan) -> Iterator[Draft]:
    """Check 3: a product treated as a kind it is not (reanalysis as a forecast)."""
    for i, use, ds in _uses(plan):
        if use.assumed_kind == ds.product_kind:
            continue
        reanalysis = ds.product_kind == "reanalysis" and use.assumed_kind == "operational_forecast"
        yield (
            CheckId.REANALYSIS_AS_FORECAST if reanalysis else CheckId.PRODUCT_KIND_MISMATCH,
            "error",
            _path(plan, i, "assumed_kind"),
            f"{ds.dataset_id} is {ds.product_kind}, treated as {use.assumed_kind}",
            "describe the product as what it is; a reanalysis is a retrospective estimate",
        )


def experiment(plan: InvestigationPlan) -> Iterator[Draft]:
    """Check 4 and the experiment-design guard."""
    design = plan.experiment_design
    if design is None:
        if plan.selected.method_class in _MODEL_CLASSES:
            yield (
                CheckId.NO_EXPERIMENT_DESIGN,
                "error",
                "experiment_design",
                f"{plan.selected.method_id} fits a model but the plan has no experiment design",
                "add split, baselines, metrics and an independent reference",
            )
        return
    if design.split.method != "random_rows" or design.sample_unit not in TIME_SERIES_UNITS:
        return
    controlled = design.split.leakage_control is not None
    yield (
        CheckId.RANDOM_SPLIT_TIME_SERIES,
        "warning" if controlled else "error",
        "experiment_design.split.method",
        f"random row split over adjacent {design.sample_unit} samples leaks autocorrelation",
        "use blocked_time or forward_chaining, or keep the embargo and its evidence",
    )


def feature_timing(plan: InvestigationPlan) -> Iterator[Draft]:
    """Check 5: features not known at the forecast issue time, or labels as features."""
    design = plan.experiment_design
    if design is None:
        return
    for i, feat in enumerate(design.features):
        ds = plan.dataset(feat.dataset_id)
        path = f"experiment_design.features[{i}]"
        if ds.product_kind == "post_event_label" or feat.dataset_id == (
            design.independent_reference_id
        ):
            yield (
                CheckId.FUTURE_INFORMATION_IN_FEATURES,
                "error",
                path,
                f"feature {feat.name} uses a post-event label or the reference dataset",
                "remove labels and reference data from the feature set",
            )
            continue
        if plan.research_intent != RI.PROSPECTIVE_PREDICTION:
            continue
        known = (
            feat.issued_offset_hours
            if ds.product_kind == "operational_forecast"
            else feat.valid_offset_hours + ds.availability_latency_hours
        )
        if known is None or known > 0:
            yield (
                CheckId.FUTURE_INFORMATION_IN_FEATURES,
                "error",
                path,
                f"feature {feat.name} is not available at the issue time (known at {known} h)",
                "use only values published before the issue time, including data latency",
            )


def causal(plan: InvestigationPlan) -> Iterator[Draft]:
    """Check 6: a causal claim from correlation or wind direction alone."""
    if plan.research_intent != RI.CAUSAL_INFERENCE:
        return
    design = plan.causal_design
    weak = design is None or design.identification in {"correlation_only", "wind_direction_only"}
    yield (
        CheckId.CAUSAL_FROM_WEAK_DESIGN,
        "error" if weak else "warning",
        "research_intent",
        "correlation or wind direction alone cannot establish cause"
        if weak
        else "this system has no validated attribution protocol; cause stays unestablished",
        "plan an association or transport-plausibility study and state cause as not established",
    )


def image_inputs(plan: InvestigationPlan) -> Iterator[Draft]:
    """Check 7: segmentation inputs without the bands, normalization or quality mask."""
    need = plan.selected.image_requirements
    if plan.selected.technique != "image_segmentation" or need is None:
        return
    for i, use, ds in _uses(plan):
        if use.role != "input":
            continue
        missing = sorted(set(need.bands) - set(ds.bands))
        gaps = [f"missing bands {missing}"] if missing else []
        if ds.normalization != need.normalization:
            gaps.append(f"normalization {ds.normalization} is not {need.normalization}")
        if need.needs_quality_mask and ds.quality_mask is None:
            gaps.append("no quality mask")
        if gaps:
            yield (
                CheckId.INCOMPATIBLE_IMAGE_INPUT,
                "error",
                _path(plan, i, "dataset_id"),
                f"{ds.dataset_id}: " + "; ".join(gaps),
                "use scenes with the model's bands, its normalization and a cloud/QA mask",
            )


def pm25_from_wind(plan: InvestigationPlan) -> Iterator[Draft]:
    """Check 8: a PM2.5 estimate with transport inputs but no source, dilution or removal."""
    if plan.target.quantity != V.AIR_POLLUTION_OBSERVATION or plan.research_intent not in (
        _ESTIMATES
    ):
        return
    used = {u.used_as for u in plan.selected.inputs if u.role == "input"}
    if used & WIND_QUANTITIES and not used & PM25_PHYSICAL_SUPPORT:
        yield (
            CheckId.PM25_FROM_WIND_ALONE,
            "error",
            f"method_candidates[{plan.selected.method_id}].inputs",
            "wind gives transport direction only; it cannot give a PM2.5 concentration",
            "add emissions, dilution (boundary layer) or deposition inputs, or plan a "
            "transport-plausibility study",
        )


def coverage(plan: InvestigationPlan) -> Iterator[Draft]:
    """Check 9: data outside the study area or period, unavailable, or too few valid."""
    declared = {i for g in plan.evidence_gaps for i in g.candidate_dataset_ids}
    floor = _valid_floor(plan)
    for i, use, ds in _uses(plan):
        if use.role == "context":
            continue
        severity: Severity = "uncertainty" if ds.dataset_id in declared else "error"
        for problem in _coverage_problems(plan, ds, floor):
            yield (
                CheckId.DATA_COVERAGE,
                severity,
                _path(plan, i, "dataset_id"),
                f"{ds.dataset_id}: {problem}",
                "narrow the area or period, choose covered data, or declare an evidence gap",
            )


def _valid_floor(plan: InvestigationPlan) -> float:
    entry = CATALOGUE.get(plan.selected.catalogue_id or "")
    return entry.min_valid_fraction if entry else plan.selected.min_valid_fraction


def _coverage_problems(plan: InvestigationPlan, ds: DataCandidate, floor: float) -> list[str]:
    problems = []
    if ds.availability == "unavailable":
        problems.append("unavailable for this area and period")
    if not ds.coverage.contains(plan.time_range.period):
        problems.append("temporal coverage does not contain the study period")
    if not ds.covers(plan.aoi.area):
        problems.append("spatial coverage does not contain the study area")
    if ds.valid_fraction is not None and ds.valid_fraction < floor:
        problems.append(f"valid fraction {ds.valid_fraction} is below {floor}")
    return problems


def approvals(plan: InvestigationPlan) -> Iterator[Draft]:
    """Check 10: a billed, destructive or consequential step without a matching request."""
    for path, action, ids, usd, size in _required_actions(plan):
        if not any(
            r.action == action
            and set(ids) <= set(r.dataset_ids)
            and (usd is None or (r.max_usd is not None and usd <= r.max_usd))
            and (size is None or (r.max_bytes is not None and size <= r.max_bytes))
            for r in plan.approval_requests
        ):
            yield (
                CheckId.MISSING_APPROVAL,
                "error",
                path,
                f"{action.value} for {list(ids)} has no matching approval request",
                "add an approval request that names the action, datasets and cost cap",
            )
    for i, req in enumerate(plan.approval_requests):
        if req.action not in plan.approval_scope:
            yield (
                CheckId.APPROVAL_OUTSIDE_SCOPE,
                "error",
                f"approval_requests[{i}].action",
                f"{req.action.value} is outside the task approval scope",
                "remove the request or ask the director to widen the task scope",
            )


Required = tuple[str, ActionKind, tuple[str, ...], float | None, int | None]


def _required_actions(plan: InvestigationPlan) -> list[Required]:
    needed: list[Required] = [
        (f"operations[{i}]", o.action, o.dataset_ids, o.estimated_usd, o.estimated_bytes)
        for i, o in enumerate(plan.operations)
    ]
    selected = "method_choice.selected_id"
    pending = tuple(
        ds.dataset_id for _, _, ds in _uses(plan) if ds.availability == "registered_not_downloaded"
    )
    if pending:
        needed.append((selected, ApprovalAction.DOWNLOAD, pending, None, None))
    if plan.selected.compute == "hosted":
        needed.append((selected, ApprovalAction.HOSTED_MODEL_SPEND, (), None, None))
    if plan.selected.method_class == "machine_learning" and plan.experiment_design is not None:
        needed.append(("experiment_design", PlanAction.TRAIN_MODEL, (), None, None))
    return needed


def rivals_and_gaps(plan: InvestigationPlan) -> Iterator[Draft]:
    """Competing hypotheses for relational questions; one uncertainty per declared gap."""
    if plan.research_intent in _NEEDS_RIVALS and not any(
        h.direction != "forward" for h in plan.hypotheses
    ):
        yield (
            CheckId.NO_COMPETING_HYPOTHESIS,
            "warning",
            "hypotheses",
            "no reverse, common-cause or null hypothesis is stated",
            "add at least one competing hypothesis and the data that would separate them",
        )
    for i, gap in enumerate(plan.evidence_gaps):
        yield (
            CheckId.DECLARED_EVIDENCE_GAP,
            "uncertainty",
            f"evidence_gaps[{i}]",
            f"missing evidence for {gap.needed.value}",
            "obtain one of the candidate datasets before any claim depends on it",
        )


RULES: tuple[Rule, ...] = (
    variable_substitution,
    product_kind,
    experiment,
    feature_timing,
    causal,
    image_inputs,
    pm25_from_wind,
    coverage,
    approvals,
    rivals_and_gaps,
)

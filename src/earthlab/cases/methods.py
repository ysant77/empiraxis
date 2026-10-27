"""The method catalogue and the feasibility check that decides whether a method can run.

A method is chosen by what the case needs and what the assets can support, never by
place. The check reports every reason it finds. Status order: blocked (a hard data or
science mismatch), then needs_approval (a download or a draft study area a human must
approve), then not_implemented, then feasible.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

from pydantic import Field

from earthlab.cases.models import (
    IDENT,
    ApprovalAction,
    CausalStatus,
    EvidenceClaim,
    ScientificCase,
    ScientificVariable,
    SourceAsset,
    StudyArea,
)
from earthlab.contracts import Strict

V = ScientificVariable
NOT_A_SUBSTITUTE: dict[tuple[ScientificVariable, ScientificVariable], str] = {
    (V.ACTIVE_FIRE, V.BURNED_AREA): "active-fire detections are not burned area",
    (V.LAND_SURFACE_TEMPERATURE, V.AIR_TEMPERATURE_ANOMALY): (
        "land-surface temperature is not 2 m air temperature"
    ),
    (V.AIR_POLLUTION_OBSERVATION, V.AIR_TEMPERATURE_ANOMALY): "PM2.5 is not air temperature",
}


class MethodCandidate(Strict):
    method_id: str = Field(pattern=IDENT)
    version: str
    variable: ScientificVariable
    required_products: tuple[str, ...] = Field(min_length=1)
    accepted_crs: tuple[str, ...] = Field(min_length=1)
    max_period_days: int = Field(gt=0)
    time_unit: Literal["hour", "calendar_month_utc"]
    output_units: tuple[str, ...] = Field(min_length=1)
    min_valid_fraction: float = Field(ge=0, le=1)
    needs_quality_policy: bool
    implemented: bool
    validation_steps: tuple[str, ...] = ()
    limitations: tuple[str, ...] = ()


CATALOGUE: dict[str, MethodCandidate] = {
    m.method_id: m
    for m in (
        MethodCandidate(
            method_id="nea_hourly_episode",
            version="1",
            variable=V.AIR_POLLUTION_OBSERVATION,
            required_products=("nea-historical-1hr-pm25",),
            accepted_crs=("named-regions",),
            max_period_days=92,
            time_unit="hour",
            output_units=("ug/m3", "hours"),
            min_valid_fraction=0.75,
            needs_quality_policy=False,
            implemented=True,
            validation_steps=("independent re-parse of the pinned CSV", "hash check"),
            limitations=("Regional values, not station coordinates.", "PM2.5 is not PSI/AQI."),
        ),
        MethodCandidate(
            method_id="mcd64a1_burned_area",
            version="0",
            variable=V.BURNED_AREA,
            required_products=("MODIS/061/MCD64A1",),
            accepted_crs=("SR-ORG:6974",),
            max_period_days=92,
            time_unit="calendar_month_utc",
            output_units=("ha",),
            min_valid_fraction=0.8,
            needs_quality_policy=True,
            implemented=True,
            validation_steps=(
                "QA mask from the product user guide",
                "equal-area pixel area in the native sinusoidal grid",
                "independent server-side area sum recorded at download",
            ),
            limitations=(
                "Mapped burned area at 500 m; not destroyed trees or forest loss.",
                "Hotspot counts are not burned area.",
            ),
        ),
        MethodCandidate(
            method_id="era5_t2m_anomaly",
            version="0",
            variable=V.AIR_TEMPERATURE_ANOMALY,
            required_products=("ECMWF/ERA5/HOURLY",),
            accepted_crs=("EPSG:4326",),
            max_period_days=92,
            time_unit="hour",
            output_units=("K",),
            min_valid_fraction=0.9,
            needs_quality_policy=False,
            implemented=False,
            limitations=("Reanalysis, not observations available at the time.",),
        ),
    )
}


def get_method(method_id: str) -> MethodCandidate:
    try:
        return CATALOGUE[method_id]
    except KeyError:
        raise ValueError(f"unknown method {method_id!r}") from None


class Feasibility(Strict):
    status: Literal["feasible", "needs_approval", "not_implemented", "blocked"]
    reasons: tuple[str, ...] = ()
    approvals_needed: tuple[tuple[ApprovalAction, str], ...] = ()


def _product_problems(
    case: ScientificCase, method: MethodCandidate, product: str, assets: list[SourceAsset]
) -> tuple[list[str], list[tuple[ApprovalAction, str]]]:
    matches = [a for a in assets if a.product == product]
    if not matches:
        notes = {NOT_A_SUBSTITUTE.get((a.variable, method.variable)) for a in assets}
        detail = "; ".join(sorted(n for n in notes if n)) or "no asset of that product"
        return [f"variable mismatch for {product}: {detail}"], []
    if len(matches) > 1:
        ids = ", ".join(a.asset_id for a in matches)
        return [f"{len(matches)} assets for {product} ({ids}); a case uses one per product"], []
    asset = matches[0]
    hard: list[str] = []
    if asset.availability == "unavailable":
        hard.append(f"{asset.asset_id} is unavailable for this case")
    if not asset.coverage.contains(case.period):
        hard.append(f"{asset.asset_id}: temporal coverage does not contain the study period")
    if not asset.covers(case.area):
        hard.append(f"{asset.asset_id}: spatial coverage does not contain the study area")
    if asset.crs not in method.accepted_crs:
        hard.append(f"{asset.asset_id}: CRS {asset.crs} is not one of {method.accepted_crs}")
    if method.needs_quality_policy and asset.quality_policy is None:
        hard.append(f"{asset.asset_id}: the method needs a quality-flag policy")
    approvals = []
    if asset.availability == "registered_not_downloaded":
        approvals.append((ApprovalAction.DOWNLOAD, asset.asset_id))
    return hard, approvals


def _whole_utc_months(case: ScientificCase) -> bool:
    return all(
        (t.day, t.hour, t.minute, t.second, t.microsecond) == (1, 0, 0, 0, 0)
        for t in (case.period.start, case.period.end)
    )


def _case_problems(case: ScientificCase, method: MethodCandidate) -> list[str]:
    hard: list[str] = []
    if method.variable is not case.variable:
        hard.append(f"method measures {method.variable.value}, case asks {case.variable.value}")
    if case.period.days > method.max_period_days:
        hard.append(f"study period longer than {method.max_period_days} days")
    if method.time_unit == "calendar_month_utc" and not _whole_utc_months(case):
        hard.append("a monthly product needs a period of whole UTC calendar months")
    return hard


def assess(
    case: ScientificCase, method: MethodCandidate, assets: Mapping[str, SourceAsset]
) -> Feasibility:
    """Every reason the method cannot run on this case now; feasible only with none."""
    hard = _case_problems(case, method)
    approvals: list[tuple[ApprovalAction, str]] = []
    if case.status == "draft":
        approvals.append((ApprovalAction.CONFIRM_STUDY_AREA, case.area.area_id))
    missing = [i for i in case.asset_ids if i not in assets]
    hard += [f"asset {i} is not registered" for i in missing]
    case_assets = [assets[i] for i in case.asset_ids if i in assets]
    for product in method.required_products:
        problems, needed = _product_problems(case, method, product, case_assets)
        hard += problems
        approvals += needed
    soft = [] if method.implemented else [f"method {method.method_id} is not implemented yet"]
    reasons = tuple(hard + [f"needs {a.value} approval for {i}" for a, i in approvals] + soft)
    if hard:
        return Feasibility(status="blocked", reasons=reasons, approvals_needed=tuple(approvals))
    if approvals:
        return Feasibility(
            status="needs_approval", reasons=reasons, approvals_needed=tuple(approvals)
        )
    return Feasibility(status="not_implemented" if soft else "feasible", reasons=reasons)


def _inside(inner: StudyArea, outer: StudyArea) -> bool:
    if outer.bbox is not None:
        return inner.bbox is not None and outer.bbox.contains(inner.bbox)
    return bool(inner.regions) and set(inner.regions) <= set(outer.regions)


def claim_problems(
    claim: EvidenceClaim, case: ScientificCase, method: MethodCandidate
) -> list[str]:
    """Why a claim does not fit its case and method; empty when it fits."""
    problems: list[str] = []
    if claim.case_id != case.case_id or claim.method_id != method.method_id:
        problems.append("claim names a different case or method")
    if claim.variable is not case.variable:
        problems.append("claim variable differs from the case variable")
    if not _inside(claim.area, case.area):
        problems.append("claim area lies outside the case area")
    if not case.period.contains(claim.period):
        problems.append("claim period lies outside the case period")
    if claim.unit not in method.output_units:
        problems.append(f"claim unit {claim.unit} is not a method unit {method.output_units}")
    if claim.valid_fraction is not None and claim.valid_fraction < method.min_valid_fraction:
        problems.append(f"valid fraction below the method minimum {method.min_valid_fraction}")
    expected = case.default_causal_status()
    if claim.causal_status is CausalStatus.NOT_REQUESTED and expected is not claim.causal_status:
        problems.append("the case asks a causal question; causal status must be stated")
    return problems

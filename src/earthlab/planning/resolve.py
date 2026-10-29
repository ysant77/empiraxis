"""Replace a plan's dataset claims with registry records, and check catalogue methods.

The critic reviews the resolved plan, never the plan's own dataset metadata. Each claim
that disagrees with the registry is an error, so a planner cannot pass the critic by
stating better coverage or a higher valid fraction than the data has.
"""

from __future__ import annotations

from collections.abc import Iterator

from earthlab.cases.methods import CATALOGUE, Feasibility, assess
from earthlab.cases.models import ApprovalAction, ScientificCase, ScientificVariable
from earthlab.planning.plan import InvestigationPlan
from earthlab.planning.registry import Registry
from earthlab.planning.report import CheckId
from earthlab.planning.rules import Draft
from earthlab.planning.sources import DataCandidate

# The fields the critic reads. A plan's claim must equal the registry on each of them.
REGISTRY_FIELDS = (
    "availability",
    "sha256",
    "quantity",
    "product_kind",
    "crs",
    "coverage",
    "extent",
    "regions",
    "availability_latency_hours",
    "valid_fraction",
    "valid_fraction_by_period",
)


def _unregistered(claim: DataCandidate) -> DataCandidate:
    """An unknown dataset is treated as unavailable with no measured quality."""
    return claim.model_copy(
        update={"availability": "unavailable", "valid_fraction": None, "sha256": None}
    )


def resolve(plan: InvestigationPlan, registry: Registry) -> tuple[InvestigationPlan, list[Draft]]:
    """The plan with registry records in place of its claims, and every disagreement."""
    drafts: list[Draft] = []
    resolved = []
    for claim in plan.data_candidates:
        path = f"data_candidates[{claim.dataset_id}]"
        record = registry.candidates.get(claim.dataset_id)
        if record is None:
            drafts.append(_draft_unregistered(claim, path))
            resolved.append(_unregistered(claim))
            continue
        for name in REGISTRY_FIELDS:
            claimed, actual = getattr(claim, name), getattr(record, name)
            if claimed != actual:
                drafts.append(_draft_mismatch(claim, path, name))
        resolved.append(record)
    return plan.model_copy(update={"data_candidates": tuple(resolved)}), drafts


def _draft_unregistered(claim: DataCandidate, path: str) -> Draft:
    return (
        CheckId.UNREGISTERED_DATASET,
        "error",
        path,
        f"{claim.dataset_id} is not in the dataset registry; it is treated as unavailable",
        "register the dataset in a case file, or remove it from the plan",
    )


def _draft_mismatch(claim: DataCandidate, path: str, name: str) -> Draft:
    return (
        CheckId.REGISTRY_MISMATCH,
        "error",
        f"{path}.{name}",
        f"{claim.dataset_id}: the plan's {name} differs from the registry",
        "copy the registry value; the critic uses the registry, not the plan",
    )


def catalogue_check(plan: InvestigationPlan, registry: Registry) -> Iterator[Draft]:
    """Run the case feasibility check for a selected catalogue method."""
    method = plan.selected
    if method.catalogue_id is None:
        return
    path = f"method_candidates[{method.method_id}]"
    entry = CATALOGUE.get(method.catalogue_id)
    target = plan.target.quantity
    if entry is None or not isinstance(target, ScientificVariable):
        why = "is not in the catalogue" if entry is None else "needs a case variable as target"
        yield (
            CheckId.METHOD_INFEASIBLE,
            "error",
            f"{path}.catalogue_id",
            f"catalogue method {method.catalogue_id} {why}",
            "select a catalogue method that measures the target, or drop catalogue_id",
        )
        return
    case = ScientificCase(
        case_id=plan.plan_id,
        title=plan.plan_id,
        question=plan.research_question,
        area=plan.aoi.area,
        period=plan.time_range.period,
        variable=target,
        asset_ids=tuple(u.dataset_id for u in method.inputs),
        method_id=entry.method_id,
        status="active",
    )
    yield from _feasibility_drafts(plan, path, assess(case, entry, registry.assets))


def _feasibility_drafts(plan: InvestigationPlan, path: str, result: Feasibility) -> Iterator[Draft]:
    if result.status != plan.selected.feasibility:
        yield (
            CheckId.REGISTRY_MISMATCH,
            "error",
            f"{path}.feasibility",
            f"the plan says {plan.selected.feasibility}; the feasibility check says "
            f"{result.status}",
            "state the feasibility that the case check reports",
        )
    if result.status in ("blocked", "not_implemented"):
        declared = any(plan.declared_missing(i) for i in plan.selected.input_ids())
        for reason in result.reasons:
            yield (
                CheckId.METHOD_INFEASIBLE,
                "uncertainty" if declared and result.status == "blocked" else "error",
                path,
                reason,
                "choose data and a method that the feasibility check accepts",
            )
    for action, ident in result.approvals_needed:
        if action is not ApprovalAction.DOWNLOAD and not any(
            r.action == action and ident in r.dataset_ids for r in plan.approval_requests
        ):
            yield (
                CheckId.MISSING_APPROVAL,
                "error",
                path,
                f"the feasibility check needs {action.value} approval for {ident}",
                "add an approval request for this action",
            )

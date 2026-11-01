"""Deterministic router specification: three policies, no model call to choose a model.

Policy A is the existing all-Muse workflow. Policy B swaps in a smaller approved PM model and
keeps a Muse Geospatial Lead. Policy C routes in code, with no separate orchestrator call.

The router is a pure function of the request indicators, the role bindings file and the
provider table. It imports no model client and no network library. A candidate that is
disabled, planned, unlicensed, without a passed preflight, or on a disabled provider is never
selected, and the router falls back to policy A or reports that nothing can serve.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Literal

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.implement.bindings import BindableRole, Bindings, Candidate
from earthlab.llm.providers import ProviderConfig

Policy = Literal["A", "B", "C"]
POLICY_NAMES: dict[str, str] = {
    "A": "existing all-Muse workflow (separate orchestrator call)",
    "B": "smaller approved PM model plus Muse Geospatial Lead",
    "C": "deterministic routing, no separate orchestrator call",
}
# Model calls the router itself makes to choose a model. A constant, tested to stay zero.
ROUTING_MODEL_CALLS = 0
CAUSAL = re.compile(r"\b(caus\w*|because|due to|responsible|attribut\w*)\b", re.I)
FORECAST = re.compile(r"\b(forecast|predict\w*|will|next (week|month|year))\b", re.I)
MONTHS = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{4}\b", re.I)


class Complexity(Strict):
    """Indicators computed from the request and the case list, with no model."""

    case_registered: bool
    causal_wording: bool
    forecast_wording: bool
    periods_named: int = Field(ge=0)

    @property
    def level(self) -> Literal["low", "high"]:
        simple = (
            self.case_registered
            and not self.causal_wording
            and not self.forecast_wording
            and self.periods_named <= 1
        )
        return "low" if simple else "high"


def complexity_of(question: str, case_ids: tuple[str, ...], case_hint: str | None) -> Complexity:
    """`case_hint` is a case ID the caller already resolved in code, or None."""
    return Complexity(
        case_registered=case_hint is not None and case_hint in case_ids,
        causal_wording=bool(CAUSAL.search(question)),
        forecast_wording=bool(FORECAST.search(question)),
        periods_named=len(MONTHS.findall(question)),
    )


class Budget(Strict):
    """Hard limits a policy must fit inside. Local providers cost 0 USD but still take time."""

    max_model_calls: int = Field(gt=0)
    max_seconds: float = Field(gt=0)
    max_usd: float = Field(ge=0)


class RouteDecision(Strict):
    requested: Policy
    effective: Policy
    pm_candidate: str | None
    orchestrator_candidate: str | None  # None: no separate orchestrator call
    engineer_candidate: str | None
    complexity: Literal["low", "high"]
    fallbacks: tuple[str, ...]
    refusals: tuple[str, ...]
    routing_model_calls: Literal[0] = 0
    planned_model_calls_max: int

    @property
    def can_run(self) -> bool:
        return not self.refusals


def _blockers(
    bindings: Bindings,
    providers: Mapping[str, ProviderConfig],
    role: BindableRole,
    c: Candidate,
    budget: Budget,
) -> list[str]:
    """Every reason the candidate cannot serve the role under this budget. Empty: it can."""
    if role not in c.roles:
        return [f"{c.candidate_id} is not listed for {role}"]
    status = bindings.status(role, c.candidate_id, providers)
    found = status.blockers(allow_experimental=True)
    provider = providers.get(c.provider_id or "")
    if provider is not None and provider.kind == "hosted":
        if budget.max_usd <= 0:
            found.append("hosted provider needs a positive USD budget")
        if provider.usd_per_mtok_input is None or provider.usd_per_mtok_output is None:
            found.append("hosted provider has no recorded price")
    return found


def _pick(
    bindings: Bindings,
    providers: Mapping[str, ProviderConfig],
    role: BindableRole,
    budget: Budget,
    *,
    exclude: str | None = None,
) -> tuple[str | None, list[str]]:
    """First candidate, in file order, that passes every gate; plus why others failed.

    `exclude` keeps policy B honest: its PM must be a different model from the lead.
    """
    why: list[str] = []
    for c in bindings.candidates:
        if c.candidate_id == exclude:
            continue
        blocked = _blockers(bindings, providers, role, c, budget)
        if not blocked:
            return c.candidate_id, why
        why.append(f"{role}/{c.candidate_id}: " + "; ".join(blocked))
    return None, why


def _calls(policy: Policy) -> int:
    # PM brief, optional orchestrator, engineer turns (plan, tools, answer), PM report.
    return {"A": 1 + 1 + 12 + 1, "B": 1 + 1 + 12 + 1, "C": 1 + 12 + 1}[policy]


def route(
    request: Policy,
    complexity: Complexity,
    bindings: Bindings,
    providers: Mapping[str, ProviderConfig],
    budget: Budget,
) -> RouteDecision:
    """Pick the policy and the bound candidates. Pure: same inputs, same decision."""
    fallbacks: list[str] = []
    effective: Policy = request
    if request != "A" and complexity.level == "high":
        fallbacks.append("complexity is high: policy A keeps the Muse lead on every stage")
        effective = "A"
    eng, why_e = _pick(bindings, providers, "geospatial_engineer", budget)
    pm, why = _pick(
        bindings, providers, "product_manager", budget, exclude=eng if effective == "B" else None
    )
    if effective == "B" and pm is None:
        fallbacks.append("no approved smaller PM model: falling back to policy A")
        fallbacks.extend(why)
        effective = "A"
        pm, why = _pick(bindings, providers, "product_manager", budget)
    orch = None
    if effective in {"A", "B"}:
        orch, why_o = _pick(bindings, providers, "orchestrator", budget)
        why += why_o
    refusals = [] if (pm and eng and (orch or effective == "C")) else why + why_e
    planned = _calls(effective)
    if planned > budget.max_model_calls:
        refusals.append(
            f"policy {effective} needs up to {planned} model calls; budget allows "
            f"{budget.max_model_calls}"
        )
    return RouteDecision(
        requested=request,
        effective=effective,
        pm_candidate=pm,
        orchestrator_candidate=orch,
        engineer_candidate=eng,
        complexity=complexity.level,
        fallbacks=tuple(fallbacks),
        refusals=tuple(refusals),
        planned_model_calls_max=planned,
    )

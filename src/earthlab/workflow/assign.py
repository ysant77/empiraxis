"""Who serves each workflow role, and what the engineer's task may touch.

`resolve_assignment` binds the PM and the engineer through the role bindings and checks
that each client is the bound candidate's provider and model. `task_scope` derives the
engineer's tools and datasets from its one assigned case: a burned-area case never sees
the NEA PM2.5 tools, and the PM2.5 case never sees the burned-area tools.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from earthlab.cases.loader import CaseFile
from earthlab.cases.models import ScientificVariable
from earthlab.implement.bindings import BindingRefused, Bindings, RoleBinding, load_bindings
from earthlab.llm.client import ChatClient
from earthlab.llm.providers import ProviderConfig
from earthlab.runtime import TaskScope
from earthlab.workflow.contracts import Topology

__all__ = [
    "BindingRefused",
    "WorkflowAssignment",
    "repo_assignment",
    "resolve_assignment",
    "task_scope",
]

BINDINGS_FILE = Path("config") / "roles" / "bindings.yaml"

PLAN_TOOLS = frozenset({"submit_plan", "declare_limitation", "assess_case"})
PM25_TOOLS = frozenset(
    {
        "inspect_coverage",
        "summarize_regions",
        "daily_peaks",
        "rank_regions",
        "count_hours_above",
        "submit_findings",
    }
)
AREA_TOOLS = frozenset({"burned_area_summary", "submit_area_findings"})
_BY_VARIABLE = {
    ScientificVariable.AIR_POLLUTION_OBSERVATION: PM25_TOOLS,
    ScientificVariable.BURNED_AREA: AREA_TOOLS,
}


@dataclass(frozen=True)
class WorkflowAssignment:
    """The resolved role bindings a run uses. Checked again against the live clients."""

    pm: RoleBinding
    engineer: RoleBinding
    topology: Topology = "combined"
    orchestrator: RoleBinding | None = None  # the separate topology's model orchestrator

    def __post_init__(self) -> None:
        if (self.topology == "separate") != (self.orchestrator is not None):
            raise ValueError("the separate topology, and only it, binds an orchestrator")

    def summary(self) -> str:
        roles = [("PM", self.pm), ("orchestrator", self.orchestrator), ("engineer", self.engineer)]
        named = [f"{name} {b.candidate_id} ({b.implementation})" for name, b in roles if b]
        return f"{self.topology} topology; " + ", ".join(named)

    def records(self) -> dict[str, Any]:
        out = {
            "pm": self.pm.model_dump(mode="json"),
            "engineer": self.engineer.model_dump(mode="json"),
        }
        if self.orchestrator is not None:
            out["orchestrator"] = self.orchestrator.model_dump(mode="json")
        return out

    def check(
        self,
        pm_client: ChatClient,
        engineer_client: ChatClient,
        orchestrator_client: ChatClient | None = None,
    ) -> None:
        pairs = [(self.pm, pm_client), (self.engineer, engineer_client)]
        if self.orchestrator is not None:
            if orchestrator_client is None:
                raise BindingRefused("the separate topology needs an orchestrator client")
            pairs.append((self.orchestrator, orchestrator_client))
        for binding, client in pairs:
            cfg = client.config
            if (cfg.name, cfg.model) != (binding.provider_id, binding.model_id):
                raise BindingRefused(
                    f"{binding.role} is bound to {binding.provider_id}/{binding.model_id}, "
                    f"but the client is {cfg.name}/{cfg.model}"
                )


def resolve_assignment(
    bindings: Bindings,
    providers: Mapping[str, ProviderConfig],
    pm_client: ChatClient,
    engineer_client: ChatClient,
    *,
    pm_candidate: str = "muse-glimmer",
    engineer_candidate: str = "muse-glimmer",
    orchestrator_client: ChatClient | None = None,
    orchestrator_candidate: str = "muse-glimmer",
) -> WorkflowAssignment:
    """Bind every role or raise BindingRefused. The workflow is an explicit opt-in to its
    experimental roles; planned roles and unapproved candidates are always refused.

    With an orchestrator client the topology is separate. The orchestrator role is
    implemented for the single investigator; as a separate workflow call it is
    experimental, and its binding says so.
    """
    pm = bindings.bind_runtime(
        "product_manager", pm_candidate, pm_client.config, providers, allow_experimental=True
    )
    engineer = bindings.bind_runtime(
        "geospatial_engineer",
        engineer_candidate,
        engineer_client.config,
        providers,
        allow_experimental=True,
    )
    if orchestrator_client is None:
        return WorkflowAssignment(pm=pm, engineer=engineer)
    orchestrator = bindings.bind_runtime(
        "orchestrator",
        orchestrator_candidate,
        orchestrator_client.config,
        providers,
        allow_experimental=True,
    ).model_copy(update={"implementation": "experimental"})
    return WorkflowAssignment(pm, engineer, "separate", orchestrator)


def repo_assignment(
    providers: Mapping[str, ProviderConfig],
    client: ChatClient,
    root: Path = Path(),
    topology: Topology = "combined",
) -> WorkflowAssignment:
    """Every role on one client, bound through the repository's bindings file."""
    orchestrator = client if topology == "separate" else None
    bindings = load_bindings(root / BINDINGS_FILE)
    return resolve_assignment(bindings, providers, client, client, orchestrator_client=orchestrator)


def task_scope(case_file: CaseFile) -> TaskScope:
    """The tools and datasets for a task on this case only."""
    tools = PLAN_TOOLS | _BY_VARIABLE.get(case_file.case.variable, frozenset())
    return TaskScope(tools=tools, dataset_ids=frozenset(case_file.assets))

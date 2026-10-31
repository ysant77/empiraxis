"""Role bindings for scripted workflow tests: the fake Glimmer client, bound like the real one."""

from __future__ import annotations

from typing import Any

from fake_client import FAKE_CONFIG

from earthlab.implement.bindings import Bindings
from earthlab.llm.client import ChatClient
from earthlab.workflow.assign import WorkflowAssignment, resolve_assignment

PREFLIGHT = {
    "checked_on": "2026-10-30",
    "json_schema": "pass",
    "tool_call": "pass",
    "served_model": "muse-glimmer-30B",
}


def candidate(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "candidate_id": "fake-glimmer",
        "family": "meta-muse",
        "model_id": FAKE_CONFIG.model,
        "provider_id": FAKE_CONFIG.name,
        "roles": ["product_manager", "geospatial_engineer"],
        "license": "Apache-2.0",
        "license_checked": True,
        "enabled": True,
        "preflight": PREFLIGHT,
    }
    return {**base, **overrides}


def bindings(*candidates: dict[str, Any], status: str = "experimental") -> Bindings:
    roles = {
        role: {"families": ["meta-muse", "meta-llama"], "status": status}
        for role in ("product_manager", "orchestrator", "geospatial_engineer")
    }
    return Bindings.model_validate(
        {"schema_version": "1", "roles": roles, "candidates": list(candidates) or [candidate()]}
    )


def assignment(client: ChatClient) -> WorkflowAssignment:
    return resolve_assignment(
        bindings(), {FAKE_CONFIG.name: FAKE_CONFIG}, client, client,
        pm_candidate="fake-glimmer", engineer_candidate="fake-glimmer",
    )  # fmt: skip

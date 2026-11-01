from __future__ import annotations

import ast
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest
import yaml

from earthlab.efficiency.__main__ import main
from earthlab.efficiency.paired import load_plan, order_for
from earthlab.efficiency.router import (
    ROUTING_MODEL_CALLS,
    Budget,
    Complexity,
    Policy,
    complexity_of,
    route,
)
from earthlab.implement.bindings import Bindings, load_bindings
from earthlab.llm.providers import ProviderConfig, load_providers

ROOT = Path(__file__).resolve().parents[1]
CASE = "kalimantan-2015-burned-area"
BUDGET = Budget(max_model_calls=40, max_seconds=3600, max_usd=1.0)
PREFLIGHT = {
    "checked_on": "2026-11-01",
    "json_schema": "pass",
    "tool_call": "pass",
    "served_model": "m",
}


def _repo() -> tuple[Bindings, dict[str, ProviderConfig]]:
    return (
        load_bindings(ROOT / "config/roles/bindings.yaml"),
        load_providers(ROOT / "config/providers.yaml"),
    )


def _small_pm(bindings: Bindings, **over: Any) -> Bindings:
    raw = deepcopy(bindings.model_dump(mode="json"))
    llama = next(c for c in raw["candidates"] if c["candidate_id"] == "llama-3-2-3b")
    llama |= {
        "roles": ["product_manager"],
        "planned_roles": [],
        "license_checked": True,
        "enabled": True,
        "provider_id": "local-small",
        "preflight": PREFLIGHT,
    } | over
    return Bindings.model_validate(raw)


def _providers(extra: dict[str, ProviderConfig]) -> dict[str, ProviderConfig]:
    return _repo()[1] | extra


def _local(name: str = "local-small") -> ProviderConfig:
    return ProviderConfig(
        name=name,
        kind="local",
        base_url="http://127.0.0.1:8081/v1",
        model="meta-llama/Llama-3.2-3B-Instruct",
        logical_model="llama-3-2-3b",
        usd_per_mtok_input=0.0,
        usd_per_mtok_output=0.0,
    )


LOW = complexity_of(
    "How much area burned in the Kalimantan study box in September 2015?", (CASE,), CASE
)


def test_complexity_indicators() -> None:
    assert LOW.level == "low" and LOW.periods_named == 1
    causal = complexity_of("Did clearing cause the fires in September 2015?", (CASE,), CASE)
    assert causal.causal_wording and causal.level == "high"
    assert complexity_of("Will fires rise next month?", (CASE,), CASE).level == "high"
    assert complexity_of("x", (CASE,), None).case_registered is False
    two = complexity_of("Compare September 2015 with October 2015", (CASE,), CASE)
    assert two.periods_named == 2 and two.level == "high"


def test_policy_a_binds_existing_muse_roles() -> None:
    d = route("A", LOW, *_repo(), BUDGET)
    assert (d.effective, d.pm_candidate, d.orchestrator_candidate, d.engineer_candidate) == (
        "A",
        "muse-glimmer",
        "muse-glimmer",
        "muse-glimmer",
    )
    assert d.can_run and d.routing_model_calls == ROUTING_MODEL_CALLS == 0


def test_policy_c_has_no_orchestrator_call() -> None:
    d = route("C", LOW, *_repo(), BUDGET)
    assert d.effective == "C" and d.orchestrator_candidate is None and d.can_run
    assert d.planned_model_calls_max < route("A", LOW, *_repo(), BUDGET).planned_model_calls_max


def test_policy_b_falls_back_when_no_small_model_is_approved() -> None:
    d = route("B", LOW, *_repo(), BUDGET)
    assert d.requested == "B" and d.effective == "A"
    assert any("falling back to policy A" in f for f in d.fallbacks)
    assert d.pm_candidate == "muse-glimmer"


def test_policy_b_uses_an_approved_small_model() -> None:
    bindings, providers = _small_pm(_repo()[0]), _providers({"local-small": _local()})
    d = route("B", LOW, bindings, providers, BUDGET)
    assert d.effective == "B" and d.pm_candidate == "llama-3-2-3b"
    assert d.engineer_candidate == "muse-glimmer" and d.fallbacks == ()


def test_policy_b_needs_its_provider_enabled() -> None:
    bindings = _small_pm(_repo()[0])
    off = _local().model_copy(update={"enabled": False})
    d = route("B", LOW, bindings, _providers({"local-small": off}), BUDGET)
    assert d.effective == "A"
    missing = route("B", LOW, bindings, _repo()[1], BUDGET)
    assert missing.effective == "A"


def test_unvalidated_model_cannot_be_enabled_or_chosen() -> None:
    raw = deepcopy(_repo()[0].model_dump(mode="json"))
    llama = next(c for c in raw["candidates"] if c["candidate_id"] == "llama-3-1-8b")
    llama |= {
        "roles": ["product_manager"],
        "planned_roles": [],
        "enabled": True,
        "license_checked": True,
        "provider_id": "local-small",
        "preflight": None,
    }  # no preflight
    with pytest.raises(ValueError, match="passed preflight"):
        Bindings.model_validate(raw)


def test_high_complexity_keeps_policy_a() -> None:
    high = complexity_of("Did clearing cause the burn?", (CASE,), CASE)
    policies: tuple[Policy, ...] = ("B", "C")
    for policy in policies:
        d = route(policy, high, *_repo(), BUDGET)
        assert d.effective == "A" and "complexity is high" in d.fallbacks[0]


def test_budget_gates() -> None:
    tight = Budget(max_model_calls=5, max_seconds=60, max_usd=0.0)
    d = route("A", LOW, *_repo(), tight)
    assert not d.can_run and "model calls" in d.refusals[-1]


def test_hosted_provider_needs_price_and_usd_budget() -> None:
    bindings = _small_pm(_repo()[0], provider_id="hosted-small")
    hosted = ProviderConfig(
        name="hosted-small",
        kind="hosted",
        base_url="https://x.example/v1",
        model="m",
        logical_model="llama-3-2-3b",
        api_key_env="KEY",
    )
    d = route("B", LOW, bindings, _providers({"hosted-small": hosted}), BUDGET)
    assert d.effective == "A" and "no recorded price" in "; ".join(d.fallbacks)
    free = Budget(max_model_calls=40, max_seconds=60, max_usd=0.0)
    priced = hosted.model_copy(update={"usd_per_mtok_input": 1.0, "usd_per_mtok_output": 2.0})
    d2 = route("B", LOW, bindings, _providers({"hosted-small": priced}), free)
    assert "positive USD budget" in "; ".join(d2.fallbacks)


def test_nothing_can_serve_is_a_refusal() -> None:
    raw = deepcopy(_repo()[0].model_dump(mode="json"))
    for c in raw["candidates"]:
        c |= {"roles": [], "enabled": False}
    d = route("A", LOW, Bindings.model_validate(raw), _repo()[1], BUDGET)
    assert d.pm_candidate is None and not d.can_run


def test_router_is_pure_and_imports_no_model_client() -> None:
    assert route("B", LOW, *_repo(), BUDGET) == route("B", LOW, *_repo(), BUDGET)
    tree = ast.parse((ROOT / "src/earthlab/efficiency/router.py").read_text(encoding="utf-8"))
    imported = {n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not {m for m in imported if m.startswith(("httpx", "earthlab.llm.client", "requests"))}


def test_complexity_model_is_strict() -> None:
    with pytest.raises(ValueError):
        Complexity(
            case_registered=True, causal_wording=False, forecast_wording=False, periods_named=-1
        )


def test_paired_plan_is_valid_and_uses_only_dev_scenarios() -> None:
    plan = load_plan(ROOT / "config/efficiency/paired_tasks.yaml")
    dev = yaml.safe_load((ROOT / plan.source_suite).read_text(encoding="utf-8"))
    ids = {s["id"] for s in dev["scenarios"]}
    assert {t.scenario_id for t in plan.tasks} <= ids
    assert "heldout" not in plan.source_suite
    assert {c.id for c in plan.acceptance.hard} >= {"H1", "H2", "H3", "H4", "H5"}


def test_paired_orders_are_balanced() -> None:
    firsts = [order_for(i)[0] for i in range(6)]
    assert sorted(firsts) == ["A", "A", "B", "B", "C", "C"]
    assert all(sorted(order_for(i)) == ["A", "B", "C"] for i in range(6))


def test_paired_plan_rejects_heldout_source(tmp_path: Path) -> None:
    raw = yaml.safe_load((ROOT / "config/efficiency/paired_tasks.yaml").read_text())
    raw["source_suite"] = "evals/heldout_v1.protocol.yaml"
    path = tmp_path / "p.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="held-out"):
        load_plan(path)
    raw["source_suite"] = "evals/workflow_dev_v1.yaml"
    raw["policies"] = ["A", "B"]
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    with pytest.raises(ValueError, match="exactly policies"):
        load_plan(path)


def test_cli_route_and_plan(capsys: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    assert (
        main(
            [
                "route",
                "How much area burned in the Kalimantan study box in September 2015?",
                "--case-id",
                CASE,
            ]
        )
        == 0
    )
    out = capsys.readouterr().out
    assert '"effective": "C"' in out and '"level": "low"' in out
    assert main(["plan"]) == 0
    assert "PT-01" in capsys.readouterr().out

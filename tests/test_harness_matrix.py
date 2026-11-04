"""Arm config, binding gates, rotated order, the time estimate, and the runner."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from fake_client import ScriptedClient

from earthlab.harness.arms import ArmSpec, build_role_clients, gate_blockers
from earthlab.harness.compare import build, load_runs, markdown
from earthlab.harness.matrix import MatrixPlan, estimate_hours, expand, load_plan
from earthlab.harness.matrix_run import Refused, pin_problems, run_stage
from earthlab.harness.variants import load_variants
from earthlab.implement.bindings import Bindings
from earthlab.llm.client import ChatClient
from earthlab.llm.providers import ProviderConfig, load_providers

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "config"
PIN = "a" * 40


@pytest.fixture(scope="module")
def plan() -> MatrixPlan:
    return load_plan(CONFIG / "benchmark" / "matrix.yaml")


@pytest.fixture(scope="module")
def providers() -> dict[str, ProviderConfig]:
    return load_providers(CONFIG / "providers.yaml")


@pytest.fixture(scope="module")
def bindings() -> Bindings:
    return Bindings.model_validate(
        yaml.safe_load((CONFIG / "roles" / "bindings.yaml").read_text(encoding="utf-8"))
    )


def test_an_arm_must_name_the_roles_of_its_kind() -> None:
    with pytest.raises(ValueError, match="names roles"):
        ArmSpec(arm_id="x", arm="team", lead="local-glimmer")
    with pytest.raises(ValueError, match="names roles"):
        ArmSpec(arm_id="x", arm="fixed", lead="local-glimmer")
    with pytest.raises(ValueError, match="must be a named role"):
        ArmSpec(arm_id="x", arm="single", lead="local-glimmer", muse_roles=("pm",))


def test_the_plan_stays_inside_the_hour_budget_and_names_known_arms(plan: MatrixPlan) -> None:
    assert estimate_hours(plan, list(plan.default_path)) <= plan.budget.total_hours
    fallback = [s for s in plan.default_path if s != "screen-mixed"] + ["fallback-single"]
    assert estimate_hours(plan, fallback) <= plan.budget.total_hours
    assert {a.block for a in plan.arms} == {
        "none", "muse", "muse+local-llama-3-2-3b", "muse+local-qwen3-4b-2507",
        "muse+local-llama-3-1-8b", "local-qwen3-4b-2507", "local-llama-3-2-3b",
    }  # fmt: skip
    assert plan.stage("fallback-single").alternative_to == "screen-mixed"


def test_the_order_rotates_each_repeat_and_lists_each_pair_once(plan: MatrixPlan) -> None:
    runs = expand(plan, "confirm")
    one = [r.arm_id for r in runs if r.scenario == "burned-area-method" and r.repeat == 1]
    two = [r.arm_id for r in runs if r.scenario == "burned-area-method" and r.repeat == 2]
    assert sorted(one) == sorted(two) == ["T-M-base", "T-M-win"] and one != two
    assert [r.order for r in runs] == list(range(1, len(runs) + 1))
    assert not any(r.scenario == "pm25-regression" for r in runs)
    assert sum(r.arm_id == "T-M-base" for r in runs) == 3  # the same-session control


def test_muse_arms_pass_the_gates_and_a_disabled_small_model_does_not(
    plan: MatrixPlan, providers: dict[str, ProviderConfig], bindings: Bindings
) -> None:
    assert gate_blockers(plan.arm("T-M-v1"), bindings, providers) == []
    assert gate_blockers(plan.arm("T-sp4"), bindings, providers) == []  # preflight passed
    found = gate_blockers(plan.arm("T-sp8"), bindings, providers)  # its preflight failed
    assert found and any("llama-3-1-8b" in f for f in found)


def test_a_muse_role_cannot_be_served_by_another_model(
    providers: dict[str, ProviderConfig], bindings: Bindings
) -> None:
    arm = ArmSpec(arm_id="bad", arm="single", lead="local-llama-3-1-8b", muse_roles=("lead",))
    assert any("must be a Muse model" in f for f in gate_blockers(arm, bindings, providers))


def test_roles_get_the_client_of_their_own_provider(
    plan: MatrixPlan, providers: dict[str, ProviderConfig]
) -> None:
    made: list[str] = []

    def build_fake(config: ProviderConfig) -> ChatClient:
        made.append(config.name)
        return ScriptedClient([], config)

    default, per_role = build_role_clients(plan.arm("T-sp4"), providers, build_fake)
    assert made.count("local-glimmer") == 1 and "local-qwen3-4b-2507" in made
    assert default is per_role["geospatial_engineer"]
    assert per_role["data_specialist"] is per_role["ml_engineer"]
    assert per_role["data_specialist"].config.name == "local-qwen3-4b-2507"
    assert build_role_clients(plan.arm("F"), providers, build_fake) == (None, {})


def test_the_commit_pin_refuses_a_moved_head_and_a_dirty_tree() -> None:
    assert pin_problems(PIN, PIN, False) == []
    assert len(pin_problems("b" * 40, PIN, True)) == 2
    assert pin_problems("abc", PIN, False)


def fake_run(calls: list[dict[str, Any]], status: str = "awaiting_human") -> Any:
    def run_one(name: str, arm: str, run_dir: Path, client: Any, **kw: Any) -> dict[str, Any]:
        calls.append({"scenario": name, "arm": arm, "variant": kw["variant"].id})
        (run_dir / "result.json").write_text(
            json.dumps({"status": status, "state": "forwarded", "usage": {"wall_seconds": 1.0}}),
            encoding="utf-8",
        )
        return {"status": status}

    return run_one


def stage(plan: MatrixPlan, tmp_path: Path, **kw: Any) -> list[dict[str, Any]]:
    cfg = load_providers(CONFIG / "providers.yaml")
    bind = Bindings.model_validate(
        yaml.safe_load((CONFIG / "roles" / "bindings.yaml").read_text(encoding="utf-8"))
    )
    args: dict[str, Any] = {
        "variants": load_variants(CONFIG / "benchmark" / "prompt_variants.yaml"),
        "providers": cfg, "bindings": bind, "pin": PIN, "repo": ROOT, "out_dir": tmp_path,
        "build": lambda c: ScriptedClient([], c), "head_of": lambda _r: (PIN, False),
    }  # fmt: skip
    return run_stage(plan, "screen-muse", "muse", **(args | kw))


def test_the_runner_writes_a_manifest_that_harness_compare_reads(
    plan: MatrixPlan, tmp_path: Path
) -> None:
    calls: list[dict[str, Any]] = []
    rows = stage(plan, tmp_path, run_one=fake_run(calls))
    assert len(rows) == 10 and {c["variant"] for c in calls} == {
        "baseline", "note-close-v1", "note-close-reminder-v1"
    }  # fmt: skip
    again = stage(plan, tmp_path, run_one=fake_run(calls))
    assert again == [] and len(calls) == 10
    lines = (tmp_path / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["commit"] == PIN
    table = build(load_runs(tmp_path / "manifest.jsonl"))
    arm = table["scenarios"]["burned-area-method"]["T-M-v1"]
    assert arm["prompt_variant"] == "note-close-v1" and "local-glimmer" in arm["models"]
    assert "| prompt variant |" in markdown(table)


def test_two_failures_in_a_row_stop_the_stage(plan: MatrixPlan, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    rows = stage(plan, tmp_path, run_one=fake_run(calls, status="failed"))
    assert len(rows) == 2 and all(r["exit"] == 2 for r in rows)
    assert "failures in a row" in (tmp_path / "manifest.jsonl").read_text(encoding="utf-8")


def test_a_crash_is_a_row_and_the_time_budget_stops_before_an_overrun(
    plan: MatrixPlan, tmp_path: Path
) -> None:
    def boom(*_a: Any, **_k: Any) -> dict[str, Any]:
        raise RuntimeError("server down")

    rows = stage(plan, tmp_path, run_one=boom)
    assert rows[0]["status"] == "crashed" and "server down" in rows[0]["err"]
    quiet = tmp_path / "q"
    assert stage(plan, quiet, run_one=fake_run([]), minutes_left=1.0) == []


def test_the_runner_refuses_before_any_run(plan: MatrixPlan, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    with pytest.raises(Refused, match="pinned commit"):
        stage(plan, tmp_path, run_one=fake_run(calls), pin="b" * 40)
    off = yaml.safe_load((CONFIG / "roles" / "bindings.yaml").read_text(encoding="utf-8"))
    for candidate in off["candidates"]:
        if candidate["candidate_id"] == "qwen3-4b-2507":
            candidate |= {"enabled": False, "planned_roles": ["data_specialist"], "roles": []}
    with pytest.raises(Refused, match="not approved for use"):
        run_stage(
            plan, "screen-mixed", "muse+local-qwen3-4b-2507",
            variants=load_variants(CONFIG / "benchmark" / "prompt_variants.yaml"),
            providers=load_providers(CONFIG / "providers.yaml"),
            bindings=Bindings.model_validate(off),
            pin=PIN, repo=ROOT, out_dir=tmp_path / "m", winner="note-close-v1",
            run_one=fake_run(calls), head_of=lambda _r: (PIN, False),
        )  # fmt: skip
    with pytest.raises(Refused, match="needs --winner"):
        run_stage(
            plan, "confirm", "muse",
            variants=load_variants(CONFIG / "benchmark" / "prompt_variants.yaml"),
            providers=load_providers(CONFIG / "providers.yaml"),
            bindings=Bindings.model_validate(
                yaml.safe_load((CONFIG / "roles" / "bindings.yaml").read_text(encoding="utf-8"))
            ),
            pin=PIN, repo=ROOT, out_dir=tmp_path / "w", head_of=lambda _r: (PIN, False),
        )  # fmt: skip
    assert calls == []


def test_a_waived_lead_gate_needs_a_single_unranked_arm_and_still_checks_the_model(
    plan: MatrixPlan, providers: dict[str, ProviderConfig], bindings: Bindings
) -> None:
    with pytest.raises(ValueError, match="single, unranked"):
        ArmSpec(arm_id="x", arm="single", lead="local-qwen3-4b-2507", lead_gate_waived=True)
    fallback = plan.arm("S-q4")
    assert not fallback.ranked and fallback.block == "local-qwen3-4b-2507"
    assert gate_blockers(fallback, bindings, providers) == []  # Qwen passed its preflight
    failed = ArmSpec(
        arm_id="y", arm="single", lead="local-llama-3-1-8b", lead_gate_waived=True, ranked=False
    )
    found = gate_blockers(failed, bindings, providers)
    assert any("data_specialist" in f for f in found)  # judged in the specialist seat


def test_the_tuned_arm_is_refused_until_a_person_adds_the_reviewed_variant(
    plan: MatrixPlan, tmp_path: Path
) -> None:
    with pytest.raises(Refused, match="qwen-tuned-v1"):
        run_stage(
            plan, "screen-tuned", "muse+local-qwen3-4b-2507",
            variants=load_variants(CONFIG / "benchmark" / "prompt_variants.yaml"),
            providers=load_providers(CONFIG / "providers.yaml"),
            bindings=Bindings.model_validate(
                yaml.safe_load((CONFIG / "roles" / "bindings.yaml").read_text(encoding="utf-8"))
            ),
            pin=PIN, repo=ROOT, out_dir=tmp_path, head_of=lambda _r: (PIN, False),
        )  # fmt: skip


def test_only_arms_limits_a_block_to_the_named_arm(plan: MatrixPlan, tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    rows = stage(plan, tmp_path, run_one=fake_run(calls), only_arms=frozenset({"S-M"}))
    assert {r["arm_id"] for r in rows} == {"S-M"} and len(calls) == len(rows) == 4

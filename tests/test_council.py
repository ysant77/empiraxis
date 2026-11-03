"""Council identity, the decision critic and the arm rules. Scripted clients only; no server."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fake_client import FAKE_CONFIG, ScriptedClient, call, say
from pydantic import ValidationError
from test_harness_engine import SOURCE, trainer  # noqa: F401
from test_harness_variants import clients

from earthlab.harness import critic_eval
from earthlab.harness import decision_critic as dc
from earthlab.harness.arms import ArmSpec
from earthlab.harness.contracts import EvaluationReportV1, ModelScore, ResearchRequestV1
from earthlab.harness.council import CouncilOptions
from earthlab.harness.engine import run_harness
from earthlab.harness.identity import CheckpointV1, bindings_of, council_summary, load_registry
from earthlab.harness.matrix import load_plan
from earthlab.harness.regression import PM25_PROBLEM, RegressionAdapter
from earthlab.harness.seats import Seats
from earthlab.harness.variants import load_variants
from earthlab.trace import RunTrace

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "examples" / "replay" / "scenario-muse-method-comparison" / "evaluation-plan-1.json"
VARIANTS = ROOT / "config" / "benchmark" / "prompt_variants.yaml"
SHA_A, SHA_B = "a" * 64, "b" * 64


def ckpt(provider: str, sha: str) -> CheckpointV1:
    return CheckpointV1(
        provider=provider, family="test", file=f"{provider}.gguf", sha256=sha, size_bytes=10,
        quantization="Q4_K_M", licence="test", source="test",
    )  # fmt: skip


def named(name: str, steps: list[Any] | None = None) -> ScriptedClient:
    return ScriptedClient(steps or [], FAKE_CONFIG.model_copy(update={"name": name}))


def report() -> EvaluationReportV1:
    return critic_eval.load_report(REPORT)


def test_the_checkpoint_registry_covers_every_provider_in_the_m4_matrix() -> None:
    registry = load_registry(ROOT / "config" / "benchmark" / "checkpoints.yaml")
    plan = load_plan(ROOT / "config" / "benchmark" / "m4-matrix.yaml")
    needed = {name for arm in plan.arms for name in arm.providers().values()}
    assert needed <= set(registry)
    shas = {registry[name].sha256 for name in needed}
    assert len(shas) == len(needed), "two providers must not share one digest"


def test_a_council_is_heterogeneous_only_when_digests_differ() -> None:
    registry = {"p1": ckpt("p1", SHA_A), "p2": ckpt("p2", SHA_B), "p3": ckpt("p3", SHA_A)}
    same = {"product_manager": named("p1"), "geospatial_engineer": named("p3")}
    mixed = {"product_manager": named("p1"), "data_specialist": named("p2")}
    assert council_summary(bindings_of(same, registry))["heterogeneous"] is False
    got = council_summary(bindings_of(mixed, registry))
    assert got["heterogeneous"] is True and got["distinct_checkpoints"] == 2


def test_a_seat_without_a_checkpoint_entry_is_an_error() -> None:
    with pytest.raises(KeyError, match="no checkpoint entry"):
        bindings_of({"product_manager": named("ghost")}, {})


def test_the_critic_contract_ties_the_verdict_to_the_findings() -> None:
    with pytest.raises(ValidationError, match="verdict concerns"):
        dc.DecisionCritiqueV1(verdict="concerns")
    with pytest.raises(ValidationError, match="no_concern"):
        dc.DecisionCritiqueV1(verdict="no_concern", findings=(finding(),))


def finding(**over: Any) -> dc.CriticFinding:
    base: dict[str, Any] = {
        "kind": "selection_not_supported",
        "claim": "The TCN error is above the lagged ridge error on the same rows.",
        "evidence": ({"field": "candidate-1.mae", "value": 4.711},
                     {"field": "B4_lagged_ridge.mae", "value": 4.68}),
        "falsified_by": "A lower candidate-1 MAE on the same validation rows.",
    }  # fmt: skip
    return dc.CriticFinding.model_validate(base | over)


def test_code_checks_every_cited_value_against_the_report() -> None:
    facts = dc.fact_table(report())
    assert dc.finding_issues(finding(), facts, "pm25-method-comparison-6h") == []
    wrong = finding(evidence=({"field": "candidate-1.mae", "value": 3.9},))
    assert "differs from" in dc.finding_issues(wrong, facts, "x")[0]
    ghost = finding(evidence=({"field": "candidate-9.mae", "value": 1.0},))
    assert "not an evaluator field" in dc.finding_issues(ghost, facts, "x")[0]


@pytest.mark.parametrize(
    ("claim", "expect"),
    [
        ("The TCN error of 9.999 is above the ridge error of 4.680 here.", "9.999"),
        ("The sealed test period would show the TCN error rising above the ridge.", "sealed"),
        ("This is a well-chosen decision and the numbers look good to me.", "praise"),
        ("The ridge error is high because of fires near the border, as shown.", "cause"),
    ],
)
def test_a_finding_with_an_unbacked_number_or_a_banned_claim_is_refused(
    claim: str, expect: str
) -> None:
    issues = dc.finding_issues(finding(claim=claim), dc.fact_table(report()), "pm25-x")
    assert any(expect in i for i in issues), issues


def test_the_fact_table_names_models_metrics_intervals_and_subgroups() -> None:
    score = ModelScore(
        model="m", metrics={"mae": 1.5, "bias": None}, low=0.1, high=0.2,
        subgroups={"elevated": {"mae": 9.0}}, passes=True,
    )  # fmt: skip
    rep = EvaluationReportV1(
        evaluator="e", evaluator_sha256=SHA_A, split_scored="validation", reference="m",
        scores=(score,),
    )  # fmt: skip
    assert dc.fact_table(rep) == {
        "m.mae": 1.5, "m.skill_low": 0.1, "m.skill_high": 0.2, "m.elevated.mae": 9.0,
    }  # fmt: skip


def critic_script(*steps: Any) -> ScriptedClient:
    return named("critic-fake", list(steps))


def finding_args() -> dict[str, Any]:
    return finding().model_dump(mode="json")


def test_the_critic_records_a_backed_finding_and_does_not_decide(tmp_path: Path) -> None:
    client = critic_script(call("submit_critique", verdict="concerns", findings=[finding_args()]))
    seats = Seats("single", tmp_path, client, {})
    got = dc.run_critic(
        seats,
        report(),
        critic_eval.decision_of(critic_eval.CASES[0]),
        "pm25-m",
        "independent_model",
    )
    assert got["state"] == "usable" and got["advisory"] is True
    assert got["findings"][0]["backed"] is True
    assert [e["event"] for e in seats.trace.records()][-1] == "decision_critique"


def test_a_critic_that_cites_a_wrong_number_twice_is_unusable_and_the_run_goes_on(
    tmp_path: Path,
) -> None:
    bad = finding_args() | {"evidence": [{"field": "candidate-1.mae", "value": 1.0}]}
    step = call("submit_critique", verdict="concerns", findings=[bad])
    seats = Seats("single", tmp_path, critic_script(step, step), {})
    got = dc.run_critic(
        seats,
        report(),
        critic_eval.decision_of(critic_eval.CASES[0]),
        "pm25-m",
        "independent_model",
    )
    assert got["state"] == "unusable" and got["findings"] == []
    assert len(critic_eval.rejected_attempts(seats)) == 2


def test_a_critic_that_never_calls_the_tool_is_unusable(tmp_path: Path) -> None:
    seats = Seats("single", tmp_path, critic_script(say("fine"), say("fine")), {})
    got = dc.run_critic(
        seats,
        report(),
        critic_eval.decision_of(critic_eval.CASES[0]),
        "pm25-m",
        "independent_model",
    )
    assert got["state"] == "unusable"


def test_the_seeded_cases_are_scored_by_code_from_the_labels(tmp_path: Path) -> None:
    case = critic_eval.CASES[0]
    assert case.faulty and critic_eval.CASES[-1].faulty is False
    hit = critic_script(call("submit_critique", verdict="concerns", findings=[finding_args()]))
    rows = critic_eval.evaluate(hit, report(), tmp_path, (case,))
    assert rows[0]["detected"] is True and rows[0]["attempts_refused"] == 0
    quiet = critic_script(call("submit_critique", verdict="no_concern", findings=[]))
    clean = critic_eval.evaluate(quiet, report(), tmp_path / "q", (critic_eval.CASES[-1],))
    assert clean[0]["flagged"] is False
    summary = critic_eval.summarise(rows + clean)
    assert summary["detected"] == 1 and summary["clean_flagged"] == 0


def test_the_label_list_has_five_faulty_and_five_clean_cases_with_cited_fields() -> None:
    facts = dc.fact_table(report())
    faulty = [c for c in critic_eval.CASES if c.faulty]
    assert len(faulty) == 5 and len(critic_eval.CASES) == 10
    assert all(set(c.fault_fields) <= set(facts) for c in faulty)


def test_arm_rules_for_the_critic_and_the_number_of_servers() -> None:
    base: dict[str, Any] = {
        "arm_id": "X",
        "arm": "team",
        "pm": "local-glimmer",
        "lead": "local-glimmer",
        "specialist": "local-glimmer",
    }
    with pytest.raises(ValidationError, match="needs a critic provider"):
        ArmSpec.model_validate(base | {"decision_critic": True})
    with pytest.raises(ValidationError, match="at most one non-Muse"):
        ArmSpec.model_validate(base | {"specialist": "q", "critic": "l"})
    ok = ArmSpec.model_validate(base | {"critic": "l", "decision_critic": True})
    assert ok.providers()["method_critic"] == "l"


@pytest.mark.usefixtures("trainer")
def test_a_team_run_records_bindings_and_an_independent_critic(tmp_path: Path) -> None:
    pm, lead, worker = clients()
    critic = critic_script(call("submit_critique", verdict="no_concern", findings=[]))
    roles = {
        "product_manager": pm, "geospatial_engineer": lead, "data_specialist": worker,
        "ml_engineer": worker, "method_critic": critic,
    }  # fmt: skip
    registry = {
        "pm-fake": ckpt("pm-fake", SHA_A), "lead-fake": ckpt("lead-fake", SHA_A),
        "sp-fake": ckpt("sp-fake", SHA_B), "critic-fake": ckpt("critic-fake", SHA_B),
    }  # fmt: skip
    path = tmp_path / "run"
    done = run_harness(
        "team", ResearchRequestV1(request_id="r1", objective="Predict PM2.5."), PM25_PROBLEM,
        RegressionAdapter(path, SOURCE), path, lead, role_clients=roles,
        variant=load_variants(VARIANTS).get("note-close-reminder-v1"),
        options=CouncilOptions(registry, decision_critic=True),
    )  # fmt: skip
    assert done["status"] == "awaiting_human", done["reason"]
    assert done["council"]["heterogeneous"] is True and done["council"]["seats"] == 5
    assert done["decision_critique"]["state"] == "usable"
    assert done["roles"]["method_critic"]["provider"] == "critic-fake"
    events = [e["event"] for e in RunTrace(path / "trace.jsonl").records()]
    assert events.count("role_binding") == 5 and events.index("council_formed") < events.index(
        "model_turn"
    )
    assert events.index("decision_critique") < events.index("finish")


@pytest.mark.usefixtures("trainer")
def test_without_options_a_run_has_no_council_records(tmp_path: Path) -> None:
    pm, lead, worker = clients()
    roles = {"product_manager": pm, "geospatial_engineer": lead,
             "data_specialist": worker, "ml_engineer": worker}  # fmt: skip
    path = tmp_path / "run"
    done = run_harness(
        "team", ResearchRequestV1(request_id="r1", objective="Predict PM2.5."), PM25_PROBLEM,
        RegressionAdapter(path, SOURCE), path, lead, role_clients=roles,
        variant=load_variants(VARIANTS).get("note-close-reminder-v1"),
    )  # fmt: skip
    assert "council" not in done and "decision_critique" not in done
    assert "role_binding" not in {e["event"] for e in RunTrace(path / "trace.jsonl").records()}


def test_every_m4_arm_passes_the_binding_gates_with_the_real_config() -> None:
    import yaml

    from earthlab.harness.arms import gate_blockers
    from earthlab.implement.bindings import Bindings
    from earthlab.llm.providers import load_providers

    config = ROOT / "config"
    bindings = Bindings.model_validate(
        yaml.safe_load((config / "roles" / "bindings.yaml").read_text(encoding="utf-8"))
    )
    providers = load_providers(config / "providers.yaml")
    plan = load_plan(config / "benchmark" / "m4-matrix.yaml")
    for arm in plan.arms:
        assert gate_blockers(arm, bindings, providers) == [], arm.arm_id

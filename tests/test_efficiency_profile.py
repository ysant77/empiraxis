from __future__ import annotations

import json
from pathlib import Path

from earthlab.efficiency.__main__ import main
from earthlab.efficiency.load import attribute_turns, load_runs
from earthlab.efficiency.report import render_markdown, summarize

FIXTURES = Path(__file__).parent / "fixtures" / "efficiency"


def _by_id() -> dict[str | None, object]:
    profiles, _ = load_runs(FIXTURES)
    return {p.run_id: p for p in profiles}


def test_roles_are_attributed_from_brackets_and_role_field() -> None:
    p = _by_id()["fx-separate"]
    assert [(u.role, u.model_calls) for u in p.roles] == [  # type: ignore[attr-defined]
        ("product_manager", 2),
        ("orchestrator", 1),
        ("geospatial_engineer", 2),
    ]


def test_direct_arm_is_all_engineer() -> None:
    p = _by_id()["fx-direct"]
    (u,) = p.roles  # type: ignore[attr-defined]
    assert (u.role, u.prompt_tokens, u.completion_tokens, u.wall_seconds) == (
        "geospatial_engineer",
        2100,
        150,
        15.0,
    )
    assert p.answer_revisions == 1  # type: ignore[attr-defined]


def test_missing_usage_is_missing_not_zero() -> None:
    p = _by_id()["fx-separate"]
    orch = p.usage("orchestrator")  # type: ignore[attr-defined]
    assert orch.prompt_tokens is None and orch.completion_tokens is None
    assert orch.calls_with_usage == 0 and orch.wall_seconds == 7.0
    pm = p.usage("product_manager")  # type: ignore[attr-defined]
    assert pm.calls_with_usage == 2 and pm.prompt_tokens == 500


def test_cost_keeps_local_compute_apart_from_billed_cost() -> None:
    cost = _by_id()["fx-separate"].cost  # type: ignore[attr-defined]
    assert cost.local_model_wall_seconds == 54.0
    assert cost.billed_provider_cost_usd is None
    assert cost.local_energy_wh is None
    assert cost.billed_cost_note.startswith("NOT_MEASURED")


def test_goal_abstention_and_failure() -> None:
    ids = _by_id()
    assert ids["fx-direct"].goal_satisfied is True  # type: ignore[attr-defined]
    assert ids["fx-separate"].abstained is True  # type: ignore[attr-defined]
    wrong = ids["fx-wrong"]
    assert wrong.goal_satisfied is False and wrong.failed is False  # type: ignore[attr-defined]


def test_rows_without_artifacts_are_reported() -> None:
    profiles, anomalies = load_runs(FIXTURES)
    kinds = sorted(a.kind for a in anomalies)
    assert kinds == [
        "manifest_row_without_artifacts",
        "manifest_row_without_artifacts",
        "run_folder_not_in_manifest",
    ]
    states = {p.artifacts for p in profiles}
    assert states == {"complete", "no_run_folder", "no_trace"}
    missing = next(p for p in profiles if p.artifacts == "no_run_folder")
    assert missing.goal_satisfied is None and missing.roles == ()


def test_summary_counts_and_missing_values() -> None:
    profiles, anomalies = load_runs(FIXTURES)
    s = summarize(profiles, anomalies)
    assert s["manifest_rows"] == 5 and s["rows_with_complete_artifacts"] == 3
    direct = s["by_arm"]["direct"]
    assert direct["goal_satisfied"] == "1/2" and direct["runs_with_artifacts"] == 2
    orch = s["by_arm"]["separate"]["roles"]["orchestrator"]
    assert orch["prompt_tokens"] == {"median": None, "runs_with_value": 0, "runs_with_role": 1}
    assert s["by_arm"]["separate"]["stage_overhead"]["pm_token_share_median"] is None
    assert s["by_arm"]["direct"]["billed_provider_cost_usd"] == "not measured"
    assert s["observed_conditions"]["guard_cold_start_runs"] == ["s1/WD-02/separate"]
    assert len(s["uncontrolled_factors"]) >= 5


def test_overhead_share_with_full_usage() -> None:
    profiles, anomalies = load_runs(FIXTURES)
    direct = summarize(profiles, anomalies)["by_arm"]["direct"]["stage_overhead"]
    assert direct["engineer_token_share_median"] == 1.0
    assert direct["pm_and_orchestrator_token_share_median"] == 0.0


def test_markdown_marks_missing() -> None:
    profiles, anomalies = load_runs(FIXTURES)
    text = render_markdown(summarize(profiles, anomalies))
    assert "| separate |" in text and "missing" in text
    assert "Uncontrolled factors" in text


def test_attribute_turns_ignores_unknown_roles() -> None:
    trace = [
        {"event": "role_invocation", "data": {"role": "tool", "phase": "started"}},
        {"event": "model_turn", "data": {"role": "ghost"}},
    ]
    assert list(attribute_turns(trace)) == ["geospatial_engineer"]


def test_cli_profile_prints_json_and_markdown(capsys: object) -> None:
    assert main(["profile", "--runs", str(FIXTURES), "--json"]) == 0
    out = capsys.readouterr().out  # type: ignore[attr-defined]
    assert json.loads(out)["manifest_rows"] == 5
    assert main(["profile", "--runs", str(FIXTURES)]) == 0
    assert "Run profile" in capsys.readouterr().out  # type: ignore[attr-defined]

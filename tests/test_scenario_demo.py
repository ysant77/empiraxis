"""The four demonstration scenarios: one identity on three surfaces, and labels that stay true."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
from streamlit.testing.v1 import AppTest

from earthlab.board.progress import fold
from earthlab.events.adapter import load_run
from earthlab.events.manifest import listed_runs, verified_run
from earthlab.harness.credit import steps
from earthlab.runtime import open_workspace
from earthlab.trace import RunTrace
from earthlab.ui import common, scenarios
from earthlab.ui.engineering_lab import review_status
from earthlab.verify.replay import replay_run

ROOT = Path(__file__).resolve().parents[1]
REPLAY = ROOT / "examples" / "replay"
APP = ROOT / "src" / "earthlab" / "ui" / "app.py"
RUNS = {
    "S1": "scenario-s1-regression", "S2": "scenario-s2-encoder-reuse",
    "S3": "scenario-s3-transport", "S4": "scenario-s4-resource-request",
}  # fmt: skip


def record(run: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads((REPLAY / run / "result.json").read_text("utf-8"))
    return result


@pytest.mark.parametrize("scenario", list(RUNS))
@pytest.mark.parametrize("view", ["workspace", "control", "lab"])
def test_each_surface_shows_the_same_run_and_artifact(
    monkeypatch: pytest.MonkeyPatch, scenario: str, view: str
) -> None:
    monkeypatch.delenv("EARTHLAB_UI_MODE", raising=False)
    monkeypatch.chdir(ROOT)
    run = RUNS[scenario]
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.query_params["view"] = view
    app.query_params["run"] = f"replay/{run}"
    app.run()
    assert not app.exception
    text = "\n".join(str(c.value) for c in [*app.markdown, *app.caption, *app.info, *app.warning])
    events = load_run(verified_run(REPLAY, run))
    head = events.trace_head
    entry = next(r for r in listed_runs(REPLAY) if r["run"] == run)
    assert head[:16] in text and str(entry["result_sha256"])[:16] in text
    assert f"Scenario {scenario}" in text and not app.error


@pytest.mark.parametrize("run", list(RUNS.values()))
def test_replay_checks_a_recorded_scenario_and_finds_a_changed_file(
    run: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(ROOT)
    workspace = open_workspace(ROOT / "data" / "nea")
    saved = replay_run(REPLAY / run, workspace)
    assert saved.ok and saved.recorded and saved.files_checked >= 1
    copy = tmp_path / run
    shutil.copytree(REPLAY / run, copy)
    target = next(p for p in sorted(copy.glob("*.json")) if p.name != "result.json")
    target.write_text("{}", encoding="utf-8")
    changed = replay_run(copy, workspace)
    assert not changed.ok and target.name in changed.changed_files


def test_a_packaged_scenario_opens_no_human_decision() -> None:
    for run in (RUNS["S2"], RUNS["S3"]):
        assert record(run)["status"] == "recorded"
    for run in (RUNS["S1"], RUNS["S4"]):
        assert record(run)["status"] == "awaiting_human"


def test_every_scenario_says_what_really_ran(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    labels = [common.scenario_note(f"replay/{run}") or "" for run in RUNS.values()]
    assert "Real execution" in labels[0] and "Real execution" in labels[1]
    assert "Retrospective reanalysis" in labels[2] and "hindsight_diagnostic" in labels[2]
    assert "No signed approval exists" in labels[3] and "No segmentation model ran" in labels[3]
    assert common.scenario_note("replay/live-september-verified") is None


def test_s1_compares_baselines_and_stays_a_research_result() -> None:
    result = record(RUNS["S1"])
    assert result["recommendation"]["outcome"] == "adopt_limited"
    assert {row["model"] for row in result["comparison"]} >= {"B0_persistence", "B4_lagged_ridge"}
    ready = json.loads((REPLAY / RUNS["S1"] / "readiness-02d39d3ee183.json").read_text("utf-8"))
    assert ready["production_ready"] is False and ready["readiness"] == "research"
    assert any("elevated hours" in text for text in result["limitations"])


def test_s2_keeps_the_negative_result_against_persistence() -> None:
    result = record(RUNS["S2"])
    rows = {row["model"]: row for row in result["comparison"]}
    hybrid, alarm = rows["frozen_gru_logistic"], rows["persistence_alarm"]
    assert hybrid["f1"] < alarm["f1"] and hybrid["f1"] > rows["logistic"]["f1"]
    assert not hybrid["passes"] and result["recommendation"]["outcome"] == "retain_baseline"


def test_s3_is_inconclusive_and_names_no_source() -> None:
    result = record(RUNS["S3"])
    assert result["recommendation"]["outcome"] == "abstain"
    assert "inconclusive" in result["recommendation"]["reason"]
    assert "False" in result["recommendation"]["reason"]
    assert "not a source attribution" in " ".join(result["limitations"])
    assert not any(row["verdict"] == "consistent" for row in result["comparison"])


def test_s4_requests_resources_and_reports_no_segmentation_score() -> None:
    result = record(RUNS["S4"])
    assert result["recommendation"]["outcome"] == result["code_outcome"] == "request_resource"
    assert result["acceptance"]["no_segmentation_score"] is True
    chips = json.loads((REPLAY / RUNS["S4"] / "s4-measured-chips.json").read_text("utf-8"))
    assert "no signed" in chips["weights_authority"]


def test_no_scenario_file_holds_a_local_path() -> None:
    for run in RUNS.values():
        for path in (REPLAY / run).iterdir():
            assert "/Users/" not in path.read_text("utf-8"), path.name


TEAM = REPLAY / "scenario-muse-team-exceedance"


def test_the_muse_team_replay_holds_no_model_text_or_reasoning() -> None:
    for line in (TEAM / "trace.jsonl").read_text("utf-8").splitlines():
        entry = json.loads(line)
        if entry["event"] == "model_turn":
            assert not {"content", "reasoning", "request_id"} & set(entry["data"])


def test_a_step_is_credited_to_muse_only_when_the_trace_shows_its_proposal() -> None:
    rows = steps(TEAM)
    tools = {what: who for who, what, _ in rows}
    assert tools["prepare_data"] == tools["train_models"] == "deterministic code"
    assert tools["score"] == "independent evaluator code"
    assert tools["recommend"] == "muse-glimmer-30B (geospatial_engineer)"
    assert tools["review_scope"] == "muse-glimmer-30B (product_manager)"
    assert rows[-1][0] == "human" and "pending" in rows[-1][2]


@pytest.mark.parametrize(
    ("run", "owner"),
    [(RUNS["S1"], "controller"), (RUNS["S2"], "controller"), (RUNS["S3"], "controller"),
     (RUNS["S4"], "controller"), ("scenario-muse-team-exceedance", "product_manager")],
)  # fmt: skip
def test_a_role_owns_a_run_only_when_that_role_took_part(run: str, owner: str) -> None:
    entries = list(RunTrace(REPLAY / run / "trace.jsonl").records())
    view = fold(run, entries)
    assert view.root is not None and view.tasks[view.root].owner == owner


@pytest.mark.parametrize("scenario", ["S3", "S4"])
def test_a_run_with_no_score_makes_no_scoring_claim(
    monkeypatch: pytest.MonkeyPatch, scenario: str
) -> None:
    monkeypatch.delenv("EARTHLAB_UI_MODE", raising=False)
    monkeypatch.chdir(ROOT)
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.query_params["view"] = "lab"
    app.query_params["run"] = f"replay/{RUNS[scenario]}"
    app.run()
    text = "\n".join(str(c.value) for c in [*app.markdown, *app.caption])
    assert "Scored on validation only" not in text and "block-bootstrap" not in text


def page(view: str, run: str) -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.query_params["view"] = view
    app.query_params["run"] = f"replay/{run}"
    return app.run()


def visible(app: AppTest) -> str:
    parts = [str(e.value) for kind in ("markdown", "caption", "warning", "info")
             for e in getattr(app, kind)]  # fmt: skip
    parts += [f"{m.label} {m.value} {m.delta}" for m in app.metric]
    return "\n".join(parts + [t.value.to_string() for t in app.table])


@pytest.mark.parametrize("scenario", list(RUNS))
@pytest.mark.parametrize("view", ["workspace", "control", "lab"])
def test_a_scenario_page_opens_with_no_error(
    monkeypatch: pytest.MonkeyPatch, scenario: str, view: str
) -> None:
    monkeypatch.delenv("EARTHLAB_UI_MODE", raising=False)
    monkeypatch.chdir(ROOT)
    app = page(view, RUNS[scenario])
    assert not app.exception and not app.error
    assert app.subheader[0].value == scenarios.TITLES[scenario]


def test_the_pages_read_their_numbers_from_the_records(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    s1 = {r["model"]: r for r in record(RUNS["S1"])["comparison"]}
    text = visible(page("workspace", RUNS["S1"]))
    assert f"{s1['candidate-1']['mae']:.3f}" in text and "µg/m³" in text
    assert f"{s1['candidate-1']['above_55_mae']:.3f}" in text
    assert "operational forecast" not in text and "candidate-1" not in text
    s2 = {r["model"]: r for r in record(RUNS["S2"])["comparison"]}
    text = visible(page("workspace", RUNS["S2"]))
    assert f"{s2['frozen_gru_logistic']['f1']:.3f}" in text
    assert f"{s2['persistence_alarm']['f1']:.3f}" in text


def test_only_a_run_with_model_calls_shows_a_model_role(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    for run in RUNS.values():
        text = visible(page("control", run))
        assert "Trusted controller" in text or "packaging" in text.lower()
        assert "model: muse" not in text and "No critic took part" in text
    team = visible(page("control", scenarios.TEAM_RUN))
    assert "model: muse-glimmer-30B" in team and "Lead" in team and "same-model" in team


def test_a_packaging_trace_is_not_called_the_original_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(ROOT)
    for key in ("S2", "S3"):
        text = visible(page("control", RUNS[key]))
        assert "Packaging" in text and "not the original job" in text
        assert "No human decision is open" in text
    for key in ("S1", "S4"):
        text = visible(page("control", RUNS[key]))
        assert "Run's own trace" in text and "Human decision pending" in text


def test_s4_shows_no_score_and_no_approval(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.chdir(ROOT)
    text = visible(page("workspace", RUNS["S4"]))
    assert "Segmentation score None" in text and "no signed" in text.lower()
    assert "Texas" in text and "Scored on validation" not in text


@pytest.mark.parametrize("name", ["plan-1.json", "result.json"])
def test_a_corrupt_or_missing_scenario_file_shows_no_values(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, name: str
) -> None:
    monkeypatch.delenv("EARTHLAB_UI_MODE", raising=False)
    monkeypatch.chdir(ROOT)
    root = tmp_path / "replay"
    shutil.copytree(REPLAY, root)
    monkeypatch.setattr(common, "REPLAY_DIR", root)
    (root / RUNS["S1"] / name).write_text("{}", encoding="utf-8")
    app = page("workspace", RUNS["S1"])
    assert not app.exception and "not shown" in app.error[0].value
    assert not app.subheader


def test_missing_field_after_the_checks_is_reported_not_raised(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "result.json").write_text("{}", encoding="utf-8")
    with pytest.raises(FileNotFoundError):
        scenarios.story("S1", run_dir)


def test_switching_scenario_keeps_the_surface_and_the_url(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EARTHLAB_UI_MODE", raising=False)
    monkeypatch.chdir(ROOT)
    app = page("lab", RUNS["S1"])
    scenario = next(b for b in app.button_group if b.label == "Scenario")
    scenario.set_value("S3").run()
    assert not app.exception
    assert app.subheader[0].value == scenarios.TITLES["S3"]
    assert app.query_params["run"] == [f"replay/{RUNS['S3']}"] or (
        app.query_params["run"] == f"replay/{RUNS['S3']}"
    )
    assert "lab" in str(app.query_params["view"])
    surface = next(b for b in app.button_group if b.label == "Surface")
    surface.set_value("control").run()
    assert app.subheader[0].value == scenarios.TITLES["S3"]
    assert "control" in str(app.query_params["view"])


def test_the_demo_script_and_readme_quote_the_recorded_numbers() -> None:
    s1 = {r["model"]: r for r in record(RUNS["S1"])["comparison"]}
    s2 = {r["model"]: r for r in record(RUNS["S2"])["comparison"]}
    team = record(scenarios.TEAM_RUN)["usage"]
    numbers = [
        f"{s1['candidate-1']['mae']:.3f}", f"{s1['B0_persistence']['mae']:.3f}",
        f"{s1['candidate-1']['above_55_mae']:.3f}", f"{s1['B0_persistence']['above_55_mae']:.3f}",
        f"{s2['frozen_gru_logistic']['f1']:.3f}", f"{s2['logistic']['f1']:.3f}",
        f"{s2['persistence_alarm']['f1']:.3f}",
    ]  # fmt: skip
    for name in ("docs/demo-three-minute.md", "README.md"):
        text = (ROOT / name).read_text("utf-8")
        assert all(number in text for number in numbers), name
    script = (ROOT / "docs/demo-three-minute.md").read_text("utf-8")
    assert f"{team['model_calls']} model calls" in script
    assert str(team["wall_seconds"]) in script


def test_the_review_status_reads_its_summary_or_says_there_is_none(tmp_path: Path) -> None:
    assert review_status(tmp_path / "absent.json") is None
    path = tmp_path / "summary.json"
    path.write_text('{"conclusion": "Stays off.", "measures": [{"Measure": "a"}]}', "utf-8")
    assert review_status(path) == ("Stays off.", [{"Measure": "a"}])

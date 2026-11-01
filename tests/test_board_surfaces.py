"""Every surface shows the same run from the shared index, in any session, on any refresh."""

from __future__ import annotations

import json
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from earthlab.board.store import BOARD_FILE, Board, RunSpec
from earthlab.digest import file_digest
from earthlab.forecast.contracts import ARM_LABEL, LIMITATIONS
from earthlab.team.resources import OPERATOR_KEY_ENV, ResourceDesk, ResourceRequestV1
from earthlab.trace import RunTrace
from earthlab.ui import common, experiments, live

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "earthlab" / "ui" / "app.py"
REPLAY = ROOT / "examples" / "replay"
SPEC = RunSpec(
    question="How much area burned?",
    topology="combined",
    provider="local-glimmer",
    guard="local-llama-guard",
    reasoning="low",
)
SURFACES = ("workspace", "control", "lab")


@pytest.fixture
def operator(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("EARTHLAB_UI_MODE", "operator")
    monkeypatch.setenv("EARTHLAB_METRICS_PORT", "0")
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)
    return tmp_path


def open_view(view: str, run: str | None = None) -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.query_params["view"] = view
    if run is not None:
        app.query_params["run"] = run
    return app.run()


def shown(app: AppTest) -> str:
    parts = [*app.markdown, *app.caption, *app.info, *app.warning, *app.error]
    return "\n".join(str(item.value) for item in parts)


def saved_run(runs: Path, source: str, *, lines: int | None = None) -> tuple[Board, str]:
    board = Board(runs / BOARD_FILE)
    entry, _ = board.submit(SPEC, source)
    target = runs / entry.run_id
    shutil.copytree(REPLAY / source, target)
    if lines is not None:
        text = (target / "trace.jsonl").read_text(encoding="utf-8").splitlines()[:lines]
        (target / "trace.jsonl").write_text("\n".join(text) + "\n", encoding="utf-8")
        (target / "result.json").unlink()
        board.claim(entry.run_id, 1)
        return board, entry.run_id
    board.claim(entry.run_id, 1)
    board.end(entry.run_id, "finished")
    return board, entry.run_id


def test_three_sessions_show_one_run_identity(operator: Path) -> None:
    _, run_id = saved_run(operator, "live-september-verified")
    head = json.loads(
        (operator / run_id / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1]
    )["hash"]
    for view in SURFACES:
        app = open_view(view, run_id)
        assert not app.exception
        text = shown(app)
        assert run_id in text and "trace status verified" in text and head[:16] in text


def test_the_newest_operator_run_is_selected_first(operator: Path) -> None:
    _, run_id = saved_run(operator, "live-october-abstained")
    app = open_view("control")
    picker = next(s for s in app.selectbox if s.label == "Recorded run")
    assert picker.value == run_id and app.query_params["run"] == run_id


def test_a_run_in_progress_is_shown_as_unfinished_on_every_surface(operator: Path) -> None:
    _, run_id = saved_run(operator, "live-september-verified", lines=8)
    for view in SURFACES:
        app = open_view(view, run_id)
        assert not app.exception
        text = shown(app)
        assert "Run in progress" in text and "trace status not finished" in text
        assert "Integrity check failed" not in text and "verified." not in text


def test_a_queued_run_with_no_trace_is_not_called_a_failure(operator: Path) -> None:
    board = Board(operator / BOARD_FILE)
    entry, _ = board.submit(SPEC, "k")
    for view in SURFACES:
        app = open_view(view, entry.run_id)
        assert not app.exception
        text = shown(app)
        assert "Integrity check failed" not in text and "TraceMissingError" not in text
        assert "No recorded run passed" not in text
        assert f"Run {entry.run_id} is queued" in text


def test_refresh_never_repeats_a_run(operator: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    spawned: list[str] = []

    def spawn(run_id: str, _runs: Path) -> int:
        spawned.append(run_id)
        return 1

    monkeypatch.setattr(live, "spawn", spawn)
    app = open_view("workspace")
    button = next(b for b in app.button if b.label == "Run investigation")
    app = button.click().run()
    assert not app.exception and len(spawned) == 1
    app = app.run()
    open_view("workspace", spawned[0])
    assert len(spawned) == 1 and len(Board(operator / BOARD_FILE).recent()) == 1
    assert app.query_params["run"] == spawned[0]


def test_an_active_run_disables_the_button_in_another_session(operator: Path) -> None:
    Board(operator / BOARD_FILE).submit(SPEC, "k")
    app = open_view("workspace")
    assert next(b for b in app.button if b.label == "Run investigation").disabled


def test_replay_mode_never_opens_the_board(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("EARTHLAB_UI_MODE", raising=False)
    monkeypatch.setenv("EARTHLAB_METRICS_PORT", "0")
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)
    for view in SURFACES:
        app = open_view(view, "replay/live-october-abstained")
        assert not app.exception
        assert "trace status abstained" in shown(app)
    assert not (tmp_path / BOARD_FILE).exists()


def test_a_tampered_operator_run_shows_no_state(operator: Path) -> None:
    _, run_id = saved_run(operator, "live-september-verified")
    with (operator / run_id / "trace.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"tampered": true}\n')
    text = shown(open_view("control", run_id))
    assert "Run state not shown" in text and "trace status verified" not in text


def pending_request(runs: Path) -> None:
    desk = ResourceDesk(runs)
    desk.open(
        ResourceRequestV1(
            request_id="req-1",
            parent_task_id="lead.data",
            purpose="Compare the gate with a second table.",
            asset="mock table",
            url="http://127.0.0.1:9/a.csv",
            max_bytes=4096,
            content_types=("text/csv",),
            license_terms="mock terms",
            credential_name="MOCK_API_TOKEN",
            expires_utc=datetime.now(UTC) + timedelta(days=1),
            scientific_need="A second table lets the Lead check the gate.",
            risk="Low.",
        )
    )
    desk.review("req-1", "geospatial_engineer", "m", True, "needed")
    desk.review("req-1", "product_manager", "m", True, "in scope")


def test_a_pending_request_needs_the_operator_key(
    operator: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, "test-operator-key")
    pending_request(operator)
    app = open_view("control", "replay/live-october-abstained")
    assert "credential_required: MOCK_API_TOKEN" in shown(app)
    assert next(b for b in app.button if b.label == "Approve").disabled
    next(t for t in app.text_input if t.label == "Operator key").set_value("wrong").run()
    next(b for b in app.button if b.label == "Deny").click().run()
    assert any("operator key is not valid" in e.value for e in app.error)
    assert ResourceDesk(operator).view("req-1").status == "pm_endorsed"
    next(t for t in app.text_input if t.label == "Operator key").set_value(
        "test-operator-key"
    ).run()
    next(b for b in app.button if b.label == "Deny").click().run()
    assert ResourceDesk(operator).view("req-1").status == "denied"


def test_without_an_operator_key_no_decision_control_is_shown(
    operator: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv(OPERATOR_KEY_ENV, raising=False)
    pending_request(operator)
    app = open_view("control", "replay/live-october-abstained")
    assert "No operator key is set" in shown(app)
    assert not [b for b in app.button if b.label in ("Approve", "Deny")]


def experiment_run(runs: Path) -> tuple[str, Path]:
    board = Board(runs / BOARD_FILE)
    entry, _ = board.submit(SPEC, "e1")
    run_dir = runs / entry.run_id
    trace = RunTrace(run_dir / "trace.jsonl")
    trace.append("experiment_start", "runtime", task_id="e1.pm", arm="multi_agent")
    trace.append("finish", "runtime", status="awaiting_human", reason="ready", workflow=True)
    board.claim(entry.run_id, 1)
    board.end(entry.run_id, "finished")
    record = {
        "status": "awaiting_human",
        "reason": "ready",
        "arm": "multi_agent",
        "evidence_label": ARM_LABEL,
        "limitations": LIMITATIONS,
        "recommendation": {"outcome": "adopt_candidate", "model_id": "candidate-1"},
        "comparison": [{"model": "candidate-1", "mae": 4.5, "skill": 0.15}],
        "acceptance": {"neural_model_trained": True},
        "roles": {},
        "usage": {"model_calls": 1},
    }
    (run_dir / "result.json").write_text(json.dumps(record), encoding="utf-8")
    return entry.run_id, run_dir


def test_the_lab_labels_an_experiment_as_a_historical_evaluation(operator: Path) -> None:
    run_id, _ = experiment_run(operator)
    text = shown(open_view("lab", run_id))
    assert "Issue-time replay with modelled availability" in text
    assert "Not a forecast of any future date" in text and "not PSI or AQI" in text
    assert "The test period is not evaluated" in text


def test_a_human_decision_needs_the_key_and_binds_the_record(
    operator: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, "test-operator-key")
    _, run_dir = experiment_run(operator)
    with pytest.raises(PermissionError):
        experiments.decide(run_dir, True, "wrong")
    assert not (run_dir / experiments.DECISION_FILE).exists()
    signed = experiments.decide(run_dir, True, "test-operator-key")
    assert signed.request_sha256 == file_digest(run_dir / "result.json")
    with pytest.raises(FileExistsError):
        experiments.decide(run_dir, False, "test-operator-key")


def test_a_plain_run_shows_no_experiment_panel(operator: Path) -> None:
    _, run_id = saved_run(operator, "live-september-verified")
    assert "Experiment E1" not in shown(open_view("lab", run_id))

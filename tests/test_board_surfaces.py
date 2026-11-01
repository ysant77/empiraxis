"""Every surface shows the same run from the shared index, in any session, on any refresh."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from earthlab.board.store import BOARD_FILE, Board, RunSpec
from earthlab.ui import common, live

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

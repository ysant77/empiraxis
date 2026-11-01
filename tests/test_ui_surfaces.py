"""Three UI surfaces: honest status, offline replay, fail-closed traces, no leaks, phone layout."""

from __future__ import annotations

import json
import shutil
import socket
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from earthlab.events.contract import IMPLEMENTED_ROLES, PLANNED_ROLES
from earthlab.trace import RunTrace
from earthlab.ui import common
from earthlab.ui.control_room import recorded_approvals, role_kind
from earthlab.ui.engineering_lab import evidence_rows

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "src" / "earthlab" / "ui" / "app.py"
REPLAY = ROOT / "examples" / "replay"
HEADERS = {
    "workspace": "EarthLab Research Workspace",
    "control": "Axiom Control Room",
    "lab": "Geospatial Engineering Lab",
}
STATUS_WORDS = ("Status: implemented", "Status: planned", "Status: experimental")


@pytest.fixture
def offline(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replay mode, repo root as cwd, and every network connection refused."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("network disabled in replay tests")

    monkeypatch.setenv("EARTHLAB_METRICS_PORT", "0")
    monkeypatch.delenv("EARTHLAB_UI_MODE", raising=False)
    monkeypatch.chdir(ROOT)
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)


def open_view(view: str, **state: Any) -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.query_params["view"] = view
    for key, value in state.items():
        app.session_state[key] = value
    return app.run()


def page_text(app: AppTest) -> str:
    parts = [
        str(e.value)
        for kind in ("markdown", "caption", "header", "info", "error")
        for e in getattr(app, kind)
    ]
    parts += [e.value.to_string() for e in app.dataframe]
    parts += [str(e.value) for e in app.table]
    return "\n".join(parts)


@pytest.mark.parametrize("view", list(HEADERS))
def test_each_route_renders_with_status_text(offline: None, view: str) -> None:
    app = open_view(view)
    assert not app.exception
    assert app.title[0].value == "Axiom EarthLab"
    assert app.header[0].value == HEADERS[view]
    captions = [c.value for c in app.caption]
    assert any(word in c for c in captions for word in STATUS_WORDS)
    assert any("read-only replay" in c for c in captions)


def test_sample_recorded_run_loads_offline(offline: None) -> None:
    app = open_view("control")
    assert not app.exception and not app.error
    timeline = app.dataframe[0].value
    assert len(timeline) == 15
    assert "Round 1: A1.1 supported" in timeline.to_string()
    assert any("real Muse Glimmer run; redacted copy" in c.value for c in app.caption)


def test_tampered_trace_is_not_displayed(
    offline: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "replay"
    shutil.copytree(REPLAY, root)
    trace = root / "sb05-september" / "trace.jsonl"
    trace.write_text(trace.read_text().replace("2015-09", "2015-08", 1))
    monkeypatch.setattr(common, "REPLAY_DIR", root)
    app = open_view("control")
    assert not app.exception
    assert "Integrity check failed" in app.error[0].value
    assert "Round 1" not in page_text(app)


def test_unknown_role_in_a_listed_run_is_not_displayed(
    offline: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "replay"
    shutil.copytree(REPLAY, root)
    RunTrace(root / "sb05-september" / "trace.jsonl").append("message", "product_manager")
    monkeypatch.setattr(common, "REPLAY_DIR", root)
    app = open_view("control")
    assert "Integrity check failed" in app.error[0].value  # the manifest digest no longer matches


def test_no_sealed_content_or_keys_in_public_views(offline: None) -> None:
    for view in HEADERS:
        text = page_text(open_view(view))
        for marker in ("HO-", "sk-", "api_key", "<think>"):
            assert marker not in text, (view, marker)
    lab = page_text(open_view("lab"))
    assert "running, results not yet archived" not in lab
    assert "archived; measured at an older code revision" in lab
    assert "Typed plan critic is in a separate branch" not in lab
    assert "development, visible questions" in lab


def test_control_room_shows_no_planned_role_as_an_actor(offline: None) -> None:
    app = open_view("control")
    actors = set(app.dataframe[0].value["actor"])
    assert actors <= IMPLEMENTED_ROLES and not actors & PLANNED_ROLES
    kinds = dict(
        zip(app.dataframe[0].value["actor"], app.dataframe[0].value["actor kind"], strict=True)
    )
    assert kinds["tool"] == "code" and kinds["verifier"] == "code"
    assert kinds["orchestrator"] == "model agent"
    consoles = [b for b in app.button if b.label.startswith("Open ")]
    assert len(consoles) == len(PLANNED_ROLES) and all(b.disabled for b in consoles)


def test_role_kind_never_calls_code_an_agent() -> None:
    assert role_kind("tool") == "code" and role_kind("verifier") == "code"
    assert role_kind("safety_gate") == "code" and role_kind("human_director") == "human"
    assert role_kind("product_manager") == "model agent"
    assert role_kind("implementor") == "planned role, not running"
    assert role_kind("scientific_critic") == "code"


def test_replay_has_no_live_or_unapproved_interactive_controls(offline: None) -> None:
    app = open_view("workspace")
    assert not any(s.label == "Meta model endpoint" for s in app.selectbox)
    run = next(b for b in app.button if b.label == "Run investigation")
    assert run.disabled
    for label in ("Send to assistant", "Submit challenge"):
        assert next(b for b in app.button if b.label == label).disabled
    control = open_view("control")
    assert next(b for b in control.button if b.label == "Approve pending action").disabled


def test_phone_layout_stacks_every_panel(offline: None) -> None:
    for view in HEADERS:
        wide = open_view(view)
        narrow = open_view(view, compact=True)
        assert len(wide.columns) > 0 and len(narrow.columns) == 0
        assert not narrow.exception


def test_maps_carry_source_and_unit_labels(offline: None) -> None:
    app = open_view("workspace")
    captions = [c.value for c in app.caption]
    assert any("MCD64A1" in c and "hectares (ha)" in c and "longitude" in c for c in captions)
    assert any("ug/m3" in c and "reporting regions" in c for c in captions)


def test_recorded_run_tab_replays_both_months(offline: None) -> None:
    app = open_view("workspace")
    picker = next(s for s in app.selectbox if s.label == "Recorded run")
    assert picker.options[:2] == ["replay/sb05-september", "replay/sb05b-october"]
    assert picker.options[2:] == ["replay/live-september-verified", "replay/live-october-abstained"]
    assert any(s.value == "Trace hash chain intact (13 records)." for s in app.success)
    picker.set_value("replay/sb05b-october").run()
    assert any("insufficient_valid_data" in w.value for w in app.warning)


def test_missing_replay_folder_shows_unavailable(
    offline: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(common, "REPLAY_DIR", tmp_path / "absent")
    app = open_view("control")
    assert not app.exception
    assert any("Status: unavailable" in c.value for c in app.caption)
    assert any("No recorded runs are available." in i.value for i in open_view("workspace").info)


def test_recorded_approvals_report_their_expiry(tmp_path: Path) -> None:
    (tmp_path / "a.yaml").write_text(
        "approvals:\n"
        "  - {approval_id: x, action: download, approved: true, approver: owner,\n"
        "     decided_at_utc: '2026-01-01T00:00:00Z', expires_at_utc: '2026-01-02T00:00:00Z'}\n"
    )
    assert recorded_approvals(tmp_path)[0]["state"] == "expired"


def _shows_recomputed(result: dict[str, object]) -> None:
    from earthlab.ui.workspace_tabs import _show_recomputed

    _show_recomputed(result)


def test_workspace_shows_verified_values_and_the_manager_report(offline: None) -> None:
    result = {
        "findings_text": "A1.1: mapped burned area",
        "workflow": {"manager_result": {"report_text": "Verified.", "report_source": "pm_model"}},
    }
    app = AppTest.from_function(_shows_recomputed, args=(result,)).run()
    assert not app.exception
    assert [t.value for t in app.text] == ["A1.1: mapped burned area"]
    assert "Verified." in [m.value for m in app.markdown]
    empty = AppTest.from_function(_shows_recomputed, args=({},)).run()
    assert not empty.exception and not empty.text


def test_every_surface_shows_the_run_chosen_on_another(offline: None) -> None:
    for view in ("workspace", "control", "lab"):
        app = AppTest.from_file(str(APP), default_timeout=120)
        app.query_params["view"] = view
        app.session_state[common.SHARED_RUN] = "replay/sb05b-october"
        done = app.run()
        assert not done.exception
        picker = next(s for s in done.selectbox if s.label == "Recorded run")
        assert picker.value == "replay/sb05b-october"


def test_a_tampered_local_run_is_not_shown(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    shutil.copytree(REPLAY / "sb05-september", run_dir)
    with (run_dir / "trace.jsonl").open("a", encoding="utf-8") as handle:
        handle.write('{"tampered": true}\n')
    assert common.open_run("local", run_dir)[1] is None


def test_lab_rows_come_from_the_saved_record() -> None:
    result = json.loads((REPLAY / "sb05-september" / "result.json").read_text(encoding="utf-8"))
    rows = evidence_rows(result)
    assert any(r["check"] == "area claim 2015-09" and r["source"] == "verifier" for r in rows)
    assert all(r["source"] in ("code", "verifier") for r in rows)


def _show_stopped_run(run_dir: str) -> None:
    from pathlib import Path

    from earthlab.ui.workspace_tabs import show_result

    show_result(Path(run_dir))


def test_a_workflow_that_stopped_early_still_renders(tmp_path: Path, offline: None) -> None:
    report = {"report_text": "Fixed text.", "report_source": "rendered"}
    result = {"status": "out_of_scope", "workflow": {"manager_result": report}}
    (tmp_path / "result.json").write_text(json.dumps(result), encoding="utf-8")
    app = AppTest.from_function(_show_stopped_run, args=(str(tmp_path),)).run()
    assert not app.exception
    assert "Fixed text." in [m.value for m in app.markdown]

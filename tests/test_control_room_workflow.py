"""The Control Room workflow panel, on a scripted run behind a real replay manifest."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

pytest.importorskip("streamlit")

from conftest import REPO_DATA
from fake_client import ScriptedClient
from streamlit.testing.v1 import AppTest
from test_ui_surfaces import APP, offline, page_text  # noqa: F401
from test_workflow_observability import ASSIGN, STEPS, run

from earthlab.events.manifest import write_manifest
from earthlab.runtime import Workspace, open_workspace
from earthlab.ui import common
from earthlab.ui.control_room import role_name, shown


@pytest.fixture(scope="module")
def workspace() -> Workspace:
    return open_workspace(REPO_DATA)


@pytest.fixture
def workflow_replay(workspace: Workspace, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> str:
    """A replay folder holding one scripted separate-topology run, behind a manifest."""
    root = tmp_path / "replay"
    name = "synthetic-separate"
    head, *rest = STEPS
    run(ScriptedClient([head, ASSIGN, *rest]), workspace, root / name, separate=True)
    for extra in (root / name).iterdir():
        if extra.suffix not in (".jsonl", ".json"):
            extra.unlink() if extra.is_file() else shutil.rmtree(extra)
    write_manifest(root, [{"run": name}], note="synthetic scripted-client test run")
    monkeypatch.setattr(common, "REPLAY_DIR", root)
    return name


@pytest.mark.usefixtures("offline")
def test_the_control_room_shows_a_labelled_synthetic_workflow(
    workflow_replay: str,
) -> None:
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.query_params["view"] = "control"
    app.session_state[common.SHARED_RUN] = f"replay/{workflow_replay}"
    done = app.run()
    assert not done.error
    warnings = " ".join(str(w.value) for w in done.warning)
    assert "Synthetic test run" in warnings and "not live multi-agent collaboration" in warnings
    text = page_text(done) + warnings
    assert "Workflow run" in text and "separate topology" in text
    assert "Model orchestrator (separate topology)" in text
    assert "Orchestrator decision" in text and "Plan review (deterministic critic)" in text
    for marker in ("<think>", "sk-", "api_key"):
        assert marker not in text


@pytest.mark.usefixtures("offline")
def test_the_original_replays_still_load_and_name_the_investigator() -> None:
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.query_params["view"] = "control"
    text = page_text(app.run())
    assert "Muse investigator (single agent)" in text
    assert "Workflow run" not in text and not app.error


def test_role_names_and_unknown_cells() -> None:
    assert role_name("orchestrator") == "Muse investigator (single agent)"
    assert role_name("orchestrator", "separate") == "Model orchestrator (separate topology)"
    assert role_name("orchestrator", "combined") == "Muse investigator (single agent)"
    assert shown([{"tokens": None, "calls": 0}]) == [{"tokens": "unknown", "calls": 0}]

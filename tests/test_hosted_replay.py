"""The hosted replay: it refuses operator settings and credentials, and no page can act."""

from __future__ import annotations

import os
import socket
import subprocess
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest

from earthlab.ui.hosted import refusals

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "deploy" / "streamlit_app.py"
RUNS = (
    "scenario-s1-regression", "scenario-s2-encoder-reuse", "scenario-s3-transport",
    "scenario-s4-resource-request", "scenario-muse-team-exceedance",
    "scenario-muse-team-regression",
)  # fmt: skip
ACTIONS = ("Run investigation", "Approve", "Deny", "Train", "Download")


@pytest.fixture
def sealed(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """No network, no child process, no operator setting, and a cwd outside the repository."""

    def refuse(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("blocked in the hosted replay test")

    for name in ("EARTHLAB_UI_MODE", "EARTHLAB_REPLAY_DIR"):
        monkeypatch.delenv(name, raising=False)
    for line in refusals(os.environ):  # credentials of the test machine, never of the host
        monkeypatch.delenv(line.split()[0])
    monkeypatch.setenv("EARTHLAB_METRICS_PORT", "0")
    monkeypatch.chdir(tmp_path)  # the entry finds the repository itself; the cwd is restored
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


@pytest.mark.parametrize(
    ("environ", "count"),
    [
        ({}, 0), ({"EARTHLAB_UI_MODE": "replay", "EARTHLAB_REPLAY_DIR": "examples/replay"}, 0),
        ({"EARTHLAB_UI_MODE": "operator"}, 1), ({"EARTHLAB_REPLAY_DIR": "/tmp/runs"}, 1),
        ({"FIREWORKS_API_KEY": "x"}, 1), ({"EARTHLAB_OPERATOR_KEY": "x"}, 1),
        ({"github_token": "x"}, 1), ({"PATH": "/usr/bin", "HOME": "/home/app"}, 0),
        ({"MAPBOX_API_KEY": ""}, 0),
    ],
)  # fmt: skip
def test_the_hosted_replay_refuses_operator_settings(environ: dict[str, str], count: int) -> None:
    found = refusals(environ)
    assert len(found) == count
    assert not any(value in " ".join(found) for value in environ.values() if value == "x")


def test_an_operator_environment_stops_the_app(
    sealed: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("EARTHLAB_UI_MODE", "operator")
    app = AppTest.from_file(str(ENTRY), default_timeout=120).run()
    assert app.error and "refuses to start" in app.error[0].value
    assert not app.title


@pytest.mark.parametrize("run", RUNS)
@pytest.mark.parametrize("view", ["workspace", "lab", "control"])
def test_every_hosted_page_is_a_replay_with_no_action(sealed: None, view: str, run: str) -> None:
    app = AppTest.from_file(str(ENTRY), default_timeout=120)
    app.query_params["view"] = view
    app.query_params["run"] = f"replay/{run}"
    app.run()
    assert not app.exception and not app.error
    assert any("Replay mode" in c.value for c in app.caption)
    labels = [b.label for b in app.button]
    assert not [label for label in labels if label.startswith(ACTIONS)]
    assert not [s for s in app.selectbox if s.label == "Meta model endpoint"]

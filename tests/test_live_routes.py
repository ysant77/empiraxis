"""A queued run uses the options of the command line on every route."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")

from earthlab.board import execute as runner
from earthlab.board.store import RunSpec
from earthlab.ui import live


def capture(monkeypatch: pytest.MonkeyPatch, client: object, guard: object) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def record(name: str) -> Any:
        def call(
            _question: str, _client: Any, _workspace: Any, run_dir: Path, **kwargs: Any
        ) -> None:
            seen.update(name=name, **kwargs)
            (run_dir / "result.json").write_text(json.dumps({"status": "verified"}))

        return call

    monkeypatch.setattr(runner, "load_providers", lambda _path: {})
    monkeypatch.setattr(runner, "build_client", lambda _config: client)
    monkeypatch.setattr(runner, "build_guard", lambda _configs, _name: guard)
    monkeypatch.setattr(runner, "investigate", record("direct"))
    monkeypatch.setattr(runner, "run_workflow", record("workflow"))
    monkeypatch.setattr(runner, "repo_assignment", lambda *a, **k: k["topology"])
    return seen


@pytest.mark.parametrize(
    ("route", "name", "orchestrated"),
    [
        ("Direct Muse investigator (baseline)", "direct", False),
        ("Muse PM, deterministic orchestrator, Muse engineer", "workflow", False),
        ("Muse PM, separate LLM orchestrator, Muse engineer", "workflow", True),
    ],
)
def test_each_route_reviews_the_plan_and_keeps_the_guard(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, route: str, name: str, orchestrated: bool
) -> None:
    client, guard = object(), object()
    seen = capture(monkeypatch, client, guard)
    monkeypatch.setattr(runner, "load_providers", lambda _path: _Configs())
    spec = RunSpec(
        question="q", topology=live.ROUTES[route], provider="p", guard="g", reasoning="low"
    )
    runner.execute(spec, tmp_path, object(), Path("p"), Path("d"))  # type: ignore[arg-type]
    assert seen["name"] == name and seen["guard"] is guard
    assert seen["options"].plan_review and seen["options"].render_fallback
    if name == "workflow":
        assert (seen["orchestrator_client"] is client) == orchestrated


class _Enabled:
    enabled = True


class _Configs(dict[str, _Enabled]):
    def __init__(self) -> None:
        super().__init__(p=_Enabled())

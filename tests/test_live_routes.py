"""The operator's live button runs every route with the options of the command line."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("streamlit")

from earthlab.ui import common, live


def capture(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> dict[str, Any]:
    seen: dict[str, Any] = {}

    def record(name: str) -> Any:
        def call(*args: Any, **kwargs: Any) -> None:
            seen.update(name=name, **kwargs)

        return call

    monkeypatch.setattr(common, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(common, "workspace", lambda: object())
    monkeypatch.setattr(common, "metrics", lambda: object())
    monkeypatch.setattr(live, "investigate", record("direct"))
    monkeypatch.setattr(live, "run_workflow", record("workflow"))
    monkeypatch.setattr(live, "repo_assignment", lambda *a, **k: k["topology"])
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
    seen = capture(monkeypatch, tmp_path)
    client, guard = object(), object()
    live._run("q", live.ROUTES[route], client, {}, guard, "low", None)  # type: ignore[arg-type]
    assert seen["name"] == name and seen["guard"] is guard
    assert seen["options"].plan_review and seen["options"].render_fallback
    if name == "workflow":
        assert (seen["orchestrator_client"] is client) == orchestrated

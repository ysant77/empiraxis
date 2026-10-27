from __future__ import annotations

import json

import pytest

from earthlab.data.nea_pm25 import Pm25Dataset
from earthlab.tools.pm25_tools import Pm25Toolset
from earthlab.tools.registry import ToolOutcome, ToolRegistry

WINDOW = {"start": "2015-09-01T00:00", "end": "2015-09-03T00:00"}


@pytest.fixture
def registry(small_dataset: Pm25Dataset) -> ToolRegistry:
    reg = ToolRegistry()
    Pm25Toolset(small_dataset).register(reg)
    return reg


def test_schemas_are_openai_function_tools(registry: ToolRegistry) -> None:
    schemas = registry.schemas()
    assert {s["function"]["name"] for s in schemas} == set(registry.names())
    assert all(s["type"] == "function" for s in schemas)
    assert "start" in schemas[0]["function"]["parameters"]["properties"]


@pytest.mark.parametrize(
    ("name", "extra", "key"),
    [
        ("inspect_coverage", {}, "regions"),
        ("summarize_regions", {"regions": ["west"]}, "summaries"),
        ("daily_peaks", {"region": "west"}, "daily_peaks"),
        ("rank_regions", {"statistic": "max"}, "ranking"),
        ("count_hours_above", {"region": "west", "threshold": 41}, "hours_above"),
    ],
)
def test_every_tool_executes_and_cites_source(
    registry: ToolRegistry, name: str, extra: dict[str, object], key: str
) -> None:
    result = registry.execute(name, json.dumps({**WINDOW, **extra}))
    assert result.outcome == ToolOutcome.EXECUTED, result.error
    assert result.data is not None and key in result.data
    assert len(result.data["source"]["sha256"]) == 64
    assert json.loads(result.for_model())["outcome"] == "executed"


def test_rejections_never_execute(registry: ToolRegistry) -> None:
    assert registry.execute("run_shell", "{}").outcome == ToolOutcome.REJECTED
    assert registry.execute("daily_peaks", "{not json").outcome == ToolOutcome.REJECTED
    bad_region = registry.execute("daily_peaks", json.dumps({**WINDOW, "region": "jurong"}))
    assert bad_region.outcome == ToolOutcome.REJECTED and "region" in (bad_region.error or "")
    too_long = {"start": "2015-01-01T00:00", "end": "2015-12-01T00:00"}
    assert registry.execute("inspect_coverage", json.dumps(too_long)).outcome == "rejected"
    extra = registry.execute("inspect_coverage", json.dumps({**WINDOW, "lat": 1.3}))
    assert extra.outcome == ToolOutcome.REJECTED
    assert registry.execute("inspect_coverage", "x" * 9000).error == "arguments too large"


def test_handler_value_error_is_a_failed_outcome() -> None:
    from pydantic import BaseModel

    from earthlab.tools.registry import ToolSpec

    class NoArgs(BaseModel):
        pass

    def boom(_: object) -> dict[str, object]:
        raise ValueError("bad input")

    reg = ToolRegistry()
    reg.register(ToolSpec("boom", "fails", NoArgs, boom))
    with pytest.raises(ValueError, match="already"):
        reg.register(ToolSpec("boom", "fails", NoArgs, boom))
    result = reg.execute("boom", "")
    assert result.outcome == ToolOutcome.FAILED and result.error == "bad input"

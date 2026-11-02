"""The closing check is exact, and the dev tickets are synthetic and balanced."""

from __future__ import annotations

from pathlib import Path

from earthlab.harness.closure import closes_cleanly, load_dev_tickets

FILE = Path(__file__).resolve().parents[1] / "config" / "benchmark" / "specialist_dev_tickets.yaml"


def test_only_the_tool_then_the_note_closes_cleanly() -> None:
    assert closes_cleanly(["prepare_data", "submit_note"], "prepare_data")
    bad_runs = [
        [], ["prepare_data"], ["submit_note"], ["prepare_data", "prepare_data"],
        ["prepare_data", "submit_note", "submit_note"], ["train_models", "submit_note"],
    ]  # fmt: skip
    assert not any(closes_cleanly(bad, "prepare_data") for bad in bad_runs)


def test_the_dev_tickets_are_twelve_and_name_one_tool_each() -> None:
    found = load_dev_tickets(FILE).tickets
    assert len(found) == 12 and len({t.ticket_id for t in found}) == 12
    assert {t.prompt_key for t in found} == {"data", "ml"}
    for t in found:
        assert t.ticket["allowed_tools"] == [t.tool] and t.ticket["owner"] == t.owner
    assert "pm25" not in FILE.read_text(encoding="utf-8").lower().replace("pm2.5", "")


def test_the_tuning_tool_uses_the_same_closing_check() -> None:
    import importlib.util

    path = FILE.parents[2] / "tools" / "prompt_optimizer" / "optimize.py"
    spec = importlib.util.spec_from_file_location("optimize_tool", path)
    assert spec is not None and spec.loader is not None
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    cases = [[], ["a"], ["a", "submit_note"], ["a", "a", "submit_note"], ["submit_note"]]
    assert all(tool.closes_cleanly(c, "a") == closes_cleanly(c, "a") for c in cases)
    assert tool.dry_run() == 0

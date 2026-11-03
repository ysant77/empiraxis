"""The recorded M4 council run loads through the event adapter and the M4 page names its seats."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("streamlit")
from test_ui_surfaces import offline, open_view, page_text  # noqa: F401

from earthlab.events.adapter import load_run
from earthlab.events.manifest import verified_run
from earthlab.ui import scenarios
from earthlab.ui.provenance import bindings, critic_note, participants

REPLAY = Path(__file__).resolve().parents[1] / "examples" / "replay"
RUN = "scenario-m4-heterogeneous-council"


def entries() -> list[dict[str, object]]:
    lines = (verified_run(REPLAY, RUN) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line) for line in lines]


def test_the_m4_replay_loads_through_the_event_adapter() -> None:
    run = load_run(verified_run(REPLAY, RUN))
    kinds = {e.event_type for e in run.events}
    assert run.closed and run.status == "awaiting_human"
    assert {"role_bound", "critique_recorded"} <= kinds
    actors = {e.actor_role for e in run.events}
    assert "qa_reviewer" in actors and "method_critic" not in actors
    council = [e for e in run.events if e.message_summary.startswith("Council formed")]
    assert council and "heterogeneous" in council[0].message_summary


def test_the_trace_names_two_checkpoints_that_each_made_model_calls() -> None:
    records = entries()
    bound = bindings(records)
    shas = {b["checkpoint_sha256"] for b in bound.values()}
    assert len(shas) >= 2
    result = json.loads((verified_run(REPLAY, RUN) / "result.json").read_text(encoding="utf-8"))
    served = {bound[r]["checkpoint_sha256"] for r, seat in result["roles"].items() if seat["calls"]}
    assert len(served) >= 2, "each checkpoint must have made at least one model call"
    assert result["council"]["heterogeneous"] is True


def test_the_m4_story_names_every_checkpoint_and_the_critic_source() -> None:
    story = scenarios.story("M4", verified_run(REPLAY, RUN))
    assert scenarios.key_of(f"replay/{story.run}") == "M4"
    text = " ".join([story.method, *story.evidence])
    assert "Muse Glimmer 30B" in text and "Llama 3.2 3B Instruct" in text
    assert "independent_model" in text
    assert "Qwen" not in text, "the page may name only checkpoints that the trace records"


def test_the_participants_table_has_checkpoint_columns_and_the_critic_note_is_independent() -> None:
    result = json.loads((verified_run(REPLAY, RUN) / "result.json").read_text(encoding="utf-8"))
    rows = participants(entries(), result)
    assert all({"Family", "Checkpoint", "SHA-256"} <= set(row) for row in rows)
    assert {row["Checkpoint"] for row in rows if row["Kind"].startswith("model")} >= {
        "Llama-3.2-3B-Instruct-Q4_K_M.gguf", "Muse-Glimmer-30B-KQuant-17GB-Q4_K_M.gguf",
    }  # fmt: skip
    assert "different checkpoint" in critic_note(result, entries())


def test_m3_is_not_shown_with_llama_or_qwen() -> None:
    m3 = verified_run(REPLAY, "scenario-muse-method-comparison")
    text = (m3 / "trace.jsonl").read_text(encoding="utf-8") + (m3 / "result.json").read_text()
    assert "llama" not in text.lower() and "qwen" not in text.lower()
    lines = [json.loads(x) for x in (m3 / "trace.jsonl").read_text().splitlines()]
    assert not bindings(lines) and "role_binding" not in {x["event"] for x in lines}


@pytest.mark.parametrize("key", ["M1", "M2", "M3"])
def test_older_team_runs_keep_the_muse_only_wording(key: str) -> None:
    from earthlab.ui.provenance import evidence_ladder

    run = verified_run(REPLAY, scenarios.run_of(key))
    lines = [json.loads(x) for x in (run / "trace.jsonl").read_text().splitlines()]
    entry = {"evidence_mode": "x", "planned": ""}
    row = next(
        r for r in evidence_ladder(run, entry, lines) if r["Kind"] == "Model-assisted decisions"
    )
    assert "Muse Glimmer calls" in row["In this scenario"]


def test_the_workspace_and_control_pages_show_the_checkpoints(
    offline: None,  # noqa: F811
) -> None:
    for view in ("workspace", "control"):
        app = open_view(view, f"replay/{RUN}")
        assert not app.exception, view
        text = page_text(app)
        assert "Llama-3.2-3B-Instruct-Q4_K_M.gguf" in text or "Llama 3.2 3B" in text, view
        assert "Muse Glimmer calls" not in text, view
        assert "same-model second pass" not in text, view

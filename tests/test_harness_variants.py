"""Prompt variants are data, the reminder is bounded, and per-role clients are honoured."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fake_client import FAKE_CONFIG, ScriptedClient, call, say
from pydantic import BaseModel
from test_harness_engine import (  # noqa: F401
    CHOICE,
    SOURCE,
    STRATEGY,
    trainer,
)

from earthlab.digest import payload_digest
from earthlab.efficiency.prompt_models import PromptSpec, ToolDecl
from earthlab.efficiency.prompt_review import review_prompts
from earthlab.harness.contracts import ResearchRequestV1
from earthlab.harness.engine import DATA_SYSTEM, DEFAULT_PROMPTS, run_harness
from earthlab.harness.regression import PM25_PROBLEM, RegressionAdapter
from earthlab.harness.seats import Seats, Stopped
from earthlab.harness.variants import PROMPT_KEYS, VariantFile, load_variants, resolve
from earthlab.trace import RunTrace

ROOT = Path(__file__).resolve().parents[1]
FILE = ROOT / "config" / "benchmark" / "prompt_variants.yaml"
TOOLS = {"data": "prepare_data", "ml": "train_models"}


def test_the_variant_file_loads_and_the_baseline_keeps_every_default() -> None:
    variants = load_variants(FILE)
    base = resolve(variants.get("baseline"), DEFAULT_PROMPTS)
    assert base.texts == DEFAULT_PROMPTS and not base.reminders
    assert set(base.digests()) == set(PROMPT_KEYS)


def test_a_variant_replaces_only_the_keys_it_names_and_digests_the_text() -> None:
    fixed = resolve(load_variants(FILE).get("note-close-v1"), DEFAULT_PROMPTS)
    assert fixed.system("data") != DATA_SYSTEM
    assert fixed.system("plan") == DEFAULT_PROMPTS["plan"]
    assert fixed.digests()["data"] == payload_digest(fixed.system("data"))


def test_bad_variant_files_are_refused() -> None:
    row = {"id": "x", "description": "A variant of ten or more characters."}
    base = {"id": "baseline", "description": "The engine default prompts."}
    with pytest.raises(ValueError, match="unknown prompt key"):
        VariantFile.model_validate(
            {"version": 1, "variants": (base, {**row, "texts": {"nope": "t"}})}
        )
    with pytest.raises(ValueError, match="include the baseline"):
        VariantFile.model_validate({"version": 1, "variants": (row,)})
    with pytest.raises(ValueError, match="holds no text"):
        VariantFile.model_validate({"version": 1, "variants": ({**base, "texts": {"data": "t"}},)})


def _rules(prompt_id: str, key: str, text: str) -> set[str]:
    spec = PromptSpec(
        prompt_id=prompt_id, role="geospatial_engineer", text=text,
        tools=(ToolDecl(name=TOOLS[key]), ToolDecl(name="submit_note")),
    )  # fmt: skip
    return {f.rule for f in review_prompts((spec,)).findings if f.severity != "info"}


def test_a_variant_text_adds_no_finding_rule_that_the_default_text_lacks() -> None:
    """R001 and R003 target the investigator prompts and flag the defaults too."""
    for variant in load_variants(FILE).variants:
        for key, text in variant.texts.items():
            assert _rules(variant.id, key, text) <= _rules("default", key, DEFAULT_PROMPTS[key])


def specialist_script() -> list[Any]:
    return [
        call("prepare_data"), say("The data is ready."), call("submit_note", note="Prepared."),
        call("train_models"), call("submit_note", note="Trained."),
    ]  # fmt: skip


def clients() -> tuple[ScriptedClient, ScriptedClient, ScriptedClient]:
    pm = ScriptedClient(
        [
            call("review_scope", in_scope=True, note="Within the problem."),
            call("forward_decision", forward_to_human=True, note="Within the criteria."),
        ],
        FAKE_CONFIG.model_copy(update={"name": "pm-fake"}),
    )
    lead = ScriptedClient(
        [
            STRATEGY,
            call("choose_method", **CHOICE),
            call("review_results", action="finish", reason="The report gives no reason."),
            call("recommend", outcome="abstain", model_id=None, reason="The evaluator shows this."),
        ],
        FAKE_CONFIG.model_copy(update={"name": "lead-fake"}),
    )
    worker = ScriptedClient(specialist_script(), FAKE_CONFIG.model_copy(update={"name": "sp-fake"}))
    return pm, lead, worker


def team_run(tmp_path: Path, variant_id: str) -> tuple[Any, ScriptedClient]:
    pm, lead, worker = clients()
    roles = {
        "product_manager": pm, "geospatial_engineer": lead,
        "data_specialist": worker, "ml_engineer": worker,
    }  # fmt: skip
    path = tmp_path / "run"
    done = run_harness(
        "team", ResearchRequestV1(request_id="r1", objective="Predict PM2.5."), PM25_PROBLEM,
        RegressionAdapter(path, SOURCE), path, lead, role_clients=roles,
        variant=load_variants(FILE).get(variant_id),
    )  # fmt: skip
    return done, worker


@pytest.mark.usefixtures("trainer")
def test_the_live_defect_is_reproduced_by_the_baseline(tmp_path: Path) -> None:
    done, _ = team_run(tmp_path, "baseline")
    assert done["status"] == "failed" and "stopped without submit_note" in done["reason"]
    assert done["prompt_variant"] == "baseline"


@pytest.mark.usefixtures("trainer")
def test_the_reminder_variant_completes_and_each_role_uses_its_own_client(
    tmp_path: Path,
) -> None:
    done, worker = team_run(tmp_path, "note-close-reminder-v1")
    assert done["status"] == "awaiting_human"
    served = {n: r["provider"] for n, r in done["roles"].items()}
    assert served == {
        "product_manager": "pm-fake", "geospatial_engineer": "lead-fake",
        "data_specialist": "sp-fake", "ml_engineer": "sp-fake",
    }  # fmt: skip
    first = worker.requests[0]["messages"]
    assert "Step 1: call prepare_data" in first[0]["content"]
    reminders = [m for r in worker.requests for m in r["messages"] if "submit_note now" in str(m)]
    assert reminders
    start = next(e for e in RunTrace(tmp_path / "run" / "trace.jsonl").records()
                 if e["event"] == "experiment_start")  # fmt: skip
    assert start["data"]["prompt_variant"] == "note-close-reminder-v1"
    assert start["data"]["prompt_digests"] == done["prompt_digests"]


def test_the_reminder_is_bounded_so_a_silent_model_still_stops(tmp_path: Path) -> None:
    class Note(BaseModel):
        note: str

    client = ScriptedClient([say("a"), say("b"), say("c")])
    seats = Seats("team", tmp_path, client, {})
    with pytest.raises(Stopped, match="stopped without submit_note"):
        seats.loop("r", "s", {}, 3, {}, "submit_note", Note, "Call submit_note now.")
    assert len(client.requests) == 2


def test_a_repeated_tool_call_returns_the_first_result_and_runs_the_adapter_once(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    stub = request.getfixturevalue("trainer")
    pm, lead, _ = clients()
    worker = ScriptedClient(
        [
            call("prepare_data"), call("prepare_data"), call("submit_note", note="Prepared."),
            call("train_models"), call("train_models"), call("submit_note", note="Trained."),
        ]
    )  # fmt: skip
    roles = {
        "product_manager": pm, "geospatial_engineer": lead,
        "data_specialist": worker, "ml_engineer": worker,
    }  # fmt: skip
    path = tmp_path / "run"
    done = run_harness(
        "team", ResearchRequestV1(request_id="r1", objective="Predict PM2.5."), PM25_PROBLEM,
        RegressionAdapter(path, SOURCE), path, lead, role_clients=roles,
    )  # fmt: skip
    assert done["status"] == "awaiting_human"
    results = [
        m["content"] for r in worker.requests for m in r["messages"] if m.get("role") == "tool"
    ]
    assert len(set(results)) == 2 and len(results) >= 2
    assert len(stub.jobs) == 1  # the ML tool ran once although the model called it twice

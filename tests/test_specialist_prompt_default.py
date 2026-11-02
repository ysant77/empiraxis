"""The promoted specialist prompt, and the failure it fixes.

The evidence is three paired runs in `docs/benchmark-matrix-results-2026-11-02.md`, section 4.
These tests pin the text to those runs. A scripted model cannot show that the text changes what
a real model does.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fake_client import ScriptedClient, call, say
from test_harness_engine import SOURCE, trainer  # noqa: F401
from test_harness_variants import FILE, clients

from earthlab.harness.contracts import ResearchRequestV1
from earthlab.harness.engine import DATA_SYSTEM, DEFAULT_PROMPTS, ML_SYSTEM, run_harness
from earthlab.harness.regression import PM25_PROBLEM, RegressionAdapter
from earthlab.harness.variants import PROMOTED, PROMOTED_ID, load_variants, resolve

CONFIRM_DIGESTS = {
    "data": "f5a5b9014b0ac1fc757ef573faa98463cb24e0ff5ca35ff30c0c7f7cf9902d08",
    "ml": "c7b1d356a50b3f6df0f9171e5318de07a06cbed1bbc3fa29287724a33427e1df",
}


def default_team_run(tmp_path: Path, worker: ScriptedClient) -> dict[str, Any]:
    pm, lead, _ = clients()
    roles = {
        "product_manager": pm, "geospatial_engineer": lead,
        "data_specialist": worker, "ml_engineer": worker,
    }  # fmt: skip
    return run_harness(
        "team", ResearchRequestV1(request_id="r1", objective="Predict PM2.5."), PM25_PROBLEM,
        RegressionAdapter(tmp_path, SOURCE), tmp_path, lead, role_clients=roles,
    )  # fmt: skip


def test_the_default_is_the_text_the_confirm_runs_used() -> None:
    digests = resolve(PROMOTED, DEFAULT_PROMPTS).digests()
    assert {k: digests[k] for k in CONFIRM_DIGESTS} == CONFIRM_DIGESTS


def test_the_default_matches_the_reviewed_variant_and_adds_no_reminder() -> None:
    reviewed = load_variants(FILE).get(PROMOTED_ID)
    assert PROMOTED.texts == reviewed.texts and not PROMOTED.reminders


def test_the_baseline_still_gives_the_round_one_text() -> None:
    base = resolve(load_variants(FILE).get("baseline"), DEFAULT_PROMPTS)
    assert base.system("data") == DATA_SYSTEM and base.system("ml") == ML_SYSTEM


@pytest.mark.usefixtures("trainer")
def test_a_default_run_records_the_promoted_prompt(tmp_path: Path) -> None:
    worker = ScriptedClient([
        call("prepare_data"), call("submit_note", note="Prepared."),
        call("train_models"), call("submit_note", note="Trained."),
    ])  # fmt: skip
    done = default_team_run(tmp_path, worker)
    assert done["status"] == "awaiting_human" and done["prompt_variant"] == PROMOTED_ID
    sent = [m for r in worker.requests for m in r["messages"]]
    assert "Step 1: call prepare_data" in sent[0]["content"]
    assert not [m for m in sent if "submit_note now" in str(m)]


@pytest.mark.usefixtures("trainer")
def test_a_specialist_that_never_closes_still_fails_with_no_outcome(tmp_path: Path) -> None:
    done = default_team_run(tmp_path, ScriptedClient([call("prepare_data"), say("Done.")]))
    assert done["status"] == "failed" and "stopped without submit_note" in done["reason"]
    assert done.get("recommendation") is None

from __future__ import annotations

import json
from pathlib import Path

from assess_fakes import ScriptedClient, lead_plan
from test_assess_pipeline import DATA, DISPO, LLAMA, ML, MUSE, PM, QWEN, _run

from earthlab.ui import assessment


def test_replay_helpers_read_a_recorded_run(tmp_path: Path) -> None:
    clients = {
        LLAMA: ScriptedClient(LLAMA, [DATA]),
        QWEN: ScriptedClient(QWEN, [ML]),
        MUSE: ScriptedClient(MUSE, [lead_plan(dispositions=DISPO), PM]),
    }
    folder = tmp_path / "run-h"
    folder.mkdir()
    out, _ = _run("H", clients, folder)
    (folder / "result.json").write_text(json.dumps(out))
    assert assessment.runs(tmp_path) == ["run-h"]
    result, records, integrity = assessment.load("run-h", tmp_path)
    assert integrity.startswith("hash chain verified")
    assert [r["role"] for r in assessment.roster(records)][:2] == [
        "Data Specialist",
        "ML Specialist",
    ]
    rows = assessment.finding_rows(result, "ml_engineer")
    assert rows[0]["code check"] == "backed"
    assert assessment.answers(result, "lead", "dispositions")[0]["answer"] == "accept"
    assert {r["role"] for r in assessment.usage(records)} >= {"Engineering Lead"}


def test_broken_chain_is_reported(tmp_path: Path) -> None:
    folder = tmp_path / "bad"
    folder.mkdir()
    (folder / "result.json").write_text("{}")
    (folder / "trace.jsonl").write_text('{"seq": 5}\n')
    assert assessment.load("bad", tmp_path)[2].startswith("hash chain broken")

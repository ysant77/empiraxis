"""Committed M4.1 council replays: each one verifies offline, without a model.

A replay is a copy of a recorded run folder (`trace.jsonl`, `result.json`). The test checks
the hash chain, the package hash against the committed package, the roles that ran, the human
gate and the absence of local paths.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from assess_fakes import ROOT

from earthlab.assess.contracts import EvidencePackageV1
from earthlab.digest import payload_digest
from earthlab.trace import RunTrace

REPLAY = ROOT / "examples" / "assess" / "replay"
PACKAGES = ROOT / "examples" / "assess" / "packages"
FOLDERS = sorted(p for p in REPLAY.iterdir() if p.is_dir()) if REPLAY.exists() else []


def test_replays_are_committed() -> None:
    assert FOLDERS, "no M4.1 replay is committed"


@pytest.mark.parametrize("folder", FOLDERS, ids=[f.name for f in FOLDERS])
def test_replay_verifies_offline(folder: Path) -> None:
    trace = RunTrace(folder / "trace.jsonl")
    entries = trace.verify()
    records = list(trace.records())
    result = json.loads((folder / "result.json").read_text())
    assert result["trace_entries"] == entries
    events = [r["event"] for r in records]
    assert events[-1] == "human_gate" and "council_executed" in events
    started = records[0]["data"]
    pkg = EvidencePackageV1.model_validate_json(
        (PACKAGES / f"{result['package_id']}.json").read_text()
    )
    assert started["package_sha256"] == payload_digest(pkg.model_dump(mode="json"))
    bound = {r["data"]["provider"] for r in records if r["event"] == "role_binding"}
    ran = {r["data"]["provider"] for r in records if r["event"] == "model_turn"}
    assert ran <= bound
    assert set(result["participation"]["executed_checkpoints"]) == ran
    for name in ("trace.jsonl", "result.json"):
        text = (folder / name).read_text()
        assert "/Users/" not in text and "/home/" not in text

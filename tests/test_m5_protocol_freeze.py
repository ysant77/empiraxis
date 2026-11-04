"""The frozen M5 protocol files must match their recorded SHA-256."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from earthlab.digest import file_digest

FREEZE = Path("docs/m5/protocol-v1.freeze.json")


def test_protocol_files_match_the_freeze_record() -> None:
    record = json.loads(FREEZE.read_text(encoding="utf-8"))
    assert record["protocol_id"] == "m5-protocol-1"
    for name, digest in record["sha256"].items():
        assert file_digest(Path(name)) == digest, f"{name} changed after the freeze"


def test_protocol_yaml_has_the_frozen_split() -> None:
    cfg = yaml.safe_load(Path("config/m5/protocol-v1.yaml").read_text(encoding="utf-8"))
    seasons = cfg["seasons"]
    assert cfg["horizon_hours"] == 6 and cfg["bootstrap"]["seed"] == 7
    assert seasons["heldout_season"] not in seasons["train_seasons"]
    assert set(seasons["train_seasons"]) | {seasons["heldout_season"]} <= set(range(2015, 2024))
    assert cfg["sealed"]["first_sealed_label"].startswith("2024")


def test_transport_and_event_protocols_match_the_freeze_record() -> None:
    record = json.loads(Path("docs/m5/protocol-bc.freeze.json").read_text(encoding="utf-8"))
    assert record["protocol_ids"] == ["m5-protocol-b-1", "m5-protocol-c-1"]
    for name, digest in record["sha256"].items():
        assert file_digest(Path(name)) == digest, f"{name} changed after the freeze"

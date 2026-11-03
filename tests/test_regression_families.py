"""The family scenario tunes the ridge on train folds, reloads it and records both in the trace."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
import pytest
from test_harness_engine import SOURCE

from earthlab.harness import regression_families as RF
from earthlab.harness.regression import RegressionAdapter
from earthlab.trace import RunTrace


class _Seats:
    def __init__(self, trace: RunTrace) -> None:
        self.trace = trace


def test_the_tuned_ridge_reloads_exactly_and_is_scored(tmp_path: Path) -> None:
    adapter = RF.family_adapter(tmp_path)
    tuned = adapter._tune(48)
    assert tuned["tuned_id"] == RF.TUNED
    assert tuned["reload_max_abs_difference"] == 0.0
    assert RF.TUNED in adapter.bench.results
    with np.load(tmp_path / f"weights-{RF.TUNED}.npz") as kept:
        assert float(kept["alpha"]) == tuned["alpha"]


def test_train_records_the_tuning_in_the_trace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(RegressionAdapter, "train", lambda self, plan, seats: {"models": "b"})
    monkeypatch.setattr(RF.FamilyAdapter, "_tune", lambda self, window: {"tuned_id": "t"})
    trace = RunTrace(tmp_path / "trace.jsonl")
    plan: Any = type("Plan", (), {"config": {"window_hours": 48}})()
    out = RF.FamilyAdapter(tmp_path, SOURCE).train(plan, _Seats(trace))  # type: ignore[arg-type]
    assert out["tuned"] == {"tuned_id": "t"}
    events = (tmp_path / "trace.jsonl").read_text(encoding="utf-8")
    assert '"tuning_verified"' in events and "inference_verified" not in events

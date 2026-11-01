"""Reproduce a saved run with no model: chain, artifact bytes and every recomputable score."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.cases.tools import CaseLibrary
from earthlab.digest import file_digest
from earthlab.forecast.evaluator import evaluate, read_truth
from earthlab.forecast.samples import PRIMARY_HORIZON
from earthlab.harness import eval_classify
from earthlab.harness.artifacts import MissingArtifact, verify_file
from earthlab.harness.classify import HORIZON, THRESHOLD
from earthlab.harness.raster import CASE, DETERMINISTIC
from earthlab.tools.burned_area_tools import month_report
from earthlab.trace import RunTrace

SOURCE = Path("data/nea/Historical1hrPM2.5.csv")
TOLERANCE = 5e-4


def _regression(run_dir: Path, rows: dict[str, dict[str, Any]]) -> list[str]:
    truth, _ = read_truth(SOURCE)
    wrong = []
    for name, row in rows.items():
        with np.load(run_dir / f"predictions-{name}.npz") as saved:
            again = evaluate(truth, saved["issues"], list(saved["horizons"]), saved["predictions"])
        value = again[str(PRIMARY_HORIZON)]["all"]["mae"]
        if abs(value - row["mae"]) > TOLERANCE + 0.005:
            wrong.append(f"{name}: MAE {value:.3f} against {row['mae']}")
    return wrong


def _classification(run_dir: Path, rows: dict[str, dict[str, Any]]) -> list[str]:
    truth, _ = read_truth(SOURCE)
    wrong = []
    for name, row in rows.items():
        with np.load(run_dir / f"probabilities-{name}.npz") as saved:
            y = eval_classify.labels(truth, saved["issues"], HORIZON, THRESHOLD)
            again = eval_classify.score(saved["probabilities"], float(saved["cut"]), y)
        if abs(float(again["f1"] or 0) - row["f1"]) > TOLERANCE:
            wrong.append(f"{name}: F1 {again['f1']} against {row['f1']}")
    return wrong


def _raster(rows: dict[str, dict[str, Any]]) -> list[str]:
    root = Path(".").resolve()
    case = CaseLibrary.load(root / "config" / "cases", root).get(CASE)
    wrong = []
    for name, row in rows.items():
        if not name.startswith(f"{DETERMINISTIC}:"):
            continue
        check = month_report(case, root, name.split(":")[1])["check"]
        value = float(check["verifier_valid_fraction"])
        if abs(value - row["valid_fraction"]) > TOLERANCE:
            wrong.append(f"{name}: valid fraction {value} against {row['valid_fraction']}")
    return wrong


def replay_run(run_dir: Path) -> dict[str, Any]:
    """Fails closed: a broken chain or a changed artifact raises, and a mismatch is listed."""
    trace = RunTrace(run_dir / "trace.jsonl")
    trace.verify()
    record = json.loads((run_dir / "result.json").read_text(encoding="utf-8"))
    for name, digest in record["artifacts"].items():
        verify_file(run_dir / "artifacts" / f"{name}.json", digest)
    rows = {row["model"]: row for row in record.get("comparison", [])}
    kind = record["kind"]
    if kind == "regression":
        wrong = _regression(run_dir, rows)
    elif kind == "classification":
        wrong = _classification(run_dir, rows)
    else:
        wrong = _raster(rows)
    return {
        "records": sum(1 for _ in trace.records()), "artifacts": len(record["artifacts"]),
        "models_rechecked": len(rows), "mismatches": wrong, "result_sha256": file_digest(
            run_dir / "result.json"
        ),
    }  # fmt: skip


__all__ = ["MissingArtifact", "replay_run"]

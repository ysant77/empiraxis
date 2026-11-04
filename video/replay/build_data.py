"""Bundle recorded release artifacts into data.js for the replay page. Reads only.

Usage:
  python video/replay/build_data.py --release DIR --firms DIR --ledger DIR --run DIR
    --release  a checkout of the repo at release 4e4a4f1 (replay trace and 2015 ablation)
    --firms    runs/haze-2015/firms (box-a, box-b, box-c manifests and CSVs)
    --ledger   the prediction ledger folder (predictions.jsonl, verifications.jsonl)
    --run      the M3 run folder 20261103T061204Z-829fed
The committed data.js was built from these inputs. Its SHA-256 prefix is printed.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import random
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
RESULT_KEYS = (
    "status", "strategy", "recommendation", "comparison", "usage", "limitations",
    "code_outcome", "roles", "acceptance",
)  # fmt: skip
NEA = {
    "north": [103.82, 1.41803],
    "south": [103.82, 1.29587],
    "west": [103.7, 1.35735],
    "east": [103.94, 1.35735],
    "central": [103.82, 1.35735],
}


def jsonl(path: Path) -> list[Any]:
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


def keep(r: dict[str, Any]) -> dict[str, Any]:
    return {
        "seq": r["seq"],
        "ts": r["ts"],
        "actor": r["actor"],
        "event": r["event"],
        "hash": r["hash"][:12],
        "data": r["data"],
    }


def fires(root: Path) -> tuple[list[list[Any]], list[dict[str, Any]], int]:
    """A fixed random sample of 9,000 detections per study box, and the full count."""
    points, boxes, total = [], [], 0
    for b in ("box-a", "box-b", "box-c"):
        m = json.loads((root / b / f"firms-modis-sp-haze-2015-{b}.manifest.json").read_text())
        boxes.append({"id": b} | {k: m[k] for k in ("extent", "product", "provider")})
        with open(root / b / "firms_modis_sp_2015_08_2015_11.csv") as f:
            rows = list(csv.DictReader(f))
        total += len(rows)
        random.Random(7).shuffle(rows)  # noqa: S311 - a fixed display sample, not security
        points += [
            [round(float(r["longitude"]), 3), round(float(r["latitude"]), 3), r["acq_date"]]
            for r in rows[:9000]
        ]
    return points, boxes, total


def training(run: Path, usage: Any) -> dict[str, Any]:
    ro = json.loads((run / "rolling-origin-ridge.json").read_text())
    job = json.loads((run / "train-candidate-1/job.json").read_text())
    return {
        "folds": ro["folds"],
        "fold_mae": ro["fold_mae"],
        "persistence_fold_mae": ro["persistence_fold_mae"],
        "trials": [[t["config"]["alpha"], t["validation_score"]] for t in ro["search"]["trials"]],
        "tcn": json.loads((run / "train-candidate-1/training.json").read_text()),
        "job": {k: v for k, v in job.items() if k != "data"},
        "verify": json.loads((run / "train-candidate-1/verify.json").read_text()),
        "usage": usage,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    for flag in ("--release", "--firms", "--ledger", "--run"):
        ap.add_argument(flag, type=Path, required=True)
    a = ap.parse_args()
    replay = a.release / "examples/replay/scenario-muse-method-comparison"
    trace = jsonl(replay / "trace.jsonl")
    result = json.loads((replay / "result.json").read_text())
    points, boxes, total = fires(a.firms)
    data = {
        "release": "4e4a4f1",
        "run": a.run.name,
        "trace": [keep(r) for r in trace],
        "trace_head": trace[-1]["hash"],
        "result": {k: result[k] for k in RESULT_KEYS},
        "firms": points,
        "firms_total": total,
        "boxes": boxes,
        "nea": NEA,
        "haze": json.loads((HERE / "inputs/haze.json").read_text()),
        "acq": json.loads((HERE / "inputs/acq.json").read_text()),
        "ledger": jsonl(a.ledger / "predictions.jsonl"),
        "verifications": jsonl(a.ledger / "verifications.jsonl"),
        "train": training(a.run, result["usage"]),
        "ablation": json.loads((a.release / "docs/evidence/haze-2015-ablation.json").read_text()),
    }
    out = "window.DATA = " + json.dumps(data, separators=(",", ":")) + ";\n"
    (HERE / "data.js").write_text(out)
    sha = hashlib.sha256(out.encode()).hexdigest()[:12]
    print("firms total", total, "sampled", len(points), "bytes", len(out), "sha", sha)


if __name__ == "__main__":
    main()

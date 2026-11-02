"""Batch inference from a registry and a bundle digest. It writes one JSON line per issue."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.digest import file_digest
from earthlab.efficiency.artifacts import ArtifactRef, MissingArtifactError
from earthlab.mlops.registry import Registry
from earthlab.mlops.serve import InputRefused, load, predict_batch


def read_input(path: Path) -> tuple[tuple[str, ...], list[datetime], np.ndarray]:
    """A CSV with a time column, then one column per input. A blank cell is a missing value."""
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream)
        header = next(reader)
        rows = list(reader)
    stamps = [datetime.fromisoformat(r[0]) for r in rows]
    values = np.array([[float(c) if c.strip() else np.nan for c in r[1:]] for r in rows])
    return tuple(header[1:]), stamps, values


def _grid(stamps: list[datetime], cadence_hours: int) -> None:
    step = timedelta(hours=cadence_hours)
    if len(stamps) < 2 or any(b - a != step for a, b in pairwise(stamps)):
        raise InputRefused(f"the input times are not a regular {cadence_hours} h grid")


def issue_positions(rows: int, lags: int, offset: int, first: int | None) -> np.ndarray:
    """Row positions to issue at, up to the step after the last row, if the lags fit."""
    earliest = max(first if first is not None else 0, offset + lags - 1)
    return np.arange(earliest, rows + offset, dtype=np.int64)


def cmd_mlops_predict(args: argparse.Namespace) -> int:
    registry = Registry(args.registry)
    try:
        ref = ArtifactRef(kind="record", sha256=args.bundle)
        _, fitted = load(registry, ref)
        config = fitted.config
        columns, stamps, values = read_input(args.input)
        _grid(stamps, config.cadence_hours)
        offset = config.availability_offset_hours // config.cadence_hours
        issues = issue_positions(len(values), config.lags, offset, args.first_issue)
        when = [stamps[0] + timedelta(hours=config.cadence_hours * int(i)) for i in issues]
        out = predict_batch(
            registry, ref, values, columns, file_digest(args.input), issues, when,
            args.allow_research,
        )  # fmt: skip
    except (ValueError, MissingArtifactError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    with args.output.open("w", encoding="utf-8") as sink:
        for row in out:
            sink.write(json.dumps(row.model_dump(mode="json"), sort_keys=True) + "\n")
    print(f"wrote {len(out)} predictions to {args.output} ({out[0].readiness})")
    return 0


def cmd_mlops_run(args: argparse.Namespace) -> int:
    """Registered methods on the NEA series, scored by the existing evaluators."""
    from earthlab.forecast.pipeline import SOURCE
    from earthlab.harness import families_run as runs

    spec = runs.RunSpec(lags=args.lags)
    run = runs.run_regression if args.scenario == "regression" else runs.run_classification
    print(json.dumps(run(args.out, args.registry, args.source or SOURCE, spec), indent=2))
    return 0


def cmd_mlops_verify(args: argparse.Namespace) -> int:
    """A read-only check of one saved bundle. Exit 2 means refused."""
    from earthlab.harness.verify import verify_bundle

    ref = ArtifactRef(kind="record", sha256=args.bundle)
    done = verify_bundle(Registry(args.registry), ref, args.run, args.source)
    text = done.model_dump_json(indent=2)
    if args.output is not None:
        args.output.write_text(text, encoding="utf-8")
    print(text)
    return 2 if done.outcome == "refused" else 0


def cmd_mlops_accept(args: argparse.Namespace) -> int:
    """Verify, run the batch command, and write the readiness report. Exit 2 means refused."""
    from earthlab.harness.accept import accept

    done = accept(args.registry, args.bundle, args.run, args.source, args.out)
    print(done.model_dump_json(indent=2))
    return 2 if done.verification_outcome == "refused" else 0


def cmd_method_claims(args: argparse.Namespace) -> int:
    """The six claims for one row of a saved evaluator report."""
    from earthlab.harness.claims import ladder
    from earthlab.harness.contracts import EvaluationReportV1

    report = EvaluationReportV1.model_validate_json(args.report.read_bytes())
    print(ladder(report, args.model, args.status).model_dump_json(indent=2))
    return 0


def _bundle_args(parser: Any) -> None:
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--bundle", required=True, help="the bundle's SHA-256 digest")
    parser.add_argument("--run", type=Path, required=True, help="the families run folder")
    parser.add_argument("--source", type=Path, required=True, help="the NEA CSV")


def add_mlops_parsers(sub: Any) -> None:
    train = sub.add_parser("mlops-run", help="experimental: registered methods on real NEA data")
    train.add_argument("scenario", choices=["regression", "classification"])
    train.add_argument("--out", type=Path, required=True, help="folder for run artifacts")
    train.add_argument("--registry", type=Path, required=True, help="registry folder")
    train.add_argument("--source", type=Path, default=None, help="the NEA CSV")
    train.add_argument("--lags", type=int, default=12)
    train.set_defaults(func=cmd_mlops_run)
    run = sub.add_parser("mlops-predict", help="batch inference from a registered model bundle")
    run.add_argument("--registry", type=Path, required=True)
    run.add_argument("--bundle", required=True, help="the bundle's SHA-256 digest")
    run.add_argument("--input", type=Path, required=True, help="CSV: time, then each column")
    run.add_argument("--output", type=Path, required=True, help="JSONL, one line per issue")
    run.add_argument("--first-issue", type=int, default=None, help="first row position to issue")
    run.add_argument(
        "--allow-research", action="store_true", help="also serve a candidate or evaluated bundle"
    )
    run.set_defaults(func=cmd_mlops_predict)
    check = sub.add_parser("mlops-verify", help="offline integrity check of one model bundle")
    _bundle_args(check)
    check.add_argument("--output", type=Path, default=None, help="also write the JSON here")
    check.set_defaults(func=cmd_mlops_verify)
    claims = sub.add_parser("method-claims", help="the six claims for one saved report row")
    claims.add_argument("--report", type=Path, required=True, help="an evaluation report")
    claims.add_argument("--model", required=True, help="the row name in the report")
    claims.add_argument("--status", default=None, help="the registry status, if there is one")
    claims.set_defaults(func=cmd_method_claims)
    done = sub.add_parser("mlops-accept", help="verify, run batch inference, report readiness")
    _bundle_args(done)
    done.add_argument("--out", type=Path, required=True, help="folder for the evidence")
    done.set_defaults(func=cmd_mlops_accept)

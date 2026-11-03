"""Score the experimental ledger's predictions against published NEA PM2.5.

Needs no operator key. For each target date in Singapore time, it captures that day's published
values into the append-only log, then appends one verification per due prediction. A
prediction is never changed.
"""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

from earthlab.acquire.nea_live import CaptureLog, Observation, capture
from earthlab.forecast.ledger import Ledger, PredictionV1, summary

SGT = timezone(timedelta(hours=8))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    parser.add_argument("log", type=Path, help="the NEA capture log, outside the repository")
    args = parser.parse_args()
    ledger, log = Ledger(args.ledger.expanduser()), CaptureLog(args.log.expanduser())
    lines = ledger.predictions.read_text(encoding="utf-8").splitlines()
    days = sorted({PredictionV1.model_validate_json(x).target_time.astimezone(SGT).date()
                   for x in lines})  # fmt: skip
    for day in days:
        print(day, json.dumps(capture(log, ("pm25",), day=day)))
    rows = [Observation.model_validate_json(x) for x in log.path.read_text().splitlines()]
    for v in ledger.verify(rows, datetime.now(UTC)):
        print(v.prediction_id, v.state, v.observed, v.absolute_error)
    print(json.dumps(summary(ledger)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

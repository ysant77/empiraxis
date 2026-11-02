"""One small capture of the five NEA real-time products into an append-only log.

The log must be outside the repository: captured values are run data, not source.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from earthlab.acquire.nea_live import CaptureLog, capture

REPO = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log", type=Path, help="JSONL log outside the repository")
    args = parser.parse_args()
    log_path = args.log.expanduser().resolve()
    if log_path.is_relative_to(REPO):
        raise SystemExit("the capture log must be outside the repository")
    print(json.dumps(capture(CaptureLog(log_path)), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

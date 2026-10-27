"""Append-only, hash-chained run trace stored as JSON lines.

Each record carries the hash of the previous record, so any edit, deletion or
reordering is detected by :meth:`RunTrace.verify`.
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from earthlab.hashing import content_hash

GENESIS = "0" * 64


class TraceTamperError(RuntimeError):
    pass


class RunTrace:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._seq = 0
        self._last = GENESIS
        for record in self.records():
            self._seq = record["seq"] + 1
            self._last = record["hash"]

    def records(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            return
        with self.path.open(encoding="utf-8") as fh:
            for line_no, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as exc:
                    raise TraceTamperError(f"corrupt trace line {line_no}") from exc

    def append(self, event: str, actor: str, **data: Any) -> dict[str, Any]:
        body = {
            "seq": self._seq,
            "ts": datetime.now(UTC).isoformat(),
            "event": event,
            "actor": actor,
            "data": json.loads(json.dumps(data, default=str)),
            "prev": self._last,
        }
        record = {**body, "hash": content_hash(body)}
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        self._seq += 1
        self._last = record["hash"]
        return record

    def verify(self) -> int:
        """Return the number of valid records; raise on the first broken link."""
        prev = GENESIS
        count = 0
        for count, record in enumerate(self.records(), start=1):
            claimed = record.pop("hash", None)
            if record.get("prev") != prev:
                raise TraceTamperError(f"broken chain at seq {record.get('seq')}")
            if record.get("seq") != count - 1:
                raise TraceTamperError(f"out-of-order sequence at record {count}")
            if content_hash(record) != claimed:
                raise TraceTamperError(f"hash mismatch at seq {record.get('seq')}")
            prev = claimed
        return count

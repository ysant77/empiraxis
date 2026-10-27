"""Run trace: an append-only JSON-lines log where each entry commits to the one before.

Entry ``n`` stores the digest of entry ``n - 1`` in ``prev`` and its own digest in
``hash``. Changing, dropping or reordering any line breaks the chain at that point.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from earthlab.digest import payload_digest

ROOT_DIGEST = "0" * 64
Listener = Callable[[dict[str, Any]], None]


class TraceIntegrityError(RuntimeError):
    """The trace file does not form an unbroken chain."""


def _read_entries(path: Path) -> Iterator[dict[str, Any]]:
    if not path.exists():
        return
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            raise TraceIntegrityError(f"line {number} is not valid JSON") from exc


def _check_entry(entry: dict[str, Any], position: int, parent: str) -> str:
    """Return the entry's digest if it links correctly to ``parent``."""
    stored = entry.get("hash")
    body = {key: value for key, value in entry.items() if key != "hash"}
    if body.get("seq") != position:
        raise TraceIntegrityError(f"entry {position} has sequence {body.get('seq')}")
    if body.get("prev") != parent:
        raise TraceIntegrityError(f"entry {position} does not link to the previous entry")
    if payload_digest(body) != stored:
        raise TraceIntegrityError(f"entry {position} content does not match its digest")
    return str(stored)


class RunTrace:
    def __init__(self, path: Path, listener: Listener | None = None):
        self.path = path
        self._listener = listener
        path.parent.mkdir(parents=True, exist_ok=True)
        self._next_seq, self._head = 0, ROOT_DIGEST
        for entry in _read_entries(path):
            self._next_seq, self._head = entry["seq"] + 1, entry["hash"]

    def records(self) -> Iterator[dict[str, Any]]:
        return _read_entries(self.path)

    def append(self, event: str, actor: str, **data: Any) -> dict[str, Any]:
        body = {
            "seq": self._next_seq,
            "ts": datetime.now(UTC).isoformat(),
            "event": event,
            "actor": actor,
            "data": json.loads(json.dumps(data, default=str)),
            "prev": self._head,
        }
        entry = {**body, "hash": payload_digest(body)}
        with self.path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(entry, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        self._next_seq, self._head = self._next_seq + 1, entry["hash"]
        if self._listener is not None:
            self._listener(entry)
        return entry

    def verify(self) -> int:
        """Walk the whole chain; return the entry count or raise on the first break."""
        parent, count = ROOT_DIGEST, 0
        for position, entry in enumerate(self.records()):
            parent = _check_entry(entry, position, parent)
            count = position + 1
        return count

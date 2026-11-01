"""The shared run index: which runs exist, and whether a worker is still alive.

SQLite with one writer at a time. The trace stays the audit source: this file holds no
stage, task or result, only what a trace cannot say about itself. A view submits a request
and reads rows; only the worker moves a run after that. One model serves one run, so a
second run waits for the first to end.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from earthlab.contracts import Strict
from earthlab.runtime import new_run_id
from earthlab.workflow.contracts import Topology

RunState = Literal["queued", "running", "finished", "failed", "interrupted"]
ACTIVE: tuple[RunState, ...] = ("queued", "running")
UNCLAIMED_SECONDS = 60.0
BOARD_FILE = "board.sqlite"
_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    request_key TEXT NOT NULL UNIQUE,
    spec TEXT NOT NULL,
    state TEXT NOT NULL,
    queued_at REAL NOT NULL,
    started_at REAL,
    beat_at REAL,
    ended_at REAL,
    pid INTEGER,
    note TEXT
);
"""


class RunSpec(Strict):
    """What a person asked to run. It holds names and text, never a credential."""

    question: str
    topology: Topology | None
    provider: str
    guard: str
    reasoning: str


@dataclass(frozen=True)
class RunEntry:
    run_id: str
    spec: RunSpec
    state: RunState
    queued_at: float
    started_at: float | None
    beat_at: float | None
    ended_at: float | None
    pid: int | None
    note: str | None

    @property
    def active(self) -> bool:
        return self.state in ACTIVE


class RunBusy(RuntimeError):
    """Another run is active. Nothing was queued."""

    def __init__(self, run_id: str):
        super().__init__(f"run {run_id} is active")
        self.run_id = run_id


def pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Board:
    def __init__(
        self,
        path: Path,
        clock: Callable[[], float] = time.time,
        alive: Callable[[int], bool] = pid_alive,
    ):
        self.path = path
        self._clock = clock
        self._alive = alive
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(_SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA journal_mode=WAL")
            yield db
        finally:
            db.close()

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        with self._connect() as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                yield db
            except BaseException:
                db.execute("ROLLBACK")
                raise
            db.execute("COMMIT")

    def _reap(self, db: sqlite3.Connection) -> None:
        now = self._clock()
        for row in db.execute("SELECT * FROM runs WHERE state IN ('queued', 'running')").fetchall():
            dead = row["pid"] is not None and not self._alive(row["pid"])
            lost = row["state"] == "queued" and now - row["queued_at"] > UNCLAIMED_SECONDS
            if dead or lost:
                note = "worker process ended without a finish" if dead else "no worker claimed it"
                db.execute(
                    "UPDATE runs SET state = 'interrupted', ended_at = ?, note = ? "
                    "WHERE run_id = ?",
                    (now, note, row["run_id"]),
                )

    def submit(self, spec: RunSpec, request_key: str) -> tuple[RunEntry, bool]:
        """Queue one run. The same key gets the same run back and starts nothing."""
        with self._write() as db:
            self._reap(db)
            found = db.execute(
                "SELECT * FROM runs WHERE request_key = ?", (request_key,)
            ).fetchone()
            if found is not None:
                return _entry(found), False
            busy = db.execute("SELECT run_id FROM runs WHERE state IN ('queued', 'running')")
            if (row := busy.fetchone()) is not None:
                raise RunBusy(row["run_id"])
            run_id = new_run_id()
            db.execute(
                "INSERT INTO runs (run_id, request_key, spec, state, queued_at) "
                "VALUES (?, ?, ?, 'queued', ?)",
                (run_id, request_key, spec.model_dump_json(), self._clock()),
            )
            row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
            return _entry(row), True

    def claim(self, run_id: str, pid: int) -> bool:
        """The worker takes a queued run. Only one claim can succeed."""
        now = self._clock()
        with self._write() as db:
            done = db.execute(
                "UPDATE runs SET state = 'running', pid = ?, started_at = ?, beat_at = ? "
                "WHERE run_id = ? AND state = 'queued'",
                (pid, now, now, run_id),
            )
            return done.rowcount == 1

    def beat(self, run_id: str) -> None:
        with self._write() as db:
            db.execute("UPDATE runs SET beat_at = ? WHERE run_id = ?", (self._clock(), run_id))

    def end(self, run_id: str, state: RunState, note: str | None = None) -> None:
        with self._write() as db:
            db.execute(
                "UPDATE runs SET state = ?, ended_at = ?, note = ? "
                "WHERE run_id = ? AND state IN ('queued', 'running')",
                (state, self._clock(), note, run_id),
            )

    def get(self, run_id: str) -> RunEntry | None:
        with self._connect() as db:
            row = db.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        return None if row is None else self._seen(row)

    def recent(self, limit: int = 50) -> list[RunEntry]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT * FROM runs ORDER BY queued_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._seen(row) for row in rows]

    def active(self) -> RunEntry | None:
        return next((e for e in self.recent(5) if e.active), None)

    def _seen(self, row: sqlite3.Row) -> RunEntry:
        """A row as a reader must see it: a dead worker's run is not shown as running."""
        entry = _entry(row)
        if entry.active and entry.pid is not None and not self._alive(entry.pid):
            return _replace_state(entry, "interrupted", "worker process ended without a finish")
        return entry


def _replace_state(entry: RunEntry, state: RunState, note: str) -> RunEntry:
    fields = {**entry.__dict__, "state": state, "note": note}
    return RunEntry(**fields)


def _entry(row: sqlite3.Row) -> RunEntry:
    data = dict(row)
    data.pop("request_key")
    data["spec"] = RunSpec.model_validate(json.loads(data["spec"]))
    return RunEntry(**data)

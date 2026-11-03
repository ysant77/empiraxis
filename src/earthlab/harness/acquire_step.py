"""An acquisition inside a harness run: proposed by a model, permitted by a person, run by code.

The data specialist may propose one named operation with typed parameters. It never writes a
URL. Code checks the proposal against fixed limits and the sealed period, then asks the
resource desk for a signed, unexpired approval that covers the operation's endpoint. Only then
does trusted code build the requests. Each response is logged with its digest, bytes and times,
and the acquired values are checked against the local source. A refusal is recorded and the run
continues without the data.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

import httpx
import numpy as np
from pydantic import Field

from earthlab.acquire.nea_live import BASE, CaptureLog, Observation, capture
from earthlab.contracts import Strict
from earthlab.digest import file_digest
from earthlab.forecast.dataset import REGIONS, SPLITS, Grid, index_of
from earthlab.team.resources import RequestRefused, ResourceDesk

if TYPE_CHECKING:
    from earthlab.harness.engine import Engine

OPERATION = "capture_nea_day"
ENDPOINT = BASE + "pm25"
FIRST_DAY = date(2014, 4, 1)
SEALED_DAY = SPLITS["test"][0].date()
MAX_DAYS, MAX_BYTES, MAX_SECONDS = 3, 1_000_000, 120.0
LICENCE = "Singapore Open Data Licence v1.0"
SYSTEM = "You are the Data Scientist. Before any method is chosen, you may request one small \
acquisition to check the local source. Call propose_acquisition with operation capture_nea_day \
and up to three dates before the sealed period, or operation none. You never write a URL. A \
person's signed approval decides whether it runs."


class AcquisitionProposal(Strict):
    operation: Literal["capture_nea_day", "none"]
    dates: tuple[date, ...] = Field(default=(), max_length=MAX_DAYS)
    reason: str = Field(min_length=10, max_length=300)


class AcquisitionReceiptV1(Strict):
    """What was asked, what was allowed, what came back, and how it compares with the source."""

    schema_version: Literal["1"] = "1"
    operation: str
    dates: tuple[date, ...]
    state: Literal["acquired", "refused", "not_requested"]
    reason: str
    request_id: str | None = None
    endpoint: str = ENDPOINT
    licence: str = LICENCE
    started_at: datetime | None = None
    finished_at: datetime | None = None
    requests: int = 0
    bytes: int = 0
    log_sha256: str | None = None
    values: int = 0
    matched: int = 0
    mismatched: int = 0
    not_in_source: int = 0
    mismatches: tuple[str, ...] = ()


@dataclass(frozen=True)
class AcquisitionConfig:
    request_id: str
    desk_root: Path
    client: httpx.Client | None = None


def check(proposal: AcquisitionProposal) -> list[str]:
    """Typed limits. A sealed date, a duplicate or too many dates is refused."""
    found = []
    if proposal.operation == "none":
        return [] if not proposal.dates else ["operation none takes no dates"]
    if not proposal.dates:
        found.append("capture_nea_day needs at least one date")
    if len(set(proposal.dates)) != len(proposal.dates):
        found.append("dates repeat")
    for day in proposal.dates:
        if not FIRST_DAY <= day < SEALED_DAY:
            found.append(f"{day} is outside {FIRST_DAY} to {SEALED_DAY - timedelta(days=1)}")
    return found


def compare(rows: list[Observation], truth: Grid) -> dict[str, Any]:
    """Each acquired value against the local source at the same hour and region."""
    matched = mismatched = absent = 0
    notes: list[str] = []
    for row in rows:
        hour = row.event_time.astimezone(UTC).replace(tzinfo=None) + timedelta(hours=8)
        cell = truth.values[index_of(hour), REGIONS.index(row.place_id)]
        if np.isnan(cell) or row.value is None:
            absent += 1
        elif abs(float(cell) - row.value) < 1e-9:
            matched += 1
        else:
            mismatched += 1
            notes.append(f"{row.place_id} {hour:%Y-%m-%d %H:00}: API {row.value}, file {cell}")
    return {"matched": matched, "mismatched": mismatched, "not_in_source": absent,
            "mismatches": tuple(notes[:20])}  # fmt: skip


def _permit(config: AcquisitionConfig) -> str | None:
    """None when a signed, unexpired approval covers this endpoint; else the reason it does not."""
    try:
        request = ResourceDesk(config.desk_root).authorized(config.request_id)
    except RequestRefused as exc:
        return str(exc)
    except (FileNotFoundError, IndexError, KeyError):
        return f"no request {config.request_id} exists"
    return None if request.url == ENDPOINT else "the approval covers another endpoint"


def execute(
    proposal: AcquisitionProposal, config: AcquisitionConfig, folder: Path, truth: Grid,
    clock: Callable[[], float] = time.monotonic,
) -> AcquisitionReceiptV1:  # fmt: skip
    """Run an approved proposal within the limits, then compare it with the source."""
    base = {"operation": proposal.operation, "dates": proposal.dates,
            "request_id": config.request_id}  # fmt: skip
    why = _permit(config)
    if why is not None:
        return AcquisitionReceiptV1(**base, state="refused", reason=why)
    log, started, begin = CaptureLog(folder / "nea-pm25.jsonl"), datetime.now(UTC), clock()
    requests = size = 0
    for day in proposal.dates:
        if size > MAX_BYTES or clock() - begin > MAX_SECONDS:
            return AcquisitionReceiptV1(**base, state="refused", reason="a limit was reached")
        counts = capture(log, ("pm25",), config.client, day=day)["pm25"]
        requests, size = requests + counts["pages"], size + counts["bytes"]
    rows = [Observation.model_validate_json(x) for x in log.path.read_text().splitlines()]
    ResourceDesk(config.desk_root).record_fetch(
        config.request_id, operation=OPERATION, dates=[d.isoformat() for d in proposal.dates],
        bytes=size, log_sha256=file_digest(log.path),
    )  # fmt: skip
    return AcquisitionReceiptV1(
        **base, state="acquired", reason="approved and run within the limits",
        started_at=started, finished_at=datetime.now(UTC), requests=requests, bytes=size,
        log_sha256=file_digest(log.path), values=len(rows), **compare(rows, truth),
    )  # fmt: skip


def step(engine: Engine) -> None:
    """The team's acquisition step. With no config on the adapter, nothing runs or is recorded."""
    config: AcquisitionConfig | None = getattr(engine.adapter, "acquisition", None)
    if config is None or engine.arm != "team":
        return
    truth: Grid = engine.adapter.bench.grid  # type: ignore[attr-defined]
    facts = {"problem": engine.problem.model_dump(mode="json"), "operation": OPERATION,
             "first_day": FIRST_DAY, "sealed_from": SEALED_DAY, "max_days": MAX_DAYS}  # fmt: skip
    proposal = engine.seats.propose(
        "data_specialist", SYSTEM, facts, "propose_acquisition", AcquisitionProposal, check
    )
    if proposal.operation == "none":
        receipt = AcquisitionReceiptV1(
            operation="none", dates=(), state="not_requested", reason=proposal.reason
        )
    else:
        receipt = execute(proposal, config, engine.run_dir / "acquired", truth)
    engine.keep("acquisition", receipt, engine.seats.root)
    if receipt.state == "acquired":
        engine.life.move("acquired", "controller", receipt_sha256=engine.digests["acquisition"])
    else:
        engine.seats.trace.append("acquisition_refused", "controller", reason=receipt.reason)

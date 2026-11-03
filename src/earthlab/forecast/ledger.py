"""EXPERIMENTAL prospective research predictions, issued before the observation exists.

Off by default. A prediction can be issued only when an activation record exists and its
signature matches the operator key; a model cannot hold that key. The first method is
persistence: the newest published regional PM2.5 value. Each prediction is appended once with
its digest and is never changed. A later verification reads the captured NEA observation for
the same region and hour and appends its own record. A missing observation stays missing.

This is not a forecast service, a health warning or evidence of haze-forecast skill.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from pydantic import Field

from earthlab.acquire.nea_live import Observation
from earthlab.contracts import Strict
from earthlab.digest import payload_digest
from earthlab.team.resources import operator_key

METHOD = "persistence-latest-published"
METHOD_SHA256 = hashlib.sha256(METHOD.encode()).hexdigest()
ACTIVATION = "activation.json"


class LedgerDisabled(RuntimeError):
    pass


class ActivationV1(Strict):
    """The owner's decision to allow issuing. The signature needs the operator key."""

    approver: str
    decided_at_utc: datetime
    expires_utc: datetime
    max_predictions: int = Field(ge=1, le=500)
    note: str = Field(default="", max_length=300)
    signature: str = ""

    def body(self) -> bytes:
        return json.dumps(
            self.model_dump(mode="json", exclude={"signature"}), sort_keys=True
        ).encode()


def sign_activation(activation: ActivationV1, key: str) -> ActivationV1:
    signature = hmac.new(key.encode(), activation.body(), hashlib.sha256).hexdigest()
    return activation.model_copy(update={"signature": signature})


class PredictionV1(Strict):
    schema_version: Literal["1"] = "1"
    prediction_id: str
    issued_at: datetime
    region: str
    quantity: Literal["pm25"] = "pm25"
    target_time: datetime
    horizon_hours: int = Field(ge=1, le=24)
    value: float
    unit: Literal["ug/m3"] = "ug/m3"
    method: str = METHOD
    method_sha256: str = METHOD_SHA256
    input_raw_sha256: str
    input_event_time: datetime
    input_published_at: datetime
    record_sha256: str = ""


class VerificationV1(Strict):
    schema_version: Literal["1"] = "1"
    prediction_id: str
    prediction_sha256: str
    checked_at: datetime
    state: Literal["scored", "observation_missing", "not_due"]
    observed: float | None = None
    observed_raw_sha256: str | None = None
    absolute_error: float | None = None
    later_corrections: int = 0


def _rows(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines() if path.exists() else []


class Ledger:
    """predictions.jsonl and verifications.jsonl in one folder, both append-only."""

    def __init__(self, folder: Path):
        self.folder = folder
        self.predictions = folder / "predictions.jsonl"
        self.verifications = folder / "verifications.jsonl"

    def active(self, now: datetime) -> ActivationV1:
        """The valid activation, or raise. No file, no key or a bad signature means off."""
        path = self.folder / ACTIVATION
        key = operator_key()
        if not path.exists() or key is None:
            raise LedgerDisabled("the ledger is off: no signed activation, or no operator key")
        activation = ActivationV1.model_validate_json(path.read_text(encoding="utf-8"))
        if not hmac.compare_digest(
            sign_activation(activation, key).signature, activation.signature
        ):
            raise LedgerDisabled("the activation signature does not match")
        if activation.expires_utc <= now:
            raise LedgerDisabled("the activation has expired")
        if len(_rows(self.predictions)) >= activation.max_predictions:
            raise LedgerDisabled("the activation's prediction limit is reached")
        return activation

    def issue(
        self, latest: list[Observation], now: datetime, horizon: int = 6
    ) -> list[PredictionV1]:
        """Persistence from the newest PM2.5 value per region that was published before now."""
        self.active(now)
        known = [o for o in latest if o.product == "pm25" and o.value is not None
                 and o.issued_time is not None and o.issued_time <= now]  # fmt: skip
        newest: dict[str, Observation] = {}
        for o in known:
            if o.place_id not in newest or o.event_time > newest[o.place_id].event_time:
                newest[o.place_id] = o
        hour = now.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
        issued = {
            PredictionV1.model_validate_json(x).prediction_id for x in _rows(self.predictions)
        }
        out = [self._predict(o, now, hour + timedelta(hours=horizon), horizon)
               for o in sorted(newest.values(), key=lambda o: o.place_id)]  # fmt: skip
        out = [p for p in out if p.prediction_id not in issued]  # one prediction per target
        self.folder.mkdir(parents=True, exist_ok=True)
        with self.predictions.open("a", encoding="utf-8") as f:
            f.writelines(p.model_dump_json() + "\n" for p in out)
        return out

    @staticmethod
    def _predict(o: Observation, now: datetime, target: datetime, horizon: int) -> PredictionV1:
        row = PredictionV1(
            prediction_id=f"{target:%Y%m%dT%H}Z-{o.place_id}-h{horizon}", issued_at=now,
            region=o.place_id, target_time=target, horizon_hours=horizon, value=float(o.value or 0),
            input_raw_sha256=o.raw_sha256, input_event_time=o.event_time,
            input_published_at=o.issued_time or o.retrieved_at,
        )  # fmt: skip
        return row.model_copy(update={"record_sha256": payload_digest(row.model_dump(mode="json"))})

    def verify(self, captured: list[Observation], now: datetime) -> list[VerificationV1]:
        """Score each prediction once, from the first published value at its target hour."""
        done = {
            VerificationV1.model_validate_json(x).prediction_id for x in _rows(self.verifications)
        }
        out = []
        for line in _rows(self.predictions):
            p = PredictionV1.model_validate_json(line)
            if p.prediction_id in done:
                continue
            out.append(self._check(p, captured, now))
        scored = [v for v in out if v.state != "not_due"]
        with self.verifications.open("a", encoding="utf-8") as f:
            f.writelines(v.model_dump_json() + "\n" for v in scored)
        return out

    @staticmethod
    def _check(p: PredictionV1, captured: list[Observation], now: datetime) -> VerificationV1:
        base = {"prediction_id": p.prediction_id, "prediction_sha256": p.record_sha256,
                "checked_at": now}  # fmt: skip
        same = [o for o in captured if o.product == "pm25" and o.place_id == p.region
                and o.event_time == p.target_time]  # fmt: skip
        first = [o for o in same if o.kind == "first" and o.value is not None]
        if not first:
            late = now - p.target_time > timedelta(hours=2)
            return VerificationV1(**base, state="observation_missing" if late else "not_due")
        seen = first[0].value or 0.0
        return VerificationV1(
            **base, state="scored", observed=seen, observed_raw_sha256=first[0].raw_sha256,
            absolute_error=abs(p.value - seen), later_corrections=len(same) - len(first),
        )  # fmt: skip


def summary(ledger: Ledger) -> dict[str, int]:
    rows = [VerificationV1.model_validate_json(x) for x in _rows(ledger.verifications)]
    return {
        "predictions": len(_rows(ledger.predictions)),
        "scored": sum(v.state == "scored" for v in rows),
        "observation_missing": sum(v.state == "observation_missing" for v in rows),
    }

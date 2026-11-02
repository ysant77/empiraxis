"""The experimental prediction ledger: off by default, signed activation, append-only records."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from earthlab.acquire.nea_live import Observation, parse
from earthlab.forecast.ledger import (
    ACTIVATION,
    ActivationV1,
    Ledger,
    LedgerDisabled,
    sign_activation,
    summary,
)
from earthlab.team.resources import OPERATOR_KEY_ENV

FIXTURE = Path(__file__).parent / "fixtures" / "nea_live" / "pm25.json"
KEY = "test-operator-key"
NOW = datetime(2026, 11, 2, 16, 45, tzinfo=UTC)  # 00:45 SGT, after the 00:00 value was published


def observed() -> list[Observation]:
    return parse("pm25", FIXTURE.read_bytes(), NOW, "https://example.org/pm25")


def activate(folder: Path, key: str = KEY, hours: int = 24, limit: int = 50) -> None:
    activation = ActivationV1(
        approver="owner", decided_at_utc=NOW, expires_utc=NOW + timedelta(hours=hours),
        max_predictions=limit,
    )  # fmt: skip
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ACTIVATION).write_text(sign_activation(activation, key).model_dump_json())


@pytest.fixture
def operator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)


def test_the_ledger_is_off_without_a_signed_activation(tmp_path: Path, operator: None) -> None:
    with pytest.raises(LedgerDisabled, match="off"):
        Ledger(tmp_path).issue(observed(), NOW)
    activate(tmp_path, key="another-key")
    with pytest.raises(LedgerDisabled, match="signature"):
        Ledger(tmp_path).issue(observed(), NOW)
    activate(tmp_path, hours=-1)
    with pytest.raises(LedgerDisabled, match="expired"):
        Ledger(tmp_path).issue(observed(), NOW)


def test_the_ledger_is_off_without_the_operator_key(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    activate(tmp_path)
    monkeypatch.delenv(OPERATOR_KEY_ENV, raising=False)
    with pytest.raises(LedgerDisabled):
        Ledger(tmp_path).issue(observed(), NOW)


def test_persistence_uses_only_published_values_once_per_target(
    tmp_path: Path, operator: None
) -> None:
    activate(tmp_path)
    ledger = Ledger(tmp_path)
    early = NOW.replace(minute=10)  # 00:10 SGT: the 00:00 value is not published yet
    assert ledger.issue(observed(), early) == []
    made = ledger.issue(observed(), NOW)
    assert len(made) == 5 and {p.horizon_hours for p in made} == {6}
    assert all(p.input_published_at <= p.issued_at < p.target_time for p in made)
    assert ledger.issue(observed(), NOW) == []
    assert len(ledger.predictions.read_text().splitlines()) == 5


def test_verification_appends_and_never_changes_a_prediction(
    tmp_path: Path, operator: None
) -> None:
    activate(tmp_path)
    ledger = Ledger(tmp_path)
    made = ledger.issue(observed(), NOW)
    before = ledger.predictions.read_bytes()
    target = made[0].target_time
    truth = [o.model_copy(update={"event_time": target, "value": 40.0}) for o in observed()]
    same = next(o for o in truth if o.place_id == made[0].region)
    fixed = same.model_copy(update={"value": 41.0, "kind": "correction"})
    assert {v.state for v in ledger.verify([], target)} == {"not_due"}
    rows = ledger.verify([fixed, *truth], target + timedelta(hours=1))
    assert {v.state for v in rows} == {"scored"}
    first = next(v for v in rows if v.prediction_id == made[0].prediction_id)
    assert first.observed == 40.0 and first.later_corrections == 1
    assert ledger.predictions.read_bytes() == before
    assert summary(ledger) == {"predictions": 5, "scored": 5, "observation_missing": 0}


def test_a_missing_observation_is_recorded_as_missing(tmp_path: Path, operator: None) -> None:
    activate(tmp_path)
    ledger = Ledger(tmp_path)
    made = ledger.issue(observed(), NOW)
    rows = ledger.verify([], made[0].target_time + timedelta(hours=3))
    assert {v.state for v in rows} == {"observation_missing"}
    assert json.loads(ledger.verifications.read_text().splitlines()[0])["observed"] is None

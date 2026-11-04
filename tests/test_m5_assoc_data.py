"""Daily series builders: Singapore-day alignment, 80% rule, transport sign."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest

from earthlab.forecast.dataset import Grid, index_of
from earthlab.haze.geometry import H1_SOURCE_BOXES
from earthlab.m5 import assoc_data as D


def test_daily_outcome_needs_eighty_percent() -> None:
    n = index_of(datetime(2015, 11, 2, 0))
    values = np.full((n, 5), np.nan)
    first = index_of(datetime(2015, 9, 1, 0))
    values[first : first + 24, :] = 10.0  # 1 September complete
    day2 = first + 24
    values[day2 : day2 + 24, :] = 20.0
    values[day2 : day2 + 24, :][5:] = np.nan  # 19 of 24 hours = 79% -> missing
    out = D.daily_outcome(Grid(values=values, source_sha256="x"), 2015)
    assert out[0] == 10.0 and np.isnan(out[1])


def test_fire_daily_uses_singapore_days() -> None:
    late_utc = datetime(2015, 9, 1, 17, 0, tzinfo=UTC).timestamp()  # 01:00 SGT on 2 Sep
    early = datetime(2015, 9, 1, 3, 0, tzinfo=UTC).timestamp()
    out = D.fire_daily(np.array([late_utc, early, early]), 2015)
    assert out[0] == 2 and out[1] == 1 and out.sum() == 3


def write_extract(path: Path, box_id: str, u: float, v: float, rain: float) -> None:
    hours = []
    for k in range(24 * 3):
        t = datetime(2015, 8, 31, 16, tzinfo=UTC).timestamp() + k * 3600
        hours.append({"time": datetime.fromtimestamp(t, UTC).isoformat().replace("+00:00", "Z"),
                      "u_ms": u, "v_ms": v, "precip_mm": rain})  # fmt: skip
    path.write_text(json.dumps({"series": [{"box_id": box_id, "hours": hours}]}))


def test_met_daily_means_sums_and_short_days(tmp_path: Path) -> None:
    f = tmp_path / "e.json"
    write_extract(f, "box-a", 2.0, -1.0, 0.5)
    assert D.met_daily(f, "box-a", 2015, "u_ms")[0] == pytest.approx(2.0)
    assert D.met_daily(f, "box-a", 2015, "precip_mm")[0] == pytest.approx(12.0)
    assert np.isnan(D.met_daily(f, "box-a", 2015, "u_ms")[10])  # no hours that day


def test_transport_is_positive_when_wind_blows_toward_singapore(tmp_path: Path) -> None:
    box = H1_SOURCE_BOXES[2]  # Kalimantan, south-east of Singapore
    toward = np.radians(box.bearing_deg + 180.0)  # direction of travel, receptor-ward
    f = tmp_path / "e.json"
    write_extract(f, box.box_id, 5.0 * np.sin(toward), 5.0 * np.cos(toward), 0.0)
    assert D.transport_daily(f, box.box_id, 2015)[0] == pytest.approx(5.0, abs=1e-6)
    write_extract(f, box.box_id, -5.0 * np.sin(toward), -5.0 * np.cos(toward), 0.0)
    assert D.transport_daily(f, box.box_id, 2015)[0] == pytest.approx(-5.0, abs=1e-6)

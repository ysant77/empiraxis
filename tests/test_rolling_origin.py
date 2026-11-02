"""Rolling-origin ridge selection: folds stay in the train years, and no target crosses an edge."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from earthlab.forecast import samples as S
from earthlab.forecast.dataset import index_of, load_grid
from earthlab.mlops import rolling as R

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("year", R.FOLD_YEARS)
def test_each_fold_stays_in_the_train_years(year: int) -> None:
    train, score = R.fold_rows(year)
    _, last = S.split_bounds("train")
    assert score.max() + R.HORIZON <= last
    assert train.max() + R.HORIZON < score.min()
    assert train.min() - S.USABLE_OFFSET - R.LAGS + 1 >= 0
    assert score.min() >= index_of(datetime(year, 1, 1))


def test_the_search_runs_on_train_folds_and_records_the_baseline() -> None:
    grid, _ = load_grid(ROOT / "data" / "nea" / "Historical1hrPM2.5.csv")
    out = R.run(grid)
    search = out["search"]
    assert search["selection_split"] == "rolling_origin_train"
    assert search["stopped"] == "finished"
    assert all(t["state"] == "completed" for t in search["trials"])
    assert set(out["persistence_fold_mae"]) == set(R.FOLD_YEARS)

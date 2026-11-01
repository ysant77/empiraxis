from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from earthlab.data.nea_pm25 import Pm25Dataset, load_pm25
from earthlab.data.snapshot import open_snapshot
from earthlab.digest import file_digest
from earthlab.forecast import dataset, evaluator, pipeline
from earthlab.harness import attest, classify, replay

REPO_DATA = Path(__file__).resolve().parents[1] / "data" / "nea"
HEADER = "1hr_pm25,north,south,east,west,central"

DatasetFactory = Callable[[list[str]], Path]
PLAIN_LOAD_GRID, PLAIN_READ_TRUTH = dataset.load_grid, evaluator.read_truth


@lru_cache(maxsize=8)
def _parsed(path: Path, _digest: str) -> tuple[Any, Any, np.ndarray, str]:
    """Equal bytes parse once. Read-only arrays turn a shared mutation into an error."""
    grid, audit = PLAIN_LOAD_GRID(path)
    truth, sha = PLAIN_READ_TRUTH(path)
    grid.values.flags.writeable = False
    truth.flags.writeable = False
    return grid, audit, truth, sha


def _load_grid(path: Path) -> tuple[Any, Any]:
    grid, audit, _, _ = _parsed(path, file_digest(path))
    return grid, audit


def _read_truth(path: Path) -> tuple[np.ndarray, str]:
    _, _, truth, sha = _parsed(path, file_digest(path))
    return truth, sha


@pytest.fixture(autouse=True, scope="session")
def shared_source_parsing() -> Iterator[None]:
    """Line coverage makes the CSV parsers slow, and most tests read the same file."""
    patch = pytest.MonkeyPatch()
    for module in (dataset, pipeline, classify):
        patch.setattr(module, "load_grid", _load_grid)
    for module in (evaluator, pipeline, classify, replay):
        patch.setattr(module, "read_truth", _read_truth)
    patch.setattr(attest, "load_grid", _load_grid)
    yield
    patch.undo()


@pytest.fixture
def make_data_dir(tmp_path: Path) -> DatasetFactory:
    """Write a small NEA-format CSV plus a matching manifest; return the directory."""

    def build(lines: list[str]) -> Path:
        csv_path = tmp_path / "pm25.csv"
        csv_path.write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
        manifest = json.loads((REPO_DATA / "manifest.json").read_text(encoding="utf-8"))
        manifest.update(
            file="pm25.csv", sha256=file_digest(csv_path), bytes=csv_path.stat().st_size
        )
        (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        return tmp_path

    return build


@pytest.fixture
def small_dataset(make_data_dir: DatasetFactory) -> Pm25Dataset:
    lines = [
        "1/9/2015 0:00,10,20,30,40,50",
        "1/9/2015 1:00,12,22,,44,55",
        "1/9/2015 3:00,14,24,34,400,54",
        "1/9/2015 3:00,14,24,34,400,54",
        "2015-09-01 002:00:00,11,21,31,41,51",
    ]
    snapshot, path = open_snapshot(make_data_dir(lines))
    return load_pm25(path, snapshot)


@pytest.fixture(scope="session")
def real_dataset() -> Pm25Dataset:
    snapshot, path = open_snapshot(REPO_DATA)
    return load_pm25(path, snapshot)

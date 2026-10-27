from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import pytest

from earthlab.data.nea_pm25 import Pm25Dataset, load_pm25
from earthlab.data.snapshot import open_snapshot
from earthlab.hashing import file_sha256

REPO_DATA = Path(__file__).resolve().parents[1] / "data" / "nea"
HEADER = "1hr_pm25,north,south,east,west,central"

DatasetFactory = Callable[[list[str]], Path]


@pytest.fixture
def make_data_dir(tmp_path: Path) -> DatasetFactory:
    """Write a small NEA-format CSV plus a matching manifest; return the directory."""

    def build(lines: list[str]) -> Path:
        csv_path = tmp_path / "pm25.csv"
        csv_path.write_text("\n".join([HEADER, *lines]) + "\n", encoding="utf-8")
        manifest = json.loads((REPO_DATA / "manifest.json").read_text(encoding="utf-8"))
        manifest.update(
            file="pm25.csv", sha256=file_sha256(csv_path), bytes=csv_path.stat().st_size
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

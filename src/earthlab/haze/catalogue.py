"""Load the haze dataset catalogue (config/haze/datasets.yaml) into strict descriptors."""

from __future__ import annotations

from pathlib import Path

import yaml

from earthlab.haze.contracts import DatasetDescriptor


def load_catalogue(path: Path) -> tuple[DatasetDescriptor, ...]:
    """Every descriptor in the file. Duplicate IDs and unknown fields are refused."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("datasets"), list):
        raise ValueError(f"{path}: expected a mapping with a 'datasets' list")
    descriptors = tuple(DatasetDescriptor.model_validate(item) for item in raw["datasets"])
    ids = [d.dataset_id for d in descriptors]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{path}: duplicate dataset_id")
    return descriptors

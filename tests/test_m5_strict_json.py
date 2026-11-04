from __future__ import annotations

import json
from pathlib import Path

import pytest

from earthlab.digest import file_digest
from earthlab.m5 import strict_json as sj

ROOT = Path(__file__).resolve().parents[1]
# The primary M5-C record holds NaN tokens. It stays byte-identical; a strict export sits beside it.
PRIMARY = "docs/m5/results/m5_c_v1.json"
PRIMARY_SHA256 = "7ec0a05ea212c6113d277ebc03e4aa8af2ec2494ce1a6ea768c3cfc0413bec57"


def published() -> list[Path]:
    found = [*(ROOT / "docs/m5").rglob("*.json"), *(ROOT / "docs/m5").rglob("*.jsonl")]
    found += list((ROOT / "config/m5").rglob("*.json"))
    return sorted(p for p in found if p.relative_to(ROOT).as_posix() != PRIMARY)


def test_the_list_of_published_files_is_not_empty() -> None:
    assert len(published()) >= 25


@pytest.mark.parametrize("path", published(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_published_file_is_strict_json(path: Path) -> None:
    text = path.read_text()
    lines = [x for x in text.splitlines() if x] if path.suffix == ".jsonl" else [text]
    assert lines
    for line in lines:
        sj.loads_strict(line)


def test_the_primary_record_is_unchanged_and_the_only_one_with_nan() -> None:
    assert file_digest(ROOT / PRIMARY) == PRIMARY_SHA256
    with pytest.raises(ValueError, match="NaN"):
        sj.loads_strict((ROOT / PRIMARY).read_text())


def test_strict_export_keeps_every_number_and_lists_each_missing_value() -> None:
    export = sj.loads_strict((ROOT / "docs/m5/results/m5_c_v1.strict_v1.json").read_text())
    assert export["source_sha256"] == PRIMARY_SHA256
    assert len(export["missing_value_reasons"]) == 9
    original = json.loads((ROOT / PRIMARY).read_text())
    for item in export["missing_value_reasons"]:
        node, kept = original, export["data"]
        for key in item["path"].strip("/").split("/"):
            node, kept = (
                node[int(key) if isinstance(node, list) else key],
                (kept[int(key) if isinstance(kept, list) else key]),
            )
        assert node != node and kept is None  # NaN in the source, null in the export
        assert item["reason"]


def test_writer_rejects_non_finite_numbers_and_sanitize_marks_them() -> None:
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ValueError):
            sj.dumps({"x": bad})
    clean, missing = sj.sanitize(
        {"a": [1.0, float("nan")], "b": {"rate": float("inf")}}, {"rate": "r"}
    )
    assert clean == {"a": [1.0, None], "b": {"rate": None}}
    assert missing == [
        {"path": "/a/1", "reason": sj.DEFAULT_REASON},
        {"path": "/b/rate", "reason": "r"},
    ]
    assert sj.dumps(clean, sort_keys=True) == '{"a": [1.0, null], "b": {"rate": null}}'

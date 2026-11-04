"""Smoke tests for render.py failure handling. No browser is needed; ffmpeg is needed for one."""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
pytest.importorskip("playwright")
import render


class BadPage:
    """A page that returns bytes that are not a PNG, so ffmpeg must fail."""

    def evaluate(self, _: str) -> None:
        return None

    def screenshot(self, **_: object) -> bytes:
        return b"not a png"


def test_clean_capture_passes(tmp_path: Path) -> None:
    out = tmp_path / "f.mp4"
    out.write_bytes(b"x")
    assert render.verdict([], 0, str(out)) == 0
    assert out.exists()


def test_page_error_fails_and_removes_the_film(tmp_path: Path) -> None:
    out = tmp_path / "f.mp4"
    out.write_bytes(b"x")
    assert render.verdict(["ReferenceError: x"], 0, str(out)) == 2
    assert not out.exists()


def test_encoder_failure_fails() -> None:
    assert render.verdict([], 1, None) == 2


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")
def test_ffmpeg_failure_is_reported(tmp_path: Path) -> None:
    out = tmp_path / "f.mp4"
    code = render.film(BadPage(), str(out), 0.0, 0.1, [])
    assert code != 0
    assert render.verdict([], code, str(out)) == 2
    assert not out.exists()

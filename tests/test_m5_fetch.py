"""Capped download: host allow-list, token handling, cap checks and digest."""

from __future__ import annotations

import hashlib
import io
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any

import pytest

from earthlab.m5 import fetch

URL = "https://data.lpdaac.earthdatacloud.nasa.gov/x/y.tif"
SECRET = "SECRET-TOKEN-VALUE"


class Resp:
    def __init__(self, data: bytes, length: str | None = "auto") -> None:
        self._io = io.BytesIO(data)
        self.headers = Message()
        if length == "auto":
            self.headers["Content-Length"] = str(len(data))
        elif length is not None:
            self.headers["Content-Length"] = length

    def read(self, n: int) -> bytes:
        return self._io.read(n)


def opener_for(
    data: bytes, length: str | None = "auto"
) -> tuple[Any, list[urllib.request.Request]]:
    seen: list[urllib.request.Request] = []

    def op(request: urllib.request.Request) -> Resp:
        seen.append(request)
        if request.has_header("Authorization"):
            h = Message()
            h["Location"] = "https://signed.example/obj"
            raise urllib.error.HTTPError(request.full_url, 303, "see other", h, None)
        return Resp(data, length)

    return op, seen


def test_download_hashes_follows_redirect_without_the_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(fetch.TOKEN_ENV, SECRET)
    op, seen = opener_for(b"hello")
    sha, size = fetch.download(URL, tmp_path / "a" / "f.bin", 100, op)
    assert (sha, size) == (hashlib.sha256(b"hello").hexdigest(), 5)
    assert seen[0].get_header("Authorization") == f"Bearer {SECRET}"
    assert not seen[1].has_header("Authorization")


def test_refuses_host_scheme_missing_token_and_caps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(fetch.TOKEN_ENV, SECRET)
    for bad in ("http://data.lpdaac.earthdatacloud.nasa.gov/x", "https://evil.example/x"):
        with pytest.raises(fetch.FetchRefused):
            fetch.download(bad, tmp_path / "f", 100)
    op, _ = opener_for(b"x" * 50)
    with pytest.raises(fetch.FetchRefused, match="announced"):
        fetch.download(URL, tmp_path / "f", 10, op)
    op2, _ = opener_for(b"x" * 50, length=None)
    with pytest.raises(fetch.FetchRefused, match="passed the cap"):
        fetch.download(URL, tmp_path / "g", 10, op2)
    assert not (tmp_path / "g").exists()
    monkeypatch.delenv(fetch.TOKEN_ENV)
    with pytest.raises(fetch.FetchRefused, match="not set") as err:
        fetch.download(URL, tmp_path / "h", 10, op)
    assert SECRET not in str(err.value)


def test_http_errors_do_not_leak_the_token(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(fetch.TOKEN_ENV, SECRET)

    def op(request: urllib.request.Request) -> Resp:
        raise urllib.error.HTTPError(request.full_url, 403, "no", Message(), None)

    with pytest.raises(fetch.FetchRefused, match="HTTP 403") as err:
        fetch.download(URL, tmp_path / "f", 10, op)
    assert SECRET not in str(err.value)

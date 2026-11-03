"""Capped download from NASA Earthdata with a bearer token read from the environment.

The token is never printed, logged or put in an error. The first request carries it; the
redirect target (a signed storage URL) is followed without it. The announced size is checked
against the byte cap before any byte is written, and the written file is checked again.
Only https URLs on an allow-listed host are fetched.
"""

from __future__ import annotations

import hashlib
import os
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

TOKEN_ENV = "EARTHDATA_TOKEN"  # noqa: S105 - the variable name, not a secret
ALLOWED_HOSTS = (
    "data.lpdaac.earthdatacloud.nasa.gov",
    "data.gesdisc.earthdata.nasa.gov",
    "n5eil01u.ecs.nsidc.org",
    "data.nsidc.earthdatacloud.nasa.gov",
)
CHUNK = 1 << 20
Opener = Callable[[urllib.request.Request], Any]


class FetchRefused(PermissionError):
    """The URL, token or size was refused before or during transfer. No secret is included."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


def _token() -> str:
    token = os.environ.get(TOKEN_ENV, "")
    if not token:
        raise FetchRefused(f"{TOKEN_ENV} is not set")
    return token


def check_url(url: str) -> None:
    parts = urllib.parse.urlparse(url)
    if parts.scheme != "https" or parts.hostname not in ALLOWED_HOSTS:
        raise FetchRefused(f"host not allowed: {parts.hostname}")


def _open_follow(url: str, headers: dict[str, str], opener: Opener) -> Any:
    request = urllib.request.Request(url, headers=headers)  # noqa: S310 - https checked
    try:
        return opener(request)
    except urllib.error.HTTPError as err:
        target = err.headers.get("Location")
        if err.code in (301, 302, 303, 307, 308) and target:
            plain = urllib.request.Request(target)  # noqa: S310 - signed URL, no token
            if urllib.parse.urlparse(target).scheme != "https":
                raise FetchRefused("redirect target is not https") from None
            return opener(plain)
        raise FetchRefused(f"HTTP {err.code} for {urllib.parse.urlparse(url).path}") from None


def _default_opener() -> Opener:
    first = urllib.request.build_opener(_NoRedirect)
    plain = urllib.request.build_opener()

    def open_(request: urllib.request.Request) -> Any:
        has_token = request.has_header("Authorization")
        return (first if has_token else plain).open(request, timeout=120)

    return open_


def download(
    url: str, target: Path, byte_cap: int, opener: Opener | None = None
) -> tuple[str, int]:
    """Fetch url to target and return (sha256, bytes). Refuses on cap, host or missing token."""
    check_url(url)
    opener = opener or _default_opener()
    headers = {"Authorization": f"Bearer {_token()}"}
    response = _open_follow(url, headers, opener)
    announced = response.headers.get("Content-Length")
    if announced is not None and int(announced) > byte_cap:
        raise FetchRefused(f"announced {announced} bytes exceed the cap of {byte_cap}")
    target.parent.mkdir(parents=True, exist_ok=True)
    sha, size = hashlib.sha256(), 0
    with target.open("wb") as out:
        size = _copy(response, out, sha, byte_cap, target)
    return sha.hexdigest(), size


def _copy(response: Any, out: IO[bytes], sha: Any, byte_cap: int, target: Path) -> int:
    size = 0
    while block := response.read(CHUNK):
        size += len(block)
        if size > byte_cap:
            out.close()
            target.unlink(missing_ok=True)
            raise FetchRefused(f"transfer passed the cap of {byte_cap} bytes")
        sha.update(block)
        out.write(block)
    return size

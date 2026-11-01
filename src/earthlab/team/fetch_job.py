"""One bounded HTTP GET in its own short-lived process. Input: one JSON line on stdin.

The parent gives this process a minimal environment. The credential, when a request has
one, reaches only this process and only as one request header. This code never prints it.
No redirect is followed, and a response over the byte cap is deleted. Every address this
process resolves must be public, so a name that later resolves to an internal host fails.
Only an http URL on a loopback name reaches a local address: the local mock server. This
is a code check, not operating-system isolation, so the broker is for trusted local use.
"""

from __future__ import annotations

import ipaddress
import json
import os
import socket
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from earthlab.acquire.gate import CapExceeded, write_capped

TOKEN_ENV = "EARTHLAB_FETCH_TOKEN"  # noqa: S105 - the name of a variable, not a value
LOOPBACK = ("127.0.0.1", "::1", "localhost")
EXECUTABLE_MAGIC = (b"#!", b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


def is_public(address: str) -> bool:
    ip = ipaddress.ip_address(address.split("%")[0])
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


def public_only(resolve: Callable[..., list[Any]]) -> Callable[..., list[Any]]:
    """A resolver that refuses the whole answer if one address is not public."""

    def guarded(*args: Any, **kwargs: Any) -> list[Any]:
        answers = resolve(*args, **kwargs)
        if not all(is_public(str(answer[4][0])) for answer in answers):
            raise ValueError("the host resolves to an address that is not public")
        return answers

    return guarded


def fetch(job: dict[str, object], token: str | None) -> dict[str, object]:
    url, target = str(job["url"]), Path(str(job["target"]))
    allowed = tuple(str(t) for t in job["content_types"])  # type: ignore[attr-defined]
    if urlsplit(url).hostname != job["domain"]:
        raise ValueError("the URL host is not the approved domain")
    parts = urlsplit(url)
    if not (parts.scheme == "http" and parts.hostname in LOOPBACK):
        socket.getaddrinfo = public_only(socket.getaddrinfo)  # this process does one GET
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    timeout = httpx.Timeout(float(str(job["timeout_seconds"])))
    with httpx.stream(
        "GET", url, headers=headers, timeout=timeout, follow_redirects=False, trust_env=False
    ) as resp:
        if resp.status_code != 200:
            raise ValueError(f"the server answered {resp.status_code}")
        kind = resp.headers.get("content-type", "").split(";")[0].strip()
        if kind not in allowed:
            raise ValueError(f"content type {kind or 'none'} is not approved")
        digest, size = write_capped(resp.iter_bytes(), target, int(str(job["max_bytes"])))
    with target.open("rb") as head:
        if head.read(4).startswith(EXECUTABLE_MAGIC):
            target.unlink()
            raise ValueError("the file looks like an executable")
    return {"sha256": digest, "bytes": size, "content_type": kind}


def main() -> int:
    job = json.loads(sys.stdin.readline())
    try:
        out = fetch(job, os.environ.get(TOKEN_ENV))
    except (ValueError, CapExceeded, httpx.HTTPError) as exc:
        print(json.dumps({"error": f"{type(exc).__name__}: {exc}"}))
        return 1
    print(json.dumps(out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

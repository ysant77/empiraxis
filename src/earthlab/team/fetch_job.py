"""One bounded HTTP GET in its own short-lived process. Input: one JSON line on stdin.

The parent gives this process a minimal environment. The credential, when a request has
one, reaches only this process and only as one request header. This code never prints it.
No redirect is followed, and a response over the byte cap is deleted.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from earthlab.acquire.gate import CapExceeded, write_capped

TOKEN_ENV = "EARTHLAB_FETCH_TOKEN"  # noqa: S105 - the name of a variable, not a value
EXECUTABLE_MAGIC = (b"#!", b"MZ", b"\x7fELF", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


def fetch(job: dict[str, object], token: str | None) -> dict[str, object]:
    url, target = str(job["url"]), Path(str(job["target"]))
    allowed = tuple(str(t) for t in job["content_types"])  # type: ignore[attr-defined]
    if urlsplit(url).hostname != job["domain"]:
        raise ValueError("the URL host is not the approved domain")
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    timeout = httpx.Timeout(float(str(job["timeout_seconds"])))
    with httpx.stream("GET", url, headers=headers, timeout=timeout, follow_redirects=False) as resp:
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

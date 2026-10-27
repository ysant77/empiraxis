"""SHA-256 digests: canonical JSON for structured payloads, streamed bytes for files."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

_READ_SIZE = 1 << 20


def canonical_json(payload: Any) -> bytes:
    """One byte string per logical value: sorted keys, no spaces, non-JSON types as str."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()


def payload_digest(payload: Any) -> str:
    return hashlib.sha256(canonical_json(payload)).hexdigest()


def file_digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(_READ_SIZE), b""):
            sha.update(block)
    return sha.hexdigest()

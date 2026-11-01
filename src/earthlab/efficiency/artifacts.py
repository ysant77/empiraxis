"""Immutable, hash-addressed artifact store. A reference is a hash; a missing one is an error."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from earthlab.contracts import Strict

SHA256 = r"^[0-9a-f]{64}$"
Kind = Literal["text", "record"]


class MissingArtifactError(KeyError):
    """A reference points at an artifact that the store does not hold."""


class ArtifactIntegrityError(ValueError):
    """Stored bytes no longer match the hash in the reference."""


class ArtifactRef(Strict):
    kind: Kind
    sha256: str = Field(pattern=SHA256)


def canonical(value: Any) -> bytes:
    """Stable bytes for a JSON-compatible value: sorted keys, no spaces, UTF-8."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def model_digest(model: BaseModel) -> str:
    return digest(model.model_dump(mode="json"))


class ArtifactStore:
    """Content-addressed and write-once: the same content has the same reference."""

    def __init__(self) -> None:
        self._items: dict[str, bytes] = {}

    def put_text(self, text: str) -> ArtifactRef:
        return self._put("text", text)

    def put_record(self, model: BaseModel) -> ArtifactRef:
        return self._put("record", model.model_dump(mode="json"))

    def _put(self, kind: Kind, value: Any) -> ArtifactRef:
        data = canonical(value)
        key = hashlib.sha256(data).hexdigest()
        self._items.setdefault(key, data)
        return ArtifactRef(kind=kind, sha256=key)

    def get(self, ref: ArtifactRef) -> Any:
        data = self._items.get(ref.sha256)
        if data is None:
            raise MissingArtifactError(ref.sha256)
        if hashlib.sha256(data).hexdigest() != ref.sha256:
            raise ArtifactIntegrityError(ref.sha256)
        return json.loads(data)

    def text(self, ref: ArtifactRef) -> str:
        value = self.get(ref)
        if not isinstance(value, str):
            raise ArtifactIntegrityError(f"{ref.sha256} is not a text artifact")
        return value

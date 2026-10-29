"""Provenance carried by every haze output: evidence class, source hashes and limitations.

The verifier and the Engineering Lab read this block. An output may not claim a class
above the ceiling its method allows, and no output may claim causal inference.
"""

from __future__ import annotations

from typing import Self

from pydantic import Field, model_validator

from earthlab.contracts import Strict
from earthlab.digest import payload_digest
from earthlab.haze.contracts import EvidenceClass

CLASS_ORDER: tuple[EvidenceClass, ...] = tuple(EvidenceClass)


class ClaimRefused(ValueError):
    """The requested evidence class is above what the method and inputs support."""


class SourceRef(Strict):
    dataset_id: str = Field(min_length=1)
    file: str = Field(min_length=1)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class Provenance(Strict):
    evidence_class: EvidenceClass
    method_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    method_version: str = Field(min_length=1)
    sources: tuple[SourceRef, ...] = Field(min_length=1)
    limitations: tuple[str, ...] = Field(min_length=1)
    parameters: dict[str, float | int | str] = Field(default_factory=dict)
    synthetic: bool = False

    @model_validator(mode="after")
    def _never_causal(self) -> Self:
        if self.evidence_class is EvidenceClass.CAUSAL_INFERENCE:
            raise ValueError("no haze output can claim causal inference")
        return self


def check_claim(requested: EvidenceClass, ceiling: EvidenceClass) -> EvidenceClass:
    """Return the requested class if the ceiling allows it; refuse otherwise."""
    if requested is EvidenceClass.CAUSAL_INFERENCE:
        raise ClaimRefused(
            "causal inference is out of scope: it needs emissions and a dispersion model"
        )
    if CLASS_ORDER.index(requested) > CLASS_ORDER.index(ceiling):
        raise ClaimRefused(f"{requested.value} exceeds the {ceiling.value} ceiling")
    return requested


def output_digest(model: Strict) -> str:
    """SHA-256 of the canonical JSON form; equal inputs give equal digests."""
    return payload_digest(model.model_dump(mode="json"))

"""Load case files from config/cases, and express the existing NEA data in case terms.

A case file holds one ScientificCase and its assets. An asset may be written out, or
built from a pinned source manifest so that its hash cannot drift from the data folder.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from earthlab.cases.models import (
    EvidenceClaim,
    ObservationStatus,
    ScientificCase,
    ScientificVariable,
    SourceAsset,
    StudyArea,
    StudyPeriod,
)
from earthlab.contracts import ALL_REGIONS
from earthlab.verify.claims import Verdict, VerificationResult
from earthlab.verify.recompute import IndependentSource

NEA_ZONE = "Asia/Singapore"
_STATUS = {
    Verdict.SUPPORTED: ObservationStatus.SUPPORTED_OBSERVATION,
    Verdict.CONTRADICTED: ObservationStatus.CONTRADICTED,
    Verdict.INSUFFICIENT_DATA: ObservationStatus.INSUFFICIENT_DATA,
    Verdict.UNSUPPORTED: ObservationStatus.NOT_VERIFIED,
}


@dataclass(frozen=True)
class CaseFile:
    case: ScientificCase
    assets: dict[str, SourceAsset]


def asset_from_manifest(path: Path) -> SourceAsset:
    """The pinned NEA manifest as a SourceAsset; hash, size and coverage are copied."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    return SourceAsset(
        asset_id=raw["dataset_id"],
        product=raw["dataset_id"],
        version=raw["source_last_updated"],
        provider=raw["publisher"],
        variable=ScientificVariable.AIR_POLLUTION_OBSERVATION,
        units=raw["unit"],
        licence=raw["licence"],
        licence_url=raw["licence_url"],
        url=raw["source_url"],
        availability="pinned",
        sha256=raw["sha256"],
        bytes=raw["bytes"],
        retrieved_at_utc=raw["retrieved_at_utc"],
        crs="named-regions",
        coverage=StudyPeriod(local_zone=NEA_ZONE, **raw["coverage"]),
        regions=ALL_REGIONS,
        limitations=(raw["spatial_support"], raw["time_label_convention"]),
    )


def _asset(item: dict[str, Any], root: Path) -> SourceAsset:
    if set(item) == {"from_manifest"}:
        return asset_from_manifest(root / item["from_manifest"])
    return SourceAsset.model_validate(item)


def load_case(path: Path, root: Path) -> CaseFile:
    """Load one case file; manifest paths are relative to the repository root."""
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if set(raw) != {"case", "assets"}:
        raise ValueError(f"{path.name}: a case file has exactly 'case' and 'assets'")
    assets = [_asset(item, root) for item in raw["assets"]]
    return CaseFile(
        case=ScientificCase.model_validate(raw["case"]),
        assets={a.asset_id: a for a in assets},
    )


def claim_from_verification(
    result: VerificationResult,
    claim_id: str,
    case: ScientificCase,
    source: IndependentSource,
    source_sha256: str,
) -> EvidenceClaim:
    """An NEA verifier verdict as an EvidenceClaim, with its measured valid fraction."""
    claim = result.claim
    window = claim.window
    regions = ALL_REGIONS if claim.kind.value == "peak_region" else (claim.region,)
    fractions = []
    for region in regions:
        pairs, expected = source.series(region, window)
        fractions.append(len(pairs) / expected if expected else 0.0)
    value = claim.value if claim.value is not None else _peak_value(result)
    return EvidenceClaim(
        claim_id=claim_id,
        case_id=case.case_id,
        method_id=case.method_id,
        variable=case.variable,
        area=StudyArea(
            area_id="nea-" + "-".join(r.value for r in regions),
            name=", ".join(r.value for r in regions),
            regions=regions,
        ),
        period=StudyPeriod(start=window.start, end=window.end, local_zone=NEA_ZONE),
        value=value,
        unit=claim.unit,
        source_sha256=(source_sha256,),
        valid_fraction=round(min(fractions), 4),
        observation_status=_STATUS[result.verdict],
        causal_status=case.default_causal_status(),
    )


def _peak_value(result: VerificationResult) -> float | None:
    """A peak_region verdict reports 'west at 471'; read the number back."""
    observed = result.observed
    if isinstance(observed, str) and " at " in observed:
        return float(observed.rsplit(" at ", 1)[1])
    return None

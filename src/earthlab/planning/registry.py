"""The dataset registry the plan critic trusts: case assets joined with product profiles.

A plan names datasets and claims their metadata. The critic never trusts those claims. It
takes coverage, valid fraction, product kind and publication delay from this registry,
which is built from the case files in config/cases, the product profiles in
config/planning/products.yaml and the download manifests in each case data folder.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field

from earthlab.cases.loader import CaseFile, load_case
from earthlab.cases.models import SourceAsset, StudyPeriod
from earthlab.contracts import Strict
from earthlab.digest import payload_digest
from earthlab.planning.sources import DataCandidate, PeriodFraction
from earthlab.planning.vocab import ProductKind

CASES_DIR = Path("config/cases")
PROFILES_FILE = Path("config/planning/products.yaml")


class ProductProfile(Strict):
    """What a case asset does not record: product kind, delay and data handling."""

    product_kind: ProductKind
    availability_latency_hours: float = Field(ge=0)
    native_variables: tuple[str, ...] = Field(min_length=1)
    missing_data_policy: str = Field(min_length=1)
    bands: tuple[str, ...] = ()
    normalization: str | None = None
    quality_mask: str | None = None


class _ProfileFile(Strict):
    products: dict[str, ProductProfile]


@dataclass(frozen=True)
class Registry:
    """Dataset records by ID. `assets` holds the case asset for catalogue checks."""

    candidates: Mapping[str, DataCandidate]
    assets: Mapping[str, SourceAsset] = field(default_factory=dict)

    def with_candidates(self, extra: Iterable[DataCandidate]) -> Registry:
        """A registry with more records; an ID that already exists is an error."""
        merged = dict(self.candidates)
        for candidate in extra:
            if candidate.dataset_id in merged:
                raise ValueError(f"dataset {candidate.dataset_id} is already registered")
            merged[candidate.dataset_id] = candidate
        return Registry(candidates=merged, assets=self.assets)

    def digest(self) -> str:
        return payload_digest(
            {k: self.candidates[k].model_dump(mode="json") for k in sorted(self.candidates)}
        )


def _next_month(start: datetime) -> datetime:
    year, month = divmod(start.month, 12)
    return start.replace(year=start.year + year, month=month + 1)


def manifest_fractions(manifest: Mapping[str, Any]) -> tuple[PeriodFraction, ...]:
    """Per-month valid land fraction from a download manifest's reference counts."""
    parts = []
    for item in manifest.get("files", ()):
        ref, month = item.get("reference"), item.get("month")
        if not ref or not month or not ref.get("land_pixels"):
            continue
        start = datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)
        period = StudyPeriod(start=start, end=_next_month(start), local_zone="UTC")
        fraction = ref["valid_land_pixels"] / ref["land_pixels"]
        parts.append(PeriodFraction(period=period, valid_fraction=round(fraction, 4)))
    return tuple(parts)


def candidate_from_asset(
    asset: SourceAsset, profile: ProductProfile, fractions: tuple[PeriodFraction, ...] = ()
) -> DataCandidate:
    return DataCandidate(
        dataset_id=asset.asset_id,
        product=asset.product,
        version=asset.version,
        publisher=asset.provider,
        uri=asset.url,
        licence=asset.licence,
        availability=asset.availability,
        sha256=asset.sha256,
        quantity=asset.variable,
        units=asset.units,
        crs=asset.crs,
        resolution_m=asset.resolution_m,
        coverage=asset.coverage,
        extent=asset.extent,
        regions=asset.regions,
        quality_policy=asset.quality_policy,
        valid_fraction=min((f.valid_fraction for f in fractions), default=None),
        valid_fraction_by_period=fractions,
        **profile.model_dump(),
    )


def candidates_from_case(
    case_file: CaseFile,
    profiles: Mapping[str, ProductProfile],
    manifests: Mapping[str, Mapping[str, Any]] | None = None,
) -> tuple[DataCandidate, ...]:
    """Pure: the dataset records for one case file. A product needs a profile."""
    manifests = manifests or {}
    out = []
    for asset_id in sorted(case_file.assets):
        asset = case_file.assets[asset_id]
        if asset.product not in profiles:
            raise ValueError(f"product {asset.product} has no planning profile")
        fractions = manifest_fractions(manifests.get(asset_id, {}))
        out.append(candidate_from_asset(asset, profiles[asset.product], fractions))
    return tuple(out)


def load_profiles(path: Path) -> dict[str, ProductProfile]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return dict(_ProfileFile.model_validate(raw).products)


def _manifests(case_file: CaseFile, root: Path) -> dict[str, dict[str, Any]]:
    folder = case_file.case.data_dir
    found: dict[str, dict[str, Any]] = {}
    for asset_id in case_file.assets if folder else ():
        path = root / str(folder) / f"{asset_id}.manifest.json"
        if path.is_file():
            found[asset_id] = json.loads(path.read_text(encoding="utf-8"))
    return found


def load_registry(root: Path) -> Registry:
    """Every case file under config/cases, joined with profiles and manifests."""
    profiles = load_profiles(root / PROFILES_FILE)
    candidates: dict[str, DataCandidate] = {}
    assets: dict[str, SourceAsset] = {}
    for path in sorted((root / CASES_DIR).glob("*.yaml")):
        case_file = load_case(path, root)
        for candidate in candidates_from_case(case_file, profiles, _manifests(case_file, root)):
            if candidate.dataset_id in candidates:
                raise ValueError(f"dataset {candidate.dataset_id} is registered twice")
            candidates[candidate.dataset_id] = candidate
        assets.update(case_file.assets)
    return Registry(candidates=candidates, assets=assets)

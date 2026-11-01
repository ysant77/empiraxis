"""Catalogue facts for products the audit reports on without a manifest.

Two pinned assets have a provenance file. Four public products have no local copy. The facts
below come from the product pages and from the pinned provenance. A catalogue entry grants
no permission to download.
"""

from __future__ import annotations

from typing import Any

from earthlab.harness.suitability import DatasetSuitabilityV1, LocalState, VariableSpec

CHAT_ONLY = "chat_only_unsigned"
_NOT_LOCAL: dict[str, dict[str, Any]] = {
    "maiac-mcd19a2": dict(
        revision="v6.1", url="https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MCD19A2",
        variables=(VariableSpec(name="aod_055", unit="1"),), cadence=24.0, support="grid_cell",
        kind="observation", optical=True, license="NASA Earth science data",
        notes=("AOD is a column quantity, not ground PM2.5", "clouds mask many days"),
    ),
    "smap-spl3smp-e": dict(
        revision="SPL3SMP_E", url="https://nsidc.org/data/smap/data",
        variables=(VariableSpec(name="soil_moisture", unit="m3 m-3"),), cadence=24.0,
        support="grid_cell", kind="observation", optical=False, license="NASA Earth science data",
        notes=("9 km product; March 2015 onward",),
    ),
    "emit-l2a-rfl": dict(
        revision="001", url="https://doi.org/10.5067/EMIT/EMITL2ARFL.001",
        variables=(VariableSpec(name="reflectance", unit="1"),), cadence=None, support="swath",
        kind="observation", optical=True, license="NASA Earth science data",
        notes=("hyperspectral, from August 2022: no 2015 haze coverage",),
    ),
    "cams-archived-forecast": dict(
        revision="unpinned", url="https://ads.atmosphere.copernicus.eu/",
        variables=(VariableSpec(name="aerosol", unit="unknown"),), cadence=None,
        support="grid_cell", kind="issued_forecast", optical=False, license="CAMS licence",
        notes=("not approved; needs a pinned run_issue_time and retrospective availability",),
    ),
}  # fmt: skip
NOT_ACQUIRED = tuple(_NOT_LOCAL)


def _absent(key: str) -> DatasetSuitabilityV1:
    f = _NOT_LOCAL[key]
    return DatasetSuitabilityV1(
        dataset_id=key, revision=f["revision"], source_url=f["url"], variables=f["variables"],
        cadence_hours=f["cadence"], spatial_support=f["support"], event_time="unknown",
        valid_time="unknown", data_kind=f["kind"], availability="unknown", optical=f["optical"],
        license=f["license"], local_state="not_acquired", permission="needs_approval",
        notes=f["notes"],
    )  # fmt: skip


def _asset(kind: str, prov: dict[str, Any], state: LocalState) -> DatasetSuitabilityV1:
    weights = kind == "weights"
    spec = VariableSpec(name="model_weights" if weights else "hls_reflectance_6band", unit="1")
    notes = (
        "no signed ResourceApprovalV1; approval was a chat statement",
        "transfer was a direct pinned download, not through the broker",
        "weights were not loaded" if weights else "multispectral, not hyperspectral",
    )
    return DatasetSuitabilityV1(
        dataset_id="prithvi-burnscars-weights" if weights else "hls-burn-scars-chips",
        revision=prov["revision"][:8], source_url=prov["url"], variables=(spec,),
        spatial_support="scene", event_time="unknown", valid_time="unknown",
        data_kind="weights" if weights else "observation", availability="unknown",
        optical=not weights, license=prov["license_terms"], bytes_estimate=prov["bytes"],
        local_state=state, permission=CHAT_ONLY, notes=notes,
        local_sha256=prov["sha256"] if state == "verified" else None,
        allowed_evidence=("method_input",),
    )  # fmt: skip


def unacquired_profile(key: str, prov: dict[str, Any], state: LocalState) -> DatasetSuitabilityV1:
    """A profile for a pinned asset (key weights or chips) or for a product not on disk."""
    if key in ("weights", "chips"):
        return _asset(key, prov, state)
    return _absent(key)

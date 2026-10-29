"""ERA5 hourly reanalysis for the approved 2015 haze H1 request only, through cdsapi.

The module knows one request: the H1 variables, all 24 UTC hours, the meteorology box
and September-October 2015. Anything outside it is refused before a client is built.
Each month is one CDS request. Its announced size is checked against the remaining
byte cap before any byte moves, and the written file is checked again after.
Credentials are read only by cdsapi's own lookup and never appear in an error.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol

from earthlab.acquire.gate import CapExceeded
from earthlab.cases.models import BoundingBox
from earthlab.digest import file_digest

SINGLE_LEVELS = "reanalysis-era5-single-levels"
PRESSURE_LEVELS = "reanalysis-era5-pressure-levels"
PRODUCTS = {f"ERA5/{SINGLE_LEVELS}": SINGLE_LEVELS, f"ERA5/{PRESSURE_LEVELS}": PRESSURE_LEVELS}
H1_BOX = BoundingBox(min_lon=95.0, min_lat=-6.0, max_lon=118.0, max_lat=4.0)
H1_START = datetime(2015, 9, 1, tzinfo=UTC)
H1_END = datetime(2015, 11, 1, tzinfo=UTC)
H1_VARIABLES: dict[str, tuple[str, ...]] = {
    SINGLE_LEVELS: (
        "10m_u_component_of_wind",
        "10m_v_component_of_wind",
        "total_precipitation",
        "boundary_layer_height",
    ),
    PRESSURE_LEVELS: ("u_component_of_wind", "v_component_of_wind"),
}
H1_LEVELS: dict[str, tuple[int, ...]] = {SINGLE_LEVELS: (), PRESSURE_LEVELS: (850,)}
HOURS = tuple(f"{hour:02d}:00" for hour in range(24))
GRID_DEG = 0.25
GRIB_BYTES_PER_VALUE = 2  # ERA5 GRIB fields are packed at 16 bits
GRIB_HEADER_BYTES = 200  # per message (one field at one hour), an upper estimate
SHORT_NAMES = {SINGLE_LEVELS: "sl", PRESSURE_LEVELS: "pl"}


class Era5Refused(PermissionError):
    """The request lies outside the approved H1 request; nothing was sent."""


class Era5CredentialsMissing(RuntimeError):
    """cdsapi found no usable configuration. The message never holds a secret."""


class CdsResult(Protocol):
    @property
    def content_length(self) -> int: ...

    def download(self, target: str) -> str: ...


class CdsClient(Protocol):
    def retrieve(self, name: str, request: dict[str, Any]) -> CdsResult: ...


def dataset_of(product: str) -> str:
    if product not in PRODUCTS:
        raise Era5Refused(f"{product} is not an approved ERA5 product")
    return PRODUCTS[product]


def check_h1(
    dataset: str,
    variables: tuple[str, ...],
    levels: tuple[int, ...],
    box: BoundingBox,
    start: datetime,
    end: datetime,
) -> None:
    """Raise Era5Refused with every reason the request differs from the H1 request."""
    reasons: list[str] = []
    if dataset not in H1_VARIABLES:
        reasons.append(f"dataset {dataset} is not approved")
    else:
        if not variables or set(variables) - set(H1_VARIABLES[dataset]):
            reasons.append(f"variables {sorted(variables)} are not the approved set")
        if set(levels) != set(H1_LEVELS[dataset]):
            reasons.append(f"pressure levels {sorted(levels)} are not approved")
    if box != H1_BOX:
        reasons.append("area is not the approved meteorology box")
    if start < H1_START or end > H1_END or end <= start:
        reasons.append("period lies outside 2015-09-01 to 2015-11-01 UTC")
    if any((t.hour, t.minute, t.second, t.microsecond) != (0, 0, 0, 0) for t in (start, end)):
        reasons.append("period must start and end at 00:00 UTC (whole days, all 24 hours)")
    if reasons:
        raise Era5Refused("; ".join(reasons))


def _grid_points(box: BoundingBox) -> int:
    lon = round((box.max_lon - box.min_lon) / GRID_DEG) + 1
    lat = round((box.max_lat - box.min_lat) / GRID_DEG) + 1
    return lon * lat


def expected_bytes(
    variables: tuple[str, ...], levels: tuple[int, ...], box: BoundingBox, hours: int
) -> int:
    """Estimated GRIB size: grid points x hours x fields x 2 bytes, plus message headers."""
    fields = len(variables) * max(1, len(levels))
    return hours * fields * (_grid_points(box) * GRIB_BYTES_PER_VALUE + GRIB_HEADER_BYTES)


def monthly_requests(
    variables: tuple[str, ...],
    levels: tuple[int, ...],
    box: BoundingBox,
    start: datetime,
    end: datetime,
) -> list[tuple[date, dict[str, Any]]]:
    """One CDS request per UTC calendar month, listing only days inside [start, end)."""
    days: dict[date, list[str]] = {}
    moment = start
    while moment < end:
        days.setdefault(moment.date().replace(day=1), []).append(f"{moment.day:02d}")
        moment += timedelta(days=1)
    requests: list[tuple[date, dict[str, Any]]] = []
    for month, month_days in days.items():
        request: dict[str, Any] = {
            "product_type": ["reanalysis"],
            "variable": list(variables),
            "year": [f"{month.year}"],
            "month": [f"{month.month:02d}"],
            "day": month_days,
            "time": list(HOURS),
            "area": [box.max_lat, box.min_lon, box.min_lat, box.max_lon],  # N, W, S, E
            "data_format": "grib",
            "download_format": "unarchived",
        }
        if levels:
            request["pressure_level"] = [str(level) for level in levels]
        requests.append((month, request))
    return requests


def fetch_month(
    client: CdsClient, dataset: str, request: dict[str, Any], path: Path, budget: int
) -> tuple[str, int]:
    """Retrieve one month into path; return (sha256, bytes). Refuse before download if big."""
    try:
        result = client.retrieve(dataset, request)
        announced = int(result.content_length)
    except Exception as exc:
        raise RuntimeError(
            f"CDS request for {dataset} {request['year'][0]}-{request['month'][0]} failed "
            f"({type(exc).__name__}); check the dataset licence acceptance and the CDS queue"
        ) from None
    if announced > budget:
        raise CapExceeded(f"{path.name}: CDS announced {announced} bytes; {budget} remain")
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        result.download(str(tmp))
        size = tmp.stat().st_size
        if size > budget or size != announced:
            raise CapExceeded(f"{path.name}: got {size} bytes, announced {announced}")
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise
    tmp.replace(path)
    return file_digest(path), size


def month_file(dataset: str, month: date) -> str:
    return f"era5_{SHORT_NAMES[dataset]}_{month:%Y_%m}.grib"


def client_from_config(factory: Callable[[], Any] | None = None) -> CdsClient:
    """A cdsapi client from its own config lookup (~/.cdsapirc or CDSAPI_URL/CDSAPI_KEY)."""
    try:
        if factory is None:
            import cdsapi  # optional extra: uv sync --extra acquire

            factory = cdsapi.Client
        client: CdsClient = factory()
    except Exception:
        raise Era5CredentialsMissing(
            "CDS credentials not found or incomplete; configure ~/.cdsapirc"
        ) from None
    return client

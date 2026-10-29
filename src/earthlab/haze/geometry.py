"""Source boxes and receptor geometry for the 2015 haze case.

The boxes are the analysis choices in the H1 design and match the approved FIRMS
download boxes. Bearings and distances run from the receptor to each box centre.
"""

from __future__ import annotations

from pydantic import Field

from earthlab.cases.models import BoundingBox
from earthlab.contracts import Strict
from earthlab.haze.wind import great_circle_km, initial_bearing, normalise_bearing

RECEPTOR_LAT, RECEPTOR_LON = 1.35, 103.82  # Singapore
REFERENCE_SPEED_MS = 5.0
CORRIDOR_PAD_DEG = 0.25


class SourceBox(Strict):
    box_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]*$")
    name: str
    box: BoundingBox

    @property
    def centre(self) -> tuple[float, float]:
        """(lat, lon) of the box centre."""
        return (self.box.min_lat + self.box.max_lat) / 2, (self.box.min_lon + self.box.max_lon) / 2

    @property
    def bearing_deg(self) -> float:
        """Bearing from the receptor to the box centre: the wind-from direction to test."""
        return initial_bearing(RECEPTOR_LAT, RECEPTOR_LON, *self.centre)

    @property
    def distance_km(self) -> float:
        return great_circle_km(RECEPTOR_LAT, RECEPTOR_LON, *self.centre)


class GeometryRow(Strict):
    box_id: str
    name: str
    bearing_deg: float
    distance_km: float
    sector_from_deg: tuple[float, float]
    straight_line_lag_h_at_5ms: float


H1_SOURCE_BOXES: tuple[SourceBox, ...] = (
    SourceBox(
        box_id="box-a",
        name="Riau / central Sumatra",
        box=BoundingBox(min_lon=100.0, min_lat=-1.5, max_lon=103.5, max_lat=2.0),
    ),
    SourceBox(
        box_id="box-b",
        name="Jambi / South Sumatra",
        box=BoundingBox(min_lon=102.5, min_lat=-4.5, max_lon=106.5, max_lat=-1.0),
    ),
    SourceBox(
        box_id="box-c",
        name="Central / West Kalimantan",
        box=BoundingBox(min_lon=108.5, min_lat=-3.5, max_lon=115.0, max_lat=1.0),
    ),
)


def geometry_row(source: SourceBox, tolerance_deg: float) -> GeometryRow:
    bearing = source.bearing_deg
    return GeometryRow(
        box_id=source.box_id,
        name=source.name,
        bearing_deg=round(bearing, 1),
        distance_km=round(source.distance_km, 1),
        sector_from_deg=(
            round(normalise_bearing(bearing - tolerance_deg), 1),
            round(normalise_bearing(bearing + tolerance_deg), 1),
        ),
        straight_line_lag_h_at_5ms=round(source.distance_km / (REFERENCE_SPEED_MS * 3.6), 1),
    )


def corridor(source: SourceBox) -> BoundingBox:
    """The box spanning the source centre and the receptor, padded by one grid cell."""
    lat, lon = source.centre
    return BoundingBox(
        min_lon=min(lon, RECEPTOR_LON) - CORRIDOR_PAD_DEG,
        min_lat=min(lat, RECEPTOR_LAT) - CORRIDOR_PAD_DEG,
        max_lon=max(lon, RECEPTOR_LON) + CORRIDOR_PAD_DEG,
        max_lat=max(lat, RECEPTOR_LAT) + CORRIDOR_PAD_DEG,
    )

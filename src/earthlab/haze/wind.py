"""Deterministic wind geometry: wind-from bearings, U/V components and sector checks.

Conventions. A meteorological bearing is the direction the wind blows FROM, in degrees
clockwise from true north. U is the eastward and V the northward component of the
vector the air moves TO. A bearing is always reported in [0, 360). A calm wind has a
speed but no direction.
"""

from __future__ import annotations

import math

from pydantic import Field

from earthlab.contracts import Strict

CALM_SPEED_MS = 0.5
EARTH_RADIUS_KM = 6371.0088


class WindReading(Strict):
    speed_ms: float = Field(ge=0)
    from_deg: float | None = Field(default=None, ge=0, lt=360)

    @property
    def is_calm(self) -> bool:
        return self.from_deg is None


def normalise_bearing(degrees: float) -> float:
    """Wrap any finite angle into [0, 360); 360 and -0.0 both become 0."""
    if not math.isfinite(degrees):
        raise ValueError(f"bearing must be finite, got {degrees!r}")
    wrapped = degrees % 360.0
    return 0.0 if wrapped >= 360.0 or wrapped == 0.0 else wrapped


def downwind_unit_vector(from_deg: float) -> tuple[float, float]:
    """(east, north) unit vector of the direction the air moves for a wind-from bearing."""
    theta = math.radians(normalise_bearing(from_deg))
    return _clean(-math.sin(theta)), _clean(-math.cos(theta))


def uv_from_wind(speed_ms: float, from_deg: float) -> tuple[float, float]:
    """U and V components (m/s) of a wind with a given speed and wind-from bearing."""
    if not math.isfinite(speed_ms) or speed_ms < 0:
        raise ValueError(f"speed must be finite and not negative, got {speed_ms!r}")
    east, north = downwind_unit_vector(from_deg)
    return speed_ms * east, speed_ms * north


def wind_from_uv(u_ms: float, v_ms: float, calm_ms: float = CALM_SPEED_MS) -> WindReading:
    """Speed and wind-from bearing of U/V components; no bearing below the calm speed."""
    if not (math.isfinite(u_ms) and math.isfinite(v_ms)):
        raise ValueError("u and v must be finite")
    speed = math.hypot(u_ms, v_ms)
    if speed < calm_ms:
        return WindReading(speed_ms=speed, from_deg=None)
    return WindReading(speed_ms=speed, from_deg=normalise_bearing(_atan2_bearing(-u_ms, -v_ms)))


def angular_difference(a_deg: float, b_deg: float) -> float:
    """Smallest absolute angle between two bearings, in [0, 180]."""
    diff = abs(normalise_bearing(a_deg) - normalise_bearing(b_deg))
    return min(diff, 360.0 - diff)


def initial_bearing(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle initial bearing from point 1 to point 2, degrees in [0, 360)."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    x = math.sin(dlon) * math.cos(phi2)
    y = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlon)
    return normalise_bearing(_atan2_bearing(x, y))


def great_circle_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Haversine distance on a spherical Earth, in kilometres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    half = (
        math.sin((phi2 - phi1) / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(math.radians(lon2 - lon1) / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(min(1.0, half)))


def blows_from_source(
    reading: WindReading, source_bearing_deg: float, tolerance_deg: float
) -> bool:
    """True if the wind comes from within tolerance of the receptor-to-source bearing.

    A calm wind is never in sector. This is a geometry test only: it says nothing about
    how much smoke, if any, arrives.
    """
    if not 0 <= tolerance_deg <= 180:
        raise ValueError("tolerance must be between 0 and 180 degrees")
    if reading.from_deg is None:
        return False
    return angular_difference(reading.from_deg, source_bearing_deg) <= tolerance_deg


def _atan2_bearing(east: float, north: float) -> float:
    return math.degrees(math.atan2(east, north))


def _clean(value: float, eps: float = 1e-12) -> float:
    """Remove floating-point dust so exact cardinal directions give exact components."""
    return 0.0 if abs(value) < eps else value

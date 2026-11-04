"""When each M5 source can be read at a historical issue time. Rules, not measurements.

Latencies are nominal values from product documentation, not measured per file. Any source
marked hindsight_only never enters an issue-time-valid feature set. The assumptions are listed
so the protocol can state them and a reader can change them in one place.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from earthlab.m5.contracts import Availability

# source key -> (basis, nominal latency hours or None, documentation note)
RULES: dict[str, tuple[str, float | None, str]] = {
    "nea_pm25": ("nominal_latency", 2.0, "E1 rule: newest usable value is T-2 h"),
    "firms_modis_sp": ("nominal_latency", 3.0, "assumed pass+3 h; standard product not real time"),
    "imerg_early": ("nominal_latency", 4.0, "IMERG Early nominal latency about 4 h"),
    "imerg_late": ("nominal_latency", 14.0, "IMERG Late nominal latency about 14 h"),
    "imerg_final": ("nominal_latency", 2556.0, "IMERG Final about 3.5 months (106.5 days)"),
    "smap_l3": ("nominal_latency", 50.0, "SMAP L3 nominal 48-50 h; no use at a 6 h horizon"),
    "era5": ("hindsight_only", None, "reanalysis made later; not readable at the issue time"),
    "mcd64a1": ("hindsight_only", None, "monthly map, published after the month"),
    "hls_archive": ("hindsight_only", None, "archive reprocessing; no per-scene release time"),
    "maiac_061": ("hindsight_only", None, "reprocessed collection; no per-file release time"),
}


def availability_for(source: str, observation_end_utc: datetime) -> Availability:
    """The availability record for a source observation that ends at the given time."""
    basis, latency, _ = RULES[source]
    if basis == "hindsight_only":
        return Availability(observation_end_utc=observation_end_utc, basis="hindsight_only")
    return Availability(observation_end_utc=observation_end_utc, basis="nominal_latency",
                        assumed_latency_hours=latency)  # fmt: skip


class LeakError(ValueError):
    """A feature used data that was not readable at the issue time."""


def assert_issue_time_valid(
    source: str, observation_end_utc: datetime, issue_utc: datetime
) -> None:
    """Raise LeakError unless the source's rule makes the value visible at the issue time."""
    if not availability_for(source, observation_end_utc).usable_at(issue_utc):
        raise LeakError(f"{source} value ending {observation_end_utc:%Y-%m-%d %H:%MZ} "
                        f"is not readable at {issue_utc:%Y-%m-%d %H:%MZ}")  # fmt: skip


def latest_visible_end(source: str, issue_utc: datetime) -> datetime:
    """Newest observation end that the source's rule allows at the issue time."""
    basis, latency, _ = RULES[source]
    if basis == "hindsight_only" or latency is None:
        raise LeakError(f"{source} is hindsight only; no observation is visible at issue time")
    return issue_utc - timedelta(hours=latency)

"""Implementor development tasks (dev v1): the same task and frozen checks for every worker.

Each task asks for one new module under src/earthlab/implement/workspace/, which is not
in the repository; a worker's patch creates it. The acceptance checks in acceptance.py are
frozen by hash. This is a development set, written by the developer, not a held-out set.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from earthlab.digest import file_digest
from earthlab.implement.contracts import ImplementationTaskV1

ACCEPTANCE_FILE = Path(__file__).with_name("acceptance.py")
# Re-freeze only on purpose: a changed check changes every worker's score.
ACCEPTANCE_SHA256 = "4adbdaf39a3fc17aa63b5da31a688ad3904ef9ea7dfbd9922edc60280717f642"
WORKSPACE = "src/earthlab/implement/workspace"
FIXED_TEST = "tests/test_implementor_acceptance.py"


@dataclass(frozen=True)
class TaskSpec:
    task: ImplementationTaskV1
    check: str  # key in acceptance.CHECKS
    interface: str  # the exact signatures the worker must provide


def _task(task_id: str, method: str, target: str, requirements: list[str]) -> ImplementationTaskV1:
    return ImplementationTaskV1.model_validate(
        {
            "task_id": task_id,
            "parent_task_id": "implementor-dev-v1",
            "task_kind": "code_patch",
            "method_ref": method,
            "allowed_paths": [f"{WORKSPACE}/{target}"],
            "read_only_sources": ["src/earthlab/implement/acceptance.py"],
            "requirements": requirements,
            "fixed_tests": [FIXED_TEST],
            "data_classification": "synthetic_development",
        }
    )


TASKS: dict[str, TaskSpec] = {
    "dev-wind-vector": TaskSpec(
        _task(
            "dev-wind-vector",
            "wind-vector-geometry",
            "wind.py",
            [
                "Convert a meteorological wind-FROM bearing and a speed to the (u, v) vector "
                "of the air moving TO; u eastward, v northward",
                "A calm wind (speed 0) has the zero vector; refuse negative or non-finite input "
                "with ValueError",
                "Give the downwind bearing in [0, 360)",
            ],
        ),
        "wind_vector",
        "def wind_vector(from_deg: float, speed_ms: float) -> tuple[float, float]\n"
        "def downwind_bearing(from_deg: float) -> float",
    ),
    "dev-nea-hour-utc": TaskSpec(
        _task(
            "dev-nea-hour-utc",
            "nea-hour-convention",
            "timebase.py",
            [
                "Map a naive Singapore-time NEA hourly label to the UTC interval it covers",
                "Support hour_ending (01:00 covers 00:00-01:00) and hour_beginning labels",
                "Refuse a timezone-aware label with ValueError",
            ],
        ),
        "nea_hour_to_utc",
        "def nea_hour_to_utc(label: datetime, convention: str) -> tuple[datetime, datetime]",
    ),
    "dev-chronological-split": TaskSpec(
        _task(
            "dev-chronological-split",
            "chronological-split-embargo",
            "splits.py",
            [
                "Split samples in time order into train, validation and test index lists",
                "Drop samples that fall within the embargo after the previous part ends",
                "Provide split_leaks() that reports overlap and embargo violations",
                "Refuse fractions that leave no test part with ValueError",
            ],
        ),
        "chronological_split",
        "def chronological_split(times, train: float, validation: float, embargo: timedelta)"
        " -> dict[str, list[int]]\n"
        "def split_leaks(parts, times, embargo: timedelta) -> list[str]",
    ),
}


def acceptance_is_frozen() -> bool:
    return file_digest(ACCEPTANCE_FILE) == ACCEPTANCE_SHA256

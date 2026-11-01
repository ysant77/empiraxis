"""Typed records of experiment E1. A model proposes inside these menus; code validates.

No proposal has a field that can pass a check, skip a stage or read the test period. The
menus hold approved training values. They do not hold code.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from earthlab.contracts import Strict

LEARNING_RATES = (0.0003, 0.001, 0.003)
Outcome = Literal["adopt_candidate", "retain_baseline", "abstain"]
ARM_LABEL = "Issue-time replay with modelled availability"
LIMITATIONS = (
    "Non-operational research result.",
    "Historical evaluation. Not a forecast of any future date.",
    "Not for health, safety or travel decisions.",
    "PM2.5 is not PSI or AQI.",
    "PM2.5 concentration alone does not identify wildfire haze or its cause.",
)


class Requirements(Strict):
    """The PM's translation of the modeling objective."""

    primary_horizon_hours: int
    horizons_hours: tuple[int, ...] = Field(min_length=1, max_length=5)
    primary_metric: Literal["mae_skill_against_persistence"]
    must_exceed_persistence_lower_limit: bool
    max_candidates: int = Field(ge=1, le=3)
    abstain_when: str = Field(min_length=5, max_length=300)


class Assignment(Strict):
    """The Lead's method choice. These values set the real training job."""

    window_hours: Literal[24, 48, 96, 168]
    log_transform: bool
    architecture: Literal["gru", "tcn"]
    hidden: Literal[16, 32, 64]
    layers: Literal[1, 2]
    max_epochs: int = Field(ge=3, le=20)
    loss: Literal["mae", "huber"]
    reason: str = Field(min_length=5, max_length=400)


class Review(Strict):
    """The Lead's reading of the evaluator's table. One refinement at most."""

    action: Literal["finish", "refine"]
    change: Assignment | None = None
    reason: str = Field(min_length=5, max_length=400)


class Recommendation(Strict):
    outcome: Outcome
    model_id: str | None = Field(default=None, max_length=60)
    reason: str = Field(min_length=5, max_length=500)


class PmDecision(Strict):
    forward_to_human: bool
    note: str = Field(min_length=3, max_length=300)


class DataReport(Strict):
    """The Data Scientist's closing note. Facts come from the artifacts it references."""

    features_id: str = Field(max_length=40)
    concerns: tuple[str, ...] = Field(default=(), max_length=5)


class TrainArgs(Strict):
    learning_rate: float

    @field_validator("learning_rate")
    @classmethod
    def _menu(cls, value: float) -> float:
        if value not in LEARNING_RATES:
            raise ValueError(f"the learning rate must be one of {LEARNING_RATES}")
        return value


class FeatureArgs(Strict):
    window_hours: Literal[24, 48, 96, 168]
    log_transform: bool


class NoArgs(Strict):
    pass


class TrainingReport(Strict):
    model_id: str = Field(max_length=60)
    note: str = Field(min_length=3, max_length=300)

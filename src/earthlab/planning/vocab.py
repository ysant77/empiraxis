"""Closed vocabularies for investigation plans: intent, quantities, product kinds, methods.

Quantities reuse `ScientificVariable` and add plan-only quantities that no case uses yet
(wind vectors, emissions, dilution and deposition inputs, land-cover change). The values
of the two enums never overlap, so one string has one meaning.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from earthlab.cases.models import ApprovalAction, ScientificVariable


class ResearchIntent(StrEnum):
    """What kind of answer the plan aims for. Order is roughly by evidence demand.

    CAUSAL_INFERENCE is unsupported in this system unless a separate, validated
    attribution study establishes it; the critic never accepts it as plain evidence.
    """

    OBSERVATIONAL_SUMMARY = "observational_summary"
    ASSOCIATION = "association"
    TRANSPORT_PLAUSIBILITY = "transport_plausibility"
    RETROSPECTIVE_ESTIMATION = "retrospective_estimation"
    PROSPECTIVE_PREDICTION = "prospective_prediction"
    CAUSAL_INFERENCE = "causal_inference"


class PlanQuantity(StrEnum):
    """Quantities a plan may name that no ScientificCase uses yet (future-facing)."""

    WIND_VECTOR = "wind_vector"
    EMISSIONS = "emissions"
    BOUNDARY_LAYER_HEIGHT = "boundary_layer_height"
    PRECIPITATION = "precipitation"
    DEPOSITION = "deposition"
    LAND_COVER_CHANGE = "land_cover_change"
    AIR_QUALITY_INDEX = "air_quality_index"
    SURFACE_REFLECTANCE = "surface_reflectance"
    FUEL_MOISTURE = "fuel_moisture"


Quantity = ScientificVariable | PlanQuantity

V, Q = ScientificVariable, PlanQuantity
WIND_QUANTITIES: frozenset[Quantity] = frozenset({V.WIND_CONSISTENCY, Q.WIND_VECTOR})
# Inputs that give a PM2.5 estimate a physical basis beyond transport direction:
# a source term (emissions or fire proxies), dilution, removal, or upstream observations.
PM25_PHYSICAL_SUPPORT: frozenset[Quantity] = frozenset(
    {
        Q.EMISSIONS,
        V.ACTIVE_FIRE,
        V.BURNED_AREA,
        Q.BOUNDARY_LAYER_HEIGHT,
        Q.PRECIPITATION,
        Q.DEPOSITION,
        V.AIR_POLLUTION_OBSERVATION,
    }
)

ProductKind = Literal[
    "in_situ_observation",
    "satellite_retrieval",
    "reanalysis",
    "operational_forecast",
    "derived_product",
    "post_event_label",
]


class PlanAction(StrEnum):
    """Consequential actions outside the current ApprovalAction set (future-facing)."""

    TRAIN_MODEL = "train_model"
    DELETE_DATA = "delete_data"


ActionKind = ApprovalAction | PlanAction

MethodClass = Literal["deterministic", "statistical", "physical", "machine_learning"]
Technique = Literal[
    "summary_statistics",
    "area_sum",
    "lagged_association",
    "back_trajectory",
    "dispersion_model",
    "regression",
    "time_series_forecast",
    "image_segmentation",
]
SplitMethod = Literal[
    "none",
    "random_rows",
    "blocked_time",
    "forward_chaining",
    "spatial_blocks",
    "leave_one_event_out",
]
SampleUnit = Literal["hour", "day", "month", "pixel", "scene", "event"]
TIME_SERIES_UNITS: frozenset[SampleUnit] = frozenset({"hour", "day", "month"})
DataRole = Literal["input", "reference", "context"]
Compute = Literal["laptop_cpu", "local_gpu", "hosted"]

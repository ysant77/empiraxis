"""The declare_limitation tool: a typed, scorable way to abstain instead of guessing.

A limitation names one or more reason codes from a fixed list. The codes make an
abstention checkable by code: a benchmark can require a specific reason, and a vague
refusal does not pass.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from pydantic import Field

from earthlab.contracts import Strict
from earthlab.tools.registry import ToolSpec

DECLARE_TOOL = "declare_limitation"


class ReasonCode(StrEnum):
    NEEDS_INPUT = "needs_input"
    DATA_UNAVAILABLE = "data_unavailable"
    METHOD_NOT_IMPLEMENTED = "method_not_implemented"
    INSUFFICIENT_VALID_DATA = "insufficient_valid_data"
    NEEDS_APPROVAL = "needs_approval"
    CAUSATION_NOT_IDENTIFIABLE = "causation_not_identifiable"
    HOTSPOT_NOT_AREA = "hotspot_count_is_not_burned_area"
    LST_NOT_AIR_TEMPERATURE = "land_surface_temperature_is_not_air_temperature"
    DEFINITION_MISMATCH = "definition_mismatch"
    HINDCAST_NOT_RUN = "hindcast_not_run"
    OUT_OF_SCOPE = "out_of_scope"


_HELP = (
    "needs_input: a required value (for example a threshold) is missing; ask, do not choose. "
    "data_unavailable / method_not_implemented / needs_approval: from assess_case. "
    "insufficient_valid_data: the data exist but too few cells are valid (quality gate). "
    "causation_not_identifiable: observations alone cannot show a cause. "
    "hotspot_count_is_not_burned_area, land_surface_temperature_is_not_air_temperature, "
    "definition_mismatch: the question equates different quantities. "
    "hindcast_not_run: no executed holdout exists. out_of_scope: none of the above fits."
)


class LimitationArgs(Strict):
    reasons: list[ReasonCode] = Field(min_length=1, max_length=4, description=_HELP)
    explanation: str = Field(min_length=10, max_length=400, description="Plain words, no numbers.")


@dataclass
class LimitationLog:
    """Every declared limitation in order. Nothing is ever removed."""

    entries: list[LimitationArgs] = field(default_factory=list)

    def codes(self) -> set[ReasonCode]:
        return {code for entry in self.entries for code in entry.reasons}


def declare_limitation_spec(log: LimitationLog) -> ToolSpec:
    def handle(args: LimitationArgs) -> dict[str, Any]:
        log.entries.append(args)
        return {"recorded": True, "reasons": [r.value for r in args.reasons]}

    return ToolSpec(
        DECLARE_TOOL,
        "Declare that the question cannot be answered as asked, with typed reasons. Use it "
        "instead of guessing a value, a cause or a method the data cannot support.",
        LimitationArgs,
        handle,
    )

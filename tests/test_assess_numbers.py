"""Rule m41-v3: integer measurements in free text must come from the package."""

from __future__ import annotations

import pytest
from assess_fakes import ROOT

from earthlab.assess.checks import ungrounded_numbers
from earthlab.assess.contracts import EvidencePackageV1
from earthlab.assess.numbers import integer_measurements

PKG = EvidencePackageV1.model_validate_json(
    (ROOT / "examples" / "assess" / "packages" / "e-m5-handoff-v2.json").read_text()
)


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        ("skill is 45%", ["45%"]),  # fabricated percent
        ("MAE is 12 ug/m3 lower", ["12"]),  # fabricated value with a unit
        ("MAE of 29", ["29"]),  # metric word before the integer
        ("349 events in 2019", ["349"]),  # count that this package does not hold
        ("18 elevated hours", ["18"]),  # one adjective before the unit
        ("MAE of 31", []),  # 30.76 rounds to 31
        ("17 elevated days", []),  # t19.elev_days
        ("skill of -13%", []),  # -0.135 is -13.5%
        ("skill of -14%", []),
        ("R2 MAE above 55 is 17.267", []),  # threshold and a package decimal
        ("PM2.5 > 55", []),
        ("the 2019 season and T+6 with R2 and p15", []),  # years and identifiers
        ("on 2015-09-01 at 06:00", []),  # dates and times
        ("over 3 seasons in 2 regions", []),  # counts without a measurement unit
        ("MAE 30.761", []),  # decimal rule unchanged
        ("MAE 33.5", ["33.5"]),  # fabricated decimal
    ],
)
def test_integer_measurements_are_grounded(text: str, bad: list[str]) -> None:
    assert ungrounded_numbers([text], PKG) == bad


def test_years_are_not_measurements_without_a_unit() -> None:
    assert integer_measurements("in 2019 and 2015") == []
    assert integer_measurements("2019 days") == [(2019, False)]


def test_percent_flag() -> None:
    assert integer_measurements("share of 45%") == [(45, True)]
    assert integer_measurements("rate 45 days") == [(45, False)]


def test_m41_v3_fault_classes() -> None:
    """All-hour deterioration is not a subgroup fault; the elevated-hour case still is."""
    from earthlab.assess import policy
    from earthlab.assess.contracts import FaultClass

    folder = ROOT / "examples" / "assess" / "packages"
    a = EvidencePackageV1.model_validate_json((folder / "a-model-selection-m3.json").read_text())
    classes_e = {f.fault_class for f in policy.decide(PKG).flags}
    classes_a = {f.fault_class for f in policy.decide(a).flags}
    assert FaultClass.OVERALL_DETERIORATION in classes_e
    assert FaultClass.SUBGROUP_DETERIORATION not in classes_e
    assert FaultClass.SUBGROUP_DETERIORATION in classes_a
    assert policy.decide(PKG).policy == "m41-v3"

"""ScientificEvidencePackageV2 (version m5-evidence-5): the package with four availability classes.

m5-evidence-4 marked FIRMS standard processing and IMERG Early rain as `issue_time_valid`. No M5
source has a verified per-observation publication time. The latencies are nominal values. This
version replaces the two-class field with four classes and states what each one means. The v4
file, the v4 builder and every frozen M5 result stay as they were.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal, get_args

from pydantic import Field

from earthlab.haze.geometry import H1_SOURCE_BOXES, RECEPTOR_LAT, RECEPTOR_LON
from earthlab.m5 import evidence as V4
from earthlab.m5.availability import RULES

PACKAGE_VERSION = "m5-evidence-5"
SUPERSEDES = "m5-evidence-4"
AvailabilityClass = Literal[
    "verified_issue_time", "nominal_latency_assumed", "retrospective_only", "unknown"
]
CLASS_MEANING = {
    "verified_issue_time": "a publication time per observation was checked; no M5 source has this",
    "nominal_latency_assumed": "a nominal latency from documentation; not verified per observation",
    "retrospective_only": "made or reprocessed after the event; never usable at the issue time",
    "unknown": "availability at the issue time was not assessed",
}
NEW_SOURCES: dict[str, tuple[AvailabilityClass, str]] = {
    "firms_nrt": (
        "unknown",
        "FIRMS near-real-time feed: a different product from MODIS_SP, not compared in M5",
    ),
}
MODALITY_REASON = {
    "firms_modis_sp": "fire counts and FRP; nominal latency +3 h assumed, not verified",
    "imerg_early": "rung I1, 2015 only; nominal latency about 4 h assumed; no gain",
}
CORRECTION = (
    "Correction of m5-evidence-4 (2026-11-04): the label issue_time_valid there meant allowed "
    "under the nominal-latency rule. It did not mean verified. The m5-evidence-4 file is unchanged."
)


class SourceRuleV2(V4.Frozen):
    source: str
    basis: Literal["nominal_latency", "hindsight_only", "not_assessed"]
    latency_hours: float | None
    note: str
    availability_class: AvailabilityClass


class FeatureContractV2(V4.Frozen):
    name: str
    source: str
    definition: str
    unit: str
    availability_class: AvailabilityClass


class EvidencePackageV2(V4.Frozen):
    version: str
    supersedes: str
    correction: str
    class_meaning: dict[str, str]
    questions: dict[str, str]
    primary_question: str
    receptor: dict[str, float]
    source_boxes: dict[str, dict[str, float]]
    period: str
    protocol_sha256: dict[str, str]
    protocol_bc_sha256: dict[str, str]
    window_rule: str
    source_rules: list[SourceRuleV2]
    assets: list[V4.Asset]
    modalities: list[V4.Modality]
    features: list[FeatureContractV2]
    artifacts: list[V4.Artifact]
    baselines: dict[str, dict[str, float]]
    limitations: list[str]
    claims_not_made: list[str]
    package_sha256: str = Field(default="")


WINDOW_RULE = (
    "A feature window is allowed only if its newest observation end plus the source's nominal "
    "latency is at or before the issue time T. availability.assert_issue_time_valid checks this "
    "rule. The latencies are not verified per observation, so the rule does not show that a "
    "feature was available in real time."
)


def source_rules() -> list[SourceRuleV2]:
    out = []
    for source, (basis, hours, note) in RULES.items():
        klass: AvailabilityClass = (
            "retrospective_only" if basis == "hindsight_only" else "nominal_latency_assumed"
        )
        out.append(SourceRuleV2(source=source, basis=basis, latency_hours=hours, note=note,
                                availability_class=klass))  # fmt: skip
    for source, (klass, note) in NEW_SOURCES.items():
        out.append(SourceRuleV2(source=source, basis="not_assessed", latency_hours=None, note=note,
                                availability_class=klass))  # fmt: skip
    return out


def features(static: dict[str, Any], rules: list[SourceRuleV2]) -> list[FeatureContractV2]:
    by_source = {r.source: r.availability_class for r in rules}
    return [
        FeatureContractV2(name=f["name"], source=f["source"], definition=f["definition"],
                          unit=f["unit"], availability_class=by_source[f["source"]])
        for f in static["features"]
    ]  # fmt: skip


def modalities(static: dict[str, Any]) -> list[V4.Modality]:
    return [
        V4.Modality(**{**m, "reason": MODALITY_REASON.get(m["source"], m["reason"])})
        for m in static["modalities"]
    ]


def digest(pkg: EvidencePackageV2) -> str:
    return hashlib.sha256(pkg.model_dump_json(exclude={"package_sha256"}).encode()).hexdigest()


def verify(pkg: EvidencePackageV2) -> bool:
    return digest(pkg) == pkg.package_sha256


def _freeze(repo: Path, name: str) -> dict[str, str]:
    record: dict[str, str] = json.loads((repo / f"docs/m5/{name}.freeze.json").read_text())[
        "sha256"
    ]
    return record


def build(repo: Path) -> EvidencePackageV2:
    static = json.loads((repo / V4.STATIC).read_text())
    rules = source_rules()
    pkg = EvidencePackageV2(
        version=PACKAGE_VERSION,
        supersedes=SUPERSEDES,
        correction=CORRECTION,
        class_meaning={k: CLASS_MEANING[k] for k in get_args(AvailabilityClass)},
        questions=V4.questions_from(repo),
        primary_question="M5-A",
        receptor={"lat": RECEPTOR_LAT, "lon": RECEPTOR_LON},
        source_boxes={s.box_id: s.box.model_dump(mode="json") for s in H1_SOURCE_BOXES},
        period=static["period"],
        protocol_sha256=_freeze(repo, "protocol-v1"),
        protocol_bc_sha256=_freeze(repo, "protocol-bc"),
        window_rule=WINDOW_RULE,
        source_rules=rules,
        assets=V4.assets_from(repo),
        modalities=modalities(static),
        features=features(static, rules),
        artifacts=V4.artifacts_from(repo),
        baselines=V4.baselines_from(repo),
        limitations=static["limitations"]
        + ["No M5 source has a verified per-observation publication time (see class_meaning)."],
        claims_not_made=static["claims_not_made"],
    )
    return pkg.model_copy(update={"package_sha256": digest(pkg)})

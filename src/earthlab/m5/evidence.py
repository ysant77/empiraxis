"""ScientificEvidencePackageV1: an immutable hand-off of M5 evidence for the M4 council.

The package holds references, hashes and numbers read from committed M5 artifacts. It holds
no raw data. It keeps retrospective evidence apart from issue-time-valid inputs. It does not
grade itself: the numbers come from result files that deterministic runs wrote.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import ConfigDict, Field

from earthlab.contracts import Strict
from earthlab.haze.geometry import H1_SOURCE_BOXES, RECEPTOR_LAT, RECEPTOR_LON
from earthlab.m5.availability import RULES

PACKAGE_VERSION = "m5-evidence-3"
RECEIPT_DIR = "docs/m5/receipts"
RESULT_FILES = (
    "m5_ladder_stage_p",
    "m5_ladder_stage_t",
    "m5_i1_stage_p_2015",
    "m5_h1_stage_p",
    "m5_assoc_v1",
    "m5_event_rates",
    "m5_c_v1",
    "m5_c_v1.strict_v1",
    "m5_latency_sample",
)


class Frozen(Strict):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Asset(Frozen):
    receipt_file: str
    name: str
    dataset: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    bytes: int = Field(ge=0)


class SourceRule(Frozen):
    source: str
    basis: Literal["nominal_latency", "hindsight_only"]
    latency_hours: float | None
    note: str
    input_class: Literal["issue_time_valid", "retrospective_only"]


class Modality(Frozen):
    source: str
    status: Literal["used", "gated_out", "blocked", "not_assessed"]
    reason: str


class Artifact(Frozen):
    path: str
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class FeatureContract(Frozen):
    name: str
    source: str
    definition: str
    unit: str
    input_class: Literal["issue_time_valid", "retrospective_only"]


class EvidencePackage(Frozen):
    version: str
    questions: dict[str, str]
    primary_question: str
    receptor: dict[str, float]
    source_boxes: dict[str, dict[str, float]]
    period: str
    protocol_sha256: dict[str, str]
    protocol_bc_sha256: dict[str, str]
    window_rule: str
    source_rules: list[SourceRule]
    assets: list[Asset]
    modalities: list[Modality]
    features: list[FeatureContract]
    artifacts: list[Artifact]
    baselines: dict[str, dict[str, float]]
    limitations: list[str]
    claims_not_made: list[str]
    package_sha256: str = ""


STATIC = "config/m5/evidence-static.json"
WINDOW_RULE = (
    "A feature window is valid only if its newest observation end plus the source latency is "
    "at or before the issue time T. availability.assert_issue_time_valid checks this. "
    "IMERG Final (2556 h) and SMAP (50 h) are issue-time valid per source, but no recent-hours "
    "window at T+6 can use them; tests/test_m5_units_masks_availability.py covers IMERG Final."
)


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _rows(path: Path) -> list[dict[str, Any]]:
    if path.suffix == ".jsonl":
        return [json.loads(x) for x in path.read_text().splitlines() if x]
    raw = json.loads(path.read_text())
    return raw if isinstance(raw, list) else raw["files"]


def assets_from(repo: Path) -> list[Asset]:
    out: list[Asset] = []
    for path in sorted((repo / RECEIPT_DIR).iterdir()):
        for row in _rows(path):
            dataset = row["product"]["dataset_id"] if "product" in row else row["dataset"]
            name = row.get("receipt_id") or row["file"]
            out.append(
                Asset(
                    receipt_file=path.name,
                    name=name,
                    dataset=dataset,
                    sha256=row["sha256"],
                    bytes=row["bytes"],
                )
            )
    return out


def baselines_from(repo: Path) -> dict[str, dict[str, float]]:
    p = json.loads((repo / "docs/m5/results/m5_ladder_stage_p.json").read_text())
    i1 = json.loads((repo / "docs/m5/results/m5_i1_stage_p_2015.json").read_text())
    return {
        "stage_p_2015_mae": p["2015"]["mae"],
        "stage_p_2016_mae": p["2016"]["mae"],
        "stage_p_2015_i1_mae": i1["mae"],
    }


def questions_from(repo: Path) -> dict[str, str]:
    lines = (repo / "docs/m5/M5_RESEARCH_QUESTIONS.md").read_text().splitlines()
    found: dict[str, str] = {}
    for i, line in enumerate(lines):
        if line.startswith("## M5-"):
            found[line[3:7]] = next(x for x in lines[i + 1 :] if x.strip())
    return found


def build(repo: Path) -> EvidencePackage:
    freeze = json.loads((repo / "docs/m5/protocol-v1.freeze.json").read_text())
    static = json.loads((repo / STATIC).read_text())
    bc = json.loads((repo / "docs/m5/protocol-bc.freeze.json").read_text())
    pkg = EvidencePackage(
        version=PACKAGE_VERSION,
        questions=questions_from(repo),
        primary_question="M5-A",
        receptor={"lat": RECEPTOR_LAT, "lon": RECEPTOR_LON},
        source_boxes={s.box_id: s.box.model_dump(mode="json") for s in H1_SOURCE_BOXES},
        period=static["period"],
        protocol_sha256=freeze["sha256"],
        protocol_bc_sha256=bc["sha256"],
        window_rule=WINDOW_RULE,
        source_rules=rules(),
        assets=assets_from(repo),
        modalities=[Modality(**m) for m in static["modalities"]],
        features=[FeatureContract(**f) for f in static["features"]],
        artifacts=artifacts_from(repo),
        baselines=baselines_from(repo),
        limitations=static["limitations"],
        claims_not_made=static["claims_not_made"],
    )
    return pkg.model_copy(update={"package_sha256": _digest(pkg)})


def _digest(pkg: EvidencePackage) -> str:
    return hashlib.sha256(pkg.model_dump_json(exclude={"package_sha256"}).encode()).hexdigest()


def verify(pkg: EvidencePackage) -> bool:
    return _digest(pkg) == pkg.package_sha256


def rules() -> list[SourceRule]:
    out = []
    for source, (basis, hours, note) in RULES.items():
        klass = "retrospective_only" if basis == "hindsight_only" else "issue_time_valid"
        out.append(
            SourceRule(
                source=source, basis=basis, latency_hours=hours, note=note, input_class=klass
            )
        )
    return out


def artifacts_from(repo: Path) -> list[Artifact]:
    paths = [f"docs/m5/results/{n}.json" for n in RESULT_FILES]
    paths += ["docs/m5/M5_SCIENCE_REPORT.md", "docs/m5/layers_manifest.json"]
    return [Artifact(path=p, sha256=sha256_file(repo / p)) for p in paths]

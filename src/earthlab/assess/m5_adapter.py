"""Read an M5 evidence package (m5-evidence-1) into an M4.1 EvidencePackageV1.

M4.1 consumes the package that M5 wrote. It does not acquire or recompute M5 data. Every
result file that the adapter reads must match the SHA-256 that the M5 package records.

Availability rule for a T+6 hourly experiment (M4.1, Amendment 2): a source is issue-time
valid when M5 classes it so and its nominal latency is at most 24 hours. A source that M5
gated out or did not assess has unknown quality. A retrospective source is hindsight.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from typing import Any

from earthlab.assess.contracts import Availability, EvidencePackageV1

MAX_LATENCY_HOURS = 24.0
ROLE = {
    "nea_pm25": "observation",
    "firms_modis_sp": "observation",
    "era5": "reanalysis",
    "mcd64a1": "observation",
    "hls_archive": "observation",
}
Reader = Callable[[str], bytes]


class ArtifactMismatch(RuntimeError):
    """A file does not match the digest in the M5 package."""


def verified(read: Reader, path: str, artifacts: dict[str, str]) -> Any:
    raw = read(path)
    digest = hashlib.sha256(raw).hexdigest()
    if artifacts.get(path) != digest:
        raise ArtifactMismatch(f"{path}: {digest[:12]} is not the package digest")
    return json.loads(raw)


def availability(rule: dict[str, Any], status: str) -> Availability:
    if rule["input_class"] == "retrospective_only":
        return Availability.HINDSIGHT
    latency = rule.get("latency_hours")
    if latency is None or latency > MAX_LATENCY_HOURS:
        return Availability.HINDSIGHT
    if status in ("gated_out", "not_assessed", "blocked"):
        return Availability.UNKNOWN
    return Availability.ISSUE_TIME_VALID


def sources(m5: dict[str, Any], origin: str) -> list[dict[str, Any]]:
    status = {m["source"]: m["status"] for m in m5["modalities"]}
    out = []
    for rule in m5["source_rules"]:
        name = rule["source"]
        out.append(
            {
                "id": name,
                "dataset": f"{name} ({status.get(name, 'not listed')})",
                "role": ROLE.get(name, "estimate"),
                "availability": availability(rule, status.get(name, "not_assessed")).value,
                "latency_hours": rule.get("latency_hours"),
                "origin": origin,
            }
        )
    return out


def _fact(
    fid: str, statement: str, source: str, value: float, unit: str = "ug/m3"
) -> dict[str, Any]:
    return {
        "id": fid,
        "statement": statement,
        "value": round(value, 3),
        "unit": unit,
        "source": source,
    }


def facts(m5: dict[str, Any], stage_t: dict[str, Any]) -> list[dict[str, Any]]:
    b = m5["baselines"]
    out = [
        _fact(f"p15.{k}", f"2015 Stage P {k} MAE (blocked folds, no skill claim)", "m5_package", v)
        for k, v in b["stage_p_2015_mae"].items()
    ]
    out += [
        _fact(f"p16.{k}", f"2016 clean season Stage P {k} MAE", "m5_package", v)
        for k, v in b["stage_p_2016_mae"].items()
    ]
    out.append(
        _fact(
            "p15.I1",
            "2015 Stage P I1 (R2 + IMERG Early) MAE",
            "m5_package",
            b["stage_p_2015_i1_mae"]["I1"],
        )
    )
    s = stage_t["2019"]
    for rung in ("R0", "R1", "R2"):
        out.append(
            _fact(
                f"t19.{rung}.mae",
                f"2019 held-out {rung} MAE, all hours",
                "m5_stage_t",
                s["mae"][rung],
            )
        )
        out.append(
            _fact(
                f"t19.{rung}.mae_gt55",
                f"2019 held-out {rung} MAE above 55",
                "m5_stage_t",
                s["elevated_mae"][rung],
            )
        )
    p = s["paired"]["R2_vs_R1"]
    out += [
        _fact(
            "t19.R2_vs_R1.high",
            "R2 vs R1 all-hours paired skill, upper 95% bound",
            "m5_stage_t",
            p["high"],
            "",
        ),
        _fact(
            "t19.elev_days",
            "Elevated days in the 2019 season",
            "m5_stage_t",
            s["elevated_days"],
            "days",
        ),
    ]
    return out


def adapt(m5: dict[str, Any], read: Reader, commit: str) -> EvidencePackageV1:
    """Build package E from the M5 package and its hash-checked Stage T result."""
    artifacts = {a["path"]: a["sha256"] for a in m5["artifacts"]}
    stage_t_path = "docs/m5/results/m5_ladder_stage_t.json"
    stage_t = verified(read, stage_t_path, artifacts)
    origin = f"m5@{commit[:7]}:docs/m5/evidence/scientific_evidence_package_v1.json"
    srcs = [
        *sources(m5, origin),
        {
            "id": "m5_package",
            "dataset": m5["version"],
            "role": "derived",
            "availability": "hindsight",
            "origin": origin,
            "sha256": m5["package_sha256"],
        },
        {
            "id": "m5_stage_t",
            "dataset": "M5 Stage T results",
            "role": "evaluation",
            "availability": "hindsight",
            "origin": f"m5@{commit[:7]}:{stage_t_path}",
            "sha256": artifacts[stage_t_path],
        },
    ]
    return EvidencePackageV1.model_validate(
        {
            "package_id": "e-m5-handoff",
            "scenario": "design",
            "question": m5["questions"][m5["primary_question"]][:400],
            "study_area": "Singapore receptor and source boxes A, B, C",
            "interval": m5["period"],
            "target": "hourly PM2.5 at T+6, ug/m3",
            "acceptance_criteria": [
                "Only inputs available at issue time enter the prediction experiment.",
                "Inputs that M5 gated out or did not assess are excluded.",
                "No supported gain is claimed from Stage P or one season.",
            ],
            "sources": srcs,
            "facts": facts(m5, stage_t),
            "limitations": [*m5["limitations"], *m5["claims_not_made"]],
            "missing_inputs": [
                f"{m['source']}: {m['reason']}"
                for m in m5["modalities"]
                if m["status"] in ("not_assessed", "blocked")
            ],
            "allowed_decisions": [
                "proceed_with_limits",
                "request_validation",
                "request_data",
                "abstain",
                "adopt",
            ],
            "fixture": False,
        }
    )

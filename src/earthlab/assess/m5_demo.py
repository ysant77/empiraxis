"""Package e-m5-demo-v3: the merged M5 evidence for one council demonstration.

This package is outside the m41-v2 benchmark. It has no answer key and no score. The frozen
benchmark package e-m5-handoff-v2 (m5-evidence-2) does not change. M5 computed every number
here. The council reviews the numbers. It did not compute them.
"""

from __future__ import annotations

from typing import Any

from earthlab.assess import m5_adapter
from earthlab.assess.contracts import EvidencePackageV1

DEMO_ID = "e-m5-demo-v3"
M5C_PATH = "docs/m5/results/m5_c_v1.strict_v1.json"
SETTINGS = {
    "main": ("c19", "frozen M5-C run"),
    "sensitivity_firms_delay_24h": ("c19d24", "FIRMS delayed 24 h"),
    "diagnostic_season_rank_hindsight": ("c19rank", "season-rank check, hindsight"),
}
DEMO_LIMITS = [
    "Demonstration package outside the m41-v2 benchmark. It has no answer key and no score.",
    "M5 computed every number in this package. The council reviews them and computed none.",
    "FIRMS is the MODIS standard-product archive, not the near-real-time product. "
    "When each value was available at issue time is not known.",
    "ERA5 is retrospective reanalysis. M5 used it only for association in hindsight.",
    "HLS has 2.7% clear land on both pilot dates. SMAP has no recommended-quality retrieval "
    "in the study box. M5 gated out both.",
    "2019 is the test season of both Stage T and M5-C. It was reused and is not an "
    "independent test. M5-C holds one 2019 episode.",
    "Correction: M5 later replaced its issue_time_valid label (m5-evidence-5). No M5 source has "
    "a verified publication time per observation. NEA and IMERG Early availability is a nominal "
    "latency assumption, not verified.",
]


def m5c_facts(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Brier skill and its lower 95% bound for rungs C2 (lags) and C3 (lags + FIRMS)."""
    main = data["main"]
    out = [
        m5_adapter._fact("c19.episodes", "M5-C 2019: episodes", "m5_c", main["episodes"], ""),
        m5_adapter._fact("c19.events", "M5-C 2019: event issues", "m5_c", main["events"], ""),
    ]
    for key, (prefix, what) in SETTINGS.items():
        for rung, name in (("C2", "lags"), ("C3", "lags + FIRMS")):
            r = data[key][rung]
            label = r.get("label", "not labelled")
            out += [
                m5_adapter._fact(
                    f"{prefix}.{rung}.skill",
                    f"M5-C {what}, {rung} ({name}): Brier skill; frozen label {label}",
                    "m5_c",
                    r["brier_skill"],
                    "",
                ),
                m5_adapter._fact(
                    f"{prefix}.{rung}.skill_low",
                    "Same, lower 95% bound (week bootstrap, not episodes)",
                    "m5_c",
                    r["skill_ci"][0],
                    "",
                ),
            ]
    return out


def build(m5: dict[str, Any], read: m5_adapter.Reader, commit: str) -> EvidencePackageV1:
    """The adapter output for the merged M5 package, plus the hash-checked M5-C result."""
    body = m5_adapter.adapt(m5, read, commit).model_dump(mode="json")
    artifacts = {a["path"]: a["sha256"] for a in m5["artifacts"]}
    m5c = m5_adapter.verified(read, M5C_PATH, artifacts)["data"]
    body["package_id"] = DEMO_ID
    body["sources"].append(
        {
            "id": "m5_c",
            "dataset": "M5-C event result, held-out 2019 (strict export)",
            "role": "evaluation",
            "availability": "hindsight",
            "origin": f"m5@{commit[:7]}:{M5C_PATH}",
            "sha256": artifacts[M5C_PATH],
        }
    )
    body["facts"] += m5c_facts(m5c)
    body["limitations"] += DEMO_LIMITS
    return EvidencePackageV1.model_validate(body)

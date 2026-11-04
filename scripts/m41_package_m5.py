"""M4.1 packages D and E, built from M5 files at pinned commits. The M5 worktree is not touched."""

from __future__ import annotations

import json
from typing import Any

from m41_package_store import LIMITS, M5_PATHS, Store, fact, src

from earthlab.assess.contracts import EvidencePackageV1
from earthlab.assess.m5_adapter import adapt

RUNGS = ("R0", "R1", "R2", "R3a")
HEAD_D: dict[str, Any] = {
    "package_id": "d-multisource-design-m5",
    "scenario": "design",
    "question": "Which ERA5, FIRMS, IMERG, HLS and SMAP inputs are suitable for an "
    "issue-time-valid PM2.5 T+6 prediction experiment, and what experiment should run next?",
    "study_area": "Singapore and three upwind boxes",
    "interval": "2015 to 2019 seasons",
    "target": "hourly PM2.5 at T+6, ug/m3",
    "acceptance_criteria": [
        "Only inputs available at issue time enter the prediction experiment.",
        "Inputs that failed quality checks are excluded.",
        "The elevated-hour signal is not claimed as a supported gain.",
    ],
    "limitations": LIMITS,
    "missing_inputs": [
        "MAIAC aerosol not assessed (no HDF4 reader).",
        "ERA5 2016 download not complete.",
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
# id, dataset, role, availability, origin, latency hours
LISTED = [
    (
        "nea_pm25",
        "NEA hourly PM2.5",
        "observation",
        "issue_time_valid",
        "Historical1hrPM2.5.csv",
        2,
    ),
    (
        "firms",
        "FIRMS MODIS fire detections",
        "observation",
        "issue_time_valid",
        "FIRMS area API",
        3,
    ),
    ("era5", "ERA5 reanalysis wind and rain", "reanalysis", "hindsight", "Copernicus CDS", 120),
    ("imerg_early", "GPM IMERG V07 Early", "estimate", "issue_time_valid", "NASA GES DISC", 4),
    ("imerg_final", "GPM IMERG V07 Final", "estimate", "hindsight", "NASA GES DISC", 2500),
]


def _stage_t_facts(s: dict[str, Any]) -> list[dict[str, Any]]:
    out = [
        fact(
            f"t19.{r}.mae",
            f"2019 held-out {r}: MAE all hours",
            "m5_stage_t",
            round(s["mae"][r], 2),
            "ug/m3",
        )
        for r in RUNGS
    ]
    out += [
        fact(
            f"t19.{r}.mae_gt55",
            f"2019 held-out {r}: MAE above 55",
            "m5_stage_t",
            round(s["elevated_mae"][r], 2),
            "ug/m3",
        )
        for r in RUNGS
    ]
    p = s["paired"]["R2_vs_R1"]
    return [
        *out,
        fact(
            "t19.R2_vs_R1.skill",
            "R2 (lags + FIRMS) vs R1, all hours, paired skill",
            "m5_stage_t",
            round(p["skill"], 3),
        ),
        fact("t19.R2_vs_R1.high", "Same, upper 95% bound", "m5_stage_t", round(p["high"], 3)),
        fact("t19.R2.bias", "R2 bias, all hours", "m5_stage_t", round(s["bias"]["R2"], 2), "ug/m3"),
        fact(
            "t19.elev_days",
            "Elevated days in the 2019 season",
            "m5_stage_t",
            s["elevated_days"],
            "days",
        ),
    ]


def _qa_facts(i1: dict[str, Any], hls: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        fact(
            "i1.mae",
            "I1 (R2 + IMERG Early) MAE, 2015 Stage P",
            "m5_i1",
            round(i1["mae"]["I1"], 2),
            "ug/m3",
        ),
        fact("i1.R2.mae", "R2 MAE, 2015 Stage P", "m5_i1", round(i1["mae"]["R2"], 2), "ug/m3"),
        fact(
            "hls.clear",
            "HLS clear-land share on both dates",
            "m5_hls",
            round(hls["both_dates_clear_fraction_of_box_pixels"], 3),
        ),
        fact(
            "hls.aerosol3",
            "HLS post-date pixels with high aerosol flag",
            "m5_hls",
            round(hls["post"]["aerosol_level_3"], 3),
        ),
        fact(
            "smap.rq",
            "SMAP recommended-quality cells over the Kalimantan box, 16 Oct 2015",
            "m5_smap",
            0,
        ),
    ]


def package_d(st: Store) -> dict[str, Any]:
    t, thash, to = st.m5_file(M5_PATHS["stage_t"])
    i1, ih, io = st.m5_file(M5_PATHS["i1"])
    hls, hh, ho = st.m5_file(M5_PATHS["hls"])
    _, sh, so = st.m5_file(M5_PATHS["smap"])
    sources = [src(i, d, r, a, o, latency_hours=h) for i, d, r, a, o, h in LISTED]
    sources += [
        src("hls", "HLS L30 v2.0 surface reflectance", "observation", "unknown", ho, sha256=hh),
        src("smap", "SMAP L3 SPL3SMP v009 soil moisture", "estimate", "unknown", so, sha256=sh),
        src(
            "m5_stage_t",
            "M5 Stage T results, 2019 held out",
            "evaluation",
            "hindsight",
            to,
            sha256=thash,
        ),
        src("m5_i1", "M5 rung I1 result, 2015", "evaluation", "hindsight", io, sha256=ih),
        src("m5_hls", "M5 HLS quality check", "derived", "hindsight", ho, sha256=hh),
        src("m5_smap", "M5 SMAP quality check", "derived", "hindsight", so, sha256=sh),
    ]
    facts = [*_stage_t_facts(t["2019"]), *_qa_facts(i1, hls)]
    return {**HEAD_D, "sources": sources, "facts": facts}


def package_e(st: Store, ref: str) -> EvidencePackageV1:
    """Amendment 2: consume the M5 package itself through the hash-checking adapter."""
    path = "docs/m5/evidence/scientific_evidence_package_v1.json"
    m5 = json.loads(st.git_bytes(ref, path))
    return adapt(m5, lambda rel: st.git_bytes(ref, rel), ref)

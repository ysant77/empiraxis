"""Build the frozen M4.1 evidence packages from recorded artifacts.

Every value comes from a recorded file. Each source records the SHA-256 of that file and a
path relative to its root, not an absolute path. M5 files are read from a pinned commit with
`git show`; the M5 worktree is not touched. Packages D and E: `m41_package_m5.py`.

Usage:
  python scripts/m41_build_packages.py --runs DIR --m4-runs DIR --repo DIR --m5-ref SHA --out DIR
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path
from typing import Any

from m41_package_m5 import package_d, package_e
from m41_package_store import LIMITS, M3_RUN, NEA_RUN, TL_RUN, Store, _row, fact, src

from earthlab.assess.contracts import EvidencePackageV1

M3_NAMES = {
    "B4_lagged_ridge": "b4",
    "candidate-ridge-cv": "ridgecv",
    "candidate-1": "tcn",
    "B0_persistence": "persist",
}


def _model_facts(model: str, key: str, r: dict[str, Any]) -> list[dict[str, Any]]:
    out = [
        fact(f"{key}.mae", f"{model} validation MAE, all hours", "m3_eval", r["mae"], "ug/m3"),
        fact(f"{key}.rmse", f"{model} validation RMSE", "m3_eval", r["rmse"], "ug/m3"),
        fact(
            f"{key}.mae_gt55",
            f"{model} MAE when PM2.5 is above 55",
            "m3_eval",
            r["above_55_mae"],
            "ug/m3",
        ),
    ]
    if key != "persist":
        out += [
            fact(f"{key}.skill", f"{model} MAE skill against persistence", "m3_eval", r["skill"]),
            fact(
                f"{key}.skill_low", f"{model} skill, lower 95% bound", "m3_eval", round(r["low"], 4)
            ),
        ]
    return out


def _m3_facts(result: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for model, key in M3_NAMES.items():
        out += _model_facts(model, key, _row(result["comparison"], model))
    val = profile["splits"]["validation"]
    out += [
        fact(
            "val.years",
            "Validation covers 2019 to 2023; the same years chose the candidate configuration",
            "m3_profile",
            5,
            "years",
        ),
        fact(
            "val.gt55_hours",
            "Validation hours with PM2.5 above 55",
            "m3_profile",
            val["peak_above_55_hours"],
            "hours",
        ),
        fact("tcn.params", "TCN candidate trainable parameters", "m3_eval", 10287),
    ]
    return out


def package_a(st: Store) -> dict[str, Any]:
    result, rh, ro = st.run_file(M3_RUN, "result.json")
    profile, ph, po = st.run_file(M3_RUN, "data_profile.json")
    tl, th, to = st.m4_file(f"primary-c/runs/{TL_RUN}/result.json")
    gru = _row(tl["comparison"], "candidate-1")
    facts = [
        *_m3_facts(result, profile),
        fact(
            "gru.mae",
            "GRU candidate from a later run (M4 T-L) on the same validation years",
            "m4_tl_eval",
            gru["mae"],
            "ug/m3",
        ),
        fact(
            "gru.mae_gt55",
            "GRU candidate MAE when PM2.5 is above 55",
            "m4_tl_eval",
            gru["above_55_mae"],
            "ug/m3",
        ),
    ]
    sources = [
        src("m3_eval", "M3 evaluator report", "evaluation", "hindsight", ro, sha256=rh),
        src("m3_profile", "M3 data profile", "derived", "hindsight", po, sha256=ph),
        src("m4_tl_eval", "M4 T-L evaluator report", "evaluation", "hindsight", to, sha256=th),
    ]
    return {**HEAD_A, "sources": sources, "facts": facts}


HEAD_A: dict[str, Any] = {
    "package_id": "a-model-selection-m3",
    "scenario": "model_selection",
    "question": "Should the PM2.5 T+6 baseline (lagged ridge B4) be retained, should a more "
    "complex candidate be adopted for a limited purpose, or is more validation needed?",
    "study_area": "Singapore, five NEA regions",
    "interval": "validation 2019 to 2023",
    "target": "hourly PM2.5, T+1 to T+6, ug/m3",
    "acceptance_criteria": [
        "The decision follows the evaluator numbers, not agent text.",
        "Elevated hours (PM2.5 above 55) are considered separately.",
        "Reuse of validation years is stated.",
    ],
    "limitations": LIMITS,
    "missing_inputs": [
        "No paired interval between a candidate and B4.",
        "No untouched test period was read; it is sealed.",
    ],
    "allowed_decisions": [
        "retain_baseline",
        "adopt_limited",
        "adopt",
        "request_validation",
        "abstain",
    ],
    "fixture": False,
}


def _mismatch_facts(acq: dict[str, Any]) -> list[dict[str, Any]]:
    regions = Counter(m.split()[0] for m in acq["mismatches"])
    diffs = []
    for m in acq["mismatches"]:
        api = float(m.split("API ")[1].split(",")[0])
        diffs.append(abs(api - float(m.split("file ")[1])))
    out = [
        fact(f"nea.mm_{r}", f"Disagreements in region {r}", "nea_acq", n, "hours")
        for r, n in sorted(regions.items())
    ]
    return [
        *out,
        fact("nea.mm_max_abs", "Largest API minus file difference", "nea_acq", max(diffs), "ug/m3"),
        fact("nea.mm_days", "Days with any disagreement (2023-11-15 only)", "nea_acq", 1, "days"),
    ]


def _nea_facts(acq: dict[str, Any], audit: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        fact(
            "nea.compared",
            "Hourly values compared between the live API and the file",
            "nea_acq",
            acq["values"],
        ),
        fact("nea.matched", "Values that agree", "nea_acq", acq["matched"]),
        fact("nea.mismatched", "Values that disagree", "nea_acq", acq["mismatched"]),
        fact("nea.days_checked", "Days checked: 2023-02-15, 2023-07-15, 2023-11-15", "nea_acq", 3),
        fact(
            "file.duplicates",
            "Duplicate time labels in the historical file",
            "nea_profile",
            audit["duplicate_labels"],
        ),
        fact(
            "file.conflicts",
            "Duplicate labels with conflicting values",
            "nea_profile",
            len(audit["conflicting_labels"]),
        ),
        fact(
            "file.unparsed",
            "Unparsed time labels (for example '2016-04-04 010:00:00')",
            "nea_profile",
            len(audit["unparsed_labels"]),
        ),
        fact(
            "file.missing_region",
            "Missing hours per region in the file",
            "nea_profile",
            audit["missing_by_region"]["east"],
            "hours",
        ),
        *_mismatch_facts(acq),
    ]


def _nea_sources(
    audit: dict[str, Any], acq_ref: tuple[str, str], prof_ref: tuple[str, str]
) -> list[dict[str, Any]]:
    (ah, ao), (ph, po) = acq_ref, prof_ref
    return [
        src(
            "nea_api",
            "data.gov.sg real-time PM2.5 API",
            "observation",
            "issue_time_valid",
            "https://api-open.data.gov.sg/v2/real-time/api/pm25",
            latency_hours=1,
        ),
        src(
            "nea_file",
            "NEA Historical1hrPM2.5.csv",
            "observation",
            "hindsight",
            "data.gov.sg historical file",
            sha256=audit["source_sha256"],
        ),
        src(
            "nea_acq",
            "Acquisition receipt nea-pm25-qa-1",
            "derived",
            "hindsight",
            ao,
            sha256=ah,
        ),
        src(
            "nea_profile",
            "Data profile of the historical file",
            "derived",
            "hindsight",
            po,
            sha256=ph,
        ),
    ]


def package_b(st: Store) -> dict[str, Any]:
    acq, ah, ao = st.run_file(NEA_RUN, "artifacts/acquisition.json")
    prof, ph, po = st.run_file(NEA_RUN, "data_profile.json")
    audit = prof["audit"]
    return {
        **HEAD_B,
        "sources": _nea_sources(audit, (ah, ao), (ph, po)),
        "facts": _nea_facts(acq, audit),
    }


HEAD_B: dict[str, Any] = {
    "package_id": "b-nea-provenance",
    "scenario": "provenance",
    "question": "What is known and what is inconsistent about the NEA PM2.5 values, and what "
    "must not be inferred from the 17 disagreements?",
    "study_area": "Singapore, five NEA regions",
    "interval": "2014-04 to 2026-10; checks on three days in 2023",
    "target": "hourly PM2.5, ug/m3",
    "acceptance_criteria": [
        "Known facts and inconsistencies are kept apart.",
        "No cause of the disagreements is asserted without evidence.",
        "A next check or a limit of use is stated.",
    ],
    "limitations": LIMITS,
    "missing_inputs": [
        "No NEA statement on revisions or quality control of the file.",
        "Only three days were compared.",
    ],
    "allowed_decisions": [
        "proceed_with_limits",
        "request_data",
        "request_validation",
        "abstain",
    ],
    "fixture": False,
}
C_NAMES = {
    "B0": "persistence",
    "B1": "ridge on PM2.5 lags",
    "B2": "B1 plus ERA5 weather",
    "B3": "B2 plus FIRMS fire counts",
}


def _abl_facts(abl: dict[str, Any]) -> list[dict[str, Any]]:
    facts = [
        fact(f"abl.{k}.mae", f"{k} {v}: MAE, T+6", "abl", round(abl["mae"][k], 2), "ug/m3")
        for k, v in C_NAMES.items()
    ]
    for pair, p in abl["paired"].items():
        facts += [
            fact(f"abl.{pair}.skill", f"Paired skill {pair}", "abl", round(p["skill"], 3)),
            fact(
                f"abl.{pair}.high",
                f"Paired skill {pair}, upper 95% bound",
                "abl",
                round(p["high"], 3),
            ),
        ]
    facts += [
        fact("abl.rows", "Scored region-hours, 18 Sep to 31 Oct 2015", "abl", abl["scored_rows"]),
        fact("abl.days", "Scored days, one haze season", "abl", abl["scored_days"], "days"),
        fact("abl.elev_rows", "Scored rows with PM2.5 above 55", "abl", abl["elevated_rows"]),
    ]
    return facts


def package_c(st: Store) -> dict[str, Any]:
    abl, ah, ao = st.repo_file("docs/evidence/haze-2015-ablation.json")
    inputs = abl["inputs"]
    sources = [
        src(
            "nea_pm25",
            "NEA hourly PM2.5",
            "observation",
            "issue_time_valid",
            "Historical1hrPM2.5.csv",
            latency_hours=2,
            sha256=inputs["Historical1hrPM2.5.csv"],
        ),
        src(
            "era5",
            "ERA5 reanalysis 10 m and 850 hPa wind",
            "reanalysis",
            "hindsight",
            "extract_10m.json, extract_850hpa.json",
            sha256=inputs["extract_10m.json"],
        ),
        src(
            "firms",
            "FIRMS MODIS standard product fire counts",
            "observation",
            "issue_time_valid",
            "firms_modis_sp_2015_08_2015_11.csv",
            latency_hours=3,
            sha256=inputs["firms_modis_sp_2015_08_2015_11.csv"],
        ),
        src("abl", "2015 ablation result", "evaluation", "hindsight", ao, sha256=ah),
    ]
    return {**HEAD_C, "sources": sources, "facts": _abl_facts(abl)}


HEAD_C: dict[str, Any] = {
    "package_id": "c-fire-weather-sufficiency",
    "scenario": "sufficiency",
    "question": "Does this fire and weather evidence justify a claim that wind and fire "
    "inputs improve Singapore PM2.5 prediction at T+6, or should we request more or abstain?",
    "study_area": "Singapore and upwind study boxes",
    "interval": "18 Sep to 31 Oct 2015",
    "target": "hourly PM2.5 at T+6, ug/m3",
    "acceptance_criteria": [
        "The answer states whether each input is available at issue time.",
        "No cause of haze is asserted from PM2.5 association.",
        "The answer says what more evidence would be needed.",
    ],
    "limitations": LIMITS,
    "missing_inputs": [
        "No second haze season in this package.",
        "No satellite aerosol (MAIAC) or rainfall layer.",
    ],
    "allowed_decisions": ["proceed_with_limits", "request_data", "abstain", "adopt"],
    "fixture": False,
}


def main() -> None:
    ap = argparse.ArgumentParser()
    for flag in ("--runs", "--m4-runs", "--repo", "--out"):
        ap.add_argument(flag, type=Path, required=True)
    ap.add_argument("--m5-ref", required=True)
    ap.add_argument("--m5-package-ref", default=None)
    ap.add_argument("--only", default="abcd")
    a = ap.parse_args()
    st = Store(a.runs, a.m4_runs, a.repo, a.m5_ref)
    a.out.mkdir(parents=True, exist_ok=True)
    built = [
        EvidencePackageV1.model_validate(b(st))
        for k, b in zip("abcd", (package_a, package_b, package_c, package_d), strict=True)
        if k in a.only
    ]
    if a.m5_package_ref:
        built.append(package_e(st, a.m5_package_ref))
    for pkg in built:
        path = a.out / f"{pkg.package_id}.json"
        path.write_text(json.dumps(pkg.model_dump(mode="json"), indent=1) + "\n")
        print(path.name, len(pkg.facts), "facts")


if __name__ == "__main__":
    main()

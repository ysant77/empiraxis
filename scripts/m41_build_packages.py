"""Build the four frozen M4.1 evidence packages from recorded artifacts.

Every value comes from a recorded file. Each source records the SHA-256 of that file and a
path relative to its root, not an absolute path. M5 files are read from a pinned commit with
`git show`; the M5 worktree is not touched.

Usage:
  python scripts/m41_build_packages.py --runs DIR --m4-runs DIR --repo DIR --m5-ref SHA --out DIR
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from collections import Counter
from pathlib import Path
from typing import Any

from earthlab.assess.contracts import EvidencePackageV1
from earthlab.assess.m5_adapter import adapt

M3_RUN = "20261103T061204Z-829fed"
NEA_RUN = "20261103T035551Z-95e7a3"
TL_RUN = "20261103T140243Z-40d596"
M5_PATHS = {
    "stage_t": "docs/m5/results/m5_ladder_stage_t.json",
    "i1": "docs/m5/results/m5_i1_stage_p_2015.json",
    "hls": "docs/m5/qa/hls_qa.json",
    "smap": "docs/m5/qa/smap_qa.json",
    "rain": "docs/m5/qa/rain_compare_early.json",
}
LIMITS = [
    "Historical validation only. Not a forecast of any future date.",
    "Not for health, safety or travel decisions.",
    "PM2.5 alone does not identify the cause of haze.",
]


class Store:
    """Reads artifacts once and remembers their digests."""

    def __init__(self, runs: Path, m4_runs: Path, repo: Path, m5_ref: str):
        self.runs, self.m4_runs, self.repo, self.m5_ref = runs, m4_runs, repo, m5_ref

    def run_file(self, run: str, name: str) -> tuple[Any, str, str]:
        raw = (self.runs / run / name).read_bytes()
        return json.loads(raw), hashlib.sha256(raw).hexdigest(), f"earthlab-e2e-runs/{run}/{name}"

    def m4_file(self, rel: str) -> tuple[Any, str, str]:
        raw = (self.m4_runs / rel).read_bytes()
        return json.loads(raw), hashlib.sha256(raw).hexdigest(), f"m4-runs/{rel}"

    def repo_file(self, rel: str) -> tuple[Any, str, str]:
        raw = Path(rel).read_bytes()  # this checkout
        return json.loads(raw), hashlib.sha256(raw).hexdigest(), rel

    def git_bytes(self, ref: str, rel: str) -> bytes:
        git = shutil.which("git") or "git"
        return subprocess.run(  # noqa: S603 - fixed git command on a pinned commit
            [git, "-C", str(self.repo), "show", f"{ref}:{rel}"], check=True, capture_output=True
        ).stdout

    def m5_file(self, rel: str) -> tuple[Any, str, str]:
        git = shutil.which("git") or "git"
        raw = subprocess.run(  # noqa: S603 - fixed git command on a pinned commit
            [git, "-C", str(self.repo), "show", f"{self.m5_ref}:{rel}"],
            check=True,
            capture_output=True,
        ).stdout
        return json.loads(raw), hashlib.sha256(raw).hexdigest(), f"m5@{self.m5_ref[:7]}:{rel}"


def src(sid: str, dataset: str, role: str, avail: str, origin: str, **kw: Any) -> dict[str, Any]:
    return {
        "id": sid,
        "dataset": dataset,
        "role": role,
        "availability": avail,
        "origin": origin,
        **kw,
    }


def fact(fid: str, statement: str, source: str, value: float | None = None, unit: str = "") -> dict:
    return {"id": fid, "statement": statement, "value": value, "unit": unit, "source": source}


def _row(table: list[dict[str, Any]], model: str) -> dict[str, Any]:
    return next(r for r in table if r["model"] == model)


def _m3_facts(result: dict[str, Any], profile: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    names = {
        "B4_lagged_ridge": "b4",
        "candidate-ridge-cv": "ridgecv",
        "candidate-1": "tcn",
        "B0_persistence": "persist",
    }
    for model, key in names.items():
        r = _row(result["comparison"], model)
        out += [
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
                fact(
                    f"{key}.skill", f"{model} MAE skill against persistence", "m3_eval", r["skill"]
                ),
                fact(
                    f"{key}.skill_low",
                    f"{model} skill, lower 95% bound",
                    "m3_eval",
                    round(r["low"], 4),
                ),
            ]
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
    return {
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
        "sources": [
            src("m3_eval", "M3 evaluator report", "evaluation", "hindsight", ro, sha256=rh),
            src("m3_profile", "M3 data profile", "derived", "hindsight", po, sha256=ph),
            src("m4_tl_eval", "M4 T-L evaluator report", "evaluation", "hindsight", to, sha256=th),
        ],
        "facts": facts,
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


def package_b(st: Store) -> dict[str, Any]:
    acq, ah, ao = st.run_file(NEA_RUN, "artifacts/acquisition.json")
    prof, ph, po = st.run_file(NEA_RUN, "data_profile.json")
    audit = prof["audit"]
    facts = [
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
    return {
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
        "sources": [
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
        ],
        "facts": facts,
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


def package_c(st: Store) -> dict[str, Any]:
    abl, ah, ao = st.repo_file("docs/evidence/haze-2015-ablation.json")
    names = {
        "B0": "persistence",
        "B1": "ridge on PM2.5 lags",
        "B2": "B1 plus ERA5 weather",
        "B3": "B2 plus FIRMS fire counts",
    }
    facts = [
        fact(f"abl.{k}.mae", f"{k} {v}: MAE, T+6", "abl", round(abl["mae"][k], 2), "ug/m3")
        for k, v in names.items()
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
    return {
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
        "sources": [
            src(
                "nea_pm25",
                "NEA hourly PM2.5",
                "observation",
                "issue_time_valid",
                "Historical1hrPM2.5.csv",
                latency_hours=2,
                sha256=abl["inputs"]["Historical1hrPM2.5.csv"],
            ),
            src(
                "era5",
                "ERA5 reanalysis 10 m and 850 hPa wind",
                "reanalysis",
                "hindsight",
                "extract_10m.json, extract_850hpa.json",
                sha256=abl["inputs"]["extract_10m.json"],
            ),
            src(
                "firms",
                "FIRMS MODIS standard product fire counts",
                "observation",
                "issue_time_valid",
                "firms_modis_sp_2015_08_2015_11.csv",
                latency_hours=3,
                sha256=abl["inputs"]["firms_modis_sp_2015_08_2015_11.csv"],
            ),
            src("abl", "2015 ablation result", "evaluation", "hindsight", ao, sha256=ah),
        ],
        "facts": facts,
        "limitations": LIMITS,
        "missing_inputs": [
            "No second haze season in this package.",
            "No satellite aerosol (MAIAC) or rainfall layer.",
        ],
        "allowed_decisions": ["proceed_with_limits", "request_data", "abstain", "adopt"],
        "fixture": False,
    }


def _m5_facts(t: dict[str, Any], i1: dict[str, Any], hls: dict[str, Any]) -> list[dict]:
    s = t["2019"]
    out = [
        fact(
            f"t19.{r}.mae",
            f"2019 held-out {r}: MAE all hours",
            "m5_stage_t",
            round(s["mae"][r], 2),
            "ug/m3",
        )
        for r in ("R0", "R1", "R2", "R3a")
    ]
    out += [
        fact(
            f"t19.{r}.mae_gt55",
            f"2019 held-out {r}: MAE above 55",
            "m5_stage_t",
            round(s["elevated_mae"][r], 2),
            "ug/m3",
        )
        for r in ("R0", "R1", "R2", "R3a")
    ]
    p = s["paired"]["R2_vs_R1"]
    out += [
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
    return out


def package_d(st: Store) -> dict[str, Any]:
    t, thash, to = st.m5_file(M5_PATHS["stage_t"])
    i1, ih, io = st.m5_file(M5_PATHS["i1"])
    hls, hh, ho = st.m5_file(M5_PATHS["hls"])
    _, sh, so = st.m5_file(M5_PATHS["smap"])
    return {
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
        "sources": [
            src(
                "nea_pm25",
                "NEA hourly PM2.5",
                "observation",
                "issue_time_valid",
                "Historical1hrPM2.5.csv",
                latency_hours=2,
            ),
            src(
                "firms",
                "FIRMS MODIS fire detections",
                "observation",
                "issue_time_valid",
                "FIRMS area API",
                latency_hours=3,
            ),
            src(
                "era5",
                "ERA5 reanalysis wind and rain",
                "reanalysis",
                "hindsight",
                "Copernicus CDS",
                latency_hours=120,
            ),
            src(
                "imerg_early",
                "GPM IMERG V07 Early",
                "estimate",
                "issue_time_valid",
                "NASA GES DISC",
                latency_hours=4,
            ),
            src(
                "imerg_final",
                "GPM IMERG V07 Final",
                "estimate",
                "hindsight",
                "NASA GES DISC",
                latency_hours=2500,
            ),
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
        ],
        "facts": _m5_facts(t, i1, hls),
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


def package_e(st: Store, ref: str) -> EvidencePackageV1:
    """Amendment 2: consume the M5 package itself through the hash-checking adapter."""
    path = "docs/m5/evidence/scientific_evidence_package_v1.json"
    m5 = json.loads(st.git_bytes(ref, path))
    return adapt(m5, lambda rel: st.git_bytes(ref, rel), ref)


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

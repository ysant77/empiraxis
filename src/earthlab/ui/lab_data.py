"""The Engineering Lab's rows for one scenario, read from its verified files."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from earthlab.ui.scenarios import UNIT, read, record_of, s4_verdict

STRATEGIES = {
    "deterministic": "Deterministic method",
    "statistical": "Statistical model",
    "small_neural": "Small neural model",
    "pretrained_transfer": "Pretrained transfer",
    "fine_tuning": "Fine-tuning",
    "distillation": "Distillation",
    "abstain_or_request": "Abstain or request",
}
FAMILIES = {"M_ridge": "Ridge", "M_trees": "Trees", "B0_persistence": "Persistence"}
READINESS = {"S1": "readiness-02d39d3ee183.json", "S2": "readiness-e53f6e427df8.json"}


def _profile_rows(run_dir: Path) -> list[dict[str, Any]]:
    profile = read(run_dir, "profile.json")
    sources = profile["sources"]
    source = sources[0] if sources else None
    return [
        {
            "Dataset": source["name"] if source else "MCD64A1 v061 monthly burned area",
            "Digest": source["sha256"][:12] if source else "see the artifact list",
            "Coverage": f"{profile['first_label'][:10]} to {profile['last_label'][:10]}"
            if profile.get("first_label")
            else "fixed months of a pinned product",
            "Granularity": profile["granularity"],
            "Availability": f"delay {profile['availability_latency_hours']} h (assumed)",
        }
    ]


def _s2_data(run_dir: Path) -> list[dict[str, Any]]:
    data = read(run_dir, "readiness-e53f6e427df8.json")["data"]
    return [
        {
            "Dataset": "NEA historical 1-hour PM2.5",
            "Digest": data["source_sha256"][:12],
            "Coverage": read(run_dir, "families-classification-evaluation.json")["split_scored"],
            "Granularity": "1 h, five regions",
            "Availability": "; ".join(f.split(": ")[-1] for f in data["alignment_findings"]),
        }
    ]


def _s3_data(run_dir: Path) -> list[dict[str, Any]]:
    wind = read(run_dir, "s3-wind-consistency-2015.json")
    clocks = wind["clocks"]
    return [
        {
            "Dataset": "ERA5 reanalysis: wind and precipitation",
            "Digest": "see the artifact list",
            "Coverage": f"{clocks[0]['first'][:10]} to {clocks[0]['last'][:10]}",
            "Granularity": "1 h, three boxes, 10 m and 850 hPa",
            "Availability": "reanalysis made after the event: hindsight only, never issue-time",
        }
    ]


def data_rows(key: str, run_dir: Path) -> list[dict[str, Any]]:
    if key == "S2":
        return _s2_data(run_dir)
    if key == "S3":
        return _s3_data(run_dir)
    if (run_dir / "profile.json").is_file():
        return _profile_rows(run_dir)
    return []


def alternatives(run_dir: Path) -> list[dict[str, Any]]:
    """The suitability rows the run recorded. A packaged result holds none."""
    checks = (record_of(run_dir).get("suitability") or {}).get("checks", [])
    return [
        {
            "Alternative": STRATEGIES.get(c["strategy"], c["strategy"]),
            "Allowed": "yes" if c["eligible"] else "no",
            "Reason": "; ".join(c["reasons"]) or "none",
        }
        for c in checks
    ]


def execution(key: str, run_dir: Path) -> str:
    record = record_of(run_dir)
    usage = record.get("usage") or {}
    if key == "S1":
        return (
            f"GRU trained for real: {usage['training_seconds']} s of "
            f"{usage['wall_seconds']} s, peak memory {usage['peak_training_rss_mb']} MB."
        )
    if key == "S2":
        return "The hybrid ran earlier and wrote the report shown here. Nothing was retrained."
    if key == "S3":
        return "No model was trained. The diagnostic is a fixed rule over reanalysis hours."
    if key == "S4":
        return "No model ran. The training budget in the plan is 0 s."
    return f"Training time {usage['training_seconds']} s; {usage['tool_calls']} tool calls."


def _family_rows(run_dir: Path) -> list[dict[str, Any]]:
    report = read(run_dir, "families-regression-evaluation.json")
    return [
        {
            "Model": FAMILIES[s["model"]],
            f"MAE ({UNIT})": f"{s['metrics']['mae']:.3f}",
            f"MAE above 55 {UNIT}": f"{s['metrics']['above_55_mae']:.3f}",
            "Recall above 55": f"{s['subgroups']['elevated']['recall']:.3f}",
            "Passes": "yes" if s["passes"] else "no",
        }
        for s in report["scores"]
        if s["model"] in FAMILIES
    ]


def extra_comparison(key: str, run_dir: Path) -> list[dict[str, Any]]:
    """More alternatives, under the same evaluator, where the scenario has them."""
    return _family_rows(run_dir) if key == "S1" else []


def _s1_negative(run_dir: Path) -> list[str]:
    ready = read(run_dir, "readiness-02d39d3ee183.json")
    high = ready["high_pm25"]
    return [
        f"Above {high['threshold_ug_m3']:.0f} {UNIT} the verified ridge bundle has MAE "
        f"{high['model_mae']:.3f} against {high['reference_mae']:.3f} for persistence, with "
        f"recall {high['model_recall']:.3f}.",
        f"Readiness is {ready['readiness']}. Production ready: "
        f"{'yes' if ready['production_ready'] else 'no'}.",
    ]


def _s2_negative(run_dir: Path) -> list[str]:
    report = read(run_dir, "families-classification-evaluation.json")
    hybrid = next(s for s in report["scores"] if s["model"] == "frozen_gru_logistic")
    regions = [
        f"region {name.split('_')[1]} {value['f1']:.3f}"
        for name, value in hybrid["subgroups"].items()
    ]
    reasons = [f"{r[0].upper()}{r[1:]}." for r in hybrid["reasons"]]
    return [*reasons, "F1 of the hybrid by region: " + ", ".join(regions) + "."]


def _s3_negative(run_dir: Path) -> list[str]:
    wind = read(run_dir, "s3-wind-consistency-2015.json")
    best = max(wind["boxes"], key=lambda b: b["base_event_rate"])
    name = best["box_id"].replace("box-", "Box ").title()
    return [
        f"{name} at {best['level']} passed in {best['base_event_rate']:.0%} of haze onsets and "
        f"{best['base_clean_rate']:.0%} of clean hours, so wind alone does not separate them.",
        *wind["notes"],
    ]


def _s4_negative(run_dir: Path) -> list[str]:
    verdict = s4_verdict(run_dir)
    return [
        *[f"{r['code']}: {r['detail']}" for r in verdict["refusals"]],
        *verdict["notes"],
        "Alternatives: " + "; ".join(verdict["alternatives"]) + ".",
    ]


def negatives(key: str, run_dir: Path) -> list[str]:
    builders = {"S1": _s1_negative, "S2": _s2_negative, "S3": _s3_negative, "S4": _s4_negative}
    return builders[key](run_dir) if key in builders else []


def readiness(key: str, run_dir: Path) -> dict[str, Any] | None:
    return read(run_dir, READINESS[key]) if key in READINESS else None


def inference_line(ready: dict[str, Any]) -> str:
    done = ready["inference"]
    if done["state"] == "not_run":
        return f"Inference not run: {done['note']}."
    return (
        f"Inference on real data: {done['rows_compared']:,} rows compared, largest difference "
        f"{done['max_abs_difference']}. Output MAE {done['output_mae']} {UNIT}, reference "
        f"{done['reference_mae']} {UNIT}."
    )

"""What each demonstration scenario shows, built only from its verified replay files.

No streamlit here and no number typed by hand: every value is read from a file in the
scenario's folder, and the folder is read only after the replay allowlist has checked it.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

UNIT = "µg/m³"
SCENARIO_RUNS = {
    "S1": "scenario-s1-regression",
    "S2": "scenario-s2-encoder-reuse",
    "S3": "scenario-s3-transport",
    "S4": "scenario-s4-resource-request",
}
TEAM_RUN = "scenario-muse-team-exceedance"
LABELS = {
    "S1": "S1 · PM2.5 regression",
    "S2": "S2 · Model reuse",
    "S3": "S3 · Transport diagnostic",
    "S4": "S4 · Satellite and resources",
}
TITLES = {
    **{key: label.split(" · ")[1] for key, label in LABELS.items()},
    "M1": "Recorded Muse team run",
}
OUTCOMES = {
    "adopt": "Adopt",
    "adopt_limited": "Adopt with limits",
    "retain_baseline": "Keep the baseline",
    "abstain": "Abstain",
    "request_resource": "Request resources",
}
MODELS = {
    "candidate-1": "GRU",
    "B0_persistence": "Persistence",
    "B1_daily_naive": "Daily naive",
    "B2_weekly_naive": "Weekly naive",
    "B3_climatology": "Climatology",
    "B4_lagged_ridge": "Lagged ridge",
    "train_rate": "Training base rate",
    "persistence_alarm": "Persistence alarm",
    "logistic": "Logistic regression",
    "trees_classifier": "Tree classifier",
    "frozen_gru_logistic": "Frozen GRU + logistic",
}
SCIENCE_LABELS = {
    "simulated_availability_hindcast": "Simulated-availability hindcast",
    "hindsight_diagnostic": "Hindsight diagnostic",
    "historical_raster_analysis": "Historical raster analysis",
}


@dataclass(frozen=True)
class Bars:
    """One measure over named models. The highlighted bar is the model under test."""

    title: str
    axis: str
    bars: list[tuple[str, float]]
    highlight: str


@dataclass(frozen=True)
class Tile:
    label: str
    value: str
    note: str = ""


@dataclass
class Story:
    key: str
    run: str
    title: str
    question: str
    method: str
    evidence: list[str]
    tiles: list[Tile]
    rows: list[dict[str, Any]]
    rows_title: str
    decision: str
    why: str
    limits: list[str]
    charts: list[Bars] = field(default_factory=list)


def read(run_dir: Path, name: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((run_dir / name).read_text(encoding="utf-8"))
    return data


def record_of(run_dir: Path) -> dict[str, Any]:
    return read(run_dir, "result.json")


def model_name(model: str) -> str:
    return MODELS.get(model, model)


def outcome_name(outcome: str | None) -> str:
    return OUTCOMES.get(outcome or "", outcome or "none")


def plain(limits: list[str]) -> list[str]:
    """The saved limit lines, with the page's model name and unit."""
    return [line.replace("candidate-1", "the GRU").replace("ug/m3", UNIT) for line in limits]


def key_of(label: str) -> str | None:
    """The scenario key of a run label, or None for any other run."""
    run = label.removeprefix("replay/")
    if run == TEAM_RUN:
        return "M1"
    return next((key for key, name in SCENARIO_RUNS.items() if name == run), None)


def run_of(key: str) -> str:
    return TEAM_RUN if key == "M1" else SCENARIO_RUNS[key]


def _rows_by_model(record: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {row["model"]: row for row in record["comparison"]}


def _regression_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "Model": model_name(row["model"]),
            f"MAE ({UNIT})": f"{row['mae']:.3f}",
            f"MAE above 55 {UNIT}": f"{row['above_55_mae']:.3f}",
            "Skill vs persistence": f"{row['skill']:.3f}",
        }
        for row in record["comparison"]
    ]


def _regression_bars(record: dict[str, Any], measure: str, title: str) -> Bars:
    bars = [(model_name(r["model"]), float(r[measure])) for r in record["comparison"]]
    return Bars(title, f"{UNIT}, lower is better", bars, "GRU")


def _s1_evidence(run_dir: Path, record: dict[str, Any]) -> list[str]:
    profile = read(run_dir, "profile.json")
    usage = record["usage"]
    ready = read(run_dir, "readiness-02d39d3ee183.json")
    inference = ready["inference"]
    return [
        f"{profile['usable_rows']:,} region-hours of NEA PM2.5, "
        f"{profile['first_label'][:10]} to {profile['last_label'][:10]}. "
        f"Assumed availability delay: {profile['availability_latency_hours']} h.",
        f"Real training: {usage['training_seconds']} s, peak memory "
        f"{usage['peak_training_rss_mb']} MB. Scored on {record['split_scored']} only.",
        f"Separate verified ridge bundle: {inference['rows_compared']:,} inference rows "
        f"reproduced, largest difference {inference['max_abs_difference']}. "
        f"This bundle is ridge, not the GRU.",
    ]


def s1(run_dir: Path) -> Story:
    record, plan = record_of(run_dir), read(run_dir, "plan-1.json")
    config = plan["config"]
    rows = _rows_by_model(record)
    gru, base = rows["candidate-1"], rows["B0_persistence"]
    return Story(
        key="S1", run=SCENARIO_RUNS["S1"], title=TITLES["S1"],
        question=read(run_dir, "request.json")["objective"],
        method=f"A small {config['architecture'].upper()}: {config['window_hours']} h window, "
        f"{config['hidden']} hidden units, {config['loss'].upper()} loss. Compared with "
        f"persistence, naive, climatology and lagged ridge.",
        evidence=_s1_evidence(run_dir, record),
        tiles=[
            Tile(f"GRU MAE ({UNIT})", f"{gru['mae']:.3f}", "all scored hours"),
            Tile(f"Persistence MAE ({UNIT})", f"{base['mae']:.3f}", "the reference"),
            Tile("Skill vs persistence", f"{gru['skill']:.3f}",
                 f"95% limits {gru['low']:.3f} to {gru['high']:.3f}"),
            Tile(f"Above 55 {UNIT}: GRU", f"{gru['above_55_mae']:.3f}",
                 f"persistence {base['above_55_mae']:.3f}; the GRU is worse"),
        ],
        rows=_regression_rows(record),
        rows_title="Baseline comparison",
        charts=[
            _regression_bars(record, "mae", "MAE, all scored hours"),
            _regression_bars(record, "above_55_mae", "MAE above 55 µg/m³"),
        ],
        decision=outcome_name(record["recommendation"]["outcome"]) + ": GRU",
        why=f"The GRU passes the rule on all hours. It loses to persistence above 55 {UNIT}, "
        "so a code rule limits it. That elevated-hour rule is exploratory. A person decides.",
        limits=plain(record["limitations"]),
    )  # fmt: skip


def _classification_rows(record: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        {
            "Model": model_name(row["model"]),
            "F1": f"{row['f1']:.3f}",
            "F1 gain, low": f"{row.get('gain_low', row.get('low')):.3f}",
            "F1 gain, high": f"{row.get('gain_high', row.get('high')):.3f}",
            "Passes": "yes" if row["passes"] else "no",
        }
        for row in record["comparison"]
    ]


def s2(run_dir: Path) -> Story:
    record = record_of(run_dir)
    report = read(run_dir, "families-classification-evaluation.json")
    ready = read(run_dir, "readiness-e53f6e427df8.json")
    rows = _rows_by_model(record)
    hybrid, alarm, logistic = (
        rows["frozen_gru_logistic"],
        rows["persistence_alarm"],
        rows["logistic"],
    )
    metrics = next(s for s in report["scores"] if s["model"] == "frozen_gru_logistic")["metrics"]
    failed = [c["name"] for c in ready["integrity_checks"] if not c["passed"]]
    return Story(
        key="S2", run=SCENARIO_RUNS["S2"], title=TITLES["S2"],
        question="Can the GRU encoder, frozen after S1, be reused to warn when PM2.5 exceeds "
        f"35 {UNIT} six hours ahead?",
        method="Keep the GRU encoder fixed and fit a logistic head on its features. Compare with "
        "the persistence alarm, logistic regression, trees and the training base rate.",
        evidence=[
            f"{metrics['scored']:,.0f} scored region-hours, {metrics['positives']:,.0f} "
            f"exceedances (base rate {metrics['base_rate']:.2%}), {report['split_scored']}.",
            "No model was retrained for this result.",
            f"Bundle check: {ready['verification_outcome']}. Failed checks: {', '.join(failed)}.",
        ],
        tiles=[
            Tile("Frozen GRU + logistic F1", f"{hybrid['f1']:.3f}", "the reused model"),
            Tile("Persistence alarm F1", f"{alarm['f1']:.3f}", "the reference"),
            Tile("Logistic F1", f"{logistic['f1']:.3f}", "reuse beat this"),
            Tile("F1 gain over persistence",
                 f"{hybrid['gain_low']:.3f} to {hybrid['gain_high']:.3f}",
                 "95% limits, all below zero"),
        ],
        rows=_classification_rows(record),
        rows_title="Baseline comparison",
        charts=[Bars("F1 by model", "F1, higher is better",
                     [(model_name(r["model"]), float(r["f1"])) for r in record["comparison"]],
                     "Frozen GRU + logistic")],
        decision=outcome_name(record["recommendation"]["outcome"]) + ": persistence alarm",
        why="Reuse worked and beat logistic regression. It still lost to the persistence alarm, "
        "so adoption is not justified. This negative result stands.",
        limits=plain(record["limitations"]),
    )  # fmt: skip


def _percent(value: float) -> str:
    return f"{value:.0%}"


def s3(run_dir: Path) -> Story:
    record = record_of(run_dir)
    wind = read(run_dir, "s3-wind-consistency-2015.json")
    boxes = wind["boxes"]
    count = {name: sum(b["verdict"] == name for b in boxes) for name in
             ("consistent", "inconclusive", "inconsistent")}  # fmt: skip
    signs = sum(test["passed"] for test in wind["sign_tests"])
    clocks = wind["clocks"]
    variants = len(boxes[0]["variants"])
    rows = [
        {
            "Box": b["box_id"].replace("box-", "Box ").title(),
            "Level": b["level"],
            "Verdict": b["verdict"],
            "Haze onsets passing": _percent(b["base_event_rate"]),
            "Clean hours passing": _percent(b["base_clean_rate"]),
            "Stable across variants": _percent(b["stable_share"]),
        }
        for b in record["comparison"]
    ]
    return Story(
        key="S3", run=SCENARIO_RUNS["S3"], title=TITLES["S3"],
        question="Do wind and rain in September and October 2015 support haze transport from "
        "any one fire box?",
        method=f"Test wind direction and rain along the path from three fire boxes at two levels, "
        f"over {variants} variants of tolerance, rain limit, lag and clock convention. Compare "
        "haze onsets with clean hours.",
        evidence=[
            f"ERA5 reanalysis: {clocks[0]['hours']:,} hours for each of {len(clocks)} box-level "
            f"series, {sum(c['gaps'] for c in clocks)} gaps.",
            f"Wind direction sign tests: {signs} of {len(wind['sign_tests'])} passed.",
            f"Rain check: {sum(p['missing'] for p in wind['precip'].values())} missing hours, "
            "no cumulative pattern." if not any(
                p["looks_cumulative"] for p in wind["precip"].values()
            ) else "Rain check: a cumulative pattern was found.",
        ],
        tiles=[
            Tile("Consistent", f"{count['consistent']} of {len(boxes)}", "box and level pairs"),
            Tile("Inconclusive", str(count["inconclusive"]), "box and level pairs"),
            Tile("Inconsistent", str(count["inconsistent"]), "box and level pairs"),
            Tile("Identifiable source", "Yes" if wind["identifiable_source"] else "No"),
        ],
        rows=rows,
        rows_title="Result for each box and level",
        decision=f"{outcome_name(record['recommendation']['outcome'])}: {wind['overall']}",
        why="No box and level reached consistent. Winds that pass in haze hours also pass in "
        "clean hours, so this evidence cannot name a source.",
        limits=plain(record["limitations"]),
    )  # fmt: skip


def s4_verdict(run_dir: Path) -> dict[str, Any]:
    verdict: dict[str, Any] = read(run_dir, "s4-measured-chips.json")["verdicts"]["s4-kalimantan"]
    return verdict


def s4(run_dir: Path) -> Story:
    record = record_of(run_dir)
    chips = read(run_dir, "s4-measured-chips.json")
    verdict = s4_verdict(run_dir)
    box, chip = chips["footprint"], chips["chip"]
    need = verdict["needs"][0]
    return Story(
        key="S4", run=SCENARIO_RUNS["S4"], title=TITLES["S4"],
        question=read(run_dir, "request.json")["objective"],
        method="Check the inputs before any model runs. The check covers bands, resolution, "
        "reference masks, study area and the permission for the weights.",
        evidence=[
            "The local burned-area product is MCD64A1 at 500 m. It has no six-band imagery and "
            "no reference masks.",
            f"The measured chips are {chip['shape'][0]} by {chip['shape'][1]} pixels with "
            f"{chip['band_count']} bands at {chip['pixel_size'][0]:.0f} m, but they cover Texas "
            f"(lon {box['min_lon']:.2f} to {box['max_lon']:.2f}, lat {box['min_lat']:.2f} to "
            f"{box['max_lat']:.2f}), not the Kalimantan box.",
            "The segmentation weights have a verified file digest, but no signed approval "
            "exists for them." if "no signed" in chips["weights_authority"]
            else "A signed approval for the weights is on file.",
        ],
        tiles=[
            Tile("Segmentation score", "None", "nothing ran, so no score exists"),
            Tile("Segmentation runs", "0"),
            Tile("Imagery in the study box", "None", "the chips are outside it"),
            Tile("HLS needed", f"{need['estimated_bytes'] / 2**20:.0f} MiB", "estimated"),
        ],
        rows=[{"Needed": n["item"], "Note": n["detail"] or "none"} for n in verdict["needs"]],
        rows_title="Resources requested",
        decision=outcome_name(record["recommendation"]["outcome"]),
        why=record["recommendation"]["reason"],
        limits=plain(record["limitations"]),
    )  # fmt: skip


def m1(run_dir: Path) -> Story:
    record = record_of(run_dir)
    usage = record["usage"]
    rows = _rows_by_model(record)
    tokens = usage["prompt_tokens"] + usage["completion_tokens"]
    best = max(
        (r for r in record["comparison"] if r["model"] != "persistence_alarm"),
        key=lambda r: r["f1"],
    )
    return Story(
        key="M1", run=TEAM_RUN, title=TITLES["M1"],
        question="Can the same historical observations support a reliable future PM2.5 "
        "threshold-exceedance classifier?",
        method=f"Muse Glimmer chose the strategy {record['strategy']} and its parameters, then "
        "reviewed the results. Code ran the work and separate code scored it.",
        evidence=[
            f"{usage['model_calls']} model calls and {usage['tool_calls']} tool calls, recorded "
            f"in a hash-chained trace. Prompt variant {record['prompt_variant']}.",
            f"Scored on {record['split_scored']}.",
        ],
        tiles=[
            Tile("Model calls", str(usage["model_calls"]), "all on local Muse Glimmer"),
            Tile("Tokens", f"{tokens:,}", "prompt plus completion"),
            Tile("Wall time (s)", f"{usage['wall_seconds']:,.1f}"),
            Tile("Persistence alarm F1", f"{rows['persistence_alarm']['f1']:.3f}",
                 f"best other: {model_name(best['model'])} {best['f1']:.3f}"),
        ],
        rows=_classification_rows(record),
        rows_title="Baseline comparison",
        decision=outcome_name(record["recommendation"]["outcome"]) + ": persistence alarm",
        why=record["recommendation"]["reason"],
        limits=plain(record["limitations"]),
    )  # fmt: skip


BUILDERS = {"S1": s1, "S2": s2, "S3": s3, "S4": s4, "M1": m1}


def story(key: str, run_dir: Path) -> Story:
    return BUILDERS[key](run_dir)

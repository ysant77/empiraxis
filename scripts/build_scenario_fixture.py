"""Add the four demonstration scenarios to the replay folder, from saved results.

S1 and S4 copy real runs with their own traces. S2 and S3 came from jobs that wrote reports and
no run trace, so this script writes a packaging trace. That trace records this step and the
digest of each source. It does not claim that the job ran here. Every number comes from a saved
file, and no model runs.

Run with:  uv run python scripts/build_scenario_fixture.py <folder that holds the run folders>
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

from earthlab.digest import file_digest
from earthlab.events.fixture import copy_redacted_harness
from earthlab.events.manifest import listed_runs, read_manifest, write_manifest
from earthlab.trace import RunTrace

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "examples" / "replay"
MATRIX = "earthlab-matrix-runs/decisions-v1/screen-muse/runs"
S1_RUN, S4_RUN = f"{MATRIX}/20261101T142630Z-4bdffe", f"{MATRIX}/20261101T142627Z-897754"
ACCEPT = "earthlab-e1-runs/acceptance-v1"
HYBRID = "earthlab-e1-runs/mlops-v1/s2-hybrid/families-classification-evaluation.json"
S2_READY = f"{ACCEPT}/s2-frozen_gru_logistic-e53f6e42/readiness-e53f6e427df8.json"
S1_READY = f"{ACCEPT}/s1-ridge-02d39d3e/readiness-02d39d3ee183.json"
S1_FAMILY = "earthlab-e1-runs/mlops-v1/regression/families-regression-evaluation.json"
S3_FILE = "earthlab-e1-runs/suitability-v1/s3-wind-consistency-2015.json"
S4_FILE = "earthlab-e1-runs/suitability-v1/s4-measured-chips.json"
TEAM_RUN = "earthlab-matrix-runs/decisions-v1/confirm/runs/20261101T185947Z-d31490"
HINDCAST = "simulated_availability_hindcast"
SCENARIO_LABEL = "recorded scenario evidence; no model turn in this folder"
NOTE = (
    "Recorded replay. development, visible questions. Each scenario entry states what ran. "
    "S1 to S4 run no model here. The research questions are visible development questions."
)


def copy_all(sources: list[Path], run_dir: Path) -> dict[str, str]:
    """Flat copies, so the manifest pins each one. The digest is the source file's digest."""
    run_dir.mkdir(parents=True)
    digests = {}
    for source in sources:
        shutil.copyfile(source, run_dir / source.name)
        digests[source.name] = file_digest(source)
    return digests


def copied_run(source: Path, extra: list[Path], run_dir: Path) -> dict[str, str]:
    """A real run: its own trace and result, with its stored artifacts beside them."""
    files = [source / "trace.jsonl", source / "result.json"]
    return copy_all([*files, *sorted((source / "artifacts").glob("*.json")), *extra], run_dir)


def packaged_run(run_dir: Path, sources: list[Path], result: dict[str, Any]) -> dict[str, str]:
    """A saved report with no trace of its own. The trace records the packaging only."""
    digests = copy_all(sources, run_dir)
    trace = RunTrace(run_dir / "trace.jsonl")
    trace.append(
        "experiment_start", "runtime", task_id=run_dir.name, arm="recorded",
        kind=result["kind"], evidence_label=result["evidence_label"],
        note="This trace records packaging. The job that made the report ran earlier.",
    )  # fmt: skip
    for name, digest in digests.items():
        trace.append("artifact_stored", "runtime", name=name, sha256=digest, task_id=run_dir.name)
    trace.append(
        "finish", "runtime", status=result["status"], reason=result["reason"], workflow=True
    )
    record = {**result, "evidence": {"files": digests}}
    (run_dir / "result.json").write_text(json.dumps(record, indent=1) + "\n", "utf-8")
    return digests


def s2_record(report: dict[str, Any]) -> dict[str, Any]:
    rows = [
        {"model": s["model"], "f1": s["metrics"].get("f1"), "gain_low": s.get("low"),
         "gain_high": s.get("high"), "passes": s["passes"]}
        for s in report["scores"]
    ]  # fmt: skip
    winners = [r["model"] for r in rows if r["passes"] and r["model"] != report["reference"]]
    return {
        "status": "awaiting_human", "reason": "evidence ready for a human decision",
        "arm": "recorded", "kind": "classification", "problem_id": "s2-frozen-encoder-reuse",
        "evidence_label": f"Recorded results of a real run. {HINDCAST}. Scored on validation.",
        "limitations": [
            "Reuse ran, and the hybrid beat logistic. It stayed below the persistence alarm.",
            "No single verified bundle loads the hybrid, so inference is refused.",
            "Not a forecast of any future date, and not a health or hazard warning.",
        ],
        "recommendation": {
            "outcome": "retain_baseline" if not winners else "adopt_limited",
            "model_id": report["reference"] if not winners else winners[0],
            "reason": "The rule applied by code to the evaluator's rows.",
        },
        "comparison": rows,
    }  # fmt: skip


def s3_record(found: dict[str, Any]) -> dict[str, Any]:
    keep = ("box_id", "level", "verdict", "base_event_rate", "base_clean_rate", "stable_share")
    rows = [{k: b.get(k) for k in keep if k in b} for b in found["boxes"]]
    return {
        "status": "awaiting_human", "reason": "evidence ready for a human decision",
        "arm": "recorded", "kind": "transport_consistency", "problem_id": "s3-wind-rain-fire-2015",
        "evidence_label": f"Retrospective reanalysis: {found['evidence_class']}",
        "limitations": [found["statement"], *found.get("notes", [])][:4],
        "recommendation": {
            "outcome": "abstain", "model_id": None,
            "reason": f"Overall {found['overall']}. Identifiable source: "
            f"{found['identifiable_source']}.",
        },
        "comparison": rows,
    }  # fmt: skip


def entries(root: Path) -> list[dict[str, Any]]:
    report = json.loads((root / HYBRID).read_text())
    wind = json.loads((root / S3_FILE).read_text())
    s1_extra = [root / S1_READY, root / S1_FAMILY]
    s1 = copied_run(root / S1_RUN, s1_extra, OUT / "scenario-s1-regression")
    s2 = packaged_run(OUT / "scenario-s2-encoder-reuse", [root / HYBRID, root / S2_READY],
                      s2_record(report))  # fmt: skip
    s3 = packaged_run(OUT / "scenario-s3-transport", [root / S3_FILE], s3_record(wind))
    s4 = copied_run(root / S4_RUN, [root / S4_FILE], OUT / "scenario-s4-resource-request")
    return [
        {"run": "scenario-s1-regression", "scenario_id": "S1", "sources": s1,
         "evidence_mode": "Real execution, recorded replay. No model in this run.",
         "science_label": HINDCAST, "planned": "A human decision on the model is still open."},
        {"run": "scenario-s2-encoder-reuse", "scenario_id": "S2", "sources": s2,
         "evidence_mode": "Real execution, recorded results. The trace records packaging only.",
         "science_label": HINDCAST, "planned": "None. The negative result stands."},
        {"run": "scenario-s3-transport", "scenario_id": "S3", "sources": s3,
         "evidence_mode": "Retrospective reanalysis, recorded results. The trace records "
                          "packaging only.",
         "science_label": "hindsight_diagnostic", "planned": "None. This is not an attribution."},
        {"run": "scenario-s4-resource-request", "scenario_id": "S4", "sources": s4,
         "evidence_mode": "Real execution, recorded replay. No segmentation model ran.",
         "science_label": "historical_raster_analysis",
         "planned": "Planned work: the human decision on the request. No signed approval exists."},
    ]  # fmt: skip


def team_entry(root: Path) -> dict[str, Any]:
    """The recorded Muse team run. Model text and reasoning are removed; typed choices stay."""
    run_dir = OUT / "scenario-muse-team-exceedance"
    removed = copy_redacted_harness(root / TEAM_RUN, run_dir)
    for source in sorted((root / TEAM_RUN / "artifacts").glob("evaluation-*.json")):
        shutil.copyfile(source, run_dir / source.name)
    return {
        "run": run_dir.name, "scenario_id": "M1", "removed_fields": sorted(removed),
        "label": "real Muse Glimmer team run; redacted copy",
        "source_trace_sha256": file_digest(root / TEAM_RUN / "trace.jsonl"),
        "evidence_mode": "Real Muse Glimmer team run, recorded replay, redacted copy.",
        "science_label": HINDCAST, "planned": "A human decision on the outcome is still open.",
    }  # fmt: skip


def main() -> int:
    top = argparse.ArgumentParser(description=__doc__)
    top.add_argument("root", type=Path)
    args = top.parse_args()
    kept = [r for r in listed_runs(OUT) if not str(r["run"]).startswith("scenario-")]
    for old in OUT.glob("scenario-*"):
        shutil.rmtree(old)
    built = [*entries(args.root.resolve()), team_entry(args.root.resolve())]
    for entry in built:
        entry["split"] = "validation only; the sealed test period was not read"
        entry.setdefault("label", SCENARIO_LABEL)
        entry["result_sha256"] = file_digest(OUT / str(entry["run"]) / "result.json")
    note = str(read_manifest(OUT).get("note", NOTE))
    write_manifest(OUT, [*kept, *built], note=note)
    print(f"{len(built)} recorded runs written to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

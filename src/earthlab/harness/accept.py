"""Inference acceptance: verify a bundle, run the real batch command, write the readiness report.

The batch command runs as its own process on rows before the sealed period. Its output is
compared with the predictions the evaluator scored. The source digest decides whether this is
real-data evidence or a synthetic smoke test. No passing check makes a model production-ready.
"""

from __future__ import annotations

import csv
import json
import os
import resource
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Literal

import numpy as np

from earthlab.digest import file_digest
from earthlab.efficiency.artifacts import ArtifactRef
from earthlab.forecast import evaluator as forecast_eval
from earthlab.forecast import samples as S
from earthlab.forecast.dataset import REGIONS, label_at, load_grid
from earthlab.harness import attest as authority
from earthlab.harness import hindcast
from earthlab.harness.contracts import EvaluationReportV1
from earthlab.harness.verify import verify_bundle
from earthlab.mlops.contracts import ModelBundleV1, QualityReportV1
from earthlab.mlops.evidence import (
    DataValidityV1,
    DeploymentReadinessV1,
    HighPmEvidenceV1,
    InferenceEvidenceV1,
    InferenceState,
    ResourceEvidenceV1,
)
from earthlab.mlops.registry import Registry
from earthlab.mlops.serve import readiness

COMMAND_TIMEOUT = 600.0
MATCH_LIMIT = 1e-6
HIGH = 55.0
MEMORY_UNIT = 2**20 if sys.platform == "darwin" else 2**10
MISSING = (
    "prospective issue-time runs with a logged available-at time for each input",
    "monitoring of input drift and output quality in operation",
    "a rollback drill on a live path",
    "load and failure tests on the target hardware",
    "a named operator and an incident path",
)


def export_input(source: Path, path: Path) -> Path:
    """The published rows up to the validation end, for the batch command. Test rows stay out."""
    values = load_grid(source)[0].values[: S.split_bounds("validation")[1] + 1]
    with path.open("w", newline="", encoding="utf-8") as stream:
        out = csv.writer(stream)
        out.writerow(("time", *REGIONS))
        for index, row in enumerate(values):
            cells = ["" if np.isnan(v) else repr(float(v)) for v in row]
            out.writerow((label_at(index).isoformat(), *cells))
    return path


def _wait(child: subprocess.Popen[bytes], deadline: float) -> tuple[int, resource.struct_rusage]:
    """Wait for this child alone, so its memory is its own. Stop it at the deadline."""
    while True:
        pid, state, usage = os.wait4(child.pid, os.WNOHANG)
        if pid:
            return state, usage
        if time.perf_counter() > deadline:
            child.kill()
        time.sleep(0.05)


def run_batch(
    registry: Path, ref: ArtifactRef, data: Path, output: Path, first: int
) -> tuple[int, str, float, float]:
    """The real command line, as a child process. It returns code, errors, seconds and MB."""
    args = [
        sys.executable, "-m", "earthlab.cli", "mlops-predict", "--registry", str(registry),
        "--bundle", ref.sha256, "--input", str(data), "--output", str(output),
        "--first-issue", str(first), "--allow-research",
    ]  # fmt: skip
    with tempfile.TemporaryFile() as errors:
        begun = time.perf_counter()
        child = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=errors)  # noqa: S603
        state, usage = _wait(child, begun + COMMAND_TIMEOUT)
        seconds = time.perf_counter() - begun
        errors.seek(0)
        return (
            os.waitstatus_to_exitcode(state), errors.read().decode(errors="replace")[-500:],
            round(seconds, 3), round(usage.ru_maxrss / MEMORY_UNIT, 1),
        )  # fmt: skip


def read_output(path: Path) -> dict[int, list[float]]:
    with path.open(encoding="utf-8") as stream:
        rows = (json.loads(line) for line in stream)
        return {int(r["issue_index"]): r["values"] for r in rows}


def _kept(bundle: ModelBundleV1, saved: dict[str, np.ndarray]) -> np.ndarray:
    """What the batch command must print for each scored issue."""
    if bundle.task == "regression":
        return saved["predictions"][:, 0, :]
    return (saved["probabilities"] >= float(saved["cut"])).astype(float)


def compare(
    bundle: ModelBundleV1,
    files: authority.RunFiles,
    output: Path,
    input_sha: str,
    state: InferenceState,
) -> InferenceEvidenceV1:
    """Batch output against the scored predictions, and its MAE against the report."""
    saved, _ = authority.read_predictions(files, bundle.task)
    issues, kept = saved["issues"], _kept(bundle, saved)
    printed = read_output(output)
    absent = [int(i) for i in issues if int(i) not in printed]
    if absent:
        return InferenceEvidenceV1(
            state=state, input_sha256=input_sha, output_sha256=file_digest(output),
            note=f"{len(absent)} scored issues are missing from the batch output",
        )  # fmt: skip
    made = np.array([printed[int(i)] for i in issues])
    gap = float(np.abs(made - kept).max())
    reference, mae = None, None
    if bundle.task == "regression":
        truth = forecast_eval.read_truth(files.source)[0]
        line = forecast_eval.evaluate(truth, issues, [S.PRIMARY_HORIZON], made[:, None, :])
        report = EvaluationReportV1.model_validate_json(files.report.read_bytes())
        mae = round(line[str(S.PRIMARY_HORIZON)]["all"]["mae"], 3)
        reference = next(s for s in report.scores if s.model == files.row).metrics["mae"]
    same = gap <= MATCH_LIMIT and mae == reference
    return InferenceEvidenceV1(
        state=state, input_sha256=input_sha, output_sha256=file_digest(output),
        rows_compared=len(issues), max_abs_difference=gap, matches_reference=same,
        reference_mae=reference, output_mae=mae,
    )  # fmt: skip


def _data(folder: Path, source: Path) -> DataValidityV1:
    values = load_grid(source)[0].values[: S.SEALED_FROM]
    align = hindcast.check(source, values)
    digest = file_digest(source)
    quality = folder / "quality-report.json"
    issues = ["no quality report was saved"]
    if quality.is_file():
        saved = QualityReportV1.model_validate_json(quality.read_bytes())
        issues = list(saved.issues) if saved.source_sha256 == digest else ["another source"]
    return DataValidityV1(
        source_sha256=digest, pinned_source=digest == hindcast.PINNED_NEA,
        quality_issues=tuple(issues), alignment_verdict=align.verdict,
        alignment_findings=tuple(f"{f.code.value}: {f.detail}" for f in align.findings),
        valid=not issues and align.verdict != "not_alignable",
    )  # fmt: skip


def high_pm(bundle: ModelBundleV1, files: authority.RunFiles) -> HighPmEvidenceV1 | None:
    """Regression only: the model and the persistence reference in the elevated hours."""
    if bundle.task != "regression" or not files.report.is_file():
        return None
    report = EvaluationReportV1.model_validate_json(files.report.read_bytes())
    rows = {s.model: s for s in report.scores}
    if files.row not in rows:
        return None
    mine, base = rows[files.row], rows[report.reference]
    model, reference = mine.metrics.get("above_55_mae"), base.metrics.get("above_55_mae")
    worse = model is None or reference is None or model > reference
    return HighPmEvidenceV1(
        threshold_ug_m3=HIGH, model_mae=model, reference_mae=reference,
        model_recall=mine.subgroups.get("elevated", {}).get("recall"), worse_than_reference=worse,
    )  # fmt: skip


def _inference(
    registry: Path, ref: ArtifactRef, bundle: ModelBundleV1, files: authority.RunFiles, out: Path,
    pinned: bool,
) -> tuple[InferenceEvidenceV1, ResourceEvidenceV1]:  # fmt: skip
    data = export_input(files.source, out / f"input-{ref.sha256[:12]}.csv")
    output = out / f"predictions-{ref.sha256[:12]}.jsonl"
    saved, _ = authority.read_predictions(files, bundle.task)
    first = int(saved["issues"].min())
    code, errors, seconds, peak = run_batch(registry, ref, data, output, first)
    state: InferenceState = "real_data" if pinned else "synthetic_smoke"
    input_sha = file_digest(data)
    if code != 0:
        evidence = InferenceEvidenceV1(
            state=state, input_sha256=input_sha, note=f"exit {code}: {errors}"
        )  # fmt: skip
        return evidence, ResourceEvidenceV1()
    evidence = compare(bundle, files, output, input_sha, state)
    rows = sum(1 for _ in output.open(encoding="utf-8"))
    used = ResourceEvidenceV1(
        seconds_total=seconds, seconds_per_row=round(seconds / rows, 6), peak_rss_mb=peak,
        conditions=os.environ.get("EARTHLAB_MEASURE_CONDITIONS", "conditions not stated"),
    )  # fmt: skip
    return evidence, used


def _approval(registry: Registry, ref: ArtifactRef) -> Literal["none", "approved", "rejected"]:
    """Only the signed human path writes these entries."""
    human = [
        e["data"]["to"]
        for e in registry.log.records()
        if e["data"]["model"] == ref.sha256 and e["actor"] == "human"
    ]
    if not human:
        return "none"
    return "approved" if human[-1] == "approved" else "rejected"


def accept(
    registry_root: Path, bundle_sha: str, folder: Path, source: Path, out: Path
) -> DeploymentReadinessV1:
    """The readiness report. A refused bundle gets a report too, with no inference run."""
    out.mkdir(parents=True, exist_ok=True)
    registry, ref = Registry(registry_root), ArtifactRef(kind="record", sha256=bundle_sha)
    verified = verify_bundle(registry, ref, folder, source)
    data = _data(folder, source)
    inference = InferenceEvidenceV1(state="not_run", note="the bundle check refused this model")
    used, weakness = ResourceEvidenceV1(), None
    if verified.model_name is not None:
        bundle = registry.bundle(ref)
        files = authority.run_files(bundle, folder, source)
        weakness = high_pm(bundle, files)
        if verified.outcome != "refused":
            inference, used = _inference(registry_root, ref, bundle, files, out, data.pinned_source)
    status = registry.status(ref)
    report = DeploymentReadinessV1(
        bundle_sha256=ref.sha256, model_name=verified.model_name, scientific_label=hindcast.LABEL,
        data=data, integrity_checks=verified.checks, verification_outcome=verified.outcome,
        independent_evaluation=verified.evaluation, inference=inference, high_pm25=weakness,
        resources=used, missing_operational_evidence=MISSING,
        human_approval=_approval(registry, ref),
        readiness=readiness(status or "candidate"),
    )  # fmt: skip
    path = out / f"readiness-{ref.sha256[:12]}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return report

"""Evaluator evidence, offline bundle checks and inference acceptance, on a synthetic NEA file."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np
import pytest
from mlops_helpers import evaluate, record, report_file, stored_bundle
from pydantic import ValidationError
from test_harness_families import FAST, write_source

from earthlab.cli import main
from earthlab.digest import file_digest
from earthlab.efficiency.artifacts import ArtifactRef
from earthlab.forecast import gate
from earthlab.forecast import samples as S
from earthlab.harness import attest as authority
from earthlab.harness import hindcast
from earthlab.harness.accept import accept, compare
from earthlab.harness.contracts import EvaluationReportV1
from earthlab.harness.families_run import run_classification, run_regression
from earthlab.harness.verify import HYBRID_REFUSAL, verify_bundle
from earthlab.mlops.contracts import FeatureArtifactV1, FittedPipelineV1, ModelBundleV1
from earthlab.mlops.evidence import DeploymentReadinessV1
from earthlab.mlops.registry import IllegalStatus, Registry
from earthlab.team.resources import OPERATOR_KEY_ENV, ResourceApprovalV1, sign

KEY = "operator-test-key-value"


@dataclass(frozen=True)
class Run:
    registry: Path
    folder: Path
    source: Path
    bundles: dict[str, str]


@pytest.fixture(scope="module")
def base(tmp_path_factory: pytest.TempPathFactory) -> Run:
    root = tmp_path_factory.mktemp("verify")
    source = write_source(root / "nea.csv")
    done = run_regression(root / "run", root / "registry", source, FAST)
    bundles = {row["model"]: row["bundle"] for row in done["bundles"]}
    return Run(root / "registry", root / "run", source, bundles)


@pytest.fixture
def run(base: Run, tmp_path: Path) -> Run:
    """A private copy, so a test can damage it."""
    registry, folder = tmp_path / "registry", tmp_path / "run"
    shutil.copytree(base.registry, registry)
    shutil.copytree(base.folder, folder)
    return Run(registry, folder, base.source, base.bundles)


def ref_of(run: Run, model: str = "M_ridge") -> ArtifactRef:
    return ArtifactRef(kind="record", sha256=run.bundles[model])


def verified(run: Run, ref: ArtifactRef) -> dict[str, bool]:
    done = verify_bundle(Registry(run.registry), ref, run.folder, run.source)
    return {c.name: c.passed for c in done.checks}


def outcome(run: Run, ref: ArtifactRef) -> str:
    return verify_bundle(Registry(run.registry), ref, run.folder, run.source).outcome


def variant(run: Run, **change: object) -> ArtifactRef:
    registry = Registry(run.registry)
    bundle = registry.bundle(ref_of(run)).model_copy(update=change)
    return registry.register(bundle)


def test_a_run_stores_a_typed_record_and_its_scientific_label(base: Run) -> None:
    registry = Registry(base.registry)
    entries = [e for e in registry.log.records() if e["data"]["to"] == "evaluated"]
    assert entries and all(e["actor"] == "evaluator" for e in entries)
    kept = registry.store.get(
        ArtifactRef(kind="record", sha256=entries[0]["data"]["evaluation_record"])
    )
    assert kept["reproduction"] == "exact" and kept["passes"] is True
    summary = json.loads((base.folder / "families-regression-summary.json").read_text("utf-8"))
    assert summary["scientific_label"] == "simulated_availability_hindcast"
    saved = json.loads((base.folder / hindcast.ALIGNMENT_FILE).read_text("utf-8"))
    assert saved["arm"] == "simulated_availability_hindcast"
    assert "modelled_availability" in {f["code"] for f in saved["findings"]}


def test_a_run_stops_when_the_data_are_not_alignable(
    base: Run, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plain = hindcast.nea_plan
    monkeypatch.setattr(
        hindcast, "nea_plan",
        lambda rows: plain(rows).model_copy(update={"arm": "issue_time_forecast"}),
    )  # fmt: skip
    with pytest.raises(hindcast.NotAlignable, match="modelled latency"):
        run_regression(tmp_path / "run", tmp_path / "registry", base.source, FAST)
    assert not (tmp_path / "registry" / "status.jsonl").exists()


def test_a_record_for_another_bundle_or_input_is_refused(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    first = registry.register(stored_bundle(registry))
    other = registry.register(stored_bundle(registry, seed=2))
    report = report_file(tmp_path)
    good = record(first, registry)
    for change, words in (
        ({"bundle_sha256": other.sha256}, "different bundle"),
        ({"feature_sha256": "e" * 64}, "different feature"),
        ({"source_sha256": "e" * 64}, "different input"),
        ({"report_sha256": "e" * 64}, "not the one"),
        ({"evaluator": "someone.else"}, "not the trusted"),
        ({"evaluator_sha256": "e" * 64}, "evaluator code"),
    ):
        with pytest.raises(IllegalStatus, match=words):
            registry.evaluate(first, good.model_copy(update=change), report)
    assert registry.status(first) == "candidate"


def test_a_forged_pass_on_a_failed_row_is_refused(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    forged = record(ref, registry, False).model_copy(update={"passes": True, "reasons": ()})
    with pytest.raises(IllegalStatus, match="differs from the report"):
        registry.evaluate(ref, forged, report_file(tmp_path))
    assert registry.status(ref) == "candidate"


def test_a_pass_with_no_reproduction_does_not_promote(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    ref = registry.register(stored_bundle(registry))
    hybrid = record(ref, registry).model_copy(update={"reproduction": "unsupported_hybrid"})
    with pytest.raises(IllegalStatus, match="reproduced"):
        registry.evaluate(ref, hybrid, report_file(tmp_path))
    assert evaluate(registry, ref, tmp_path, False) == "rejected"


def test_a_clean_bundle_verifies_and_the_check_writes_nothing(run: Run) -> None:
    log = run.registry / "status.jsonl"
    before = file_digest(log)
    ref = ref_of(run)
    assert all(verified(run, ref).values())
    assert outcome(run, ref) == "verified_experimental"
    assert file_digest(log) == before


def test_swapped_weights_do_not_reproduce_the_scored_predictions(run: Run) -> None:
    registry = Registry(run.registry)
    trees = registry.bundle(ref_of(run, "M_trees"))
    ridge = registry.bundle(ref_of(run))
    state = registry.arrays(ridge.weights_sha256)
    other = registry.put_arrays({"weights": state["weights"] * 1.5})
    swapped = variant(run, weights_sha256=other)
    assert trees.weights_sha256 != other
    checks = verified(run, swapped)
    assert checks["weights"] and not checks["independent_evaluation"]
    assert outcome(run, swapped) == "refused"


def test_corrupted_weights_are_refused(run: Run) -> None:
    ref = ref_of(run)
    blob = run.registry / "blobs" / f"{Registry(run.registry).bundle(ref).weights_sha256}.npz"
    blob.write_bytes(blob.read_bytes()[:-3] + b"xyz")
    checks = verified(run, ref)
    assert not checks["weights"] and not checks["independent_evaluation"]


def _reordered(run: Run) -> ArtifactRef:
    registry = Registry(run.registry)
    bundle = registry.bundle(ref_of(run))
    feature = registry.record(bundle.feature, FeatureArtifactV1)
    fitted = registry.record(feature.fitted_pipeline, FittedPipelineV1)
    names = tuple(reversed(feature.feature_names))
    wrong = fitted.model_copy(update={"feature_names": names})
    artifact = feature.model_copy(
        update={"feature_names": names, "fitted_pipeline": registry.store.put_record(wrong)}
    )
    return variant(run, feature=registry.put_feature(wrong, artifact))


def test_a_wrong_feature_order_is_refused(run: Run) -> None:
    ref = _reordered(run)
    assert not verified(run, ref)["feature_schema"]
    assert outcome(run, ref) == "refused"


def test_missing_preprocessing_is_refused(run: Run) -> None:
    registry = Registry(run.registry)
    ref = ref_of(run)
    feature = registry.record(registry.bundle(ref).feature, FeatureArtifactV1)
    (run.registry / "objects" / f"{feature.fitted_pipeline.sha256}.json").unlink()
    done = verify_bundle(registry, ref, run.folder, run.source)
    assert done.outcome == "refused" and done.checks[0].name == "records"


def test_a_changed_report_or_prediction_file_is_refused(run: Run) -> None:
    ref = ref_of(run)
    report = run.folder / "families-regression-evaluation.json"
    original = report.read_bytes()
    report.write_bytes(original + b" ")
    assert not verified(run, ref)["independent_evaluation"]
    report.write_bytes(original)
    saved = run.folder / "predictions-M_ridge.npz"
    with np.load(saved) as held:
        arrays = {k: held[k] for k in held.files}
    arrays["predictions"] = arrays["predictions"] + 1.0
    np.savez(saved, **arrays)
    assert not verified(run, ref)["independent_evaluation"]


def test_a_recomputed_verdict_must_match_the_report(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = Registry(run.registry)
    ref = ref_of(run)
    files = authority.run_files(registry.bundle(ref), run.folder, run.source)
    monkeypatch.setattr(
        gate, "verdict",
        lambda name, _: gate.Verdict(name, False, ("the rule changed",)),
    )  # fmt: skip
    with pytest.raises(authority.EvidenceRefused, match="verdict differs"):
        authority.attest(registry, ref, files)


def test_another_source_file_is_refused(run: Run, tmp_path: Path) -> None:
    other = write_source(tmp_path / "other.csv", test_shift=1.0)
    done = verify_bundle(Registry(run.registry), ref_of(run), run.folder, other)
    assert done.outcome == "refused" and done.evaluation is None


def test_a_rejected_model_is_refused(run: Run) -> None:
    assert not verified(run, ref_of(run, "M_persistence"))["readiness"]


def test_an_unsupported_method_and_a_wrong_family_are_refused(run: Run) -> None:
    assert not verified(run, variant(run, method_id="linear"))["method"]
    assert not verified(run, variant(run, family="transfer"))["method"]


def test_a_changed_environment_or_subgroup_is_refused(run: Run) -> None:
    registry = Registry(run.registry)
    bundle = registry.bundle(ref_of(run))
    old = bundle.environment.model_copy(update={"packages": (("numpy", "0.0.1"),)})
    assert not verified(run, variant(run, environment=old))["environment"]
    assert not verified(run, variant(run, subgroups={}))["limitations"]


def test_a_hybrid_bundle_is_refused_as_unsupported(run: Run) -> None:
    registry = Registry(run.registry)
    bundle = registry.bundle(ref_of(run))
    feature = registry.store.put_record(registry.record(bundle.feature, FeatureArtifactV1))
    encoder = ArtifactRef(kind="record", sha256=feature.sha256)
    ref = variant(run, family="hybrid", encoder=encoder, method_id="frozen_gru_logistic")
    done = verify_bundle(registry, ref, run.folder, run.source)
    assert any(c.detail == HYBRID_REFUSAL for c in done.checks)
    assert done.outcome == "refused"


def _signed(ref: ArtifactRef, approved: bool) -> ResourceApprovalV1:
    body = ResourceApprovalV1(
        request_id="m", request_sha256=ref.sha256, approved=approved, approver="owner",
        decided_at_utc=datetime.now(UTC),
    )  # fmt: skip
    return body.model_copy(update={"signature": sign(body, KEY)})


def test_human_approval_and_denial_stay_separate_from_evaluation(
    run: Run, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)
    registry = Registry(run.registry)
    ridge, trees = ref_of(run), ref_of(run, "M_trees")
    registry.decide(trees, _signed(trees, False), KEY)
    assert outcome(run, trees) == "refused"
    denied = accept(run.registry, trees.sha256, run.folder, run.source, run.folder / "out")
    assert denied.human_approval == "rejected" and denied.inference.state == "not_run"
    registry.decide(ridge, _signed(ridge, True), KEY)
    assert outcome(run, ridge) == "verified_approved"


@pytest.fixture(scope="module")
def accepted(
    base: Run, tmp_path_factory: pytest.TempPathFactory
) -> tuple[DeploymentReadinessV1, Path]:
    out = tmp_path_factory.mktemp("accepted")
    return accept(base.registry, base.bundles["M_ridge"], base.folder, base.source, out), out


def test_a_synthetic_source_gives_a_labelled_smoke_test(
    base: Run, accepted: tuple[DeploymentReadinessV1, Path]
) -> None:
    out, folder = accepted
    assert out.inference.state == "synthetic_smoke" and out.inference.matches_reference
    assert out.inference.rows_compared > 0 and out.inference.max_abs_difference is not None
    assert out.inference.output_mae == out.inference.reference_mae
    assert out.data.pinned_source is False and out.data.valid
    assert out.scientific_label == "simulated_availability_hindcast"
    assert out.readiness == "research" and out.production_ready is False
    assert out.resources.seconds_total is not None and out.resources.peak_rss_mb
    assert out.high_pm25 is not None and out.human_approval == "none"
    assert out.missing_operational_evidence
    with (folder / f"input-{base.bundles['M_ridge'][:12]}.csv").open() as stream:
        assert sum(1 for _ in stream) - 1 <= S.SEALED_FROM


def test_a_refused_bundle_gets_a_report_and_no_inference(run: Run, tmp_path: Path) -> None:
    out = accept(run.registry, run.bundles["M_persistence"], run.folder, run.source, tmp_path)
    assert out.verification_outcome == "refused" and out.inference.state == "not_run"
    assert out.resources.seconds_total is None
    saved = tmp_path / f"readiness-{run.bundles['M_persistence'][:12]}.json"
    assert json.loads(saved.read_text("utf-8"))["production_ready"] is False


def test_a_readiness_record_cannot_claim_production(
    accepted: tuple[DeploymentReadinessV1, Path],
) -> None:
    data = accepted[0].model_dump(mode="json")
    with pytest.raises(ValidationError):
        DeploymentReadinessV1.model_validate({**data, "production_ready": True})
    with pytest.raises(ValidationError):
        DeploymentReadinessV1.model_validate({**data, "readiness": "deployed_production"})


def test_the_commands_report_a_refusal_by_exit_code(
    run: Run, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = ["--registry", str(run.registry), "--run", str(run.folder), "--source", str(run.source)]
    check = tmp_path / "check.json"
    good = ["mlops-verify", *args, "--bundle", run.bundles["M_ridge"], "--output", str(check)]
    assert main(good) == 0
    assert json.loads(check.read_text("utf-8"))["outcome"] == "verified_experimental"
    assert main(["mlops-verify", *args, "--bundle", run.bundles["M_persistence"]]) == 2
    bad = ["mlops-accept", *args, "--bundle", run.bundles["M_persistence"], "--out", str(tmp_path)]
    assert main(bad) == 2
    capsys.readouterr()


def test_a_classifier_is_recomputed_and_compared_by_its_alarms(run: Run, tmp_path: Path) -> None:
    done = run_classification(tmp_path / "s2", tmp_path / "registry", run.source, FAST)
    registry = Registry(tmp_path / "registry")
    row = next(b for b in done["bundles"] if b["model"] == "logistic")
    ref = ArtifactRef(kind="record", sha256=row["bundle"])
    bundle = registry.bundle(ref)
    files = authority.run_files(bundle, tmp_path / "s2", run.source)
    made = authority.attest(registry, ref, files)
    assert made.reproduction == "exact" and made.passes == (row["status"] == "evaluated")
    saved, _ = authority.read_predictions(files, "classification")
    alarms = (saved["probabilities"] >= float(saved["cut"])).astype(float)
    output = tmp_path / "out.jsonl"
    lines = [
        json.dumps({"issue_index": int(i), "values": v.tolist()})
        for i, v in zip(saved["issues"], alarms, strict=True)
    ]
    output.write_text("\n".join(lines) + "\n", "utf-8")
    evidence = compare(bundle, files, output, "a" * 64, "synthetic_smoke")
    assert evidence.matches_reference and evidence.max_abs_difference == 0.0
    output.write_text(lines[0] + "\n", "utf-8")
    assert not compare(bundle, files, output, "a" * 64, "synthetic_smoke").matches_reference


def test_the_report_row_needs_a_trusted_evaluator(run: Run) -> None:
    path = run.folder / "families-regression-evaluation.json"
    report = EvaluationReportV1.model_validate_json(path.read_bytes())
    path.write_text(report.model_copy(update={"evaluator": "a.b"}).model_dump_json(), "utf-8")
    ref = variant(run, evaluation_sha256=file_digest(path))
    assert not verified(run, ref)["independent_evaluation"]


def test_a_bundle_with_no_report_is_refused(run: Run) -> None:
    ref = variant(run, evaluation_sha256=None)
    assert not verified(run, ref)["independent_evaluation"]
    assert isinstance(Registry(run.registry).bundle(ref), ModelBundleV1)

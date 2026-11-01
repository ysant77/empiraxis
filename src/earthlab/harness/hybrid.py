"""The frozen-encoder path for scenario S2: export, manifest, reuse checks and embeddings.

The encoder comes from a model trained in the isolated environment. Export runs the approved
template there. Everything after that is numpy on plain arrays: the manifest is read from
the training job files by code, not claimed by a person, and reuse is refused with reasons
unless the checks in `earthlab.mlops.encoder` pass.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from earthlab.digest import file_digest
from earthlab.efficiency.artifacts import ArtifactRef
from earthlab.forecast import samples as S
from earthlab.forecast.isolated import python_for_training, run_isolated
from earthlab.forecast.pipeline import FeatureSpec, Workbench
from earthlab.mlops import encoder as enc
from earthlab.mlops.contracts import Span
from earthlab.mlops.registry import Registry

TEMPLATE = Path(__file__).parents[1] / "forecast" / "templates_export_encoder.py"
EXPORT_TIMEOUT = 300.0
HORIZON_PAD = max(S.HORIZONS)


def export_encoder(
    registry: Registry, train_dir: Path, features_path: Path, source_sha256: str, revision: str
) -> ArtifactRef:
    """Export a trained GRU's weights and write its manifest from the job's own files."""
    job = json.loads((train_dir / "job.json").read_text(encoding="utf-8"))
    report = json.loads((train_dir / "training.json").read_text(encoding="utf-8"))
    model = train_dir / "model.pt"
    if file_digest(model) != report["model_sha256"]:
        raise enc.ReuseRefused("model.pt does not match the digest in training.json")
    if job["architecture"] != "gru":
        raise enc.ReuseRefused("only a GRU can be exported as an encoder")
    with np.load(features_path) as saved:
        arrays = {k: saved[k] for k in saved.files}
    out = train_dir / "export"
    out.mkdir(exist_ok=True)
    (out / "job.json").write_text(
        json.dumps({"model": str(model.resolve()), "layers": job["layers"]}), encoding="utf-8"
    )
    run = run_isolated(python_for_training(), TEMPLATE, out, [str(out)], EXPORT_TIMEOUT, 1)
    if run.exit_code != 0:
        raise enc.ReuseRefused(f"the export failed: {run.output_tail}")
    return write_manifest(
        registry, out / "encoder.npz", job, report, arrays, source_sha256, revision
    )


def write_manifest(
    registry: Registry, weights_path: Path, job: dict[str, object], report: dict[str, object],
    arrays: dict[str, np.ndarray], source_sha256: str, revision: str,
) -> ArtifactRef:  # fmt: skip
    """Spans come from the issue lists the job trained and selected on."""
    with np.load(weights_path) as saved:
        weights = {k: saved[k] for k in saved.files}
    train, valid = arrays["train_issues"], arrays["valid_issues"]
    manifest = enc.EncoderManifestV1(
        architecture="gru", hidden=int(str(job["hidden"])), layers=int(str(job["layers"])),
        inputs=int(weights["weight_ih_l0"].shape[1]), window=int(str(job["window"])),
        offset=int(str(job["offset"])), channels=enc.CHANNELS,
        preprocessing_sha256=enc.preprocessing_digest(arrays), source_sha256=source_sha256,
        train_span=Span(first=int(train.min()), last=int(train.max()) + HORIZON_PAD),
        selection_span=Span(first=int(valid.min()), last=int(valid.max()) + HORIZON_PAD),
        weights_sha256=registry.put_arrays(weights), model_sha256=str(report["model_sha256"]),
        code_revision=revision,
    )  # fmt: skip
    return registry.store.put_record(manifest)


def load_encoder(
    registry: Registry, ref: ArtifactRef
) -> tuple[enc.EncoderManifestV1, dict[str, np.ndarray]]:
    manifest = registry.record(ref, enc.EncoderManifestV1)
    return manifest, registry.arrays(manifest.weights_sha256)


def embeddings(
    registry: Registry, ref: ArtifactRef, folder: Path, source: Path,
    issues: dict[str, np.ndarray], scored: str,
) -> tuple[dict[str, np.ndarray], ArtifactRef]:  # fmt: skip
    """Embeddings per split, or ReuseRefused. The inputs are rebuilt here, never trusted."""
    manifest, weights = load_encoder(registry, ref)
    bench = Workbench(folder, source)
    built = bench.build_features(FeatureSpec(manifest.window, True))
    with np.load(built["path"]) as saved:
        arrays = {k: saved[k] for k in enc.CHANNELS}
    hits = issues[scored]
    enc.check_reuse(
        manifest, architecture="gru", preprocessing_sha256=enc.preprocessing_digest(arrays),
        source_sha256=bench.truth_sha, train_end=S.split_bounds("train")[1],
        scored=Span(first=int(hits.min()), last=int(hits.max()) + HORIZON_PAD),
    )  # fmt: skip
    return {k: enc.embed(manifest, weights, arrays, v) for k, v in issues.items()}, ref

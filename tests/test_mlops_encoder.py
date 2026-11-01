"""The frozen encoder: numpy GRU maths, the reuse boundary and the hybrid bundle rules."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from mlops_helpers import KEY, NAMES, SHA, approve, series, stored_bundle, times
from pydantic import ValidationError

from earthlab.efficiency.artifacts import ArtifactRef
from earthlab.mlops import encoder as enc
from earthlab.mlops import families
from earthlab.mlops.contracts import Span
from earthlab.mlops.families import Facts
from earthlab.mlops.registry import Registry
from earthlab.mlops.serve import InputRefused, predict_batch
from earthlab.team.resources import OPERATOR_KEY_ENV

HIDDEN, INPUTS, STEPS = 4, 14, 6


@pytest.fixture(autouse=True)
def operator_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(OPERATOR_KEY_ENV, KEY)


def weights(seed: int = 0, layers: int = 1) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(seed)
    out: dict[str, np.ndarray] = {}
    for k in range(layers):
        width = INPUTS if k == 0 else HIDDEN
        out[f"weight_ih_l{k}"] = rng.normal(0, 0.5, (3 * HIDDEN, width))
        out[f"weight_hh_l{k}"] = rng.normal(0, 0.5, (3 * HIDDEN, HIDDEN))
        out[f"bias_ih_l{k}"] = rng.normal(0, 0.1, 3 * HIDDEN)
        out[f"bias_hh_l{k}"] = rng.normal(0, 0.1, 3 * HIDDEN)
    return out


def manifest(**change: object) -> enc.EncoderManifestV1:
    base = enc.EncoderManifestV1(
        architecture="gru", hidden=HIDDEN, layers=1, inputs=INPUTS, window=STEPS, offset=2,
        channels=enc.CHANNELS, preprocessing_sha256=SHA, source_sha256=SHA,
        train_span=Span(first=10, last=1_000), selection_span=Span(first=1_001, last=2_000),
        weights_sha256=SHA, model_sha256=SHA, code_revision="abc",
    )  # fmt: skip
    return base.model_copy(update=change)


def reference(w: dict[str, np.ndarray], window: np.ndarray) -> np.ndarray:
    """One window, written gate by gate, as a second code path for the batched version."""
    h = np.zeros(HIDDEN)
    gate = [slice(i * HIDDEN, (i + 1) * HIDDEN) for i in range(3)]

    def sig(v: np.ndarray) -> np.ndarray:
        return np.asarray(1 / (1 + np.exp(-v)))

    def part(name: str, i: int, vector: np.ndarray) -> np.ndarray:
        return np.asarray(w[f"weight_{name}_l0"][gate[i]] @ vector + w[f"bias_{name}_l0"][gate[i]])

    for step in window:
        r = sig(part("ih", 0, step) + part("hh", 0, h))
        z = sig(part("ih", 1, step) + part("hh", 1, h))
        n = np.tanh(part("ih", 2, step) + r * part("hh", 2, h))
        h = (1 - z) * n + z * h
    return h


def test_the_numpy_gru_matches_a_gate_by_gate_reference() -> None:
    w = weights()
    x = np.random.default_rng(1).normal(size=(5, STEPS, INPUTS))
    got = enc.encode(manifest(), w, x)
    assert got.shape == (5, HIDDEN)
    np.testing.assert_allclose(got, [reference(w, row) for row in x], atol=1e-12)


def test_a_two_layer_encoder_stacks_the_layers() -> None:
    w = weights(layers=2)
    x = np.random.default_rng(2).normal(size=(3, STEPS, INPUTS))
    two = enc.encode(manifest(layers=2), w, x)
    first = enc._layer(x, *(w[f"{k}_l0"] for k in ("weight_ih", "weight_hh", "bias_ih", "bias_hh")))
    second = enc._layer(
        first, *(w[f"{k}_l1"] for k in ("weight_ih", "weight_hh", "bias_ih", "bias_hh"))
    )
    np.testing.assert_allclose(two, second[:, -1])


def test_the_wrong_input_width_is_refused() -> None:
    with pytest.raises(enc.ReuseRefused, match="input width"):
        enc.encode(manifest(), weights(), np.zeros((2, STEPS, INPUTS + 1)))


def arrays(rows: int = 200) -> dict[str, np.ndarray]:
    rng = np.random.default_rng(3)
    return {
        "series": rng.normal(size=(rows, 5)), "mask": np.ones((rows, 5)),
        "calendar": rng.normal(size=(rows, 4)),
    }  # fmt: skip


def test_an_embedding_never_reads_a_row_after_its_availability_time() -> None:
    data, issue = arrays(), np.array([100])
    base = enc.embed(manifest(), weights(), data, issue)
    changed = {k: v.copy() for k, v in data.items()}
    for v in changed.values():
        v[99:] = 50.0  # issue minus offset is row 98
    np.testing.assert_array_equal(base, enc.embed(manifest(), weights(), changed, issue))
    for v in changed.values():
        v[98] = 50.0
    assert not np.array_equal(base, enc.embed(manifest(), weights(), changed, issue))


def test_a_window_before_the_first_row_is_refused() -> None:
    with pytest.raises(enc.ReuseRefused, match="before the first row"):
        enc.windows(arrays(), np.array([3]), STEPS, 2)


def test_batches_give_the_same_embeddings_as_one_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    data, issues = arrays(), np.arange(20, 120)
    whole = enc.embed(manifest(), weights(), data, issues)
    monkeypatch.setattr(enc, "BATCH", 7)
    np.testing.assert_allclose(enc.embed(manifest(), weights(), data, issues), whole)


def ready(**change: object) -> None:
    args: dict[str, object] = {
        "architecture": "gru", "preprocessing_sha256": SHA, "source_sha256": SHA,
        "train_end": 1_000, "scored": Span(first=3_000, last=4_000),
    }  # fmt: skip
    enc.check_reuse(manifest(), **{**args, **change})  # type: ignore[arg-type]


def test_a_matching_encoder_selected_before_the_scored_years_is_accepted() -> None:
    ready()


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"architecture": "tcn"}, "architecture"),
        ({"preprocessing_sha256": "b" * 64}, "preprocessing digest"),
        ({"source_sha256": "c" * 64}, "source data"),
        ({"train_end": 500}, "past the classifier's train end"),
        ({"scored": Span(first=1_500, last=2_500)}, "selected on samples"),
        ({"scored": Span(first=1_001, last=1_001)}, "selected on samples"),
        ({"scored": Span(first=2_000, last=2_100)}, "selected on samples"),
    ],
)
def test_every_mismatch_refuses_reuse(change: dict[str, object], reason: str) -> None:
    with pytest.raises(enc.ReuseRefused, match=reason):
        ready(**change)


def test_an_undeclared_selection_span_or_other_channels_refuse_reuse() -> None:
    with pytest.raises(enc.ReuseRefused, match="not declared"):
        enc.check_reuse(
            manifest(selection_span=None), architecture="gru", preprocessing_sha256=SHA,
            source_sha256=SHA, train_end=1_000, scored=Span(first=3_000, last=4_000),
        )  # fmt: skip
    with pytest.raises(enc.ReuseRefused, match="channels"):
        enc.check_reuse(
            manifest(channels=("series",)), architecture="gru", preprocessing_sha256=SHA,
            source_sha256=SHA, train_end=1_000, scored=Span(first=3_000, last=4_000),
        )  # fmt: skip


def test_all_reasons_are_reported_together() -> None:
    with pytest.raises(enc.ReuseRefused) as caught:
        ready(architecture="tcn", preprocessing_sha256="b" * 64)
    assert "architecture" in str(caught.value) and "preprocessing" in str(caught.value)


def test_the_preprocessing_digest_changes_with_any_input_array() -> None:
    data = arrays()
    base = enc.preprocessing_digest(data)
    data["mask"][3, 1] = 0.0
    assert enc.preprocessing_digest(data) != base


def test_the_hybrid_method_is_blocked_until_an_encoder_passes() -> None:
    plain = Facts("classification", 5_000, 400, True, True)
    assert families.eligible(plain)["frozen_gru_logistic"] == (
        "no frozen encoder passed the reuse checks"
    )
    from dataclasses import replace

    ok = replace(plain, pretrained_approved=True)
    assert families.eligible(ok)["frozen_gru_logistic"] is None
    rare = replace(ok, positives=3)
    assert "positive labels" in str(families.eligible(rare)["frozen_gru_logistic"])
    assert families.METHODS["frozen_gru_logistic"].family == "hybrid"


def test_a_hybrid_bundle_must_name_its_encoder_and_no_other_may(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    plain = stored_bundle(registry)
    ref = ArtifactRef(kind="record", sha256=SHA)
    with pytest.raises(ValidationError, match="names its frozen encoder"):
        type(plain).model_validate({**plain.model_dump(), "family": "hybrid"})
    with pytest.raises(ValidationError, match="names its frozen encoder"):
        type(plain).model_validate({**plain.model_dump(), "encoder": ref.model_dump()})
    hybrid = type(plain).model_validate(
        {**plain.model_dump(), "family": "hybrid", "encoder": ref.model_dump()}
    )
    assert hybrid.encoder == ref


def test_serving_refuses_a_hybrid_bundle(tmp_path: Path) -> None:
    registry = Registry(tmp_path / "r")
    plain = stored_bundle(registry)
    hybrid = type(plain).model_validate(
        {**plain.model_dump(), "family": "hybrid",
         "encoder": ArtifactRef(kind="record", sha256=SHA).model_dump()}
    )  # fmt: skip
    ref = registry.register(hybrid)
    approve(registry, ref, tmp_path)
    issues = np.array([120])
    with pytest.raises(InputRefused, match="hybrid"):
        predict_batch(registry, ref, series(), NAMES, SHA, issues, times(issues))

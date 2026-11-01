"""A frozen sequence encoder from an earlier model, applied in numpy, with a reuse boundary.

The weights are plain arrays exported by the approved template. Reuse is allowed only when
the encoder's architecture, input channels and preprocessing digest equal what the new task
builds, and only when no sample that scores the new model was used to train or select the
encoder. Anything else raises with every reason found, and no embedding is computed.
"""

from __future__ import annotations

import hashlib
from typing import Literal

import numpy as np
from pydantic import Field

from earthlab.contracts import Strict
from earthlab.mlops.contracts import Sha, Span

CHANNELS = ("series", "mask", "calendar")
BATCH = 4096


class ReuseRefused(ValueError):
    """The encoder may not serve this task. The message lists each reason."""


class EncoderManifestV1(Strict):
    """What an exported encoder was trained on, read from its job files by code."""

    schema_version: Literal["1"] = "1"
    architecture: Literal["gru"]
    hidden: int = Field(ge=1)
    layers: int = Field(ge=1)
    inputs: int = Field(ge=1)
    window: int = Field(ge=1)
    offset: int = Field(ge=0)
    channels: tuple[str, ...]
    preprocessing_sha256: Sha
    source_sha256: Sha
    train_span: Span
    selection_span: Span | None
    weights_sha256: Sha
    model_sha256: Sha
    code_revision: str


def preprocessing_digest(arrays: dict[str, np.ndarray]) -> str:
    """The digest of the exact input arrays a window is cut from."""
    sha = hashlib.sha256()
    for name in CHANNELS:
        array = np.ascontiguousarray(arrays[name])
        sha.update(f"{name}:{array.dtype}:{array.shape}".encode())
        sha.update(array.tobytes())
    return sha.hexdigest()


def check_reuse(
    manifest: EncoderManifestV1, *, architecture: str, preprocessing_sha256: str,
    source_sha256: str, train_end: int, scored: Span,
) -> None:  # fmt: skip
    """Raise unless every rule holds. `scored` is the first issue to the last target scored."""
    why: list[str] = []
    if manifest.architecture != architecture:
        why.append(f"architecture {manifest.architecture} is not {architecture}")
    if manifest.channels != CHANNELS:
        why.append("the input channels differ from the registered schema")
    if manifest.preprocessing_sha256 != preprocessing_sha256:
        why.append("the preprocessing digest differs")
    if manifest.source_sha256 != source_sha256:
        why.append("the source data digest differs")
    if manifest.train_span.last > train_end:
        why.append("the encoder trained on samples past the classifier's train end")
    chosen = manifest.selection_span
    if chosen is None:
        why.append("the encoder's selection span is not declared")
    elif chosen.first <= scored.last and scored.first <= chosen.last:
        why.append("the encoder was selected on samples that the new model would be scored on")
    if why:
        raise ReuseRefused("; ".join(why))


def _sigmoid(value: np.ndarray) -> np.ndarray:
    return np.asarray(1 / (1 + np.exp(-np.clip(value, -30, 30))))


def _layer(
    x: np.ndarray, w_ih: np.ndarray, w_hh: np.ndarray, b_ih: np.ndarray, b_hh: np.ndarray
) -> np.ndarray:
    """One GRU layer over (samples, steps, inputs). Gate order is reset, update, new."""
    size = w_hh.shape[1]
    state = np.zeros((len(x), size))
    steps = []
    for t in range(x.shape[1]):
        gi, gh = x[:, t] @ w_ih.T + b_ih, state @ w_hh.T + b_hh
        reset = _sigmoid(gi[:, :size] + gh[:, :size])
        update = _sigmoid(gi[:, size : 2 * size] + gh[:, size : 2 * size])
        new = np.tanh(gi[:, 2 * size :] + reset * gh[:, 2 * size :])
        state = (1 - update) * new + update * state
        steps.append(state)
    return np.stack(steps, axis=1)


def encode(
    manifest: EncoderManifestV1, weights: dict[str, np.ndarray], x: np.ndarray
) -> np.ndarray:
    """The last hidden state of each window, shape (samples, hidden)."""
    if x.ndim != 3 or x.shape[2] != manifest.inputs:
        raise ReuseRefused("the windows do not have the encoder's input width")
    layer = x
    for k in range(manifest.layers):
        keys = (f"weight_ih_l{k}", f"weight_hh_l{k}", f"bias_ih_l{k}", f"bias_hh_l{k}")
        layer = _layer(layer, *(weights[key] for key in keys))
    return np.asarray(layer[:, -1])


def windows(
    arrays: dict[str, np.ndarray], issues: np.ndarray, width: int, offset: int
) -> np.ndarray:
    """(samples, width, channels), each window ending at the newest usable label, T - offset."""
    rows = (issues - offset)[:, None] + np.arange(-width + 1, 1)
    if rows.min() < 0:
        raise ReuseRefused("a window starts before the first row")
    return np.concatenate([arrays[name][rows] for name in CHANNELS], axis=2).astype(float)


def embed(
    manifest: EncoderManifestV1, weights: dict[str, np.ndarray], arrays: dict[str, np.ndarray],
    issues: np.ndarray,
) -> np.ndarray:  # fmt: skip
    """Embeddings in batches, so the full window array never sits in memory."""
    parts = [
        encode(
            manifest, weights,
            windows(arrays, issues[start : start + BATCH], manifest.window, manifest.offset),
        )
        for start in range(0, len(issues), BATCH)
    ]  # fmt: skip
    return np.concatenate(parts) if parts else np.empty((0, manifest.hidden))

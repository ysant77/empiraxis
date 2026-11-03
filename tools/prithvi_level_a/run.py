"""Level A: one pretrained Prithvi-EO-2.0-300M-BurnScars inference on one published HLS chip.

Runs in its own environment (terratorch), not in the EarthLab package environment. It reads
only local, hash-checked files under a signed resource approval, downloads nothing, trains
nothing and loads the checkpoint with weights_only=True. The chip is from the publisher's test
split, so the score is a reproduction on published data, not an independent generalization test.

Usage: python tools/prithvi_level_a/run.py <weights.pt> <config.yaml> <image.tif> <mask.tif> <out>
"""

from __future__ import annotations

import hashlib
import json
import platform
import resource
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import tifffile
import torch
import yaml

WEIGHTS_SHA256 = "0c5f9334be9a75c9006387ab8f3dc05a55ea7fb5ef7956717316be57c62954d3"
LABELS = {0: "not burned", 1: "burn scar", -1: "no label (ignored)"}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 22), b""):
            digest.update(block)
    return digest.hexdigest()


def build(config: dict[str, Any], weights: Path) -> torch.nn.Module:
    from terratorch.models import EncoderDecoderFactory

    args = dict(config["model"]["init_args"]["model_args"])
    args["backbone_pretrained"] = False  # the approved checkpoint holds every weight
    model = EncoderDecoderFactory().build_model(task="segmentation", **args)
    saved = torch.load(weights, map_location="cpu", weights_only=True)
    state = saved.get("state_dict", saved)
    state = {k.removeprefix("model."): v for k, v in state.items()}
    model.load_state_dict(state, strict=True)
    return model.eval()


def scores(pred: np.ndarray, truth: np.ndarray) -> dict[str, Any]:
    valid = truth >= 0
    p, t = pred[valid] == 1, truth[valid] == 1
    tp, fp, fn = int((p & t).sum()), int((p & ~t).sum()), int((~p & t).sum())
    return {
        "valid_pixels": int(valid.sum()), "ignored_pixels": int((~valid).sum()),
        "reference_burn_pixels": int(t.sum()), "predicted_burn_pixels": int(p.sum()),
        "iou_burn": tp / (tp + fp + fn) if tp + fp + fn else None,
        "precision_burn": tp / (tp + fp) if tp + fp else None,
        "recall_burn": tp / (tp + fn) if tp + fn else None,
        "pixel_accuracy": float((p == t).mean()),
    }  # fmt: skip


def main(weights: Path, config_path: Path, image: Path, mask: Path, out: Path) -> int:
    if sha256(weights) != WEIGHTS_SHA256:
        raise SystemExit("the weights do not match the approved digest")
    config = yaml.safe_load(config_path.read_text())
    data = config["data"]["init_args"]
    raw = tifffile.imread(image).astype(np.float32)  # (512, 512, 6), reflectance 0 to 1
    nodata = ~np.isfinite(raw) | (raw <= -9000)
    raw[nodata] = data["no_data_replace"]
    mean, std = np.array(data["means"], np.float32), np.array(data["stds"], np.float32)
    x = torch.from_numpy(((raw - mean) / std).transpose(2, 0, 1)[None].copy())
    truth = tifffile.imread(mask).astype(np.int16)
    torch.manual_seed(0)
    started = time.perf_counter()
    model = build(config, weights)
    loaded = time.perf_counter()
    with torch.no_grad():
        logits = model(x).output
    done = time.perf_counter()
    pred = logits.argmax(dim=1)[0].numpy().astype(np.int16)
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "prediction.npy", pred)
    record = {
        "level": "A", "kind": "reproduction on the publisher's test split",
        "model": "Prithvi-EO-2.0-300M-BurnScars", "weights_sha256": WEIGHTS_SHA256,
        "config_sha256": sha256(config_path), "image": image.name, "image_sha256": sha256(image),
        "mask_sha256": sha256(mask), "input_shape": list(raw.shape),
        "nodata_pixels": int(nodata.sum()),
        "bands": data["output_bands"], "labels": LABELS,
        "logits_shape": list(logits.shape), "scores": scores(pred, truth),
        "seconds": {"load": round(loaded - started, 2), "inference": round(done - loaded, 2)},
        "peak_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 2**20, 1),
        "prediction_sha256": sha256(out / "prediction.npy"),
        "environment": {"python": platform.python_version(), "torch": torch.__version__,
                        "device": "cpu", "machine": platform.machine()},
    }  # fmt: skip
    (out / "result.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps({k: record[k] for k in ("scores", "seconds", "peak_rss_mb")}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main(*(Path(a).expanduser() for a in sys.argv[1:6])))

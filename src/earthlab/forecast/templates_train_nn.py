"""The approved training template. It runs alone, in the isolated environment.

No generated code runs here. An agent chooses values from a fixed menu, and this file reads
them from one JSON job. It imports only the standard library, numpy and torch, reads one
NPZ, writes into one folder, and has no network. The file it reads ends before the test
period, so no training or selection can touch that period.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from torch import nn

CHECKPOINT = "checkpoint.pt"


class Gru(nn.Module):  # type: ignore[misc]
    def __init__(self, inputs: int, hidden: int, layers: int, outputs: int):
        super().__init__()
        self.rnn = nn.GRU(inputs, hidden, layers, batch_first=True)
        self.head = nn.Linear(hidden, outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out, _ = self.rnn(x)
        return self.head(out[:, -1])


class Block(nn.Module):  # type: ignore[misc]
    def __init__(self, channels: int, dilation: int):
        super().__init__()
        self.pad = 2 * dilation
        self.conv = nn.Conv1d(channels, channels, 3, dilation=dilation)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = torch.relu(self.conv(nn.functional.pad(x, (self.pad, 0))))
        return x + out


class TemporalCnn(nn.Module):  # type: ignore[misc]
    def __init__(self, inputs: int, hidden: int, layers: int, outputs: int):
        super().__init__()
        self.enter = nn.Conv1d(inputs, hidden, 1)
        self.blocks = nn.Sequential(*[Block(hidden, 2**i) for i in range(layers * 3)])
        self.head = nn.Linear(hidden, outputs)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        out = self.blocks(self.enter(x.transpose(1, 2)))
        return self.head(out[:, :, -1])


def windows(data: dict[str, np.ndarray], issues: np.ndarray, width: int, offset: int) -> np.ndarray:
    """(samples, width, channels). Each window ends at the newest usable label, T - offset."""
    last = issues - offset
    rows = last[:, None] + np.arange(-width + 1, 1)
    return np.concatenate(
        [data["series"][rows], data["mask"][rows], data["calendar"][rows]], axis=2
    )


def loss_of(pred: torch.Tensor, y: torch.Tensor, known: torch.Tensor, name: str) -> torch.Tensor:
    if name == "huber":
        error = nn.functional.huber_loss(pred, y, reduction="none")
    else:
        error = (pred - y).abs()
    return (error * known).sum() / known.sum().clamp(min=1)


def predict(
    model: nn.Module, data: dict[str, np.ndarray], issues: np.ndarray, job: dict[str, Any]
) -> np.ndarray:
    outs = []
    with torch.no_grad():
        for start in range(0, len(issues), 1024):
            batch = issues[start : start + 1024]
            x = torch.from_numpy(windows(data, batch, job["window"], job["offset"])).float()
            outs.append(model(x).numpy())
    return np.concatenate(outs)


def one_epoch(
    model: Any, optimiser: Any, data: dict[str, np.ndarray], job: dict[str, Any],
    order: np.ndarray, soft: np.ndarray | None,
) -> float:  # fmt: skip
    """One pass. With a teacher, the loss blends the labels and the teacher's values."""
    train, blend, total = data["train_issues"], float(job.get("soft_weight", 0.0)), 0.0
    for start in range(0, len(order), job["batch"]):
        take = order[start : start + job["batch"]]
        x = torch.from_numpy(windows(data, train[take], job["window"], job["offset"])).float()
        y = torch.from_numpy(data["train_y"][take]).float()
        known = torch.from_numpy(data["train_known"][take]).float()
        pred = model(x)
        loss = loss_of(pred, y, known, job["loss"])
        if soft is not None:
            teacher = torch.from_numpy(soft[take]).float()
            mimic = loss_of(pred, teacher, torch.ones_like(teacher), job["loss"])
            loss = (1 - blend) * loss + blend * mimic
        optimiser.zero_grad()
        loss.backward()
        nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        optimiser.step()
        total += float(loss) * len(take)
    return total


def restore(model: Any, optimiser: Any, rng: Any, out: Path) -> tuple[float, int, list[Any], int]:
    """The last finished epoch of an interrupted job, or a clean start."""
    path = out / CHECKPOINT
    if not path.is_file():
        return float("inf"), 0, [], 0
    saved = torch.load(path, weights_only=False)
    model.load_state_dict(saved["model"])
    optimiser.load_state_dict(saved["optimiser"])
    rng.bit_generator.state = saved["rng"]
    print(json.dumps({"resumed_after_epoch": saved["progress"][3]}), flush=True)
    best, stale, history, first = saved["progress"]
    return best, stale, history, first


def save_point(
    model: Any, optimiser: Any, rng: Any, out: Path, progress: tuple[float, int, list[Any], int]
) -> None:
    partial = out / f"{CHECKPOINT}.part"
    torch.save(
        {"model": model.state_dict(), "optimiser": optimiser.state_dict(),
         "rng": rng.bit_generator.state, "progress": progress},
        partial,
    )  # fmt: skip
    partial.replace(out / CHECKPOINT)


def fit(data: dict[str, np.ndarray], job: dict[str, Any], out: Path) -> dict[str, Any]:
    torch.manual_seed(job["seed"])
    rng = np.random.default_rng(job["seed"])
    train, valid = data["train_issues"], data["valid_issues"]
    y_all = data["train_y"]
    inputs = data["series"].shape[1] * 2 + data["calendar"].shape[1]
    make: Any = {"gru": Gru, "tcn": TemporalCnn}[job["architecture"]]
    model: Any = make(inputs, job["hidden"], job["layers"], y_all.shape[1])
    optimiser = torch.optim.Adam(model.parameters(), lr=job["learning_rate"])
    soft = np.load(job["soft"]) if job.get("soft") else None
    best, stale, history, first = restore(model, optimiser, rng, out)
    started = time.perf_counter()
    for epoch in range(first, job["max_epochs"]):
        model.train()
        order = rng.permutation(len(train))
        total = one_epoch(model, optimiser, data, job, order, soft)
        model.eval()
        pred = predict(model, data, valid, job)
        known = data["valid_known"]
        score = float((np.abs(pred - data["valid_y"]) * known).sum() / known.sum())
        history.append({"epoch": epoch + 1, "train": total / len(order), "valid": score})
        print(json.dumps(history[-1]), flush=True)
        if score < best - 1e-5:
            best, stale = score, 0
            torch.save(model.state_dict(), out / "model.pt")
        else:
            stale += 1
            if stale >= job["patience"]:
                break
        save_point(model, optimiser, rng, out, (best, stale, history, epoch + 1))
    model.load_state_dict(torch.load(out / "model.pt", weights_only=True))
    model.eval()
    timed = time.perf_counter()
    np.save(out / "valid_scaled.npy", predict(model, data, valid, job))
    predict_seconds = time.perf_counter() - timed
    if job.get("save_train"):
        np.save(out / "train_scaled.npy", predict(model, data, train, job))
    return {
        "history": history,
        "epochs_run": len(history),
        "train_seconds": round(time.perf_counter() - started, 2),
        "predict_seconds": round(predict_seconds, 3),
        "parameters": sum(p.numel() for p in model.parameters()),
        "model_sha256": hashlib.sha256((out / "model.pt").read_bytes()).hexdigest(),
        "torch": torch.__version__,
    }


def main() -> int:
    out = Path(sys.argv[1])
    job = json.loads((out / "job.json").read_text(encoding="utf-8"))
    torch.set_num_threads(job["threads"])
    with np.load(job["data"]) as loaded:
        data = {k: loaded[k] for k in loaded.files}
    report = fit(data, job, out)
    (out / "training.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

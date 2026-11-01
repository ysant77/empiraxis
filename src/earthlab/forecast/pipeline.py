"""The deterministic steps every arm shares. Agents choose values; this code does the work.

Each step writes a content-addressed artifact and returns a small reference. Prompts carry
references and summaries, never the dataset, a source file or a training log.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.digest import file_digest, payload_digest
from earthlab.forecast import samples as S
from earthlab.forecast.dataset import Audit, Grid, index_of, label_at, load_grid
from earthlab.forecast.evaluator import evaluate, read_truth
from earthlab.forecast.isolated import IsolatedRun, python_for_training, run_isolated

SOURCE = Path("data/nea/Historical1hrPM2.5.csv")
TEMPLATE = Path(__file__).with_name("templates_train_nn.py")
RIDGE_ALPHAS = (1.0, 10.0, 100.0, 1000.0, 10000.0)
RIDGE_LAGS = 24
THREADS = 4
SEED = 20261101
TRAIN_TIMEOUT = 1800.0
EPISODES = ((2019, 9), (2019, 11), (2023, 10))


@dataclass(frozen=True)
class FeatureSpec:
    window: int = 48
    log_transform: bool = True
    exclude_2015_haze: bool = False


@dataclass(frozen=True)
class TrainSpec:
    architecture: str = "gru"
    hidden: int = 32
    layers: int = 1
    max_epochs: int = 12
    loss: str = "mae"
    learning_rate: float = 0.001
    seed: int = SEED
    soft: str | None = None  # teacher predictions on the train samples, scaled
    soft_weight: float = 0.0
    save_train: bool = False


class Workbench:
    """One experiment folder. Every call is deterministic given its spec."""

    def __init__(self, folder: Path, source: Path = SOURCE):
        self.folder, self.source = folder, source
        folder.mkdir(parents=True, exist_ok=True)
        self.grid: Grid
        self.audit: Audit
        self.grid, self.audit = load_grid(source)
        self.truth, self.truth_sha = read_truth(source)
        self.features: dict[str, dict[str, Any]] = {}
        self.results: dict[str, dict[str, Any]] = {}

    def _save(self, name: str, payload: dict[str, Any]) -> dict[str, str]:
        path = self.folder / name
        path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        return {"artifact": name, "sha256": file_digest(path)}

    def profile(self) -> dict[str, Any]:
        """The versioned data profile and partitions, and a short summary for prompts."""
        splits = {}
        for split in ("train", "validation", "test"):
            first, last = S.split_bounds(split)
            part = self.grid.values[first : last + 1]
            splits[split] = {
                "first": label_at(first).isoformat(),
                "last": label_at(last).isoformat(),
                "hours": last - first + 1,
                "missing_cells": int(np.isnan(part).sum()),
                "peak_above_55_hours": int((np.nan_to_num(part).max(axis=1) > 55).sum()),
            }
        ref = self._save(
            "data_profile.json",
            {"audit": asdict(self.audit), "splits": splits, "latency_hours": S.LATENCY_HOURS},
        )
        summary = {
            "hours": self.audit.grid_hours, "duplicates": self.audit.duplicate_labels,
            "conflicts": len(self.audit.conflicting_labels),
            "excluded_labels": self.audit.excluded_labels,
            "longest_gap_hours": self.audit.longest_gap_hours, "splits": splits,
        }  # fmt: skip
        return {**ref, "summary": summary}

    def _train_mask(self, spec: FeatureSpec) -> np.ndarray:
        mask = np.ones(self.grid.hours, dtype=bool)
        if spec.exclude_2015_haze:
            first = index_of(datetime(2015, 8, 1))
            last = index_of(datetime(2015, 11, 30, 23))
            mask[first : last + 1] = False
        return mask

    def build_features(self, spec: FeatureSpec) -> dict[str, Any]:
        """A feature set ending before the test period. The test labels are not in the file."""
        mask = self._train_mask(spec)
        scaler = S.fit_scaler(self.grid, spec.log_transform, mask)
        scaled = scaler.apply(self.grid.values)
        visible = S.SEALED_FROM
        issues = {s: S.issue_times(s, spec.window) for s in ("train", "validation")}
        issues["train"] = issues["train"][
            mask[issues["train"]] & mask[issues["train"] + max(S.HORIZONS)]
        ]
        last = S.split_bounds("validation")[1]
        hours = np.array([label_at(i).hour for i in range(last + 1)]) * (2 * np.pi / 24)
        months = np.array([label_at(i).month for i in range(last + 1)]) * (2 * np.pi / 12)
        calendar = np.stack([np.sin(hours), np.cos(hours), np.sin(months), np.cos(months)], axis=1)
        arrays: dict[str, np.ndarray] = {
            "series": np.nan_to_num(scaled[:visible], nan=0.0).astype(np.float32),
            "mask": (~np.isnan(scaled[:visible])).astype(np.float32),
            "calendar": calendar.astype(np.float32),
            "train_issues": issues["train"],
            "valid_issues": issues["validation"],
        }
        for name, key in (("train", "train"), ("validation", "valid")):
            target = scaled[issues[name][:, None] + np.array(S.HORIZONS)]
            flat = target.reshape(len(target), -1)
            arrays[f"{key}_known"] = (~np.isnan(flat)).astype(np.float32)
            arrays[f"{key}_y"] = np.nan_to_num(flat, nan=0.0).astype(np.float32)
        name = payload_digest(asdict(spec))[:12]
        path = self.folder / f"features-{name}.npz"
        np.savez(path, allow_pickle=False, **arrays)
        reference = {
            "features_id": name, "sha256": file_digest(path), "path": str(path.resolve()),
            "train_samples": len(issues["train"]), "validation_samples": len(issues["validation"]),
            "last_visible_label": label_at(visible - 1).isoformat(),
            "spec": asdict(spec),
        }  # fmt: skip
        self.features[name] = {**reference, "scaler": scaler}
        return reference

    def _store(
        self,
        name: str,
        issues: np.ndarray,
        prediction: np.ndarray,
        horizons: tuple[int, ...] = S.HORIZONS,
    ) -> dict[str, Any]:
        path = self.folder / f"predictions-{name}.npz"
        np.savez(path, issues=issues, predictions=prediction, horizons=np.array(horizons))
        scored = evaluate(self.truth, issues, list(horizons), prediction)
        record = {"model": name, "predictions_sha256": file_digest(path), "metrics": scored}
        self.results[name] = record
        self._save(f"evaluation-{name}.json", record)
        return record

    def score(
        self, name: str, issues: np.ndarray, prediction: np.ndarray, horizons: tuple[int, ...]
    ) -> dict[str, Any]:
        """Store and evaluate predictions made outside the workbench, such as registry methods."""
        return self._store(name, issues, prediction, horizons)

    def baselines(self, window: int) -> dict[str, dict[str, Any]]:
        """B0 to B4 on validation, frozen before any candidate trains."""
        issues = S.issue_times("validation", window)
        train_end = S.split_bounds("train")[1]
        table = S.climatology_table(self.grid, train_end)
        base = S.persistence(self.grid, issues)
        horizons = S.HORIZONS
        made = {
            "B0_persistence": np.stack([base for _ in horizons], axis=1),
            "B1_daily_naive": np.stack([S.daily_naive(self.grid, issues, h) for h in horizons], 1),
            "B2_weekly_naive": np.stack(
                [S.weekly_naive(self.grid, issues, h) for h in horizons], 1
            ),
            "B3_climatology": np.stack([S.climatology(table, issues, h) for h in horizons], 1),
            "B4_lagged_ridge": self._ridge(issues),
        }
        if "B0_persistence" in self.results:
            raise ValueError("the baselines are frozen and cannot be rebuilt")
        return {name: self._store(name, issues, array) for name, array in made.items()}

    def _ridge(self, issues: np.ndarray) -> np.ndarray:
        """One regularised model per horizon. Alpha is chosen on validation MAE."""
        if issues.min() < RIDGE_LAGS + S.USABLE_OFFSET:
            raise ValueError("the ridge lags do not fit before the first issue")
        scaler = S.fit_scaler(self.grid, log=False)
        scaled = scaler.apply(self.grid.values)
        train = S.issue_times("train", RIDGE_LAGS + 8)
        x_train, x_valid = (S.lag_matrix(scaled, i, RIDGE_LAGS) for i in (train, issues))
        out = []
        for h in S.HORIZONS:
            best, chosen = float("inf"), np.empty(0)
            for alpha in RIDGE_ALPHAS:
                weights = S.fit_ridge(x_train, scaled[train + h], alpha)
                pred = scaler.invert(S.apply_ridge(x_valid, weights))
                score = float(np.nanmean(np.abs(pred - self.grid.values[issues + h])))
                if score < best:
                    best, chosen = score, pred
            out.append(chosen)
        return np.stack(out, axis=1)

    def train(self, name: str, features_id: str, spec: TrainSpec) -> dict[str, Any]:
        """Train one candidate through the template, in isolation, then evaluate it."""
        feature = self.features[features_id]
        out = (self.folder / f"train-{name}").resolve()
        out.mkdir(exist_ok=True)
        job = {
            **asdict(spec), "window": feature["spec"]["window"], "offset": S.USABLE_OFFSET,
            "threads": THREADS, "batch": 256, "patience": 3,
            "data": feature["path"],
        }  # fmt: skip
        (out / "job.json").write_text(json.dumps(job, indent=2), encoding="utf-8")
        run: IsolatedRun = run_isolated(
            python_for_training(), TEMPLATE.resolve(), out, [str(out)], TRAIN_TIMEOUT, THREADS
        )
        if run.exit_code != 0:
            return {
                "model": name,
                "failed": True,
                "exit_code": run.exit_code,
                "tail": run.output_tail,
            }
        training = json.loads((out / "training.json").read_text(encoding="utf-8"))
        scaled = np.load(out / "valid_scaled.npy")
        count, regions = len(scaled), len(S.HORIZONS)
        shaped = scaled.reshape(count, regions, -1)
        scaler: S.Scaler = feature["scaler"]
        issues = S.issue_times("validation", feature["spec"]["window"])
        record = self._store(name, issues, scaler.invert(shaped))
        record["training"] = {k: v for k, v in training.items() if k != "history"}
        record["wall_seconds"], record["peak_rss_mb"] = run.wall_seconds, run.peak_rss_mb
        record["features_sha256"] = feature["sha256"]
        self._save(f"evaluation-{name}.json", record)
        return record

    def ensemble(self, name: str, members: list[str], features_id: str) -> dict[str, Any]:
        """The mean of trained members, scored as one model. It also writes the soft targets."""
        feature = self.features[features_id]
        folders = [self.folder / f"train-{m}" for m in members]
        valid = np.mean([np.load(f / "valid_scaled.npy") for f in folders], axis=0)
        soft = (self.folder / f"soft-{name}.npy").resolve()
        np.save(soft, np.mean([np.load(f / "train_scaled.npy") for f in folders], axis=0))
        issues = S.issue_times("validation", feature["spec"]["window"])
        shaped = valid.reshape(len(valid), len(S.HORIZONS), -1)
        record = self._store(name, issues, feature["scaler"].invert(shaped))
        made = [self.results[m]["training"] for m in members]
        record["training"] = {
            "parameters": sum(t["parameters"] for t in made),
            "train_seconds": round(sum(t["train_seconds"] for t in made), 2),
            "predict_seconds": round(sum(t["predict_seconds"] for t in made), 3),
            "model_sha256": payload_digest([t["model_sha256"] for t in made]),
        }
        record["soft_path"] = str(soft)
        return record

    def prediction(self, name: str) -> dict[int, np.ndarray]:
        """Primary-horizon predictions by issue index, read back from the stored file."""
        with np.load(self.folder / f"predictions-{name}.npz") as saved:
            slot = list(saved["horizons"]).index(S.PRIMARY_HORIZON)
            return dict(zip(saved["issues"].tolist(), saved["predictions"][:, slot], strict=True))

    def aligned(
        self, name: str, base: dict[int, np.ndarray]
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Issues both models scored, with each model's values. Windows can differ."""
        mine = self.prediction(name)
        shared = sorted(set(mine) & set(base))
        return (
            np.array(shared),
            np.stack([mine[i] for i in shared]),
            np.stack([base[i] for i in shared]),
        )

    def compare(self) -> list[dict[str, Any]]:
        """One row per model at the primary horizon, from the evaluator's own numbers."""
        rows = []
        for name, record in self.results.items():
            row = record["metrics"][str(S.PRIMARY_HORIZON)]
            limits = row["limits"]
            rows.append(
                {
                    "model": name, "mae": round(row["all"]["mae"], 3),
                    "rmse": round(row["all"]["rmse"], 3), "bias": round(row["all"]["bias"], 3),
                    "skill": round(row["mean_skill"], 4),
                    "skill_low": round(limits["mean_skill_low"], 4),
                    "skill_high": round(limits["mean_skill_high"], 4),
                    "worst_region_skill_high": round(min(limits["region_skill_high"]), 4),
                    "above_55_mae": round(row["above_55"]["mae"], 3),
                    "exceed_recall": row["exceedance"]["recall"],
                    "exceed_precision": row["exceedance"]["precision"],
                }
            )  # fmt: skip
        return sorted(rows, key=lambda r: r["mae"])


def stamp() -> str:
    return datetime.now(UTC).isoformat()

"""PM2.5 regression that asks for a comparison of model families under one protocol.

The same data, splits and evaluator as the regression scenario. Two additions run inside the
run: an optional approved acquisition that checks the local source against the official API,
and a rolling-origin search of the ridge penalty on the train years. The tuned ridge is scored
on validation as a statistical candidate beside any neural candidate the Lead chooses.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np

from earthlab.digest import file_digest
from earthlab.forecast import samples as S
from earthlab.forecast.isolated import python_for_training, run_isolated
from earthlab.forecast.pipeline import SOURCE, TEMPLATE, THREADS
from earthlab.harness.acquire_step import AcquisitionConfig
from earthlab.harness.contracts import ExperimentPlanV1
from earthlab.harness.regression import PM25_PROBLEM, RegressionAdapter
from earthlab.harness.seats import Seats
from earthlab.mlops import rolling

TUNED = "candidate-ridge-cv"
FAMILY_PROBLEM = PM25_PROBLEM.model_copy(
    update={
        "problem_id": "pm25-regression-families-6h",
        "success_criteria": (
            *PM25_PROBLEM.success_criteria,
            "persistence, a tuned statistical model and a compact neural model compared under "
            "one protocol, when the data allow each",
        ),
    }
)
OBJECTIVE = (
    "Compare a simple reference, a tuned statistical model and a compact neural model for "
    "regional PM2.5 six hours ahead on the historical NEA series. Keep the simplest method "
    "that meets the criteria."
)


class FamilyAdapter(RegressionAdapter):
    def __init__(
        self, run_dir: Path, source: Path = SOURCE, acquisition: AcquisitionConfig | None = None
    ):
        super().__init__(run_dir, source)
        self.acquisition = acquisition

    def train(self, plan: ExperimentPlanV1, seats: Seats) -> dict[str, Any]:
        out = super().train(plan, seats)
        if TUNED not in self.bench.results:
            out["tuned"] = self._tune(int(plan.config["window_hours"]))
            seats.trace.append("tuning_verified", "runtime", **out["tuned"])
        if "model_id" in out:
            out["inference_check"] = self._reload(str(out["model_id"]))
            seats.trace.append("inference_verified", "runtime", **out["inference_check"])
        return out

    def _reload(self, name: str) -> dict[str, Any]:
        """Reload the saved neural model in isolation and compare its predictions."""
        folder = (self.bench.folder / f"train-{name}").resolve()
        run_isolated(python_for_training(), TEMPLATE.resolve(), folder,
                     [str(folder), "verify"], 300, THREADS)  # fmt: skip
        check = json.loads((folder / "verify.json").read_text(encoding="utf-8"))
        return {"model_id": name, **check}

    def _tune(self, window: int) -> dict[str, Any]:
        """Select the penalty on train folds, then fit once on all train years and score it."""
        search = rolling.run(self.bench.grid)
        path = self.bench.folder / "rolling-origin-ridge.json"
        path.write_text(json.dumps(search, indent=2, sort_keys=True), encoding="utf-8")
        best = search["search"]["trials"][search["search"]["best_trial"]]
        alpha = float(best["config"]["alpha"])
        issues = S.issue_times("validation", max(window, rolling.LAGS + 8))
        scaler = S.fit_scaler(self.bench.grid, log=False)
        scaled = scaler.apply(self.bench.grid.values)
        train = S.issue_times("train", rolling.LAGS + 8)
        x_train = S.lag_matrix(scaled, train, rolling.LAGS)
        weights = S.fit_ridge(x_train, scaled[train + rolling.HORIZON], alpha)
        pred = scaler.invert(S.apply_ridge(S.lag_matrix(scaled, issues, rolling.LAGS), weights))
        saved = self.bench.folder / f"weights-{TUNED}.npz"
        np.savez(saved, weights=weights, mean=scaler.mean, std=scaler.std, alpha=alpha)
        again = self._reload_ridge(saved, scaled_issues=(scaled, issues), scaler=scaler)
        self.bench.score(TUNED, issues, pred[:, None, :], (rolling.HORIZON,))
        return {"tuned_id": TUNED, "alpha": alpha, "search_sha256": file_digest(path),
                "mean_fold_mae": best["validation_score"], "weights_sha256": file_digest(saved),
                "reload_max_abs_difference": float(np.max(np.abs(again - pred)))}  # fmt: skip

    @staticmethod
    def _reload_ridge(
        saved: Path, scaled_issues: tuple[np.ndarray, np.ndarray], scaler: S.Scaler
    ) -> np.ndarray:
        """Predict again from the saved weights file alone."""
        scaled, issues = scaled_issues
        with np.load(saved) as kept:
            weights = kept["weights"]
        return scaler.invert(S.apply_ridge(S.lag_matrix(scaled, issues, rolling.LAGS), weights))


def family_adapter(run_dir: Path) -> FamilyAdapter:
    return FamilyAdapter(run_dir)


__all__ = ["FAMILY_PROBLEM", "OBJECTIVE", "TUNED", "FamilyAdapter", "family_adapter"]

"""Run M5-C under protocol m5-protocol-c-1 (amendments C1, C2): fit 2015 to 2017, score 2019.

Usage: uv run python scripts/m5_run_c.py DATA_ROOT HAZE2015_RUN_FOLDER
Output: docs/m5/results/m5_c_v1.json
With a third argument `post-hoc-bands` it writes only m5_c_v1_post_hoc_bands.json (Amendment C3)
and leaves m5_c_v1.json unchanged.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier

from earthlab.haze import ablation_features as F
from earthlab.m5 import event_c as E
from earthlab.m5 import strict_json as sj
from earthlab.m5.ladder import TREE
from earthlab.m5.ladder_data import load_open_grid

TRAIN, TEST = (2015, 2016, 2017), 2019


def firms_dir(data: Path, haze: Path, year: int) -> Path:
    return haze / "firms" if year == 2015 else data / "season" / str(year) / "firms"


def stack(blocks: list[E.Block], fire: bool) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    x = np.vstack([np.hstack([b.lags, b.fire]) if fire else b.lags for b in blocks])
    return x, np.concatenate([b.y for b in blocks]), np.concatenate([b.weeks for b in blocks])


class Trees:
    def fit(self, x: np.ndarray, y: np.ndarray) -> Trees:
        self.model = HistGradientBoostingClassifier(**TREE_CLF).fit(x, y)
        return self

    def proba(self, x: np.ndarray) -> np.ndarray:
        return np.asarray(self.model.predict_proba(x)[:, 1])


TREE_CLF = {k: v for k, v in TREE.items() if k != "random_state"} | {"random_state": 7}


def calibrated(train: list[E.Block], test: E.Block, fire: bool, trees: bool = False) -> np.ndarray:
    x, y, weeks = stack(train, fire)
    xt = np.hstack([test.lags, test.fire]) if fire else test.lags
    make = Trees if trees else E.Logit
    fold = E.fold_ids(weeks)
    oof = np.zeros(len(y))
    for f in np.unique(fold):
        tr, te = fold != f, fold == f
        oof[te] = make().fit(x[tr], y[tr]).proba(x[te]) if len(set(y[tr])) > 1 else y[tr].mean()
    pl = E.platt(oof, y)
    return np.asarray(pl.predict_proba(E.logit_of(make().fit(x, y).proba(xt)))[:, 1])


def evaluate(train: list[E.Block], test: E.Block, trees_gate: bool = True) -> dict[str, Any]:
    y = test.y
    base_rate = float(np.concatenate([b.y for b in train]).mean())
    base = np.full(len(y), base_rate)
    c1 = np.nan_to_num((test.lags[:, 0] > E.HIGH).astype(float))
    probs = {"C1": c1, "C2": calibrated(train, test, False), "C3": calibrated(train, test, True)}
    boot = E.week_bootstrap(probs, base, y, test.weeks)
    base_brier = E.brier(base, y)
    out: dict[str, Any] = {"C0": E.score_rung(base, y, base_brier)}
    for k, p in probs.items():
        out[k] = E.score_rung(p, y, base_brier) | {"skill_ci": boot[k]}
        out[k]["label"] = E.label(
            out[k]["brier_skill"], boot[k][0], out[k]["abstention"]["calibration_gap"]
        )
    c3 = out["C3"]
    if trees_gate and c3["brier_skill"] > 0 and c3["skill_ci"][0] > 0:
        p4 = calibrated(train, test, True, trees=True)
        out["C4"] = E.score_rung(p4, y, base_brier) | {
            "skill_ci": E.week_bootstrap({"C4": p4}, base, y, test.weeks)["C4"]
        }
    else:
        out["C4"] = {"status": "not_run_gate_C3_did_not_beat_C0"}
    out["scored_issues"] = len(y)
    out["events"] = int(y.sum())
    out["episodes"] = E.episodes(test.days, y)
    out["train_base_rate"] = base_rate
    return out


def blocks(grid: Any, data: Path, haze: Path, years: tuple[int, ...]) -> dict[int, E.Block]:
    return {y: E.build_block(grid, y, firms_dir(data, haze, y)) for y in years}


REASONS = {k: "no issue outside the abstention band (coverage 0): rate undefined"
           for k in ("error_rate", "random_error_rate", "calibration_gap")}  # fmt: skip


def rank_within(block: E.Block) -> E.Block:
    order = block.fire.argsort(axis=0).argsort(axis=0) / max(len(block.fire) - 1, 1)
    return E.Block(block.year, block.lags, order, block.y, block.weeks, block.days)


def post_hoc_bands(train: list[E.Block], test: E.Block) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, fire in (("C2", False), ("C3", True)):
        p = calibrated(train, test, fire)
        out[name] = {
            f"{lo}-{hi}": E.covered_error(p, test.y, band=(lo, hi))
            for lo, hi in E.EXPLORATORY_BANDS
        }
    return out


def main() -> int:
    data, haze = Path(sys.argv[1]).expanduser(), Path(sys.argv[2]).expanduser()
    grid = load_open_grid(Path("data/nea/Historical1hrPM2.5.csv"))
    b = blocks(grid, data, haze, (*TRAIN, TEST))
    train, test = [b[y] for y in TRAIN], b[TEST]
    if "post-hoc-bands" in sys.argv[3:]:
        rows = {"status": "exploratory_post_hoc_amendment_C3", "primary_run_commit": "a7a3c14",
                "bands": post_hoc_bands(train, test)}  # fmt: skip
        Path("docs/m5/results/m5_c_v1_post_hoc_bands.json").write_text(
            sj.dumps(rows, indent=1) + "\n"
        )
        print(sj.dumps(rows, indent=1))
        return 0
    record: dict[str, Any] = {"protocol_id": "m5-protocol-c-1", "main": evaluate(train, test)}
    F.FIRMS_DELAY = timedelta(hours=24)
    late = blocks(grid, data, haze, (*TRAIN, TEST))
    F.FIRMS_DELAY = timedelta(hours=3)
    record["sensitivity_firms_delay_24h"] = evaluate([late[y] for y in TRAIN], late[TEST], False)
    record["diagnostic_season_rank_hindsight"] = evaluate(
        [rank_within(x) for x in train], rank_within(test), False
    )
    record["control_lags_only_without_2015"] = evaluate([b[2016], b[2017]], test, False)
    record["computed_at_utc"] = datetime.now(UTC).isoformat(timespec="seconds")
    clean, missing = sj.sanitize(record, REASONS)
    clean["missing_value_reasons"] = missing
    Path("docs/m5/results/m5_c_v1.json").write_text(
        sj.dumps(clean, indent=1, sort_keys=True) + "\n"
    )
    for name in ("main", "sensitivity_firms_delay_24h", "diagnostic_season_rank_hindsight",
                 "control_lags_only_without_2015"):  # fmt: skip
        r = record[name]
        skills = {k: round(r[k]["brier_skill"], 3) for k in ("C1", "C2", "C3")}
        print(name, r["scored_issues"], r["events"], r["episodes"], skills)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

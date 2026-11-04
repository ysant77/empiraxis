"""M5-C (protocol m5-protocol-c-1, amendments C1, C2): event 12 to 24 h ahead, with abstention.

Inputs are issue-time valid: NEA lags (newest T-2 h) and FIRMS features (pass + 3 h). The event is
any region-hour above the elevated threshold in (T+12 h, T+24 h].
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score

from earthlab.forecast.dataset import Grid, label_at
from earthlab.haze import ablation_features as F
from earthlab.m5.ladder import HIGH
from earthlab.m5.ladder_data import season_rows

WINDOW = range(13, 25)
LOW_BAND, HIGH_BAND = 0.2, 0.8
BINS = 10
EXPLORATORY_BANDS = ((0.1, 0.9), (0.3, 0.7))  # post hoc, Amendment C3


@dataclass(frozen=True)
class Block:
    year: int
    lags: np.ndarray  # (n, 48): max and mean over regions for lags 0 to 23
    fire: np.ndarray  # (n, 9)
    y: np.ndarray  # (n,) 0/1 event
    weeks: np.ndarray  # (n,) season-and-ISO-week labels
    days: np.ndarray  # (n,) issue-day labels


def event_labels(values: np.ndarray, rows: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Event flag and a mask of issues whose window has at least one observed hour."""
    win = np.stack([values[rows + h] for h in WINDOW])
    scored = ~np.isnan(win).all(axis=(0, 2))
    flag = (np.nan_to_num(win, nan=0.0) > HIGH).any(axis=(0, 2))
    return flag.astype(float), scored


def lag_matrix(values: np.ndarray, rows: np.ndarray) -> np.ndarray:
    cols = []
    for k in range(F.LAGS):
        block = values[rows - F.NEWEST - k, :]
        with np.errstate(all="ignore"):
            cols += [
                np.nanmax(np.where(np.isnan(block), -np.inf, block), axis=1),
                np.nanmean(block, axis=1),
            ]
    out = np.stack(cols, axis=1)
    out[np.isneginf(out)] = np.nan
    return out


def build_block(grid: Grid, year: int, firms_dir: Path) -> Block:
    rows = season_rows(year)
    y, scored = event_labels(grid.values, rows)
    keep = np.flatnonzero(scored)
    r = rows[keep]
    stamps = [label_at(int(i)) for i in r]
    iso = [s.isocalendar() for s in stamps]
    return Block(
        year=year,
        lags=lag_matrix(grid.values, r),
        fire=F.fire_features(r, F.load_firms(firms_dir)),
        y=y[keep],
        weeks=np.array([f"{year}-W{i.week:02d}" for i in iso]),
        days=np.array([f"{s:%Y-%m-%d}" for s in stamps]),
    )


class Logit:
    """Mean imputation, standardisation and L2 logistic regression with fixed C = 1.0."""

    def fit(self, x: np.ndarray, y: np.ndarray) -> Logit:
        self.mean = np.nanmean(x, axis=0)
        filled = np.where(np.isnan(x), self.mean, x)
        self.mu, self.sd = filled.mean(axis=0), filled.std(axis=0) + 1e-9
        self.model = LogisticRegression(C=1.0, max_iter=1000).fit((filled - self.mu) / self.sd, y)
        return self

    def proba(self, x: np.ndarray) -> np.ndarray:
        filled = np.where(np.isnan(x), self.mean, x)
        return np.asarray(self.model.predict_proba((filled - self.mu) / self.sd)[:, 1])


def fold_ids(weeks: np.ndarray, folds: int = 5) -> np.ndarray:
    """Deal ISO-week groups to folds in order."""
    order = {w: i % folds for i, w in enumerate(sorted(set(weeks.tolist())))}
    return np.array([order[w] for w in weeks])


def logit_of(p: np.ndarray) -> np.ndarray:
    q = np.clip(p, 1e-6, 1 - 1e-6)
    return np.asarray(np.log(q / (1 - q)).reshape(-1, 1))


def out_of_fold(x: np.ndarray, y: np.ndarray, weeks: np.ndarray) -> np.ndarray:
    fold = fold_ids(weeks)
    oof = np.zeros(len(y))
    for f in np.unique(fold):
        tr, te = fold != f, fold == f
        if len(np.unique(y[tr])) < 2:
            oof[te] = float(y[tr].mean())
        else:
            oof[te] = Logit().fit(x[tr], y[tr]).proba(x[te])
    return oof


def platt(oof: np.ndarray, y: np.ndarray) -> LogisticRegression:
    return LogisticRegression(C=1e6, max_iter=1000).fit(logit_of(oof), y)


def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def reliability(p: np.ndarray, y: np.ndarray) -> list[dict[str, float]]:
    edges = np.linspace(0.0, 1.0, BINS + 1)
    which = np.minimum(np.digitize(p, edges[1:-1]), BINS - 1)
    rows = []
    for b in range(BINS):
        m = which == b
        if m.any():
            rows.append({"bin": b, "n": int(m.sum()), "mean_p": float(p[m].mean()),
                         "observed": float(y[m].mean())})  # fmt: skip
    return rows


def covered_error(
    p: np.ndarray, y: np.ndarray, seed: int = 7, band: tuple[float, float] = (LOW_BAND, HIGH_BAND)
) -> dict[str, float]:
    """Coverage, error rate and calibration gap on issues outside the abstention band."""
    cover = (p < band[0]) | (p > band[1])
    n = int(cover.sum())
    if n == 0:
        return {"coverage": 0.0, "error_rate": float("nan"), "random_error_rate": float("nan"),
                "calibration_gap": float("nan")}  # fmt: skip
    wrong = ((p >= 0.5) != (y == 1)).astype(float)
    rng = np.random.default_rng(seed)
    random_err = float(
        np.mean([wrong[rng.choice(len(p), n, replace=False)].mean() for _ in range(200)])
    )
    table = reliability(p[cover], y[cover])
    gap = sum(r["n"] * abs(r["mean_p"] - r["observed"]) for r in table) / n
    return {"coverage": n / len(p), "error_rate": float(wrong[cover].mean()),
            "random_error_rate": random_err, "calibration_gap": float(gap)}  # fmt: skip


def episodes(days: np.ndarray, y: np.ndarray) -> int:
    hit = sorted({d for d, e in zip(days.tolist(), y.tolist(), strict=True) if e == 1})
    if not hit:
        return 0
    ordinal = np.array([np.datetime64(d).astype(int) for d in hit])
    return int((np.diff(ordinal) > 1).sum() + 1)


def week_bootstrap(
    probs: dict[str, np.ndarray], base: np.ndarray, y: np.ndarray, weeks: np.ndarray,
    resamples: int = 2000, seed: int = 7,
) -> dict[str, tuple[float, float]]:  # fmt: skip
    """95% interval of Brier skill against the base rate for every rung, resampling ISO weeks."""
    groups = [np.flatnonzero(weeks == w) for w in sorted(set(weeks.tolist()))]
    rng = np.random.default_rng(seed)
    draws: dict[str, list[float]] = {k: [] for k in probs}
    for _ in range(resamples):
        idx = np.concatenate([groups[i] for i in rng.integers(0, len(groups), len(groups))])
        ref = brier(base[idx], y[idx])
        for k, p in probs.items():
            draws[k].append(1.0 - brier(p[idx], y[idx]) / ref if ref > 0 else float("nan"))
    return {k: (float(np.nanpercentile(v, 2.5)), float(np.nanpercentile(v, 97.5)))
            for k, v in draws.items()}  # fmt: skip


def score_rung(p: np.ndarray, y: np.ndarray, base_brier: float) -> dict[str, Any]:
    both = len(np.unique(y)) == 2
    return {
        "brier": brier(p, y),
        "brier_skill": 1.0 - brier(p, y) / base_brier if base_brier > 0 else float("nan"),
        "roc_auc": float(roc_auc_score(y, p)) if both else float("nan"),
        "reliability": reliability(p, y),
        "abstention": covered_error(p, y),
    }


def label(skill: float, ci_low: float, gap: float) -> str:
    if np.isnan(skill) or np.isnan(gap):
        return "no_supported_signal"
    return "useful_signal" if skill > 0 and ci_low > 0 and gap < 0.1 else "no_supported_signal"

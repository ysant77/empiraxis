"""AUC and burned-versus-control contrast on small arrays."""

from __future__ import annotations

import math

import numpy as np
import pytest

from earthlab.m5.contrast import auc, burn_contrast


def test_auc_extremes_ties_and_empty() -> None:
    assert auc(np.array([3.0, 4.0]), np.array([1.0, 2.0])) == 1.0
    assert auc(np.array([1.0, 2.0]), np.array([3.0, 4.0])) == 0.0
    assert auc(np.array([1.0, 1.0]), np.array([1.0, 1.0])) == 0.5
    assert math.isnan(auc(np.array([]), np.array([1.0])))


def test_burn_contrast_drops_missing_index_but_reports_totals() -> None:
    index = np.array([0.5, 0.6, np.nan, 0.1, 0.0, 0.2])
    burned = np.array([True, True, True, False, False, False])
    control = np.array([False, False, False, True, True, True])
    out = burn_contrast(index, burned, control)
    assert out["n_burned_valid"] == 2 and out["n_burned_total"] == 3
    assert out["n_control_valid"] == 3
    assert out["mean_burned"] == pytest.approx(0.55) and out["auc"] == 1.0
    empty = burn_contrast(np.full(2, np.nan), burned[:2], control[:2])
    assert empty["mean_burned"] is None

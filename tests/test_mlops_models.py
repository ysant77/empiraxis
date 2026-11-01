"""Registered methods, eligibility, trees, the bounded search and the declared postprocessing."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import numpy as np
import pytest
from mlops_helpers import SHA, stored_bundle
from pydantic import ValidationError

from earthlab.harness.eval_classify import failed_checks, score
from earthlab.mlops import families, postprocess
from earthlab.mlops.contracts import PostprocessV1, SearchSpaceV1
from earthlab.mlops.families import Facts
from earthlab.mlops.registry import Registry
from earthlab.mlops.trees import apply_trees, fit_trees
from earthlab.mlops.tuning import search


def data(rows: int = 400) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(3)
    x = rng.normal(size=(rows, 4))
    y = (2 * x[:, 0] - x[:, 1] + 0.1 * rng.normal(size=rows))[:, None]
    return x, y


def labels(rows: int = 600) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(5)
    x = rng.normal(size=(rows, 3))
    return x, (x[:, :1] + 0.3 * rng.normal(size=(rows, 1)) > 1.0).astype(float)


@pytest.mark.parametrize(
    ("method", "config"),
    [
        ("ridge", {"alpha": 0.0}),
        ("ridge", {"alpha": 1.0, "extra": 1}),
        ("ridge", {}),
        ("logistic", {"penalty": -1.0}),
        ("trees", {"trees": 500, "depth": 2, "rate": 0.1}),
        ("trees", {"trees": 20, "depth": 9, "rate": 0.1}),
        ("trees", {"trees": 20, "depth": 2, "rate": 0.0}),
        ("persistence", {"alpha": 1.0}),
    ],
)
def test_an_invalid_training_config_is_refused(method: str, config: Mapping[str, Any]) -> None:
    task = "classification" if method == "logistic" else "regression"
    x, y = data(50)
    with pytest.raises(ValidationError):
        families.train(method, task, x, y, config, 1)  # type: ignore[arg-type]


def test_an_unknown_method_or_the_wrong_task_is_refused() -> None:
    x, y = data(50)
    with pytest.raises(ValueError, match="not a registered"):
        families.train("transformer", "regression", x, y, {}, 1)
    with pytest.raises(ValueError, match="not a registered"):
        families.train("ridge", "classification", x, y, {"alpha": 1.0}, 1)
    with pytest.raises(ValueError, match="not a registered"):
        families.predict("ghost", "regression", x, {}, {})


def test_misaligned_rows_are_refused() -> None:
    x, y = data(50)
    with pytest.raises(ValueError, match="align"):
        families.train("ridge", "regression", x, y[:40], {"alpha": 1.0}, 1)
    with pytest.raises(ValueError, match="align"):
        families.train("ridge", "regression", x, y[:, 0], {"alpha": 1.0}, 1)


def test_eligibility_comes_from_measured_facts() -> None:
    few = Facts("classification", 5_000, 3, True, True)
    blocked = families.eligible(few)
    assert set(blocked) == {"logistic", "trees_classifier"}
    assert all("positive labels" in str(reason) for reason in blocked.values())
    assert families.eligible(Facts("classification", 5_000, None, True, True))["logistic"]
    rich = families.eligible(Facts("classification", 5_000, 400, True, True))
    assert rich == {"logistic": None, "trees_classifier": None}
    small = families.eligible(Facts("regression", 200, None, False, True))
    assert small["trees"] and small["climatology"] and small["ridge"] is None
    assert small["persistence"] is None


def test_a_majority_class_output_never_counts_as_success() -> None:
    _, y = labels()
    assert 0.0 < float(y.mean()) < 0.2  # imbalanced
    quiet = np.zeros_like(y)
    row = score(quiet, 0.5, y)
    assert row["accuracy"] and float(row["accuracy"]) > 0.8  # accuracy alone would look fine
    gain = {"gain": 0.0, "low": -0.1, "high": 0.1}
    reasons = failed_checks(row, gain)
    assert any("majority class" in reason for reason in reasons)
    assert any("base rate" in reason for reason in reasons)


def test_the_alarm_cut_gets_no_credit_for_a_constant_output() -> None:
    _, both = labels()
    y = both[:, 0]
    flat = np.full(len(y), 0.9)
    assert postprocess.best_cut(flat, y) == 0.02  # no cut separates anything: first cut stands
    assert float(postprocess.classification(PostprocessV1(alarm_cut=0.5), flat).mean()) == 1.0
    with pytest.raises(ValueError, match="both classes"):
        postprocess.fit_calibration(np.full(10, 0.3), np.zeros(10))


def test_a_trained_classifier_beats_the_base_rate() -> None:
    x, y = labels(1_500)
    cfg = {"trees": 30, "depth": 2, "rate": 0.2}
    state = families.train("trees_classifier", "classification", x, y, cfg, 1)
    prob = families.predict("trees_classifier", "classification", x, state, cfg)
    row = score(prob[:, 0], postprocess.best_cut(prob[:, 0], y[:, 0]), y[:, 0])
    assert float(row["pr_auc"] or 0.0) > float(row["base_rate"] or 1.0)
    assert not failed_checks(row, {"gain": 0.1, "low": 0.05, "high": 0.2})


def test_logistic_fits_and_stays_a_probability() -> None:
    x, y = labels()
    cfg = {"penalty": 1.0, "balanced": True}
    state = families.train("logistic", "classification", x, y, cfg, 1)
    prob = families.predict("logistic", "classification", x, state, cfg)
    assert prob.shape == y.shape and prob.min() >= 0.0 and prob.max() <= 1.0
    assert prob[y[:, 0] == 1].mean() > prob[y[:, 0] == 0].mean()


def test_trees_fit_and_predict_on_small_data() -> None:
    x, y = data()
    cfg = {"trees": 40, "depth": 3, "rate": 0.3}
    state = families.train("trees", "regression", x, y, cfg, 1)
    out = families.predict("trees", "regression", x, state, cfg)
    assert out.shape == y.shape
    assert float(np.mean((out - y) ** 2)) < 0.4 * float(np.var(y))
    again = families.predict("trees", "regression", x, state, cfg)
    np.testing.assert_array_equal(out, again)
    assert all(not v.dtype.hasobject for v in state.values())


def test_a_constant_target_gives_a_constant_tree_output() -> None:
    x, _ = data(60)
    state = fit_trees(x, np.full(60, 3.0), 5, 2, 0.1, False)
    np.testing.assert_allclose(apply_trees(x, state), 3.0)


def test_nan_targets_are_skipped_per_output() -> None:
    x, y = data()
    y = np.hstack([y, y])
    y[:50, 1] = np.nan
    cfg = {"trees": 5, "depth": 2, "rate": 0.2}
    state = families.train("trees", "regression", x, y, cfg, 1)
    out = families.predict("trees", "regression", x, state, cfg)
    assert out.shape == y.shape and not np.isnan(out).any()


def test_comparison_needs_the_same_features_outputs_and_task(tmp_path: Any) -> None:
    registry = Registry(tmp_path / "r")
    one = stored_bundle(registry, seed=1)
    two = stored_bundle(registry, seed=2)
    families.comparable([one, two])
    with pytest.raises(ValueError, match="do not share"):
        families.comparable([one, one.model_copy(update={"output_names": ("north",)})])
    with pytest.raises(ValueError, match="do not share"):
        families.comparable([one, one.model_copy(update={"task": "classification"})])
    other = one.model_copy(update={"feature": one.feature.model_copy(update={"sha256": SHA})})
    with pytest.raises(ValueError, match="do not share"):
        families.comparable([one, other])


def space(budget: float = 100.0, memory: float = 1e9, seeds: tuple[int, ...] = (1,)) -> Any:
    return SearchSpaceV1(
        method_id="ridge", metric="mae", direction="minimize", seeds=seeds,
        candidates=tuple({"alpha": a} for a in (1.0, 2.0, 3.0)),
        budget_seconds=budget, max_memory_mb=memory,
    )  # fmt: skip


def test_the_search_selects_on_validation_scores_only() -> None:
    scores = {1.0: 5.0, 2.0: 2.0, 3.0: 9.0}
    result = search(space(), lambda config, _seed: scores[float(config["alpha"])])
    assert result.selection_split == "validation" and result.stopped == "finished"
    assert result.best_trial == 1
    assert [t.state for t in result.trials] == ["completed"] * 3


def test_the_search_maximizes_when_asked() -> None:
    maximize = space().model_copy(update={"direction": "maximize"})
    result = search(maximize, lambda config, _seed: float(config["alpha"]))
    assert result.best_trial == 2


def test_the_mean_over_seeds_selects_a_configuration() -> None:
    table = {(1.0, 1): 1.0, (1.0, 2): 9.0, (2.0, 1): 4.0, (2.0, 2): 4.0, (3.0, 1): 6.0,
             (3.0, 2): 6.0}  # fmt: skip
    result = search(space(seeds=(1, 2)), lambda c, s: table[(float(c["alpha"]), s)])
    chosen = result.trials[result.best_trial or 0]
    assert chosen.config == {"alpha": 2.0}


def test_budget_exhaustion_leaves_not_started_trials() -> None:
    ticks = iter(range(0, 1_000, 10))
    result = search(space(budget=15.0), lambda *_: 1.0, clock=lambda: float(next(ticks)))
    states = [t.state for t in result.trials]
    assert result.stopped == "budget"
    assert states[0] == "completed" and states[-1] == "not_started"
    assert result.best_trial == 0


def test_a_memory_limit_stops_the_search_before_any_trial() -> None:
    result = search(space(memory=1.0), lambda *_: 1.0, memory=lambda: 50.0)
    assert result.stopped == "budget" and result.best_trial is None
    assert {t.state for t in result.trials} == {"not_started"}


def test_an_interruption_is_recorded_and_stops_later_trials() -> None:
    def trainer(config: Mapping[str, Any], _seed: int) -> float:
        if config["alpha"] == 2.0:
            raise KeyboardInterrupt
        return 1.0

    result = search(space(), trainer)
    assert [t.state for t in result.trials] == ["completed", "interrupted", "not_started"]
    assert result.stopped == "interrupted" and result.best_trial == 0


def test_failed_trials_stay_in_the_record() -> None:
    def trainer(config: Mapping[str, Any], _seed: int) -> float:
        if config["alpha"] == 1.0:
            raise ValueError("singular matrix")
        if config["alpha"] == 2.0:
            return float("nan")
        return 3.0

    result = search(space(), trainer)
    first, second, third = result.trials
    assert first.state == "failed" and "singular matrix" in first.note
    assert second.state == "failed" and "not a number" in second.note
    assert third.state == "completed" and result.best_trial == 2


def test_a_search_with_no_completed_trial_has_no_best() -> None:
    def trainer(_config: Mapping[str, Any], _seed: int) -> float:
        raise RuntimeError("out of memory")

    result = search(space(), trainer)
    assert result.best_trial is None and result.stopped == "finished"


def test_calibration_and_the_alarm_cut_come_from_validation_data() -> None:
    rng = np.random.default_rng(1)
    truth = (rng.random(4_000) < 0.2).astype(float)
    raw = np.clip(0.5 * truth + 0.1 + 0.1 * rng.random(4_000), 0.01, 0.99)
    slope, intercept = postprocess.fit_calibration(raw, truth)
    assert slope > 0.0
    post = PostprocessV1(calibration=(slope, intercept))
    prob = postprocess.classification(post, raw)
    assert abs(float(prob.mean()) - float(truth.mean())) < 0.02
    cut = postprocess.best_cut(prob, truth)
    alarms = postprocess.classification(
        PostprocessV1(calibration=(slope, intercept), alarm_cut=cut), raw
    )
    assert set(np.unique(alarms)) <= {0.0, 1.0}
    hit = alarms[truth == 1].mean()
    assert hit > 0.9 and alarms[truth == 0].mean() < 0.1
    assert 0.02 <= cut <= 0.98


def test_input_warnings_flag_values_far_outside_the_train_range() -> None:
    x = np.array([[0.5, 1.0], [0.0, 9.0]])
    first, second = postprocess.input_warnings(x, ("a", "b"))
    assert first == [] and "b" in second[0]

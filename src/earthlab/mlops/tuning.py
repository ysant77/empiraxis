"""A bounded search over a declared finite space. The test split has no route into it.

The caller's trainer returns a validation score. Each configuration runs once per declared
seed, and the mean over its completed seeds selects it. A failure, an interruption and a trial
that never started all stay in the record.
"""

from __future__ import annotations

import resource
import time
from collections.abc import Callable, Mapping
from typing import Any

from earthlab.digest import payload_digest
from earthlab.mlops.contracts import SearchResultV1, SearchSpaceV1, TrialV1

Trainer = Callable[[Mapping[str, Any], int], float]
_MB = 2**20


def _peak_mb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / _MB


def _best(space: SearchSpaceV1, trials: list[TrialV1]) -> int | None:
    groups: dict[str, list[TrialV1]] = {}
    for trial in trials:
        if trial.state == "completed" and trial.validation_score is not None:
            groups.setdefault(payload_digest(trial.config), []).append(trial)
    if not groups:
        return None
    sign = 1 if space.direction == "minimize" else -1

    def mean(rows: list[TrialV1]) -> float:
        return sign * sum(float(r.validation_score or 0.0) for r in rows) / len(rows)

    return min(groups.values(), key=mean)[0].trial


def search(
    space: SearchSpaceV1,
    trainer: Trainer,
    clock: Callable[[], float] = time.monotonic,
    memory: Callable[[], float] = _peak_mb,
) -> SearchResultV1:
    plan = [(c, s) for c in space.candidates for s in space.seeds]
    trials: list[TrialV1] = []
    started = clock()
    stopped: Any = "finished"
    for index, (config, seed) in enumerate(plan):
        over = clock() - started >= space.budget_seconds or memory() >= space.max_memory_mb
        if over or stopped != "finished":
            stopped = "budget" if stopped == "finished" else stopped
            trials.append(TrialV1(trial=index, config=config, seed=seed, state="not_started"))
            continue
        begin = clock()
        try:
            score = float(trainer(config, seed))
            state: Any = "completed"
            value: float | None = score
            note = ""
        except KeyboardInterrupt:
            state, value, note, stopped = (
                "interrupted",
                None,
                "stopped by the operator",
                "interrupted",
            )
        except (ValueError, ArithmeticError, RuntimeError, MemoryError) as exc:
            state, value, note = "failed", None, f"{type(exc).__name__}: {exc}"[:200]
        if value is not None and value != value:
            state, value, note = "failed", None, "the score is not a number"
        seconds = round(clock() - begin, 3)
        trials.append(
            TrialV1(trial=index, config=config, seed=seed, state=state,
                    validation_score=value, seconds=seconds, note=note)
        )  # fmt: skip
    return SearchResultV1(
        space_sha256=payload_digest(space.model_dump(mode="json")),
        trials=tuple(trials), best_trial=_best(space, trials), stopped=stopped,
    )  # fmt: skip

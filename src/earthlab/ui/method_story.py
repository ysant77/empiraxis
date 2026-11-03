"""M3: the recorded Muse run that trained a tuned ridge and a compact neural model.

Built only from the redacted replay copy. The neural model's architecture comes from the run's
own trace, so the page never names a model the run did not train.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from earthlab.ui import scenarios as S

RUN = "scenario-muse-method-comparison"
NAMES = {"candidate-ridge-cv": "Tuned ridge (rolling-origin)"}


def _trace(run_dir: Path, event: str) -> dict[str, Any]:
    for line in (run_dir / "trace.jsonl").read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record["event"] == event:
            return dict(record["data"])
    return {}


def _rows(record: dict[str, Any], neural: str) -> list[dict[str, Any]]:
    names = {**NAMES, "candidate-1": f"{neural} (compact neural)"}
    return [
        {
            "Model": names.get(row["model"], S.model_name(row["model"])),
            f"MAE ({S.UNIT})": f"{row['mae']:.3f}",
            f"RMSE ({S.UNIT})": f"{row['rmse']:.3f}",
            f"MAE above 55 {S.UNIT}": f"{row['above_55_mae']:.3f}",
            "Skill vs persistence": f"{row['skill']:.3f}",
        }
        for row in record["comparison"]
    ]


def m3(run_dir: Path) -> S.Story:
    record = S.record_of(run_dir)
    usage = record["usage"]
    family = _trace(run_dir, "family_comparison")
    tuned, reload = _trace(run_dir, "tuning_verified"), _trace(run_dir, "inference_verified")
    neural = str(family.get("trained", ["", "neural"])[-1]).upper()
    pick = record["recommendation"]
    return S.Story(
        key="M3", run=RUN, title=S.TITLES["M3"],
        question="Does a compact neural model gain enough over a tuned ridge to justify its "
        "cost, for regional PM2.5 six hours ahead?",
        method=f"Muse Glimmer as Lead expected the {family.get('lead_strategy')} family to win "
        f"and set the {neural} configuration. Trusted tools trained both families: a ridge "
        f"tuned on rolling-origin train folds (penalty {tuned.get('alpha')}) and the {neural}. "
        "Separate code scored every model on the same validation rows.",
        evidence=[
            f"{usage['model_calls']} model calls and {usage['tool_calls']} tool calls in a "
            f"hash-chained trace; {usage['training_seconds']:.0f} s of neural training.",
            f"Ridge reload difference {tuned.get('reload_max_abs_difference')}; {neural} reload "
            f"difference {reload.get('max_abs_difference')} over {reload.get('rows')} rows.",
            "Code refused " + str(len(S.refusals(run_dir))) + " proposals for length; each "
            "seat answered once: " + " | ".join(S.refusals(run_dir)) + ".",
            "The Lead read the evaluator's report and chose to finish with no revision.",
            "Validation years 2019 to 2023 were used in earlier experiments, so this is not an "
            f"independent score. The {neural} chose its best epoch on the same years.",
        ],
        tiles=[
            S.Tile("Model calls", str(usage["model_calls"]), "all on local Muse Glimmer"),
            S.Tile("Neural training (s)", f"{usage['training_seconds']:.0f}", neural),
            S.Tile("Wall time (s)", f"{usage['wall_seconds']:,.1f}"),
            S.Tile("Families trained", "2", "statistical and neural"),
        ],
        rows=_rows(record, neural),
        rows_title="Family comparison, same validation rows",
        decision=S.outcome_name(pick["outcome"]) + ": " + S.model_name(str(pick["model_id"])),
        why=pick["reason"],
        limits=[line.replace("ug/m3", S.UNIT) for line in record["limitations"]],
    )  # fmt: skip
